---
name: project-time-report
description: Build a time and activity report for an OpenCode project from the local OpenCode SQLite database. Use when the user asks how long work on a project took, wants a per-project time or effort report, a daily breakdown of agent activity, or wants to compare time across sessions - even when they do not mention this plugin. The database is always read-only.
---

# Project time report

Produce a Markdown report that answers "how much time was spent on this project"
using OpenCode's own session records. The source database is never modified.

## Guardrails

- Open the database only through `scripts/collect.py`, which uses a `mode=ro`
  SQLite URI and sets `PRAGMA query_only = ON`.
- Never write to `~/.local/share/opencode/opencode.db`, its WAL, or its SHM
  file. If a task appears to require that, stop and ask the owner.
- Do not change OpenCode configuration files while generating a report.
- Generated JSON snapshots and reports belong in `var/` unless the owner names
  another output directory.

## Workflow

1. Choose the project filter.

   - `--project NAME` matches the project name, the checkout directory basename,
     or the project id in OpenCode's `project` table.
   - `--dir PATH` matches a canonical checkout; worktrees below it are included.
   - Repeat either flag to combine several projects or directories.

2. Collect a snapshot:

   ```sh
   python3 scripts/collect.py --project EunomiaSync --out var/eunomiasync-snapshot.json
   ```

3. Render the report:

   ```sh
   python3 scripts/report.py var/eunomiasync-snapshot.json --out var/eunomiasync-report.md
   ```

4. Read the generated Markdown, report the headline numbers to the owner (wall
   clock, execution time, sessions, days covered) and give both file paths.

## Optional flags

- `--since` / `--until` accept ISO-8601 timestamps and filter sessions.
- `--include-subagents` adds child sessions to the totals. By default they are
  excluded from totals so overlapping wall-clock windows do not inflate time.
- `--db PATH` overrides the default database location
  (`~/.local/share/opencode/opencode.db`).

## Metrics and their meaning

| Metric | Source | Includes |
| --- | --- | --- |
| Wall clock | `time_updated - time_created` for each session | Waiting for the next prompt, server restarts, everything |
| Execution | First assistant message to each `idle` message in `session_message` | Model generation, tool calls, waiting for shell/subagent results; not user thinking time |
| Last busy window | `time_idle - time_busy` in `session_v2` | Only the final execution of each session; OpenCode does not store earlier windows as durations |

Timing is attributed to UTC calendar days, splitting intervals at midnight.
Token and cost figures come from the same session rows; report them as
recorded, without recomputing prices.

## Interpreting a report

Wall clock is an upper bound on project involvement, not a measure of active
work. Execution is the best available approximation of active time. The last
busy window is a lower bound and is useful mainly as a consistency check.

If a session has no `idle` message (interrupted run), it contributes wall clock
but no execution time; mention that when summarizing a report with such rows.

## Troubleshooting

- "database not found": pass `--db` with the actual OpenCode database path.
- Empty snapshot: check the spelling of `--project`, or use `--dir` with the
  canonical checkout path.
- A write-related SQLite error means the read-only guard failed. Stop; do not
  retry with a different connection mode.
