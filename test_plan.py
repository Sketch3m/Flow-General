import unittest
from types import SimpleNamespace
from unittest import mock

import cells
import plan
from test_cells import TEXT


def gaps(*pairs):
    return [SimpleNamespace(id=f"{a}~{b}", score=s) for a, b, s in pairs]


class BudgetTest(unittest.TestCase):
    def test_shape_scales_with_gaps_but_never_exceeds_the_cap(self):
        for n in range(0, 21):
            p = plan.budget(gaps(*[(f"a{i}", f"b{i}", 0.1 / (i + 1)) for i in range(n)]))
            if n == 0:
                self.assertEqual(p["subagents"], 0)
                self.assertEqual(p["generations"], 0)
                continue
            self.assertLessEqual(p["subagents"], plan.MAX_SUBAGENTS)
            self.assertLessEqual(p["cap"], plan.MAX_ATTEMPTS)
            self.assertLessEqual(p["generations"], plan.MAX_GENERATIONS)
            self.assertGreaterEqual(p["generations"], 1)
            self.assertEqual(len(p["targets"]), p["subagents"])

    def test_targets_are_the_highest_scoring_gaps(self):
        p = plan.budget(gaps(("a", "b", 0.03), ("c", "d", 0.7), ("e", "f", 0.4)))
        # three gaps -> three lanes, in score order
        self.assertEqual(p["targets"], ["c~d", "e~f", "a~b"])
        self.assertEqual(p["scores"]["c~d"], 0.7)


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.plan = plan.budget(gaps(("a", "b", 0.5), ("c", "d", 0.2)))

    def test_rules_approve_when_needle_is_off(self):
        ap = plan.approval(self.plan, use_needle=False)
        self.assertEqual(ap["decision"], "approve")
        self.assertEqual(ap["by"], "rules")
        self.assertIn("disabled", ap["error"])

    def test_needle_adjust_is_clamped_to_the_hard_cap(self):
        fake = {"call": {"name": "adjust", "arguments": {"generations": 99}}, "confidence": 0.4, "reasoning": "fewer"}
        with mock.patch("localmodels.route", return_value=fake):
            ap = plan.approval(self.plan, use_needle=True)
        self.assertEqual(ap["decision"], "adjust")
        self.assertEqual(ap["generations"], plan.MAX_GENERATIONS)  # 99 cannot raise the cap
        self.assertEqual(ap["by"], "needle")

    def test_broken_needle_response_falls_back_to_rules(self):
        with mock.patch("localmodels.route", side_effect=RuntimeError("boom")):
            ap = plan.approval(self.plan, use_needle=True)
        self.assertEqual(ap["decision"], "approve")
        self.assertEqual(ap["by"], "rules")
        self.assertIn("boom", ap["error"])

    def test_no_gaps_refuses_without_a_model(self):
        ap = plan.approval(plan.budget([]), use_needle=False)
        self.assertEqual(ap["decision"], "refuse")


class RunnerTerminationTest(unittest.TestCase):
    def _sheet(self):
        cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
        cells.assign(cs)
        return cs

    def test_silent_world_stops_by_patience_not_by_looping(self):
        cs = self._sheet()
        calls = {"n": 0}

        def no_progress(*a, **k):
            calls["n"] += 1
            return {"stopped": "qwen produced nothing", "log": ["qwen    sentence 1/3 1 ms - empty: "]}

        with mock.patch.object(cells, "step", side_effect=no_progress):
            res = plan.run(cs, use_qwen=False, use_needle=False)
        self.assertEqual(res["stopped"], "patience spent")
        self.assertEqual(res["generations_run"], 1)
        self.assertEqual(calls["n"], plan.budget(plan._open(cs)[0])["subagents"] or calls["n"])
        self.assertLessEqual(calls["n"], plan.MAX_ATTEMPTS)

    def test_progress_runs_all_generations_but_still_bounded(self):
        cs = self._sheet()
        calls = {"n": 0}

        def crossing(*a, **k):
            calls["n"] += 1
            g = plan._open(cs)[0][0]
            text = f"{g.terms_a[0]} requires {g.terms_b[0]} because {g.terms_a[1]} and {g.terms_b[1]} matter."
            cell = cells.Cell(id=f"x{calls['n']}", text=text, origin="qwen-draft", role="hypothesis")
            cells.assign([cell])
            acc = cells.accept(g.terms_a, g.terms_b, plan._open(cs)[1].graph.nodes, text)
            cell.meta["crossed"] = acc["ok"]
            return {"cell": cell, "log": ["qwen    sentence 1/3 1 ms - ok: " + text[:40]]}

        with mock.patch.object(cells, "step", side_effect=crossing):
            res = plan.run(cs, use_qwen=False, use_needle=False)
        # whatever the graph does, the run halts: either the fake closing every
        # gap (early success) or the hard generation cap - both bounded
        self.assertIn(res["stopped"], ("no unbridged gaps", "generations exhausted"))
        self.assertLessEqual(calls["n"], plan.MAX_ATTEMPTS)
        self.assertLessEqual(res["generations_run"], plan.MAX_GENERATIONS)

    def test_refusal_never_calls_step(self):
        cs = self._sheet()
        with mock.patch.object(plan, "approval", return_value={"decision": "refuse", "generations": 0, "by": "needle", "confidence": 0.9, "reason": "no", "ms": 5, "error": None}):
            with mock.patch.object(cells, "step") as step:
                res = plan.run(cs, use_qwen=False, use_needle=True)
        step.assert_not_called()
        self.assertEqual(res["stopped"], "approval refused")

    def test_approval_lands_as_a_control_event(self):
        cs = self._sheet()
        seen = []
        with mock.patch.object(cells, "step", return_value={"stopped": "qwen produced nothing", "log": []}):
            plan.run(cs, use_qwen=False, use_needle=False, sink=lambda k, p, a: seen.append((k, p, a)))
        approvals = [(k, p, a) for k, p, a in seen if p.get("action", "").startswith("plan-")]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0][1]["action"], "plan-approve")
        self.assertEqual(approvals[0][2], "rules")


class TargetTest(unittest.TestCase):
    def test_unknown_target_falls_back_to_the_top_gap(self):
        cs = [cells.Cell(id="h1", text=TEXT, role="seed")]
        cells.assign(cs)
        top_id = plan._open(cs)[0][0].id
        res = cells.step(cs, mode="draft", use_needle=False, use_qwen=False, target="not-a-gap")
        self.assertEqual(res["gap"]["id"], top_id)


if __name__ == "__main__":
    unittest.main()
