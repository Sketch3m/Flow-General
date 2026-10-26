"""
nodus.py - the core of a text-network gap finder, in ~460 lines.

InfraNodus, stripped to what actually does the work. The 23 MB open-source
repo is: Express + EJS + jQuery + Sigma.js (13 MB of it is images/vendor
JS), a Neo4j 3.3 server, passport/bcrypt auth, chargebee billing, and
importers for Twitter, Evernote, IMAP, YouTube, RSS and Google. None of
that is the idea. The idea is this pipeline:

    text -> concepts -> weighted co-occurrence graph -> communities
         -> weakly-connected important community pairs == structural gaps

Everything here is deterministic, has no server, and needs only networkx.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import combinations

import networkx as nx

WINDOW = 4  # InfraNodus' "scan gap": how far apart two words can be and connect
ADJ_W = 3  # a pair that touches gets weight 3, one word apart 2, two apart 1
BRIDGED = 0.25  # porosity above this = the divide is already spanned
CLUSTER_CAP = 14  # only the most influential clusters get paired up
PAIR_CAP = 18  # strongest nodes per side when searching for the absent link

STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren as at be because been
    before being below between both but by can cannot could couldn did didn do does
    doesn doing don down during each few for from further had hadn has hasn have haven
    having he her here hers herself him himself his how i if in into is isn it its
    itself just let me more most mustn my myself no nor not of off on once only or
    other ought our ours ourselves out over own same shan she should shouldn so some
    such than that the their theirs them themselves then there these they this those
    through to too under until up very was wasn we were weren what when where which
    while who whom why will with won would wouldn you your yours yourself yourselves
    also may might much many one two three get got make made way thing things really
    want need like use used using new now first last even still however since every
    high low tool keep stay put together side list number whole enough just rather
    work works something anything everything someone anyone thin
    whatever whenever whichever whoever nobody somebody everyone anyone
    nothing become becomes became seem seems seemed say says said see sees seen
    know knows think thinks find finds found tell tells ask asks call calls
    try tries take takes give gives come comes let lets put puts move moves
    already almost often sometimes usually maybe perhaps actually basically
    simply exactly quite pretty lot lots
    currently different quickly available happens around oldest next
    asking making taking giving coming getting going seeing knowing thinking
    working trying calling saying telling finding keeping letting running
    becoming
    """.split()
)

_TOKEN = re.compile(r"[#@]?[a-z][a-z0-9'\-]*")
_URL = re.compile(r"https?://\S+")
_FENCE = re.compile(r"```.*?```", re.S)


def lemma(word: str) -> str:
    """Cheap suffix stripping. Not linguistics - just enough to merge plurals
    and gerunds so 'citations' and 'citation' are one node. Conservative on
    purpose: a real lemmatizer (spaCy/nltk) is a 40 MB dependency we skip."""
    w = word
    if len(w) > 5 and w.endswith(("ies", "ied")):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ses"):
        return w[:-2]
    if len(w) > 6 and w.endswith(("ing", "edly")):
        return w[:-3] if w.endswith("ing") else w[:-4]
    if len(w) > 5 and w.endswith("ed") and not w.endswith(("eed", "red")):
        return w[:-2]
    if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is", "as")):
        return w[:-1]
    return w


def concepts(text: str, stopwords: frozenset[str] = STOPWORDS, min_len: int = 3) -> list[str]:
    """Raw text -> the ordered list of concept lemmas the graph is built from."""
    text = _FENCE.sub(" ", text)
    text = _URL.sub(" ", text.lower())
    out = []
    for tok in _TOKEN.findall(text):
        if len(tok) < min_len or tok.isdigit():
            continue
        # Filter the lemma *and* the raw token. The lemma alone lets 'needs'
        # through as 'need'; the raw alone lets 'nothing' survive as 'noth'.
        w = tok if tok[0] in "#@" else lemma(tok)
        if w in stopwords or tok in stopwords:
            continue
        out.append(w)
    return out


def build_graph(cs: list[str], window: int = WINDOW, min_freq: int = 2) -> nx.Graph:
    """Concept sequence -> undirected weighted graph.

    Edge weight reproduces InfraNodus' scan gap: neighbouring concepts weigh 3,
    one concept apart 2, two apart 1. Repeated co-occurrence accumulates."""
    freq = Counter(cs)
    keep = {c for c, n in freq.items() if n >= min_freq}
    g = nx.Graph()
    # sorted, not set order: insertion order feeds Louvain's RNG, so iterating a
    # set here made the whole pipeline non-deterministic across processes
    for c in sorted(keep):
        g.add_node(c, freq=freq[c])
    for i, c in enumerate(cs):
        if c not in keep:
            continue
        for d in range(1, window):
            j = i + d
            if j >= len(cs):
                break
            other = cs[j]
            if other not in keep or other == c:
                continue
            w = ADJ_W + 1 - d
            if g.has_edge(c, other):
                g[c][other]["weight"] += w
                g[c][other]["count"] += 1
            else:
                g.add_edge(c, other, weight=w, count=1)
    return g


