import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0658 (q): the owner's new texts (the Guild board's owner line and party chips, Pocket's owner line in the order sheet)
 * read at least 4.5:1 (WCAG AA, normal text) on the backgrounds they sit on, and none of them is faded with opacity (the
 * console proof's axe check measures the composited colour). The panel under the board's texts is taken as #141d2d, the
 * lighter of the dark panels axe measured in V0657 (contrast.v0657.test.ts), so the check is the strict one.
 * BASE: none of these rules exists.
 */
const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]
type Paint = { rgb: RGB; a: number }

function rule(css: string, selector: string): string | null {
  const at = css.indexOf(`${selector} {`)
  return at < 0 ? null : css.slice(at, css.indexOf('}', at))
}
function paint(v: string): Paint {
  const hex = v.match(/^#([0-9a-f]{6})$/i)
  if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as RGB, a: 1 }
  const rgba = v.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
  if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: rgba[4] === undefined ? 1 : Number(rgba[4]) }
  throw new Error(`a colour this test does not read: ${v}`)
}
function prop(block: string, name: string): string | null {
  const m = block.match(new RegExp(`(?:^|[\\s;{])${name}:\\s*([^;]+);`))
  return m ? m[1].trim() : null
}
const over = (fg: Paint, bg: RGB): RGB => fg.rgb.map((c, i) => Math.round(fg.a * c + (1 - fg.a) * bg[i])) as RGB
function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
function ratio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const PANEL: RGB = [0x14, 0x1d, 0x2d]

function check(file: string, selector: string, under: RGB) {
  const block = rule(read(file), selector)
  expect(block, `${selector} declares its own rule`).not.toBeNull()
  const color = prop(block!, 'color')
  expect(color, `${selector} declares its colour`).not.toBeNull()
  const opacity = prop(block!, 'opacity')
  expect(opacity === null || Number(opacity) === 1, `${selector} is not faded`).toBe(true)
  const bgDecl = prop(block!, 'background')
  const bg = bgDecl ? over(paint(bgDecl), under) : under
  expect(ratio(over(paint(color!), bg), bg)).toBeGreaterThanOrEqual(4.5)
}

describe("the owner's texts read at least 4.5:1", () => {
  it("the Guild board's owner line", () => check('views/GuildBoard.vue', '.gld-owner', PANEL))
  it("the Guild board's party chips in My work", () => check('views/GuildBoard.vue', '.gld-mine-chip', PANEL))
  it("Pocket's owner line on the order sheet (#0c0f15)", () =>
    check('views/pocket/PocketEarn.vue', '.pe-ord-note.pe-ord-owner', [0x0c, 0x0f, 0x15]))
})
