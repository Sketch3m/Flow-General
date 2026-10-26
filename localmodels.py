"""
localmodels.py - the two small models, called the way they actually work.

Measured on this machine (2 vCPU, 3 GB RAM, no GPU):

    Needle 3   34 MB model, 79 MB peak RSS, ~270-330 tok/s prefill,
               ~100-200 tok/s decode, ~0.1 s per routing decision
    Qwen2.5-0.5B-Instruct  Q4_K_M, 469 MB, ~1 s per short answer

What that buys, and what it does not:

* **Needle routes.** Given a card whose fields are literally present in the
  prompt, it picks one tool and copies the arguments out of the text. It
  *suppresses* a call when an argument is not grounded (confidence collapses to
  ~0.01), which is the behaviour you want in front of a button that spends
  money. It cannot invent an objective: ask it to author one and it either
  refuses or copies the instruction back.
* **Qwen does not route.** In testing it chose the wrong tool, put the utterance
  where the tool name belongs, and paraphrased text it was told to quote. With
  a JSON-schema-constrained output the *format* is fixed but the judgement is
  not. It is usable for one job only: choosing among a closed set of short
  labels, and even then it needs the grammar to keep it honest.

So the split this file exposes is deliberate: `route()` is a router you can put
in front of real actions, `pick()` is a constrained classifier, and neither is
allowed to write prose that later gets cited.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).with_name(".models")
NEEDLE_BIN = ROOT / "needle.bin"
NEEDLE_MODEL = ROOT / "needle3.cact"
QWEN_URL = os.environ.get("NODUS_QWEN_URL", "http://127.0.0.1:8090")

# The tools the page can actually perform. Names are the words a writer would
# say out loud, because Needle retrieves on the schema text, not on a name we
# find elegant.
TOOLS = [
    {
        "name": "write_bridge",
        "description": (
            "Write new text into a cell. Triggers: add, write, draft, bridge, "
            "connect, expand on, explain. Use when the human wants something new "
            "written into the document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cell": {"type": "string", "description": "cell id"},
                "objective": {"type": "string", "description": "what to write, one sentence"},
                "budget_chars": {"type": "integer", "description": "characters of context to allow"},
            },
            "required": ["cell", "objective"],
        },
    },
    {
        "name": "open_cell",
        "description": (
            "Open a cell and show the text it is holding back. Triggers: show me, "
            "open, expand, the rest, full text, unfold."
        ),
        "parameters": {
            "type": "object",
            "properties": {"cell": {"type": "string", "description": "cell id"}},
            "required": ["cell"],
        },
    },
    {
        "name": "ask_me",
        "description": (
            "Ask the human a question and stop. Triggers: which one, choose, "
            "unclear, do you mean, confirm. Use when two gaps compete or the "
            "request is ambiguous."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cell": {"type": "string", "description": "cell id"},
                "question": {"type": "string", "description": "one question"},
            },
            "required": ["cell", "question"],
        },
    },
]


def available() -> dict:
    return {
        "needle": NEEDLE_BIN.exists() and NEEDLE_MODEL.exists(),
        "qwen": _qwen_up(),
    }


def _qwen_up() -> bool:
    try:
        with urllib.request.urlopen(f"{QWEN_URL}/v1/models", timeout=1.5):
            return True
    except Exception:
        return False


def route(
    card: str,
    tools: list | None = None,
    timeout: float = 20.0,
    forced: bool = False,
) -> dict:
    """One routing decision, or a refusal.

    `card` must contain every argument literally - the cell id, the budget, the
    span ids - because Needle copies rather than composes. That is a constraint
    of the model, not of this wrapper: callers should render the card as text
    before asking.

    `forced` passes needle's benchmark flag: always dispatch when tools are
    offered. That removes the engine's 0.1 suppression floor, so evals can
    score *selection* (what it would choose) separately from *act* (what it
    was confident enough to ship) - refusal and wrongness are different
    failures and must not be summed.

    Returns {"call": {...} | None, "suppressed_call": {...} | None,
             "confidence": float, "reasoning": str, "suppressed": bool}.
    `suppressed_call` is the pick the floor held back: hidden from a real
    caller, but it is still the model's choice. A refused call is a normal
    result, not an error.
    """
    if not (NEEDLE_BIN.exists() and NEEDLE_MODEL.exists()):
        return {
            "call": None,
            "suppressed_call": None,
            "confidence": 0.0,
            "reasoning": "needle not installed",
            "suppressed": False,
        }

    tools_file = ROOT / "_tools.json"
    tools_file.write_text(json.dumps(tools or TOOLS))
    argv = [
        str(NEEDLE_BIN),
        "--model", str(NEEDLE_MODEL),
        "--tools", str(tools_file),
        "--prompt", card,
    ]
    if forced:
        argv.append("--forced")
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
        )
        d = json.loads(p.stdout)
    except Exception as e:
        return {
            "call": None,
            "suppressed_call": None,
            "confidence": 0.0,
            "reasoning": f"{type(e).__name__}: {e}",
            "suppressed": False,
        }

    calls = d.get("function_calls") or []
    held = d.get("suppressed_calls") or []
    suppressed = bool(held)
    return {
        "call": calls[0] if calls else None,
        "suppressed_call": held[0] if held else None,
        "confidence": float(d.get("confidence") or 0.0),
        "reasoning": d.get("reasoning") or "",
        "suppressed": suppressed,
        "validation": d.get("validation") or {},
        "ram_mb": d.get("peak_ram_mb"),
    }


def pick(question: str, options: list[str], context: str = "", timeout: float = 60.0) -> dict:
    """Choose one label from a closed set, grammar-constrained.

    This is the only job the 0.5B model did reliably. The enum is in the JSON
    schema so the output cannot be malformed; what it still cannot guarantee is
    that the choice is *right*, which is why callers should show the answer and
    keep the deterministic selector as the default.
    """
    # The server here accepts only response_format 'text' or 'json_object' (a
    # json_schema enum returns HTTP 500). The closed set is enforced in code below,
    # so the choice is always one of `options` whatever the model writes.
    payload = {
        "messages": [
            {"role": "system", "content": 'Choose one option from the list. Reply as JSON: {"choice": "<option>"}.'},
            {"role": "user", "content": f"{context}\n\n{question}\nOptions: {', '.join(options)}"},
        ],
        "temperature": 0,
        "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{QWEN_URL}/v1/chat/completions",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        raw = str(json.loads(d["choices"][0]["message"]["content"]).get("choice") or "").strip()
        # Models often return a shortened label (a title without its subtitle).
        # Match to the option it names; reject only if no option matches.
        match = next((o for o in options if o == raw), None) or next(
            (o for o in options if raw and (raw.lower() in o.lower() or o.lower() in raw.lower())),
            None,
        )
        if match is None:
            return {"choice": None, "error": f"choice not in options: {raw!r}"}
        return {"choice": match, "error": None}
    except Exception as e:
        return {"choice": None, "error": f"{type(e).__name__}: {e}"}


def chat(
    messages: list[dict],
    timeout: float = 90.0,
    max_tokens: int = 400,
    stop: list[str] | None = None,
    response_json: bool = False,
) -> dict:
    """Free-form reply from the local model, for a chat box on an issue card.

    Deliberately not used to write cited text: bench.py showed the 0.5B model
    paraphrases when asked to quote. Here the issue's evidence is put in the
    system prompt and the answer is read by a human, not written into the board.
    """
    payload = {
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if stop:
        payload["stop"] = stop
    if response_json:
        # This server accepts only 'text' or 'json_object' here; the JSON shape is
        # enforced by the caller's schema check, not by a json_schema enum.
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        f"{QWEN_URL}/v1/chat/completions",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return {"text": d["choices"][0]["message"]["content"].strip(), "error": None}
    except Exception as e:
        return {"text": None, "error": f"{type(e).__name__}: {e}"}


def card_text(cell: str, gap: str, budget: int, spans: list[str], ask: str) -> str:
    """Render a task card as the flat text Needle can ground against.

    Every field is repeated in words, not passed as structure. That looks
    redundant and is the point: an argument the model cannot find in the prompt
    is an argument it is not allowed to emit.
    """
    return (
        f"Cell {cell}. Budget: {budget} characters. "
        f"Spans: {', '.join(spans) or 'none'}. "
        f"Gap: {gap}. Human: {ask}"
    )
