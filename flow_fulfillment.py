"""Durable cell-scoped Fulfillment subchats for Flow's SolveIt/nbdev notebook.

Unlike Shadow's ambient workers, a Fulfillment thread is an explicit conversation
rooted in a notebook cell. Children are inspectable delegated *conversations*.
This module stores intent/messages/report-backs, but NEVER claims to execute an AI
provider: a future PandaCode adapter must supply actual run receipts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

DEFAULT_DB = Path(os.environ.get("FLOW_SITE_DB", "solve/flow-site.sqlite3"))
MAX_TEXT = 12_000
MAX_DEPTH = 3
MAX_CHILDREN = 24

def _db(path=None):
    dest = Path(path or DEFAULT_DB)
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dest, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("""CREATE TABLE IF NOT EXISTS fulfillment_threads (
        id TEXT PRIMARY KEY, cell_id TEXT NOT NULL,
        parent_id TEXT REFERENCES fulfillment_threads(id),
        title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        depth INTEGER NOT NULL, created_at INTEGER NOT NULL)""")
    con.execute("""CREATE UNIQUE INDEX IF NOT EXISTS fulfillment_cell_root
        ON fulfillment_threads(cell_id) WHERE parent_id IS NULL""")
    con.execute("""CREATE INDEX IF NOT EXISTS fulfillment_thread_cell
        ON fulfillment_threads(cell_id, created_at)""")
    con.execute("""CREATE TABLE IF NOT EXISTS fulfillment_messages (
        id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES fulfillment_threads(id),
        role TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
        created_at INTEGER NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS fulfillment_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL)""")
    return con

def _text(s, field="text", max_length=MAX_TEXT):
    if not isinstance(s, str):
        raise TypeError(field + " must be a string")
    val = s.strip()
    if not val or len(val) > max_length:
        raise ValueError(field + " must contain 1–" + str(max_length) + " characters")
    return val

def _event(con, thread, kind, **detail):
    con.execute("INSERT INTO fulfillment_events(thread_id,kind,payload) VALUES(?,?,?)",
                (thread, kind, json.dumps(detail, ensure_ascii=False)))

def _message(con, thread, role, body, source):
    con.execute("""INSERT INTO fulfillment_messages(id,thread_id,role,text,source,created_at)
        VALUES(?,?,?,?,?,?)""", ("msg-" + uuid4().hex, thread, role, body, source, time.time_ns()))

def ensure_root(cell_id, intent, path=None):
    """Create one main Fulfillment conversation per cell, idempotently."""
    cell = _text(cell_id, "cell id", 160)
    brief = _text(intent, "intent")
    con = _db(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("""SELECT id FROM fulfillment_threads
                WHERE cell_id=? AND parent_id IS NULL""", (cell,)).fetchone()
            if existing:
                return existing["id"]
            identifier = "ful-" + uuid4().hex
            con.execute("""INSERT INTO fulfillment_threads
                (id,cell_id,parent_id,title,status,depth,created_at)
                VALUES (?,?,NULL,?,'open',0,?)""",
                (identifier, cell, "Fulfillment", time.time_ns()))
            _message(con, identifier, "user", brief, "cell_intent")
            _event(con, identifier, "opened", source="cell_intent", engine="unconnected")
            return identifier
    finally:
        con.close()

def open_child(parent_id, title, brief, path=None):
    """Open a true child chat without launching an executor or copying whole history."""
    parent_id = _text(parent_id, "parent", 160)
    name = _text(title, "title", 100)
    instruction = _text(brief, "brief")
    con = _db(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            parent = con.execute("SELECT * FROM fulfillment_threads WHERE id=?", (parent_id,)).fetchone()
            if not parent:
                raise KeyError(parent_id)
            if parent["status"] != "open":
                raise ValueError("parent is no longer open")
            if parent["depth"] >= MAX_DEPTH:
                raise ValueError("maximum nesting depth reached")
            count = con.execute("SELECT COUNT(*) FROM fulfillment_threads WHERE parent_id=?",
                                (parent_id,)).fetchone()[0]
            if count >= MAX_CHILDREN:
                raise ValueError("maximum subchats reached")
            identifier = "ful-" + uuid4().hex
            con.execute("""INSERT INTO fulfillment_threads
                (id,cell_id,parent_id,title,status,depth,created_at)
                VALUES (?,?,?,?,'open',?,?)""",
                (identifier, parent["cell_id"], parent_id, name, parent["depth"] + 1, time.time_ns()))
            _message(con, identifier, "user", instruction, "delegated_brief")
            _event(con, identifier, "opened", parent_id=parent_id, engine="unconnected")
            return identifier
    finally:
        con.close()

def post_user_message(thread_id, message, path=None):
    """Write a local user message; this is *not* a fabricated model completion."""
    identifier = _text(thread_id, "thread id", 160)
    body = _text(message)
    con = _db(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            thread = con.execute("SELECT status FROM fulfillment_threads WHERE id=?", (identifier,)).fetchone()
            if thread is None:
                raise KeyError(identifier)
            if thread["status"] != "open":
                raise ValueError("thread is closed")
            _message(con, identifier, "user", body, "human")
            _event(con, identifier, "message_added", source="human")
            return {"ok": True, "dispatch": "not_connected",
                    "reason": "Saved locally; no PandaCode or LLM provider is configured."}
    finally:
        con.close()

def finish_child(thread_id, report, path=None):
    """Explicit manual report back, labeled as such and written atomically."""
    identifier = _text(thread_id, "thread id", 160)
    body = _text(report, "report")
    con = _db(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            child = con.execute("SELECT * FROM fulfillment_threads WHERE id=?", (identifier,)).fetchone()
            if not child:
                raise KeyError(identifier)
            if not child["parent_id"]:
                raise ValueError("root thread cannot report to a parent")
            if child["status"] != "open":
                raise ValueError("child thread already closed")
            parent = con.execute("SELECT status FROM fulfillment_threads WHERE id=?",
                                 (child["parent_id"],)).fetchone()
            if parent is None or parent["status"] != "open":
                raise ValueError("parent thread unavailable")
            _message(con, identifier, "report", body, "manual_report")
            _message(con, child["parent_id"], "report",
                     "[" + child["title"] + " — manually reported] " + body,
                     "manual_child_report")
            con.execute("UPDATE fulfillment_threads SET status='completed' WHERE id=?", (identifier,))
            _event(con, identifier, "completed", source="manual_report", parent=child["parent_id"])
            _event(con, child["parent_id"], "child_reported", child=identifier, source="manual_report")
            return child["parent_id"]
    finally:
        con.close()

def cancel_thread(thread_id, path=None):
    """Cancel a thread and all descendants without claiming to stop a remote process."""
    identifier = _text(thread_id, "thread id", 160)
    con = _db(path)
    try:
        with con:
            con.execute("BEGIN IMMEDIATE")
            exists = con.execute("SELECT id FROM fulfillment_threads WHERE id=?", (identifier,)).fetchone()
            if not exists:
                raise KeyError(identifier)
            # Recursive CTE bounds descendant traversal by the stored parent tree.
            rows = con.execute("""WITH RECURSIVE descendants(id) AS (
                SELECT id FROM fulfillment_threads WHERE id=?
                UNION ALL
                SELECT t.id FROM fulfillment_threads t JOIN descendants d ON t.parent_id=d.id
            ) SELECT id FROM descendants""", (identifier,)).fetchall()
            for row in rows:
                con.execute("UPDATE fulfillment_threads SET status='cancelled' WHERE id=? AND status='open'",
                            (row["id"],))
                _event(con, row["id"], "cancelled", source="human")
            return len(rows)
    finally:
        con.close()

def tree(cell_id, path=None):
    """Full inspectable conversation tree; the notebook owns its associated cell."""
    identifier = _text(cell_id, "cell id", 160)
    con = _db(path)
    try:
        threads = con.execute("""SELECT id,cell_id,parent_id,title,status,depth
            FROM fulfillment_threads WHERE cell_id=? ORDER BY created_at,id""", (identifier,)).fetchall()
        out = []
        for row in threads:
            record = dict(row)
            record["messages"] = [dict(m) for m in con.execute(
                """SELECT role,text,source,created_at FROM fulfillment_messages
                   WHERE thread_id=? ORDER BY created_at,id""", (row["id"],))]
            out.append(record)
        return out
    finally:
        con.close()

def events(thread_id, path=None):
    con = _db(path)
    try:
        return [dict(e) for e in con.execute(
            "SELECT kind,payload FROM fulfillment_events WHERE thread_id=? ORDER BY seq",
            (_text(thread_id, "thread id", 160),))]
    finally:
        con.close()
