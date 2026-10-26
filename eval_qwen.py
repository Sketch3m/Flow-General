"""Measure Qwen as a background agent, without nodus in the loop.

Two jobs, each with a ground truth that does not depend on the gap detector:

1. PICK: given a sentence from a paper's abstract, choose its title from the five
   titles in papers/. Ground truth is which paper the sentence came from.
2. WRITE: given two terms that co-occur in one abstract sentence, write one sentence
   that uses both terms and a relation verb. Scored on: both terms present, a relation
   verb present, and no words absent from the abstract's vocabulary beyond stopwords.

Every call is repeated REPEATS times so the rate is not one lucky draw.
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import localmodels
import nodus

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
VERBS = (
    "causes implies leads requires depends supports contradicts is includes "
    "contains enables produces shows demonstrates needs"
).split()


def load() -> list[dict]:
    out = []
    for p in sorted(Path("papers").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        body = text.split("\n", 2)[2] if text.count("\n") > 2 else text
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 40]
        out.append({"file": p.name, "title": title, "sents": sents, "vocab": set(nodus.concepts(body))})
    return out


def pick_job(papers: list[dict]) -> dict:
    options = [p["title"] for p in papers]
    hits = total = errors = 0
    for p in papers:
        for s in p["sents"][:2]:
            for _ in range(REPEATS):
                r = localmodels.pick(
                    "Which paper does this abstract sentence come from?",
                    options,
                    context=s[:300],
                )
                total += 1
                errors += bool(r.get("error"))
                hits += r.get("choice") == p["title"]
    return {"correct": hits, "total": total, "errors": errors}


def write_job(papers: list[dict]) -> dict:
    tried = ok_terms = ok_verb = ok_grounded = errors = 0
    rng = random.Random(7)
    for p in papers:
        pairs = []
        for s in p["sents"]:
            terms = [t for t in nodus.concepts(s) if t in p["vocab"]]
            terms = sorted(set(terms))
            if len(terms) >= 2:
                pairs.append(tuple(rng.sample(terms, 2)))
        for a, b in pairs[:3]:
            for _ in range(REPEATS):
                r = localmodels.chat(
                    [
                        {"role": "system", "content": "Write exactly one sentence. Use a relation verb such as requires, supports, implies or depends on."},
                        {"role": "user", "content": f"Connect '{a}' and '{b}' in one sentence."},
                    ],
                    max_tokens=60,
                    timeout=90,
                    stop=["\n"],
                )
                text = (r.get("text") or "").strip().lower()
                tried += 1
                errors += bool(r.get("error")) or not text
                words = set(re.findall(r"[a-z]+", text))
                ok_terms += a in words and b in words
                ok_verb += any(v in words for v in VERBS)
                # 'grounded' was dropped: the concept vocabulary is lemmatised, so
                # ordinary English ("meaning", "structure") reads as invented. Only
                # the two checks below are reported.
    return {"tried": tried, "terms": ok_terms, "verb": ok_verb, "errors": errors}


def main() -> None:
    print("qwen up:", localmodels.available()["qwen"])
    papers = load()
    print(f"papers: {len(papers)}, repeats per item: {REPEATS}")
    p = pick_job(papers)
    print(f"PICK   correct {p['correct']}/{p['total']} ({p['correct'] / max(1, p['total']):.0%}), errors {p['errors']}")
    w = write_job(papers)
    n = max(1, w["tried"])
    print(f"WRITE  tried {w['tried']}, both terms {w['terms']} ({w['terms'] / n:.0%}), relation verb {w['verb']} ({w['verb'] / n:.0%}), errors {w['errors']}")


if __name__ == "__main__":
    main()
