"""
decision.py - a detected gap becomes a durable, cited, decided record.

Note the naming, because it is easy to confuse two different things:

  SolveIt (Answer.AI, Jeremy Howard / Johno Whitaker / Eric Ries) is a
  *dialogue* environment - a document of notes, prompts and code. That is
  dialog.py. SolveIt has no decision artefact at all.

  This file is the thing SolveIt does not have: once research has happened, the
  answer is a record with alternatives, weights, confidence and citations,
  rather than a confident-sounding paragraph.

    frame -> decompose -> gather -> verify -> decide -> close

Six stages, each with required artefacts. `missing()` is the point: the record
cannot claim to be finished while evidence is uncited or the decision has no
alternatives. Nothing here calls a model - a human, a notebook cell or an LLM
can fill a stage, and the record is the same either way.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STAGES = ("frame", "decompose", "gather", "verify", "decide", "close")
SUPPORT = ("supports", "contradicts", "unclear")


@dataclass
class Claim:
    """One piece of evidence. `source` and `quote` are required before a claim
    counts as verified - a claim with no URL is a hypothesis, not evidence."""

    text: str
    source: str = ""
    quote: str = ""
    status: str = "unclear"
    claim_id: str = ""

    def verified(self) -> bool:
        return bool(self.source.strip() and self.quote.strip() and self.status in SUPPORT)


@dataclass
class Record:
    gap_id: str
    problem: str = ""
    subquestions: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    decision: str = ""
    confidence: float = 0.0
    rationale: str = ""
    alternatives: list[dict] = field(default_factory=list)
    next_evidence: list[str] = field(default_factory=list)
    stage: str = "frame"

    # ---- protocol checks -------------------------------------------------
    def missing(self) -> dict[str, list[str]]:
        """What each unfinished stage still owes. Empty dict == protocol complete."""
        gaps: dict[str, list[str]] = {}
        if not self.problem.strip():
            gaps["frame"] = ["problem statement (one sentence, falsifiable)"]
        if len(self.subquestions) < 2:
            gaps["decompose"] = ["at least two sub-questions"]
        cited = [c for c in self.claims if c.source.strip()]
        unsourced = [c for c in self.claims if not c.source.strip()]
        if not cited:
            gaps["gather"] = ["at least one claim with a source URL"]
        needs = []
        for c in unsourced:
            needs.append(f"claim {c.claim_id or c.text[:30]!r}: no source URL")
        for c in cited:
            if not c.quote.strip():
                needs.append(f"claim {c.claim_id or c.text[:30]!r}: no exact quote")
        if cited and not any(c.status == "supports" for c in cited):
            needs.append("one claim marked 'supports'")
        if needs:
            gaps["verify"] = needs
        decide_missing = []
        if not self.decision.strip():
            decide_missing.append("a decision, not a summary")
        if len(self.alternatives) < 2:
            decide_missing.append("at least two options that were weighed")
        if not 0.0 < self.confidence <= 1.0:
            decide_missing.append("a confidence between 0 and 1")
        if decide_missing:
            gaps["decide"] = decide_missing
        if not self.next_evidence:
            gaps["close"] = ["what evidence would change the answer"]
        return gaps

    def complete(self) -> bool:
        return not self.missing()

    def next_stage(self) -> str:
        gaps = self.missing()
        return next((s for s in STAGES if s in gaps), "close")

    # ---- evidence --------------------------------------------------------
    def add_claim(self, text: str, source: str = "", quote: str = "", status: str = "unclear") -> Claim:
        c = Claim(
            text=text.strip(),
            source=source.strip(),
            quote=quote.strip(),
            status=status if status in SUPPORT else "unclear",
            claim_id=f"c{len(self.claims) + 1}",
        )
        self.claims.append(c)
        return c

    def decide(self, decision: str, confidence: float, rationale: str, alternatives: list[dict],
               next_evidence: list[str]) -> None:
        self.decision, self.rationale = decision.strip(), rationale.strip()
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.alternatives = alternatives
        self.next_evidence = [n for n in next_evidence if n.strip()]
        self.stage = self.next_stage()

    # ---- io --------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        claims = [Claim(**c) for c in d.get("claims", [])]
        return cls(**{**d, "claims": claims})


def from_gap(gap) -> Record:
    """Seed a record from a structural gap. Deterministic: no model needed to
    open the protocol, only to answer it."""
    a = gap.terms_a[0] if gap.terms_a else "cluster A"
    b = gap.terms_b[0] if gap.terms_b else "cluster B"
    rec = Record(gap_id=gap.id, problem=gap.question)
    rec.subquestions = [
        f"What is already established about {a}?",
        f"What is already established about {b}?",
        f"Is there a mechanism that connects {a} and {b}, or only shared vocabulary?",
        f"What observation would falsify that connection?",
    ]
    if gap.bridge_terms:
        rec.subquestions.append(
            "Do the bridge terms (" + ", ".join(gap.bridge_terms[:3]) + ") carry the link, or only appear near it?"
        )
    rec.next_evidence = [
        f"a source that explicitly discusses both {a} and {b}",
        f"a counter-example where bridging {a} and {b} fails",
    ]
    return rec


def store_path(root: str | Path = "ledger") -> Path:
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p / "records.json"


def save(records: dict[str, Record], root: str | Path = "ledger") -> Path:
    path = store_path(root)
    path.write_text(json.dumps({k: r.to_dict() for k, r in records.items()}, indent=2))
    return path


def load(root: str | Path = "ledger") -> dict[str, Record]:
    path = store_path(root)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text() or "{}")
    return {k: Record.from_dict(v) for k, v in raw.items()}


def render_markdown(rec: Record) -> str:
    """The record as a document - this is what a dynamic document shows."""
    missing = rec.missing()
    status = "✅ protocol complete" if not missing else f"⏳ next: **{rec.next_stage()}**"
    lines = [f"### {rec.problem}", "", f"`{rec.gap_id}` · {status}", ""]

    lines += ["| # | sub-question |", "|---|---|"]
    lines += [f"| {i + 1} | {q} |" for i, q in enumerate(rec.subquestions)]

    lines += ["", "#### Evidence ledger", ""]
    if rec.claims:
        lines += ["| id | claim | status | source |", "|---|---|---|---|"]
        for c in rec.claims:
            src = f"[{_short(c.source)}]({c.source})" if c.source else "_none_"
            mark = {"supports": "🟢", "contradicts": "🔴"}.get(c.status, "⚪")
            lines.append(f"| {c.claim_id} | {c.text} | {mark} {c.status} | {src} |")
    else:
        lines.append("_no evidence gathered yet_")

    if rec.decision:
        lines += [
            "",
            "#### Decision",
            "",
            f"**{rec.decision}** — confidence {rec.confidence:.0%}",
            "",
            rec.rationale,
        ]
        if rec.alternatives:
            lines += ["", "| option | expected utility | downside |", "|---|---|---|"]
            for alt in rec.alternatives:
                lines.append(
                    f"| {alt.get('option', '')} | {alt.get('expected_utility', '')} | {alt.get('downside', '')} |"
                )

    if missing:
        lines += ["", "#### Still missing"]
        for stage, needs in missing.items():
            lines.append(f"- **{stage}**: " + "; ".join(needs))

    if rec.next_evidence:
        lines += ["", "#### What would change the answer", *[f"- {n}" for n in rec.next_evidence]]
    return "\n".join(lines)


def _short(url: str, n: int = 34) -> str:
    return url if len(url) <= n else url[: n - 1] + "…"
