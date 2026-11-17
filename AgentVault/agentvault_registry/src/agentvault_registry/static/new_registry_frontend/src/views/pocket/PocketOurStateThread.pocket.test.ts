import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** V0662 (OurChat lane), the maintainer's seq 3212: on a phone the / list reached out of the top of the screen and could not be
 *  scrolled, and a scroll at the end of the history carried the page (and the composer) with it. The stylesheet is scoped CSS,
 *  which happy-dom does not lay out, so these pin the rules' source. */
const src = readFileSync(resolve(__dirname, 'PocketOurStateThread.vue'), 'utf8')
const rule = (sel: string) => {
  const i = src.indexOf(`\n${sel} {`)
  expect(i, `${sel} has a rule`).toBeGreaterThan(-1)
  return src.slice(i, src.indexOf('}', i) + 1)
}

describe('the / list', () => {
  it('is bounded to what the screen can show and scrolls inside itself', () => {
    const r = rule('.ost-complete')
    expect(r).toMatch(/max-height: min\(16rem, 35dvh\)/)
    expect(r).toMatch(/overflow-y: auto/)
    expect(r).toMatch(/overscroll-behavior: contain/)
  })
})

describe('the history', () => {
  it('keeps its scroll to itself, so the page and the composer stay where they are', () => {
    expect(rule('.ost-scroll')).toMatch(/overscroll-behavior: contain/)
  })
})
