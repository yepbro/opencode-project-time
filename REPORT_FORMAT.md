# Report format

`scripts/report.py` renders a deterministic Markdown document. The report has
five fixed sections in this order:

1. **Title and metadata** — project names, UTC period covered, session counts,
   prompt/step/tool-call counts, token totals, and recorded cost.
2. **Time summary** — a two-row table with reconstructed execution time and
   last busy window, each as an absolute duration.
3. **Metric explanation** — a short paragraph stating what execution time and
   the last busy window include.
4. **By day (UTC)** — one row per calendar day with execution time and the
   number of sessions with activity on that day.
5. **Sessions** — one row per session with creation date, title, type (main or
   subagent), execution time, and idle outcome.

Wall-clock session duration is deliberately absent from the snapshot and the
report.

Durations are rounded: minutes below one hour (`19m`), one decimal of an hour
at or above one hour (`8.8h`). A pipe character in a session title is escaped.

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

## By day (UTC)

| Day | Execution | Sessions |
| --- | ---: | ---: |
| 2026-01-01 | 1.0h | 2 |

## Sessions

| Created | Title | Type | Exec | Outcome |
| --- | --- | --- | ---: | --- |
| 2026-01-01 | Example session | main | 1.0h | succeeded |
```

A complete generated example for EunomiaSync is written to
`var/eunomiasync-report.md` during validation; that file is gitignored because
it contains real session titles.
