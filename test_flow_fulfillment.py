"""Headless proofs of a real nested conversation store, without simulated AI."""
import tempfile
import unittest
from pathlib import Path

import flow_fulfillment as f


class FulfillmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "site.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_root_idempotent_and_cell_isolation(self):
        a = f.ensure_root("cell-a", "Investigate hypothesis", self.db)
        self.assertEqual(a, f.ensure_root("cell-a", "Different prompt", self.db))
        b = f.ensure_root("cell-b", "Other question", self.db)
        self.assertNotEqual(a, b)
        self.assertEqual(len(f.tree("cell-a", self.db)), 1)
        self.assertEqual(f.tree("cell-a", self.db)[0]["messages"][0]["text"],
                         "Investigate hypothesis")
        self.assertEqual(f.tree("cell-b", self.db)[0]["cell_id"], "cell-b")

    def test_subchats_and_manual_report_back(self):
        root = f.ensure_root("cell-a", "Formulate a theory", self.db)
        child = f.open_child(root, "Mathematical investigation", "Prove the bound", self.db)
        f.post_user_message(child, "Check the nonlinear case", self.db)
        grandchild = f.open_child(child, "Counterexample", "Look for edge cases", self.db)
        f.finish_child(grandchild, "Candidate contradiction under boundary X", self.db)
        f.finish_child(child, "A bound holds conditionally", self.db)
        threads = f.tree("cell-a", self.db)
        self.assertEqual([t["depth"] for t in threads], [0, 1, 2])
        self.assertEqual([t["status"] for t in threads], ["open", "completed", "completed"])
        msgs = threads[0]["messages"]
        self.assertEqual(msgs[-1]["source"], "manual_child_report")
        self.assertIn("conditionally", msgs[-1]["text"])
        self.assertNotIn("assistant", [m["role"] for t in threads for m in t["messages"]])
        with self.assertRaises(ValueError):
            f.finish_child(child, "replay", self.db)
        with self.assertRaises(ValueError):
            f.post_user_message(child, "after close", self.db)

    def test_validation_and_cancellation(self):
        root = f.ensure_root("cell-c", "An intent", self.db)
        ch = f.open_child(root, "Worker", "A job", self.db)
        grand = f.open_child(ch, "Nested", "More work", self.db)
        with self.assertRaises(ValueError):
            f.open_child(grand, "Too deep", "Nope", self.db)
        with self.assertRaises(ValueError):
            f.post_user_message(root, "x" * (f.MAX_TEXT + 1), self.db)
        with self.assertRaises(ValueError):
            f.open_child(root, "Invalid", "", self.db)
        self.assertEqual(f.cancel_thread(ch, self.db), 2)
        self.assertEqual(f.tree("cell-c", self.db)[0]["status"], "open")
        self.assertEqual([t["status"] for t in f.tree("cell-c", self.db)][1:],
                         ["cancelled", "cancelled"])
        with self.assertRaises(ValueError):
            f.open_child(ch, "After stop", "No", self.db)

    def test_durable_reload_and_audit(self):
        root = f.ensure_root("cell-a", "Explore", self.db)
        child = f.open_child(root, "Subchat", "First question", self.db)
        f.finish_child(child, "This is only a human report", self.db)
        self.assertEqual([e["kind"] for e in f.events(child, self.db)],
                         ["opened", "completed"])
        self.assertEqual(f.tree("cell-a", self.db)[1]["messages"][-1]["source"],
                         "manual_report")


if __name__ == "__main__":
    unittest.main()
