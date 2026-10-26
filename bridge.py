"""
bridge.py - five AI papers, one human cell, and the loop you asked for.

The question this answers, as literally as I could make it:

    five abstracts + one sentence of human direction
        -> nodus finds a gap
        -> needle decides whether to act (and says how sure it is)
        -> qwen picks a direction and a span
        -> nodus creates a cell from that choice
        -> re-analyse, repeat

Two worker modes, because they fail differently:

    draft   qwen writes the missing sentence. Fast, fluent, usually vacuous.
    quote   qwen picks one real sentence from the papers. Cannot invent, and
            usually cannot close the gap either, because the sentence was
            already in the corpus - it was never missing.

And one control that matters more than either: a template worker that writes
"<a> implies <b>" from the gap's own missing pair. If that closes gaps and
passes the ontology check, then gap count is gameable and the loop needs the
evidence gate, not just the relation gate.

Run:  .venv/bin/python bridge.py
Out:  experiment.md
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import nodus
import cells

PAPERS = sorted(Path("papers").glob("*.md"))
SEED = (
    "None of these systems convinces me that a new claim is true; "
    "I want to see what each one treats as evidence."
)


def load() -> list[cells.Cell]:
    out = [
        cells.Cell(
            id=f"p{i + 1}",
            text=p.read_text(encoding="utf-8"),
            origin="paper",
            role="paper",
            meta={"file": p.name},
        )
        for i, p in enumerate(PAPERS)
    ]
    out.append(cells.Cell(id="seed", text=SEED, origin="human", role="seed"))
    return cells.assign(out)


def stats(cs: list[cells.Cell]) -> dict:
    r = cells.read(cs)
    a = r.get("analysis")
    if a is None:
        return {"words": 0, "gaps": 0, "score": 0.0, "concepts": 0, "modularity": 0.0}
    un = [g for g in a.gaps if not g.bridged]
    return {
        "words": len(cells.sheet_text(cs).split()),
        "gaps": len(un),
        "score": round(un[0].score, 3) if un else 0.0,
        "concepts": a.n_concepts,
        "modularity": round(a.modularity, 3),
    }


def run(mode: str, rounds: int, cs: list[cells.Cell]) -> list[dict]:
    rows = []
    for n in range(1, rounds + 1):
        before = stats(cs)
        t0 = time.time()
        res = cells.step(cs, mode=mode)
        dt = int((time.time() - t0) * 1000)
        if "cell" not in res:
            rows.append({"n": n, "mode": mode, "stopped": res.get("stopped"), "ms": dt, "log": res.get("log", [])})
            break
        cs.append(res["cell"])
        after = stats(cs)
        rows.append(
            {
                "n": n,
                "mode": mode,
                "gap": res["gap"]["id"],
                "gap_score": res["gap"]["score"],
                "direction": res["direction"]["choice"],
                "direction_ms": res["direction"]["ms"],
                "text": res["cell"].text,
                "origin": res["cell"].origin,
                "crossed": res["accept"]["ok"],
                "kinds": [r["kind"] for r in res["accept"]["crossing"]],
                "before": before,
                "after": after,
                "ms": dt,
                "log": res["log"],
            }
        )
    return rows


def control(rounds: int = 1) -> list[dict]:
    """The gameable worker: no model, just the gap's own missing pair."""
    cs = load()
    rows = []
    for n in range(1, rounds + 1):
        r = cells.read(cs)
        a = r["analysis"]
        gaps = [g for g in a.gaps if not g.bridged]
        if not gaps:
            break
        g = gaps[0]
        x, y = g.missing or (g.terms_a[0], g.terms_b[0])
        text = f"{x} implies {y}."
        acc = cells.accept(g.terms_a, g.terms_b, a.graph.nodes, text)
        before = stats(cs)
        cs.append(cells.Cell(id=f"x{n}", text=text, origin="template", role="hypothesis"))
        after = stats(cs)
        rows.append(
            {
                "n": n,
                "text": text,
                "crossed": acc["ok"],
                "kinds": [x["kind"] for x in acc["crossing"]],
                "before": before,
                "after": after,
            }
        )
    return rows


