import unittest

import eval_route


class CardsTest(unittest.TestCase):
    def test_twenty_cards_balanced_and_truth_is_exclusive(self):
        cards = eval_route.make_cards()
        self.assertEqual(len(cards), 20)
        self.assertEqual({c["truth"] for c in cards}, {"draft", "ask", "stop"})
        counts = {t: sum(1 for c in cards if c["truth"] == t) for t in ("draft", "ask", "stop")}
        self.assertEqual(counts, {"draft": 8, "stop": 6, "ask": 6})
        self.assertEqual(len({c["id"] for c in cards}), 20)

    def test_rules_floor_is_perfect_because_facts_are_on_the_card(self):
        cards = eval_route.make_cards()
        for c in cards:
            self.assertEqual(eval_route.route_rules(c["text"]), c["truth"], c["id"])

    def test_matrix_counts_confusion(self):
        cards = eval_route.make_cards()
        preds = [c["truth"] for c in cards]
        m = eval_route._matrix(cards, preds)
        self.assertEqual(m["accuracy"], 1.0)
        m2 = eval_route._matrix(cards, ["ask"] * len(cards))
        self.assertLess(m2["accuracy"], 1.0)
        self.assertEqual(m2["per"]["stop"]["confusion"], {"ask": 6})


class IntendedFormatTest(unittest.TestCase):
    def test_intended_rendering_keeps_the_rules_floor(self):
        # the format change must not hide the facts: the floor is only a
        # floor if the truth survives the rendering
        for c in eval_route.make_cards():
            rendered = eval_route.render_intended(c["text"])
            self.assertEqual(eval_route.route_rules(rendered), c["truth"], c["id"])

    def test_intended_rendering_names_the_functions(self):
        rendered = eval_route.render_intended("Cell sheet. Human direction: ...")
        for fn in ("draft", "ask", "stop"):
            self.assertIn(fn, rendered)


class PickOfTest(unittest.TestCase):
    def test_dispatched_call_wins(self):
        r = {"call": {"name": "draft"}, "suppressed_call": {"name": "stop"}}
        self.assertEqual(eval_route.pick_of(r), "draft")
        self.assertEqual(eval_route.pick_of(r, include_suppressed=False), "draft")

    def test_held_back_call_is_selection_but_never_act(self):
        r = {"call": None, "suppressed_call": {"name": "stop"}}
        self.assertEqual(eval_route.pick_of(r), "stop")
        self.assertEqual(eval_route.pick_of(r, include_suppressed=False), "none")

    def test_empty_answer_is_none_not_ask(self):
        # the published 30% defaulted empties to ask; none is the honest label
        self.assertEqual(eval_route.pick_of({"call": None, "suppressed_call": None}), "none")
        self.assertEqual(eval_route.pick_of({"call": {"name": "mystery"}}), "none")


class ScoreNeedleTest(unittest.TestCase):
    def test_act_and_selection_score_different_things(self):
        cards = eval_route.make_cards()
        original_route = eval_route.localmodels.route
        seen = []

        def fake_route(card, tools=None, forced=False):
            seen.append((card, forced))
            i = len(seen)
            if i == 1:  # first card: dispatched correctly (truth: draft)
                return {"call": {"name": "draft"}, "suppressed_call": None, "confidence": 0.7, "error": None, "suppressed": False}
            if i == 2:  # second: right pick, held back by the floor
                return {"call": None, "suppressed_call": {"name": "draft"}, "confidence": 0.05, "error": None, "suppressed": True}
            return {"call": None, "suppressed_call": None, "confidence": 0.02, "error": None, "suppressed": False}

        eval_route.localmodels.route = fake_route
        try:
            s = eval_route.score_needle(cards, intended=False, forced=True)
        finally:
            eval_route.localmodels.route = original_route
        self.assertEqual(s["act"]["accuracy"], 1 / len(cards))
        self.assertEqual(s["sel"]["accuracy"], 2 / len(cards))
        self.assertEqual(s["held"], 1)
        self.assertEqual(s["errors"], 0)
        self.assertTrue(all(forced for _, forced in seen), "forced must reach the engine")

    def test_intended_flag_renders_before_routing(self):
        cards = eval_route.make_cards()
        original_route = eval_route.localmodels.route
        prompts = []

        def fake_route(card, tools=None, forced=False):
            prompts.append(card)
            return {"call": None, "suppressed_call": None, "confidence": 0.0, "error": None, "suppressed": False}

        eval_route.localmodels.route = fake_route
        try:
            eval_route.score_needle(cards[:2], intended=True)
        finally:
            eval_route.localmodels.route = original_route
        self.assertTrue(all(p.startswith("Question:") for p in prompts))


if __name__ == "__main__":
    unittest.main()
