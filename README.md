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

## Usage without the plugin

```sh
python3 scripts/collect.py --project EunomiaSync --out var/eunomiasync-snapshot.json
python3 scripts/report.py var/eunomiasync-snapshot.json --out var/eunomiasync-report.md
```

The `--project` value matches an OpenCode project name, a checkout directory
basename, or a project id. Use `--dir PATH` to select a canonical checkout,
including its worktrees. Repeat either flag to combine projects.

Other flags:

| Flag | Meaning |
| --- | --- |
| `--db PATH` | Override the default OpenCode database path |
| `--since`, `--until` | ISO-8601 bounds on session end and session start |
| `--include-subagents` | Add child sessions to totals (excluded by default) |

Use the plugin tool `time_project_report` (or `tools.time.project_report` in Code
Mode) with `{"project":"EunomiaSync"}` to run both steps and get the report path.
The `/project-time` command asks the model to use the skill.

## Metrics

| Metric | Definition | What it includes |
| --- | --- | --- |
| Wall clock | `time_updated - time_created` per session | Everything: waiting for the next prompt, server restarts |
| Execution | First assistant message to each `idle` message in `session_message` | Model work, tool calls, waiting for shell and subagent results |
| Last busy window | `time_idle - time_busy` in `session_v2` | Only the final execution of a session |

OpenCode stores only the final `busy`/`idle` timestamps per session, so older
execution windows have to be reconstructed from the message stream. Daily totals
are attributed to UTC calendar days and intervals are split at midnight.

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
