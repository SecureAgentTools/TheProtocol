// V0665: the art review gallery's small labels (the theme tags and the two caption kinds) carry their own solid colour, never a faded opacity: axe's color-contrast counted 175 nodes on
// /admin/flare-art (a 9px tag at opacity .45 on #08111a reads 3.7:1, on the light surface 1.45:1; need 4.5:1). The light surface gets dark labels.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const css = readFileSync('src/views/AdminFlareArtGallery.vue', 'utf8').split('<style scoped>')[1]
const rule = (sel: string) => css.split('\n').filter((l) => l.startsWith(sel + ' {'))
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
const colorOf = (line: string) => (line.match(/color:\s*(#[0-9a-fA-F]{6})/) || [])[1]

describe('the art gallery labels', () => {
  for (const sel of ['.fag-tag', '.fag-cap', '.fag-cap2']) {
    it(`${sel} has a solid colour and no faded opacity`, () => {
      const [line] = rule(sel)
      expect(line, sel).toBeTruthy()
      expect(line).not.toMatch(/opacity:\s*0?\.\d/)
      expect(colorOf(line), `${sel} colour`).toBeTruthy()
    })
  }

  it('reads at 4.5:1 or more on each of the three surfaces', () => {
    const dark = colorOf(rule('.fag-tag')[0])
    for (const sel of ['.fag-tag', '.fag-cap', '.fag-cap2']) expect(colorOf(rule(sel)[0])).toBe(dark)
    expect(ratio(dark, '#08111a')).toBeGreaterThanOrEqual(4.5)       // neural
    expect(ratio(dark, '#170a0d')).toBeGreaterThanOrEqual(4.5)       // sovereign
    const lightRule = css.split('\n').find((l) => l.startsWith('.fag-panel-light .fag-tag'))!
    expect(lightRule, 'the light surface rule').toBeTruthy()
    expect(ratio(colorOf(lightRule)!, '#8d9aa8')).toBeGreaterThanOrEqual(4.5)   // light
  })
})
