import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0659 (o), session-code's review: the "your agent" mark in the thread the console and Pocket both mount
 * (PocketOurStateThread.vue, `.ost-my-agent`) is small text (.62rem), so it must read at least 4.5:1 (WCAG AA, normal
 * text) on the surfaces the thread sits on, under BOTH brand palettes: the neural one (EU and both sandbox frames) and
 * the sovereign one (ASIA, `body.theme-sovereign`), which the console proof does not reach (both sandbox frames are
 * neural). A mark that follows the palette's accent, var(--nc-primary), turns #DC2626 under the sovereign palette and
 * reads 3.8:1 on the console's dark surface. It carries no opacity either: a faded small text fails at any colour.
 * Red on 98edfcf03 (the branch before the review's fixes).
 */

const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]

/** The declarations of the first rule written for exactly `selector` (`<selector> {` at a line start). */
function block(css: string, selector: string): string | null {
  const at = css.search(new RegExp(`(^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{`))
  if (at < 0) return null
  const open = css.indexOf('{', at)
  return css.slice(open + 1, css.indexOf('}', open))
}

/** A palette's custom properties: name -> value. */
function palette(css: string, selector: string): Record<string, string> {
  const body = block(css, selector)
  if (body == null) throw new Error(`no ${selector} palette in neural-command.css`)
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

/** A colour value as one theme resolves it: a var() takes the theme's value, else the neural one, else its fallback. */
function resolve(value: string, theme: Record<string, string>, base: Record<string, string>): string {
  const v = value.trim()
  const m = v.match(/^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)$/)
  if (!m) return v
  const got = theme[m[1]] ?? base[m[1]] ?? m[2]
  if (got == null) throw new Error(`${m[1]} is defined by no palette and has no fallback`)
  return resolve(got, theme, base)
}

const hexRgb = (h: string): RGB => {
  const x = h.trim().match(/^#([0-9a-f]{6})$/i)
  if (!x) throw new Error(`a colour this test does not read: ${h}`)
  return [0, 2, 4].map((i) => parseInt(x[1].slice(i, i + 2), 16)) as RGB
}
function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
function ratio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const THEME = read('assets/styles/neural-command.css')
const NEURAL = palette(THEME, ':root, body.theme-neural')
const SOVEREIGN = palette(THEME, 'body.theme-sovereign')
// the surfaces under the mark: the console's dark surface as the proof's axe measured it (V0657), and Pocket's shell
const SURFACES = ['#131224', '#06080c']

describe('the "your agent" mark reads at least 4.5:1 under both palettes', () => {
  const rule = block(read('views/pocket/PocketOurStateThread.vue'), '.ost-my-agent')

  it('declares its colour and no opacity', () => {
    expect(rule, 'the mark has its rule').not.toBeNull()
    expect(rule!).toMatch(/(?:^|[\s;{])color:\s*[^;]+;/)
    expect(rule!, 'a faded small text fails at any colour').not.toMatch(/(?:^|[\s;{])opacity\s*:/)
  })

  for (const [name, theme] of [['neural', NEURAL], ['sovereign', SOVEREIGN]] as const) {
    it(`under the ${name} palette`, () => {
      const value = rule!.match(/(?:^|[\s;{])color:\s*([^;]+);/)![1]
      const fg = hexRgb(resolve(value, theme, NEURAL))
      for (const bg of SURFACES) {
        expect(ratio(fg, hexRgb(bg)), `${value} as ${name} resolves it, on ${bg}`).toBeGreaterThanOrEqual(4.5)
      }
    })
  }

  it('reads the palettes the way the themes do (a control)', () => {
    expect(resolve('var(--nc-primary, #00d2d2)', SOVEREIGN, NEURAL).toUpperCase()).toBe('#DC2626')
    expect(resolve('var(--nc-primary, #00d2d2)', NEURAL, NEURAL)).toBe('#00d2d2')
    expect(ratio(hexRgb('#DC2626'), hexRgb('#131224'))).toBeCloseTo(3.8, 1)
  })
})
