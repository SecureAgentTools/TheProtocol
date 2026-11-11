import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0658 (v): the small texts the Firms surfaces gained hold at least 4.5:1 (WCAG AA, normal text) on the backgrounds
 * the console proof measured for the strip (#0f121b, the lightest page background, with the strip card's 2% white over
 * it), the way contrast.v0657.test.ts reads a rule's declared colour: the line labels and the placeholder logo mark in
 * the strip, the line Discovery shows when the strip is hidden, and the firm reservation in Pocket's post sheet.
 * The review of 4914af776 added the two texts #/firms gained, the agents' line on a directory card and the records
 * panel's subtitle: both were faded by `opacity` over an inherited colour, the class the proof's axe gate fails, and a
 * rule's declared `opacity` now folds into the colour it is read at (RED there: neither rule declares a colour).
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
  // a declared opacity fades the text as much as an alpha does: it is part of the colour the text is read at
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

const PAGE = hexRgb('#0f121b')
const CARD = over({ rgb: [255, 255, 255], a: 0.02 }, PAGE)

describe('the Firms surfaces\' new small texts read at least 4.5:1', () => {
  it('the strip: the two lines\' labels and the placeholder logo mark, on the card', () => {
    const lane = read('components/discovery/FirmsLane.vue')
    for (const sel of ['.fl-label', '.fl-logo-mark']) {
      expect(ratio(over(declared(lane, sel), CARD), CARD), sel).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('Discovery\'s line for a hidden strip, on the page', () => {
    const fg = declared(read('views/Discovery.vue'), '.disc-firms-hidden')
    expect(ratio(over(fg, PAGE), PAGE)).toBeGreaterThanOrEqual(4.5)
  })

  it('the firm reservation in Pocket\'s post sheet', () => {
    const fg = declared(read('views/pocket/PocketEarn.vue'), '.pe-firm-reserved')
    expect(ratio(over(fg, PAGE), PAGE)).toBeGreaterThanOrEqual(4.5)
  })

  it('#/firms: the agents\' line on a directory card, on the page', () => {
    const fg = declared(read('components/organizations/OrgDirectory.vue'), ':deep(.odir__members)')
    expect(ratio(over(fg, PAGE), PAGE)).toBeGreaterThanOrEqual(4.5)
  })

  it('#/firms: the records panel\'s subtitle, on the panel', () => {
    const panel = over({ rgb: [128, 128, 128], a: 0.03 }, PAGE)
    const fg = declared(read('views/PublicFirms.vue'), '.pfw-panel-sub')
    expect(ratio(over(fg, panel), panel)).toBeGreaterThanOrEqual(4.5)
  })

  it('reads a declared opacity as part of the colour (a control)', () => {
    const faded = declared('.x { color: rgba(148, 163, 184, 0.85); opacity: .5; }', '.x')
    expect(faded.a).toBeCloseTo(0.425, 3)
    expect(ratio(over(faded, PAGE), PAGE)).toBeLessThan(4.5)
    expect(declared('.y { color: #ffffff; }', '.y').a).toBe(1)
  })
})
