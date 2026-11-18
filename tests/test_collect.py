"""Behavior tests for the read-only collector.

The fixtures build a small SQLite database with the same shape as the parts of
``session_v2`` that the collector reads. Assertions use values chosen in the
fixture, never values recomputed by the collector.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

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
                30, 4, 1, 200, 0, 0,
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
        # m2 (T0+5min, 2026-01-01) carries two tool parts and token usage;
        # m4 (T0+25min, 2026-01-02) carries one tool part and token usage.
        # main-1's session totals equal the message sums, so its residual is
        # zero; child-1 records tokens without any messages, so its whole
        # total is the residual attributed to its creation day.
        for seq, (kind, ms, data) in enumerate(
            [
                ("user", T0, "{}"),
                (
                    "assistant",
                    T0 + 5 * MIN,
                    json.dumps({
                        "content": [{"type": "text"}, {"type": "tool"}, {"type": "tool"}],
                        "tokens": {"input": 60, "output": 12, "reasoning": 3,
                                   "cache": {"read": 600, "write": 6}},
                    }),
                ),
                ("idle", T0 + 15 * MIN, json.dumps({"time": {"created": T0 + 15 * MIN}})),
                (
                    "assistant",
                    T0 + 25 * MIN,
                    json.dumps({
                        "content": [{"type": "tool"}],
                        "tokens": {"input": 40, "output": 8, "reasoning": 2,
                                   "cache": {"read": 400, "write": 4}},
                    }),
                ),
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


def add_project(path: Path, project_id: str, worktree: str, name: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO project VALUES (?, ?, ?)", (project_id, worktree, name)
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

    def test_child_sessions_included_by_default(self) -> None:
        snapshot = self.run_collect()
        totals = snapshot["totals"]
        self.assertEqual(totals["sessions"], 1)
        self.assertEqual(totals["subagents"], 1)
        self.assertEqual(totals["exec_ms"], 20 * MIN)
        self.assertEqual(totals["busy_ms"], 10 * MIN)
        self.assertEqual(totals["steps"], 2)
        self.assertEqual(totals["prompts"], 1)
        self.assertEqual(totals["cost"], 0.25)
        self.assertEqual(
            sorted(item["id"] for item in snapshot["sessions"]), ["child-1", "main-1"]
        )
        self.assertFalse(snapshot["main_only"])

    def test_execution_windows_split_at_midnight(self) -> None:
        days = {item["date"]: item for item in self.run_collect()["days"]}
        self.assertEqual(set(days), {"2026-01-01", "2026-01-02"})
        self.assertEqual(days["2026-01-01"]["exec_ms"], 5 * MIN)
        self.assertEqual(days["2026-01-02"]["exec_ms"], 15 * MIN)

    def test_day_rows_attribute_prompts_steps_and_tools_by_message_day(self) -> None:
        days = {item["date"]: item for item in self.run_collect()["days"]}
        # The user prompt and the first assistant step (two tool calls) belong
        # to 2026-01-01; the second assistant step (one tool call) lands at
        # 00:15 UTC on 2026-01-02, not on the session's creation day.
        self.assertEqual(days["2026-01-01"]["prompts"], 1)
        self.assertEqual(days["2026-01-01"]["steps"], 1)
        self.assertEqual(days["2026-01-01"]["tool_calls"], 2)
        self.assertEqual(days["2026-01-02"]["prompts"], 0)
        self.assertEqual(days["2026-01-02"]["steps"], 1)
        self.assertEqual(days["2026-01-02"]["tool_calls"], 1)

    def test_day_tokens_use_message_data_with_residual_on_creation_day(self) -> None:
        days = {item["date"]: item for item in self.run_collect()["days"]}
        self.assertEqual(days["2026-01-01"]["tokens_input"], 60)
        self.assertEqual(days["2026-01-01"]["tokens_output"], 12)
        self.assertEqual(days["2026-01-01"]["tokens_reasoning"], 3)
        self.assertEqual(days["2026-01-01"]["tokens_cache_read"], 600)
        # child-1 records tokens in session_v2 but has no messages, so its
        # whole total is a residual attributed to its creation day.
        self.assertEqual(days["2026-01-02"]["tokens_input"], 40 + 30)
        self.assertEqual(days["2026-01-02"]["tokens_output"], 8 + 4)
        self.assertEqual(days["2026-01-02"]["tokens_reasoning"], 2 + 1)
        self.assertEqual(days["2026-01-02"]["tokens_cache_read"], 400 + 200)

    def test_day_rows_sum_to_report_totals(self) -> None:
        snapshot = self.run_collect()
        for key in (
            "exec_ms", "prompts", "steps", "tool_calls",
            "tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read",
        ):
            self.assertEqual(
                sum(day[key] for day in snapshot["days"]), snapshot["totals"][key], key
            )

    def test_day_sessions_count_sessions_with_activity(self) -> None:
        days = {item["date"]: item for item in self.run_collect()["days"]}
        self.assertEqual(days["2026-01-01"]["sessions"], 1)
        # main-1 still executes and writes messages after midnight, and
        # child-1 is created that day with token usage: two active sessions.
        self.assertEqual(days["2026-01-02"]["sessions"], 2)

    def test_null_numeric_columns_do_not_crash(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "UPDATE session_v2 SET tokens_input = NULL, tokens_output = NULL, "
                "tokens_reasoning = NULL, tokens_cache_read = NULL, "
                "tokens_cache_write = NULL, cost = NULL WHERE id = 'main-1'"
            )
            connection.commit()
        finally:
            connection.close()
        snapshot = self.run_collect()
        main = next(item for item in snapshot["sessions"] if item["id"] == "main-1")
        self.assertEqual(main["tokens_input"], 0)
        self.assertEqual(main["cost"], 0.0)

    def test_inactive_session_creates_no_day_row(self) -> None:
        silent = int(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "silent-1", "p1", None, "/work/eunomia", "Silent session",
                    silent, silent + MIN, None, None, None,
                    0, 0, 0, 0, 0, 0,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        days = {item["date"]: item for item in self.run_collect()["days"]}
        self.assertNotIn("2026-01-05", days)


    def test_main_only_excludes_child_sessions(self) -> None:
        main_only = self.run_collect("--main-only")
        self.assertEqual(main_only["totals"]["sessions"], 1)
        self.assertEqual(main_only["totals"]["subagents"], 0)
        self.assertEqual([item["id"] for item in main_only["sessions"]], ["main-1"])
        self.assertTrue(main_only["main_only"])

    def test_current_project_detected_from_worktree_directory(self) -> None:
        connection = collect.connect_readonly(self.db)
        try:
            found = collect.detect_current_project(
                connection, Path("/work/eunomia/.worktrees/t-1")
            )
        finally:
            connection.close()
        self.assertEqual(found, ({"p1"}, "/work/eunomia"))

    def test_exact_worktree_wins_over_basename_matches(self) -> None:
        add_project(self.db, "p3", "/other/eunomia", "Other Eunomia")
        connection = collect.connect_readonly(self.db)
        try:
            found = collect.detect_current_project(connection, Path("/work/eunomia"))
        finally:
            connection.close()
        self.assertEqual(found, ({"p1"}, "/work/eunomia"))

    def test_explicit_dir_ignores_duplicate_basenames(self) -> None:
        add_project(self.db, "p3", "/other/eunomia", "Other Eunomia")
        code = collect.main(
            ["--db", str(self.db), "--dir", "/work/eunomia", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        snapshot = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(item["id"] for item in snapshot["sessions"]), ["child-1", "main-1"]
        )

    def test_ignored_global_worktree_does_not_cause_ambiguity(self) -> None:
        add_project(self.db, "global", "/", "Global")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "global-1", "global", None, "/work/scratch", "Global session",
                    T0, T0 + MIN, None, None, None, 0, 0, 0, 0, 0, 0,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        connection = collect.connect_readonly(self.db)
        try:
            found = collect.detect_current_project(connection, Path("/work/scratch"))
        finally:
            connection.close()
        self.assertIsNone(found)

    def test_ambiguous_project_name_is_rejected(self) -> None:
        add_project(self.db, "p3", "/other/eunomia", "Other Eunomia")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = collect.main(
                ["--db", str(self.db), "--project", "eunomia", "--out", str(self.out)]
            )
        self.assertEqual(code, 2)
        self.assertIn("ambiguous project name", stderr.getvalue())

    def test_missing_current_project_reports_error(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(collect.Path, "cwd", return_value=Path("/nowhere/project")), redirect_stderr(stderr):
            code = collect.main(["--db", str(self.db), "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertIn("--project", stderr.getvalue())
        self.assertIn("tell the owner", stderr.getvalue())

    def test_directory_scope_includes_worktrees(self) -> None:
        code = collect.main(
            ["--db", str(self.db), "--dir", "/work/eunomia", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        snapshot = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(item["id"] for item in snapshot["sessions"]), ["child-1", "main-1"]
        )

    def test_unknown_project_returns_empty_snapshot(self) -> None:
        code = collect.main(
            ["--db", str(self.db), "--project", "does-not-exist", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        snapshot = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["totals"]["exec_ms"], 0)

    def test_snapshot_keeps_original_project_name(self) -> None:
        snapshot = self.run_collect("--project", "EunomiaSync")
        self.assertEqual(snapshot["project"]["display_name"], "EunomiaSync")
        self.assertEqual(snapshot["project"]["names"], ["eunomiasync"])

    def test_time_filter_excludes_session(self) -> None:
        snapshot = self.run_collect("--since", "2026-02-01T00:00:00Z")
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["totals"]["exec_ms"], 0)

    def test_since_clips_execution_intervals(self) -> None:
        since = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
        snapshot = self.run_collect("--since", datetime.fromtimestamp(since / 1000, timezone.utc).isoformat())
        main = next(item for item in snapshot["sessions"] if item["id"] == "main-1")
        self.assertLess(main["exec_ms"], 40 * MIN)
        for day in snapshot["days"]:
            if day["date"] < "2026-01-02":
                self.assertEqual(day["exec_ms"], 0)

    def test_out_cannot_overwrite_database(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = collect.main(
                ["--db", str(self.db), "--project", "Nope", "--out", str(self.db)]
            )
        self.assertEqual(code, 2)
        self.assertIn("refusing", stderr.getvalue())
        self.assertTrue(self.db.read_bytes().startswith(b"SQLite format 3"))

    def test_out_cannot_overwrite_database_sidecars(self) -> None:
        for suffix in ("-wal", "-shm"):
            target = Path(f"{self.db}{suffix}")
            target.write_bytes(b"keep")
            with redirect_stderr(io.StringIO()):
                code = collect.main(["--db", str(self.db), "--out", str(target)])
            self.assertEqual(code, 2)
            self.assertEqual(target.read_bytes(), b"keep")


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

    def test_open_failure_is_reported_clearly(self) -> None:
        db = Path(__file__).resolve().parents[0] / "_tmp" / "unopenable.db"
        db.parent.mkdir(exist_ok=True)
        db.touch(exist_ok=True)
        with mock.patch.object(
            collect.sqlite3, "connect", side_effect=sqlite3.OperationalError("permission denied")
        ):
            with self.assertRaises(collect.CollectError) as caught:
                collect.connect_readonly(db)
        self.assertIn("cannot open database read-only", str(caught.exception))
        db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
