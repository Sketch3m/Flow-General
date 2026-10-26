"""
harness.py - Qwen edits the harness; Infranodus is the gate.

Harness^2 (arXiv:2610.14224) freezes the model and moves improvement into the
harness: propose an edit, probe it, keep it only if it works. Self-Harness
(arXiv:2606.09498) adds regression testing before any edit is kept. This file
is that loop for this repo, with one rule the two papers leave open:

    the probe is Infranodus, not a benchmark score.

A candidate edit is applied to the live harness, the loop runs on a fixed probe
corpus, and cells.accept() - the typed-relation crossing plus the two-terms-per-
side grounding check - decides what counts as progress. Nothing is kept on the
model's word alone:

    propose   one JSON edit against FIELD_SPECS; deterministic rules answer when
              qwen is down or returns something invalid (recorded, not hidden)
    probe     cells.step on the probe corpus with the candidate applied; the
              live harness is restored no matter what the probe does
    gate      keep the edit only if crossings rise, or if crossings hold while
              valid drafts rise and failures do not; otherwise reject and say why
    record    every attempt, kept or not, appends to solve/harness_trace.json

The editable surface is deliberately three fields. A harness the model can
rewrite wholesale has no gate worth the name - the gate only means something
because the set of things it may touch is small and closed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import delta

FIELD_SPECS = {
    "draft_system": {"type": str, "min": 40, "max": 1200},
    "draft_tries": {"type": int, "min": 1, "max": 5},
    "draft_hint": {"type": str, "min": 0, "max": 300},
}

DEFAULTS = {
    "draft_system": (
        "You write one sentence that links two research areas. Rules: name both areas; "
        "use a relation verb (causes, implies, requires, depends on, supports, contradicts); "
        "say only what the evidence supports; if the evidence is insufficient, start the "
        "sentence with 'However,' and say what is missing. Never invent a paper, a number, "
        "or a quote. One sentence, under 35 words."
    ),
    "draft_tries": 3,
    "draft_hint": "",
}

STATE = Path("solve") / "harness.json"
TRACE = Path("solve") / "harness_trace.json"

PROBE_SEED = (
    "None of these systems convinces me that a new claim is true; "
    "I want to see what each one treats as evidence."
)
_FALLBACK_TEXT = (
    "Compiler passes lower intermediate representation into machine code, and inlining "
    "reduces call overhead. Predator and prey populations oscillate over seasons, and "
    "hunting rates shape survival. Governance records preserve evidence of disputed "
    "metadata decisions. Quantization changes precision and sensitivity of fixed-step "
    "denoisers across training runs."
)


def _load() -> dict:
    """Saved harness wins over defaults, each field validated on its own.

    validate_edit() handles one field at a time (it takes the first key), so
    calling it on the whole saved dict silently kept only that key - a kept
    edit to a non-first field vanished on restart. Each field is checked here.
    """
    try:
        saved = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    for k, v in saved.items():
        if k in FIELD_SPECS:
            clean, err = validate_edit({k: v})
            if not err:
                out[k] = clean[k]
    return out


def validate_edit(edit: dict) -> tuple[dict, str]:
    """Closed schema: one field, right type, right range. Returns (clean, error)."""
    if not isinstance(edit, dict) or not edit:
        return {}, "edit is not an object"
    unknown = [k for k in edit if k not in FIELD_SPECS]
    if unknown:
        return {}, f"unknown field(s): {', '.join(unknown)}"
    field, value = next(iter(edit.items()))
    spec = FIELD_SPECS[field]
    if spec["type"] is int and isinstance(value, bool):
        return {}, f"{field} must be an integer"
    if not isinstance(value, spec["type"]):
        return {}, f"{field} must be {spec['type'].__name__}, got {type(value).__name__}"
    if isinstance(value, str) and not (spec["min"] <= len(value) <= spec["max"]):
        return {}, f"{field} length {len(value)} outside {spec['min']}..{spec['max']}"
    if isinstance(value, int) and not (spec["min"] <= value <= spec["max"]):
        return {}, f"{field} value {value} outside {spec['min']}..{spec['max']}"
    return {field: value}, ""


HARNESS: dict = _load()


def propose(failure_summary: str, use_qwen: bool = True) -> dict:
    """One edit to one field. Qwen writes it; rules answer if the model cannot.

    The failure summary is probe data (how many drafts failed and why), never a
    compliment: the model proposes against evidence of what broke.
    """
    t0 = time.time()
    if use_qwen:
        try:
            import localmodels

            prompt = (
                f"Current harness draft_system: {HARNESS['draft_system']}\n"
                f"Current draft_tries: {HARNESS['draft_tries']}\n"
                f"Current draft_hint: {HARNESS['draft_hint']!r}\n\n"
                f"Probe failures: {failure_summary}\n\n"
                "Propose ONE edit as JSON with keys field, value, reason. "
                "field is one of draft_system, draft_tries, draft_hint. "
                'Reply only with JSON, e.g. {"field": "draft_hint", '
                '"value": "state the verb first", "reason": "..."}'
            )
            r = localmodels.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=300,
                timeout=90,
                response_json=True,
            )
            raw = json.loads((r["text"] or "").strip())
            candidate, err = validate_edit({raw["field"]: raw["value"]})
            if not err:
                return {
                    "field": next(iter(candidate)),
                    "value": candidate[next(iter(candidate))],
                    "reason": str(raw.get("reason", ""))[:300],
                    "by": "qwen",
                    "ms": int((time.time() - t0) * 1000),
                    "error": None,
                }
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        # falls through to rules with the model's error recorded
    else:
        err = "qwen disabled"

    edit, rerr = _rules_edit(failure_summary)
    return {
        "field": next(iter(edit)),
        "value": edit[next(iter(edit))],
        "reason": rerr,
        "by": "rules",
        "ms": int((time.time() - t0) * 1000),
        "error": err,
    }


def _rules_edit(failure_summary: str) -> tuple[dict, str]:
    """Deterministic fallback: address the failure the probe actually reported."""
    s = failure_summary.lower()
    if "relation verb" in s:
        hint = "Use one of these verbs: requires, implies, supports, depends on, causes."
        return {"draft_hint": (HARNESS["draft_hint"] + " " + hint).strip()}, "rules: failures cite missing relation verb"
    if "missing" in s:
        hint = "Write both terms into the sentence exactly as given."
        return {"draft_hint": (HARNESS["draft_hint"] + " " + hint).strip()}, "rules: failures cite missing terms"
    if HARNESS["draft_tries"] < FIELD_SPECS["draft_tries"]["max"]:
        return {"draft_tries": HARNESS["draft_tries"] + 1}, "rules: drafts failed, spend more attempts"
    return {"draft_hint": HARNESS["draft_hint"]}, "rules: nothing to change, keep as is"


def _probe_sheet() -> list:
    import cells

    cs = [cells.Cell(id="h1", text=PROBE_SEED, role="seed")]
    for i, p in enumerate(sorted(Path("papers").glob("*.md")), 1):
        cs.append(cells.Cell(id=f"p{i}", text=p.read_text(encoding="utf-8"), origin="paper", role="paper"))
    if len(cs) == 1:
        cs.append(cells.Cell(id="f1", text=_FALLBACK_TEXT, role="note"))
    cells.assign(cs)
    return cs


_SENT = re.compile(r"sentence \d+/\d+ \d+ ms - ([^:]+):")
_FAIL_WHYS = ("no relation verb", "empty")


def _tally(line: str) -> str | None:
    """Classify a step log line: 'fail', 'valid', or None if not a sentence line.

    Matched structurally (any 'sentence i/n ... ms - <why>:' line) instead of on
    fixed words - the step's vocabulary changed once already and silently zeroed
    this counter the first time.
    """
    m = _SENT.search(line)
    if not m:
        return None
    why = m.group(1).strip()
    if why.startswith("missing") or why in _FAIL_WHYS:
        return "fail"
    return "valid"


def probe(candidate: dict, rounds: int = 1, use_qwen: bool = True) -> dict:
    """Run the loop with the candidate applied. Live harness restored always."""
    import cells

    before = dict(HARNESS)
    HARNESS.update(candidate)
    crossed = satisfied = fails = 0
    stopped = ""
    try:
        cs = _probe_sheet()
        for _ in range(rounds):
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=use_qwen)
            for line in res.get("log", []):
                kind = _tally(line)
                fails += kind == "fail"
                satisfied += kind == "valid"
            if "cell" in res:
                crossed += bool(res["cell"].meta.get("crossed"))
                cs.append(res["cell"])
            else:
                stopped = res.get("stopped", "")
                break
    finally:
        HARNESS.clear()
        HARNESS.update(before)
    return {"crossed": crossed, "satisfied": satisfied, "fails": fails, "stopped": stopped}


def gate(before: dict, after: dict) -> tuple[bool, str]:
    """The Infranodus gate: crossings first, valid drafts second, failures never worse."""
    if after["crossed"] > before["crossed"]:
        return True, f"crossings {before['crossed']} -> {after['crossed']}"
    if after["crossed"] == before["crossed"] and after["satisfied"] > before["satisfied"] and after["fails"] <= before["fails"]:
        return True, (
            f"crossings held at {after['crossed']}, "
            f"valid drafts {before['satisfied']} -> {after['satisfied']}"
        )
    if after["crossed"] < before["crossed"]:
        return False, f"crossings regressed {before['crossed']} -> {after['crossed']}"
    if after["fails"] > before["fails"]:
        return False, f"failures rose {before['fails']} -> {after['fails']}"
    return False, f"no improvement (crossed {after['crossed']}, drafts {after['satisfied']})"


def save(path: Path = STATE) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(HARNESS, indent=2), encoding="utf-8")


def record(entry: dict, path: Path = TRACE) -> None:
    path.parent.mkdir(exist_ok=True)
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    log.append(entry)
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def summary_of(before: dict) -> str:
    return (
        f"{before['fails']} drafts rejected, {before['satisfied']} valid, "
        f"{before['crossed']} gaps closed"
        + (f" (stopped: {before['stopped']})" if before["stopped"] else "")
    )


def edit_once(rounds: int = 1, use_qwen: bool = True) -> dict:
    """Propose -> probe -> gate -> record. Returns everything the UI needs to show."""
    before = probe({}, rounds=rounds, use_qwen=use_qwen)
    proposal = propose(summary_of(before), use_qwen=use_qwen)
    after = probe({proposal["field"]: proposal["value"]}, rounds=rounds, use_qwen=use_qwen)
    keep, why = gate(before, after)
    if keep:
        HARNESS.update({proposal["field"]: proposal["value"]})
        save()
    entry = {
        "ts": int(time.time()),
        "field": proposal["field"],
        "value": proposal["value"],
        "reason": proposal["reason"],
        "by": proposal["by"],
        "model_error": proposal["error"],
        "before": before,
        "after": after,
        "kept": keep,
        "why": why,
    }
    record(entry)
    delta.append("harness_edit", entry, actor=proposal["by"])
    log = [
        f"before  {summary_of(before)}",
        f"propose {proposal['field']} by {proposal['by']}: {str(proposal['value'])[:90]}",
        f"probe   {summary_of(after)}",
        f"gate    {'KEEP' if keep else 'REJECT'} - {why}",
    ]
    if proposal["error"]:
        log.append(f"model   proposal unavailable ({proposal['error'][:60]}); rules answered")
    return {"entry": entry, "log": log, "harness": dict(HARNESS)}
