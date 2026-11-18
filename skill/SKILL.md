---
name: project-time-report
description: Build a report of how much time OpenCode agents spent on a project from the local OpenCode SQLite database. Use when the user asks how long the agents worked on a project, wants a per-project agent time or effort report, a daily breakdown of agent activity, or wants to compare time across sessions - even when they do not mention this plugin. The database is always read-only.
---

# Project time report

Produce a Markdown report that answers "how much time was spent on this project"
using OpenCode's own session records. The source database is never modified.

## Guardrails

- This skill's base directory is the package's `skill/` directory. All paths
  below are relative to it: `../scripts/` is the package's `scripts/` directory
  and `../var/` is the package's output directory.
- Open the database only through `../scripts/collect.py`, which uses a `mode=ro`
  SQLite URI and sets `PRAGMA query_only = ON`.
- Never modify `~/.local/share/opencode/opencode.db` or its committed WAL
  frames. SQLite may create or attach a read-only `-shm` WAL-index file while
  reading; that is expected and is not a violation. If a task appears to
  require writing any of them, stop and ask the owner.
- Do not change OpenCode configuration files while generating a report.
- Generated JSON snapshots and reports belong in `../var/` unless the owner
  names another output directory.

## Workflow

1. Choose the project filter.

   - With no `--project` and no `--dir`, the collector resolves the **current
     project** from the working directory. If it cannot identify one, it fails
     with a message asking for the project name; relay that error to the owner
     and ask which project to collect, then pass the answer explicitly.
   - `--project NAME` matches the project name, the checkout directory basename,
     or the project id in OpenCode's `project` table.
   - `--dir PATH` matches a canonical checkout; worktrees below it are included.
   - Repeat either flag to combine several projects or directories.

2. Collect a snapshot. Child sessions are included by default:

   ```sh
   python3 ../scripts/collect.py --out ../var/current-snapshot.json
   ```
   
   For a named project:
   
   ```sh
   python3 ../scripts/collect.py --project EunomiaSync --out ../var/eunomiasync-snapshot.json
   ```
   
3. Render the report:
   
   ```sh
   python3 ../scripts/report.py ../var/eunomiasync-snapshot.json --out ../var/eunomiasync-report.md
   ```

4. Read the generated Markdown, report the headline numbers to the owner
   (execution time, last busy window, sessions, days covered) and give both
   file paths.

## Optional flags

- `--since` / `--until` accept ISO-8601 timestamps and filter sessions. With
  neither flag, all recorded sessions are collected.
- `--main-only` is the opposite of the default: it excludes child sessions and
  leaves only main sessions. It exists for an explicitly narrower report; do
  not add it to ordinary requests.
- `--db PATH` overrides the default database location
  (`~/.local/share/opencode/opencode.db`).

## Other entry points

When the plugin is loaded, `/project-time` runs the same generator directly and
posts the report path into the session. Its syntax is:

```text
/project-time [PROJECT | --project NAME | --dir PATH] [--since ISO] [--until ISO] [--main-only]
```

The tool `time_project_report` is the programmatic equivalent for agents; it
accepts `project`, `directory`, `since`, `until`, and `mainOnly`. Both use the
current plugin location when no project is given.

## Metrics and their meaning

| Metric | Source | Includes |
| --- | --- | --- |
| Execution | First assistant message to each `idle` message in `session_message` | Model generation, tool calls, waiting for shell/subagent results; not user thinking time |
| Last busy window | `time_idle - time_busy` in `session_v2` | Only the final execution of each session; OpenCode does not store earlier windows as durations |

Wall-clock session duration is deliberately not collected or reported. Time
spent waiting for the next prompt is not work and must not enter the totals.

Timing is attributed to UTC calendar days, splitting intervals at midnight.
Token and cost figures come from the same session rows; report them as
recorded, without recomputing prices.

## Interpreting a report

Execution is the best available approximation of active time. The last busy
window is a lower bound covering only the final execution of each session and
is useful mainly as a consistency check. A running session has no recorded
`idle` yet and therefore contributes zero execution time; mention that when
summarizing a report with such rows.

## Troubleshooting

- "cannot determine the current project": ask the owner which project to use,
  then rerun with `--project NAME` or `--dir PATH`.
- "ambiguous current project": more than one distinct checkout matched; ask the
  owner and pass the exact `--project NAME` or `--dir PATH`.
- "database not found": pass `--db` with the actual OpenCode database path.
- Empty snapshot: check the spelling of `--project`, or use `--dir` with the
  canonical checkout path.
- A write-related SQLite error means the read-only guard failed. Stop; do not
  retry with a different connection mode.
