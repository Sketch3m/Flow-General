"""Durable, UI-independent notebook runtime (roadmap #2, #3).

SQLite is the canonical store for the new runtime. Each mutation and its
event commit together. Legacy JSONL and .ipynb are interchange, not live
competing stores. No external side-effect exactly-once guarantee.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cells(
 id TEXT PRIMARY KEY, notebook TEXT NOT NULL REFERENCES notebooks(id),
 parent TEXT REFERENCES cells(id), position INTEGER NOT NULL,
 kind TEXT NOT NULL, source TEXT NOT NULL, revision INTEGER NOT NULL,
 intent TEXT NOT NULL, metadata TEXT NOT NULL, outputs TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS focus(
 notebook TEXT PRIMARY KEY REFERENCES notebooks(id), cell TEXT REFERENCES cells(id),
 selection TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, cell TEXT NOT NULL REFERENCES cells(id),
 revision INTEGER NOT NULL, role TEXT NOT NULL, capability TEXT NOT NULL,
 input TEXT NOT NULL, input_hash TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
 priority INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
 max_attempts INTEGER NOT NULL, lease TEXT, deadline REAL,
 checkpoint TEXT NOT NULL, result TEXT);
CREATE TABLE IF NOT EXISTS task_deps(
 task TEXT REFERENCES tasks(id), dependency TEXT REFERENCES tasks(id),
 PRIMARY KEY(task,dependency));
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, notebook TEXT NOT NULL,
 cell TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS clarifications(
 id TEXT PRIMARY KEY, task TEXT NOT NULL REFERENCES tasks(id),
 revision INTEGER NOT NULL, question TEXT NOT NULL, alternatives TEXT NOT NULL,
 status TEXT NOT NULL, answer TEXT, UNIQUE(task,revision,question));
CREATE TABLE IF NOT EXISTS cache(
 key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS task_ready ON tasks(status,priority);
CREATE INDEX IF NOT EXISTS cell_order ON cells(notebook,parent,position);
CREATE INDEX IF NOT EXISTS event_notebook ON events(notebook,seq);
"""

def pack(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value):
    return hashlib.sha256(pack(value).encode()).hexdigest()

def uid():
    return uuid.uuid4().hex

class Stale(RuntimeError):
    """An obsolete revision or lost lease cannot publish."""

