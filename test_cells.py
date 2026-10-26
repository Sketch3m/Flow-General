import unittest

import cells
import nodus

# Two topics with no shared vocabulary: the graph must see a gap between them.
TEXT = (
    "Predator populations depend on prey abundance. Prey populations grow when "
    "predator numbers fall. Predator and prey dynamics oscillate over seasons. "
    "Predator hunting rates shape prey survival. "
    "Compiler optimisation rewrites intermediate representation. Compiler passes "
    "lower the intermediate representation into machine code. Compiler backends "
    "schedule machine instructions. Compiler inlining reduces call overhead."
)


class GroundingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = nodus.analyse(TEXT, max_gaps=5)
        cls.gap = next(g for g in cls.a.gaps if not g.bridged)

    def _accept(self, sentence):
        return cells.accept(self.gap.terms_a, self.gap.terms_b, self.a.graph.nodes, sentence)

    def test_bare_relation_between_one_term_each_is_not_grounded(self):
        s = f"{self.gap.terms_a[0]} implies {self.gap.terms_b[0]}"
        acc = self._accept(s)
        self.assertFalse(acc["grounded"])
        self.assertFalse(acc["ok"])

    def test_grounded_sentence_with_terms_on_both_sides_passes(self):
        a1, a2 = self.gap.terms_a[:2]
        b1, b2 = self.gap.terms_b[:2]
        s = f"{a1} and {a2} requires {b1} and {b2} because they share the same dynamics."
        acc = self._accept(s)
        self.assertTrue(acc["grounded"])
        self.assertTrue(acc["ok"])


class SatisfiesTest(unittest.TestCase):
    NODES = {"predator", "prey", "compiler", "machine"}

    def test_rejects_draft_missing_a_gap_term(self):
        ok, why = cells.satisfies("Predator populations depend on food.", "predator", "compiler", self.NODES)
        self.assertFalse(ok)
        self.assertIn("compiler", why)

    def test_rejects_draft_without_relation_verb(self):
        ok, why = cells.satisfies("Predator and prey and compiler and machine.", "predator", "compiler", self.NODES)
        self.assertFalse(ok)
        self.assertEqual(why, "no relation verb")

    def test_accepts_draft_with_both_terms_and_relation(self):
        ok, _ = cells.satisfies("Predator requires compiler.", "predator", "compiler", self.NODES)
        self.assertTrue(ok)


class EditTest(unittest.TestCase):
    def _sheet(self):
        return [cells.Cell(id="c1", text="A duck crosses the street."), cells.Cell(id="c2", text="Other.")]

    def test_edit_changes_only_the_target_and_reinfers_view(self):
        cs = cells.edit(self._sheet(), "c1", "Predator and prey populations oscillate.")
        self.assertEqual(cs[0].view, "plot")
        self.assertEqual(cs[1].text, "Other.")

    def test_edit_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            cells.edit(self._sheet(), "c9", "x")


class RepresentativesTest(unittest.TestCase):
    def test_skips_glue_heads(self):
        reps = cells.representatives(["across", "quantization", "fixed", "denois"])
        self.assertNotIn("across", reps)
        self.assertIn("quantization", reps)

    def test_falls_back_when_every_term_is_glue(self):
        self.assertEqual(cells.representatives(["across", "between"]), ["across", "between"])


class GroupSatisfiesTest(unittest.TestCase):
    NODES = {"quantization", "denois", "governance", "record"}

    def test_accepts_one_term_from_each_group(self):
        ok, why = cells.satisfies(
            "Quantization requires governance because precision is auditable.",
            ["quantization", "denois"],
            ["governance", "record"],
            self.NODES,
        )
        self.assertTrue(ok, why)

    def test_rejects_sentence_from_one_side_only(self):
        ok, why = cells.satisfies(
            "Governance and record and evidence are retained.",
            ["quantization", "denois"],
            ["governance", "record"],
            self.NODES,
        )
        self.assertFalse(ok)
        self.assertIn("missing", why)


