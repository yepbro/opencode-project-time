import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import test from 'node:test'

const require = createRequire(import.meta.url)
const projectRoot = path.resolve(import.meta.dirname, '..')

function loadTypescript() {
  try {
    return require(process.env.TS_MODULE || 'typescript')
  } catch {
    throw new Error('typescript is required; run npm install in the project root')
  }
}

function makeHarness() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'opt-command-'))
  const stubPackage = path.join(tmp, 'node_modules', '@opencode', 'plugin')
  fs.mkdirSync(stubPackage, { recursive: true })
  fs.writeFileSync(
    path.join(stubPackage, 'package.json'),
    JSON.stringify({ name: '@opencode/plugin', type: 'module', exports: { '.': './index.js' } }),
  )
  fs.writeFileSync(
    path.join(stubPackage, 'index.js'),
    [
      'export const Plugin = { define: (value) => value }',
      'export const Skill = { ID: { make: (v) => v }, Name: { make: (v) => v },',
      '  Info: { fields: { path: { make: (v) => v } } } }',
    ].join('\n'),
  )
  const ts = loadTypescript()
  const source = fs.readFileSync(path.join(projectRoot, 'src', 'index.ts'), 'utf8')
  const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const pluginFile = path.join(tmp, 'src', 'plugin.mjs')
  fs.mkdirSync(path.dirname(pluginFile), { recursive: true })
  fs.writeFileSync(pluginFile, javascript)

  const bin = path.join(tmp, 'bin')
  fs.mkdirSync(bin)
  const calls = path.join(tmp, 'calls.txt')
  const pythonStub = path.join(bin, 'python3')
  fs.writeFileSync(
    pythonStub,
    [
      '#!/bin/sh',
      `echo "$*" >> "${calls}"`,
      'out=""',
      'prev=""',
      'for arg in "$@"; do',
      '  if [ "$prev" = "--out" ]; then out="$arg"; fi',
      '  prev="$arg"',
      'done',
      'case "$1" in',
      '  *collect.py*) printf \'{"schema_version":1}\\n\' > "$out" ;;',
      '  *report.py*) printf \'# stub report\\n\' > "$out" ;;',
      'esac',
      'echo "wrote $out"',
    ].join('\n'),
  )
  fs.chmodSync(pythonStub, 0o755)
  const skillDir = path.join(tmp, 'skill')
  fs.mkdirSync(skillDir, { recursive: true })
  fs.writeFileSync(
    path.join(skillDir, 'SKILL.md'),
    '---\nname: X\ndescription: Y\n---\n\n# Body\n',
  )
  return { tmp, pluginFile, calls, bin, skillDir }
}

async function importPlugin(pluginFile) {
  return import(`${pathToFileURL(pluginFile).href}?t=${Date.now()}`)
}

