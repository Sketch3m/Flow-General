"""
delta.py - our own operation log: every event, stable identity, state as a fold.

The pattern DeltaDB (Zed, 2026) made famous, sized for this repo:

    every operation   append-only JSONL, one line per event, never rewritten
    stable identity   ULID per event: time-sortable, unique without a server
    lineage           each event carries sha256 of the raw previous line, so
                      tampering or reordering is detectable (verify())
    state is a fold   fold()/state_at() reconstruct any past state; nothing
                      overwrites anything, edits append

Why not a base: Zed's DeltaDB is closed (waitlist), delta-db/deltadb is an
unrelated JS document database, the eventsourcing framework is heavier than
the tool, and the closest open concept (Decima, 1 star) is unproven. The core
is 150 lines of stdlib and answers exactly three questions this repo leaves
open: what did a cell say before it was edited, what harness state produced a
trace entry, and what corpus + model produced an experiment's numbers.

Scale note: reads load the whole file - thousands of lines of JSONL, not
millions. If it ever needs more, that is a different store, not this one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

DEFAULT_LOG = Path("solve") / "delta.jsonl"

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32, no I L O U


_last_ms = -1
_last_rand = 0


def _ulid() -> str:
    """48-bit millisecond timestamp + 80 bits, base32.

    Monotonic within a millisecond (same-ms issues increment the random part),
    so ids sort by time even for back-to-back appends. seq remains the
    ordering authority for the file itself.
    """
    global _last_ms, _last_rand
    t = int(time.time() * 1000)
    if t == _last_ms:
        _last_rand = (_last_rand + 1) & ((1 << 80) - 1)
    else:
        _last_ms, _last_rand = t, secrets.randbits(80)
    ts = ""
    x = t
    for _ in range(10):
        ts = _ALPHABET[x & 31] + ts
        x >>= 5
    rnd = ""
    y = _last_rand
    for _ in range(16):
        rnd = _ALPHABET[y & 31] + rnd
        y >>= 5
    return ts + rnd


def _raw_lines(path: Path) -> list[bytes]:
    if not path.exists():
        return []
    data = path.read_bytes()
    return [ln for ln in data.splitlines() if ln.strip()]


def append(kind: str, payload: dict, actor: str = "human", path: Path = DEFAULT_LOG, base: str | list[str] | None = None) -> dict:
    """Append one event as a child of base (default: the current tip).

    base pins the state this event is *about*, which is what lets two agents
    work from the same observation instead of racing for the tail: if the tip
    has moved on, passing the older base creates a fork (two events sharing a
    parent) - legal data, not corruption. base must reference an existing
    event hash, else this is a lie about lineage.
    """
    lines = _raw_lines(path)
    hashes = [hashlib.sha256(ln).hexdigest() for ln in lines]
    if base is None:
        parents = [hashes[-1]] if hashes else []
    else:
        parents = [base] if isinstance(base, str) else list(base)
        missing = [p for p in parents if p not in hashes]
        if missing:
            raise ValueError(f"base not in log: {missing[0][:16]}...")
    seq = (json.loads(lines[-1])["seq"] + 1) if lines else 1
    ev = {
        "id": _ulid(),
        "seq": seq,
        "ts": int(time.time()),
        "kind": kind,
        "actor": actor,
        "payload": payload,
        "parents": parents,
    }
    path.parent.mkdir(exist_ok=True)
    line = json.dumps(ev, sort_keys=True, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return ev


def _parents(ev: dict) -> list[str]:
    """Parent hashes of an event; reads both DAG events and legacy 'prev' lines."""
    if "parents" in ev:
        return list(ev["parents"] or [])
    return [ev["prev"]] if ev.get("prev") else []


def tips(path: Path = DEFAULT_LOG) -> list[str]:
    """Event hashes no event references - the DAG's open ends (forks included).

    File order is a valid topological order for this log: a parent always
    exists before its child is appended, so folds need no re-sorting.
    """
    lines = _raw_lines(path)
    hashes = [hashlib.sha256(ln).hexdigest() for ln in lines]
    referenced = {p for ln in lines for p in _parents(json.loads(ln))}
    return [h for h in hashes if h not in referenced]


def events(path: Path = DEFAULT_LOG, kind: str | None = None) -> list[dict]:
    out = []
    for ln in _raw_lines(path):
        ev = json.loads(ln)
        if kind is None or ev["kind"] == kind:
            out.append(ev)
    return out


def verify(path: Path = DEFAULT_LOG) -> tuple[bool, int, str]:
    """Check lineage: (ok, first bad line number or -1, message).

    Every parent must hash to an *actual earlier line*, and seq must equal file
    position. An interior edit breaks this at the line after it (whose parent
    no longer matches any line); a re-linked rewrite - where the attacker
    fixes every parent - passes this check, which is what verify_checkpoints()
    is for. An edit to the final line still has nothing after it to object.
    """
    lines = _raw_lines(path)
    earlier: set[str] = set()
    for i, ln in enumerate(lines):
        ev = json.loads(ln)
        if ev.get("seq") != i + 1:
            return False, i + 1, f"seq {ev.get('seq')} out of order at line {i + 1}"
        for p in _parents(ev):
            if p not in earlier:
                return False, i + 1, f"parent {p[:16]}... at line {i + 1} matches no earlier line"
        earlier.add(hashlib.sha256(ln).hexdigest())
    return True, -1, "lineage intact"


def _log_sha(lines: list[bytes]) -> str:
    return hashlib.sha256(b"\n".join(lines)).hexdigest()


def checkpoint(path: Path = DEFAULT_LOG) -> dict:
    """Notarize the log as it stands: hash of every line so far + its tips.

    The receipt lives *inside* the log, so rewriting history means rewriting
    every later checkpoint too - which catches re-link attacks verify() misses.
    Against a full local rewrite it raises the bar rather than removing it:
    an external copy (the exported log_sha in git, a ledger, paper) is what
    makes the notary independent. Export it with the last checkpoint.
    """
    lines = _raw_lines(path)
    return append(
        "checkpoint",
        {"lines": len(lines), "log_sha": _log_sha(lines), "tips": tips(path)},
        actor="system",
        path=path,
    )


def verify_checkpoints(path: Path = DEFAULT_LOG) -> tuple[bool, int, str]:
    """Recompute each checkpoint's coverage over the lines that preceded it."""
    lines = _raw_lines(path)
    for i, ln in enumerate(lines):
        ev = json.loads(ln)
        if ev["kind"] != "checkpoint":
            continue
        p = ev["payload"]
        covered = lines[:i]
        if p.get("lines") != len(covered):
            return False, i + 1, f"checkpoint at line {i + 1} covers {p.get('lines')} lines, {len(covered)} precede it"
        if p.get("log_sha") != _log_sha(covered):
            return False, i + 1, f"checkpoint at line {i + 1} does not match the history it covers"
    return True, -1, "checkpoints match history"


