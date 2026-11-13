import json
import tempfile
import unittest
from pathlib import Path

from flow_runtime import Runtime, Stale
from flow_process import Capability, Registry, SourceIndex, Process, simulation
from flow_interchange import import_ipynb, export_ipynb


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"runtime.db"
        self.now=100
        self.rt=Runtime(self.path,clock=lambda:self.now)
        self.n=self.rt.notebook("book")
        self.a=self.rt.add_cell(self.n,"Growth recurrence",intent={"main":"explore growth rate"})
        self.b=self.rt.add_cell(self.n,"Experiment")
        self.reg=Registry()
        self.reg.add(Capability("growth","simulate growth rate",simulation))
        self.index=SourceIndex(lambda:iter([
            ("chapter1","sha1",iter(["The growth rate is 0.2."])),
            ("chapter2","sha2",iter(["Spoiler: final theorem."]))]))
        self.p=Process(self.rt,self.reg,self.index)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def test_navigation_does_not_cancel_and_recovery(self):
        self.p.focus(self.a,allowed={"chapter1"})
        tid=self.p.submit(self.a,"growth",allowed={"chapter1"})
        self.p.focus(self.b)
        self.assertEqual(self.rt.task(tid)["status"],"queued")
        self.assertEqual(self.p.run_one()["status"],"blocked")
        self.p.recoverers["growth"]=lambda report,evidence: (
            {"rate":0.2} if any(e["text"]=="The growth rate is 0.2." for e in evidence) else None)
        self.assertEqual(self.p.supervise(tid)["status"],"recovered")
        self.assertEqual(self.p.run_one()["status"],"done")
        slide=self.p.representation(self.a)
        self.assertEqual(slide["mode"],"slide")
        self.p.focus(self.a)
        interactive=self.p.representation(self.a)
        self.assertEqual(interactive["session"],slide["session"])
        self.assertEqual(interactive["mode"],"interactive")
        self.assertAlmostEqual(interactive["artifacts"][0]["points"][-1],1.2**10)

    def test_clarification_does_not_stop_other_cell(self):
        tid=self.p.submit(self.a,"growth")
        self.p.run_one()
        q=self.p.supervise(tid)
        self.assertEqual(q["status"],"clarification")
        self.assertEqual(self.p.supervise(tid)["id"],q["id"])
        other=self.p.submit(self.b,"growth",inputs={"rate":0.4})
        self.assertEqual(self.p.run_one()["id"],other)
        self.rt.answer(q["id"],"fast")
        self.assertEqual(self.p.run_one()["id"],tid)
        self.assertAlmostEqual(self.rt.task(tid)["result"]["rate"],0.3)
        self.assertFalse(self.rt.pending(self.n))
        with self.assertRaises(Stale): self.rt.answer(q["id"],"slow")

    def test_crash_expired_lease_and_revision(self):
        tid=self.rt.submit(self.a,"manual",max_attempts=2)
        t=self.rt.claim("first",lease_s=5)
        self.rt.heartbeat(tid,t["lease"],lease_s=5,checkpoint={"step":3})
        self.rt.close()
        self.rt=Runtime(self.path,clock=lambda:self.now)
        self.now=106
        second=self.rt.claim("second")
        self.assertEqual(second["id"],tid)
        self.assertEqual(second["checkpoint"],{"step":3})
        with self.assertRaises(Stale):
            self.rt.finish(tid,t["lease"],{"wrong":True})
        self.rt.revise(self.a,1,source="changed")
        with self.assertRaises(Stale):
            self.rt.finish(tid,second["lease"],{})
        self.assertEqual(self.rt.task(tid)["status"],"stale")

    def test_two_connections_dedup_and_dependency(self):
        x=self.rt.submit(self.a,"x")
        self.assertEqual(x,self.rt.submit(self.a,"x"))
        y=self.rt.submit(self.b,"y",dependencies=[x])
        other=Runtime(self.path,clock=lambda:self.now)
        try:
            t=self.rt.claim("first")
            self.assertEqual(t["id"],x)
            self.assertIsNone(other.claim("second"))
            self.rt.finish(x,t["lease"],{})
            u=other.claim("second")
            self.assertEqual(u["id"],y)
            other.finish(y,u["lease"],{})
        finally:
            other.close()

    def test_context_cache_scope_and_spoiler(self):
        self.rt.add_cell(self.n,"Later spoiler")
        first=self.p.context(self.b,"growth",allowed={"chapter1"})
        second=self.p.context(self.b,"growth",allowed={"chapter1"})
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertNotIn("Spoiler",json.dumps(first))
        self.assertEqual([r["id"] for r in first["latent"]],[self.a])
        self.rt.revise(self.a,1,source="New premise")
        third=self.p.context(self.b,"growth",allowed={"chapter1"})
        self.assertFalse(third["cache_hit"])
        self.assertEqual(third["latent"][0]["source"],"New premise")
        self.assertFalse(self.p.context(self.b,"growth")["evidence"])

    def test_stale_clarification(self):
        t=self.p.submit(self.a,"growth")
        self.p.run_one()
        q=self.p.supervise(t)["id"]
        self.rt.revise(self.a,1,source="different")
        with self.assertRaises(Stale): self.rt.answer(q,"fast")

    def test_ipynb_roundtrip(self):
        nested=self.rt.add_cell(self.n,"print(1)",kind="code",parent=self.a,
                                metadata={"pinned":True},outputs=[])
        p=Path(self.tmp.name)/"notebook.ipynb"
        export_ipynb(self.rt,self.n,p)
        n2=import_ipynb(self.rt,p)
        root=self.rt.ordered(n2)
        self.assertEqual([r["source"] for r in root],["Growth recurrence","Experiment"])
        child=self.rt.ordered(n2,root[0]["id"])[0]
        self.assertEqual(child["source"],"print(1)")
        self.assertTrue(child["metadata"]["pinned"])


if __name__=="__main__":
    unittest.main()