class Runtime:
    def __init__(self, path: str | Path, *, clock=time.time):
        self.path = str(path)
        self.clock = clock
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        if row is None:
            raise KeyError(args)
        return dict(row)

    def cell(self, cid):
        row = self.one("SELECT * FROM cells WHERE id=?", (cid,))
        for k in ("intent", "metadata", "outputs"):
            row[k] = json.loads(row[k])
        return row

    def task(self, tid):
        row = self.one("SELECT * FROM tasks WHERE id=?", (tid,))
        for k in ("input", "checkpoint", "result"):
            row[k] = json.loads(row[k]) if row[k] is not None else None
        return row

    def _event(self, notebook, cell, kind, payload):
        self.db.execute(
            "INSERT INTO events(notebook,cell,kind,payload,ts) VALUES(?,?,?,?,?)",
            (notebook, cell, kind, pack(payload), self.clock()))

    def events(self, notebook, after=0):
        return [{**dict(r), "payload": json.loads(r["payload"])}
                for r in self.db.execute(
                    "SELECT * FROM events WHERE notebook=? AND seq>? ORDER BY seq",
                    (notebook, after))]

    def notebook(self, name, *, id=None):
        nid = id or uid()
        with self.tx():
            self.db.execute("INSERT INTO notebooks VALUES(?,?)", (nid, name))
            self._event(nid, None, "notebook.created", {"name": name})
        return nid

    def add_cell(self, notebook, source="", *, kind="note", parent=None,
                 id=None, intent=None, metadata=None, outputs=None):
        cid = id or uid()
        with self.tx():
            self.one("SELECT id FROM notebooks WHERE id=?", (notebook,))
            if parent is not None and self.cell(parent)["notebook"] != notebook:
                raise ValueError("cross-notebook parent")
            pos = self.db.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM cells WHERE notebook=? AND parent IS ?",
                (notebook,parent)).fetchone()[0]
            self.db.execute("INSERT INTO cells VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cid, notebook, parent, pos, kind, source, 1,
                 pack(intent or {}), pack(metadata or {}), pack(outputs or [])))
            self._event(notebook, cid, "cell.created", self.cell(cid))
        return cid

    def ordered(self, notebook, parent=None):
        return [self.cell(r[0]) for r in self.db.execute(
            "SELECT id FROM cells WHERE notebook=? AND parent IS ? ORDER BY position,id",
            (notebook, parent))]

    def revise(self, cid, base, *, source=None, intent=None):
        with self.tx():
            c = self.cell(cid)
            if c["revision"] != base:
                raise Stale("cell revision changed")
            self.db.execute("UPDATE cells SET source=?,intent=?,revision=revision+1 WHERE id=?",
                (c["source"] if source is None else source,
                 pack(c["intent"] if intent is None else intent), cid))
            self.db.execute("UPDATE tasks SET status='stale',lease=NULL,deadline=NULL "
                            "WHERE cell=? AND revision=? AND status IN ('queued','running','blocked')",
                            (cid,base))
            self.db.execute("UPDATE clarifications SET status='stale' WHERE status='open' "
                            "AND task IN (SELECT id FROM tasks WHERE cell=? AND revision=?)",
                            (cid,base))
            self._event(c["notebook"],cid,"cell.revised",self.cell(cid))
        return base+1

    def set_focus(self, notebook, cid=None, *, selection=None):
        """Navigation affects attention only; no task state or authority changes."""
        with self.tx():
            if cid is not None and self.cell(cid)["notebook"] != notebook:
                raise ValueError("cross-notebook focus")
            self.db.execute("INSERT INTO focus VALUES(?,?,?) ON CONFLICT(notebook) "
                            "DO UPDATE SET cell=excluded.cell,selection=excluded.selection",
                            (notebook,cid,pack(selection or {})))
            self._event(notebook,cid,"focus.changed",{"selection":selection or {}})

    def submit(self, cid, capability, *, role="experiential", inputs=None,
               priority=0, max_attempts=3, dependencies=(), request_key=None,
               expected_revision=None, context_revisions=()):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        deps = sorted(set(dependencies))
        with self.tx():
            c = self.cell(cid)
            if expected_revision is not None and c["revision"] != expected_revision:
                raise Stale("context prepared for obsolete cell revision")
            context_revisions = list(context_revisions)
            for source_id, revision in context_revisions:
                source = self.cell(source_id)
                if source["notebook"] != c["notebook"] or source["revision"] != revision:
                    raise Stale("context source revision changed")
            for dep in deps:
                d = self.task(dep)
                if self.cell(d["cell"])["notebook"] != c["notebook"]:
                    raise ValueError("cross-notebook dependency")
            snapshot = {"cell":c,"inputs":inputs or {},"dependencies":deps,
                        "context_revisions":context_revisions}
            ih = digest(snapshot)
            key = digest([cid,role,capability,ih,request_key])
            existing = self.db.execute("SELECT id FROM tasks WHERE key=?", (key,)).fetchone()
            if existing:
                return existing[0]
            tid = uid()
            self.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid,cid,c["revision"],role,capability,pack(snapshot),ih,key,
                 priority,"queued",0,max_attempts,None,None,pack({}),None))
            self.db.executemany("INSERT INTO task_deps VALUES(?,?)", [(tid,d) for d in deps])
            self._event(c["notebook"],cid,"task.queued",{"task":tid,"input_hash":ih})
        return tid

    def claim(self, worker, *, lease_s=30, capabilities=None):
        if lease_s <= 0:
            raise ValueError("lease must be positive")
        now = self.clock()
        with self.tx():
            for row in self.db.execute("SELECT id,cell,attempts,max_attempts FROM tasks "
                                       "WHERE status='running' AND deadline<=?",(now,)).fetchall():
                status = "queued" if row["attempts"] < row["max_attempts"] else "failed"
                self.db.execute("UPDATE tasks SET status=?,lease=NULL,deadline=NULL WHERE id=?",
                                (status,row["id"]))
                self._event(self.cell(row["cell"])["notebook"],row["cell"],"task.lease_expired",
                            {"task":row["id"],"status":status})
            for row in self.db.execute("SELECT id FROM tasks WHERE status IN ('queued','running','blocked')").fetchall():
                t = self.task(row["id"])
                if not self._input_current(t):
                    self.db.execute("UPDATE tasks SET status='stale',lease=NULL,deadline=NULL WHERE id=?", (t["id"],))
                    self.db.execute("UPDATE clarifications SET status='stale' WHERE task=? AND status='open'", (t["id"],))
                    self._event(self.cell(t["cell"])["notebook"],t["cell"],"task.stale",{"task":t["id"]})
            # Dependency failure propagates without claiming unusable tasks.
            while True:
                dead = self.db.execute("""
                    SELECT DISTINCT t.id,t.cell FROM tasks t
                    JOIN task_deps d ON t.id=d.task JOIN tasks p ON p.id=d.dependency
                    WHERE t.status='queued' AND p.status IN ('failed','stale','cancelled')
                    """).fetchall()
                if not dead: break
                for row in dead:
                    self.db.execute("UPDATE tasks SET status='failed',result=? WHERE id=?",
                                    (pack({"error":"dependency failed"}),row["id"]))
                    self._event(self.cell(row["cell"])["notebook"],row["cell"],"task.dependency_failed",
                                {"task":row["id"]})
            rows = self.db.execute("""
                SELECT t.* FROM tasks t JOIN cells c ON c.id=t.cell
                WHERE t.status='queued' AND t.attempts<t.max_attempts
                AND t.revision=c.revision AND NOT EXISTS(
                 SELECT 1 FROM task_deps d JOIN tasks p ON p.id=d.dependency
                 WHERE d.task=t.id AND p.status!='done')
                ORDER BY t.priority DESC,t.rowid
                """).fetchall()
            for r in rows:
                if capabilities is not None and r["capability"] not in capabilities:
                    continue
                token = uid()
                self.db.execute("UPDATE tasks SET status='running',attempts=attempts+1,lease=?,deadline=? WHERE id=?",
                                (token,now+lease_s,r["id"]))
                self._event(self.cell(r["cell"])["notebook"],r["cell"],"task.claimed",
                            {"task":r["id"],"worker":worker,"attempt":r["attempts"]+1})
                return self.task(r["id"])
        return None

    def _input_current(self, t):
        if self.cell(t["cell"])["revision"] != t["revision"]:
            return False
        return all(self.cell(cid)["revision"] == rev
                   for cid,rev in t["input"].get("context_revisions",[]))

    def _leased(self, tid, token):
        t = self.task(tid)
        c = self.cell(t["cell"])
        if (t["status"]!="running" or not token or t["lease"]!=token
            or t["deadline"]<=self.clock() or not self._input_current(t)):
            raise Stale("expired lease or obsolete task")
        return t,c

    def heartbeat(self, tid, token, *, lease_s=30, checkpoint=None):
        if lease_s <= 0:
            raise ValueError("lease must be positive")
        with self.tx():
            t,c = self._leased(tid,token)
            self.db.execute("UPDATE tasks SET deadline=?,checkpoint=? WHERE id=?",
                            (self.clock()+lease_s,pack(t["checkpoint"] if checkpoint is None else checkpoint),tid))

    def finish(self, tid, token, result, *, status="done", checkpoint=None):
        if status not in ("done","failed","blocked"):
            raise ValueError("invalid terminal status")
        with self.tx():
            t,c = self._leased(tid,token)
            self.db.execute("UPDATE tasks SET status=?,result=?,checkpoint=?,lease=NULL,deadline=NULL WHERE id=?",
                            (status,pack(result),pack(t["checkpoint"] if checkpoint is None else checkpoint),tid))
            self._event(c["notebook"],c["id"],"task."+status,{"task":tid,"result":result})

    def cancel(self, tid):
        with self.tx():
            t = self.task(tid)
            if t["status"] not in ("queued","running","blocked"):
                return False
            self.db.execute("UPDATE tasks SET status='cancelled',lease=NULL,deadline=NULL WHERE id=?", (tid,))
            self.db.execute("UPDATE clarifications SET status='stale' WHERE task=? AND status='open'",(tid,))
            self._event(self.cell(t["cell"])["notebook"],t["cell"],"task.cancelled",{"task":tid})
            return True

    def _resume(self, t, decision):
        c = self.cell(t["cell"])
        if t["status"]!="blocked" or not self._input_current(t):
            raise Stale("task no longer blocked at this revision")
        if t["attempts"]>=t["max_attempts"]:
            raise ValueError("attempt budget exhausted")
        checkpoint = {**t["checkpoint"],"resolution":decision}
        self.db.execute("UPDATE tasks SET status='queued',checkpoint=?,result=NULL WHERE id=?",
                        (pack(checkpoint),t["id"]))
        self._event(c["notebook"],c["id"],"task.resumed",{"task":t["id"],"decision":decision})

    def recover(self, tid, decision):
        with self.tx():
            t = self.task(tid)
            self._resume(t,decision)
            self.db.execute("UPDATE clarifications SET status='stale' WHERE task=? AND status='open'",(tid,))

    def clarify(self, tid, question, alternatives):
        if len(alternatives)<2 or len({a["id"] for a in alternatives})!=len(alternatives):
            raise ValueError("distinct alternatives required")
        with self.tx():
            t = self.task(tid)
            c = self.cell(t["cell"])
            if t["status"]!="blocked" or not self._input_current(t):
                raise Stale("task no longer blocked")
            existing = self.db.execute("SELECT id,status FROM clarifications WHERE task=? AND revision=? AND question=?",
                                       (tid,t["revision"],question)).fetchone()
            if existing:
                if existing["status"]=="open": return existing["id"]
                raise Stale("clarification already resolved")
            q = uid()
            self.db.execute("INSERT INTO clarifications VALUES(?,?,?,?,?,?,?)",
                            (q,tid,t["revision"],question,pack(alternatives),"open",None))
            self._event(c["notebook"],c["id"],"clarification.queued",{"id":q,"task":tid})
            return q

    def pending(self, notebook):
        rows = self.db.execute("SELECT q.* FROM clarifications q JOIN tasks t ON q.task=t.id "
                               "JOIN cells c ON t.cell=c.id WHERE c.notebook=? AND q.status='open' ORDER BY q.rowid",
                               (notebook,))
        return [{**dict(r),"alternatives":json.loads(r["alternatives"])} for r in rows]

    def answer(self, qid, choice):
        with self.tx():
            q = self.one("SELECT * FROM clarifications WHERE id=?", (qid,))
            if q["status"]!="open":
                raise Stale("clarification no longer open")
            selected = next((a for a in json.loads(q["alternatives"]) if a["id"]==choice),None)
            if selected is None:
                raise ValueError("unknown alternative")
            t = self.task(q["task"])
            self._resume(t,{"clarification":qid,"choice":selected})
            self.db.execute("UPDATE clarifications SET status='answered',answer=? WHERE id=?",
                            (pack(selected),qid))
            self.db.execute("UPDATE clarifications SET status='stale' WHERE task=? AND status='open'",(t["id"],))

    def cache_put(self, scope, payload, *, ttl=300):
        if ttl<=0: raise ValueError("positive ttl required")
        key = digest(scope)
        with self.tx():
            self.db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",(key,pack(payload),self.clock()+ttl))
        return key

    def cache_get(self, scope):
        row = self.db.execute("SELECT payload FROM cache WHERE key=? AND expires>?",
                              (digest(scope),self.clock())).fetchone()
        return json.loads(row[0]) if row else None
