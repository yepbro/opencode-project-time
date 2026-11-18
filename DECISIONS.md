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

Note: the wall-clock metric and the wording around it were superseded by D-002.

## D-002 — Remove wall-clock time from collection and reports

Context: the owner clarified that time waiting for the next prompt is not work.
A session with two prompts a day apart would otherwise contribute a full day
of wall clock even though the agent was active for minutes.

Decision:

- Drop `wall_ms` from the snapshot schema, all totals, day buckets, and session
  rows. Drop the wall column and the wall-derived percentage from the Markdown
  report.
- Keep execution time (first assistant step to each `idle` message, including
  tool and shell waits) and the last busy window as the only time metrics.
- Keep session creation/update timestamps only as internal inputs for
  filtering, interval clipping, and the calendar range printed in the report.

Consequences: snapshots from before this decision are not schema-compatible
with the new renderer; regenerate them with `scripts/collect.py`.

## D-003 — Default scope: current project and all sessions

Context: the owner wants an ordinary request to cover the full effort on a
project without extra flags. Earlier reports silently omitted child sessions,
which understated the work.

Decision:

- Child sessions are included by default. `--include-subagents` is removed and
  replaced by the opposite flag `--main-only`, which reproduces the old narrow
  scope. The snapshot records `main_only`.
- With no `--project` and no `--dir`, the collector resolves the current project
  from the working directory using canonical worktrees, parent directories
  named after the project, and recorded session directories.
- If resolution fails, the collector returns an error telling the caller to ask
  the owner which project to collect and pass it explicitly. The plugin tool
  uses `ctx.location.directory` for the same purpose and surfaces collector
  errors to the model.

Consequences: a report for the current directory can be produced with no flags.
Duplicate project ids that share one worktree are merged; home and root are
skipped so no catch-all project hides a missing project. Genuinely ambiguous
matches are errors, not guesses. Existing snapshots that lack `main_only`
still render because the renderer does not read that field.

## D-004 — Make the slash command a real entry point

Context: `/project-time` only rewrote the user prompt and relied on the model
deciding to invoke the skill. It had no argument parsing and no deterministic
result.

Decision:

- Extract report generation into one exported `generateReport` function shared
  by the tool and the command. Both write the same snapshot/report paths and
  return the same description.
- `parseCommand` accepts a positional project name plus `--project`, `--dir`,
  `--since`, `--until`, and `--main-only`. Unknown or malformed arguments
  produce a usage error instead of a report.
- The command posts the result as a synthetic session message; it does not
  start a model turn. OpenCode configuration is still not modified by this
  repository.

Consequences: the skill, the tool, and the command are three inputs to one
mechanism. Node tests transpile the plugin with a stubbed SDK and a stub
`python3` to verify parsing and flag propagation without loading the plugin.

## D-005 — GitHub repository settings

Context: the owner wants changes to land only through pull requests that they
accept, a linear `main` history, branch protection on `main`, and the ability to
push directly as the repository owner.

Decision:

- Disable merge commits in the repository (`allow_merge_commit=false`); keep
  squash and rebase merges available. Protect `main` with `required_linear_history=true`.
- Require one approving review and dismiss stale reviews on `main`; force pushes
  and branch deletion are disabled. The only collaborator is the owner, so only
  they can approve and merge a PR.
- Keep `enforce_admins=false`: on a personal repository the branch-protection
  API rejects user/team restrictions and bypass allowances with "Only
  organization repositories can have users and team restrictions" (HTTP 422),
  so the owner's direct pushes are preserved by not applying the rules to
  administrators.

Consequences: other contributors must open a PR, and the merge methods cannot
create a merge commit. If more collaborators are added, restrict approvals with
a `CODEOWNERS` file and `require_code_owner_reviews=true`, or move the
repository to an organization to use explicit bypass actors.

## D-006 — MIT license

Context: the owner wants the most permissive license that does not conflict with
OpenCode's rules. OpenCode and `@opencode/plugin` are MIT, and the plugin docs
impose no additional licensing requirement.

Decision:

- Add a standard MIT `LICENSE` with copyright `2026 Den Brooks` and declare
  `"license": "MIT"` in `package.json` so installed packages carry it.
- Keep the attribution clause: it is the condition MIT itself requires and is
  compatible with OpenCode's own license.

Consequences: downstream users may use, modify, and redistribute the plugin,
including commercially, provided they keep the copyright and permission notice.

## D-007 — Per-day attribution of prompts, steps, tool calls, and tokens

Context: the owner wants the "By day (UTC)" table to carry the full metric
set, not just execution time and session counts. Tokens live on `session_v2`
rows while prompts, steps, and tool calls are derived from `session_message`,
and attributing a session's totals to its creation day would put a
day-spanning session's work on the wrong day. In the real database, assistant
messages carry per-message usage in `data.tokens` (`input`, `output`,
`reasoning`, `cache.read`), but the last step of an unfinished session can
have `tokens: null`, so message sums do not always reproduce the session
totals.

Decision:

- Prompts, steps, and tool calls are attributed to the UTC day of the message
  (`session_message.time_created`); a message row without a timestamp falls
  back to the session's creation timestamp so the counts still sum to the
  totals.
- Token usage is attributed to the day of the assistant message that records
  it. The difference between a session's `session_v2` token totals and the
  sum over its messages (unfinished last step, aborted message, missing
  token data) is attributed to the session's creation day. Daily token sums
  therefore equal the report totals exactly. `tokens_cache_write` stays a
  report-total-only metric because the day table shows the same four token
  kinds as the metadata bullets.
- A day bucket exists only where a session had activity (execution, messages,
  or a token remainder), so creation-only days no longer produce empty `0m/0`
  rows. The day's Sessions value counts sessions with activity on that day;
  a session spanning midnight counts on both days, so the column is not
  additive and the table's Total row shows unique sessions (main plus
  subagents).
- Execution-time splitting at midnight is unchanged. Snapshot
  `schema_version` becomes 2; day buckets gain `prompts`, `tool_calls`, and
  the four token fields. Older snapshots still render — missing day fields
  default to zero.

Consequences: day rows sum to the report totals for every column except
Sessions, which is a per-day distinct count. Reports regenerated from old
snapshots show zeros in the new day columns until the snapshot is recollected.

## D-008 — Timestamp suffix on generated file names

Context: reports from different runs landed under the same `var/<slug>-report.md`
name, so a later run silently replaced an earlier one and a user could not tell
which report belonged to which generation.

Decision:

- Add a `YYYYMMDDHHII` suffix from the UTC generation time to both generated
  files: `<slug>-snapshot-<stamp>.json` and `<slug>-report-<stamp>.md`.
- Use UTC for consistency with the report's UTC day buckets; minute precision
  is enough for human ordering and keeps names short.
- `generationStamp()` is exported and covered by the Node command tests, which
  assert the format and that both files share one stamp.

Consequences: old unstamped files in `var/` are left alone. Two runs in the same
minute still overwrite each other; second-level precision was not requested.

