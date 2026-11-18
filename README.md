# opencode-project-time

> **V2-only:** this plugin targets the OpenCode 2 plugin API (`@opencode/plugin`,
> `Plugin.define`). It does not load in OpenCode 1. The standalone `collect.py`
> and `report.py` scripts can still be run directly.

An OpenCode plugin that reports how much time was spent on a project, using
only read-only queries against OpenCode's local SQLite database.

The package contains four parts:

- `src/index.ts` — the server plugin: registers the skill, a `time_project_report`
  tool, and the `/project-time` command.
- `skill/SKILL.md` — the skill that drives a report from natural-language
  requests such as "how long did we work on EunomiaSync?".
- `scripts/collect.py` and `scripts/report.py` — the data collector and the
  Markdown renderer. They work without the plugin.
- `REPORT_FORMAT.md` — the report contract; `examples/sample-report.md` is a
  short example with synthetic data.

## Safety

`collect.py` opens `~/.local/share/opencode/opencode.db` with a `mode=ro` URI and
enables `PRAGMA query_only = ON`. It never writes to the database, its WAL, or
its SHM file. The only files it writes are the JSON snapshot and Markdown report
you pass with `--out`. OpenCode configuration files are not touched by this
project.

## Defaults

- **Project:** the current project, resolved from the working directory (canonical
  checkout, a parent directory named after the project, or a recorded session
  directory). If it cannot be identified, the collector exits with an error that
  asks for the project name explicitly. `--project NAME` or `--dir PATH` override
  the default; both flags may be repeated.
- **Period:** all recorded sessions. `--since` and `--until` accept ISO-8601
  timestamps and narrow the selection.
- **Child sessions:** included. Use `--main-only` when a report should contain
  only main sessions; this is the only flag that reduces the default scope.

## Usage without the plugin

Current project, all sessions:

```sh
python3 scripts/collect.py --out var/current-snapshot.json
python3 scripts/report.py var/current-snapshot.json --out var/current-report.md
```

Named project and period, main sessions only:

```sh
python3 scripts/collect.py --project EunomiaSync \
  --since 2026-11-17T00:00:00Z --until 2026-11-18T23:59:59Z \
  --main-only --out var/eunomiasync-main-snapshot.json
python3 scripts/report.py var/eunomiasync-main-snapshot.json \
  --out var/eunomiasync-main-report.md
```

The `--project` value matches an OpenCode project name, a checkout directory
basename, or a project id. Use `--dir PATH` to select a canonical checkout,
including its worktrees. `--db PATH` overrides the database location.

## Example requests to the skill

| Request | Effective parameters |
| --- | --- |
| "How long did we work on this project?" | current project, all sessions, child sessions included |
| "Time report for EunomiaSync" | `--project EunomiaSync`, all sessions, child sessions included |
| "Report for EunomiaSync for the last two days" | `--project EunomiaSync`, `--since`/`--until` for those days, child sessions included |
| "Only main sessions on EunomiaSync, all time" | `--project EunomiaSync`, `--main-only` |

When the project is not named and the current directory cannot be resolved, the
skill should relay the error and ask the owner which project to collect.

## Plugin entry points

All three entry points call the same generator; only the way of specifying
parameters differs.

- **Skill** — natural language, for example «How long did we work on this
  project?». The skill drives `collect.py` and `report.py`.
- **Tool** `time_project_report` (`tools.time.project_report` in Code Mode) —
  for agents. It accepts `project`, `directory`, `since`, `until`, and
  `mainOnly`; with no arguments it uses the plugin's current location.
- **Command** `/project-time` — for the user, executes the report directly and
  posts the file paths into the session as a synthetic message. No model turn
  is required.

Command syntax:

```text
/project-time [PROJECT | --project NAME | --dir PATH] [--since ISO] [--until ISO] [--main-only]
```

Examples:

```text
/project-time
/project-time EunomiaSync
/project-time --project EunomiaSync --since 2026-11-17T00:00:00Z --until 2026-11-18T00:00:00Z
/project-time --dir /home/brooks/projects/business/EunomiaSync --main-only
```

`--main-only` reproduces the older narrow scope; the default includes child
sessions. Invalid arguments produce a usage message instead of a report.

## Metrics

| Metric | Definition | What it includes |
| --- | --- | --- |
| Execution | First assistant message to each `idle` message in `session_message` | Model work, tool calls, waiting for shell and subagent results |
| Last busy window | `time_idle - time_busy` in `session_v2` | Only the final execution of a session |

Wall-clock session duration is not collected or reported: waiting for the next
prompt is not work. OpenCode stores only the final `busy`/`idle` timestamps per
session, so older execution windows have to be reconstructed from the message
stream. Daily totals are attributed to UTC calendar days and intervals are
split at midnight.

## Installing the plugin (not done by this repository)

No OpenCode configuration is changed here. To load the plugin, add its directory
to `plugins` in `opencode.jsonc` (global or project-local):

```jsonc
{
  "plugins": ["/home/brooks/projects/utils/opencode-project-time"]
}
```

Optional plugin options: `dbPath`, `outputDir`.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test tests/command.test.mjs
```

The Python tests build a synthetic SQLite database with the relevant OpenCode
tables. They check scope matching, worktree inclusion, daily splitting,
subagent handling, time filters, the read-only guard, and the rendered Markdown.
The Node test transpiles `src/index.ts`, stubs `@opencode/plugin` and `python3`,
then checks command argument parsing and that both entry points pass the right
flags and write both output files. It needs the TypeScript compiler; set
`TS_MODULE` if it is not resolvable by default.

## Validation data

The real-data check uses the EunomiaSync project from OpenCode's database. The
generated snapshot and report are written to `var/` and are gitignored.
