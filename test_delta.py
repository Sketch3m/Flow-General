import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import delta


class LogBasicsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name) / "delta.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_append_roundtrip_with_stable_sortable_ids(self):
        a = delta.append("cell_add", {"id": "c1", "text": "hi"}, path=self.p)
        b = delta.append("cell_edit", {"id": "c1", "text": "hi!"}, actor="qwen", path=self.p)
        got = delta.events(self.p)
        self.assertEqual([e["seq"] for e in got], [1, 2])
        self.assertLess(a["id"], b["id"])  # ULIDs sort by time
        self.assertEqual(len({a["id"], b["id"]}), 2)
        self.assertEqual(got[1]["actor"], "qwen")
        self.assertEqual(got[1]["parents"], [hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False).encode()).hexdigest()])

    def test_kind_filter_and_empty_file(self):
        delta.append("cell_add", {"id": "c1"}, path=self.p)
        delta.append("harness_edit", {"field": "draft_tries", "kept": True, "value": 4}, path=self.p)
        self.assertEqual(len(delta.events(self.p)), 2)
        self.assertEqual(len(delta.events(self.p, kind="harness_edit")), 1)
        self.assertEqual(delta.events(Path(self.dir.name) / "nope.jsonl"), [])

    def test_verify_detects_tampering_and_reordering(self):
        delta.append("cell_add", {"id": "c1", "text": "one"}, path=self.p)
        delta.append("cell_edit", {"id": "c1", "text": "two"}, path=self.p)
        ok, bad, _ = delta.verify(self.p)
        self.assertTrue(ok, "intact chain must verify")
        # tamper with line 1's payload
        lines = self.p.read_text().splitlines()
        ev = json.loads(lines[0])
        ev["payload"]["text"] = "rewritten history"
        lines[0] = json.dumps(ev, sort_keys=True, ensure_ascii=False)
        self.p.write_text("\n".join(lines) + "\n")
        ok, bad, msg = delta.verify(self.p)
        self.assertFalse(ok)
        # line 1's own parents are empty and match; the break shows at line 2,
        # whose parent still points at the original line 1
        self.assertEqual(bad, 2)
        self.assertIn("matches no earlier line", msg)

    def test_fold_and_state_at_reconstruct_past_text(self):
        delta.append("cell_add", {"id": "c1", "text": "v1"}, path=self.p)
        delta.append("cell_edit", {"id": "c1", "text": "v2"}, path=self.p)
        delta.append("cell_add", {"id": "c2", "text": "other"}, path=self.p)
        self.assertEqual(delta.fold_cells(self.p)["c1"]["text"], "v2")
        past = delta.state_at(delta.cell_reducer, {}, seq=1, path=self.p)
        self.assertEqual(past["c1"]["text"], "v1")
        self.assertNotIn("c2", past)

    def test_edit_keeps_previous_versions(self):
        delta.append("cell_add", {"id": "c1", "text": "first"}, path=self.p)
        delta.append("cell_edit", {"id": "c1", "text": "second"}, actor="human", path=self.p)
        state = delta.fold_cells(self.p)
        self.assertEqual(state["c1"]["text"], "second")
        self.assertEqual(state["c1"]["previous"], [{"text": "first", "at": delta.events(self.p)[1]["ts"], "by": "human"}])

    def test_sheet_state_replaces_everything(self):
        delta.append("cell_add", {"id": "c1", "text": "old"}, path=self.p)
        delta.append("sheet_state", {"cells": [{"id": "p1", "text": "paper"}]}, actor="human", path=self.p)
        state = delta.fold_cells(self.p)
        self.assertEqual(list(state), ["p1"])

    def test_fold_harness_keeps_only_kept_edits_in_order(self):
        delta.append("harness_edit", {"field": "draft_tries", "value": 4, "kept": False}, path=self.p)
        delta.append("harness_edit", {"field": "draft_tries", "value": 5, "kept": True}, path=self.p)
        delta.append("harness_edit", {"field": "draft_hint", "value": "use the shape", "kept": True}, path=self.p)
        delta.append("harness_edit", {"field": "draft_hint", "value": "x", "kept": False}, path=self.p)
        self.assertEqual(delta.fold_harness(self.p), {"draft_tries": 5, "draft_hint": "use the shape"})

    def test_record_context_carries_paper_hashes(self):
        ev = delta.record_context("smoke", path=self.p)
        ctx = ev["payload"]["context"]
        self.assertIn("harness", ctx)
        self.assertIn("papers", ctx)
        for p in ctx["papers"]:
            self.assertEqual(len(p["sha"]), 16)


class DagTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name) / "delta.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_fork_via_base_lists_both_tips_and_still_verifies(self):
        a = delta.append("control", {"who": "needle", "gap": "x~y"}, path=self.p)
        a_hash = hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        delta.append("cell_add", {"id": "c1", "text": "agent B"}, path=self.p)
        # agent A pins the state it observed (a) instead of the tip - a fork
        delta.append("cell_add", {"id": "c2", "text": "agent A"}, base=a_hash, path=self.p)
        ok, bad, _ = delta.verify(self.p)
        self.assertTrue(ok)
        self.assertEqual(len(delta.tips(self.p)), 2)  # both forks are open ends
        self.assertEqual(len(delta.fold_cells(self.p)), 2)  # fold keeps both children

    def test_unknown_base_is_rejected(self):
        delta.append("cell_add", {"id": "c1"}, path=self.p)
        with self.assertRaises(ValueError):
            delta.append("cell_add", {"id": "c2"}, base="0" * 64, path=self.p)

    def test_legacy_prev_lines_still_verify(self):
        # a file written by the chain-era code: 'prev' instead of 'parents'
        l1 = {"id": "old1", "seq": 1, "ts": 1, "kind": "cell_add", "actor": "human", "payload": {"id": "c1", "text": "v1"}, "prev": None}
        j1 = json.dumps(l1, sort_keys=True, ensure_ascii=False)
        l2 = {"id": "old2", "seq": 2, "ts": 2, "kind": "cell_edit", "actor": "human", "payload": {"id": "c1", "text": "v2"}, "prev": hashlib.sha256(j1.encode()).hexdigest()}
        self.p.write_text(j1 + "\n" + json.dumps(l2, sort_keys=True, ensure_ascii=False) + "\n")
        ok, _, _ = delta.verify(self.p)
        self.assertTrue(ok, "legacy chain-era files must keep verifying")
        self.assertEqual(delta.fold_cells(self.p)["c1"]["text"], "v2")
        # and new appends extend it
        delta.append("cell_add", {"id": "c2", "text": "new"}, path=self.p)
        ok, _, _ = delta.verify(self.p)
        self.assertTrue(ok)

    def test_checkpoint_catches_a_relinked_rewrite(self):
        delta.append("cell_add", {"id": "c1", "text": "original"}, path=self.p)
        delta.append("cell_edit", {"id": "c1", "text": "edited"}, path=self.p)
        delta.checkpoint(self.p)
        # attacker rewrites line 1 and *relinks* every parent that follows:
        # verify() alone would pass this.
        lines = self.p.read_text().splitlines()
        ev1 = json.loads(lines[0])
        ev1["payload"]["text"] = "forged"
        lines[0] = json.dumps(ev1, sort_keys=True, ensure_ascii=False)
        for i in range(1, len(lines)):
            ev = json.loads(lines[i])
            if "parents" in ev and ev["parents"]:
                ev["parents"] = [hashlib.sha256(lines[i - 1].encode()).hexdigest()]
            lines[i] = json.dumps(ev, sort_keys=True, ensure_ascii=False)
        self.p.write_text("\n".join(lines) + "\n")
        self.assertTrue(delta.verify(self.p)[0], "relinked chain passes the lineage check")
        ok, bad, msg = delta.verify_checkpoints(self.p)
        self.assertFalse(ok, "the checkpoint must catch what relinking hides")
        self.assertIn("line 3", msg)

    def test_control_events_are_foldable_evidence(self):
        delta.append("control", {"who": "needle", "action": "draft", "gap": "x~y"}, actor="needle", path=self.p)
        delta.append("control", {"who": "nodus", "gap": "x~y", "crossed": True}, actor="nodus", path=self.p)
        controls = delta.events(self.p, kind="control")
        self.assertEqual([c["actor"] for c in controls], ["needle", "nodus"])
        self.assertTrue(controls[1]["payload"]["crossed"])


if __name__ == "__main__":
    unittest.main()
