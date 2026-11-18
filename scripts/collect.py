#!/usr/bin/env python3
"""Collect read-only OpenCode session timing data for one or more projects.

The database is opened through a SQLite ``mode=ro`` URI and checked with
``PRAGMA query_only``. The only file written is the JSON snapshot requested
with ``--out``.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
MS_PER_DAY = 86_400_000


class CollectError(Exception):
    """An expected failure that should be shown to the caller."""


@dataclass
class ProjectScope:
    """Selection rules for rows of session_v2."""

    names: set[str] = field(default_factory=set)
    project_ids: set[str] = field(default_factory=set)
    directories: set[str] = field(default_factory=set)

    def matches(self, row: sqlite3.Row) -> bool:
        if row["project_id"] in self.project_ids:
            return True
        directory = row["directory"] or ""
        for prefix in self.directories:
            if directory == prefix or directory.startswith(prefix.rstrip("/") + "/"):
                return True
        return False


@dataclass(frozen=True)
class Interval:
    """A half-open time window in epoch milliseconds."""

    start: int
    end: int

    def clipped(self, low: int, high: int) -> "Interval | None":
        start = max(self.start, low)
        end = min(self.end, high)
        return Interval(start, end) if end > start else None


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def split_by_day(intervals: Iterable[Interval]) -> dict[str, int]:
    """Attribute durations to UTC calendar days, splitting at midnight."""
    totals: dict[str, int] = {}
    for interval in intervals:
        cursor = interval.start
        while cursor < interval.end:
            midnight = datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_start = int(midnight.timestamp() * 1000)
            stop = min(interval.end, day_start + MS_PER_DAY)
            key = day_key(cursor)
            totals[key] = totals.get(key, 0) + (stop - cursor)
            cursor = stop
    return totals


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise CollectError(f"OpenCode database not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise CollectError("connection is not read-only; refusing to continue")
    return connection


def resolve_scope(connection: sqlite3.Connection, args: argparse.Namespace) -> ProjectScope:
    scope = ProjectScope(
        names={name.lower() for name in args.project},
        directories={os.path.realpath(path) for path in args.dir},
    )
    if not scope.names and not scope.directories:
        raise CollectError("specify at least one --project or --dir")
    for row in connection.execute("SELECT id, worktree, name FROM project"):
        worktree = os.path.realpath(row["worktree"])
        candidates = {
            (row["name"] or "").lower(),
            os.path.basename(worktree).lower(),
            row["id"].lower(),
        }
        if scope.names & candidates:
            scope.project_ids.add(row["id"])
            scope.directories.add(worktree)
    return scope


def session_rows(connection: sqlite3.Connection, scope: ProjectScope) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT id, project_id, parent_id, directory, title,
               time_created, time_updated, time_busy, time_idle, idle_outcome,
               tokens_input, tokens_output, tokens_reasoning,
               tokens_cache_read, tokens_cache_write, cost
        FROM session_v2
        ORDER BY time_created, id
        """
    ).fetchall()
    return [row for row in rows if scope.matches(row)]


def message_rows(connection: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT type, time_created, data FROM session_message "
        "WHERE session_id = ? ORDER BY seq, time_created, id",
        (session_id,),
    ).fetchall()


def payload_time(row: sqlite3.Row) -> int | None:
    try:
        data = json.loads(row["data"])
    except (TypeError, ValueError):
        return None
    created = (data.get("time") or {}).get("created")
    return int(created) if isinstance(created, int) else None


def count_tool_calls(row: sqlite3.Row) -> int:
    try:
        data = json.loads(row["data"])
    except (TypeError, ValueError):
        return 0
    return sum(1 for part in data.get("content", []) if part.get("type") == "tool")


def execution_intervals(
    messages: list[sqlite3.Row], created: int, updated: int
) -> list[Interval]:
    """Rebuild execution windows from the message stream.

    An ``idle`` message ends an execution. Its start is the first assistant
    message since the previous idle, so tool waits stay inside the window and
    time spent waiting for the next user prompt stays outside it.
    """
    intervals: list[Interval] = []
    first_assistant: int | None = None
    for row in messages:
        if row["type"] == "assistant":
            if first_assistant is None:
                first_assistant = int(row["time_created"])
            continue
        if row["type"] != "idle":
            continue
        end = payload_time(row)
        if end is not None and first_assistant is not None and end > first_assistant:
            clipped = Interval(first_assistant, end).clipped(created, updated)
            if clipped:
                intervals.append(clipped)
        first_assistant = None
    return intervals


def in_range(start: int, end: int, args: argparse.Namespace) -> bool:
    if args.since is not None and end < args.since:
        return False
    if args.until is not None and start > args.until:
        return False
    return True


