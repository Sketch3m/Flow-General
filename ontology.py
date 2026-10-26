"""
ontology.py - the layer the concept graph cannot see: typed relations.

A co-occurrence graph says *window* and *citation* never appear near each other.
It cannot say whether the document ever claims that one causes, implies, needs,
or contradicts the other - and "these words are far apart" is a much weaker
statement than "nothing here links these two ideas".

So this module reads a small closed set of relation cues and keeps the ones the
graph knows about:

    causes / implies / leads to / produces        -> causal
    is a / is an / is one of                      -> is-a
    contains / includes / is part of / consists   -> part-of
    contradicts / conflicts with / rules out      -> opposition
    depends on / requires / rests on              -> dependency
    supports / confirms / shows                   -> evidential

That is OpenIE-lite: no parser, no model, no claims of completeness. It is a
census of the relations a writer actually spelled out, which is exactly what the
gap card needs, because "no typed link crosses this divide" is checkable and
"no co-occurrence" is not.

Three levels, kept distinct on purpose:

    concept   a lemma                       (nodus.concepts)
    topic     a cluster of concepts          (nodus.clusters)
    domain    a merge of topics              (nodus.layers human regions)
    ontology  a *typed edge between two concepts*   <- this file
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import nodus

KINDS = {
    "causal": {"cause", "causes", "caused", "causing", "implies", "imply", "lead", "leads", "produce", "produces", "creates", "prevents", "enables"},
    "is-a": {"is", "are", "was", "were"},
    "part-of": {"contains", "contain", "includes", "include", "comprises", "comprise", "has", "have"},
    "opposition": {"contradicts", "contradict", "conflicts", "opposes", "rules", "undermines", "refutes"},
    "dependency": {"depends", "depend", "requires", "require", "rests", "needs", "assumes", "presupposes"},
    "evidential": {"supports", "support", "confirms", "confirm", "shows", "show", "proves", "prove", "demonstrates"},
}

# is-a is only kept for "X is a Y" with an article, otherwise English produces
# thousands of "the reply is dropped" edges that mean nothing.
_ISA = re.compile(r"\b([a-z][a-z'\-]+)\s+(?:is|are)\s+(?:a|an|one of the)\s+([a-z][a-z'\-]+)")
# "X is Y" is handled by _ISA only when an article is present; leaving is/are in
# the verb alternation produces thousands of "reply is dropped" edges that mean
# nothing.
_VERB_ALTS = sorted({v for k, vs in KINDS.items() if k != "is-a" for v in vs})
_VERB = re.compile(r"\b([a-z][a-z'\-]+)\s+(" + "|".join(_VERB_ALTS) + r")\s+([a-z][a-z'\-]+)")


@dataclass
class Relation:
    subject: str
    kind: str
    object: str
    sentence: str

    def to_dict(self) -> dict:
        return {"subject": self.subject, "kind": self.kind, "object": self.object}


def _kind_of(verb: str) -> str:
    for kind, verbs in KINDS.items():
        if verb in verbs:
            return kind
    return "other"


def relations(text: str, concepts: set[str] | None = None) -> list[Relation]:
    """Typed edges the document actually states, in reading order.

    Only lemmas the graph kept are accepted, so a relation cannot introduce a
    concept that the analysis never saw. Duplicates are collapsed; the first
    sentence that states a relation is the one kept, because that is the one a
    reader can go and check.
    """
    seen = set()
    out: list[Relation] = []
    for raw in re.split(r"(?<=[.!?])\s+", text):
        s = raw.strip().replace("\n", " ")
        if len(s) < 12:
            continue
        low = s.lower()
        for m in _VERB.finditer(low):
            subj, verb, obj = m.group(1), m.group(2), m.group(3)
            a, b, kind = nodus.lemma(subj), nodus.lemma(obj), _kind_of(verb)
            if a == b or (concepts and (a not in concepts or b not in concepts)):
                continue
            key = (a, kind, b)
            if key in seen:
                continue
            seen.add(key)
            out.append(Relation(a, kind, b, s))
        for m in _ISA.finditer(low):
            a, b = nodus.lemma(m.group(1)), nodus.lemma(m.group(2))
            if a == b or (concepts and (a not in concepts or b not in concepts)):
                continue
            key = (a, "is-a", b)
            if key in seen:
                continue
            seen.add(key)
            out.append(Relation(a, "is-a", b, s))
    return out


def crossings(rels: list[Relation], side_a: set[str], side_b: set[str]) -> list[Relation]:
    """Relations that actually join the two sides - the thing a gap claims is absent."""
    return [
        r
        for r in rels
        if (r.subject in side_a and r.object in side_b)
        or (r.subject in side_b and r.object in side_a)
    ]


def summary(rels: list[Relation], side_a: set[str], side_b: set[str]) -> dict:
    cross = crossings(rels, side_a, side_b)
    kinds: dict[str, int] = {}
    for r in rels:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    return {
        "relations": len(rels),
        "kinds": kinds,
        "crossings": len(cross),
        "examples": [r.to_dict() for r in cross[:3]],
    }