def fold(reducer, initial, path: Path = DEFAULT_LOG, kind: str | None = None, upto: int | None = None):
    """State as a fold over events. upto = last seq to include (replay to a point)."""
    state = initial
    for ev in events(path, kind):
        if upto is not None and ev["seq"] > upto:
            break
        state = reducer(state, ev)
    return state


def state_at(reducer, initial, seq: int, path: Path = DEFAULT_LOG, kind: str | None = None):
    """Reconstruct state as of seq - the undo primitive."""
    return fold(reducer, initial, path=path, kind=kind, upto=seq)


# ---------------------------------------------------------------------------
# folds this repo actually uses
# ---------------------------------------------------------------------------


def cell_reducer(state: dict, ev: dict) -> dict:
    """fold_cells reducer: cell_add / cell_edit / sheet_state over a dict of cells.

    cell_edit keeps `previous`, so any past text is one state_at() away instead
    of being destroyed at the moment of editing.
    """
    k, p = ev["kind"], ev["payload"]
    if k == "sheet_state":  # reset / load-papers: a full replacement
        return {c["id"]: dict(c) for c in p.get("cells", [])}
    cid = p.get("id")
    if not cid:
        return state
    if k == "cell_add":
        state[cid] = {**p, "added_by": ev["actor"], "added_at": ev["ts"]}
    elif k == "cell_edit":
        cur = dict(state.get(cid, {"id": cid}))
        cur.setdefault("previous", []).append({"text": cur.get("text", ""), "at": ev["ts"], "by": ev["actor"]})
        cur.update({kk: vv for kk, vv in p.items() if kk != "previous"})
        state[cid] = cur
    return state


def fold_cells(path: Path = DEFAULT_LOG) -> dict[str, dict]:
    """Every cell's current text and view, rebuilt from the log."""
    return fold(cell_reducer, {}, path=path)


def harness_reducer(state: dict, ev: dict) -> dict:
    """Kept harness edits only, in order - the harness as of the log's end."""
    if ev["kind"] == "harness_edit" and ev["payload"].get("kept"):
        field = ev["payload"].get("field")
        if field:
            state[field] = ev["payload"].get("value")
    return state


def fold_harness(path: Path = DEFAULT_LOG) -> dict:
    return fold(harness_reducer, {}, path=path)


def context() -> dict:
    """Provenance for an experiment: corpus files with hashes, harness, model.

    This is the "message and the edit side by side" half - a result recorded
    without this is a number with no parentage.
    """
    papers = []
    for p in sorted(Path("papers").glob("*.md")):
        papers.append({"file": p.name, "sha": hashlib.sha256(p.read_bytes()).hexdigest()[:16]})
    try:
        import harness

        harness_state = dict(harness.HARNESS)
    except Exception:
        harness_state = {}
    try:
        import localmodels

        model = localmodels.available()
    except Exception:
        model = {}
    return {"papers": papers, "harness": harness_state, "models": model}


def record_context(label: str, path: Path = DEFAULT_LOG) -> dict:
    """One experiment/observation event carrying the full context snapshot."""
    return append("experiment", {"label": label, "context": context()}, actor="system", path=path)
