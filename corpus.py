"""
corpus.py - many documents in, one ordered page out.

The point of importing two hundred proofs is not to read two hundred proofs. It
is that the *shape* of the pile tells you what the page should be: which
clusters exist, which documents cover which of them, which divisions nothing
spans, and which documents are the only evidence for something. That shape, not
a template, decides which cells the document gets and what order they come in.

Two layers throughout, because they answer different questions at different
scales:

    machine   fine clusters, every absent pair, all statements      -> agents
    human     a handful of regions, top moves, gist sentences       -> reading

The regions are merges of the fine clusters, never a second opinion about the
graph, so anything named on the page resolves down into the evidence behind it.

No model is called here. Every ordering decision is a rule over numbers that the
page also prints, so a reader can disagree with the order by checking it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import nodus


@dataclass
class Doc:
    name: str
    text: str
    concepts: list[str]

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Corpus:
    docs: list[Doc]
    layers: nodus.Layers
    covers: dict[str, dict[int, int]] = field(default_factory=dict)
    orphans: list[str] = field(default_factory=list)
    bridges: dict[tuple[int, int], list[str]] = field(default_factory=dict)

    @property
    def analysis(self) -> nodus.Analysis:
        return self.layers.machine

    def region_of(self, cluster: int) -> int:
        """Which human region a machine cluster sits in."""
        node = next((c for c in self.analysis.clusters[cluster]), None)
        if node is None:
            return -1
        for h, region in enumerate(self.layers.human.clusters):
            if node in region:
                return h
        return -1

    def coverage(self) -> list[dict]:
        """Documents against regions, biggest first."""
        rows = []
        for d in self.docs:
            hits = Counter()
            for c, n in self.covers.get(d.name, {}).items():
                hits[self.region_of(c)] += n
            total = sum(hits.values()) or 1
            rows.append(
                {
                    "doc": d.name,
                    "words": d.words,
                    "regions": len(hits),
                    "spread": round(max(hits.values()) / total, 2) if hits else 0.0,
                    "top": hits.most_common(1)[0][0] if hits else -1,
                }
            )
        rows.sort(key=lambda r: (-r["spread"], -r["regions"]))
        return rows

    def summary(self) -> dict:
        s = self.analysis.summary()
        return {
            **s,
            "docs": len(self.docs),
            "regions": len(self.layers.human.clusters),
            "orphans": len(self.orphans),
            "words": sum(d.words for d in self.docs),
        }


@dataclass
class Cell:
    """One thing the page should show, and why it earned the space."""

    kind: str
    title: str
    why: str
    payload: Any = None
    priority: float = 0.5


def organize(
    sources: list[tuple[str, str]],
    window: int = nodus.WINDOW,
    min_freq: int = 2,
) -> Corpus:
    """Documents -> one graph -> two resolutions -> coverage and bridges."""
    docs = []
    for name, text in sources:
        if text.strip():
            docs.append(Doc(name=name.strip() or "untitled", text=text, concepts=nodus.concepts(text)))
    if not docs:
        return Corpus(docs=[], layers=nodus.Layers(machine=nodus.Analysis(graph=_empty()), human=nodus.Analysis(graph=_empty())))

    cs = [c for d in docs for c in d.concepts]
    a = nodus.analyse(cs=cs, window=window, min_freq=min_freq)
    L = nodus.layers(a)
    owner = {n: i for i, c in enumerate(L.machine.clusters) for n in c}

    covers: dict[str, dict[int, int]] = {}
    for d in docs:
        hits = Counter(owner[c] for c in set(d.concepts) if c in owner)
        covers[d.name] = dict(hits)

    # A document that touches one region heavily is a building block; one that
    # touches several evenly is a bridge between them. An orphan is neither: it
    # is a document the graph could not represent at all, because most of its
    # vocabulary fell below the frequency floor. Breadth is not orphanhood -
    # confusing the two flags every two-topic paper as lost.
    orphans, bridges = [], {}
    for d in docs:
        hits = covers[d.name]
        distinct = set(d.concepts)
        survived = len([c for c in distinct if c in owner]) / max(1, len(distinct))
        # A lone document loses most of its vocabulary to the frequency floor by
        # construction; that is the floor working, not the document failing.
        if not sum(hits.values()) or (len(docs) > 1 and survived < 0.35):
            orphans.append(d.name)
            continue
        for i in hits:
            for j in hits:
                if i < j:
                    bridges.setdefault((i, j), []).append(d.name)

    return Corpus(docs=docs, layers=L, covers=covers, orphans=orphans, bridges=bridges)


def plan(c: Corpus, dlg=None, records: dict | None = None) -> list[Cell]:
    """The page, derived from the corpus rather than from a template.

    Ordering is a consequence of the shape. A pile with no bridges leads with
    the hole; a pile where one document is the only witness for a region leads
    with that document; a pile with nothing organized yet leads with coverage.
    Re-import different documents and the same rules produce a different order.
    """
    cells: list[Cell] = []
    s = c.summary()
    a = c.analysis

    cells.append(
        Cell(
            kind="overview",
            title=f"{s['docs']} documents · {s['words']:,} words",
            why=(
                f"{s['nodes']} concepts, {s['edges']} edges, {s['clusters']} clusters at "
                f"machine resolution collapsing to {s['regions']} regions — "
                f"structure reads as {s['structure']}"
            ),
            payload=s,
            priority=1.0 if a.label != "dispersed" else 0.99,
        )
    )

    # 1. the hole. Highest weight when nothing spans it.
    for i, g in enumerate(a.gaps[:3]):
        span = len(c.bridges.get((min(g.a, g.b), max(g.a, g.b)), []))
        cells.append(
            Cell(
                kind="gap",
                title=f"{g.terms_a[0]} ~ {g.terms_b[0]}",
                why=(
                    f"cross-weight {g.cross_weight}, porosity {g.porosity:.2f} — "
                    + (
                        f"already spanned by {span} document{'s' if span != 1 else ''}, listed last"
                        if g.bridged
                        else "no document spans this divide"
                    )
                ),
                payload=g,
                priority=(0.62 + 0.30 * g.score) * (0.45 if g.bridged else 1.0) - i * 0.02,
            )
        )

    # 2. coverage: which documents are where. Leads when the pile is dispersed
    #    or when nothing has been organized yet.
    rows = c.coverage()
    if rows:
        lead = a.label in ("dispersed", "focused") or s["regions"] <= 2
        cells.append(
            Cell(
                kind="coverage",
                title="documents against regions",
                why=(
                    f"{sum(1 for r in rows if r['regions'] > 1)} of {len(rows)} documents "
                    f"are spread across more than one region; "
                    f"{sum(1 for r in rows if r['spread'] >= 0.8)} are single-region building blocks"
                ),
                payload=rows,
                priority=0.84 if lead else 0.44,
            )
        )

    # 3. the witness: documents that are the only coverage of some region.
    only = []
    for h in range(len(c.layers.human.clusters)):
        witnesses = [d for d in c.docs if any(c.region_of(k) == h for k in c.covers.get(d.name, {}))]
        if len(witnesses) == 1 and len(c.docs) > 1:
            only.append((h, witnesses[0].name))
    if only:
        cells.append(
            Cell(
                kind="witness",
                title=f"{len(only)} region{'s' if len(only) != 1 else ''} with a single witness",
                why="losing one document would remove a whole region from the graph",
                payload=only,
                priority=0.78 - 0.03 * len(only),
            )
        )

    # 4. documents the graph cannot place.
    if c.orphans:
        cells.append(
            Cell(
                kind="orphan",
                title=f"{len(c.orphans)} document{'s' if len(c.orphans) != 1 else ''} with no home region",
                why="either off-topic, too short to survive the frequency floor, or the start of a new region",
                payload=c.orphans,
                priority=0.70,
            )
        )

    # 5. the ledger, if there is one. Never first: it is the slowest thing here.
    if dlg is not None and getattr(dlg, "messages", None):
        cells.append(
            Cell(
                kind="ledger",
                title=f"the writing · {len(dlg.messages)} messages",
                why="prompts are never compressed; replies are held at the selected gap",
                payload=dlg,
                priority=0.55,
            )
        )

    if records is not None and a.gaps:
        cells.append(
            Cell(
                kind="decision",
                title=f"decision record · {a.gaps[0].id}",
                why="one claim, one source, one next step — filed against the top gap",
                payload=a.gaps[0],
                priority=0.30,
            )
        )

    cells.sort(key=lambda x: (x.kind != "overview", -x.priority))
    return cells


def _empty():
    import networkx as nx

    return nx.Graph()
