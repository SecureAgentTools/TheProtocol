import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0657 recut: the console proof's a11y check (axe, color-contrast) measured two texts under 4.5:1 on sbx-beta
 * (fes-20261107T085224Z-70e6):
 *  - the saga state label of a settlement on #/admin/settlements, #924bd7 on #131224 = 3.69:1;
 *  - the logo upload button on the organization page, #5a6779 on #141d2d = 2.93:1.
 * Each rule's colour, laid over the background axe measured under it, must read at least 4.5:1 (WCAG AA, normal text).
 * Red on v0657/cut.
 */

const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]

/** The colour a rule declares for `selector` (its first `color:`), as RGB and alpha. */
function declared(css: string, selector: string): { rgb: RGB; a: number } | null {
  const at = css.indexOf(`${selector} {`)
  if (at < 0) return null
  const block = css.slice(at, css.indexOf('}', at))
  const m = block.match(/(?:^|[\s;{])color:\s*([^;]+);/)
  if (!m) return null
  const v = m[1].trim()
  const hex = v.match(/^#([0-9a-f]{6})$/i)
  if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as RGB, a: 1 }
  const rgba = v.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
  if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: rgba[4] === undefined ? 1 : Number(rgba[4]) }
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

describe('the two texts the console proof measured under 4.5:1 now read at least 4.5:1', () => {
  it('the saga state label on the admin settlements view', () => {
    const fg = declared(read('views/AdminSettlements.vue'), '.as-feed-saga')
    expect(fg, 'the label declares its colour').not.toBeNull()
    expect(ratio(over(fg!, hexRgb('#131224')), hexRgb('#131224'))).toBeGreaterThanOrEqual(4.5)
  })

  it('the logo upload button on the organization page', () => {
    // the button's own rule when the page sets one, else the shared ghost button's
    const own = declared(read('components/organizations/OrgPublicFace.vue'), '.opf__btn.tp-btn--ghost')
    const fg = own ?? declared(read('components/organizations/tp-modal-shared.css'), '.tp-btn--ghost')
    expect(fg).not.toBeNull()
    expect(ratio(over(fg!, hexRgb('#141d2d')), hexRgb('#141d2d'))).toBeGreaterThanOrEqual(4.5)
  })

  it('reads the measured pairs the way axe did (a control)', () => {
    expect(ratio(hexRgb('#924bd7'), hexRgb('#131224'))).toBeCloseTo(3.69, 1)
    expect(ratio(hexRgb('#5a6779'), hexRgb('#141d2d'))).toBeCloseTo(2.93, 1)
  })
})
