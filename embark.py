"""
embark.py - detectors, formulas, views: the deterministic layer.

Geoffrey Litt's Embark and Potluck do their "the document grows a tool" trick
with no model in the loop. Three stages, all ordinary code:

    detector   a pattern finds structured data in the text (Potluck: `{number}`,
               `{/g|kg|ml/:unit}`; Embark: `@Aachen` mentions linked to a record)
    formula    a function recomputes a value from that data, reactively
    view       the value's *type* decides which widget renders it (map, calendar,
               table - one per type, dispatched, not chosen by an LLM)

Worth being honest about the ceiling: in both prototypes the formulas and views
were **hardcoded**. Embark's essay says a future version might let users define
views at runtime; it did not. So a small registry is not a limitation of this
file, it is the state of the art in the prototypes. What is real is the feel:
you type, the value updates, nothing streams, nothing waits.

Potluck's rule is kept: **detectors never edit the text.** They read spans and
return values; every rendered value is an overlay computed at view time.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import nodus


@dataclass(frozen=True)
class Detector:
    """A named pattern. `fields` names the capture groups."""

    name: str
    pattern: re.Pattern[str]
    fields: tuple[str, ...]


@dataclass
class Match:
    detector: str
    raw: str
    span: tuple[int, int]
    fields: dict[str, str] = field(default_factory=dict)
    line: int = 0


DETECTORS: tuple[Detector, ...] = (
    Detector("mention", re.compile(r"(?<![@\w])@([a-z][\w-]{2,})", re.I), ("term",)),
    Detector(
        "call",
        re.compile(
            r"!(?P<fn>gap|hops|influence)\(\s*@?(?P<a>[a-z][\w-]{2,})"
            r"(?:\s*,\s*@?(?P<b>[a-z][\w-]{2,}))?\s*\)",
            re.I,
        ),
        ("fn", "a", "b"),
    ),
)


def detect(text: str, detectors: tuple[Detector, ...] = DETECTORS) -> list[Match]:
    """Run every detector over the text. Pure: text in, spans out."""
    out: list[Match] = []
    for det in detectors:
        for m in det.pattern.finditer(text):
            fields = {k: (v or "") for k, v in m.groupdict().items()}
            if not fields:  # positional groups
                fields = dict(zip(det.fields, m.groups()))
            out.append(
                Match(
                    detector=det.name,
                    raw=m.group(0),
                    span=(m.start(), m.end()),
                    fields={k: v.lower() for k, v in fields.items()},
                    line=text.count("\n", 0, m.start()) + 1,
                )
            )
    out.sort(key=lambda x: x.span)
    return out


@dataclass
class Value:
    """A computed value. `kind` is what the view layer dispatches on."""

    kind: str
    label: str
    data: dict = field(default_factory=dict)

    def text(self) -> str:
        """The view for this kind. One renderer per type, no model involved."""
        render = VIEWS.get(self.kind, _view_plain)
        return render(self)


# ---------------------------------------------------------------------------
# formulas: (analysis, ...) -> Value. Deterministic, recomputed on every edit.
# ---------------------------------------------------------------------------

Formula = Callable[..., Value]
FORMULAS: dict[str, Formula] = {}


def formula(name: str) -> Callable[[Formula], Formula]:
    def register(fn: Formula) -> Formula:
        FORMULAS[name] = fn
        return fn

    return register


@formula("influence")
def _influence(a: nodus.Analysis, term: str, _b: str = "") -> Value:
    d = nodus.describe(a, term)
    if d is None:
        return Value("missing", term, {"reason": "not a node in this graph"})
    return Value("term", term, d)


@formula("gap")
def _gap(a: nodus.Analysis, x: str, y: str = "") -> Value:
    """Look the pair up among the ranked gaps.

    If the pair exists, report the real numbers. If not, say so rather than
    inventing a score - a formula that cannot be wrong is not worth typing.
    """
    if not y:
        return Value("plain", x, {"reason": "gap needs two terms"})
    ta, tb = nodus.lemma(x), nodus.lemma(y)
    for g in a.gaps:
        if ta in g.terms_a and tb in g.terms_b or ta in g.terms_b and tb in g.terms_a:
            return Value(
                "gap",
                f"{ta} ~ {tb}",
                {
                    "score": round(g.score, 3),
                    "shared edges": g.cross_weight,
                    "hops": g.distance if g.distance is not None else "∞",
                    "bridges": ", ".join(g.bridge_terms) or "none",
                    "ranked": True,
                },
            )
    d = nodus.pair_gap(a, ta, tb)
    if d is None:
        return Value("plain", f"{ta} ~ {tb}", {"reason": "same cluster, or not in the graph"})
    return Value("gap", f"{ta} ~ {tb}", {**d, "score": round(d["score"], 3),
                                          "hops": d["hops"] if d["hops"] is not None else "∞"})


@formula("hops")
def _hops(a: nodus.Analysis, x: str, y: str = "") -> Value:
    if not y or x not in a.graph or y not in a.graph:
        return Value("missing", f"{x} → {y}", {"reason": "one of these is not in the graph"})
    d = nodus._hop_distance(a.graph, [x], [y])
    return Value("hops", f"{x} → {y}", {"hops": d if d is not None else "∞ (disconnected)"})


# ---------------------------------------------------------------------------
# views: one renderer per value kind
# ---------------------------------------------------------------------------

VIEWS: dict[str, Callable[[Value], str]] = {
    "term": lambda v: (
        f"**@{v.label}** · cluster {v.data['cluster']} · seen {v.data['seen']}× · "
        f"influence {v.data['influence']} · with {v.data['peers']}"
    ),
    "gap": lambda v: (
        f"**{v.label}** · score {v.data['score']} · {v.data['shared edges']} shared edges · "
        f"{v.data['hops']} hops · z {v.data.get('surprise', 0)} · "
        f"RA {v.data.get('ra', 0)} · AA {v.data.get('aa', 0)}"
        + ("" if v.data.get("ranked", True) else " · below the ranked cut, computed on demand")
    ),
    "hops": lambda v: f"**{v.label}** · {v.data['hops']} hops",
    "missing": lambda v: f"`{v.label}` — {v.data.get('reason', 'no value')}",
}


def _view_plain(v: Value) -> str:
    return f"`{v.label}` — {v.data.get('reason', 'computed')}"


def evaluate(match: Match, a: nodus.Analysis) -> Value:
    """Match -> Value, by looking the formula up in the registry."""
    if match.detector == "mention":
        return _influence(a, match.fields.get("term", ""))
    fn = FORMULAS.get(match.fields.get("fn", ""))
    if fn is None:
        return Value("missing", match.raw, {"reason": "unknown formula"})
    return fn(a, match.fields.get("a", ""), match.fields.get("b", ""))


def overlay(text: str, a: nodus.Analysis) -> list[dict]:
    """Every detected value in the document, with the line it came from.

    This is the whole overlay: the app renders these beside the text and never
    writes them into it.
    """
    return [
        {
            "line": m.line,
            "raw": m.raw,
            "kind": v.kind,
            "value": v.text(),
        }
        for m in detect(text)
        for v in [evaluate(m, a)]
    ]
