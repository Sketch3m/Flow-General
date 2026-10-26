import json
import tempfile
import unittest
from pathlib import Path

import cells
import harness


class ValidateEditTest(unittest.TestCase):
    def test_accepts_valid_values(self):
        for edit in ({"draft_tries": 4}, {"draft_hint": "state the verb first"}, {"draft_system": "x" * 60}):
            clean, err = harness.validate_edit(edit)
            self.assertEqual(err, "")
            self.assertEqual(clean, edit)

    def test_rejects_unknown_field(self):
        _, err = harness.validate_edit({"system_prompt": "anything"})
        self.assertIn("unknown field", err)

    def test_rejects_wrong_type_and_range(self):
        self.assertIn("must be int", harness.validate_edit({"draft_tries": "3"})[1])
        self.assertIn("outside", harness.validate_edit({"draft_tries": 9})[1])
        self.assertIn("outside", harness.validate_edit({"draft_hint": "x" * 400})[1])
        self.assertIn("must be an integer", harness.validate_edit({"draft_tries": True})[1])
        self.assertIn("not an object", harness.validate_edit({})[1])


class ProposeRulesTest(unittest.TestCase):
    def test_relation_verb_failure_adds_a_hint(self):
        old = harness.HARNESS["draft_hint"]
        harness.HARNESS["draft_hint"] = ""
        try:
            edit, reason = harness._rules_edit("3 drafts rejected: no relation verb, no relation verb, no relation verb")
        finally:
            harness.HARNESS["draft_hint"] = old
        self.assertEqual(edit["draft_hint"], "Use one of these verbs: requires, implies, supports, depends on, causes.")
        self.assertIn("relation verb", reason)

    def test_missing_term_failure_adds_a_hint(self):
        edit, _ = harness._rules_edit("2 drafts rejected: missing compiler")
        self.assertIn("both terms", edit["draft_hint"])

    def test_unknown_failure_spends_an_attempt(self):
        old = harness.HARNESS["draft_tries"]
        harness.HARNESS["draft_tries"] = 1
        try:
            edit, _ = harness._rules_edit("model timed out")
            self.assertEqual(edit, {"draft_tries": 2})
        finally:
            harness.HARNESS["draft_tries"] = old

    def test_propose_offline_falls_back_to_rules(self):
        r = harness.propose("no relation verb", use_qwen=False)
        self.assertEqual(r["by"], "rules")
        self.assertIn("qwen disabled", r["error"])
        self.assertEqual(r["field"], "draft_hint")


class GateTest(unittest.TestCase):
    B = {"crossed": 1, "satisfied": 2, "fails": 3, "stopped": ""}

    def test_keeps_when_crossings_rise(self):
        keep, why = harness.gate(self.B, {**self.B, "crossed": 2})
        self.assertTrue(keep)
        self.assertIn("crossings 1 -> 2", why)

    def test_keeps_when_drafts_improve_and_failures_hold(self):
        keep, _ = harness.gate(self.B, {**self.B, "satisfied": 5})
        self.assertTrue(keep)

    def test_rejects_regression_or_more_failures(self):
        self.assertFalse(harness.gate(self.B, {**self.B, "crossed": 0})[0])
        self.assertFalse(harness.gate(self.B, {**self.B, "fails": 4})[0])
        self.assertFalse(harness.gate(self.B, dict(self.B))[0])


class TraceTest(unittest.TestCase):
    def test_record_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trace.json"
            harness.record({"ts": 1, "kept": False}, p)
            harness.record({"ts": 2, "kept": True}, p)
            log = json.loads(p.read_text())
            self.assertEqual([e["ts"] for e in log], [1, 2])

    def test_state_loads_each_field_and_drops_silly_values(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "harness.json"
            p.write_text(json.dumps({"draft_tries": 99, "draft_hint": "keep this hint"}))
            old_state = harness.STATE
            harness.STATE = p
            try:
                loaded = harness._load()
            finally:
                harness.STATE = old_state
            self.assertEqual(loaded["draft_tries"], 3)  # out of range -> default
            self.assertEqual(loaded["draft_hint"], "keep this hint")  # non-first field survives
            self.assertEqual(loaded["draft_system"], harness.DEFAULTS["draft_system"])


class LiveHarnessReadTest(unittest.TestCase):
    """cells.step must take tries from the harness, not a frozen constant."""

    def test_step_uses_harness_tries(self):
        original_draft = cells.draft
        calls = {"n": 0}

        def bad_draft(gap, evidence, use_qwen=True, nudge=""):
            calls["n"] += 1
            return {"text": "A sentence with no verbs at all.", "error": None, "ms": 1}

        cells.draft = bad_draft
        old_tries = harness.HARNESS["draft_tries"]
        harness.HARNESS["draft_tries"] = 1
        try:
            # Same two-disconnected-topics fixture as test_cells: over 40 words,
            # so step() analyses it and finds an unbridged gap to draft against.
            from test_cells import TEXT

            cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
            cells.assign(cs)
            res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False)
            self.assertEqual(calls["n"], 1)
            self.assertIn("sentence 1/1", res["log"][-1])
        finally:
            cells.draft = original_draft
            harness.HARNESS["draft_tries"] = old_tries


if __name__ == "__main__":
    unittest.main()
