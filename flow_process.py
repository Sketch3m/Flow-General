"""Headless process layer: focus, meaning, workers, recovery, representations.

The lexical ranker is a transparent BASELINE, not Calyx. A verified meaning
adapter can replace it without changing persistence or worker contracts.
Only registered Python capabilities execute; text and retrieved sources never
become instructions or arbitrary code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable

from flow_runtime import Runtime, Stale, digest


def words(text):
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


@dataclass(frozen=True)
class Evidence:
    source: str
    revision: str
    start: int
    end: int
    text: str

    def record(self):
        return {**self.__dict__, "hash": digest(self.text), "kind": "source"}


class SourceIndex:
    """Bounded, streaming lexical baseline; exact source offsets retained."""
    def __init__(self, sources, *, max_chars=200_000):
        self.sources = sources
        self.max_chars = max_chars

    def search(self, query, *, limit=5, allowed=None):
        terms = words(query)
        matches = []
        remaining = self.max_chars
        scanned = 0
        if limit <= 0:
            return {"evidence": [], "scanned_chars": 0, "complete": False}
        complete = True
        for source, revision, chunks in self.sources():
            if allowed is not None and source not in allowed:
                continue
            offset = 0
            for chunk in chunks:
                if remaining <= 0:
                    complete = False
                    break
                part = chunk[:remaining]
                remaining -= len(part)
                scanned += len(part)
                score = len(terms & words(part))
                if score:
                    matches.append((score, Evidence(source, revision, offset,
                                                    offset+len(part), part)))
                offset += len(chunk)
                if len(part) < len(chunk):
                    complete = False
                    break
            if remaining <= 0:
                complete = False
                break
        matches.sort(key=lambda item: (-item[0],item[1].source,item[1].start))
        return {"evidence":[e.record() for _,e in matches[:limit]],
                "scanned_chars":scanned,"complete":complete}


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    run: Callable
    version: str = "1"
    roles: tuple = ("experiential", "main")
    # Capabilities are trusted application code; registration is not sandboxing.
    permission: str = "compute"


class Registry:
    def __init__(self):
        self.items = {}

    def add(self, capability):
        if capability.name in self.items:
            raise ValueError("duplicate capability")
        self.items[capability.name] = capability

    def rank(self, intent, permissions, role="experiential"):
        query = words(intent)
        return sorted(
            [{"name":c.name,"version":c.version,
              "score":len(query & words(c.description+" "+c.name))}
             for c in self.items.values()
             if c.permission in permissions and role in c.roles],
            key=lambda c:(-c["score"],c["name"]))


@dataclass
class Roadblock(Exception):
    question: str
    query: str = ""
    alternatives: list = field(default_factory=list)
    checkpoint: dict = field(default_factory=dict)
    attempted: list = field(default_factory=list)
    # Recovery requires a capability-specific validator; search overlap alone
    # must not be treated as an answer.
    missing_key: str = ""


class Process:
    def __init__(self, runtime: Runtime, registry: Registry, index: SourceIndex,
                 *, permissions=("compute",), source_version="1", meaning=None):
        self.rt = runtime
        self.registry = registry
        self.index = index
        self.permissions = frozenset(permissions)
        self.source_version = source_version
        self.meaning = meaning or registry.rank
        self.recoverers = {}

    def scope(self, cid, prompt, selection, allowed):
        c = self.rt.cell(cid)
        return {"notebook":c["notebook"],"cell":cid,"revision":c["revision"],
                "prompt":prompt,"selection":selection or {},
                "prior_revisions":[(x["id"],x["revision"]) for x in self.rt.ordered(c["notebook"],c["parent"]) if x["position"]<c["position"]],
                "permissions":sorted(self.permissions),
                "allowed":sorted(allowed) if allowed is not None else None,
                "source_version":self.source_version,
                "capabilities":sorted((c.name,c.version) for c in self.registry.items.values())}

    def context(self, cid, prompt="", *, selection=None, allowed=None):
        """Prepare context without changing the cell's authoritative intent."""
        scope = self.scope(cid,prompt,selection,allowed)
        cached = self.rt.cache_get(scope)
        if cached is not None:
            return {**cached,"cache_hit":True}
        c = self.rt.cell(cid)
        # Only preceding siblings are visible by default. Never read subsequent
        # chapters through notebook context. External sources require explicit
        # allowlist; None here means no external acquisition.
        prior = [x for x in self.rt.ordered(c["notebook"],c["parent"])
                 if x["position"]<c["position"] and not x["metadata"].get("skipped")]
        main = c["intent"].get("main","")
        query = " ".join([main,prompt,str(selection or {})])
        retrieval = self.index.search(query,allowed=set(allowed or ()))
        result = {"main":main,"subprompt":prompt,"selection":selection or {},
                  "latent":[{"id":x["id"],"revision":x["revision"],
                             "pinned":bool(x["metadata"].get("pinned")),
                             "source":x["source"][:2000]} for x in prior[-12:]],
                  "evidence":retrieval["evidence"],
                  "scanned_chars":retrieval["scanned_chars"],
                  "capabilities":self.meaning(query,self.permissions),
                  "scope_hash":digest(scope)}
        # Prior sibling revisions participate in the cache scope.
        self.rt.cache_put(scope,result)
        return {**result,"cache_hit":False}

    def focus(self, cid, *, selection=None, allowed=None):
        c = self.rt.cell(cid)
        self.rt.set_focus(c["notebook"],cid,selection=selection)
        # Synchronous headless baseline; scheduler may call this as a prefetch
        # task. This is not a claim of async prediction performance.
        return self.context(cid,selection=selection,allowed=allowed)

    def submit(self, cid, capability, *, prompt="", selection=None,
               allowed=None, role="experiential", inputs=None, **options):
        cap = self.registry.items[capability]
        if cap.permission not in self.permissions or role not in cap.roles:
            raise PermissionError(capability)
        context = self.context(cid,prompt,selection=selection,allowed=allowed)
        context.pop("cache_hit",None)
        return self.rt.submit(cid,capability,role=role,inputs={
            "context":context,"arguments":inputs or {},"version":cap.version,
            "permission":cap.permission,"allowed":sorted(allowed or ())},**options)

    def run_one(self, worker="worker"):
        capabilities = {name for name,c in self.registry.items.items()
                        if c.permission in self.permissions}
        t = self.rt.claim(worker,capabilities=capabilities)
        if t is None: return None
        data = t["input"]["inputs"]
        cap = self.registry.items[t["capability"]]
        try:
            if (data.get("version")!=cap.version or cap.permission not in self.permissions
                or data.get("permission")!=cap.permission or t["role"] not in cap.roles):
                raise PermissionError("capability changed or denied")
            result = cap.run(data["arguments"],data["context"],t["checkpoint"])
        except Roadblock as e:
            report = {"question":e.question,"query":e.query,
                      "alternatives":e.alternatives,"attempted":e.attempted,
                      "missing_key":e.missing_key}
            self.rt.finish(t["id"],t["lease"],report,status="blocked",checkpoint=e.checkpoint)
        except Exception as e:
            self.rt.finish(t["id"],t["lease"],{"error":str(e),"type":type(e).__name__},status="failed")
        else:
            self.rt.finish(t["id"],t["lease"],result)
        return self.rt.task(t["id"])

    def supervise(self, tid):
        """Resolve with a registered verifier, or queue an honest clarification."""
        t = self.rt.task(tid)
        if t["status"]!="blocked":
            raise Stale("not blocked")
        report = t["result"]
        if t["attempts"]>=t["max_attempts"]:
            return {"status":"budget_exhausted","task":tid}
        data = t["input"]["inputs"]
        evidence = self.index.search(report["query"],allowed=set(data.get("allowed",[])))["evidence"]
        recover = self.recoverers.get(t["capability"])
        decision = recover(report,evidence) if recover else None
        if decision is not None:
            self.rt.recover(tid,{"verified":decision,"evidence":evidence})
            return {"status":"recovered","task":tid}
        alternatives = report.get("alternatives") or []
        if len(alternatives)>=2:
            q = self.rt.clarify(tid,report["question"],alternatives)
            return {"status":"clarification","id":q,
                    "suggestions":alternatives,"task":tid}
        return {"status":"unresolved","task":tid,"report":report}

    def representation(self, cid):
        c = self.rt.cell(cid)
        f = self.rt.db.execute("SELECT cell FROM focus WHERE notebook=?",(c["notebook"],)).fetchone()
        focused = bool(f and f[0]==cid)
        tasks = [self.rt.task(r[0]) for r in self.rt.db.execute(
            "SELECT id FROM tasks WHERE cell=? AND revision=? ORDER BY rowid",(cid,c["revision"]))]
        artifacts = [t["result"] for t in tasks if t["status"]=="done"]
        return {"cell":cid,"revision":c["revision"],
                "mode":"interactive" if focused else "slide",
                "session":f"{cid}:{c['revision']}",
                "tasks":[{"id":t["id"],"status":t["status"]} for t in tasks],
                "artifacts":[a.get("interactive" if focused else "slide",a)
                             if isinstance(a,dict) else a for a in artifacts]}


def simulation(arguments, context, checkpoint):
    """Executable example: recurrence, not a fabricated prediction."""
    rate = arguments.get("rate")
    if rate is None:
        resolution = checkpoint.get("resolution",{})
        rate = resolution.get("verified",{}).get("rate")
        if rate is None:
            rate = resolution.get("choice",{}).get("value")
    if rate is None:
        raise Roadblock("Which growth assumption?",query="growth rate",
                        missing_key="rate",alternatives=[
                            {"id":"slow","value":0.1,"visual":{"kind":"curve","rate":0.1}},
                            {"id":"fast","value":0.3,"visual":{"kind":"curve","rate":0.3}}],
                        checkpoint={"stage":"parameter"})
    rate = float(rate)
    if not 0<=rate<=1: raise ValueError("rate outside supported range")
    points = [1.0]
    for _ in range(10): points.append(points[-1]*(1+rate))
    return {"kind":"simulated","rate":rate,"points":points,
            "interactive":{"kind":"line","points":points,
                           "controls":[{"id":"rate","min":0,"max":1,"value":rate}]},
            "slide":{"kind":"line","points":points,"summary":{"final":points[-1]}}}
