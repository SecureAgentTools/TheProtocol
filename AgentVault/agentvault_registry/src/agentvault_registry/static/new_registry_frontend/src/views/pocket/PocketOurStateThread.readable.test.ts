import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** V0662 (OurChat lane): readability. A rendered message in the console's wide thread stops at about 80 characters a line.
 *  The stylesheet is scoped CSS in the .vue file, which happy-dom does not lay out, so this pins the rule's source. */
const src = readFileSync(resolve(__dirname, 'PocketOurStateThread.vue'), 'utf8')

describe('the wide thread keeps a readable line length', () => {
  it('caps a rendered bubble at 80ch inside the desk layout only', () => {
    expect(src).toMatch(/\.ost--desk \.ost-bubble\.ost-md \{ max-width: 80ch; \}/)
  })
  it('sits inside the min-width 900px block, so Pocket keeps its own column', () => {
    const rule = src.indexOf('.ost--desk .ost-bubble.ost-md { max-width: 80ch; }')
    const block = src.lastIndexOf('@media (min-width: 900px) {', rule)
    expect(block).toBeGreaterThan(-1)
    expect(src.indexOf('\n}\n', block)).toBeGreaterThan(rule)
  })
})
