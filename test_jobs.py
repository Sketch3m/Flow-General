"""jobs.py: the queue's contract.

Every test runs in its own temporary directory, because the queue and the delta
log both write files relative to the cwd.
"""

import os
import tempfile
import unittest
from pathlib import Path

import cells
import delta
import jobs
import plan


class QueueTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.path = Path("solve") / "jobs.jsonl"

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def enqueue(self, gap_id, **kw):
        return jobs.enqueue({"id": gap_id, "score": 0.4, "terms_a": ["a"], "terms_b": ["b"]}, path=self.path, **kw)

    def test_enqueue_then_claim_then_finish(self):
        r = self.enqueue("g1")
        self.assertTrue(r["ok"])
        self.assertEqual(jobs.state(self.path)["g1"]["status"], "open")

        job = jobs.claim("w1", self.path)
        self.assertEqual(job["id"], "g1")
        self.assertEqual(jobs.state(self.path)["g1"]["status"], "running")

        jobs.finish("g1", cell={"id": "c9"}, crossed=True, grounded=True, ms=42, path=self.path)
        st = jobs.state(self.path)["g1"]
        self.assertEqual(st["status"], "done")
        self.assertTrue(st["crossed"])
        self.assertEqual(st["cell"]["id"], "c9")

    def test_claim_takes_one_job_and_returns_none_when_empty(self):
        self.enqueue("g1")
        self.assertIsNotNone(jobs.claim("w1", self.path))
        self.assertIsNone(jobs.claim("w2", self.path))

    def test_the_same_gap_is_not_queued_twice(self):
        self.assertTrue(self.enqueue("g1")["ok"])
        second = self.enqueue("g1")
        self.assertFalse(second["ok"])
        self.assertIn("already queued", second["reason"])

    def test_lane_cap_comes_from_plan(self):
        for i in range(plan.MAX_SUBAGENTS):
            self.assertTrue(self.enqueue(f"g{i}")["ok"])
        refused = self.enqueue("goverflow")
        self.assertFalse(refused["ok"])
        self.assertIn("in flight", refused["reason"])

    def test_attempt_cap_is_a_total_not_a_parallel_limit(self):
        for i in range(plan.MAX_ATTEMPTS):
            self.assertTrue(self.enqueue(f"g{i}")["ok"])
            self.assertIsNotNone(jobs.claim(f"w{i}", self.path))
            jobs.finish(f"g{i}", path=self.path)
        ok, why = jobs.can_enqueue(self.path)
        self.assertFalse(ok)
        self.assertIn("attempt cap", why)

    def test_cancel_stops_only_what_has_not_started(self):
        self.enqueue("g1")
        self.enqueue("g2")
        self.assertEqual(jobs.cancel_open(path=self.path), 2)
        self.assertIsNone(jobs.claim("w1", self.path))

    def test_failure_is_recorded_and_visible(self):
        self.enqueue("g1")
        jobs.claim("w1", self.path)
        jobs.fail("g1", "boom", self.path)
        st = jobs.state(self.path)["g1"]
        self.assertEqual(st["status"], "failed")
        self.assertEqual(st["error"], "boom")

    def test_enqueue_with_cells_parents_the_job_to_a_sheet_snapshot(self):
        cs = [cells.Cell(id="d1", text="A duck crosses the street at dusk.")]
        self.enqueue("g1", cells=cs)
        snap = delta.events(kind="sheet_state")
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["payload"]["cells"][0]["id"], "d1")
        # and the worker can rebuild exactly those cells
        self.assertEqual(delta.fold_cells()["d1"]["text"], "A duck crosses the street at dusk.")

    def test_a_torn_line_does_not_break_the_fold(self):
        self.enqueue("g1")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"seq": 99, "kind": "job_op')
        self.assertEqual(jobs.state(self.path)["g1"]["status"], "open")


class WorkerTest(unittest.TestCase):
    """worker.run_one over the real chain, with both models absent.

    Qwen and Needle are not installed in CI, which is exactly the fallback path a
    fresh clone hits: the worker must still claim, still record a verdict, and
    never leave a job running forever.
    """

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.path = Path("solve") / "jobs.jsonl"

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_run_one_without_models_finishes_the_job(self):
        import worker

        sheet = [
            cells.Cell(
                id="d1",
                text=(
                    "Graph retrieval answers global questions by summarising communities of a corpus. "
                    "Citation practice requires every claim to point at a span a reader can open. "
                    "Static analysis finds imports that no module declares and reports them as defects. "
                    "Predator populations oscillate when prey populations grow over a season. "
                    "The ledger records what was withheld so a reader can ask for it back. "
                    "A gap between two clusters is worth naming only when nothing crosses it."
                ),
                role="note",
            )
        ]
        delta.append("sheet_state", {"cells": [c.to_dict() for c in sheet]})
        r = jobs.enqueue({"id": "g1", "score": 0.5, "terms_a": ["graph"], "terms_b": ["retrieval"]}, path=self.path)
        self.assertTrue(r["ok"])

        job = worker.run_one("test", self.path)
        self.assertIsNotNone(job)
        st = jobs.state(self.path)["g1"]
        self.assertEqual(st["status"], "done")
        self.assertTrue(st["log"])
        # nothing may be left running: a stuck job is the only failure that
        # blocks the queue silently
        self.assertNotEqual(st["status"], "running")

    def test_run_one_on_an_empty_queue(self):
        import worker

        self.assertIsNone(worker.run_one("test", self.path))


if __name__ == "__main__":
    unittest.main()
