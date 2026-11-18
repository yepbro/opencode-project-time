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

from paths import DEFAULT_DB, UnsafeOutputError, refuse_database_output

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


def detect_current_project(
    connection: sqlite3.Connection, directory: Path
) -> tuple[set[str], str] | None:
    """Find the OpenCode project owning a directory, walking up its parents.

    The nearest matching level wins. Several project ids may point at the same
    worktree; they are merged, since OpenCode can create duplicate project rows.
    Home and root are skipped so a catch-all project never hides a missing
    project. A directory named after a worktree covers worktree checkouts.
    """
    projects = [
        (row["id"], os.path.realpath(row["worktree"]))
        for row in connection.execute("SELECT id, worktree FROM project")
    ]
    ignored = {os.path.realpath(Path.home()), "/"}
    current = os.path.realpath(directory)
    while current not in ignored:
        found: dict[str, str] = {}
        basename = os.path.basename(current).lower()
        for project_id, worktree in projects:
            if worktree in ignored:
                continue
            if worktree == current or (basename and os.path.basename(worktree).lower() == basename):
                found[project_id] = worktree
        for row in connection.execute(
            "SELECT DISTINCT project_id, directory FROM session_v2 WHERE directory = ?",
            (current,),
        ):
            project_id = row["project_id"]
            canonical = next((path for pid, path in projects if pid == project_id), None)
            found[project_id] = canonical or current
        if found:
            directories = set(found.values())
            if len(directories) > 1:
                raise CollectError(f"ambiguous current project for {directory}: {sorted(directories)}")
            return set(found), directories.pop()
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def resolve_scope(connection: sqlite3.Connection, args: argparse.Namespace) -> ProjectScope:
    names = {name.lower() for name in args.project}
    directories = {os.path.realpath(path) for path in args.dir}
    if not names and not directories:
        current = detect_current_project(connection, Path.cwd())
        if current is None:
            raise CollectError(
                "cannot determine the current project from the working directory; "
                "tell the owner which project to collect and pass --project NAME or --dir PATH"
            )
        project_ids, worktree = current
        return ProjectScope(project_ids=project_ids, directories={worktree})

    scope = ProjectScope(names=names, directories=directories)
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
    for directory in directories:
        current = detect_current_project(connection, Path(directory))
        if current:
            scope.project_ids.update(current[0])
            scope.directories.add(current[1])
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


def _token_count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def message_tokens(row: sqlite3.Row) -> dict[str, int]:
    """Token usage recorded on one assistant message; zeros when absent.

    OpenCode stores usage in ``data.tokens`` as ``input``/``output``/
    ``reasoning`` plus ``cache.read``. The last step of an unfinished session
    can carry no token data, which the per-session reconciliation covers.
    """
    try:
        data = json.loads(row["data"])
    except (TypeError, ValueError):
        data = {}
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    return {
        "input": _token_count(tokens.get("input")),
        "output": _token_count(tokens.get("output")),
        "reasoning": _token_count(tokens.get("reasoning")),
        "cache_read": _token_count(cache.get("read")),
    }


def new_day_bucket() -> dict[str, int]:
    return {
        "exec_ms": 0,
        "sessions": 0,
        "prompts": 0,
        "steps": 0,
        "tool_calls": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
    }


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
        if (is_subagent and args.main_only) or not in_range(created, updated, args):
            continue

        started.append(created)
        finished.append(updated)
        messages = message_rows(connection, row["id"])
        intervals = execution_intervals(messages, created, updated)
        exec_ms = sum(item.end - item.start for item in intervals)
        busy = 0
        if row["time_busy"] is not None and row["time_idle"] is not None:
            busy = max(0, int(row["time_idle"]) - int(row["time_busy"]))

        daily_exec = split_by_day(intervals)
        day_prompts: dict[str, int] = {}
        day_steps: dict[str, int] = {}
        day_tools: dict[str, int] = {}
        day_tokens: dict[str, dict[str, int]] = {}
        message_token_sums = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
        for message in messages:
            kind = message["type"]
            if kind not in ("user", "assistant"):
                continue
            day = day_key(int(message["time_created"] or created))
            if kind == "user":
                day_prompts[day] = day_prompts.get(day, 0) + 1
                continue
            day_steps[day] = day_steps.get(day, 0) + 1
            day_tools[day] = day_tools.get(day, 0) + count_tool_calls(message)
            bucket = day_tokens.setdefault(
                day, {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
            )
            for name, value in message_tokens(message).items():
                bucket[name] += value
                message_token_sums[name] += value

        session_tokens = {
            "input": int(row["tokens_input"]),
            "output": int(row["tokens_output"]),
            "reasoning": int(row["tokens_reasoning"]),
            "cache_read": int(row["tokens_cache_read"]),
        }
        residual = {
            name: session_tokens[name] - message_token_sums[name] for name in session_tokens
        }
        created_day = day_key(created)
        if any(residual.values()):
            bucket = day_tokens.setdefault(
                created_day, {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
            )
            for name, value in residual.items():
                bucket[name] += value

        steps = sum(day_steps.values())
        prompts = sum(day_prompts.values())
        tools = sum(day_tools.values())

        # A day row exists only where the session had activity, and the
        # Sessions column counts sessions with activity on that day.
        active_days = set(daily_exec) | set(day_prompts) | set(day_steps)
        if any(residual.values()):
            active_days.add(created_day)
        for day in active_days:
            days.setdefault(day, new_day_bucket())["sessions"] += 1
        for day, exec_on_day in daily_exec.items():
            days.setdefault(day, new_day_bucket())["exec_ms"] += exec_on_day
        for day, count_on_day in day_prompts.items():
            days.setdefault(day, new_day_bucket())["prompts"] += count_on_day
        for day, count_on_day in day_steps.items():
            days.setdefault(day, new_day_bucket())["steps"] += count_on_day
        for day, count_on_day in day_tools.items():
            days.setdefault(day, new_day_bucket())["tool_calls"] += count_on_day
        for day, kinds in day_tokens.items():
            bucket = days.setdefault(day, new_day_bucket())
            bucket["tokens_input"] += kinds["input"]
            bucket["tokens_output"] += kinds["output"]
            bucket["tokens_reasoning"] += kinds["reasoning"]
            bucket["tokens_cache_read"] += kinds["cache_read"]

        sessions.append({
            "id": row["id"],
            "title": row["title"],
            "directory": row["directory"],
            "subagent": is_subagent,
            "created": iso(created),
            "updated": iso(updated),
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
        "schema_version": 2,
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
        "main_only": args.main_only,
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
        "--main-only", action="store_true",
        help="Exclude child sessions from totals (all sessions are included by default)",
    )
    parser.add_argument("--out", type=Path, required=True, help="JSON snapshot to write")
    args = parser.parse_args(argv)
    args.since = parse_timestamp(args.since, "--since")
    args.until = parse_timestamp(args.until, "--until")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        refuse_database_output(args.out, args.db)
        connection = connect_readonly(args.db)
        try:
            snapshot = collect(connection, args)
        finally:
            connection.close()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(snapshot['sessions'])} sessions)")
        return 0
    except (CollectError, UnsafeOutputError, sqlite3.Error) as exc:
        print(f"collect: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
