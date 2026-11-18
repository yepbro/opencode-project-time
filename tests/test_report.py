"""Behavior tests for the Markdown report renderer."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import report  # noqa: E402


def snapshot(**overrides):
    data = {
        "schema_version": 1,
        "project": {"names": ["EunomiaSync"], "project_ids": ["p1"], "directories": ["/work/eunomia"]},
        "range": {"from": "2026-01-01T23:50:00+00:00", "to": "2026-01-02T00:30:00+00:00"},
        "main_only": False,
        "totals": {
            "exec_ms": 1_200_000,
            "busy_ms": 600_000,
            "sessions": 1,
            "subagents": 0,
            "prompts": 1,
            "steps": 2,
            "tool_calls": 3,
            "tokens_input": 100,
            "tokens_output": 20,
            "tokens_reasoning": 5,
            "tokens_cache_read": 1000,
            "tokens_cache_write": 10,
            "cost": 0.25,
        },
        "days": [
            {
                "date": "2026-01-01", "exec_ms": 300_000, "sessions": 1,
                "prompts": 1, "steps": 1, "tool_calls": 2,
                "tokens_input": 60, "tokens_output": 12,
                "tokens_reasoning": 3, "tokens_cache_read": 600,
            },
            {
                "date": "2026-01-02", "exec_ms": 900_000, "sessions": 2,
                "prompts": 0, "steps": 1, "tool_calls": 1,
                "tokens_input": 40, "tokens_output": 8,
                "tokens_reasoning": 2, "tokens_cache_read": 400,
            },
        ],
        "sessions": [
            {
                "id": "main-1",
                "title": "Session | with pipe",
                "directory": "/work/eunomia",
                "subagent": False,
                "created": "2026-01-01T23:50:00+00:00",
                "updated": "2026-01-02T00:30:00+00:00",
                "exec_ms": 1_200_000,
                "busy_ms": 600_000,
                "outcome": "succeeded",
            }
        ],
    }
    data.update(overrides)
    return data


class ReportTests(unittest.TestCase):
    def test_report_contains_expected_sections_and_values(self) -> None:
        text = report.render(snapshot())
        self.assertIn("# Project time report", text)
        self.assertIn("EunomiaSync", text)
        self.assertIn("| Execution (reconstructed) | 20m |", text)
        self.assertIn("| Last busy window | 10m |", text)
        self.assertIn(
            "| Day | Execution | Sessions | Prompts | Steps | Tool calls "
            "| Tokens in | Tokens out | Reasoning | Cache read |",
            text,
        )
        self.assertIn("| 2026-01-01 | 5m | 1 | 1 | 1 | 2 | 60 | 12 | 3 | 600 |", text)
        self.assertIn("| 2026-01-02 | 15m | 2 | 0 | 1 | 1 | 40 | 8 | 2 | 400 |", text)
        self.assertIn("| Total | 20m | 1 | 1 | 2 | 3 | 100 | 20 | 5 | 1,000 |", text)
        self.assertIn("attributed to the UTC day of the message", text)
        self.assertIn("Session \\| with pipe", text)
        self.assertIn("succeeded", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("${", text)

    def test_legacy_day_rows_render_with_zero_defaults(self) -> None:
        legacy = snapshot(
            days=[
                {"date": "2026-01-01", "exec_ms": 300_000, "steps": 1, "sessions": 1},
            ]
        )
        text = report.render(legacy)
        self.assertIn("| 2026-01-01 | 5m | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |", text)
        self.assertIn("| Total | 20m | 1 | 1 | 2 | 3 | 100 | 20 | 5 | 1,000 |", text)


    def test_default_project_label_uses_directory_name(self) -> None:
        data = snapshot(
            project={"names": [], "project_ids": ["p1"], "directories": ["/work/eunomia"]}
        )
        self.assertIn("**Project:** eunomia", report.render(data))

    def test_empty_snapshot_renders_without_division_error(self) -> None:
        empty = snapshot(days=[], sessions=[])
        empty["totals"]["exec_ms"] = 0
        empty["totals"]["cost"] = 0.0
        text = report.render(empty)
        self.assertIn("| Execution (reconstructed) | 0m |", text)
        self.assertIn("## By day (UTC)", text)

    def test_out_cannot_overwrite_default_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            original = b"SQLite format 3\0"
            db.write_bytes(original)
            source = Path(tmp) / "snapshot.json"
            source.write_text(json.dumps(snapshot()), encoding="utf-8")
            with mock.patch.object(report, "DEFAULT_DB", db), redirect_stderr(StringIO()):
                code = report.main([str(source), "--out", str(db)])
            self.assertEqual(code, 2)
            self.assertEqual(db.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
