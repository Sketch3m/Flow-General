"""
gist.py - the compression layer: statements, offset-stable citations, and the
idea filter.

This is the part InfraNodus does not have and SolveIt does not have. Both keep
long text; neither can hand you the two sentences that bear on the question you
are currently holding while leaving everything else retrievable.

The research is unambiguous about the split of duties: deterministic code is the
right tool for *selection and provenance* (it is reproducible, fast, auditable,
and can guarantee a span is real), and a small model is the right tool for
*semantic selection and synthesis* (recognising that different wording says the
same thing). So this module returns **quotes with offsets**, never prose. A
model can be added later to paraphrase two already-chosen spans or to pick
spans this cannot; it cannot be allowed to invent the text being cited.

`verify()` is the only guarantee offered, and it is deliberately narrow: the
span still resolves to exactly those characters. It is not a claim that the span
*supports* the idea. That distinction is where citation UIs usually start lying.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import nodus

_FENCE = re.compile(r"```.*?```", re.S)  # local copy; nodus owns the tokeniser


# ---------------------------------------------------------------------------
# statements: the unit InfraNodus annotates, and the unit we compress with
# ---------------------------------------------------------------------------

_SENT = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")


@dataclass
class Statement:
    """A sentence-sized span of the source, with exact offsets back into it.

    Offsets matter: the gist is an *overlay* over text the user still owns, so
    anything shown has to be cut from the original, never rewritten.
    """

    text: str
    start: int
    end: int
    concepts: list[str] = field(default_factory=list)
    id: str = ""  # stable citation label, s0, s1, ...
    matched: list[str] = field(default_factory=list)  # why it was selected


def statements(text: str, min_chars: int = 40, max_chars: int = 900) -> list[Statement]:
    """Split into statements without losing offsets.

    Code fences are masked with spaces rather than deleted, so every offset
    still indexes the original string. Short fragments (headings, table rows,
    stray lines) are merged forward instead of being returned as statements.
    """
    masked = _FENCE.sub(lambda m: " " * len(m.group()), text)
    out: list[Statement] = []
    buf: Statement | None = None
    for m in _SENT.finditer(masked):
        raw = text[m.start() : m.end()]
        if not raw.strip() or raw.lstrip().startswith(("|", "#", ">")):
            continue
        piece = Statement(text=raw.strip(), start=m.start(), end=m.end())
        if buf is None:
            buf = piece
        elif len(buf.text) < min_chars or len(piece.text) < min_chars:
            buf = Statement(text=text[buf.start : piece.end].strip(), start=buf.start, end=piece.end)
        else:
            out.append(buf)
            buf = piece
        if len(buf.text) >= max_chars:
            out.append(buf)
            buf = None
    if buf is not None:
        out.append(buf)
    if len(out) > 1 and len(out[-1].text) < min_chars:
        # a trailing stub joins the sentence before it
        tail = out.pop()
        out[-1] = Statement(
            text=text[out[-1].start : tail.end].strip(), start=out[-1].start, end=tail.end
        )
    for i, s in enumerate(out):
        s.id = f"s{i}"
    return [s for s in out if s.text.strip()]


@dataclass
class Gist:
    """What a long message looks like when it has to fit on a page."""

    chosen: list[Statement]
    total_statements: int
    total_chars: int
    bridge: bool  # a chosen statement touches both sides of the gap
    unrelated: bool  # nothing overlapped the focus; these are lead sentences

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.chosen)

    @property
    def chars(self) -> int:
        return sum(len(s.text) for s in self.chosen)

    def coverage(self) -> str:
        return f"{len(self.chosen)} of {self.total_statements} statements · {self.chars} of {self.total_chars} chars"

    def verify(self, source: str) -> tuple[int, int]:
        """Citations that still resolve to the exact text at their offsets.

        This is the only guarantee deterministic code can give: the span is
        real and unedited. It is not a claim that the span *supports* the idea -
        entailment needs a model, and pretending otherwise is how citation UIs
        end up lying.
        """
        return (
            sum(1 for s in self.chosen if source[s.start : s.end].strip() == s.text),
            len(self.chosen),
        )


def gist(
    text: str,
    focus_a: list[str] | tuple[str, ...] = (),
    focus_b: list[str] | tuple[str, ...] = (),
    k: int = 2,
    min_chars: int = 40,
) -> Gist:
    """The compression filter, deterministic.

    Score a statement by how much of the *current focus* it carries, with a
    bonus when one statement touches both sides of a gap - that sentence is the
    bridge, and it is the only one worth putting in front of a reader. No model,
    no embeddings: `nodus.concepts()` already normalised the text, so overlap is a set
    intersection. The research says retrieval-only selection is a good first
    stage and not a final answer writer, so this returns *quotes*, never prose.
    """
    ss = statements(text, min_chars=min_chars)
    A = {nodus.lemma(x) for x in focus_a if x}
    B = {nodus.lemma(x) for x in focus_b if x}
    if not ss:
        return Gist([], 0, len(text), False, True)
    for s in ss:
        s.concepts = nodus.concepts(s.text)

    scored: list[tuple[float, Statement]] = []
    for s in ss:
        cs = set(s.concepts)
        a_hit, b_hit = cs & A, cs & B
        if not (a_hit or b_hit):
            continue
        score = len(a_hit) + len(b_hit) + (3.0 if (a_hit and b_hit) else 0.0)
        s.matched = sorted(a_hit | b_hit)
        scored.append((score / (1 + len(s.text) / 1200), s))

    if not scored:
        lead = ss[:k]
        return Gist(lead, len(ss), len(text), False, True)

    scored.sort(key=lambda p: -p[0])
    # read in document order: a gist selected by score but printed out of
    # sequence is harder to read than the paragraph it replaced
    chosen = sorted((s for _, s in scored[:k]), key=lambda s: s.start)
    bridge = any(
        (set(s.concepts) & A) and (set(s.concepts) & B) for s in chosen
    )
    return Gist(chosen, len(ss), len(text), bridge, False)
