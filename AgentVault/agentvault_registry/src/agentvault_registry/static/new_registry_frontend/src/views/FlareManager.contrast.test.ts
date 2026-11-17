// V0666: sbx-beta's console proof failed the member flare manager on axe's color-contrast (serious, 3 nodes): the three ".flm-label-sub" hints
// (https:// , https:// , hex (#RRGGBB)) were faded with opacity .55 (2.94:1 on #131825) and ".flm-variant-section-sub" was rgba(...,.6) (3.83:1 on #191d2e).
// (the label under them faded the whole line with opacity .65, and the hints inherited it.) Small hint text carries its own solid colour (never a fade) and reads at 4.5:1 or more on the form's surfaces.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const css = readFileSync('src/views/FlareManager.vue', 'utf8').split('<style scoped>')[1]
const block = (sel: string) => {
  const i = css.indexOf(`\n${sel} {`)
  expect(i, `the rule ${sel}`).toBeGreaterThan(-1)
  return css.slice(i, css.indexOf('}', i))
}
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
const SURFACES = ['#131825', '#191d2e'] // the form card and the variant section (axe's measured backgrounds)

describe('the member flare manager hint text', () => {
  for (const sel of ['.flm-label', '.flm-label-sub', '.flm-variant-section-sub']) {
    it(`${sel}: a solid colour, no fade, 4.5:1 on the form surfaces`, () => {
      const b = block(sel)
      expect(b, `${sel} must not fade with opacity`).not.toMatch(/opacity:\s*0?\.\d/)
      const col = (b.match(/(?:^|[\s;{])color:\s*(#[0-9a-fA-F]{6})\b/) || [])[1]
      expect(col, `${sel} needs a solid #rrggbb colour (no rgba)`).toBeTruthy()
      for (const bg of SURFACES) expect(ratio(col, bg), `${sel} ${col} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    })
  }
})
