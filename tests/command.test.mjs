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
  const candidates = [
    process.env.TS_MODULE,
    'typescript',
    '/home/brooks/projects/business/EunomiaSync/node_modules/typescript',
  ].filter(Boolean)
  for (const candidate of candidates) {
    try {
      return require(candidate)
    } catch {
      continue
    }
  }
  throw new Error('typescript is required to run the plugin command tests')
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
  return { tmp, pluginFile, calls, bin }
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
    assert.throws(() => parseCommand('--bogus'), /unknown argument.*Usage/)
    assert.throws(() => parseCommand('--since'), /ISO-8601/)
    assert.throws(() => parseCommand('--since tomorrow'), /ISO-8601/)
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
    assert.ok(stamp, `report name must carry a YYYYMMDDHHII stamp: ${result.report}`)
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
