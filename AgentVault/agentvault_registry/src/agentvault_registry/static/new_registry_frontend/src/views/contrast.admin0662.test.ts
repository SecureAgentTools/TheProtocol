import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0662 (the admin contrast, gwo_06f503c2b7b0dda7e22e9bd2): the colours a 30-rule axe run found too faint on seven admin
 * pages read at least 4.5:1 (WCAG AA, normal text) on the backgrounds axe measured them on (V0661's console on sbx-alpha,
 * 2026-11-13: admin-cicd 4.12 and 3.42 and 4.48, admin-agents 3.78, evals 3.31, fiat-ops 4.05, health monitor 4.49), and
 * the page-level findings that rode with them (a table header with no text, a checkbox named only by `title`, a link told
 * apart by colour alone, a scrolling list a keyboard cannot reach, a heading level skipped) stay fixed.
 * BASE: every contrast check below fails on f569f6a6e's colours; the structure checks fail on the old markup.
 */
const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]
const hex = (v: string): RGB => [0, 2, 4].map((i) => parseInt(v.slice(1 + i, 3 + i), 16)) as RGB
const luminance = ([r, g, b]: RGB): number => {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
const ratio = (a: RGB, b: RGB): number => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** First declaration of a custom property in a stylesheet or a style block. */
function declared(text: string, name: string): string {
  const m = text.match(new RegExp(`${name}\\s*:\\s*([^;]+);`))
  if (!m) throw new Error(`${name} is not declared`)
  return m[1].replace(/\/\*.*?\*\//g, '').trim()
}
const THEME = read('assets/styles/neural-command.css')
const VARS: Record<string, string> = {
  '--nc-text-muted': declared(THEME, '--nc-text-muted'),
  '--nc-primary-rgb': declared(THEME, '--nc-primary-rgb'),
}

/** The colours these rules use: hex, rgb(), rgba(r, g, b, a) over the surface, var(--x, fallback), and color-mix(in srgb, A p%, #fff). */
function colour(expr: string, surface: RGB, vars: Record<string, string> = {}): RGB {
  const v = expr.trim().replace(/\/\*.*?\*\//g, '').trim()
  const all = { ...VARS, ...vars }
  const viaVar = v.match(/^var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)$/)
  if (viaVar) {
    const value = all[viaVar[1]] ?? viaVar[2]
    if (value === undefined) throw new Error(`${viaVar[1]} resolves to nothing`)
    return colour(value, surface, vars)
  }
  if (/^#[0-9a-f]{6}$/i.test(v)) return hex(v)
  const mix = v.match(/^color-mix\(\s*in srgb\s*,\s*(.+?)\s+(\d+)%\s*,\s*#fff\s*\)$/i)
  if (mix) {
    const base = colour(mix[1], surface, vars)
    const p = Number(mix[2]) / 100
    return base.map((c) => Math.round(p * c + (1 - p) * 255)) as RGB
  }
  const rgba = v.replace(/var\(\s*(--[\w-]+)\s*\)/g, (_, n: string) => all[n]).match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
  if (rgba) {
    const a = rgba[4] === undefined ? 1 : Number(rgba[4])
    return [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])].map((c, i) => Math.round(a * c + (1 - a) * surface[i])) as RGB
  }
  throw new Error(`a colour this test does not read: ${expr}`)
}

/** The declaration `prop: value;` inside the rule whose selector is exactly `selector`. */
function ruleColor(file: string, selector: string, property = 'color'): string {
  const css = read(file)
  const found = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{`).exec(css)
  expect(found, `${selector} declares its own rule in ${file}`).not.toBeNull()
  const at = found!.index
  const block = css.slice(at, css.indexOf('}', at))
  const m = block.match(new RegExp(`(?:^|[\\s;{])${property}:\\s*([^;]+);`))
  expect(m, `${selector} declares ${property}`).not.toBeNull()
  return m![1].trim()
}
const AA = 4.5
const surface = (v: string): RGB => hex(v)

describe('the admin pages read at least 4.5:1 where axe measured them too faint', () => {
  const cicd = { '--muted': declared(read('views/AdminCICD.vue'), '--muted'), '--red': declared(read('views/AdminCICD.vue'), '--red') }
  it('CI/CD: the muted "10 days ago" cells (#0a121b)', () => {
    const fg = colour(ruleColor('views/AdminCICD.vue', '.ac-muted'), surface('#0a121b'), cicd)
    expect(ratio(fg, surface('#0a121b'))).toBeGreaterThanOrEqual(AA)
  })
  it('CI/CD: the grey "cancelled" pill (#1e242b)', () => {
    const fg = colour(ruleColor('views/AdminCICD.vue', '.ac-st-cancelled'), surface('#1e242b'), cicd)
    expect(ratio(fg, surface('#1e242b'))).toBeGreaterThanOrEqual(AA)
  })
  it('CI/CD: the red "failed" pill (#361828)', () => {
    const fg = colour(ruleColor('views/AdminCICD.vue', '.ac-st-failed'), surface('#361828'), cicd)
    expect(ratio(fg, surface('#361828'))).toBeGreaterThanOrEqual(AA)
  })
  it('agents: the table headers (#0f1628), and no text on this page keeps the old slate #64748b', () => {
    const fg = colour(ruleColor('views/AdminAgents.vue', '.aa-table thead th'), surface('#0f1628'))
    expect(ratio(fg, surface('#0f1628'))).toBeGreaterThanOrEqual(AA)
    expect(read('views/AdminAgents.vue')).not.toContain('#64748b')
  })
  it('evals: the muted key cells (#0a111a)', () => {
    const fg = colour(ruleColor('views/AdminEvals.vue', '.ae-muted'), surface('#0a111a'))
    expect(ratio(fg, surface('#0a111a'))).toBeGreaterThanOrEqual(AA)
  })
  it('fiat-ops: the red "failed" status pill (#341f2a)', () => {
    const fg = colour(ruleColor('views/AdminFiatOps.vue', '.afo-pill-status-failed'), surface('#341f2a'))
    expect(ratio(fg, surface('#341f2a'))).toBeGreaterThanOrEqual(AA)
  })
  it('health monitor: the endpoint paths on the lightest service card (#102233)', () => {
    const dim = declared(read('components/healthMonitor/tp-healthmonitor.css'), '--hm-text-dim')
    expect(ratio(colour(dim, surface('#102233')), surface('#102233'))).toBeGreaterThanOrEqual(AA)
  })
})

describe('the findings that rode with them stay fixed', () => {
  it('CI/CD and evals: the last table header, which holds only a marker or buttons, has text for a screen reader', () => {
    expect(read('views/AdminCICD.vue')).toContain('<th><span class="sr-only">Organization</span></th>')
    expect(read('views/AdminEvals.vue')).toContain('<th><span class="sr-only">Actions</span></th>')
  })
  it('agents: the select checkboxes are named by aria-label, not by title alone', () => {
    const src = read('views/AdminAgents.vue')
    expect(src).toContain(":aria-label=\"allVisibleSelected ? 'Deselect all visible' : 'Select all visible'\"")
    expect(src).toContain(':aria-label="`Select ${a.name || a.did}`"')
  })
  it('emission policy: the in-text link is underlined, not told apart by colour alone', () => {
    expect(ruleColor('views/AdminEmissionPolicy.vue', '.ep-link', 'text-decoration')).toBe('underline')
  })
  it('canaries: the failures list a keyboard can scroll is a named, focusable region, and the cards sit under a heading level 2', () => {
    const src = read('views/AdminCanaries.vue')
    expect(src).toContain('<div class="cn-failures-list" tabindex="0" role="region" aria-label="Recent failures">')
    expect(src).toContain('<h2 class="sr-only">Canary paths</h2>')
  })
})
