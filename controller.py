"""
controller.py - the loop you asked for, with the stopping rule written down.

The proposal was: Needle stays on, watches for gaps, drives a worker, and stops
when the document is stable. The loop is easy; the two hard parts are *when to
stop* and *what counts as closing a gap*, and both are decided here rather than
by the model.

Measured on the sample document, each bridging sentence removes about one gap:

    step 0   4 unbridged gaps
    step 1   3
    step 2   0

That convergence is real and it is also a warning. Any sentence that contains
both sides' words creates the co-occurrence edge, so the metric is satisfiable
by keyword stuffing. A loop optimising gap count will learn to write "window and
citation are related" and stop. So acceptance does not test the graph - it tests
the **ontology**: the added text must state a typed relation (causal, is-a,
part-of, dependency, evidential) whose two ends sit on opposite sides of the
divide. Stuffing words is not a relation; claiming one is.

Stopping rules, in order:

    no gaps left            nothing to do
    policy says confirm     the decision is the human's
    policy says refuse      the card does not support the request
    worker returns nothing  no proposal, so nothing to accept
    rejected                proposal does not state a crossing relation
    stable                  same gaps, same modularity, within epsilon

No model is required: the policy is a callable, so today's default is
deterministic and Needle can be dropped in behind a confidence threshold without
touching the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import nodus
import ontology


@dataclass
class Decision:
    action: str  # act | confirm | refuse
    reason: str
    confidence: float = 1.0
    gap_id: str | None = None


@dataclass
class Step:
    n: int
    gap: str | None
    action: str
    accepted: bool
    why: str
    gaps_before: int
    gaps_after: int
    cohesion: float
    relation: dict | None = None


@dataclass
class Run:
    steps: list[Step] = field(default_factory=list)
    stopped: str = ""
    text: str = ""

    def table(self) -> str:
        rows = [f"{'#':>2} {'gaps':>5} {'action':>8} {'ok':>3}  why"]
        for s in self.steps:
            rows.append(
                f"{s.n:>2} {s.gaps_before:>5} {s.action:>8} {('yes' if s.accepted else 'no'):>3}  {s.why[:64]}"
            )
        rows.append(f"stopped: {self.stopped}")
        return "\n".join(rows)


def unbridged(a: nodus.Analysis) -> list[nodus.Gap]:
    return [g for g in a.gaps if not g.bridged]


def deterministic_policy(a: nodus.Analysis, gaps: list[nodus.Gap], spent: int) -> Decision:
    """The default: take the highest-scoring hole, unless it is barely a hole.

    The threshold is the value of the next best use of the writer's attention,
    not a claim about truth. A gap below it is not worth interrupting anyone for,
    which is also the honest reason to stop.
    """
    if not gaps:
        return Decision("refuse", "no unbridged gaps", gap_id=None)
    top = gaps[0]
    if top.score < 0.12:
        return Decision("refuse", f"top gap {top.id} scores {top.score:.2f}, under the floor", gap_id=top.id)
    if len(gaps) > 1 and gaps[1].score > top.score * 0.9:
        return Decision(
            "confirm",
            f"{gaps[0].id} and {gaps[1].id} are within 10% - the choice is the writer's",
            gap_id=top.id,
        )
    return Decision("act", f"{top.id} leads by {top.score - gaps[1].score:.2f}" if len(gaps) > 1 else "only gap", gap_id=top.id)


def needle_policy(threshold: float = 0.5) -> Callable:
    """Optional: let Needle route act / confirm / refuse, with a hard threshold.

    Kept behind this wrapper for a reason. In bench runs the three-way routing
    chose "act" for an off-topic request and for a claim with no source, so the
    confidence gate is doing more work than the model: below `threshold`, the
    loop treats the answer as no answer and falls back to asking the human.
    """
    import localmodels

    tools = [
        {
            "name": "act",
            "description": "Proceed with the next step now; the card names one gap and enough evidence.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "confirm",
            "description": "Ask the human before doing anything: two gaps compete or a field is missing.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "refuse",
            "description": "Do not act and do not ask: nothing in the card supports the request.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]

    def policy(a: nodus.Analysis, gaps: list[nodus.Gap], spent: int) -> Decision:
        if not gaps:
            return Decision("refuse", "no unbridged gaps")
        top = gaps[0]
        card = localmodels.card_text(
            "document",
            f"{top.terms_a[0]} to {top.terms_b[0]}",
            700,
            [],
            f"next step for gap {top.id} scoring {top.score:.2f}",
        )
        r = localmodels.route(card, tools=tools)
        name = (r["call"] or {}).get("name")
        if not name or r["confidence"] < threshold:
            return Decision("confirm", f"needle was not confident ({r['confidence']:.2f})", r["confidence"], top.id)
        return Decision(name, r["reasoning"][:160] or "needle", r["confidence"], top.id)

    return policy


def crossing_proposal(proposal: str, gap: nodus.Gap, a: nodus.Analysis) -> ontology.Relation | None:
    """The acceptance test: does the new text *state* a link across the divide?

    Only the proposal is tested, not the whole document, so a sentence that was
    already there cannot be credited to the worker twice.
    """
    rels = ontology.relations(proposal, set(a.graph.nodes))
    cross = ontology.crossings(rels, set(gap.terms_a), set(gap.terms_b))
    return cross[0] if cross else None


def run(
    text: str,
    worker: Callable[[nodus.Gap, nodus.Analysis], str | None],
    policy: Callable = deterministic_policy,
    max_steps: int = 6,
    tau: float = 0.06,
    floor: float = 0.02,
) -> Run:
    """One pass of the loop. Never writes to disk; the caller decides that."""
    out = Run(text=text)
    spent = 0
    prev_gaps: set[str] = set()

    for n in range(1, max_steps + 1):
        a = nodus.analyse(text)
        gaps = unbridged(a)
        before = len(gaps)
        if not gaps:
            out.stopped = "no unbridged gaps"
            break

        d = policy(a, gaps, spent)
        if d.action != "act":
            out.steps.append(Step(n, d.gap_id, d.action, False, d.reason, before, before, a.modularity))
            out.stopped = f"policy: {d.action}"
            break

        gap = next((g for g in gaps if g.id == d.gap_id), gaps[0])
        proposal = worker(gap, a)
        if not proposal:
            out.steps.append(Step(n, gap.id, "act", False, "worker produced nothing", before, before, a.modularity))
            out.stopped = "worker empty"
            break

        after_text = text.rstrip() + "\n\n" + proposal.strip() + "\n"
        a2 = nodus.analyse(after_text)
        rel = crossing_proposal(proposal, gap, a2)
        gaps_after = len(unbridged(a2))

        if rel is None:
            out.steps.append(
                Step(n, gap.id, "act", False, "no typed relation crosses - rejected", before, gaps_after, a2.modularity)
            )
            out.stopped = "rejected"
            break

        text = after_text
        spent += len(proposal)
        ids = {g.id for g in unbridged(a2)}
        out.steps.append(
            Step(
                n,
                gap.id,
                "act",
                True,
                f"{rel.kind}: {rel.subject} -> {rel.object}",
                before,
                gaps_after,
                a2.modularity,
                rel.to_dict(),
            )
        )

        if ids == prev_gaps and abs(a2.modularity - a.modularity) < tau:
            out.stopped = "stable"
            break
        prev_gaps = ids
        if a2.modularity < floor and gaps_after == 0:
            out.stopped = "no gaps"
            break
    else:
        out.stopped = "step budget"

    out.text = text
    return out


def _stuffer(gap: nodus.Gap, a: nodus.Analysis) -> str:
    """The failure mode: both sides named, nothing claimed."""
    return (
        f"Both {gap.terms_a[0]} and {gap.terms_b[0]} matter here, "
        f"and {gap.terms_a[0]} is connected to {gap.terms_b[0]}."
    )


def _claimer(gap: nodus.Gap, a: nodus.Analysis) -> str:
    """A sentence that states a relation across the divide."""
    return (
        f"{gap.terms_a[0]} requires {gap.terms_b[0]}: without it, the claim has no "
        f"source to trace back to and cannot be checked."
    )


if __name__ == "__main__":
    import pathlib

    sample = (pathlib.Path(__file__).with_name("sample.md")).read_text()
    for name, worker in (("keyword stuffing", _stuffer), ("states a relation", _claimer)):
        print(f"== {name}")
        r = run(sample, worker)
        print(r.table())
        print()
