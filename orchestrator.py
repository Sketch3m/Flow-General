"""
orchestrator.py - the seam between a document and a supervisor.

The human never sees this file. The page shows prose, a gist, a citation chip.
Whatever does the work — Needle as a router, Claude Code as a worker, a queue of
sub-agents — gets something else: one objective, the messages it is allowed to
use, what is being withheld, and the schema its answer has to satisfy.

Two properties matter and both are tested:

1. **It is derived from the ledger, not from the page.** Folding or closing a
   cell changes the rendering and nothing else. `Dialog.context()` reads the
   `.ipynb`; a closed cell is still in it, still eligible, still compressible.
2. **It cannot accept an unsourced answer.** The schema demands span ids, and
   `decision.Record` already rejects a claim with no source. The loop closes
   without inventing an agent framework.

No model is called here. This is the handoff, not the worker.
"""

from __future__ import annotations

import nodus

SCHEMA = {
    "claims": [
        {
            "text": "one claim, one sentence",
            "span_ids": ["s0"],
            "source": "https://…",
            "quote": "the exact words relied on",
        }
    ],
    "decision": "what to do, not what was learned",
    "confidence": "0..1",
    "next_evidence": ["what would change the answer"],
}

RULES = (
    "every claim needs a span id that resolves in the ledger",
    "quote the span; never paraphrase the text you cite",
    "span ids are minted by the segmenter, not by you - invent one and it is rejected",
    "if the context does not answer the objective, return claims: [] and say so",
)


def task_packet(
    gap: nodus.Gap,
    dlg,
    budget_chars: int = 700,
    ledger: str = "dialog.ipynb",
    layers: nodus.Layers | None = None,
) -> dict:
    """One gap -> one bounded task. Deterministic; JSON-serialisable."""
    prompt = next((m for m in reversed(dlg.messages) if m.type == "prompt"), None)
    ctx = dlg.context(
        prompt.id if prompt else None,
        budget_chars=budget_chars,
        focus=(gap.terms_a[:8], gap.terms_b[:8]),
    )
    withheld = list(ctx.dropped)
    by_id = {m.id: m for m in dlg.messages}
    return {
        "objective": gap.question,
        "why": {
            "score": round(gap.score, 3),
            "shared_edges": gap.cross_weight,
            "porosity": gap.porosity,
            "already_bridged": gap.bridged,
            "missing_link": list(gap.missing) if gap.missing else None,
            "expected_but_absent_z": round(gap.surprise, 2),
            "resource_allocation": round(gap.ra, 3),
            "knn_tension": round(gap.tension, 3),
            "positional_offset": round(gap.offset, 3),
            "hops": gap.distance,
        },
        # The human layer is not a summary of this packet, and this packet is not
        # a summary of the page: they are two projections of one graph. The
        # regions are here so a worker can say which readable part of the page
        # its answer belongs to, and the cluster ids are here so that claim can
        # be checked against the resolution the numbers were computed at.
        "structure": _structure(gap, layers),
        "sides": {"a": gap.terms_a[:6], "b": gap.terms_b[:6]},
        "context": [
            {
                "id": s.id,
                "type": s.type,
                "mode": s.mode,  # full | gist | pointer
                "chars": len(s.text),
                "text": s.text,
            }
            for s in ctx.slots
        ],
        "withheld": {
            "messages": withheld,
            "chars": sum(len(by_id[i].body) for i in withheld if i in by_id),
            "note": "retrievable in full from the ledger; ask for an id to expand it",
        },
        "ledger": ledger,
        "must_return": SCHEMA,
        "rules": RULES,
        "budget": {"chars": budget_chars, "used": ctx.chars},
    }


def _structure(gap: nodus.Gap, layers: nodus.Layers | None) -> dict:
    if layers is None:
        return {"regions": [], "note": "no layer split supplied"}
    inside = [
        r
        for r in layers.nesting()
        if set(r["clusters"]) & {gap.a, gap.b}
    ]
    return {
        "gap_at": "machine resolution",
        "clusters": [gap.a, gap.b],
        "regions": inside,
        "region_count": len(layers.human.clusters),
        "cluster_count": len(layers.machine.clusters),
        "note": "regions are merges of clusters; a region id outside this list is a misread",
    }


def queue(layers: nodus.Layers, dlg, budget_chars: int = 700, k: int = 3) -> list[dict]:
    """The ranked handoff: one bounded packet per gap, holes before seams.

    This is a queue, not a dispatcher. Whoever runs the workers decides whether
    to take the top item, all of them, or none - which is the whole reason the
    human layer keeps a way to say no.
    """
    gaps = [g for g in layers.machine.gaps if not g.bridged]
    if len(gaps) < k:
        gaps += [g for g in layers.machine.gaps if g.bridged][: k - len(gaps)]
    return [
        {
            "task": f"bridge-{i + 1}",
            "packet": task_packet(g, dlg, budget_chars=budget_chars, layers=layers),
        }
        for i, g in enumerate(gaps[:k])
    ]
