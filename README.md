# opencode-project-time

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

Use the plugin tool `time_project_report` (or `tools.time.project_report` in Code
Mode). With no arguments it uses the plugin's current location as the project;
it accepts `project`, `since`, `until`, and `mainOnly`. The `/project-time`
command asks the model to use the skill.

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
```

The tests build a synthetic SQLite database with the relevant OpenCode tables.
They check scope matching, worktree inclusion, daily splitting, subagent
handling, time filters, the read-only guard, and the rendered Markdown.

## Validation data

The real-data check uses the EunomiaSync project from OpenCode's database. The
generated snapshot and report are written to `var/` and are gitignored.
