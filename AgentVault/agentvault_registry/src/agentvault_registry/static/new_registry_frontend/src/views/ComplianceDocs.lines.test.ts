import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0667 D8 (order gwo_589b1792026bd84e1da4e798): the compliance page has one section about who may change the platform's code and an
 * organization's own release lines, and its roadmap names what is NOT built (the compliance packs and the per-release report) as not done.
 * Plain: nothing is promised that the release does not have.
 */
const SRC = fs.readFileSync(path.resolve(__dirname, 'ComplianceDocs.vue'), 'utf8')

function section(): string {
  const m = SRC.match(/<section class="cp-sec" id="code-changes">[\s\S]*?<\/section>/)
  expect(m, 'the page has no <section class="cp-sec" id="code-changes">').toBeTruthy()
  return m![0]
}

describe('the compliance page: who may change the code, and release lines', () => {
  it('the section sits after "What\'s Implemented" and before the lifecycle, once', () => {
    expect((SRC.match(/id="code-changes"/g) || []).length).toBe(1)
    const impl = SRC.indexOf("What's Implemented")
    const here = SRC.indexOf('id="code-changes"')
    const life = SRC.indexOf('AI Component Lifecycle')
    expect(here).toBeGreaterThan(impl)
    expect(life).toBeGreaterThan(here)
  })

  it('it says what every change goes through, in the order it happens', () => {
    const s = section().replace(/\s+/g, ' ').toLowerCase()
    const order = ['signed checker', 'independent review', 'ballot', 'veto window', 'record']
    let at = -1
    for (const w of order) {
      const i = s.indexOf(w, at + 1)
      expect(i, w).toBeGreaterThan(at)
      at = i
    }
    for (const w of ['release line', 'open paths', 'policy backstop', 'maintainer']) expect(s, w).toContain(w)
  })

  it('it links to chapter 40 and to the code changes chapter', () => {
    const s = section()
    expect(s).toContain('/docs/40')
    expect(s).toContain('/docs/06')
  })

  it('it never speaks of a payout, and names no unbuilt feature as present', () => {
    const s = section().toLowerCase()
    expect(s).not.toMatch(/payout|stake|token|apy/)
    for (const w of ['compliance pack', 'lean', 'scoped channel']) expect(s, w).not.toContain(w)
  })

  it('the roadmap says what packs are (declarations, signed in the report) and that their enforcement by the rails is not built', () => {
    const done = SRC.match(/\{ done: true, text: '(?:[^'\\]|\\.)*compliance packs(?:[^'\\]|\\.)*' \}/i)
    expect(done, 'the roadmap has no done item about compliance packs as declarations').toBeTruthy()
    expect(done![0].toLowerCase()).toContain('declaration')
    expect(done![0].toLowerCase()).toContain('offline')
    const open = SRC.match(/\{ done: false, text: '(?:[^'\\]|\\.)*enforced by the rails(?:[^'\\]|\\.)*' \}/i)
    expect(open, 'the roadmap has no not-done item about packs enforced by the rails').toBeTruthy()
    expect(open![0]).toMatch(/planned, not built/i)
  })

  it('the section names the signed per-release report an auditor checks offline', () => {
    const s = section().replace(/\s+/g, ' ').toLowerCase()
    expect(s).toContain('signed per-release report')
    expect(s).toContain('offline')
  })
})
