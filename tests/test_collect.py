"""Behavior tests for the read-only collector.

The fixtures build a small SQLite database with the same shape as the parts of
``session_v2`` that the collector reads. Assertions use values chosen in the
fixture, never values recomputed by the collector.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import collect  # noqa: E402

MIN = 60_000
T0 = int(datetime(2026, 1, 1, 23, 50, tzinfo=timezone.utc).timestamp() * 1000)


def make_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT);
            CREATE TABLE session_v2 (
                id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, directory TEXT,
                title TEXT, time_created INTEGER, time_updated INTEGER,
                time_busy INTEGER, time_idle INTEGER, idle_outcome TEXT,
                tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER,
                tokens_cache_read INTEGER, tokens_cache_write INTEGER, cost REAL
            );
            CREATE TABLE session_message (
                id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INTEGER,
                time_created INTEGER, data TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO project VALUES (?, ?, ?)", ("p1", "/work/eunomia", "EunomiaSync")
        )
        connection.execute(
            "INSERT INTO project VALUES (?, ?, ?)", ("p2", "/work/other", "Other")
        )
        connection.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "main-1", "p1", None, "/work/eunomia", "Main session",
                T0, T0 + 40 * MIN, T0 + 25 * MIN, T0 + 35 * MIN, "succeeded",
                100, 20, 5, 1000, 10, 0.25,
            ),
        )
        connection.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "child-1", "p1", "main-1", "/work/eunomia/.worktrees/t-1", "Child session",
                T0 + 50 * MIN, T0 + 55 * MIN, None, None, None,
                0, 0, 0, 0, 0, 0,
            ),
        )
        connection.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "foreign-1", "p2", None, "/work/other", "Other session",
                T0, T0 + 60 * MIN, None, None, None,
                0, 0, 0, 0, 0, 0,
            ),
        )
        for seq, (kind, ms, data) in enumerate(
            [
                ("user", T0, "{}"),
                ("assistant", T0 + 5 * MIN, "{}"),
                ("idle", T0 + 15 * MIN, json.dumps({"time": {"created": T0 + 15 * MIN}})),
                ("assistant", T0 + 25 * MIN, "{}"),
                ("idle", T0 + 35 * MIN, json.dumps({"time": {"created": T0 + 35 * MIN}})),
            ],
            start=1,
        ):
            connection.execute(
                "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?)",
                (f"m{seq}", "main-1", kind, seq, ms, data),
            )
        connection.commit()
    finally:
        connection.close()


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).resolve().parents[0] / "_tmp"
        self.tmp.mkdir(exist_ok=True)
        self.db = self.tmp / "fixture.db"
        self.out = self.tmp / "snapshot.json"
        make_db(self.db)

    def tearDown(self) -> None:
        for path in (self.db, self.out):
            path.unlink(missing_ok=True)

    def run_collect(self, *extra: str) -> dict:
        code = collect.main(
            ["--db", str(self.db), "--project", "EunomiaSync", "--out", str(self.out), *extra]
        )
        self.assertEqual(code, 0)
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_main_session_totals(self) -> None:
        snapshot = self.run_collect()
        totals = snapshot["totals"]
        self.assertEqual(totals["sessions"], 1)
        self.assertEqual(totals["subagents"], 0)
        self.assertEqual(totals["wall_ms"], 40 * MIN)
        self.assertEqual(totals["exec_ms"], 20 * MIN)
        self.assertEqual(totals["busy_ms"], 10 * MIN)
        self.assertEqual(totals["steps"], 2)
        self.assertEqual(totals["prompts"], 1)
        self.assertEqual(totals["cost"], 0.25)
        self.assertEqual([item["id"] for item in snapshot["sessions"]], ["main-1"])

    def test_windows_split_at_midnight(self) -> None:
        days = {item["date"]: item for item in self.run_collect()["days"]}
        self.assertEqual(set(days), {"2026-01-01", "2026-01-02"})
        self.assertEqual(days["2026-01-01"]["wall_ms"], 10 * MIN)
        self.assertEqual(days["2026-01-02"]["wall_ms"], 30 * MIN)
        self.assertEqual(days["2026-01-01"]["exec_ms"], 5 * MIN)
        self.assertEqual(days["2026-01-02"]["exec_ms"], 15 * MIN)

    def test_subagents_are_opt_in(self) -> None:
        included = self.run_collect("--include-subagents")
        self.assertEqual(included["totals"]["sessions"], 1)
        self.assertEqual(included["totals"]["subagents"], 1)
        self.assertEqual(included["totals"]["wall_ms"], 45 * MIN)
        self.assertEqual(len(included["sessions"]), 2)

    def test_directory_scope_includes_worktrees(self) -> None:
        code = collect.main(
            ["--db", str(self.db), "--dir", "/work/eunomia", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        snapshot = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["totals"]["wall_ms"], 40 * MIN)

    def test_unknown_project_returns_empty_snapshot(self) -> None:
        code = collect.main(
            ["--db", str(self.db), "--project", "does-not-exist", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        snapshot = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["totals"]["wall_ms"], 0)

    def test_time_filter_excludes_session(self) -> None:
        snapshot = self.run_collect("--since", "2026-02-01T00:00:00Z")
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["totals"]["wall_ms"], 0)


class ReadOnlyTests(unittest.TestCase):
    def test_connection_rejects_writes(self) -> None:
        db = Path(__file__).resolve().parents[0] / "_tmp" / "readonly.db"
        db.parent.mkdir(exist_ok=True)
        db.unlink(missing_ok=True)
        make_db(db)
        connection = collect.connect_readonly(db)
        try:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE should_not_exist (id TEXT)")
        finally:
            connection.close()
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
