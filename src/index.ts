import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { basename, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { Plugin, Skill } from '@opencode/plugin'

const run = promisify(execFile)
const root = fileURLToPath(new URL('..', import.meta.url))
const skillPath = fileURLToPath(new URL('../skill/SKILL.md', import.meta.url))
const collectScript = resolve(root, 'scripts/collect.py')
const renderScript = resolve(root, 'scripts/report.py')
const controlPattern = /[\u0000-\u001f\u007f]/
const timePattern = /^[0-9TZ:+\-.]{1,40}$/
const usage =
  '/project-time [PROJECT | --project NAME | --dir PATH] [--since ISO] [--until ISO] [--main-only]'

type ReportRequest = {
  project?: string
  directory?: string
  since?: string
  until?: string
  mainOnly?: boolean
}

type ReportOptions = {
  dbPath: string
  outputDir: string
  locationDirectory: string
}

type ReportResult = {
  snapshot: string
  report: string
  collectorOutput: string
  rendererOutput: string
}

function optionString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback
}

export function requireName(value: string | undefined, flag: string): string {
  if (!value || value.length > 4096 || controlPattern.test(value)) {
    throw new Error(`${flag} must be a non-empty name or path without control characters`)
  }
  return value
}

function requireTime(value: string | undefined, flag: string): string {
  if (!value || !timePattern.test(value)) {
    throw new Error(`${flag} must be an ISO-8601 timestamp without spaces`)
  }
  return value
}

export function tokenize(text: string): string[] {
  const tokens: string[] = []
  const pattern = /"([^"]*)"|'([^']*)'|(\S+)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    tokens.push(match[1] ?? match[2] ?? match[3])
  }
  return tokens
}

export function parseCommand(text: string): ReportRequest {
  const tokens = tokenize(text)
  const request: ReportRequest = {}
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token === '--main-only') {
      request.mainOnly = true
      continue
    }
    if (token === '--project') {
      request.project = requireName(tokens[index + 1], '--project')
      index += 1
      continue
    }
    if (token === '--dir') {
      request.directory = requireName(tokens[index + 1], '--dir')
      index += 1
      continue
    }
    if (token === '--since') {
      request.since = requireTime(tokens[index + 1], '--since')
      index += 1
      continue
    }
    if (token === '--until') {
      request.until = requireTime(tokens[index + 1], '--until')
      index += 1
      continue
    }
    if (!token.startsWith('-') && !request.project) {
      request.project = requireName(token, 'PROJECT')
      continue
    }
    throw new Error(`unknown argument "${token}". Usage: ${usage}`)
  }
  return request
}

export function generationStamp(date: Date = new Date()): string {
  return date.toISOString().slice(0, 16).replace(/[-:T]/g, '')
}

export async function generateReport(
  request: ReportRequest,
  options: ReportOptions,
  signal?: AbortSignal,
): Promise<ReportResult> {
  const directory = request.directory || (!request.project ? options.locationDirectory : '')
  if (!request.project && !directory) {
    throw new Error('cannot determine the current project; specify the project name or pass --dir')
  }
  if (request.project) requireName(request.project, 'project')
  if (request.directory) requireName(request.directory, '--dir')
  if (request.since) requireTime(request.since, 'since')
  if (request.until) requireTime(request.until, 'until')

  const slugSource = request.project || directory
  const slug = basename(slugSource).replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80) || 'project'
  const stamp = generationStamp()
  const snapshot = resolve(options.outputDir, `${slug}-snapshot-${stamp}.json`)
  const report = resolve(options.outputDir, `${slug}-report-${stamp}.md`)
  const collectArgs = [
    collectScript,
    request.project ? '--project' : '--dir',
    request.project || directory,
    '--out',
    snapshot,
  ]
  if (options.dbPath) collectArgs.push('--db', options.dbPath)
  if (request.since) collectArgs.push('--since', request.since)
  if (request.until) collectArgs.push('--until', request.until)
  if (request.mainOnly) collectArgs.push('--main-only')

  let collectorOutput: string
  try {
    collectorOutput = (
      await run('python3', collectArgs, { cwd: root, timeout: 120_000, signal })
    ).stdout.trim()
  } catch (error) {
    const stderr =
      error && typeof error === 'object' && 'stderr' in error
        ? String((error as { stderr?: unknown }).stderr ?? '')
        : ''
    throw new Error(
      `collector failed: ${stderr.trim() || (error instanceof Error ? error.message : String(error))}`,
    )
  }
  const rendererOutput = (
    await run('python3', [renderScript, snapshot, '--out', report], { cwd: root, timeout: 60_000, signal })
  ).stdout.trim()
  return { snapshot, report, collectorOutput, rendererOutput }
}

function describe(result: ReportResult): string {
  return `${result.collectorOutput}\n${result.rendererOutput}\nReport: ${result.report}\nSnapshot: ${result.snapshot}`
}

export default Plugin.define({
  id: 'opencode-project-time',
  async setup(ctx) {
    const options = (ctx.options ?? {}) as Record<string, unknown>
    const reportOptions: ReportOptions = {
      dbPath: optionString(options.dbPath, ''),
      outputDir: resolve(root, optionString(options.outputDir, 'var')),
      locationDirectory: ctx.location.directory,
    }
    const rawSkill = await readFile(skillPath, 'utf8')
    const skillContent = rawSkill.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '')

    await ctx.skill.transform((editor) => {
      editor.add({
        id: Skill.ID.make('project-time-report'),
        name: Skill.Name.make('Project time report'),
        description:
          'Generate a read-only report of how much time OpenCode agents spent on a project, with execution time, daily breakdown, and session details.',
        autoinvoke: true,
        path: Skill.Info.fields.path.make(skillPath),
        content: skillContent,
      })
    })

    await ctx.tool.transform((editor) => {
      editor.namespace({
        name: 'time',
        description: 'Read-only reports of agent time spent on OpenCode projects',
      })
      editor.add({
        name: 'project_report',
        description:
          'Collect agent timing data for an OpenCode project and write a Markdown report. The source database is opened read-only.',
        input: {
          type: 'object',
          properties: {
            project: {
              type: 'string',
              description:
                'Project name, checkout basename, or OpenCode project id. Omit to use the current project.',
            },
            directory: { type: 'string', description: 'Canonical checkout directory' },
            since: { type: 'string', description: 'ISO-8601 lower bound on session end' },
            until: { type: 'string', description: 'ISO-8601 upper bound on session start' },
            mainOnly: {
              type: 'boolean',
              description: 'Exclude child sessions (all sessions are included by default)',
            },
          },
          additionalProperties: false,
        },
        options: { namespace: 'time', codemode: true },
        execute: async (input, toolContext) => {
          if (toolContext.signal.aborted) throw new Error('aborted')
          const result = await generateReport(input as ReportRequest, reportOptions, toolContext.signal)
          return { content: describe(result) }
        },
      })
    })

    await ctx.command.transform((editor) => {
      editor.add({
        name: 'project-time',
        description: `Generate a read-only agent time report. Usage: ${usage}`,
        execute: async ({ sessionID, prompt }) => {
          try {
            const result = await generateReport(parseCommand(prompt.text), reportOptions)
            await ctx.session.synthetic({ sessionID, text: describe(result) })
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            await ctx.session.synthetic({
              sessionID,
              text: `project-time: ${message}\nUsage: ${usage}`,
            })
          }
        },
      })
    })
  },
})
