from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


TERMINAL_STATES = {
    "merged",
    "blocked",
    "no_change_needed",
    "failed",
    "failed_verification",
    "timed_out",
}

TASK_COLUMNS = {
    "state",
    "session_id",
    "session_url",
    "playbook_id",
    "knowledge_id",
    "pr_url",
    "pr_state",
    "verification_passed",
    "checks_passed",
    "checks_conclusion",
    "checks_confirmed_at",
    "checks_failed_sha",
    "checks_failed_at",
    "devin_mode",
    "acus",
    "attempts",
    "verdict",
    "failure_reason",
    "dispatched_at",
    "pr_opened_at",
    "merged_at",
    "completed_at",
    "updated_at",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id                    TEXT PRIMARY KEY,
    repo                  TEXT NOT NULL,
    issue_number          INTEGER NOT NULL,
    issue_url             TEXT NOT NULL,
    issue_title           TEXT NOT NULL,
    issue_body            TEXT NOT NULL,
    issue_class           TEXT NOT NULL,
    severity              TEXT NOT NULL,
    source                TEXT NOT NULL,
    delivery_id           TEXT,
    state                 TEXT NOT NULL,
    session_id            TEXT,
    session_url           TEXT,
    playbook_id           TEXT,
    knowledge_id          TEXT,
    pr_url                TEXT,
    pr_state              TEXT,
    verification_passed   INTEGER NOT NULL DEFAULT 0,  -- Devin's own claim
    checks_passed         INTEGER NOT NULL DEFAULT 0,  -- confirmed by repository CI
    checks_conclusion     TEXT,
    checks_confirmed_at   REAL,
    checks_failed_sha     TEXT,
    checks_failed_at      REAL,
    devin_mode            TEXT,
    acus                  REAL NOT NULL DEFAULT 0,
    attempts              INTEGER NOT NULL DEFAULT 0,
    verdict               TEXT,
    failure_reason        TEXT,
    created_at            REAL NOT NULL,
    dispatched_at         REAL,
    pr_opened_at          REAL,
    merged_at             REAL,
    completed_at          REAL,
    updated_at            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    kind        TEXT NOT NULL,
    detail      TEXT,
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns introduced after a database was first created.

        CREATE TABLE IF NOT EXISTS silently does nothing on an existing table, so
        without this an upgraded container fails on every query against a volume
        that predates the CI gate.
        """
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        for column, ddl in (
            ("checks_passed", "INTEGER NOT NULL DEFAULT 0"),
            ("checks_conclusion", "TEXT"),
            ("checks_confirmed_at", "REAL"),
            ("checks_failed_sha", "TEXT"),
            ("checks_failed_at", "REAL"),
            ("devin_mode", "TEXT"),
        ):
            if column not in existing:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def claim_task(self, task: dict[str, Any]) -> bool:
        now = time.time()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO tasks (
                    id, repo, issue_number, issue_url, issue_title, issue_body,
                    issue_class, severity, source, delivery_id, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (
                    task["id"],
                    task["repo"],
                    task["issue_number"],
                    task["issue_url"],
                    task["issue_title"],
                    task["issue_body"],
                    task["issue_class"],
                    task["severity"],
                    task["source"],
                    task.get("delivery_id"),
                    now,
                    now,
                ),
            )
            claimed = cursor.rowcount == 1
        self.log(task["id"], "queued" if claimed else "duplicate_suppressed", task.get("delivery_id"))
        return claimed

    def begin_dispatch(self, task_id: str) -> bool:
        now = time.time()
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE tasks
                   SET state = 'dispatching', attempts = attempts + 1, updated_at = ?
                   WHERE id = ? AND state = 'queued'""",
                (now, task_id),
            )
        if cursor.rowcount == 1:
            self.log(task_id, "state:dispatching")
            return True
        return False

    def update(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - TASK_COLUMNS
        if unknown:
            raise ValueError(f"unknown task fields: {sorted(unknown)}")
        now = time.time()
        fields["updated_at"] = now
        if fields.get("state") in TERMINAL_STATES:
            fields.setdefault("completed_at", now)
        columns = ", ".join(f"{name} = ?" for name in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE tasks SET {columns} WHERE id = ?",
                (*fields.values(), task_id),
            )
        if "state" in fields:
            self.log(task_id, f"state:{fields['state']}", fields.get("failure_reason"))

    def log(self, task_id: str | None, kind: str, detail: Any = None) -> None:
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, sort_keys=True)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events(task_id, kind, detail, ts) VALUES (?, ?, ?, ?)",
                (task_id, kind, (detail or "")[:3000], time.time()),
            )

    def has_event(self, task_id: str, kind: str) -> bool:
        """Used to notify once. A session parked awaiting approval is polled
        every few seconds; the operator should hear about it exactly once."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM events WHERE task_id = ? AND kind = ? LIMIT 1",
                (task_id, kind),
            ).fetchone()
        return row is not None

    def task_ids_with_event(self, kind: str) -> set[str]:
        """Every task that has ever logged an event of this kind."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT task_id FROM events WHERE kind = ? AND task_id IS NOT NULL",
                (kind,),
            ).fetchall()
        return {row[0] for row in rows}

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def by_state(self, *states: str) -> list[dict[str, Any]]:
        if not states:
            return []
        placeholders = ",".join("?" for _ in states)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY created_at",
                states,
            ).fetchall()
        return [dict(row) for row in rows]

    def all_tasks(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def active_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM tasks
                   WHERE state IN ('dispatching', 'dispatched', 'running')"""
            ).fetchone()
        return int(row[0])

    def sessions_dispatched_since(self, since: float) -> int:
        """Sessions started in a window.

        The ACU budget cannot be enforced on a plan that reports no consumption
        — `acus_dispatched_since` returns zero forever and the throttle never
        fires. Counting sessions is crude but it always works, and a spend cap
        that silently does nothing is worse than a blunt one that does.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM tasks
                   WHERE dispatched_at IS NOT NULL AND dispatched_at >= ?""",
                (since,),
            ).fetchone()
        return int(row[0])

    def acus_dispatched_since(self, since: float) -> float:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(acus), 0) FROM tasks
                   WHERE dispatched_at IS NOT NULL AND dispatched_at >= ?""",
                (since,),
            ).fetchone()
        return float(row[0])
