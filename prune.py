"""
prune.py - what a reader is allowed to skip, decided by the graph.

gist.py compresses one reply against one focus. This module answers the page
question instead, and it does so with three policies at once, because any one of
them alone lies in a different direction:

    cited          keep the sentence if it quotes text the corpus contains
                   (`truth.find`, exactly the gate cells.step already runs).
                   Alone: a reply that cites nothing survives as nothing, which
                   is right for a citation UI and wrong for a reply whose whole
                   value is the distinction it draws.
    gap-relevant   keep the sentence if it names terms on both sides of a gap
                   (`nodus` clusters). Alone: a reply that restates the gap in
                   one sentence and then says something unrelated looks empty.
    region quota   keep the best sentence per nodus region the reply passes
                   through. Alone: a reply is rewarded for touching many topics,
                   so a list of headings scores as well as an argument.

Together they still over-select, so the page budget is the last cut, and the
order of that cut is by score - which means a cited sentence is the last thing
dropped, never the first.

The output is a `Pruned`: kept statements in document order with the reason
each survived, what was cut, and a header line a cell can print. Nothing here
rewrites the text. Every kept statement is a slice of the original, so a reader
who expands it sees the model's own words, not a summary of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gist
import nodus
import truth


@dataclass
class Kept:
    """One surviving statement, with the reasons it survived."""

    text: str
    start: int
    idx: int
    reasons: tuple[str, ...]
    region: int | None
    score: float

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": self.start,
            "reasons": list(self.reasons),
            "region": self.region,
            "score": round(self.score, 3),
        }


@dataclass
class Pruned:
    """A reply after the three policies and the budget have had their say."""

    kept: list[Kept]
    total: int
    chars_in: int
    chars_out: int
    cited: int
    regions: list[int]
    dropped: list[Kept]
    budget: int
    over_budget: bool = False
    lead: bool = False

    @property
    def text(self) -> str:
        return " ".join(k.text for k in self.kept)

    @property
    def nothing(self) -> bool:
        return not self.kept

    def header(self) -> str:
        """The one line a cell prints. States what was cut, not only what is left."""
        if not self.total:
            return "no statements"
        parts = [
            f"{len(self.kept)}/{self.total} statements",
            f"{self.chars_out:,}/{self.chars_in:,} chars",
        ]
        if self.cited:
            parts.append(f"{self.cited} cited")
        if self.regions:
            parts.append(f"{len(self.regions)} region{'s' if len(self.regions) != 1 else ''}")
        parts.append(f"budget {self.budget:,}")
        if self.over_budget:
            parts.append("kept one over budget")
        if self.lead:
            parts.append("nothing bore on the gap: lede only")
        return " \u00b7 ".join(parts)

    def why(self, kept: Kept) -> str:
        return " \u00b7 ".join(kept.reasons) or "unexplained"


def _gap_terms(gap) -> tuple[set[str], set[str]]:
    """Terms on each side of the gap. Accepts a nodus.Gap or its dict form."""
    if gap is None:
        return set(), set()
    if isinstance(gap, dict):
        a = gap.get("terms_a") or ([gap["term_a"]] if gap.get("term_a") else [])
        b = gap.get("terms_b") or ([gap["term_b"]] if gap.get("term_b") else [])
    else:
        a = list(getattr(gap, "terms_a", []) or [])
        b = list(getattr(gap, "terms_b", []) or [])
    return {nodus.lemma(t) for t in a if t}, {nodus.lemma(t) for t in b if t}


def region_map(analysis=None, layers=None) -> dict[str, int]:
    """concept -> region index.

    `layers` wins when given, because the human layer is what a reader sees on
    the page (nodus merges fine clusters into <=5 regions). Otherwise the fine
    clusters stand in, so this module works on a bare Analysis.
    """
    clusters = None
    human = getattr(layers, "human", None) if layers is not None else None
    if human is not None and getattr(human, "clusters", None):
        clusters = human.clusters
    elif analysis is not None and getattr(analysis, "clusters", None):
        clusters = analysis.clusters
    if not clusters:
        return {}
    return {n: i for i, cl in enumerate(clusters) for n in cl}


def allocate(total: int, n: int, floor: int = 180) -> list[int]:
    """Split a page budget across n outputs, evenly, with a floor each.

    Even is deliberately dumb: weighting by cell length would give the longest,
    least-read output the biggest budget, which is the opposite of the point.
    """
    if n <= 0:
        return []
    total = max(int(total), n * floor)
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def prune(
    text: str,
    *,
    gap=None,
    analysis=None,
    layers=None,
    corpus: str = "",
    budget: int = 700,
    per_region: int = 1,
    min_chars: int = 40,
) -> Pruned:
    """Compress one model output against a gap, a corpus and a budget.

    Pure and deterministic: same text, same graph, same answer. No model is
    called, so a compressed cell is reproducible and its reasons are auditable.
    """
    ss = gist.statements(text, min_chars=min_chars)
    chars_in = len(text)
    if not ss:
        return Pruned([], 0, chars_in, 0, 0, [], [], budget)

    a_terms, b_terms = _gap_terms(gap)
    rmap = region_map(analysis, layers)

    rows: list[dict] = []
    for i, s in enumerate(ss):
        concepts = set(nodus.concepts(s.text))
        reasons: list[str] = []
        cited = False
        if corpus:
            for q in truth.spans(s.text):
                if truth.find(q, corpus)["found"]:
                    cited = True
                    reasons.append("cites the corpus")
                    break
        a_hit, b_hit = concepts & a_terms, concepts & b_terms
        if a_hit and b_hit:
            reasons.append("spans the gap")
        elif a_hit or b_hit:
            reasons.append("names one side")
        score = (
            len(a_hit)
            + len(b_hit)
            + (3.0 if (a_hit and b_hit) else 0.0)
            + (3.0 if cited else 0.0)
        )
        # same length discount as gist: a tight sentence that carries the idea
        # beats a long one that carries it plus padding
        score = score / (1 + len(s.text) / 1200)
        regs = [rmap[t] for t in concepts if t in rmap]
        region = max(set(regs), key=regs.count) if regs else None
        rows.append(
            {
                "idx": i,
                "stmt": s,
                "score": score,
                "reasons": reasons,
                "region": region,
                "cited": cited,
                "hit": bool(a_hit or b_hit),
            }
        )

    lead = False
    keep_idx: dict[int, None] = {r["idx"]: None for r in rows if r["reasons"]}
    if not keep_idx:
        # Nothing cited and nothing on the gap: show the opening, and say so.
        # Returning an empty cell would hide that the reply was off-topic.
        lead = True
        keep_idx = {rows[0]["idx"]: None}
        rows[0]["reasons"] = ["nothing bore on the gap"]

    # Region quota: every region the reply moves through gets one sentence,
    # even when nothing in that region cites anything. This is the policy that
    # stops a two-sentence gist from looking like the whole of a six-topic reply.
    by_region: dict[int, list[dict]] = {}
    for r in rows:
        if r["region"] is not None:
            by_region.setdefault(r["region"], []).append(r)
    for reg in sorted(by_region):
        for r in sorted(by_region[reg], key=lambda x: -x["score"])[: max(1, per_region)]:
            if r["idx"] not in keep_idx:
                keep_idx[r["idx"]] = None
                r["reasons"] = r["reasons"] + [f"only statement on region {reg}"]

    keep = [r for r in rows if r["idx"] in keep_idx]

    # The page budget is the last cut, by score, so a cited sentence goes last.
    dropped: list[dict] = []
    over_budget = False
    if budget and sum(len(r["stmt"].text) for r in keep) > budget:
        chosen: list[dict] = []
        used = 0
        for r in sorted(keep, key=lambda x: -x["score"]):
            if used + len(r["stmt"].text) <= budget:
                chosen.append(r)
                used += len(r["stmt"].text)
            elif not chosen:
                # one statement that alone exceeds the budget is still better
                # than an empty cell; it is reported, not hidden
                chosen.append(r)
                used += len(r["stmt"].text)
                over_budget = True
            else:
                dropped.append(r)
        keep = chosen

    keep.sort(key=lambda r: r["stmt"].start)
    kept = [
        Kept(
            text=r["stmt"].text,
            start=r["stmt"].start,
            idx=r["idx"],
            reasons=tuple(r["reasons"]),
            region=r["region"],
            score=round(r["score"], 3),
        )
        for r in keep
    ]
    lost = [
        Kept(
            text=r["stmt"].text,
            start=r["stmt"].start,
            idx=r["idx"],
            reasons=tuple(r["reasons"] + ["cut by the page budget"]),
            region=r["region"],
            score=round(r["score"], 3),
        )
        for r in sorted(dropped, key=lambda x: x["stmt"].start)
    ]
    return Pruned(
        kept=kept,
        total=len(ss),
        chars_in=chars_in,
        chars_out=sum(len(k.text) for k in kept),
        cited=sum(1 for r in keep if r["cited"]),
        regions=sorted({k.region for k in kept if k.region is not None}),
        dropped=lost,
        budget=budget,
        over_budget=over_budget,
        lead=lead,
    )
