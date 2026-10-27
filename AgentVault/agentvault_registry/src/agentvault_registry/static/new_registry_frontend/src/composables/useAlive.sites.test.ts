import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { parse as parseSFC, babelParse } from 'vue/compiler-sfc'

/**
 * §FESUITE (2026-10-03): an async onMounted that starts something after an await checks first that the page is still
 * there. Vue does not wait for an async onMounted: a page left during the await has already run onUnmounted, so a
 * timer, a socket or a window/document listener started after it is never stopped. The console suite's leave sweep
 * (e2e/suite/sweeps/leaving.spec.ts) found 16 views doing it on V0561. The sweep measures the pages a headless browser
 * can drive; this gate reads every component, the WebGL views included, and fails on a new one.
 *
 * - A STARTER is a call to setInterval, an addEventListener on window or document, new WebSocket or new EventSource, or
 *   a call to a function of the same file that makes one (followed to a fixed point).
 * - A CHECK is an `if (...) return` whose condition names the page's liveness: useAlive's `if (!alive()) return`, or a
 *   page's own flag (`closed`, `unmounted`). After the last await before a starter, one must stand between them.
 * - An `if (!data) return` does not count: it checks the answer, not the page.
 */

const SRC = path.resolve(__dirname, '..')
const LIVENESS = /alive|mounted|closed|disposed|destroyed|gone|torn/i

interface Finding { file: string; line: number; what: string }

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (e.name.endsWith('.vue')) out.push(full)
  }
  return out
}

const isFn = (n: any) => n && (n.type === 'ArrowFunctionExpression' || n.type === 'FunctionExpression' || n.type === 'FunctionDeclaration')

/** Every node under `n`, not entering nested functions (their bodies run later, if ever). */
function* nodes(n: any): Generator<any> {
  if (!n || typeof n !== 'object') return
  if (Array.isArray(n)) { for (const x of n) yield* nodes(x); return }
  if (typeof n.type !== 'string') return
  yield n
  for (const k of Object.keys(n)) {
    if (k === 'loc' || k === 'start' || k === 'end' || k === 'leadingComments' || k === 'trailingComments') continue
    const v = n[k]
    if (Array.isArray(v)) { for (const x of v) if (x && typeof x.type === 'string' && !isFn(x)) yield* nodes(x) }
    else if (v && typeof v.type === 'string' && !isFn(v)) yield* nodes(v)
  }
}

/** A starter made right here: what it is, or ''. */
function directStarter(n: any): string {
  if (n.type === 'NewExpression' && n.callee?.type === 'Identifier' && /^(WebSocket|EventSource)$/.test(n.callee.name)) return `new ${n.callee.name}`
  if (n.type !== 'CallExpression') return ''
  const c = n.callee
  if (c?.type === 'Identifier' && c.name === 'setInterval') return 'setInterval'
  if (c?.type === 'MemberExpression' && c.object?.type === 'Identifier' && c.property?.name === 'setInterval' && /^(window|globalThis)$/.test(c.object.name)) return 'setInterval'
  if (c?.type === 'MemberExpression' && c.property?.name === 'addEventListener' && c.object?.type === 'Identifier' && /^(window|document)$/.test(c.object.name)) {
    const ev = n.arguments?.[0]?.type === 'StringLiteral' ? n.arguments[0].value : '?'
    return `${c.object.name}.addEventListener('${ev}')`
  }
  return ''
}

function calledName(n: any): string {
  return n.type === 'CallExpression' && n.callee?.type === 'Identifier' ? n.callee.name : ''
}

/** The file's own functions that start something when called, followed to a fixed point. */
function starterFunctions(program: any): Map<string, string> {
  const bodies = new Map<string, any>()
  for (const s of program.body) {
    const d = s.type === 'ExportNamedDeclaration' ? s.declaration : s
    if (d?.type === 'FunctionDeclaration' && d.id) bodies.set(d.id.name, d.body)
    if (d?.type === 'VariableDeclaration') {
      for (const v of d.declarations) if (v.id?.type === 'Identifier' && isFn(v.init)) bodies.set(v.id.name, v.init.body)
    }
  }
  const starts = new Map<string, string>()
  let grew = true
  while (grew) {
    grew = false
    for (const [name, body] of bodies) {
      if (starts.has(name)) continue
      for (const n of nodes(body)) {
        const what = directStarter(n) || (starts.has(calledName(n)) ? `${calledName(n)}() -> ${starts.get(calledName(n))}` : '')
        if (what) { starts.set(name, what); grew = true; break }
      }
    }
  }
  return starts
}

/** The async functions handed to onMounted (inline, or by the name of one of the file's own). */
function asyncMountHooks(program: any): any[] {
  const named = new Map<string, any>()
  for (const s of program.body) {
    if (s.type === 'FunctionDeclaration' && s.id && s.async) named.set(s.id.name, s)
    if (s.type === 'VariableDeclaration') for (const v of s.declarations) if (v.id?.type === 'Identifier' && isFn(v.init) && v.init.async) named.set(v.id.name, v.init)
  }
  const out: any[] = []
  for (const n of nodes(program)) {
    if (calledName(n) !== 'onMounted') continue
    const a = n.arguments?.[0]
    if (isFn(a) && a.async) out.push(a)
    else if (a?.type === 'Identifier' && named.has(a.name)) out.push(named.get(a.name))
  }
  return out
}

