"""SQLite snapshots plus append-only events. Secrets are never persisted."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .services import ROOT


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("WORKFLOW_DB", ROOT / "data" / "workflow.sqlite"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL, created TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def save(self, task, kind, body):
        task["updated"] = now()
        with self.connect() as db:
            db.execute("INSERT INTO tasks VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (task["id"], json.dumps(task)))
            db.execute("INSERT INTO events(task_id,created,kind,body) VALUES(?,?,?,?)",
                       (task["id"], now(), kind, json.dumps(body)))

    def get(self, tid):
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise KeyError(tid)
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM tasks ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def events(self, tid, after=0):
        with self.connect() as db:
            rows = db.execute("SELECT id,created,kind,body FROM events WHERE task_id=? AND id>? ORDER BY id",
                              (tid, after)).fetchall()
        return [{"id": r[0], "created": r[1], "kind": r[2], "data": json.loads(r[3])} for r in rows]

    def recover(self):
        for task in self.list():
            if task["status"] in {"planning", "running", "pause_requested"}:
                task["status"] = "paused" if task.get("plan") else "needs_help"
                task["error"] = "Server restarted. Inspect the saved step boundary, then resume or retry planning."
                for sid, state in task.get("states", {}).items():
                    if state == "running":
                        task["states"][sid] = "pending"
                self.save(task, "interrupted", {"message": task["error"]})
