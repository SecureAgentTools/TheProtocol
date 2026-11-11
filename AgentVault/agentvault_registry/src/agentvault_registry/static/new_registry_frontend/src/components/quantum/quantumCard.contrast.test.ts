import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0660 (e): the quantum card passes the console's contrast gate (4.5:1, WCAG AA for normal text) and honours reduced
 * motion. Every text the card and its filters draw declares its colour; each is read the way contrast.v0657.test.ts
 * reads one (a declared opacity folds into the colour) against the card's own opaque ground (#0a0e1a, with the faint
 * light wash at its brightest) and the filter rail's page (#0f121b with the filter card's 2% white). The refracting
 * edges (the card's frame and the discovery card's ring) stand still under prefers-reduced-motion.
 */

const SRC = path.resolve(__dirname, '../..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]
function declared(css: string, selector: string): { rgb: RGB; a: number } {
  const at = css.indexOf(`${selector} {`)
  if (at < 0) throw new Error(`no rule for ${selector}`)
  const block = css.slice(at, css.indexOf('}', at))
  const m = block.match(/(?:^|[\s;{])color:\s*([^;]+);/)
  if (!m) throw new Error(`${selector} declares no colour`)
  const v = m[1].trim()
  const op = block.match(/(?:^|[\s;{])opacity:\s*([\d.]+)\s*(?:;|$)/)
  const fade = op ? Number(op[1]) : 1
  const hex = v.match(/^#([0-9a-f]{6})$/i)
  if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as RGB, a: fade }
  const rgba = v.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
  if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: (rgba[4] === undefined ? 1 : Number(rgba[4])) * fade }
  throw new Error(`a colour this test does not read: ${v}`)
}
const hexRgb = (h: string): RGB => [0, 2, 4].map((i) => parseInt(h.slice(1 + i, 3 + i), 16)) as RGB
const over = (fg: { rgb: RGB; a: number }, bg: RGB): RGB => fg.rgb.map((c, i) => Math.round(fg.a * c + (1 - fg.a) * bg[i])) as RGB
function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
function ratio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const card = read('components/quantum/QuantumCard.vue')
const filters = read('components/quantum/QuantumFilters.vue')
const lattice = read('components/quantum/QuantumLattice.vue')
const discovery = read('views/Discovery.vue')

// the card's ground at its brightest: the wash (rgba(127, 216, 240, 0.06)) and a corner facet (rgba(243, 239, 228, 0.08))
// over #0a0e1a
const GROUND = over({ rgb: [243, 239, 228], a: 0.08 }, over({ rgb: [127, 216, 240], a: 0.06 }, hexRgb('#0a0e1a')))
const PAGE = hexRgb('#0f121b')
const RAIL = over({ rgb: [255, 255, 255], a: 0.02 }, PAGE)

describe('the quantum card\'s texts read at least 4.5:1 on its own ground', () => {
  const sels = ['.qc', '.qc-eyebrow', '.qc-ver', '.qc-check--ok', '.qc-check--bad', '.qc-check--unread', '.qc-roles',
    '.qc-summary-item', '.qc-tab', '.qc-tab--on', '.qc-note', '.qc-latt-name', '.qc-digest', '.qc-more', '.qc-label',
    '.qc-value', '.qc-age', '.qc-h', '.qc-rung-n', '.qc-rung-name', '.qc-rung-state--settles_here',
    '.qc-rung-state--offered', '.qc-rung-state--claims_only', '.qc-test', '.qc-code', '.qc-test-rate', '.qc-line']
  for (const sel of sels) {
    it(sel, () => { expect(ratio(over(declared(card, sel), GROUND), GROUND), sel).toBeGreaterThanOrEqual(4.5) })
  }
  it('the ground is opaque, so the page behind it cannot lower a ratio', () => {
    expect(card).toMatch(/\.qc--framed > \.qc-in \{[^}]*background-color: #0a0e1a;/)
    expect(discovery).toMatch(/linear-gradient\(#0a0e1a, #0a0e1a\) padding-box/)
  })
})

describe('the quantum filters\' texts read at least 4.5:1 on the filter rail', () => {
  for (const sel of ['.qf-h', '.qf-count', '.qf-row', '.qf-label']) {
    it(sel, () => { expect(ratio(over(declared(filters, sel), RAIL), RAIL), sel).toBeGreaterThanOrEqual(4.5) })
  }
  it('.qf-select, on its own ground', () => {
    expect(ratio(over(declared(filters, '.qf-select'), hexRgb('#0a0e1a')), hexRgb('#0a0e1a'))).toBeGreaterThanOrEqual(4.5)
  })
})

describe('reduced motion', () => {
  /** some reduced-motion block names the selector and sets its animation to none */
  const stillUnderReduce = (css: string, sel: string) => {
    const blocks: string[] = []
    for (let at = css.indexOf('@media (prefers-reduced-motion: reduce)'); at >= 0;
      at = css.indexOf('@media (prefers-reduced-motion: reduce)', at + 1)) {
      blocks.push(css.slice(at, css.indexOf('}\n}', at) + 3))
    }
    expect(blocks.some((b) => b.includes(sel) && /animation:\s*none/.test(b)), `${sel} under reduced motion`).toBe(true)
  }
  it('the card\'s refracting frame stands still', () => {
    expect(card).toMatch(/\.qc--framed \{[^}]*animation: qc-refract/)
    stillUnderReduce(card, '.qc--framed')
  })
  it('the discovery card\'s prism ring stands still', () => {
    expect(discovery).toMatch(/animation: disc-q-refract/)
    stillUnderReduce(discovery, '.disc-agent-card--quantum')
  })
  it('the lattice draws no animation at all', () => {
    expect(lattice).not.toMatch(/animation|@keyframes|<animate/)
  })
})

describe('custom glyphs only', () => {
  it('no stock icon: the card, the lattice and the filters draw their own marks and use no Icon name', () => {
    for (const src of [card, lattice, filters]) {
      expect(src).not.toMatch(/<Icon\b/)
      expect(src).not.toMatch(/mdi:/)
    }
  })
})
