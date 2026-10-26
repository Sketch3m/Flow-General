"""
truth.py - the quote-the-evidence gate.

A crossing means the sentence *states* a relation across the divide; this gate
asks the harder question: can it *point*? Every quoted span in a drafted cell
must be found in the corpus: punctuation and case are presentation, the word
sequence is content - an exact match after normalisation, or an elided quote
whose every fragment occurs where the ellipsis cut. Rewording a quote fails,
which is the point: a citation the corpus does not contain is a hallucinated
citation. A blockquote line counts as a citation because mode="quote" cells
*are* corpus sentences. A model-written claim is thereby anchored to text a
human can read instead of to the model's memory: the Kosmos-style
requirement, quote the evidence.

gate() is pure. cells.step() evaluates it on every draft and logs the verdict
either way; the draft is blocked only when step(..., truth_gate=True) is
passed, so the harness probe and the older experiments keep comparable
numbers.
"""

from __future__ import annotations

import re

# Quoted spans of 12+ chars between matching straight or curly double quotes.
# The length floor keeps the draft's own punctuation from reading as a
# citation; single quotes are excluded because English uses them for words.
_QUOTE = re.compile(r"[\"“]([^\"”“\n]{12,300})[\"”]")
# A blockquote line is a citation by construction (mode="quote" cells).
_BLOCK = re.compile(r"^>\s*(.{12,300})$", re.M)


def spans(text: str) -> list[str]:
    """Cited spans in a draft: double-quoted strings and blockquote lines."""
    return [m.strip() for m in _QUOTE.findall(text)] + [m.strip() for m in _BLOCK.findall(text)]


def _norm(s: str) -> str:
    """Case- and punctuation-insensitive, but word order is sacred: elision
    becomes a space (so cut words never join), the rest of the punctuation is
    dropped (so presentation differences cannot fail an honest quote)."""
    s = s.lower()
    s = re.sub(r"\.{2,}|\u2026", " ", s)
    s = re.sub(r"[.,;:!?'\"\u2018\u2019\u201c\u201d]", "", s)
    return " ".join(s.split())


def find(span: str, corpus: str) -> dict:
    """Is the span in the corpus? {found, ratio}.

    The span's word sequence must occur verbatim after normalisation, so a
    reworded 'quote' cannot pass (ratio 0 - that is the hallucination the gate
    exists for). An elided quote ("A ... B") may cut the middle only if every
    fragment occurs; ratio is the share of normalized characters that do."""
    parts = [p for p in re.split(r"\.{2,}|\u2026", span) if p.strip()]
    norms = [_norm(p) for p in parts]
    norms = [n for n in norms if n]
    total = sum(len(n) for n in norms)
    if total < 15:
        return {"found": False, "ratio": 0.0}
    nc = _norm(corpus)
    covered = sum(len(n) for n in norms if n in nc)
    ratio = round(covered / total, 3)
    return {"found": ratio >= 0.99, "ratio": ratio}


def gate(text: str, corpus: str) -> dict:
    """Verdict for one drafted cell: at least one citation, every citation
    findable. The reason string is what the step log and control event carry."""
    qs = spans(text)
    if not qs:
        return {"ok": False, "quotes": [], "reason": "no citation: draft quotes nothing"}
    results = [(q, find(q, corpus)) for q in qs]
    missing = [(q, r) for q, r in results if not r["found"]]
    if missing:
        worst = min(r["ratio"] for _, r in missing)
        return {
            "ok": False,
            "quotes": qs,
            "missing": [q for q, _ in missing],
            "reason": f"{len(missing)}/{len(qs)} cited span(s) not in the corpus (best ratio {worst:.2f})",
        }
    return {"ok": True, "quotes": qs, "reason": f"{len(qs)} cited span(s) found in the corpus"}
