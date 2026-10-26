"""
eval_native.py - needle on its designed seat: task cards whose arguments sit
literally in the utterance (cells.card + cells.ACTIONS).

Contrast with eval_route.py, where the same engine refused or mispicked
routing cards: here every card exists because nodus found a real unbridged
gap on the five-paper sheet, and cells.card() renders every field in words -
the pattern needle's docs describe (copies rather than composes).

Two passes per card:
    natural   engine floor active - what a real caller sees (act)
    forced    floor removed       - what it would choose (selection)

Truth is 'draft' by construction: the card says "Action: draft one sentence
into a new cell." The reasoning excerpt per card is part of the measurement:
grounding every argument back to prompt words is the observable difference
between this seat and the routing seat.

Scoring helpers are imported from eval_route - one definition of act vs
selection, two seats.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import cells
import eval_route
import localmodels


def build_sheet() -> list[cells.Cell]:
    """The live experiment sheet headless: five papers + a seed, as sheet.py's
    load button builds it."""
    cs = [
        cells.Cell(
            id=f"p{i + 1}",
            text=p.read_text(encoding="utf-8"),
            origin="paper",
            role="paper",
            meta={"file": p.name},
        )
        for i, p in enumerate(sorted(Path("papers").glob("*.md")))
    ]
    cs.append(cells.Cell(id="s1", text="Bridge any two areas these papers leave unconnected.", role="seed"))
    return cells.assign(cs)


def native_cards(cs: list[cells.Cell], limit: int = 6) -> list[dict]:
    """One card per unbridged gap, built exactly the way cells.step builds it
    before asking needle to decide - same gapdict, same representatives."""
    cells.latent_for(cs)
    a = cells.read(cs).get("analysis")
    if a is None:
        return []
    seed = next((c.text for c in cs if c.role == "seed"), "")
    out = []
    for gap in [g for g in a.gaps if not g.bridged][:limit]:
        reps_a = cells.representatives(gap.terms_a)
        reps_b = cells.representatives(gap.terms_b)
        gapdict = {
            **gap.to_dict(),
            "term_a": reps_a[0],
            "term_b": reps_b[0],
            "group_a": reps_a,
            "group_b": reps_b,
        }
        out.append(
            {
                "id": gap.id,
                "truth": "draft",
                "text": cells.card(gapdict, seed, cs[0].latent),
                # same card, but the imperative names the arguments - the
                # pattern eval_route's cards use (and the one needle grounded
                # correctly on). Attribution probe: is the failure the model,
                # or a direction slot that says 'bridge anything'?
                "text_named": cells.card(
                    gapdict,
                    f"bridge {reps_a[0]} to {reps_b[0]} in one sentence",
                    cs[0].latent,
                ),
            }
        )
    return out


def main() -> None:
    cs = build_sheet()
    cards = native_cards(cs)
    if not cards:
        print("no unbridged gaps - nothing for needle to decide")
        return
    print(f"{len(cards)} unbridged gaps -> task cards (truth: draft by construction)")

    for tag, key, forced in (
        ("natural", "text", False),
        ("forced", "text", True),
        ("named-direction", "text_named", False),
    ):
        act_preds, sel_preds, confs, held = [], [], [], 0
        print(f"\nneedle/native {tag}:")
        for c in cards:
            r = localmodels.route(c[key], tools=cells.ACTIONS, forced=forced)
            act = eval_route.pick_of(r, include_suppressed=False)
            choice = eval_route.pick_of(r, include_suppressed=True)
            held += bool(r.get("suppressed")) and not r.get("call")
            conf = float(r.get("confidence") or 0.0)
            confs.append(conf)
            act_preds.append(act)
            sel_preds.append(choice)
            reason = (r.get("reasoning") or "").replace("\n", " ")[:110]
            print(f"  {c['id']:<20} act {act:<5} sel {choice:<5} conf {conf:.3f}  {reason}")
        m_act = eval_route._matrix(cards, act_preds)
        m_sel = eval_route._matrix(cards, sel_preds)
        print(
            f"  -> act {m_act['accuracy']:.0%} · selection {m_sel['accuracy']:.0%} · "
            f"held back {held} · conf mean {statistics.mean(confs):.3f} max {max(confs):.3f}"
        )


if __name__ == "__main__":
    main()