def _strength(g: nx.Graph) -> dict[str, float]:
    """Total incident weight per node, the denominator in weighted RA."""
    return {n: sum(d["weight"] for _, _, d in g.edges(n, data=True)) or 1.0 for n in g.nodes}


def resource_allocation(g: nx.Graph, u: str, v: str, s: dict[str, float]) -> float:
    """Weighted Resource Allocation (Zhu & Xia 2016).

    RA(u,v) = sum over shared neighbours z of (w_uz + w_zv) / s_z. This is a
    missing-link score, unlike betweenness, which measures paths through edges
    that already exist. On lexical co-occurrence graphs RA is reported to far
    outperform Adamic-Adar and common neighbours for predicting held-out links,
    which is why it leads here; AA is kept as the comparison.
    """
    common = set(g[u]) & set(g[v])
    if not common:
        return 0.0
    # sorted: summing a set varies with hash randomisation, and the last-bit
    # differences are enough to reorder gaps between runs
    return sum((g[u][z]["weight"] + g[v][z]["weight"]) / s[z] for z in sorted(common))


def adam_adar(g: nx.Graph, u: str, v: str) -> float:
    common = set(g[u]) & set(g[v])
    return sum(1.0 / math.log(max(len(g[z]), 2)) for z in sorted(common)) if common else 0.0


