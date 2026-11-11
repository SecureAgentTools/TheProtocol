import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0658 (k): the slash order and per-peer panels on #/admin/settlements hold the console proof's a11y gate (axe,
 * color-contrast, 4.5:1). The V0657 proof failed this view's saga label at 3.69:1. Here every text colour the two
 * panels declare is read over their own background (rgba(10, 13, 22, 0.6) over the view's #131224 = #0e0f1c) and must
 * read at least 4.5:1, and no rule fades text with opacity (disabled controls excepted: axe skips them). Red on
 * 2e67df6c6: slate #64748b read 4.0:1, and a switched-off step's hint at 55% opacity 3.02:1.
 */

type RGB = [number, number, number]
const PANEL: RGB = [0x0e, 0x0f, 0x1c]
const read = (f: string) => fs.readFileSync(path.join(__dirname, f), 'utf8')
const style = (src: string) => src.slice(src.indexOf('<style'), src.lastIndexOf('</style>'))

function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
const ratio = (a: RGB, b: RGB) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05) }

/** Every rule of a stylesheet as [selector, body]. */
function rules(css: string): [string, string][] {
  const out: [string, string][] = []
  for (const m of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) out.push([m[1].trim(), m[2]])
  return out
}

describe('the slash panels read at least 4.5:1', () => {
  for (const file of ['SlashOrderPanel.vue', 'PeerAutoSlashPanel.vue']) {
    it(`${file}: every text colour over the panel`, () => {
      const found: string[] = []
      for (const [sel, body] of rules(style(read(file)))) {
        for (const m of body.matchAll(/(?:^|[\s;])color:\s*#([0-9a-f]{6})\b/gi)) {
          const rgb = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)) as RGB
          const r = ratio(rgb, PANEL)
          if (r < 4.5) found.push(`${sel}: #${m[1]} = ${r.toFixed(2)}:1`)
        }
      }
      expect(found).toEqual([])
    })

    it(`${file}: no text faded by opacity`, () => {
      const faded = rules(style(read(file)))
        .filter(([sel, body]) => /(?:^|[\s;])opacity:/.test(body) && !/:disabled/.test(sel))
        .map(([sel]) => sel)
      expect(faded).toEqual([])
    })
  }
})
