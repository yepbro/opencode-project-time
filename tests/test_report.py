"""Behavior tests for the Markdown report renderer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
            {"date": "2026-01-01", "exec_ms": 300_000, "steps": 1, "sessions": 1},
            {"date": "2026-01-02", "exec_ms": 900_000, "steps": 1, "sessions": 1},
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
        self.assertIn("| 2026-01-01 | 5m | 1 |", text)
        self.assertIn("| 2026-01-02 | 15m | 1 |", text)
        self.assertIn("Session \\| with pipe", text)
        self.assertIn("succeeded", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("${", text)

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


if __name__ == "__main__":
    unittest.main()