test('parseCommand maps arguments to report parameters', async () => {
  const harness = makeHarness()
  try {
    const { parseCommand } = await importPlugin(harness.pluginFile)
    assert.deepEqual(parseCommand(''), {})
    assert.deepEqual(
      parseCommand('EunomiaSync --since 2026-01-01T00:00:00Z --until 2026-01-02T00:00:00Z --main-only'),
      {
        project: 'EunomiaSync',
        since: '2026-01-01T00:00:00Z',
        until: '2026-01-02T00:00:00Z',
        mainOnly: true,
      },
    )
    assert.deepEqual(parseCommand('--dir /work/eunomia --project p1'), {
      project: 'p1',
      directory: '/work/eunomia',
    })
    assert.deepEqual(parseCommand('--dir "/home/brooks/Documents/Default Project"'), {
      directory: '/home/brooks/Documents/Default Project',
    })
    assert.deepEqual(parseCommand('"Default Project"'), { project: 'Default Project' })
    assert.throws(() => parseCommand('--bogus'), /unknown argument.*Usage/)
    assert.throws(() => parseCommand('--since'), /ISO-8601/)
    assert.throws(() => parseCommand('--since tomorrow'), /ISO-8601/)
    assert.throws(() => parseCommand('--project --main-only'), /--project/)
    assert.throws(() => parseCommand('--dir --since 2026-01-01T00:00:00Z'), /--dir/)
  } finally {
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})

test('generateReport uses parsed arguments and writes both files', async () => {
  const harness = makeHarness()
  const originalPath = process.env.PATH
  try {
    process.env.PATH = `${harness.bin}${path.delimiter}${originalPath}`
    const { generateReport } = await importPlugin(harness.pluginFile)
    const outDir = path.join(harness.tmp, 'var')
    fs.mkdirSync(outDir, { recursive: true })
    const result = await generateReport(
      { project: 'EunomiaSync', since: '2026-01-01T00:00:00Z', mainOnly: true },
      { dbPath: '/fake/opencode.db', outputDir: outDir, locationDirectory: '/ignored' },
    )
    const stamp = result.report.match(/EunomiaSync-report-(\d{12})\.md$/)?.[1]
    assert.ok(stamp, `report name must carry a YYYYMMDDHHMM stamp: ${result.report}`)
    assert.equal(result.report, path.join(outDir, `EunomiaSync-report-${stamp}.md`))
    assert.equal(result.snapshot, path.join(outDir, `EunomiaSync-snapshot-${stamp}.json`))
    assert.match(result.collectorOutput, /wrote/)
    assert.ok(fs.existsSync(result.report))
    assert.ok(fs.existsSync(result.snapshot))
    const calls = fs.readFileSync(harness.calls, 'utf8').trim().split('\n')
    assert.equal(calls.length, 2)
    assert.match(calls[0], /--project EunomiaSync/)
    assert.match(calls[0], /--db \/fake\/opencode\.db/)
    assert.match(calls[0], /--since 2026-01-01T00:00:00Z/)
    assert.match(calls[0], /--main-only/)
    assert.match(calls[1], /report\.py/)
  } finally {
    process.env.PATH = originalPath
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})

test('generateReport falls back to the plugin location directory', async () => {
  const harness = makeHarness()
  const originalPath = process.env.PATH
  try {
    process.env.PATH = `${harness.bin}${path.delimiter}${originalPath}`
    const { generateReport } = await importPlugin(harness.pluginFile)
    const outDir = path.join(harness.tmp, 'var')
    fs.mkdirSync(outDir, { recursive: true })
    const result = await generateReport(
      {},
      { dbPath: '', outputDir: outDir, locationDirectory: '/work/eunomia' },
    )
    assert.match(result.report, /eunomia-report-\d{12}\.md$/)
    assert.equal(
      result.snapshot,
      result.report.replace('-report-', '-snapshot-').replace(/\.md$/, '.json'),
    )
    const call = fs.readFileSync(harness.calls, 'utf8').trim()
    assert.match(call, /--dir \/work\/eunomia/)
  } finally {
    process.env.PATH = originalPath
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})

test('generateReport forwards both project and directory when given', async () => {
  const harness = makeHarness()
  const originalPath = process.env.PATH
  try {
    process.env.PATH = `${harness.bin}${path.delimiter}${originalPath}`
    const { generateReport } = await importPlugin(harness.pluginFile)
    const outDir = path.join(harness.tmp, 'var')
    fs.mkdirSync(outDir, { recursive: true })
    await generateReport(
      { project: 'p1', directory: '/work/eunomia' },
      { dbPath: '', outputDir: outDir, locationDirectory: '/ignored' },
    )
    const call = fs.readFileSync(harness.calls, 'utf8').trim().split('\n')[0]
    assert.match(call, /--project p1/)
    assert.match(call, /--dir \/work\/eunomia/)
  } finally {
    process.env.PATH = originalPath
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})

test('setup registers a skill without duplicated frontmatter', async () => {
  const harness = makeHarness()
  try {
    const plugin = await importPlugin(harness.pluginFile)
    let skill
    let tool
    let command
    let namespace
    const skillEditor = { add: (definition) => { skill = definition } }
    const toolEditor = {
      add: (definition) => { tool = definition },
      namespace: (value) => { namespace = value },
    }
    const commandEditor = { add: (definition) => { command = definition } }
    const ctx = {
      options: {},
      location: { directory: '/work/eunomia' },
      skill: { transform: async (fn) => fn(skillEditor) },
      tool: { transform: async (fn) => fn(toolEditor) },
      command: { transform: async (fn) => fn(commandEditor) },
      session: { synthetic: async () => {} },
    }
    await plugin.default.setup(ctx)
    assert.ok(skill, 'skill must be registered')
    assert.equal(skill.autoinvoke, true)
    assert.doesNotMatch(skill.content, /^---/)
    assert.match(skill.content, /# Body/)
    assert.deepEqual(namespace, { name: 'time', description: 'Read-only reports of agent time spent on OpenCode projects' })
    assert.equal(tool.name, 'project_report')
    assert.deepEqual(tool.options, { namespace: 'time', codemode: true })
    assert.equal(command.name, 'project-time')
    assert.match(command.description, /agent time report/)
  } finally {
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})

test('command executor posts a synthetic result and handles usage errors', async () => {
  const harness = makeHarness()
  const originalPath = process.env.PATH
  try {
    process.env.PATH = `${harness.bin}${path.delimiter}${originalPath}`
    const plugin = await importPlugin(harness.pluginFile)
    let command
    const messages = []
    const ctx = {
      options: {},
      location: { directory: '/work/eunomia' },
      skill: { transform: async () => {} },
      tool: { transform: async () => {} },
      command: { transform: async (fn) => fn({ add: (d) => { command = d } }) },
      session: { synthetic: async ({ text }) => { messages.push(text) } },
    }
    await plugin.default.setup(ctx)
    await command.execute({ sessionID: 's1', prompt: { text: '--bogus' } })
    assert.match(messages[0], /^project-time:/)
    assert.match(messages[0], /Usage:/)
    await command.execute({ sessionID: 's1', prompt: { text: 'p1' } })
    assert.match(messages[1], /Report:/)
    assert.match(messages[1], /Snapshot:/)
  } finally {
    process.env.PATH = originalPath
    fs.rmSync(harness.tmp, { recursive: true, force: true })
  }
})