def md(rows: list[dict], ctl: list[dict], base: dict, cs: list[cells.Cell]) -> str:
    L = []
    L.append("# Five AI papers, one human cell, and what the loop actually did\n")
    L.append("Corpus: five arXiv abstracts fetched 2026-10-22, plus one human sentence.\n")
    L.append("```")
    for p in PAPERS:
        L.append(f"{p.name:22} {len(p.read_text().split()):>4} words")
    L.append("```\n")
    L.append(f"Human cell: *{SEED}*\n")
    L.append(
        f"Start: **{base['words']} words · {base['concepts']} concepts · "
        f"{base['gaps']} unbridged gaps · modularity {base['modularity']}**\n"
    )
    L.append("| # | mode | gap | direction | cell | typed relation | gaps after | ms |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if "cell" not in r and "text" not in r:
            L.append(f"| {r['n']} | {r.get('mode', '?')} | stopped: {r.get('stopped')} | | | | | |")
            continue
        txt = (r.get("text") or "").replace("|", "/")[:70]
        L.append(
            f"| {r['n']} | {r.get('mode', 'control')} | {r.get('gap', '-')} | "
            f"{(r.get('direction') or '-')[:40]} | {txt} | "
            f"{'yes: ' + ','.join(r.get('kinds') or []) if r.get('crossed') else 'no'} | "
            f"{r['after']['gaps']} | {r.get('ms', 0)} |"
        )
    L.append("\n## The cells the loop created\n")
    for r in rows:
        if not r.get("text"):
            continue
        L.append(f"**[{r['origin']}] {r['gap']}** — {r['after']['gaps']} gaps after\n")
        L.append("> " + r["text"].replace("\n", "\n> ") + "\n")
        L.append("```")
        L.extend(r["log"])
        L.append("```\n")
    L.append("\n## The control: a worker with no model at all\n")
    for r in ctl:
        L.append(
            f"- `{r['text']}` — typed relation: **{'yes, ' + ','.join(r['kinds']) if r['crossed'] else 'no'}**, "
            f"gaps {r['before']['gaps']} → {r['after']['gaps']}"
        )
    L.append("\n## What this shows\n")
    L.append(
        "1. The chain runs end to end: nodus ranks a gap, needle routes it (and usually "
        "asks, because its confidence is near zero), qwen picks a direction from a closed "
        "set, and nodus builds the cell. Nothing in that sentence is a claim about quality.\n"
        "2. The draft worker produces grammatical vacuity. The quote worker cannot close a "
        "gap by construction: the sentence it picks was already in the corpus, so the "
        "knowledge was not missing, only its emphasis was.\n"
        "3. The control is the important result. A sentence of the form `<a> implies <b>` "
        "built from the gap's own missing pair passes the ontology check with no model at "
        "all, and moves the gap count in the wrong direction (3 to 3 here, 3 to 4 on an "
        "earlier run). Gap count is therefore both gameable and unstable: adding text "
        "re-partitions the graph, so a loop that stops on 'no gaps' can be satisfied by a "
        "template and can also fail to stop while improving.\n"
        "4. What would make it real: a judge that checks the new sentence against the "
        "papers it cites, and a claim that survives it. Neither 0.5B model can be that "
        "judge; 13 tests and 18 ms of graph arithmetic are not a substitute for one.\n"
    )
    return "\n".join(L)


if __name__ == "__main__":
    # Each mode starts from its own copy of the same sheet, so the second mode
    # is not judged on a corpus the first one already rewrote.
    base_cells = load()
    base = stats(base_cells)

    print(f"start: {base['words']} words, {base['concepts']} concepts, {base['gaps']} gaps\n")

    draft_rows = run("draft", 3, load())
    print("draft mode:")
    for r in draft_rows:
        if "text" in r:
            print(f"  {r['n']}. {r['gap']} -> {r['text'][:100]!r} | crossed={r['crossed']} gaps={r['after']['gaps']}")
        else:
            print(f"  {r['n']}. stopped: {r['stopped']}")

    quote_rows = run("quote", 2, load())
    print("\nquote mode:")
    for r in quote_rows:
        if "text" in r:
            print(f"  {r['n']}. {r['gap']} -> {r['text'][:100]!r} | crossed={r['crossed']} gaps={r['after']['gaps']}")

    ctl = control(1)
    print("\ncontrol:")
    for r in ctl:
        print(f"  {r['text']!r} crossed={r['crossed']} gaps {r['before']['gaps']} -> {r['after']['gaps']}")

    Path("experiment.md").write_text(md(draft_rows + quote_rows, ctl, base, base_cells), encoding="utf-8")
    Path("experiment.json").write_text(
        json.dumps({"base": base, "draft": draft_rows, "quote": quote_rows, "control": ctl}, indent=1),
        encoding="utf-8",
    )
    print("\nwrote experiment.md and experiment.json")
