import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0663 (three contrast fixes, gwo_c642bc11a0c8bc303d35bd29, from the V0662 console proof, room seq 3486): the colours that
 * proof's axe run found too faint on three empty and unadmitted states read at least 4.5:1 (WCAG AA, normal text) on the
 * backgrounds axe measured them on: attestation analytics `.aa-empty-sub` and treasury `.at-empty-mini` (#6c6e73 on #0a0d16,
 * 3.8:1: white at 40% opacity) and compliance `.cm-tile-unadmitted` (#8f9399 on #2a2f3e, 4.31:1, three tiles).
 * The fix goes through the theme's variables, as the admin contrast did, and changes none of them: `--nc-text-muted` is
 * used by the whole console and stays as it is.
 * BASE: every check below fails on b27f2ebaf's colours.
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
  '--nc-text-secondary': declared(THEME, '--nc-text-secondary'),
  '--nc-border': declared(THEME, '--nc-border'),
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

describe('the empty and unadmitted states read at least 4.5:1 where axe measured them too faint', () => {
  it('attestation analytics: the "Available circuits" line of an empty panel (#0a0d16)', () => {
    const fg = colour(ruleColor('views/AdminAttestationAnalytics.vue', '.aa-empty-sub'), surface('#0a0d16'))
    expect(ratio(fg, surface('#0a0d16'))).toBeGreaterThanOrEqual(AA)
  })
  it('treasury: the "no mints in this window" lines (#0a0d16)', () => {
    const fg = colour(ruleColor('views/AdminTreasury.vue', '.at-empty-mini'), surface('#0a0d16'))
    expect(ratio(fg, surface('#0a0d16'))).toBeGreaterThanOrEqual(AA)
  })
  it('compliance: the NOT ADMITTED pill on its own background (the theme border, #2a2f3e)', () => {
    const bg = colour(ruleColor('views/ComplianceMonitor.vue', '.cm-tile-unadmitted', 'background'), surface('#131825'))
    const fg = colour(ruleColor('views/ComplianceMonitor.vue', '.cm-tile-unadmitted'), bg)
    expect(ratio(fg, bg)).toBeGreaterThanOrEqual(AA)
  })
  it('the shared muted colour is not the way out: it stays the theme value the whole console reads', () => {
    expect(declared(THEME, '--nc-text-muted')).toBe('#8f9399')
  })
})