def collect(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(connection, args)
    totals = {
        "wall_ms": 0,
        "exec_ms": 0,
        "busy_ms": 0,
        "sessions": 0,
        "subagents": 0,
        "prompts": 0,
        "steps": 0,
        "tool_calls": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "cost": 0.0,
    }
    days: dict[str, dict[str, int]] = {}
    sessions: list[dict[str, Any]] = []
    started: list[int] = []
    finished: list[int] = []

    for row in session_rows(connection, scope):
        created = int(row["time_created"])
        updated = int(row["time_updated"])
        is_subagent = row["parent_id"] is not None
        if (is_subagent and not args.include_subagents) or not in_range(created, updated, args):
            continue

        started.append(created)
        finished.append(updated)
        messages = message_rows(connection, row["id"])
        intervals = execution_intervals(messages, created, updated)
        wall = max(0, updated - created)
        exec_ms = sum(item.end - item.start for item in intervals)
        busy = 0
        if row["time_busy"] is not None and row["time_idle"] is not None:
            busy = max(0, int(row["time_idle"]) - int(row["time_busy"]))

        daily_wall = split_by_day([Interval(created, updated)])
        daily_exec = split_by_day(intervals)
        for day in set(daily_wall) | set(daily_exec):
            bucket = days.setdefault(
                day, {"wall_ms": 0, "exec_ms": 0, "steps": 0, "sessions": 0}
            )
            bucket["wall_ms"] += daily_wall.get(day, 0)
            bucket["exec_ms"] += daily_exec.get(day, 0)
            bucket["sessions"] += 1

        steps = sum(1 for message in messages if message["type"] == "assistant")
        prompts = sum(1 for message in messages if message["type"] == "user")
        tools = sum(count_tool_calls(message) for message in messages if message["type"] == "assistant")
        created_day = day_key(created)
        days.setdefault(created_day, {"wall_ms": 0, "exec_ms": 0, "steps": 0, "sessions": 0})
        days[created_day]["steps"] += steps

        sessions.append({
            "id": row["id"],
            "title": row["title"],
            "directory": row["directory"],
            "subagent": is_subagent,
            "created": iso(created),
            "updated": iso(updated),
            "wall_ms": wall,
            "exec_ms": exec_ms,
            "busy_ms": busy,
            "outcome": row["idle_outcome"],
            "prompts": prompts,
            "steps": steps,
            "tool_calls": tools,
            "tokens_input": int(row["tokens_input"]),
            "tokens_output": int(row["tokens_output"]),
            "tokens_reasoning": int(row["tokens_reasoning"]),
            "tokens_cache_read": int(row["tokens_cache_read"]),
            "tokens_cache_write": int(row["tokens_cache_write"]),
            "cost": float(row["cost"]),
        })

        totals["wall_ms"] += wall
        totals["exec_ms"] += exec_ms
        totals["busy_ms"] += busy
        totals["sessions"] += 0 if is_subagent else 1
        totals["subagents"] += 1 if is_subagent else 0
        totals["prompts"] += prompts
        totals["steps"] += steps
        totals["tool_calls"] += tools
        totals["tokens_input"] += int(row["tokens_input"])
        totals["tokens_output"] += int(row["tokens_output"])
        totals["tokens_reasoning"] += int(row["tokens_reasoning"])
        totals["tokens_cache_read"] += int(row["tokens_cache_read"])
        totals["tokens_cache_write"] += int(row["tokens_cache_write"])
        totals["cost"] += float(row["cost"])

    return {
        "schema_version": 1,
        "project": {
            "names": sorted(scope.names),
            "project_ids": sorted(scope.project_ids),
            "directories": sorted(scope.directories),
        },
        "range": {
            "from": iso(min(started)) if started else None,
            "to": iso(max(finished)) if finished else None,
            "since": iso(args.since) if args.since else None,
            "until": iso(args.until) if args.until else None,
        },
        "include_subagents": args.include_subagents,
        "totals": totals,
        "days": [{"date": day, **values} for day, values in sorted(days.items())],
        "sessions": sorted(sessions, key=lambda item: item["created"] or ""),
    }


def parse_timestamp(value: str | None, flag: str) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollectError(f"invalid {flag} timestamp: {exc}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="OpenCode SQLite database")
    parser.add_argument(
        "--project", action="append", default=[], metavar="NAME",
        help="Project name, id, or checkout basename (repeatable)",
    )
    parser.add_argument(
        "--dir", action="append", default=[], metavar="PATH",
        help="Canonical checkout; worktrees below it are included (repeatable)",
    )
    parser.add_argument("--since", help="ISO-8601 lower bound on session end")
    parser.add_argument("--until", help="ISO-8601 upper bound on session start")
    parser.add_argument(
        "--include-subagents", action="store_true",
        help="Include child sessions in totals (normally reported separately)",
    )
    parser.add_argument("--out", type=Path, required=True, help="JSON snapshot to write")
    args = parser.parse_args(argv)
    args.since = parse_timestamp(args.since, "--since")
    args.until = parse_timestamp(args.until, "--until")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        connection = connect_readonly(args.db)
        try:
            snapshot = collect(connection, args)
        finally:
            connection.close()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(snapshot['sessions'])} sessions)")
        return 0
    except (CollectError, sqlite3.Error) as exc:
        print(f"collect: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
