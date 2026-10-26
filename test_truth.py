import unittest

import cells
import truth

CORPUS = (
    "Predator populations depend on prey abundance. Prey populations grow when "
    "predator numbers fall. Predator and prey dynamics oscillate over seasons. "
    "Predator hunting rates shape prey survival. "
    "Compiler optimisation rewrites intermediate representation. Compiler passes "
    "lower the intermediate representation into machine code. Compiler backends "
    "schedule machine instructions. Compiler inlining reduces call overhead."
)


class SpansTest(unittest.TestCase):
    def test_double_quoted_span_extracted_and_short_ignored(self):
        t = 'Alpha requires beta because "predator hunting rates shape prey survival."'
        self.assertEqual(truth.spans(t), ["predator hunting rates shape prey survival."])
        self.assertEqual(truth.spans('he said "too short." and left'), [])

    def test_blockquote_line_counts_as_a_citation(self):
        body = "> Compiler inlining reduces call overhead.\n\nDirection: explain the link"
        self.assertEqual(truth.spans(body), ["Compiler inlining reduces call overhead."])

    def test_uncited_text_yields_nothing(self):
        self.assertEqual(truth.spans("plain prose, no citations here."), [])


class FindTest(unittest.TestCase):
    def test_exact_after_normalisation(self):
        r = truth.find("compiler  Inlining REDUCES call overhead.", CORPUS)
        self.assertTrue(r["found"])
        self.assertEqual(r["ratio"], 1.0)

    def test_absent_quote_is_not_found(self):
        r = truth.find("quantum bananas tunnel beneath Winnipeg every Tuesday", CORPUS)
        self.assertFalse(r["found"])
        self.assertLess(r["ratio"], 0.9)

    def test_reworded_quote_is_not_forgiven(self):
        # the hallucinated citation this gate exists for: one word changed,
        # word sequence no longer occurs - ratio 0, not 'close enough'
        r = truth.find("compiler inlining reduces call overheads", CORPUS)
        self.assertFalse(r["found"])
        self.assertEqual(r["ratio"], 0.0)

    def test_elision_may_cut_only_where_the_corpus_cuts(self):
        r = truth.find("Compiler optimisation rewrites ... into machine code", CORPUS)
        self.assertTrue(r["found"], r)
        bad = truth.find("Compiler optimisation rewrites ... unicorn migrations daily", CORPUS)
        self.assertFalse(bad["found"])
        self.assertLess(bad["ratio"], 0.99)

    def test_too_short_to_prove_anything(self):
        self.assertFalse(truth.find("xy zz", CORPUS)["found"])


class GateTest(unittest.TestCase):
    def test_no_citation_blocks_with_a_reason(self):
        v = truth.gate("Predator requires compiler because both are hard.", CORPUS)
        self.assertFalse(v["ok"])
        self.assertIn("no citation", v["reason"])

    def test_citation_in_corpus_passes(self):
        v = truth.gate('A states that "compiler inlining reduces call overhead" holds.', CORPUS)
        self.assertTrue(v["ok"])
        self.assertIn("found", v["reason"])

    def test_citation_outside_corpus_blocks_and_reports_ratio(self):
        v = truth.gate('A states that "the moon is made of green cheese, obviously" holds.', CORPUS)
        self.assertFalse(v["ok"])
        self.assertIn("not in the corpus", v["reason"])

    def test_blockquote_body_passes(self):
        v = truth.gate("> Compiler backends schedule machine instructions.\n\nDirection: x", CORPUS)
        self.assertTrue(v["ok"])


class StepGateTest(unittest.TestCase):
    """The wiring: verdict logged always, blocking only when truth_gate=True."""

    def _crossing_draft(self, quote: str = ""):
        original = cells.draft

        def fake(gap, evidence, use_qwen=True, nudge=""):
            a1, a2 = gap["group_a"][0], gap["group_a"][1]
            b1, b2 = gap["group_b"][0], gap["group_b"][1]
            return {
                "text": f"{a1} requires {b1} because {a2} and {b2} shape survival.{quote}",
                "error": None,
                "ms": 1,
            }

        cells.draft = fake
        return original

    def test_default_logs_the_verdict_but_never_blocks(self):
        original = self._crossing_draft()
        try:
            cs = [cells.Cell(id="h1", text=CORPUS, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False)
        finally:
            cells.draft = original
        self.assertIn("cell", res, "gate must be opt-in: default step still writes")
        self.assertTrue(any(line.startswith("gate    blocked") for line in res["log"]))
        self.assertFalse(res["cell"].meta["truth"]["ok"])

    def test_truth_gate_blocks_an_uncited_draft(self):
        original = self._crossing_draft()
        seen = []
        try:
            cs = [cells.Cell(id="h1", text=CORPUS, role="seed")]
            cells.assign(cs)
            res = cells.step(
                cs,
                mode="draft",
                use_needle=False,
                use_qwen=False,
                truth_gate=True,
                sink=lambda k, p, a: seen.append((k, p, a)),
            )
        finally:
            cells.draft = original
        self.assertNotIn("cell", res)
        self.assertTrue(res["stopped"].startswith("truth gate:"))
        self.assertTrue(any(line.startswith("gate    blocked") for line in res["log"]))
        blocked = [(k, p, a) for k, p, a in seen if p.get("who") == "truth"]
        self.assertEqual(len(blocked), 1, "the blocking decision must be a control event")
        self.assertEqual(blocked[0][2], "truth")

    def test_truth_gate_writes_when_the_draft_cites_the_corpus(self):
        original = self._crossing_draft(quote=' As stated: "compiler inlining reduces call overhead."')
        try:
            cs = [cells.Cell(id="h1", text=CORPUS, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False, truth_gate=True)
        finally:
            cells.draft = original
        self.assertIn("cell", res, res.get("stopped", ""))
        self.assertTrue(res["cell"].meta["truth"]["ok"])
        self.assertTrue(any(line.startswith("gate    pass") for line in res["log"]))

    def test_quote_mode_passes_because_the_cell_is_evidence(self):
        cs = [cells.Cell(id="h1", text=CORPUS, role="seed")]
        cells.assign(cs)
        res = cells.step(cs, mode="quote", use_needle=False, use_qwen=False, truth_gate=True)
        self.assertIn("cell", res, res.get("stopped", ""))
        self.assertTrue(res["cell"].meta["truth"]["ok"])


if __name__ == "__main__":
    unittest.main()
