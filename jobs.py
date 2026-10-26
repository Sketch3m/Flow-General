"""
jobs.py - the gap queue: agents work somewhere other than the callback.

Everything in this repo so far runs inside a button handler. marimo state lives
in the kernel, so a second process cannot touch it - which means a background
agent cannot be "a thread that updates the page". It has to be a log the page
folds, and this repo already has one (`delta.py`). So the queue is:

    vault.py  enqueue(gap)          -> sheet_state + job_open in solve/jobs.jsonl
    worker.py claim()               -> job_start, then cells.step(target=gap)
              finish(proposed cell) -> cell_add in delta.jsonl + job_done here
    vault.py  state() on a refresh  -> the proposal appears, unattended

The caps come from `plan.py`, not from here, because they were argued there:
at most MAX_SUBAGENTS lanes in flight and MAX_ATTEMPTS batches ever. A queue
that can grow without the budget is the thing plan.py exists to prevent, so
enqueue() refuses rather than trusting the caller.

What this is not: a task runner with retries, priorities, or a leader election.
One lock file guards claim() so a second worker does not take the same job; if
two workers start in the same millisecond one of them loses and returns None.
The failure mode is a job that stays open, never a job that runs twice.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

import plan

DEFAULT = Path("solve") / "jobs.jsonl"
LOCK = Path("solve") / "jobs.lock"
STALE_LOCK_S = 30.0


def _read(path: Path = DEFAULT) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # a half-written line from a killed worker is worth skipping,
                # not worth crashing the page over
                continue
    return out


def _append(kind: str, payload: dict, path: Path = DEFAULT) -> dict:
    path.parent.mkdir(exist_ok=True)
    seq = len(_read(path)) + 1
    ev = {"seq": seq, "ts": int(time.time()), "kind": kind, "payload": payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n")
    return ev


@contextmanager
def _lock(path: Path = LOCK, wait: float = 2.0):
    """One worker at a time. Yields False if the lock could not be taken."""
    path.parent.mkdir(exist_ok=True)
    got = False
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            got = True
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > STALE_LOCK_S:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    try:
        yield got
    finally:
        if got:
            path.unlink(missing_ok=True)


def state(path: Path = DEFAULT) -> dict[str, dict]:
    """Every job, as of the end of the log. Status is a fold, never a field."""
    out: dict[str, dict] = {}
    for ev in _read(path):
        p = ev.get("payload") or {}
        jid = p.get("id")
        if not jid:
            continue
        cur = out.setdefault(jid, {"id": jid, "status": "open", "opened": ev["ts"]})
        kind = ev["kind"]
        if kind == "job_open":
            cur.update(
                gap=p.get("gap"),
                score=p.get("score"),
                term_a=p.get("term_a"),
                term_b=p.get("term_b"),
                ask=p.get("ask", ""),
                status="open",
            )
        elif kind == "job_start":
            cur.update(status="running", worker=p.get("worker"), started=ev["ts"])
        elif kind == "job_done":
            cur.update(
                status="done",
                done=ev["ts"],
                crossed=bool(p.get("crossed")),
                grounded=bool(p.get("grounded")),
                stopped=p.get("stopped"),
                cell=p.get("cell"),
                log=list(p.get("log") or []),
                ms=p.get("ms", 0),
            )
        elif kind == "job_fail":
            cur.update(status="failed", done=ev["ts"], error=p.get("error"))
        elif kind == "job_stop":
            cur.update(status="stopped", done=ev["ts"], by=p.get("by", "human"))
    return out


def stats(path: Path = DEFAULT) -> dict:
    evs = _read(path)
    jobs = state(path)
    counts: dict[str, int] = {}
    for j in jobs.values():
        counts[j["status"]] = counts.get(j["status"], 0) + 1
    return {
        "jobs": jobs,
        "counts": counts,
        "events": len(evs),
        "last_ts": evs[-1]["ts"] if evs else 0,
        "attempts": len([j for j in jobs.values() if j.get("started")]),
        "cap_attempts": plan.MAX_ATTEMPTS,
        "cap_lanes": plan.MAX_SUBAGENTS,
        "path": str(path),
    }


def can_enqueue(path: Path = DEFAULT) -> tuple[bool, str]:
    """May another lane start? The caps are plan.py's, not this module's."""
    jobs = state(path)
    live = [j for j in jobs.values() if j["status"] in ("open", "running")]
    if len(live) >= plan.MAX_SUBAGENTS:
        return False, f"{len(live)} lanes already in flight (cap {plan.MAX_SUBAGENTS})"
    attempts = len([j for j in jobs.values() if j.get("started")])
    if attempts >= plan.MAX_ATTEMPTS:
        return False, f"attempt cap reached ({attempts}/{plan.MAX_ATTEMPTS})"
    return True, "ok"


def enqueue(
    gap,
    *,
    cells: list | None = None,
    ask: str = "",
    actor: str = "human",
    path: Path = DEFAULT,
) -> dict:
    """Queue one gap. Parents the job to the sheet it was opened against.

    The sheet snapshot is written first, as `sheet_state` in the delta log, so a
    worker in another process can rebuild exactly the cells the human was
    looking at when they queued this - a job whose parentage is unknown is a
    result nobody can reproduce.
    """
    gap_id = gap.get("id") if isinstance(gap, dict) else getattr(gap, "id", None)
    if not gap_id:
        return {"ok": False, "reason": "gap has no id", "job": None}
    jobs = state(path)
    for j in jobs.values():
        if j.get("gap") == gap_id and j["status"] in ("open", "running"):
            return {"ok": False, "reason": f"{gap_id} is already queued ({j['status']})", "job": j}
    ok, why = can_enqueue(path)
    if not ok:
        return {"ok": False, "reason": why, "job": None}

    if cells:
        import delta

        delta.append("sheet_state", {"cells": [c.to_dict() if hasattr(c, "to_dict") else c for c in cells]}, actor=actor)

    def field(name, default=None):
        if isinstance(gap, dict):
            return gap.get(name, default)
        return getattr(gap, name, default)

    payload = {
        "id": gap_id,
        "gap": gap_id,
        "score": round(float(field("score", 0.0) or 0.0), 3),
        "term_a": (field("terms_a") or [""])[0] if field("terms_a") else "",
        "term_b": (field("terms_b") or [""])[0] if field("terms_b") else "",
        "ask": ask,
    }
    _append("job_open", payload, path)
    return {"ok": True, "reason": "queued", "job": state(path)[gap_id]}


def claim(worker: str = "worker", path: Path = DEFAULT) -> dict | None:
    """Take the oldest open job. None means there is nothing to do (or the lock is held)."""
    with _lock(wait=2.0) as got:
        if not got:
            return None
        for job in state(path).values():
            if job["status"] != "open":
                continue
            _append("job_start", {"id": job["id"], "worker": worker}, path)
            job = dict(job)
            job.update(status="running", worker=worker, started=int(time.time()))
            return job
    return None


def finish(
    job_id: str,
    *,
    cell: dict | None = None,
    crossed: bool = False,
    grounded: bool = False,
    ms: int = 0,
    stopped: str | None = None,
    log: list[str] | None = None,
    path: Path = DEFAULT,
) -> dict:
    return _append(
        "job_done",
        {
            "id": job_id,
            "cell": cell,
            "crossed": crossed,
            "grounded": grounded,
            "ms": ms,
            "stopped": stopped,
            "log": log or [],
        },
        path,
    )


def fail(job_id: str, error: str, path: Path = DEFAULT) -> dict:
    return _append("job_fail", {"id": job_id, "error": str(error)[:400]}, path)


def cancel_open(by: str = "human", path: Path = DEFAULT) -> int:
    """Stop everything not yet started. A running job in another process is
    left alone - this cannot kill it, and pretending otherwise would be worse
    than the honest 'stop what has not begun'."""
    stopped = 0
    for job in state(path).values():
        if job["status"] == "open":
            _append("job_stop", {"id": job["id"], "by": by}, path)
            stopped += 1
    return stopped
