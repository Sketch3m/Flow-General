"""Draw five cs.AI papers at random, reproducibly.

The pool is the N most recent cs.AI submissions; the sample is random.Random(SEED).
Re-running with the same SEED and pool gives the same five papers. Writes one
markdown file per paper into papers/, which sheet.py loads as paper cells.
"""

from __future__ import annotations

import random
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
POOL = 100
K = 5
API = "https://export.arxiv.org/api/query?"
NS = {"a": "http://www.w3.org/2005/Atom"}


def fetch_pool() -> list[dict]:
    q = urllib.parse.urlencode(
        {
            "search_query": "cat:cs.AI",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": POOL,
        }
    )
    with urllib.request.urlopen(API + q, timeout=60) as r:
        root = ET.fromstring(r.read())
    out = []
    for e in root.findall("a:entry", NS):
        aid = e.find("a:id", NS).text.rsplit("/", 1)[-1]
        out.append(
            {
                "id": re.sub(r"v\d+$", "", aid),
                "title": " ".join(e.find("a:title", NS).text.split()),
                "summary": " ".join(e.find("a:summary", NS).text.split()),
            }
        )
    return out


def main() -> None:
    pool = fetch_pool()
    picks = random.Random(SEED).sample(pool, K)
    out = Path("papers")
    out.mkdir(exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    for i, p in enumerate(picks, 1):
        body = f"# {p['title']}\n\narXiv:{p['id']}\n\n{p['summary']}\n"
        (out / f"{i:02d}-{p['id']}.md").write_text(body, encoding="utf-8")
        print(f"{i}. {p['id']}  {p['title'][:80]}")
    print(f"pool={len(pool)} seed={SEED}")


if __name__ == "__main__":
    main()