const isCheck = (s: any) => s.type === 'IfStatement' && !s.alternate
  && (s.consequent.type === 'ReturnStatement' || (s.consequent.type === 'BlockStatement' && s.consequent.body.at(-1)?.type === 'ReturnStatement'))
  && [...nodes(s.test)].some((n) => (n.type === 'Identifier' && LIVENESS.test(n.name)) || (n.type === 'MemberExpression' && n.property?.type === 'Identifier' && LIVENESS.test(n.property.name)))

/** Walk a hook's statements in order: an await opens a window, a liveness check closes it, a starter inside it is a finding. */
function scan(hook: any, starts: Map<string, string>, report: (line: number, what: string) => void): void {
  const state = { awaited: false, checked: false }
  const visit = (stmts: any[]) => {
    for (const s of stmts) {
      if (isCheck(s)) { if (state.awaited) state.checked = true; continue }
      const nested: any[][] = []
      if (s.type === 'BlockStatement') nested.push(s.body)
      else if (s.type === 'TryStatement') nested.push(s.block.body, s.handler?.body?.body || [], s.finalizer?.body || [])
      else if (s.type === 'IfStatement') nested.push([s.consequent], s.alternate ? [s.alternate] : [])
      else if (/^(For|ForIn|ForOf|While|DoWhile)Statement$/.test(s.type)) nested.push([s.body])
      if (nested.length) {
        // the test of an if or a loop runs first; its await counts before the branches
        if (s.test && [...nodes(s.test)].some((n) => n.type === 'AwaitExpression')) { state.awaited = true; state.checked = false }
        for (const b of nested) visit(b)
        continue
      }
      for (const n of nodes(s)) {
        const what = directStarter(n) || (starts.has(calledName(n)) ? `${calledName(n)}() -> ${starts.get(calledName(n))}` : '')
        if (what && state.awaited && !state.checked) report(n.loc.start.line, what)
      }
      if ([...nodes(s)].some((n) => n.type === 'AwaitExpression')) { state.awaited = true; state.checked = false }
    }
  }
  visit(hook.body.type === 'BlockStatement' ? hook.body.body : [{ type: 'ExpressionStatement', expression: hook.body }])
}

function findings(file: string, source: string): Finding[] {
  const { descriptor } = parseSFC(source, { filename: file })
  const out: Finding[] = []
  for (const block of [descriptor.script, descriptor.scriptSetup]) {
    if (!block) continue
    const program = (babelParse(block.content, { sourceType: 'module', plugins: ['typescript'] }) as any).program
    const starts = starterFunctions(program)
    for (const hook of asyncMountHooks(program)) {
      scan(hook, starts, (line, what) => out.push({ file, line: block.loc.start.line - 1 + line, what }))
    }
  }
  return out
}

const sfc = (setup: string) => `<script setup lang="ts">\n${setup}\n</script>\n<template><div /></template>\n`

describe('an async onMounted checks the page is still there before it starts anything', () => {
  it('controls: what it must find, and what it must not', () => {
    const found = (setup: string) => findings('control.vue', sfc(setup)).map((f) => f.what)
    expect(found('onMounted(async () => { await load(); timer = setInterval(load, 1000) })')).toEqual(['setInterval'])
    expect(found('const alive = useAlive()\nonMounted(async () => { await load(); if (!alive()) return; timer = setInterval(load, 1000) })')).toEqual([])
    expect(found('function start() { t = setInterval(f, 1000) }\nonMounted(async () => { await load(); start() })')).toEqual(['start() -> setInterval'])
    expect(found("onMounted(async () => { try { await load() } catch {} ; window.addEventListener('resize', f) })")).toEqual(["window.addEventListener('resize')"])
    expect(found('onMounted(async () => { const r = await load(); if (!r) return; t = setInterval(f, 1) })')).toEqual(['setInterval'])
    expect(found('async function init() { await load(); ws = new WebSocket(u) }\nonMounted(init)')).toEqual(['new WebSocket'])
    expect(found('onMounted(async () => { t = setInterval(f, 1); await load() })')).toEqual([])
    expect(found('onMounted(async () => { await load(); if (closed) return; t = setInterval(f, 1) })')).toEqual([])
    expect(found('onMounted(async () => { await a(); if (!alive()) return; await b(); t = setInterval(f, 1) })')).toEqual(['setInterval'])
  })

  it('the console: no view or component starts a timer, a socket or a listener after an await without the check', () => {
    const all = walk(SRC).flatMap((f) => findings(path.relative(SRC, f), fs.readFileSync(f, 'utf8')))
    expect(all.map((f) => `${f.file}:${f.line} ${f.what}`)).toEqual([])
  }, 60_000) // ~4 s alone (every component parsed); the release build runs it beside 140 other files
})
