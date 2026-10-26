"""
worker.py - run the gap queue outside the notebook.

    python worker.py --once     take one job, run it, exit
    python worker.py            drain the queue, then exit
    python worker.py --watch    keep polling when the queue is empty

The worker owns no state. It folds the sheet out of `solve/delta.jsonl` (the
snapshot `jobs.enqueue` wrote when the job was opened), runs `cells.step`
against the gap the job names, and appends the result: a proposed cell to the
delta log, a verdict to the job log. The notebook is then just another reader of
the same two files, which is why a proposal can arrive while nobody is looking
at a button.

Exit codes are the honest part:
    0  ran something, or nothing to run
    1  no sheet in the log, so nothing was attempted
    2  a job failed; the error is in the job log
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cells
import delta
import jobs
import plan


def sheet() -> list[cells.Cell]:
    """The cells a worker is allowed to see: whatever the log says they are."""
    folded = delta.fold_cells()
    return [cells.Cell.from_dict(d) for d in folded.values() if d.get("text")]


def run_one(worker: str = "worker", path: Path = jobs.DEFAULT) -> dict | None:
    """Claim and run a single job. Returns the job, or None if the queue was empty."""
    job = jobs.claim(worker, path)
    if job is None:
        return None
    cs = sheet()
    if not cs:
        jobs.fail(job["id"], "no sheet in the delta log: open the notebook once, or enqueue with cells", path)
        return job
    t0 = time.time()
    try:
        res = cells.step(
            cs,
            mode="draft",
            use_needle=True,
            use_qwen=True,
            target=job["gap"],
            # The citation verdict is computed and recorded either way; blocking
            # is left off so a draft-mode proposal still reaches the page with
            # its verdict attached. With the gate on, every draft is blocked
            # (drafts quote nothing), and the queue would produce nothing to
            # review - which hides the finding instead of showing it.
            truth_gate=False,
            sink=lambda k, p, a: delta.append(k, p, actor=a),
        )
    except Exception as e:  # a worker that dies leaves the queue stuck; record and move on
        jobs.fail(job["id"], f"{type(e).__name__}: {e}", path)
        return job

    ms = int((time.time() - t0) * 1000)
    cell = res.get("cell")
    log = list(res.get("log") or []) + [f"worker  {ms} ms"]
    if cell is not None:
        delta.append("cell_add", cell.to_dict(), actor="qwen")
        acc = res.get("accept") or {}
        jobs.finish(
            job["id"],
            cell=cell.to_dict(),
            crossed=bool(acc.get("ok")),
            grounded=bool(acc.get("grounded")),
            ms=ms,
            log=log,
            path=path,
        )
    else:
        jobs.finish(
            job["id"],
            crossed=False,
            grounded=False,
            ms=ms,
            stopped=res.get("stopped", "nothing produced"),
            log=log,
            path=path,
        )
    return job


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run queued nodus gap jobs")
    ap.add_argument("--once", action="store_true", help="run at most one job")
    ap.add_argument("--watch", action="store_true", help="keep polling when the queue is empty")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between polls in --watch")
    ap.add_argument("--max", type=int, default=plan.MAX_ATTEMPTS, help="stop after this many jobs (default: plan.py's attempt cap)")
    args = ap.parse_args(argv)

    if not sheet():
        print("no sheet in solve/delta.jsonl - open the notebook once, or enqueue with cells", file=sys.stderr)
        return 1

    ran = 0
    failed = 0
    while ran < args.max:
        job = run_one()
        if job is None:
            if args.once or not args.watch:
                break
            time.sleep(args.interval)
            continue
        ran += 1
        st = jobs.state().get(job["id"], {})
        failed += 1 if st.get("status") == "failed" else 0
        print(
            f"{job['id']:<18} {st.get('status', '?'):<8} crossed={st.get('crossed')} "
            f"{st.get('ms', 0)} ms {st.get('stopped') or ''}"
        )
        if args.once:
            break
    if ran == 0:
        print("queue empty")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
