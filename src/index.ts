import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { Plugin, Skill } from '@opencode/plugin'

const run = promisify(execFile)
const root = fileURLToPath(new URL('..', import.meta.url))
const skillPath = fileURLToPath(new URL('../skill/SKILL.md', import.meta.url))
const collectScript = resolve(root, 'scripts/collect.py')
const renderScript = resolve(root, 'scripts/report.py')

type ReportInput = {
  project?: string
  since?: string
  until?: string
  includeSubagents?: boolean
}

function optionString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback
}

export default Plugin.define({
  id: 'opencode-project-time',
  async setup(ctx) {
    const options = (ctx.options ?? {}) as Record<string, unknown>
    const defaultDb = optionString(options.dbPath, '')
    const outputDir = resolve(root, optionString(options.outputDir, 'var'))
    const skillContent = await readFile(skillPath, 'utf8')

    await ctx.skill.transform((editor) => {
      editor.add({
        id: Skill.ID.make('project-time-report'),
        name: Skill.Name.make('Project time report'),
        description:
          'Generate a read-only OpenCode project time report with execution time, daily breakdown, and session details.',
        path: Skill.Info.fields.path.make(skillPath),
        content: skillContent,
      })
    })

    await ctx.tool.transform((editor) => {
      editor.namespace({
        name: 'time',
        description: 'Read-only project timing reports from OpenCode sessions',
      })
      editor.add({
        name: 'project_report',
        description:
          'Collect session timing data for an OpenCode project and write a Markdown report. The source database is opened read-only.',
        input: {
          type: 'object',
          properties: {
            project: {
              type: 'string',
              description: 'Project name, checkout basename, or OpenCode project id',
            },
            since: { type: 'string', description: 'ISO-8601 lower bound on session end' },
            until: { type: 'string', description: 'ISO-8601 upper bound on session start' },
            includeSubagents: { type: 'boolean', description: 'Include child sessions in totals' },
          },
          required: ['project'],
          additionalProperties: false,
        },
        options: { namespace: 'time', codemode: true },
        execute: async (input, toolContext) => {
          const args = input as ReportInput
          const project = String(args.project ?? '').trim()
          if (!/^[A-Za-z0-9._/-]{1,120}$/.test(project)) {
            throw new Error('project must be a short name, id, or path-like token')
          }
          const slug = project.replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80)
          const snapshot = resolve(outputDir, `${slug}-snapshot.json`)
          const report = resolve(outputDir, `${slug}-report.md`)
          const collectArgs = [collectScript, '--project', project, '--out', snapshot]
          if (defaultDb) collectArgs.push('--db', defaultDb)
          if (args.since) collectArgs.push('--since', args.since)
          if (args.until) collectArgs.push('--until', args.until)
          if (args.includeSubagents) collectArgs.push('--include-subagents')
          if (toolContext.signal.aborted) throw new Error('aborted')

          const first = await run('python3', collectArgs, { cwd: root, timeout: 120_000 })
          const second = await run('python3', [renderScript, snapshot, '--out', report], {
            cwd: root,
            timeout: 60_000,
          })
          return { content: `${first.stdout.trim()}\n${second.stdout.trim()}\nReport: ${report}` }
        },
      })
    })

    await ctx.command.transform((editor) => {
      editor.add({
        name: 'project-time',
        description: 'Generate a read-only time report for an OpenCode project',
        execute: async ({ sessionID, prompt, delivery }) => {
          await ctx.session.prompt({
            ...prompt,
            sessionID,
            text: `Use the project-time-report skill to generate a project time report. ${prompt.text}`.trim(),
            delivery,
          })
        },
      })
    })
  },
})