def profiles(g: nx.Graph) -> dict[str, dict[str, float]]:
    """Each concept as an L2-normalised vector of its own edge weights.

    This is the space kNN and kFN operate in. A concept is defined by what it
    keeps company with, so no embedding model is needed and nothing here is
    stochastic: the profile *is* the co-occurrence structure, normalised.
    """
    out: dict[str, dict[str, float]] = {}
    for n in g.nodes:
        v = {m: d["weight"] for m, d in g[n].items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out[n] = {m: x / norm for m, x in v.items()}
    return out


def cosine(p: dict[str, float], q: dict[str, float]) -> float:
    if len(p) > len(q):
        p, q = q, p
    return sum(x * q.get(m, 0.0) for m, x in p.items())


def knn(a: Analysis, term: str, k: int = 5) -> list[tuple[str, float]]:
    """k nearest concepts by profile, ignoring pairs that already touch.

    These are the links the vocabulary implies but the document never makes.
    """
    t = lemma(term.lower())
    p = a.profiles.get(t)
    if not p:
        return []
    scored = sorted(
        (
            (cosine(p, q), m)
            for m, q in a.profiles.items()
            if m != t and m not in p and not a.graph.has_edge(t, m)
        ),
        reverse=True,
    )
    return [(m, round(s, 3)) for s, m in scored[:k]]


def kfn(a: Analysis, term: str, k: int = 3) -> list[tuple[str, float]]:
    """k furthest concepts: the vocabulary this one shares least with.

    Useful as a diversity check - if a section's key terms all sit at the far
    end from the document's centre of mass, the document is not one argument.
    """
    t = lemma(term.lower())
    p = a.profiles.get(t)
    if not p:
        return []
    scored = sorted((cosine(p, q), m) for m, q in a.profiles.items() if m != t)
    return [(m, round(s, 3)) for s, m in scored[:k]]


def position_profiles(
    cs: list[str], nodes: set[str], bins: int = 8
) -> dict[str, list[float]]:
    """Where in the document each concept lives, as a normalised histogram.

    'Temporal' geometry in a single document is positional: the sequence index
    is the only time axis available. Two themes that occupy opposite ends of
    the page are structurally apart even if their vocabulary overlaps.
    """
    n = len(cs) or 1
    raw: dict[str, list[float]] = {}
    for i, c in enumerate(cs):
        if c in nodes:
            raw.setdefault(c, []).append(i / n)
    out: dict[str, list[float]] = {}
    for c, ps in raw.items():
        h = [0.0] * bins
        for p in ps:
            h[min(bins - 1, int(p * bins))] += 1
        norm = math.sqrt(sum(x * x for x in h)) or 1.0
        out[c] = [x / norm for x in h]
    return out


def null_deficits(
    cs: list[str], nodes: set[str], window: int = WINDOW, block: int = 0, seed: int = 7
) -> dict[tuple[str, str], float]:
    """Expected-but-absent co-occurrence, as a z-score.

    Peng et al. define a knowledge gap as a pair that *should* co-occur and
    never does (expected >= 10, observed 0), which is a sharper definition than
    'low edge weight'. Their expectation is an independence formula over a
    corpus; inside one document the honest equivalent is a null model.

    A fully random shuffle would destroy local syntax and make every topical
    pair look surprising, so this shuffles **blocks** of the concept sequence:
    word order inside a stretch of text survives, the long-range arrangement
    does not. Pairs that are neighbours by grammar stay put; pairs that are only
    'near' because the document is laid out a certain way get a chance to move.

    z = (E[observed] - observed) / sd. Positive z means more absent than chance.
    """
    seq = [c for c in cs if c in nodes]
    if len(seq) < window * 4:
        return {}

    def counts(s: list[str]) -> Counter:
        c: Counter = Counter()
        for i, tok in enumerate(s):
            for d in range(1, window):
                j = i + d
                if j >= len(s):
                    break
                other = s[j]
                if other != tok:
                    c[tuple(sorted((tok, other)))] += 1  # type: ignore[index]
        return c

    # block size scales with the document: short texts need finer blocks or
    # there is nothing for the shuffle to disturb
    block = block or max(6, min(25, len(seq) // 16))
    obs = counts(seq)
    rng = random.Random(seed)
    trials = max(4, min(12, 4000 // max(1, len(seq))))
    total: Counter = Counter()
    total_sq: Counter = Counter()
    for _ in range(trials):
        blocks = [seq[i : i + block] for i in range(0, len(seq), block)]
        rng.shuffle(blocks)
        for pair, n in counts([t for b in blocks for t in b]).items():
            total[pair] += n
            total_sq[pair] += n * n

    out: dict[tuple[str, str], float] = {}
    for pair in set(obs) | set(total):
        e = total[pair] / trials
        if e <= 0:
            continue
        var = max(total_sq[pair] / trials - e * e, 1e-9)
        out[pair] = (e - obs.get(pair, 0)) / math.sqrt(var)
    return out


@dataclass
class Gap:
    """One structural gap: two important clusters that barely talk to each other."""

    score: float
    a: int
    b: int
    terms_a: list[str]
    terms_b: list[str]
    cross_weight: int
    distance: int | None
    bridge_terms: list[str]
    question: str
    surprise: float = 0.0  # expected-but-absent co-occurrence, max z over cross pairs
    ra: float = 0.0  # best weighted resource-allocation score across the divide
    aa: float = 0.0  # Adamic-Adar, kept as the comparison RA is chosen over
    tension: float = 0.0  # kNN-profile cosine of the missing pair (0..1)
    offset: float = 0.0  # positional distance between the clusters (0..1)
    missing: tuple[str, str] | None = None  # the absent link the numbers describe
    porosity: float = 0.0  # cross weight as a share of the thinner side

    @property
    def id(self) -> str:
        return f"{self.terms_a[0] if self.terms_a else '?'}~{self.terms_b[0] if self.terms_b else '?'}"

    @property
    def bridged(self) -> bool:
        """Already well connected across the divide: not a hole, a seam."""
        return self.porosity >= BRIDGED

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "score": round(self.score, 4),
            "cluster_a": self.terms_a,
            "cluster_b": self.terms_b,
            "cross_weight": self.cross_weight,
            "porosity": round(self.porosity, 3),
            "bridged": self.bridged,
            "distance": self.distance,
            "bridge_terms": self.bridge_terms,
            "missing": list(self.missing) if self.missing else None,
            "surprise": round(self.surprise, 2),
            "ra": round(self.ra, 3),
            "aa": round(self.aa, 3),
            "tension": round(self.tension, 3),
            "offset": round(self.offset, 3),
            "question": self.question,
        }


@dataclass
class Discourse:
    """InfraNodus' four-way discourse diagnosis, with the numbers behind it.

    A text network can be read like a conversation: how many topics get
    attention, whether one of them takes most of it, and whether the topics are
    actually joined up. Those two axes - concentration and cohesion - give the
    four names the original tool uses, and unlike a label alone they can be
    argued with.

        concentration = share of all edge weight held by the largest cluster
        cohesion      = modularity (are the clusters really separate?)
        diversity     = normalised entropy of attention across clusters (0..1)
        polarity      = how disconnected the two heaviest clusters are (0..1)
    """

    diversity: float
    concentration: float
    cohesion: float
    polarity: float
    label: str
    attention: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "diversity": round(self.diversity, 3),
            "concentration": round(self.concentration, 3),
            "cohesion": round(self.cohesion, 3),
            "polarity": round(self.polarity, 3),
            "attention": [(t, round(s, 3)) for t, s in self.attention[:5]],
        }


@dataclass
class Analysis:
    graph: nx.Graph
    clusters: list[list[str]] = field(default_factory=list)
    betweenness: dict[str, float] = field(default_factory=dict)
    modularity: float = 0.0
    label: str = "empty"
    gaps: list[Gap] = field(default_factory=list)
    n_concepts: int = 0
    null: dict = field(default_factory=dict)
    strength: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)
    discourse: Discourse | None = None

    def summary(self) -> dict:
        g = self.graph
        out = {
            "concepts": self.n_concepts,
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "density": round(nx.density(g), 4) if g.number_of_nodes() > 1 else 0.0,
            "modularity": round(self.modularity, 3),
            "clusters": len(self.clusters),
            "structure": self.label,
            "gaps": len(self.gaps),
        }
        if self.discourse is not None:
            out.update({k: v for k, v in self.discourse.to_dict().items() if k != "attention"})
        return out


def _betweenness(g: nx.Graph, seed: int = 7) -> dict[str, float]:
    """Exact on small graphs, sampled above ~600 nodes.

    Betweenness is O(nm); on a 200-document corpus it is minutes of wall clock
    for a number that only ever gets multiplied and square-rooted. Above the
    threshold the estimator is seeded, so the pipeline stays deterministic.
    """
    if g.number_of_nodes() > 600:
        return nx.betweenness_centrality(g, normalized=True, k=260, seed=seed)
    return nx.betweenness_centrality(g, normalized=True)


def analyse(
    text: str | None = None,
    cs: list[str] | None = None,
    window: int = WINDOW,
    min_freq: int = 2,
    max_gaps: int = 6,
    min_cluster: int = 2,
    seed: int = 7,
    resolution: float = 1.0,
) -> Analysis:
    """The whole engine. Deterministic for a given text and seed."""
    cs = concepts(text) if cs is None else cs
    g = build_graph(cs, window=window, min_freq=min_freq)
    if g.number_of_nodes() < 4:
        return Analysis(graph=g, n_concepts=len(cs))

    bc = _betweenness(g, seed)
    comms = [
        sorted(c)
        for c in nx.community.louvain_communities(
            g, weight="weight", seed=seed, resolution=resolution
        )
    ]
    comms.sort(key=lambda c: sum(bc[n] for n in c), reverse=True)
    modularity = nx.community.modularity(g, comms, weight="weight")
    d = discourse(g, comms, modularity)

    a = Analysis(
        graph=g,
        clusters=comms,
        betweenness=bc,
        modularity=modularity,
        label=d.label,
        discourse=d,
        n_concepts=len(cs),
        strength=_strength(g),
        null=null_deficits(cs, set(g.nodes)),
        profiles=profiles(g),
        positions=position_profiles(cs, set(g.nodes)),
    )
    a.gaps = find_gaps(a, max_gaps=max_gaps, min_cluster=min_cluster)
    return a


@dataclass
class Layers:
    """One graph, two resolutions. The human layer is built *out of* the machine
    layer, never summarised from it.

    A human can hold a handful of regions; a model can hold dozens of clusters
    and every absent pair inside them. So the readable regions are merges of
    the fine clusters, which makes the relationship checkable by construction:
    every fine cluster belongs to exactly one region, every node appears once,
    and anything named on the page resolves down into the evidence.
    """

    machine: Analysis
    human: Analysis

    def resolve(self, region: int) -> list[int]:
        """Machine cluster ids inside one human region."""
        hset = set(self.human.clusters[region])
        return [k for k, c in enumerate(self.machine.clusters) if hset & set(c)]

    def nesting(self) -> list[dict]:
        return [
            {
                "region": h,
                "label": c[0] if c else "?",
                "terms": c[:6],
                "size": len(c),
                "clusters": self.resolve(h),
            }
            for h, c in enumerate(self.human.clusters)
        ]

    def consistent(self) -> bool:
        """Every machine cluster lands in exactly one region, and no node is lost."""
        owner = {}
        for n in self.machine.graph.nodes:
            hits = [h for h, c in enumerate(self.human.clusters) if n in c]
            if len(hits) != 1:
                return False
            owner[n] = hits[0]
        for c in self.machine.clusters:
            if len({owner[n] for n in c if n in owner}) != 1:
                return False
        return True


def layers(
    a: Analysis, resolution: float = 1.7, target: int | None = None, seed: int = 7
) -> Layers:
    """Split one analysis into a fine machine layer and a coarse human layer.

    Fine clusters come from Louvain at a higher resolution. Regions are then
    merged greedily by the strongest weight crossing between them, so the two
    layers are the same graph at two scales rather than two opinions about it.
    """
    g = a.graph
    if g.number_of_nodes() < 4:
        return Layers(machine=a, human=a)

    fine = [
        sorted(c)
        for c in nx.community.louvain_communities(
            g, weight="weight", seed=seed, resolution=resolution
        )
    ]
    fine.sort(key=lambda c: sum(a.betweenness.get(n, 0.0) for n in c), reverse=True)
    machine = replace(a, clusters=fine, gaps=[])
    machine.gaps = find_gaps(machine, max_gaps=min(16, max(8, len(fine))), min_cluster=2)

    # Regions are built smallest-first: the stragglers get absorbed into
    # whatever they mostly talk to, and two large clusters are never welded
    # together. Merging by raw cross weight instead produces one blob that
    # swallows the map and hides exactly the divisions worth looking at.
    target = target or min(5, len(fine))
    groups = [list(c) for c in fine]
    cross: dict[tuple[int, int], float] = {}
    while len(groups) > target:
        cross.clear()
        owner = {n: i for i, c in enumerate(groups) for n in c}
        for u, v, d in g.edges(data=True):
            i, j = owner[u], owner[v]
            if i != j:
                k = (min(i, j), max(i, j))
                cross[k] = cross.get(k, 0.0) + d["weight"]
        if not cross:
            break
        small = min(range(len(groups)), key=lambda k: (len(groups[k]), k))
        near = [(w / (len(groups[small]) * len(groups[o])), o) for (i, j), w in cross.items()
                for o in ([j] if i == small else [i] if j == small else [])]
        if not near:
            break
        _, dst = max(near)
        merged = groups[small] + groups[dst]
        groups.pop(max(small, dst))
        groups[min(small, dst)] = merged
    groups.sort(key=lambda c: -sum(a.betweenness.get(n, 0.0) for n in c))
    # Regions carry no gaps of their own: a gap is a claim about two fine
    # clusters and the exact pair missing between them, and coarsening it would
    # throw away the only part that can be checked.
    human = replace(a, clusters=[sorted(c) for c in groups], gaps=[])
    return Layers(machine=machine, human=human)


def discourse(g: nx.Graph, clusters: list[list[str]], modularity: float) -> Discourse:
    """The four-way read: how attention is spread, and whether it is joined up.

    Concentration decides between the two concentrated readings and the two
    spread ones; modularity decides whether the clusters are genuinely separate.
    That is the 2x2 InfraNodus describes, with the thresholds stated instead of
    implied:

        concentrated + cohesive    -> focused       one theme, well argued
        concentrated + loose       -> biased        one theme, everything else unattached
        spread       + cohesive    -> diversified   many themes, each coherent
        spread       + loose       -> dispersed     many themes, none joined
    """
    if not clusters:
        return Discourse(0.0, 0.0, 0.0, 0.0, "empty")

    weights = [sum(sum(d["weight"] for _, _, d in g.edges(n, data=True)) for n in c) for c in clusters]
    total = sum(weights) or 1.0
    shares = [w / total for w in weights]
    k = len(shares)
    entropy = -sum(p * math.log(p) for p in shares if p > 0)
    diversity = entropy / math.log(k) if k > 1 else 0.0
    concentration = max(shares)

    # polarity is measured between the two clusters that hold the attention,
    # because a disconnected pair nobody writes about is not a divide, it is
    # two footnotes.
    order = sorted(range(k), key=lambda i: -weights[i])[:2]
    owner = {n: i for i, c in enumerate(clusters) for n in c}
    cross = 0.0
    if len(order) == 2:
        cross = sum(
            d["weight"]
            for u, v, d in g.edges(data=True)
            if {owner[u], owner[v]} == set(order)
        )
    thin = min((weights[i] for i in order), default=1.0) / 2 or 1.0
    polarity = max(0.0, 1.0 - min(1.0, cross / thin))

    if concentration >= 0.5:
        label = "focused" if modularity >= 0.3 else "biased"
    else:
        label = "diversified" if modularity >= 0.3 else "dispersed"

    attention = [
        (sorted(c, key=lambda n: -g.nodes[n]["freq"])[0], shares[i])
        for i, c in enumerate(clusters)
        if c
    ]
    attention.sort(key=lambda t: -t[1])
    return Discourse(
        diversity=round(diversity, 3),
        concentration=round(concentration, 3),
        cohesion=round(modularity, 3),
        polarity=round(polarity, 3),
        label=label,
        attention=attention,
    )


_SENT_END = re.compile(r"(?<=[.!?])\s+")


def _statement_spans(text: str) -> list[str]:
    """Sentence-ish splits for the statement layer.

    Deliberately local rather than imported from gist: gist imports nodus, and
    a shared splitter would make the dependency circular. Offsets are not
    needed here - these spans are *candidates* for a human to read, not citable
    units, which is gist's job.
    """
    masked = _FENCE.sub(lambda m: " " * len(m.group()), text)
    # the dialog's own markup is not prose. "::: code" blocks and their bodies
    # would otherwise win the closeness score by being dense keyword soup.
    masked = re.sub(r"(?m)^:::.*$", "", masked)
    out = []
    for chunk in _SENT_END.split(masked):
        s = chunk.strip()
        if not 40 <= len(s) <= 900:
            continue
        if s.startswith(("#", "|", ">", ":::", "```")) or "\n:::" in s:
            continue
        out.append(s)
    return out


def _centroid(a: Analysis, terms: list[str]) -> dict[str, float]:
    v: dict[str, float] = {}
    for t in terms:
        for m, x in a.profiles.get(t, {}).items():
            v[m] = v.get(m, 0.0) + x
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {m: x / n for m, x in v.items()}


def bridge_candidates(text: str, a: Analysis, gap: Gap, k: int = 2) -> list[dict]:
    """Statements closest to the missing link, whether or not they cross it.

    This is the statement layer InfraNodus annotates and the page did not have:
    a gap says two clusters never meet, and this says which sentences come
    nearest to joining them. Scored by cosine to the two cluster centroids in
    the same space kNN uses, so a candidate is one sentence away from being the
    bridge rather than merely nearby.

    A sentence that already touches both sides is skipped: if it existed the
    clusters would have an edge, and re-reading it teaches nobody anything.
    """
    ca, cb = _centroid(a, gap.terms_a[:8]), _centroid(a, gap.terms_b[:8])
    if not ca or not cb:
        return []
    side_a, side_b = set(gap.terms_a), set(gap.terms_b)
    scored = []
    for s in _statement_spans(text):
        cs = [c for c in concepts(s) if c in a.graph]
        if len(set(cs)) < 3:
            continue
        touched = set(cs)
        if touched & side_a and touched & side_b:
            continue
        vec: dict[str, float] = {}
        for c in cs:
            for m, x in a.profiles.get(c, {}).items():
                vec[m] = vec.get(m, 0.0) + x
        n = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        vec = {m: x / n for m, x in vec.items()}
        da, db = cosine(vec, ca), cosine(vec, cb)
        scored.append(
            {
                "text": s,
                "closeness": round(da + db, 3),
                "leans": "a" if da > db else "b",
                "terms": sorted(touched & (side_a | side_b))[:6],
            }
        )
    scored.sort(key=lambda d: -d["closeness"])
    return scored[:k]


def question_set(gap: Gap) -> list[dict]:
    """The three questions Nodus generates for a gap, not just one.

    Develop pushes on one side, connect asks for the join, explore asks what is
    absent. Keeping the triad matters: a single "how does A relate to B" reads
    as a homework question, while the three together give a writer somewhere to
    start whichever way they think.
    """
    # Name the absent pair, not the cluster labels. "How does sentence connect
    # to reply" is a question about the schema; "what would connect window to
    # citation" is a question about the argument, and it is the same pair the
    # evidence was computed on.
    if gap.missing:
        a, b = gap.missing
    else:
        a = gap.terms_a[0] if gap.terms_a else "?"
        b = gap.terms_b[0] if gap.terms_b else "?"
    return [
        {"mode": "develop", "prompt": f"What does {a} imply that this document has not said yet?"},
        {"mode": "connect", "prompt": f"What would connect {a} to {b}?"},
        {"mode": "explore", "prompt": f"What is missing between {a} and {b}?"},
    ]


def find_gaps(a: Analysis, max_gaps: int = 6, min_cluster: int = 2) -> list[Gap]:
    """Rank community pairs by importance over connection.

    A gap is not 'two high-betweenness words'. It is two clusters that each
    carry influence but share almost no edges - the missing link is the thing
    worth researching. score = importance / (1 + log(1 + cross weight)).
    """
    g = a.graph
    bc = a.betweenness
    owner = {n: i for i, c in enumerate(a.clusters) for n in c}
    cluster_of = [c for c in a.clusters]
    infl = [sum(bc[n] for n in c) for c in cluster_of]
    if not any(infl):
        # Betweenness is identically zero on a graph with no bridges at all -
        # which is the *most* disconnected case, not the least important one.
        # Falling back to how much of the text each cluster holds keeps those
        # holes scoreable instead of ranking them all at 0.
        total = sum(g.nodes[n].get("freq", 0) for n in g) or 1
        infl = [sum(g.nodes[n].get("freq", 0) for n in c) / total for c in cluster_of]

    cross: Counter[tuple[int, int]] = Counter()
    for u, v, d in g.edges(data=True):
        i, j = owner[u], owner[v]
        if i != j:
            cross[(min(i, j), max(i, j))] += d["weight"]

    # internal weight per cluster: the denominator porosity is measured
    # against. Cheap to compute once, and it is what separates "these two
    # subjects never meet" from "these two subjects meet constantly and the
    # graph just happens to have cut them into two colours".
    internal = [0.0] * len(cluster_of)
    for u, v, d in g.edges(data=True):
        if owner[u] == owner[v]:
            internal[owner[u]] += d["weight"] / 2

    def cross_stats(i: int, j: int) -> tuple[float, float, float, tuple[str, str] | None]:
        """The single absent link that best explains this divide.

        One pair, three numbers, all describing *that* pair. Taking the max of
        z, RA and tension independently lets a card quote three different
        missing links at once, which reads as evidence for a claim nobody
        computed. The pair is chosen by RA * (1 + z) * (0.5 + tension) and its
        own three numbers are reported.

        Pairs that already have an edge are skipped: they are not missing links.
        """
        best = (0.0, 0.0, 0.0, None)
        best_key = -1.0
        side_a = sorted(cluster_of[i], key=lambda n: -a.strength[n])[:PAIR_CAP]
        side_b = sorted(cluster_of[j], key=lambda n: -a.strength[n])[:PAIR_CAP]
        for u in side_a:
            for v in side_b:
                if g.has_edge(u, v):
                    continue
                z = max(0.0, a.null.get((min(u, v), max(u, v)), 0.0))
                ra = resource_allocation(g, u, v, a.strength)
                t = cosine(a.profiles[u], a.profiles[v])
                key = ra * (1 + z) * (0.5 + t)
                if key > best_key:
                    best_key = key
                    best = (z, ra, t, (u, v))
        return best

    def cluster_span(i: int, j: int) -> float:
        """How far apart in the document the two clusters sit, 0..1.

        Pools each cluster's position histogram, then cosine-compares them. A
        gap at opposite ends of the page is a layout problem; a gap in the
        middle is an argument problem.
        """
        def pooled(c: list[str]) -> list[float]:
            v = [0.0] * len(next(iter(a.positions.values()), []))
            if not v:
                return v
            for n in c:
                for k, x in enumerate(a.positions.get(n, [])):
                    v[k] += x
            s = math.sqrt(sum(x * x for x in v)) or 1.0
            return [x / s for x in v]

        pa, pb = pooled(cluster_of[i]), pooled(cluster_of[j])
        if not pa or not pb:
            return 0.0
        return round(1.0 - sum(x * y for x, y in zip(pa, pb)), 3)

    def best_aa(i: int, j: int) -> float:
        return max(
            (
                adam_adar(g, u, v)
                for u in cluster_of[i][:PAIR_CAP]
                for v in cluster_of[j][:PAIR_CAP]
                if not g.has_edge(u, v)
            ),
            default=0.0,
        )

    # Rank by importance, then raise the divides that are actually empty. Only
    # the most influential clusters are worth pairing: on a 200-document corpus
    # every combination is thousands of pairs that no one will read.
    ranked_clusters = sorted(range(len(cluster_of)), key=lambda k: -infl[k])[:CLUSTER_CAP]
    scored = []
    for i, j in combinations(sorted(ranked_clusters), 2):
        if len(cluster_of[i]) < min_cluster or len(cluster_of[j]) < min_cluster:
            continue
        z, ra, tension, pair = cross_stats(i, j)
        shared = cross[(min(i, j), max(i, j))]
        thin = max(1.0, min(internal[i], internal[j]))
        porosity = shared / thin
        # influence x surprise x semantic tension, damped by what the two
        # clusters already share. Betweenness answers 'is this important',
        # z answers 'is its absence surprising', and the kNN profile cosine
        # answers 'do these clusters talk about the same thing in different
        # words' - which is the difference between a hole and two strangers.
        # (0.5 + tension) rather than (1 + tension): a pair with no semantic
        # overlap is two strangers, not a hole. Porosity is the third filter:
        # a divide crossed by a fifth of the thinner side's own weight is a
        # seam, and suggesting a bridge there wastes the writer's afternoon.
        s = (
            ((infl[i] * infl[j]) ** 0.5)
            * (1 + z)
            * (0.5 + tension)
            / ((1 + math.log1p(shared)) * (1 + 3 * porosity))
        )
        scored.append((s, i, j, z, ra, tension, best_aa(i, j), cluster_span(i, j), porosity, pair))
    ranked = sorted(scored, reverse=True)

    # Order a cluster by how representative each term is (frequency first, then
    # brokerage). Betweenness alone surfaces words like 'every' as a cluster's
    # label, which reads as noise in the generated question.
    def core(c: list[str]) -> list[str]:
        return sorted(c, key=lambda n: (-g.nodes[n]["freq"], -bc[n]))

    out: list[Gap] = []
    for score, i, j, z, ra, tension, aa, offset, porosity, pair in ranked[:max_gaps]:
        ca = core(cluster_of[i])
        cb = core(cluster_of[j])
        # nodes that touch both clusters are the candidate bridges
        bridges = [
            n
            for n in g.nodes
            if owner[n] != i
            and owner[n] != j
            and any(owner[m] == i for m in g[n])
            and any(owner[m] == j for m in g[n])
        ]
        distance = _hop_distance(g, ca, cb)
        a_term, b_term = ca[0], cb[0]
        out.append(
            Gap(
                score=score,
                a=i,
                b=j,
                terms_a=ca,
                terms_b=cb,
                cross_weight=cross[(min(i, j), max(i, j))],
                distance=distance,
                bridge_terms=sorted(bridges, key=lambda n: -bc[n])[:5],
                surprise=z,
                ra=ra,
                aa=aa,
                tension=tension,
                offset=offset,
                missing=pair,
                porosity=round(porosity, 3),
                question=(
                    f"How does {a_term} connect to {b_term}? {', '.join(ca[:3])} and "
                    f"{', '.join(cb[:3])} never appear together in this document - "
                    f"which claim would bridge them?"
                ),
            )
        )
    return out


def pair_gap(a: Analysis, x: str, y: str) -> dict | None:
    """Score an arbitrary pair, whether or not it made the ranked list.

    `find_gaps` reports the top pairs; a document formula needs to answer for
    whatever two terms the writer typed. Same formula, no special cases, and
    None when the terms are in one cluster or absent - which is a real answer.
    """
    tx, ty = lemma(x.lower()), lemma(y.lower())
    owner = {n: i for i, c in enumerate(a.clusters) for n in c}
    if tx not in owner or ty not in owner or owner[tx] == owner[ty]:
        return None
    i, j = owner[tx], owner[ty]
    infl = [sum(a.betweenness[n] for n in c) for c in a.clusters]
    cross = sum(
        d["weight"] for u, v, d in a.graph.edges(data=True) if {owner[u], owner[v]} == {i, j}
    )
    bridges = [
        n
        for n in a.graph.nodes
        if owner[n] not in (i, j)
        and any(owner[m] == i for m in a.graph[n])
        and any(owner[m] == j for m in a.graph[n])
    ]
    inner = {}
    for k in (i, j):
        inner[k] = sum(
            d["weight"] for u, v, d in a.graph.edges(data=True) if owner[u] == owner[v] == k
        ) / 2
    porosity = cross / max(1.0, min(inner.values()))
    z = max(0.0, a.null.get((min(tx, ty), max(tx, ty)), 0.0))
    tension = cosine(a.profiles.get(tx, {}), a.profiles.get(ty, {}))
    px, py = a.positions.get(tx, []), a.positions.get(ty, [])
    offset = round(1 - sum(u * v for u, v in zip(px, py)), 3) if px and py else 0.0
    return {
        "score": ((infl[i] * infl[j]) ** 0.5) * (1 + z) * (0.5 + tension)
        / (1 + math.log1p(cross)),
        "surprise": round(z, 2),
        "tension": round(tension, 3),
        "offset": offset,
        "ra": round(resource_allocation(a.graph, tx, ty, a.strength), 3),
        "aa": round(adam_adar(a.graph, tx, ty), 3),
        "porosity": round(porosity, 3),
        "shared edges": cross,
        "hops": _hop_distance(a.graph, [tx], [ty]),
        "bridges": ", ".join(sorted(bridges, key=lambda n: -a.betweenness[n])[:3]) or "none",
        "ranked": False,
    }


def describe(a: Analysis, term: str) -> dict | None:
    """Everything the document knows about one @mention, or None."""
    t = lemma(term.lower().lstrip("@"))
    if t not in a.graph:
        return None
    cluster = next((i for i, c in enumerate(a.clusters) if t in c), -1)
    peers = a.clusters[cluster] if cluster >= 0 else [t]
    return {
        "term": t,
        "cluster": cluster + 1,
        "seen": a.graph.nodes[t]["freq"],
        "influence": round(a.betweenness.get(t, 0.0), 3),
        "peers": ", ".join(sorted(peers, key=lambda n: -a.graph.nodes[n]["freq"])[:3]),
    }


def _hop_distance(g: nx.Graph, ca: list[str], cb: list[str]) -> int | None:
    """Shortest number of hops between two clusters, if connected at all."""
    frontier, seen, hops = set(ca), set(ca), 0
    while frontier and hops < 12:
        hops += 1
        nxt: set[str] = set()
        for n in frontier:
            for m in g[n]:
                if m in seen:
                    continue
                if m in cb:
                    return hops
                seen.add(m)
                nxt.add(m)
        frontier = nxt
    return None
