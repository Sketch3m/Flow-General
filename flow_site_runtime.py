"""Private server adapter for the Marimo Flow General notebook.

SQLite owns notebook cells and interaction events. The legacy gap queue remains
a separate adapter; it is single-workspace and is NOT Shadow or a general agent.
"""
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

DB = Path(os.environ.get("FLOW_SITE_DB", "solve/flow-site.sqlite3"))


def _connect(path=None):
    path = Path(path or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.execute("CREATE TABLE IF NOT EXISTS cells (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
    return con


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _read(con):
    return [json.loads(row[0]) for row in con.execute("SELECT payload FROM cells ORDER BY seq")]


def _event(con, event):
    con.execute("INSERT INTO events(payload) VALUES (?)", (_dump(event),))


def load(starter, path=None):
    con = _connect(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            if not _read(con):
                con.executemany("INSERT INTO cells(id,payload) VALUES (?,?)",
                                [(c["id"], _dump(c)) for c in starter])
            return _read(con)
    finally:
        con.close()


def add(cell, path=None):
    con = _connect(path)
    try:
        with con:
            con.execute("INSERT OR IGNORE INTO cells(id,payload) VALUES (?,?)", (cell["id"], _dump(cell)))
            _event(con, {"kind": "cell_add", "cell_id": cell["id"]})
            return _read(con)
    finally:
        con.close()


def update(cell_id, patch, event, path=None):
    if set(patch) - {"intent", "params", "text", "title"}:
        raise ValueError("unsupported cell patch")
    con = _connect(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT payload FROM cells WHERE id=?", (cell_id,)).fetchone()
            if row is None:
                raise KeyError(cell_id)
            value = json.loads(row[0])
            value.update(patch)
            con.execute("UPDATE cells SET payload=? WHERE id=?", (_dump(value), cell_id))
            _event(con, {"cell_id": cell_id, **event})
            return _read(con)
    finally:
        con.close()


def history(path=None):
    con = _connect(path)
    try:
        return [json.loads(row[0]) for row in con.execute("SELECT payload FROM events ORDER BY seq")]
    finally:
        con.close()


def legacy_cells(workspace):
    import cells
    return cells.assign([cells.Cell(id=c["id"], text=c["text"], role="note",
                                    origin=c.get("origin", "human"))
                         for c in workspace if c.get("text")])


def meaning(workspace, focus):
    import cells
    result = cells.read(legacy_cells(workspace))
    return {"summary": result.get("summary", {}),
            "links": [x for x in result.get("links", []) if focus in (x["a"], x["b"])],
            "gaps": result.get("gaps", [])}


def queue(workspace, focus):
    import cells
    import delta
    import jobs
    # The legacy worker folds the latest global sheet rather than a pinned task.
    # Do not overwrite another app's active sheet or start competing work.
    existing = jobs.state()
    if any(j["status"] in ("open", "running") for j in existing.values()):
        return {"ok": False, "reason": "Legacy queue busy; wait for its current task."}
    owned = {j.get("cell", {}).get("id") for j in existing.values()
             if (j.get("ask") or "").startswith("flow-site:") and isinstance(j.get("cell"), dict)}
    prior = delta.fold_cells()
    if any(not k.startswith("flow-") and k not in owned for k in prior):
        return {"ok": False, "reason": "Another notebook owns the legacy log. Use a clean private solve directory."}
    sheet = legacy_cells(workspace)
    result = cells.read(sheet)
    gaps = result.get("gaps", [])
    if not gaps:
        return {"ok": False, "reason": "No unresolved graph gaps in this notebook."}
    gap = next((g for g in gaps if focus in g.get("where", {})), gaps[0])
    return jobs.enqueue(gap, cells=sheet, ask="flow-site:" + focus, actor="human")


def status():
    import jobs
    return [j for j in jobs.state().values() if (j.get("ask") or "").startswith("flow-site:")]


def adopt(job):
    result = job.get("cell")
    if not result or not result.get("text"):
        raise ValueError("No proposal to adopt")
    return {"id": "flow-job-" + str(job["id"]), "title": "Agent proposal",
            "kind": "reading", "text": result["text"], "origin": "legacy gap worker",
            "intent": "", "params": {}, "provenance": {"job": job["id"],
                "grounded": bool(job.get("grounded")), "crossed": bool(job.get("crossed")),
                "status": job.get("status")}}
