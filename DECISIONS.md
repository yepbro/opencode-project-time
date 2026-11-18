# Decisions

## D-001 — Standalone read-only project time reporter

Context: the owner asked for an OpenCode plugin that calculates time per
project, including a skill, scripts, and a report format. The test project is
EunomiaSync. The plugin must not be placed in the EunomiaSync repository, must
not be wired into any OpenCode configuration yet, and must never modify the
OpenCode database.

Decision:

- The code lives in a standalone repository at
  `~/projects/utils/opencode-project-time`, with local git identity
  `Den Brooks <denis@yepbro.pro>`. It has no remote, so the task-id project
  identifier is the directory name `opencode-project-time`.
- The database is read via a `mode=ro` SQLite URI plus
  `PRAGMA query_only = ON` in `scripts/collect.py`. No other code path opens
  the database. Generated snapshots and reports go to gitignored `var/`.
- Three time metrics are reported instead of one: wall clock
  (`time_updated - time_created`), execution (first assistant message to each
  `idle` message, so shell and tool waits are included), and last busy window
  (`time_idle - time_busy`, only the final execution). OpenCode stores no
  cumulative active-time duration, so reconstruction is necessary.
- Child sessions are excluded from totals by default to avoid double counting
  overlapping wall-clock windows; `--include-subagents` opts in.
- Daily totals use UTC and split intervals at midnight.

Consequences: the report is an approximation of active work, not a billable
timesheet. Wall clock is an upper bound and the last busy window is a lower
bound. No OpenCode configuration file or database object is changed by this
project.
