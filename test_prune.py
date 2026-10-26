"""prune.py: the three policies, and the budget that trims their union.

The tests are written against a real `nodus.analyse` result rather than a fake,
because the thing most likely to break is the coupling to the graph (region ids,
lemmas), not the arithmetic.
"""

import unittest

import nodus
import prune

# Repetition is deliberate: nodus builds an edge only for concepts seen twice, so a
# plausible-sounding paragraph with one of every word produces no graph at all and
# every region assertion below would be vacuously true.
CORPUS = (
    "Graph retrieval builds a graph over a corpus. The graph retrieval step summarises "
    "communities of the corpus, and those communities answer global questions. Citation "
    "practice requires a citation for every claim, and the citation points at a span. A span "
    "is what a reader can open, and citation practice keeps the span honest. Predator "
    "populations oscillate when prey populations grow; predator growth follows prey with a "
    "delay, and populations oscillate again. Static analysis finds imports that no module "
    "declares, and static analysis reports those imports as defects. The module graph records "
    "imports, so static analysis reads the module graph."
)

REPLY = (
    "The graph retrieval layer answers global questions over a corpus, and it summarises "
    'communities before answering. As one source puts it, "citation practice keeps the span '
    'honest". Predator and prey populations oscillate, '
    "so the predator follows the prey by about a quarter cycle. Static analysis finds imports "
    "that no module declares, and the module graph cannot see them. The weather in Lisbon is "
    "pleasant in April and nobody disputes that. Another sentence about nothing in particular "
    "fills the space where an argument would go. A further sentence restates the first one in "
    "slightly different words so the reply is long enough to be worth compressing at all."
)


def _analysis():
    return nodus.analyse(CORPUS, max_gaps=4)


class TestPolicies(unittest.TestCase):
    def setUp(self):
        self.A = _analysis()

    def test_cited_statement_survives(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=4000)
        self.assertTrue(any("cites the corpus" in k.reasons for k in p.kept))
        self.assertEqual(p.cited, 1)

    def test_gap_statement_survives_without_a_citation(self):
        gap = {"terms_a": ["predator"], "terms_b": ["oscillate"]}
        p = prune.prune(REPLY, gap=gap, corpus="", analysis=self.A, budget=4000)
        kept_text = " ".join(k.text for k in p.kept).lower()
        self.assertIn("oscillate", kept_text)

    def test_off_topic_statement_is_dropped_when_something_better_exists(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=4000)
        kept_text = " ".join(k.text for k in p.kept).lower()
        self.assertNotIn("lisbon", kept_text)

    def test_region_quota_keeps_a_topic_a_citation_would_have_hidden(self):
        # Only the citation and the predator statement are "interesting" by
        # citation/gap; the import statement is kept by the region quota alone.
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=4000, per_region=1)
        reasons = [k.reasons for k in p.kept]
        self.assertTrue(any(any("region" in r for r in rs) for rs in reasons))
        self.assertGreater(len(p.regions), 0)

    def test_header_reports_what_was_cut(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=4000)
        self.assertLess(p.chars_out, p.chars_in)
        self.assertIn("statements", p.header())
        self.assertIn("chars", p.header())


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.A = _analysis()

    def test_budget_is_respected(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=400, per_region=1)
        self.assertLessEqual(p.chars_out, 400)

    def test_a_single_statement_over_budget_is_kept_and_flagged(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=10, per_region=0)
        self.assertGreaterEqual(len(p.kept), 1)
        self.assertTrue(p.over_budget)
        self.assertIn("over budget", p.header())

    def test_dropped_statements_are_reported_not_deleted(self):
        p = prune.prune(REPLY, corpus=CORPUS, analysis=self.A, budget=250, per_region=1)
        self.assertTrue(p.dropped)
        self.assertTrue(all("cut by the page budget" in k.reasons for k in p.dropped))
        self.assertLess(p.chars_out, p.chars_in)

    def test_allocation_splits_the_page_budget(self):
        allocs = prune.allocate(900, 3)
        self.assertEqual(sum(allocs), 900)
        self.assertEqual(len(allocs), 3)
        self.assertEqual(prune.allocate(900, 0), [])
        # a floor, so five outputs never get 4 characters each
        self.assertGreaterEqual(min(prune.allocate(10, 5)), 180)


class TestEdges(unittest.TestCase):
    def test_nothing_relevant_returns_the_lede_and_says_so(self):
        p = prune.prune("The weather is pleasant. Lisbon in April is fine.", corpus="", budget=900)
        self.assertTrue(p.lead)
        self.assertEqual(len(p.kept), 1)
        self.assertIn("lede", p.header())

    def test_empty_text(self):
        p = prune.prune("", budget=900)
        self.assertTrue(p.nothing)
        self.assertEqual(p.total, 0)

    def test_deterministic(self):
        a = prune.prune(REPLY, corpus=CORPUS, analysis=_analysis(), budget=300)
        b = prune.prune(REPLY, corpus=CORPUS, analysis=_analysis(), budget=300)
        self.assertEqual([k.text for k in a.kept], [k.text for k in b.kept])
        self.assertEqual(a.chars_out, b.chars_out)

    def test_layers_argument_wins_over_fine_clusters(self):
        A = _analysis()
        L = nodus.layers(A, target=2)
        m = prune.region_map(A, L)
        self.assertEqual(len(set(m.values())), 2)


if __name__ == "__main__":
    unittest.main()
