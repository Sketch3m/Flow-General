"""
test_issues.py - the adapters, checked without a network or a model.

Run with:  .venv/bin/python -m unittest test_issues -v
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import issues


def _tree(root: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


class TextSource(unittest.TestCase):
    def test_gap_card_is_self_contained(self):
        text = (
            "The window evicts the oldest reply first because recency is all it measures.\n"
            "The window keeps only what is recent and drops whatever does not fit inside it.\n"
            "The window cannot see that the dropped reply still exists on disk somewhere.\n\n"
            "A citation is a claim that a sentence traces back to a source.\n"
            "A citation without a quote cannot be checked by anyone reading it later.\n"
            "A quote without a source is an anecdote and nothing more than that.\n"
        )
        items = issues.from_text(text)
        self.assertTrue(items, "expected at least one unbridged gap")
        for it in items:
            self.assertEqual(it.source, "text")
            self.assertTrue(it.title.startswith("nothing links "))
            self.assertTrue(it.queries and all(isinstance(q, str) and q for q in it.queries))
            self.assertTrue(it.confirm)
            self.assertIn("score", it.numbers)
            self.assertLessEqual(it.score, 1.0)

    def test_ids_are_stable(self):
        text = (
            "Alpha beta gamma delta. Alpha beta gamma delta again. Alpha beta gamma.\n"
            "Omega sigma tau rho. Omega sigma tau rho again. Omega sigma tau."
        )
        a = [i.id for i in issues.from_text(text, max_gaps=4)]
        b = [i.id for i in issues.from_text(text, max_gaps=4)]
        self.assertEqual(a, b)


class CodeSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = _tree(
            Path(self.tmp.name),
            {
                "pkg/__init__.py": "",
                "pkg/x.py": "import pkg.y\n\ndef tox():\n    return 1\n",
                "pkg/y.py": "import pkg.x\n\ndef toy():\n    return 2\n",
                "pkg/isolated.py": "def helper_that_nobody_calls():\n    return 3\n",
                "pkg/dec.py": "REG = []\n\n\ndef register(fn):\n    REG.append(fn)\n    return fn\n\n\n@register\ndef decorated_but_live():\n    return 4\n",
                "app.py": "import pkg.x\n\nif __name__ == '__main__':\n    print(pkg.x.tox())\n",
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_cycle_is_filed_as_a_defect(self):
        items = issues.from_code(self.root)
        cycles = [i for i in items if "cycle" in i.labels]
        self.assertTrue(cycles, [i.title for i in items])
        c = cycles[0]
        self.assertEqual(c.confidence, 1.0)
        self.assertEqual(set(c.numbers["modules"]), {"pkg.x", "pkg.y"})
        self.assertTrue(all(":" in e.loc for e in c.evidence))

    def test_detached_module_is_filed_and_entrypoint_is_not(self):
        items = issues.from_code(self.root)
        titles = " | ".join(i.title for i in items)
        self.assertIn("pkg.isolated", titles)
        self.assertNotIn("app is detached", titles)

    def test_decorated_definition_is_not_called_dead(self):
        items = issues.from_code(self.root)
        dead = [i for i in items if "deadcode" in i.labels]
        self.assertFalse(
            [i for i in dead if "decorated_but_live" in i.title],
            "a registered function is live even though its name never reappears",
        )

    def test_missing_path_is_reported_not_swallowed(self):
        with self.assertRaises(NotADirectoryError):
            issues.from_code(Path(self.tmp.name) / "nope")


class GitHubSource(unittest.TestCase):
    ROWS = [
        {
            "number": 7,
            "title": "Crash when the window evicts a reply",
            "body": "Seen in nodus.py when the text is long.",
            "state": "open",
            "labels": [{"name": "bug"}],
            "comments": 2,
            "html_url": "https://example.invalid/7",
        },
        {
            "number": 8,
            "title": "Refactor everything",
            "body": "",
            "state": "open",
            "labels": [],
            "comments": 0,
            "html_url": "https://example.invalid/8",
        },
        {
            "number": 9,
            "title": "a pull request",
            "body": "",
            "state": "open",
            "labels": [],
            "pull_request": {"url": "x"},
        },
    ]

    def _fake(self, url, token):
        return list(self.ROWS), {}

    def test_parses_without_network_and_drops_pull_requests(self):
        items = issues.from_github("owner/repo", fetch=self._fake)
        self.assertEqual([i.ref for i in items], ["gh#7", "gh#8"])
        bug = items[0]
        self.assertIn("bug", bug.labels)
        self.assertGreater(bug.score, items[1].score)
        self.assertEqual(bug.numbers["number"], 7)
        self.assertEqual(bug.numbers["url"], "https://example.invalid/7")
        self.assertTrue(bug.numbers["terms"])

    def test_closed_issue_is_solved(self):
        rows = [dict(self.ROWS[0], state="closed")]
        items = issues.from_github("owner/repo", fetch=lambda u, t: (rows, {}))
        self.assertEqual(items[0].status, "solved")

    def test_bad_repo_raises_instead_of_returning_empty(self):
        with self.assertRaises(issues.GitHubError):
            issues.from_github("not-a-repo", fetch=self._fake)

    def test_http_error_is_surfaced(self):
        def boom(url, token):
            raise issues.GitHubError("404 Not Found: nope")

        with self.assertRaises(issues.GitHubError):
            issues.from_github("owner/repo", fetch=boom)


class LocateAndStore(unittest.TestCase):
    def test_ticket_is_located_in_the_module_that_shares_its_words(self):
        mods = [
            issues.Module(name="nodus", path="nodus.py", vocab={"window", "evict", "reply", "citation"}),
            issues.Module(name="web", path="web.py", vocab={"button", "layout", "colour"}),
        ]
        ticket = issues.Issue(
            id="x",
            source="github",
            title="gh#1 window evicts reply",
            why="",
            numbers={"terms": ["window", "evict", "reply", "citation"]},
        )
        [placed] = issues.locate([ticket], mods)
        self.assertEqual(placed.numbers["module"], "nodus")
        self.assertIn("nodus", placed.loc)

    def test_board_round_trips_through_disk(self):
        items = [
            issues.Issue(
                id="abc",
                source="code",
                title="t",
                why="w",
                labels=["defect"],
                evidence=[issues.Evidence("file", "def f", "a.py:3", 1.0)],
                queries=["q"],
                numbers={"n": 1},
            )
        ]
        with tempfile.TemporaryDirectory() as d:
            p = issues.save(items, d)
            self.assertTrue(p.exists())
            back = issues.load(d)
        self.assertEqual(list(back), ["abc"])
        self.assertEqual(back["abc"].evidence[0].loc, "a.py:3")
        self.assertEqual(back["abc"].labels, ["defect"])

    def test_merge_keeps_one_copy_and_ranks_open_first(self):
        a = issues.Issue(id="1", source="text", title="a", why="", score=0.1, status="solved")
        b = issues.Issue(id="2", source="code", title="b", why="", score=0.4)
        c = issues.Issue(id="1", source="text", title="dupe", why="")
        out = issues.merge([a, b], [c])
        self.assertEqual([i.id for i in out], ["2", "1"])
        self.assertEqual(out[1].title, "a")


if __name__ == "__main__":
    unittest.main()
