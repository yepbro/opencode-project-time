# Report format

`scripts/report.py` renders a deterministic Markdown document. The report has
five fixed sections in this order:

1. **Title and metadata** — project names, UTC period covered, session counts,
   prompt/step/tool-call counts, token totals, and recorded cost.
2. **Time summary** — a two-row table with reconstructed execution time and
   last busy window, each as an absolute duration.
3. **Metric explanation** — a short paragraph stating what execution time and
   the last busy window include.
4. **By day (UTC)** — one row per calendar day with execution time, sessions
   with activity on that day, prompts, steps, tool calls, and token totals
   (input, output, reasoning, cache read), followed by a Total row with the
   report totals and a short paragraph on per-day attribution.
5. **Sessions** — one row per session with creation date, title, type (main or
   subagent), execution time, and idle outcome.

Wall-clock session duration is deliberately absent from the snapshot and the
report.

Durations are rounded: minutes below one hour (`19m`), one decimal of an hour
at or above one hour (`8.8h`). Token counts in the day table use thousands
separators, like the metadata bullets. A pipe character in a session title is
escaped.

Per-day attribution: execution time is split at UTC midnight; prompts, steps,
tool calls, and tokens follow the UTC day of the `session_message` row that
produced them. Token totals live on `session_v2`; the difference between a
session's totals and the sum of its messages (for example an unfinished last
step with no recorded tokens) is attributed to the session's creation day, so
the day rows sum to the report totals. The Sessions column counts sessions
with activity on that day — a session spanning midnight is counted on both
days — so it is not additive; the Total row shows unique sessions (main plus
subagents). Snapshots whose day rows predate these fields render with zeros in
the new columns.

Example skeleton:

```markdown
# Project time report

- **Project:** ExampleProject
- **Period:** 2026-01-01 — 2026-01-02
- **Sessions:** 2 main, 0 subagents
- **Prompts / steps / tool calls:** 4 / 20 / 7
- **Tokens:** 1,000 in, 100 out, 20 reasoning, 5,000 cache read
- **Cost:** $0.0000

## Time summary

| Metric | Value |
| --- | ---: |
| Execution (reconstructed) | 1.0h |
| Last busy window | 30m |

Execution time sums the intervals from the first assistant step to each `idle` message, so tool and shell waits are included. Last busy window reproduces `time_idle - time_busy` from `session_v2`, i.e. only the final execution of each session.

## By day (UTC)

| Day | Execution | Sessions | Prompts | Steps | Tool calls | Tokens in | Tokens out | Reasoning | Cache read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-01-01 | 40m | 2 | 3 | 12 | 4 | 700 | 60 | 12 | 3,000 |
| 2026-01-02 | 20m | 1 | 1 | 8 | 3 | 300 | 40 | 8 | 2,000 |
| Total | 1.0h | 2 | 4 | 20 | 7 | 1,000 | 100 | 20 | 5,000 |

Execution time is split at UTC midnight. Prompts, steps, tool calls, and tokens are attributed to the UTC day of the message that produced them; when a session's recorded token totals exceed the sum of its messages (for example an unfinished last step), the remainder is attributed to the session's creation day. Sessions counts sessions with activity on that day, so a session spanning midnight is counted on both days; the Total row shows unique sessions (main plus subagents).

## Sessions

| Created | Title | Type | Exec | Outcome |
| --- | --- | --- | ---: | --- |
| 2026-01-01 | Example session | main | 40m | succeeded |
| 2026-01-01 | Second session | main | 20m | - |
```

A complete generated example for the maintainer's local EunomiaSync project is
written to `var/eunomiasync-report.md` during manual validation; that file is
gitignored because it contains real session titles. Reports written by the
plugin itself carry a `YYYYMMDDHHMM` UTC stamp in the file name; these manual
CLI examples do not.
