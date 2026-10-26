"""
eval_route.py - needle vs Qwen vs rules on labeled routing cards.

The question this settles: needle's routing failures - was it *scale*, or a
different issue (calibration, seat mismatch)? Three routers see the SAME 20
cards, each with a ground-truth action derivable from what the card says:

    draft   direction names a gap that exists       -> draft one sentence
    stop    0 unbridged gaps OR off-topic direction -> stop
    ask     two candidate gaps, direction names neither -> ask which one

Cards carry the facts explicitly (like cells.card() output does), so routing is
a lookup: rules score 100% by construction, and the number that matters is how
much each model loses against that floor. Needle's confidence is the
calibration evidence: if it is near zero regardless of correctness, no
threshold can ever gate on it, whatever its size.

Qwen routes via localmodels.pick (temperature 0, argmax) - it has no usable
confidence signal without logprobs, so it is scored on accuracy only.
"""

from __future__ import annotations

import statistics
import sys

import cells
import localmodels

GAPS = [("quantization", "governance", 0.074), ("predict", "record", 0.071), ("system", "semantic", 0.030)]


def make_cards() -> list[dict]:
    """20 cards: 8 draft, 6 stop (3 no-gaps, 3 off-topic), 6 ask."""
    cards = []
    drafts = [
        ("bridge", "quantization", "governance", 0.074),
        ("bridge", "predict", "record", 0.071),
        ("connect", "system", "semantic", 0.030),
        ("add a sentence linking", "quantization", "governance", 0.074),
        ("explain how", "across", "record", 0.074),
        ("hypothesise a link between", "predict", "valence", 0.071),
        ("write one sentence connecting", "system", "semantic", 0.030),
        ("propose a bridge from", "quantization", "governance", 0.074),
    ]
    for i, (verb, a, b, s) in enumerate(drafts):
        cards.append(
            {
                "id": f"d{i}",
                "truth": "draft",
                "text": (
                    f"Cell sheet. Human direction: {verb} {a} to {b} in one sentence. "
                    f"Gap: {a} to {b}, score {s:.3f} (unbridged). Latent links: 3. "
                    "Action: draft one sentence into a new cell."
                ),
            }
        )
    for i, (a, b) in enumerate([("predict", "valence"), ("across", "record"), ("process", "evidence")]):
        cards.append(
            {
                "id": f"s{i}",
                "truth": "stop",
                "text": (
                    f"Cell sheet. Human direction: bridge {a} to {b}. "
                    "Gap: none - the sheet has 0 unbridged gaps. Latent links: 4. "
                    "Action: do nothing."
                ),
            }
        )
    for i, topic in enumerate(["a poem about ducks crossing the street", "the weather in Lisbon", "a python function that sorts a list"]):
        cards.append(
            {
                "id": f"s{i + 3}",
                "truth": "stop",
                "text": (
                    f"Cell sheet. Human direction: write {topic}. "
                    "Gap: quantization to governance, score 0.074 (unbridged). Latent links: 3. "
                    "Action: do nothing - the request is off-topic for this sheet."
                ),
            }
        )
    for i in range(6):
        cards.append(
            {
                "id": f"a{i}",
                "truth": "ask",
                "text": (
                    "Cell sheet. Human direction: bridge something, your choice - which gap do you mean? "
                    "Two candidate gaps: quantization~governance score 0.074, predict~record score 0.071, "
                    "system~semantic score 0.030. Latent links: 3. Action: ask the human which gap."
                ),
            }
        )
    return cards


def route_rules(card: str) -> str:
    """The floor. Encodes the construction - circular by design, and that is
    the point: cards state their facts, so lookup should be perfect."""
    low = card.lower()
    if "0 unbridged gaps" in low or "off-topic" in low:
        return "stop"
    if "which gap" in low or "your choice" in low:
        return "ask"
    return "draft"


def render_intended(text: str) -> str:
    """The same card in the documented decision shape: functions named up front
    so the model picks rather than guesses (Cactus's own advice for constrained
    choices), the card's facts unchanged after. The rules floor must survive
    the rendering - it is only a floor if the truth is still in the text."""
    return (
        "Question: which function should be called for this sheet card? "
        "Available functions: draft (write one sentence), ask (request the human's choice), "
        f"stop (do nothing). Card: {text}"
    )


def pick_of(r: dict, include_suppressed: bool = True) -> str:
    """The action needle chose: the dispatched call, or - when
    include_suppressed - the call the engine's 0.1 floor held back.

    The held-back call is still a *choice*: reading it separates 'wrong' from
    'refused', which is the whole question being measured. 'none' means
    needle returned neither - honest, unlike defaulting an empty answer to ask.
    """
    c = r.get("call")
    if not c and include_suppressed:
        c = r.get("suppressed_call")
    name = (c or {}).get("name") or ""
    return name if name in ("draft", "ask", "stop") else "none"