class StepCrossTest(unittest.TestCase):
    """step() must resample until accept() passes, and report crossing honestly."""

    def test_draft_that_crosses_is_accepted_and_logged(self):
        original_draft = cells.draft
        calls = {"n": 0}

        def crossing_draft(gap, evidence, use_qwen=True, nudge=""):
            calls["n"] += 1
            if calls["n"] == 1:
                # passes satisfies() (both groups + verb) but does not cross
                return {"text": "Compiler and inlining and backend scheduling are hard.", "error": None, "ms": 1}
            # built from the gap's own groups: subject from A, object from B,
            # a second term per side - exactly what accept() demands
            a1, a2 = gap["group_a"][0], gap["group_a"][1]
            b1, b2 = gap["group_b"][0], gap["group_b"][1]
            return {
                "text": f"{a1} requires {b1} because {a2} and {b2} shape survival.",
                "error": None,
                "ms": 1,
            }

        cells.draft = crossing_draft
        try:
            cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False)
        finally:
            cells.draft = original_draft
        self.assertEqual(calls["n"], 2, "pre-filter pass must get an accept check and a retry")
        self.assertTrue(res["cell"].meta["crossed"])
        self.assertTrue(any("check   crosses" in line for line in res["log"]))

    def test_log_distinguishes_ungrounded_crossing(self):
        original_draft = cells.draft

        def ungrounded(gap, evidence, use_qwen=True, nudge=""):
            # relation crosses (A -> B) but only one term per side
            return {"text": f"{gap['group_a'][0]} requires {gap['group_b'][0]}.", "error": None, "ms": 1}

        cells.draft = ungrounded
        try:
            cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False)
        finally:
            cells.draft = original_draft
        self.assertTrue(any("crosses, not grounded" in line for line in res["log"]))


class SinkTest(unittest.TestCase):
    def test_control_events_cite_the_observed_gap(self):
        original_draft = cells.draft

        def crossing_draft(gap, evidence, use_qwen=True, nudge=""):
            a1, a2 = gap["group_a"][0], gap["group_a"][1]
            b1, b2 = gap["group_b"][0], gap["group_b"][1]
            return {"text": f"{a1} requires {b1} because {a2} and {b2} shape survival.", "error": None, "ms": 1}

        cells.draft = crossing_draft
        seen = []
        try:
            cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False, sink=lambda k, p, a: seen.append((k, p, a)))
        finally:
            cells.draft = original_draft
        self.assertEqual([k for k, _, _ in seen], ["control", "control"])
        self.assertEqual([p["who"] for _, p, _ in seen], ["needle", "nodus"])
        # both decisions cite the gap they observed - the walkable part
        self.assertEqual({p["gap"] for _, p, _ in seen}, {res["gap"]["id"]})
        self.assertTrue(seen[1][1]["crossed"])
        self.assertEqual([a for _, _, a in seen], ["rules", "nodus"])

    def test_no_sink_means_no_writes(self):
        original_draft = cells.draft
        cells.draft = lambda *a, **k: {"text": "", "error": None, "ms": 1}
        try:
            cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False)
        finally:
            cells.draft = original_draft
        self.assertIn(res.get("stopped"), ("qwen produced nothing",))


class FoldTest(unittest.TestCase):
    """cells.from_log: the page is a fold over the document and the log."""

    DOC = "# Title\n\nA paragraph long enough to stand alone as its own cell in the sheet.\n\nAnother paragraph that says something else entirely, at some length."

    def test_blocks_keep_a_heading_with_its_paragraph(self):
        bs = cells.blocks(self.DOC)
        self.assertEqual(len(bs), 2)
        self.assertTrue(bs[0].startswith("# Title"))
        self.assertIn("paragraph", bs[0])

    def test_short_trailing_fragment_does_not_become_its_own_cell(self):
        bs = cells.blocks("A sufficiently long opening paragraph that carries the document.\n\nTail.")
        self.assertEqual(len(bs), 1)
        self.assertIn("Tail.", bs[0])

    def test_document_alone_gives_no_proposals(self):
        doc_cells, proposals = cells.from_log(self.DOC, {})
        self.assertEqual(len(doc_cells), 2)
        self.assertEqual(proposals, [])
        self.assertEqual(doc_cells[0].id, "d1")

    def test_a_human_edit_replaces_the_text_and_re_infers_the_view(self):
        folded = {"d1": {"text": "Is this a question, now?", "added_by": "human"}}
        doc_cells, _ = cells.from_log(self.DOC, folded)
        self.assertEqual(doc_cells[0].text, "Is this a question, now?")
        self.assertEqual(doc_cells[0].view, "")
        cells.assign(doc_cells)
        self.assertEqual(doc_cells[0].view, "question")

    def test_agent_cells_become_proposals_in_id_order(self):
        folded = {
            "c10": {"id": "c10", "text": "second", "added_by": "qwen", "role": "hypothesis"},
            "c9": {"id": "c9", "text": "first", "added_by": "qwen", "role": "hypothesis"},
            "d1": {"id": "d1", "text": "a doc cell", "added_by": "human"},
        }
        _, proposals = cells.from_log(self.DOC, folded)
        self.assertEqual([p.text for p in proposals], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
