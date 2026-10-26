"""
bench.py - measure the two local models on the jobs this document actually needs.

Run: .venv/bin/python bench.py

No API keys, no network: it calls the binaries and the local server directly.
The point is not a leaderboard, it is to find out which of these jobs may sit in
front of a button and which may not.

Jobs
  route      pick one of three actions from a card, with grounded arguments
  refuse     answer nothing when no tool fits
  select     choose the sentence that bears on a gap, from four
  quote      copy a sentence verbatim (the citation requirement)
  code       write one line of Python that filters lines (an RLM-style step)

Latency here is process-per-call: each needle decision pays for loading a 34 MB
model (~1.5-2.3 s). `needle --serve` removes that cost, but accuracy is the
blocker, not speed, so the CLI is the honest way to measure it.
"""

from __future__ import annotations

import json
import time

import localmodels

GAP = "eviction and citation never meet"
SENTENCES = [
    "Every context window fills up eventually, and the reply that does not fit is dropped, oldest first.",
    "A citation is a claim that a sentence traces back to a source.",
    "The pane never competes with you for room.",
]
PASSAGE = (
    "Every context window fills up eventually, and the reply that does not fit is dropped, oldest first. "
    "The words are still on disk. What disappears is the model's ability to see them. "
    "Eviction removes whichever message is oldest rather than whichever is irrelevant. "
    "Compression keeps what bears on the question being asked."
)


def route_cases():
    return [
        ("add the missing bridge sentence", "write_bridge"),
        ("show me the rest of this reply", "open_cell"),
        ("which of the two gaps should I work on", "ask_me"),
        ("what is the weather in Lagos", None),
    ]


def main() -> None:
    print("models:", json.dumps(localmodels.available()))
    print()

    print("== needle 3 - routing (arguments must be in the card)")
    ok = n = 0
    for ask, want in route_cases():
        card = localmodels.card_text(
            "7a5d1bf7", GAP, 700, ["s0", "s2"], ask
        )
        t = time.time()
        r = localmodels.route(card)
        dt = (time.time() - t) * 1000
        got = (r["call"] or {}).get("name")
        good = got == want
        ok += good
        n += 1
        print(
            f"  {'ok ' if good else 'MISS'} {ask[:42]:44s} -> {str(got):13s} "
            f"conf {r['confidence']:.2f}  {dt:5.0f} ms"
            + ("  [refused]" if r["suppressed"] else "")
        )
    print(f"  {ok}/{n} exact\n")

    print("== needle 3 - extraction (verbatim quote + span)")
    tool = [
        {
            "name": "record",
            "description": "Record the gist for the reader.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gist": {"type": "string", "description": "one sentence quoted exactly"},
                    "spans": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["gist", "spans"],
            },
        }
    ]
    r = localmodels.route(f"Gap: {GAP}\n\n{PASSAGE}", tools=tool)
    gist = (r["call"] or {}).get("arguments", {}).get("gist", "")
    # an empty gist is a refusal, not a quote that happens to be a substring
    verbatim = bool(gist.strip()) and gist.strip() in PASSAGE
    print(f"  gist: {gist[:110]!r}")
    print(f"  verbatim: {verbatim}  confidence {r['confidence']:.3f}  refused {r['suppressed']}\n")

    if not localmodels.available()["qwen"]:
        print("qwen server not running; skipping the 0.5B cases")
        return

    print("== qwen 0.5b - constrained selection")
    t = time.time()
    r = localmodels.pick(
        "Which sentence bears on the gap?",
        ["S0", "S1", "S2", "NONE"],
        context=f"Gap: {GAP}\n" + "\n".join(f"S{i}: {s}" for i, s in enumerate(SENTENCES)),
    )
    print(f"  choice: {r['choice']}  ({(time.time() - t):.2f}s)  expected S0 or S1")

    print("\n== qwen 0.5b - free-form jobs")
    for name, system, user, n in [
        (
            "quote",
            "Quote two sentences exactly as written. Output only the quote.",
            f"Text: {PASSAGE}\nQuestion: what is lost when a reply is evicted?",
            120,
        ),
        (
            "code",
            "Answer with one line of Python only.",
            "Write an expression that returns every line in text containing the word citation.",
            80,
        ),
    ]:
        out = _raw(system, user, n)
        print(f"  {name}: {out[:120]!r}")


def _raw(system: str, user: str, n: int) -> str:
    import urllib.request

    body = json.dumps(
        {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": n,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    req = urllib.request.Request(
        f"{localmodels.QWEN_URL}/v1/chat/completions", body, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"<{type(e).__name__}: {e}>"


if __name__ == "__main__":
    main()
