import tempfile
import unittest
from pathlib import Path

import flow_site_runtime as r


class RuntimeTests(unittest.TestCase):
    def test_persistence_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            seed = [{"id": "flow-a", "text": "a", "kind": "reading"}]
            self.assertEqual(r.load(seed, db), seed)
            r.add({"id": "flow-b", "text": "b", "kind": "simulation", "params": {}}, db)
            r.update("flow-b", {"params": {"prey": 12, "pred": 5}},
                     {"kind": "parameter_change", "value": 12}, db)
            state = r.load([], db)
            self.assertEqual([c["id"] for c in state], ["flow-a", "flow-b"])
            self.assertEqual(state[1]["params"]["prey"], 12)
            self.assertEqual(r.history(db)[-1]["kind"], "parameter_change")
            self.assertEqual(len(r.add(state[1], db)), 2)

    def test_missing_cell_and_invalid_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            r.load([{"id":"flow-a","text":"a"}], db)
            with self.assertRaises(KeyError):
                r.update("missing", {"intent":"x"}, {}, db)
            with self.assertRaises(ValueError):
                r.update("flow-a", {"id":"other"}, {}, db)

    def test_proposal_provenance(self):
        p = r.adopt({"id":"g1","status":"done","grounded":False,"crossed":True,
                     "cell":{"text":"draft"}})
        self.assertFalse(p["provenance"]["grounded"])
        self.assertTrue(p["provenance"]["crossed"])


if __name__ == "__main__":
    unittest.main()
