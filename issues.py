"""
issues.py - one board, three sources, and the search each gap asks for.

The gap engine was built for prose. But "two parts of this thing never talk to
each other" is not a fact about prose; it is a fact about a graph, and the same
detector applies to three graphs that people actually work in:

    text      two topics that never co-occur        (nodus.find_gaps)
    code      modules with no import path between   (ast + import graph)
    tickets   open issues, located in the code      (GitHub REST)

The three become the same object here, an Issue, because the work on them is the
same work: name the absent link, gather the evidence on both sides, ask the
question that would close it, and search for the answer. That is why an issue
carries `queries` - a gap is not a task until you know what to look for.

What each source can and cannot claim:

  - text    "these clusters never co-occur" is measurable, and ontology.py
            upgrades it to "no typed relation crosses" - still a claim about the
            document, not about the world.
  - code    a *missing* import is not a defect by itself. No graph can know that
            an absent edge was intended. So only cycles, side-effect-free modules
            nothing imports, and fully detached modules are filed as defects
            (`confidence: 1.0`); a shared-vocabulary pair with no path between
            them is filed as a **candidate** with the falsifier written down.
  - github  a ticket is already a claim; the engine does not re-litigate it. It
            locates the ticket's vocabulary in the code graph, which is the part
            humans are slow at, and leaves state where GitHub keeps it.

Anything not in one of those three is out of scope, deliberately.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections import Counter
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

import nodus
import ontology

SKIP = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "__marimo__",
    ".models",
    "node_modules",
    "site-packages",
    ".mypy_cache",
    ".pytest_cache",
    "solve",
}

ENTRY = re.compile(r"if\s+__name__\s*==\s*[\"']__main__[\"']")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# A bridge candidate below this Jaccard overlap is not worth a card: identifiers
# in one language share a lot of words ("text", "file", "value") for free.
SHARED = 0.12

# The concept filter keeps a lot of prepositions and auxiliaries because they
# co-occur meaningfully; a card title does not want them. Only names change here -
# every number still belongs to the raw pair.
FUNCTION = {
    "without", "within", "between", "because", "while", "where", "which", "whose",
    "after", "before", "though", "through", "under", "above", "below", "against",
    "toward", "towards", "upon", "among", "around", "during", "since", "until",
    "unless", "however", "therefore", "thus", "also", "more", "most", "less",
    "least", "such", "same", "other", "another", "both", "each", "either",
    "neither", "every", "many", "much", "some", "only", "than", "then", "there",
    "here", "when", "what", "who", "whom", "why", "how", "into", "onto", "over",
    "does", "did", "doing", "being", "been", "have", "has", "had", "will",
    "would", "could", "should", "must", "might", "shall", "can", "may", "its",
    "their", "them", "they", "this", "that", "these", "those",
}
MIN_VOCAB = 14


# ---------------------------------------------------------------------------
# the object
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    """One checkable thing on one side of the gap."""

    kind: str  # statement | file | line | ticket
    text: str
    loc: str = ""  # s12 | app.py:40 | gh#31
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "loc": self.loc, "score": round(self.score, 3)}


@dataclass
class Issue:
    """A gap, whatever graph it came from, in the shape the work needs."""

    id: str
    source: str  # text | code | github
    title: str
    why: str
    labels: list[str] = field(default_factory=list)
    status: str = "open"  # open | solved | wontfix
    score: float = 0.0
    confidence: float = 1.0  # 1.0 only where the defect is decidable
    evidence: list[Evidence] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    confirm: str = ""  # what would show this is real (or not)
    numbers: dict = field(default_factory=dict)
    loc: str = ""
    ref: str = ""  # gh#31 | app.py

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["evidence"] = [e.to_dict() for e in self.evidence]
        d["score"] = round(self.score, 3)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Issue":
        d = dict(d)
        d["evidence"] = [Evidence(**e) for e in d.get("evidence", [])]
        return cls(**d)


def _id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:10]


def search(url_q: str) -> str:
    """A gap becomes solvable the moment it becomes a query."""
    return "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(url_q)


def _name_pair(gap: nodus.Gap) -> tuple[str, str]:
    """The absent link, named with content words when the raw pair is function words."""
    x, y = gap.missing or (gap.terms_a[0], gap.terms_b[0])
    if x in FUNCTION or len(x) < 4:
        x = next((t for t in gap.terms_a if t not in FUNCTION and len(t) > 3), x)
    if y in FUNCTION or len(y) < 4:
        y = next((t for t in gap.terms_b if t not in FUNCTION and len(t) > 3), y)
    return x, y


# ---------------------------------------------------------------------------
# source 1: the document
# ---------------------------------------------------------------------------


def from_text(text: str, max_gaps: int = 6) -> list[Issue]:
    """Every unbridged gap in one document, with the evidence from both sides."""
    a = nodus.analyse(text, max_gaps=max_gaps)
    rels = ontology.relations(text, set(a.graph.nodes))
    out: list[Issue] = []
    polarised = a.discourse is not None and a.discourse.polarity > 0.6

    for g in a.gaps:
        if g.bridged:
            continue
        x, y = _name_pair(g)
        cross = ontology.crossings(rels, set(g.terms_a), set(g.terms_b))
        nearest = nodus.bridge_candidates(text, a, g, k=2)
        ev = [
            Evidence("statement", b["text"][:300], ", ".join(b["terms"][:3]), b["closeness"])
            for b in nearest
            if b.get("text")
        ]
        ev += [Evidence("relation", f"{r.subject} {r.kind} {r.object}", "", 1.0) for r in cross[:3]]
        labels = ["gap", "text"] + (["polarised"] if polarised else [])
        out.append(
            Issue(
                id=_id("text", g.id),
                source="text",
                title=f"nothing links {x} to {y}",
                why=(
                    f"{len(g.terms_a)} and {len(g.terms_b)} concepts, "
                    f"{g.cross_weight} co-occurrences across the divide, "
                    f"gap score {g.score:.2f}"
                    + (f", {g.distance} hops apart" if g.distance else "")
                ),
                labels=labels,
                score=g.score,
                evidence=ev,
                queries=[
                    f"{x} {y}",
                    f"what connects {x} and {y}",
                    f"{x} {y} relationship evidence",
                ],
                confirm=(
                    f"a sentence stating a typed relation between {x} and {y}; "
                    f"today {len(rels)} typed relations, {len(cross)} crossing"
                ),
                numbers=g.to_dict(),
                loc=f"{x} x {y}",
                ref="document",
            )
        )
    return out


# ---------------------------------------------------------------------------
# source 2: the code itself
# ---------------------------------------------------------------------------


@dataclass
class Module:
    name: str
    path: str
    edges: list[tuple[str, int]] = field(default_factory=list)  # (target, line)
    external: int = 0
    defines: list[str] = field(default_factory=list)
    def_lines: dict[str, int] = field(default_factory=dict)
    decorated: set[str] = field(default_factory=set)
    names: list[str] = field(default_factory=list)
    vocab: set[str] = field(default_factory=set)
    entry: bool = False
    script: bool = False
    lines: int = 0


def _words(ident: str) -> list[str]:
    return [w.lower() for w in CAMEL.findall(ident)]


def _resolve(target: str, names: set[str]) -> str | None:
    """Longest local prefix of an import target, or None for stdlib/3rd party."""
    t = target.strip(".")
    while t:
        if t in names:
            return t
        if "." not in t:
            return None
        t = t.rsplit(".", 1)[0]
    return None


def _top_level_code(tree: ast.Module) -> bool:
    """True when the module does something on import - a script, not a library.

    ``if __name__ == "__main__"`` is excluded because that is the one form of
    top-level code that is meant to be there.
    """
    for node in tree.body:
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant):  # docstring
                continue
            return True
        if isinstance(node, ast.If):
            if "__name__" in ast.dump(node.test):
                continue
            return True
    return False


def modules(root: str | Path, extra_skip: tuple[str, ...] = ()) -> list[Module]:
    """Parse a tree into modules with local import edges. No model, no network."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    skip = SKIP | set(extra_skip)
    paths = [
        p
        for p in sorted(root.rglob("*.py"))
        if not any(part in skip for part in p.relative_to(root).parts)
    ]
    names = set()
    parsed: dict[str, tuple[Path, str, ast.Module]] = {}
    for p in paths:
        parts = list(p.relative_to(root).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        name = ".".join(parts)
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        names.add(name)
        parsed[name] = (p, src, tree)

    out: list[Module] = []
    for name, (p, src, tree) in parsed.items():
        mod = Module(name=name, path=str(p.relative_to(root)), lines=src.count("\n") + 1)
        mod.entry = bool(ENTRY.search(src))
        mod.script = _top_level_code(tree) and not mod.entry
        pkg = name.rsplit(".", 1)[0] if "." in name else ""
        doc = ast.get_docstring(tree) or ""
        vocab = {nodus.lemma(w) for w in nodus.concepts(doc)} if doc else set()
        vocab |= {w for w in _words(name.replace(".", " ")) if len(w) > 3}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names:
                    hit = _resolve(al.name, names)
                    if hit and hit != name:
                        mod.edges.append((hit, node.lineno))
                    else:
                        mod.external += 1
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = node.level - 1
                    parts = pkg.split(".") if pkg else []
                    parts = parts[: len(parts) - up] if up else parts
                    base = ".".join([*parts, base] if base else parts)
                hit = _resolve(base, names) if base else None
                if hit is None and node.level:
                    for al in node.names:  # from . import sibling
                        sib = ".".join(x for x in (pkg, al.name) if x)
                        if sib in names:
                            mod.edges.append((sib, node.lineno))
                elif hit and hit != name:
                    mod.edges.append((hit, node.lineno))
                else:
                    mod.external += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                mod.defines.append(node.name)
                mod.def_lines[node.name] = node.lineno
                mod.names.append(node.name)
                if node.decorator_list:
                    # a decorator can register the function by name, so the name
                    # never has to appear again for it to be live (marimo cells,
                    # flask routes, our own @formula registry)
                    mod.decorated.add(node.name)
                vocab |= {w for w in _words(node.name) if len(w) > 3}
            elif isinstance(node, ast.Name):
                mod.names.append(node.id)
                if len(node.id) > 3:
                    vocab |= {w for w in _words(node.id) if len(w) > 3}
            elif isinstance(node, ast.Attribute):
                mod.names.append(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                mod.names.append(node.arg)  # field written as a keyword argument
        mod.vocab = {v for v in vocab if len(v) > 3}
        out.append(mod)
    return out


def dependency_graph(mods: list[Module]) -> nx.DiGraph:
    g = nx.DiGraph()
    for m in mods:
        g.add_node(m.name)
    for m in mods:
        for target, _line in m.edges:
            if target in g:
                g.add_edge(m.name, target)
    return g


def _community(g: nx.Graph, seed: int = 7) -> dict[str, int]:
    if g.number_of_nodes() < 3:
        return {n: 0 for n in g}
    parts = nx.community.louvain_communities(g, seed=seed)
    return {n: i for i, part in enumerate(parts) for n in part}


def _reach(g: nx.DiGraph, a: str, b: str) -> bool:
    return nx.has_path(g, a, b) or nx.has_path(g, b, a)


def from_code(root: str | Path, max_candidates: int = 4) -> list[Issue]:
    """Gaps in a codebase: the decidable ones first, the guesses labelled."""
    mods = modules(root)
    if not mods:
        return []
    by = {m.name: m for m in mods}
    g = dependency_graph(mods)
    und = g.to_undirected()
    community = _community(und)
    out: list[Issue] = []

    # 1. import cycles - decidable, and the compiler will confirm it
    for scc in nx.strongly_connected_components(g):
        if len(scc) < 2:
            continue
        members = sorted(scc)
        inner = [(u, v, d) for u, v, d in g.edges(data=True) if u in scc and v in scc]
        lines = []
        for u in members:
            for target, line in by[u].edges:
                if target in scc:
                    lines.append(Evidence("line", f"import {target}", f"{by[u].path}:{line}", 1.0))
        out.append(
            Issue(
                id=_id("code", "cycle:" + ",".join(members)),
                source="code",
                title=f"import cycle: {', '.join(members)}",
                why=f"{len(members)} modules import each other in a loop ({len(inner)} edges)",
                labels=["cycle", "code", "defect"],
                score=1.0,
                confidence=1.0,
                evidence=lines[:8],
                queries=[f"python circular import {members[0]} {members[-1]}", "break import cycle by dependency injection"],
                confirm="the import graph is the evidence; `python -c 'import X'` order will expose it",
                numbers={"modules": members, "edges": len(inner)},
                loc=by[members[0]].path,
                ref=",".join(members),
            )
        )

    # 2. modules nothing imports, that also do nothing on import
    for m in mods:
        if m.entry or m.script or g.in_degree(m.name) > 0 or g.out_degree(m.name) > 0:
            continue
        if m.name.startswith("test") or ".test" in m.name or len(mods) < 4:
            continue
        out.append(
            Issue(
                id=_id("code", "orphan:" + m.name),
                source="code",
                title=f"{m.name} is detached from the graph",
                why=f"{m.lines} lines, no local imports, imported by nobody, no __main__ guard",
                labels=["orphan", "code", "defect"],
                score=0.8,
                confidence=0.9,
                evidence=[Evidence("file", ", ".join(m.defines[:6]) or "(no definitions)", m.path, 1.0)],
                queries=[f"is {m.name} dead code", f"python find unused module {m.name}"],
                confirm="no import, no CLI entry, no test and no docs reference it; delete and run the suite",
                numbers={"lines": m.lines, "defines": m.defines[:12], "external_imports": m.external},
                loc=m.path,
                ref=m.name,
            )
        )

    # 3. libraries nothing imports - dead-code candidates, not defects
    for m in mods:
        if m.entry or m.script or m.defines == []:
            continue
        if g.in_degree(m.name) == 0 and g.out_degree(m.name) > 0 and not m.name.startswith("test"):
            out.append(
                Issue(
                    id=_id("code", "unused:" + m.name),
                    source="code",
                    title=f"nothing imports {m.name}",
                    why=f"defines {len(m.defines)} name(s), imports {g.out_degree(m.name)} module(s), in-degree 0",
                    labels=["unused", "code", "candidate"],
                    score=0.55,
                    confidence=0.7,
                    evidence=[Evidence("file", ", ".join(m.defines[:8]), m.path, 1.0)],
                    queries=[f"{m.defines[0]} python usage", f"is {m.name} public api"],
                    confirm="no test, docstring reference or console_scripts entry point names it",
                    numbers={"defines": m.defines[:12], "lines": m.lines},
                    loc=m.path,
                    ref=m.name,
                )
            )

    # 3b. a definition nothing in the tree mentions again - decidable inside the
    # tree, which is why it is a candidate and not a verdict: a public API's
    # callers live outside it.
    used: Counter = Counter()
    for m in mods:
        used.update(m.names)
    dead: list[Issue] = []
    for m in mods:
        if m.entry or m.script:
            continue
        for name, line in m.def_lines.items():
            if len(name) < 4 or name.startswith("__") or name in {"main", "test"}:
                continue
            if used[name] > 1 or name in m.decorated:
                continue
            dead.append(
                Issue(
                    id=_id("code", f"dead:{m.name}.{name}"),
                    source="code",
                    title=f"{m.name}.{name} is defined and never mentioned again",
                    why=f"one occurrence in {len(mods)} modules, at {m.path}:{line}",
                    labels=["deadcode", "code", "candidate"],
                    score=0.5,
                    confidence=0.7,
                    evidence=[Evidence("file", f"def {name}", f"{m.path}:{line}", 1.0)],
                    queries=[f"{name} usage", f"is {m.name}.{name} dead code"],
                    confirm=(
                        "no test, docstring or external importer names it; delete it and run the suite. "
                        "Decorated definitions are skipped because a registry can call them by name we never see"
                    ),
                    numbers={"defs_in_module": len(m.defines), "module": m.name},
                    loc=f"{m.path}:{line}",
                    ref=f"{m.name}.{name}",
                )
            )
    dead.sort(key=lambda i: i.numbers.get("defs_in_module", 0))
    out += dead[:6]

    # 4. two modules carrying the same vocabulary without sharing code
    #
    # This is the text gap's cousin, and it is a *candidate* for the same reason:
    # both modules are reachable from the app, so "nothing links them" would be
    # false. What is true is that neither depends on the other while their
    # identifiers overlap, which is either a missing abstraction or a copy.
    cands: list[tuple[float, str, str, list[str]]] = []
    for i, a in enumerate(mods):
        if len(a.vocab) < MIN_VOCAB:
            continue
        for b in mods[i + 1 :]:
            if len(b.vocab) < MIN_VOCAB or community.get(a.name) != community.get(b.name):
                continue
            if _reach(g, a.name, b.name):
                continue
            shared = a.vocab & b.vocab
            j = len(shared) / len(a.vocab | b.vocab)
            if j >= SHARED:
                cands.append((j, a.name, b.name, sorted(shared)))
    cands.sort(reverse=True)
    for j, a, b, shared in cands[:max_candidates]:
        out.append(
            Issue(
                id=_id("code", f"bridge:{a}:{b}"),
                source="code",
                title=f"{a} and {b} share {len(shared)} terms and no module",
                why=f"Jaccard {j:.2f}, {len(shared)} shared identifiers, neither imports the other",
                labels=["overlap", "code", "candidate"],
                score=round(0.3 + j, 3),
                confidence=0.35,
                evidence=[Evidence("file", ", ".join(shared[:10]), f"{by[a].path} | {by[b].path}", j)],
                queries=[f"{a} {b} python", f"should {a} depend on {b}"],
                confirm=(
                    "read the shared names: if they are the same concept implemented twice, extract it; "
                    "if they are incidental (dict, value, text), close the card"
                ),
                numbers={"jaccard": round(j, 3), "shared": shared[:20]},
                loc=by[a].path,
                ref=f"{a} ~ {b}",
            )
        )
    return out


# ---------------------------------------------------------------------------
# source 3: GitHub issues
# ---------------------------------------------------------------------------


class GitHubError(RuntimeError):
    pass


def _gh(url: str, token: str | None = None, timeout: float = 15.0):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nodus-issues",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        detail = e.read()[:240].decode("utf-8", "replace")
        hint = " (set GITHUB_TOKEN for 5,000/hr)" if e.code == 403 else ""
        raise GitHubError(f"{e.code} {e.reason}{hint}: {detail}") from None
    except urllib.error.URLError as e:
        raise GitHubError(f"unreachable: {e.reason}") from None


def from_github(
    repo: str,
    token: str | None = None,
    state: str = "open",
    limit: int = 100,
    label: str | None = None,
    fetch=_gh,
) -> list[Issue]:
    """Real tickets, with their state left where GitHub keeps it.

    Pull requests come back from this endpoint too; they are skipped rather than
    mixed into a board of gaps.
    """
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo or ""):
        raise GitHubError(f"repo must be owner/name, got {repo!r}")
    token = token or os.environ.get("GITHUB_TOKEN") or None
    out: list[Issue] = []
    seen: set[int] = set()
    page = 1
    while len(out) < limit and page <= 10:
        q = {"state": state, "per_page": 100, "page": page}
        if label:
            q["labels"] = label
        url = f"https://api.github.com/repos/{repo}/issues?" + urllib.parse.urlencode(q)
        rows, _hd = fetch(url, token)
        if not rows:
            break
        added = 0
        for it in rows:
            if "pull_request" in it:
                continue
            n = it["number"]
            if n in seen:  # pages can overlap while issues are being edited
                continue
            seen.add(n)
            added += 1
            body = (it.get("body") or "").strip()
            labels = [l["name"] for l in it.get("labels", [])]
            terms = nodus.concepts(f"{it['title']} {body}")[:6]
            out.append(
                Issue(
                    id=_id("github", f"{repo}#{n}"),
                    source="github",
                    title=f"gh#{n} {it['title']}"[:160],
                    why=(body[:400] or "no body"),
                    labels=["github", *labels],
                    status="open" if it.get("state") == "open" else "solved",
                    score=0.6 if any(l.lower() in {"bug", "critical", "p0", "blocker"} for l in labels) else 0.4,
                    confidence=1.0,
                    evidence=[Evidence("ticket", it["title"], f"gh#{n}", 1.0)],
                    queries=[f"repo:{repo} {' '.join(terms[:3])}", *([" ".join(terms[:3])] if terms else [])],
                    confirm="a reproduction against HEAD; a ticket is a claim, not a measurement",
                    numbers={
                        "number": n,
                        "comments": it.get("comments", 0),
                        "created": it.get("created_at", ""),
                        "url": it.get("html_url", ""),
                        "terms": terms,
                    },
                    loc=f"{repo}#{n}",
                    ref=f"gh#{n}",
                )
            )
            if len(out) >= limit:
                break
        if not added:  # a server that ignores `page` must not loop for ten rounds
            break
        page += 1
    return out


def locate(issues: list[Issue], mods: list[Module], top: int = 2) -> list[Issue]:
    """Where in the code does this ticket live? Vocabulary overlap, no model.

    Only used for source == "github"; the point is that a human reading a ticket
    rarely knows which module it is about, and the code graph already holds the
    vocabulary that answers it.
    """
    for it in issues:
        if it.source != "github":
            continue
        terms = set(it.numbers.get("terms") or [])
        if not terms:
            continue
        scored = []
        for m in mods:
            hits = terms & m.vocab
            if hits:
                scored.append((len(hits) / len(terms), m.name, sorted(hits)))
        scored.sort(reverse=True)
        if scored:
            share, name, hits = scored[0]
            it.numbers["module"] = name
            it.numbers["module_share"] = round(share, 2)
            it.evidence.append(Evidence("file", ", ".join(hits[:8]), name, share))
            it.loc = f"{name} ({share:.0%} of the ticket's terms)"
    return issues


# ---------------------------------------------------------------------------
# board: persistence, merge, order
# ---------------------------------------------------------------------------


def merge(*boards: list[Issue]) -> list[Issue]:
    """One board from several sources; the same gap keeps the first copy."""
    seen: dict[str, Issue] = {}
    for b in boards:
        for it in b:
            seen.setdefault(it.id, it)
    return rank(list(seen.values()))


def rank(items: list[Issue]) -> list[Issue]:
    order = {"open": 0, "solved": 1, "wontfix": 2}
    return sorted(items, key=lambda i: (order.get(i.status, 3), -i.score, i.source, i.title))


def board_path(root: str | Path = "solve") -> Path:
    return Path(root) / "issues.json"


def load(root: str | Path = "solve") -> dict[str, Issue]:
    p = board_path(root)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: Issue.from_dict(v) for k, v in raw.items()}


def save(items: list[Issue], root: str | Path = "solve") -> Path:
    p = board_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({i.id: i.to_dict() for i in items}, indent=1), encoding="utf-8")
    return p
