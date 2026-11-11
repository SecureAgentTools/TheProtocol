/**
 * V0660 (m): /disputes keeps every command-bar control on a phone screen.
 *
 * MEASURED. The console proof of V0660 found `button.drc-icon-btn` at 396..423 px on a 412 px phone — off the
 * screen and unreachable — red since the V0658/V0659 nightlies. The cause: `.drc-cmd-bar` wraps, but the group
 * inside it, `.drc-cmd-bar__right`, held a select, a 220 px search and three buttons with no wrap of its own.
 * Measured at 412 px with the view's own style block in a standalone page: with the cut's CSS the second icon
 * button sits at 417..441 px and the file button at 449..559 px, two controls off the screen; with the wrap and a
 * shrinking search, every control is on it.
 *
 * ⚠ WHAT THIS TEST CAN AND CANNOT SEE. jsdom has no layout, so a unit test cannot measure a box: this reads the
 * view's own stylesheet and holds the two declarations that fix it. The layout itself is measured by the fesuite
 * spec on the sandbox once this is rolled, and by the standalone measurement above. A test that pins a rule is
 * weaker than one that measures an outcome, and saying so is part of the test.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '..', 'Disputes.vue')

function styleBlock(): string {
  const vue = readFileSync(SRC, 'utf8')
  const blocks = [...vue.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1])
  expect(blocks.length, 'Disputes.vue carries no style block; this test is reading the wrong file').toBeGreaterThan(0)
  return blocks.join('\n')
}

function rule(css: string, selector: string): string {
  const at = css.indexOf(selector)
  expect(at, `${selector} is not in the view's stylesheet any more`).toBeGreaterThan(-1)
  const open = css.indexOf('{', at)
  return css.slice(open + 1, css.indexOf('}', open))
}

describe('the disputes command bar on a phone', () => {
  it('lets the control group wrap', () => {
    const body = rule(styleBlock(), '.drc-cmd-bar__right')
    expect(body.replace(/\s+/g, ' '), 'without a wrap the row stays on one line and the last controls leave a '
      + '412 px screen (measured: 417..441 px and 449..559 px)').toMatch(/flex-wrap:\s*wrap/)
  })

  it('lets the 220 px search shrink instead of pushing its neighbours out', () => {
    const css = styleBlock()
    const search = rule(css, '.drc-cmd-bar__right .drc-search-wrap')
    expect(search.replace(/\s+/g, ' ')).toMatch(/flex:\s*1\s+1/)
    expect(search.replace(/\s+/g, ' '), 'a flex item with a fixed-width input needs min-width: 0 or it refuses '
      + 'to shrink below its content').toMatch(/min-width:\s*0/)
  })

  it('still has the controls it is about', () => {
    const vue = readFileSync(SRC, 'utf8')
    for (const cls of ['drc-cmd-bar__right', 'drc-icon-btn', 'drc-file-btn', 'drc-search']) {
      expect(vue, `${cls} is gone from the view; this test would pass over nothing`).toContain(cls)
    }
    expect((vue.match(/class="drc-icon-btn"/g) || []).length,
      'the proof measured two icon buttons in that group').toBeGreaterThanOrEqual(1)
  })
})
