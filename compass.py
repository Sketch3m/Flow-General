"""
compass.py - what to do next, without pretending to know.

A quest compass that always points at "the objective" is criticised for
displacing exploration, and a compass bearing on an abstract graph would be a
lie: there is no north. What transfers from wayfinding HUDs is **clarity and
optionality** - a small ranked set, each item tied to a real thing in the work,
with a truthful distance ("2 links", "no source", "1,340 chars held back") and a
stated reason. Nothing here is urgent, and nothing claims to be the only route.

Every move is derived deterministically from the graph and the dialog. There is
no model guessing at intent.
"""

from __future__ import annotations

from dataclasses import dataclass

import gist
import nodus


@dataclass
class Move:
    kind: str  # bridge | cite | expand
    label: str  # the action, imperative
    detail: str  # why this is being suggested
    distance: str  # truthful, defined, never a bearing
    target: str  # a gap id or a message id
    weight: float = 0.5


def moves(
    a: nodus.Analysis,
    dlg,
    gap: nodus.Gap | None = None,
    records: dict | None = None,
    limit: int = 4,
) -> list[Move]:
    out: list[Move] = []

    # 1. bridges - the ranked gaps, stated with the numbers that ranked them.
    # Every number below describes *one* absent pair, named on the card. A card
    # that quotes a cluster's cross-weight next to a different pair's surprise
    # is three true statements pretending to be one piece of evidence.
    heads = [g for g in a.gaps if not g.bridged][:3]
    if len(heads) < 3:
        heads += [g for g in a.gaps if g.bridged][: 3 - len(heads)]
    for g in heads:
        hops = f"{g.distance} links" if g.distance is not None else "disconnected"
        missing = f"{g.missing[0]} \u2192 {g.missing[1]}" if g.missing else "no absent pair"
        out.append(
            Move(
                kind="bridge",
                label=f"bridge {g.terms_a[0]} \u2194 {g.terms_b[0]}",
                detail=(
                    f"missing {missing} · absent {g.surprise:.2f}\u03c3 · "
                    f"RA {g.ra:.2f} · tension {g.tension:.2f}"
                ),
                distance=(
                    f"{hops} · cross {g.cross_weight} · porosity {g.porosity:.2f}"
                    + (" · already bridged" if g.bridged else "")
                ),
                target=g.id,
                weight=(1.0 + g.score) * (0.4 if g.bridged else 1.0),
            )
        )

    # 2. the one thing a research document always needs and never has
    if records:
        bare = [c for r in records.values() for c in r.claims if not c.source.strip()]
        if bare:
            out.append(
                Move(
                    kind="cite",
                    label=f"cite {len(bare)} claim{'s' if len(bare) > 1 else ''}",
                    detail="a claim without a source is a hypothesis wearing a citation's clothes",
                    distance="no source",
                    target="",
                    weight=0.9,
                )
            )

    # 3. what the page is holding back, and how much
    focus = ((gap.terms_a[:8], gap.terms_b[:8]) if gap else ([], []))
    for m in dlg.of_type("prompt"):
        if m.skipped or len(m.reply) < 400:
            continue
        g = gist.gist(m.reply, focus[0], focus[1], k=2)
        held = len(m.reply) - g.chars
        if held <= 0:
            continue
        out.append(
            Move(
                kind="expand",
                label=f"re-read reply {m.id}",
                detail=f"{len(g.chosen)} sentence{'s' if len(g.chosen) != 1 else ''} shown for the selected gap",
                distance=f"{held:,} chars held back",
                target=m.id,
                weight=0.4,
            )
        )

    out.sort(key=lambda m: -m.weight)
    return out[:limit]
