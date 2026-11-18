# Report format

`scripts/report.py` renders a deterministic Markdown document. The report has
five fixed sections in this order:

1. **Title and metadata** — project names, UTC period covered, session counts,
   prompt/step/tool-call counts, token totals, and recorded cost.
2. **Time summary** — a three-row table with wall clock, reconstructed
   execution time, and last busy window. Each row gives an absolute duration
   and its share of wall clock.
3. **Metric explanation** — a short paragraph stating what wall clock and
   execution time include.
4. **By day (UTC)** — one row per calendar day with wall clock, execution time,
   and the number of sessions active on that day.
5. **Sessions** — one row per session with creation date, title, type (main or
   subagent), wall clock, execution time, and idle outcome.

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

| Metric | Value | Share of wall clock |
| --- | ---: | ---: |
| Wall clock | 2.0h | 100.0% |
| Execution (reconstructed) | 1.0h | 50.0% |
| Last busy window | 30m | 25.0% |

## By day (UTC)

| Day | Wall clock | Execution | Sessions |
| --- | ---: | ---: | ---: |
| 2026-01-01 | 2.0h | 1.0h | 2 |

## Sessions

| Created | Title | Type | Wall | Exec | Outcome |
| --- | --- | --- | ---: | ---: | --- |
| 2026-01-01 | Example session | main | 2.0h | 1.0h | succeeded |
```

A complete generated example for EunomiaSync is written to
`var/eunomiasync-report.md` during validation; that file is gitignored because
it contains real session titles.