def score_needle(cards: list[dict], *, intended: bool, forced: bool = False) -> dict:
    """One needle pass over the cards, scored twice: what it *dispatched*
    (act = everything a threshold-0.1 caller would see) and what it *chose*
    (act or suppressed = its pick with the floor removed)."""
    act_preds, sel_preds, confs = [], [], []
    errors = held = 0
    for c in cards:
        text = render_intended(c["text"]) if intended else c["text"]
        r = localmodels.route(text, tools=cells.ACTIONS, forced=forced)
        errors += bool(r.get("error"))
        held += bool(r.get("suppressed")) and not r.get("call")
        act_preds.append(pick_of(r, include_suppressed=False))
        sel_preds.append(pick_of(r, include_suppressed=True))
        confs.append(float(r.get("confidence") or 0.0))
    return {
        "act": _matrix(cards, act_preds),
        "sel": _matrix(cards, sel_preds),
        "confs": confs,
        "errors": errors,
        "held": held,
    }


def _print_needle(tag: str, s: dict) -> None:
    print(
        f"{tag:<24} act {s['act']['accuracy']:.0%} \u00b7 selection {s['sel']['accuracy']:.0%} "
        f"\u00b7 held back {s['held']} \u00b7 {s['errors']} call errors"
    )
    for split in ("act", "sel"):
        per = s[split]["per"]
        print(f"        {split:<4} " + " ".join(f"{t} {v['correct']}/{v['n']}" for t, v in per.items()))
        for t, v in per.items():
            if v["correct"] < v["n"]:
                print(f"          {t} -> {v['confusion']}")
    confs = s["confs"]
    hi = sum(1 for x in confs if x >= 0.5)
    print(
        f"        conf min {min(confs):.3f} \u00b7 mean {statistics.mean(confs):.3f} "
        f"\u00b7 max {max(confs):.3f} \u00b7 at >= 0.5: {hi}"
    )


def route_needle(card: str) -> tuple[str, float]:
    r = localmodels.route(card, tools=cells.ACTIONS)
    return pick_of(r), float(r.get("confidence") or 0.0)


def route_qwen(card: str) -> str:
    r = localmodels.pick(
        "Which action should the agent take for this sheet card? Answer with the option only.",
        ["draft", "ask", "stop"],
        context=card,
    )
    return r["choice"] if r["choice"] in ("draft", "ask", "stop") else "ask"


def _matrix(cards: list[dict], preds: list[str]) -> dict:
    per: dict = {}
    correct = 0
    for c, p in zip(cards, preds):
        t = c["truth"]
        per.setdefault(t, {"n": 0, "correct": 0, "confusion": {}})
        per[t]["n"] += 1
        per[t]["correct"] += p == t
        per[t]["confusion"][p] = per[t]["confusion"].get(p, 0) + 1
        correct += p == t
    return {"accuracy": correct / len(cards), "per": per}


def main() -> None:
    cards = make_cards()
    print(f"{len(cards)} cards · truths: " + str({t: sum(1 for c in cards if c['truth'] == t) for t in ('draft', 'ask', 'stop')}))

    preds_rules = [route_rules(c["text"]) for c in cards]
    print(f"\nrules   {_matrix(cards, preds_rules)['accuracy']:.0%} (floor: cards state their facts)")

    preds_q, errors_q = [], 0
    for c in cards:
        r = localmodels.pick("Which action should the agent take for this sheet card? Answer with the option only.", ["draft", "ask", "stop"], context=c["text"])
        errors_q += bool(r.get("error"))
        preds_q.append(r["choice"] if r["choice"] in ("draft", "ask", "stop") else "ask")
    m_q = _matrix(cards, preds_q)
    print(f"qwen    {m_q['accuracy']:.0%} ({errors_q} call errors) per-class: "
          + ", ".join(f"{t} {v['correct']}/{v['n']}" for t, v in m_q["per"].items()))
    for t, v in m_q["per"].items():
        if v["correct"] < v["n"]:
            print(f"        {t} -> {v['confusion']}")

    # scored twice on purpose: 'act' is what a threshold-0.1 caller would
    # have seen, 'selection' is what needle chose including the held-back call.
    _print_needle("needle/original", score_needle(cards, intended=False))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--needle":
        # section runs for slow passes: original (as published), intended
        # (enum-style rendering), forced (intended + engine floor removed).
        section = sys.argv[2] if len(sys.argv) > 2 else "original"
        _print_needle(
            f"needle/{section}",
            score_needle(make_cards(), intended=section in ("intended", "forced"), forced=section == "forced"),
        )
    else:
        main()
