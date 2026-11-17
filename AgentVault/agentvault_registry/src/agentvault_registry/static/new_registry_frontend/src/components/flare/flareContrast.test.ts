// V0666: the member flare manager failed axe's color-contrast (serious, 3 nodes) on sbx-beta's console proof: the muted counts and the
// empty-state line were #6c7787 on the dark panels (4.12:1 on #0a131c, 3.94:1 on #0f1820, 3.55:1 on the teal of a chosen row; need 4.5:1).
// The small muted lines of the flare manager's components read at 4.5:1 or more on every panel surface they sit on.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const SURFACES = ['#0a131c', '#0f1820', '#09242c'] // the earned-wear panel, a rail row, a chosen rail row (axe's measured backgrounds)
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
const styleOf = (file: string) => readFileSync(`src/components/flare/${file}`, 'utf8').split('<style scoped>')[1]
const colorOfRule = (css: string, sel: string) => {
  const line = css.split('\n').find((l) => l.startsWith(sel + ' {'))
  expect(line, `the rule for ${sel}`).toBeTruthy()
  return (line!.match(/(?:^|[ ;{])color:\s*(#[0-9a-fA-F]{6})/) || [])[1]
}

describe('the flare manager small muted text', () => {
  const cases: Array<[string, string]> = [
    ['EarnedWearPanel.vue', '.ewp-count'],
    ['EarnedWearPanel.vue', '.ewp-dark-count'],
    ['FlareBearerRail.vue', '.fbr-none'],
  ]
  for (const [file, sel] of cases) {
    it(`${sel} reads at 4.5:1 or more on every panel surface`, () => {
      const col = colorOfRule(styleOf(file), sel)
      expect(col, `${sel} colour`).toBeTruthy()
      for (const bg of SURFACES) expect(ratio(col, bg), `${sel} ${col} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    })
  }

  it('no flare component uses the old muted grey #6c7787 for text any more', () => {
    for (const f of ['EarnedWearPanel.vue', 'FlareBearerRail.vue', 'BoughtOnAgent.vue']) {
      const css = styleOf(f)
      const bad = css.split('\n').filter((l) => /(?:^|[ ;{])color:\s*#6c7787/i.test(l))
      expect(bad, `${f}: ${bad.join(' | ').slice(0, 120)}`).toEqual([])
    }
  })
})
