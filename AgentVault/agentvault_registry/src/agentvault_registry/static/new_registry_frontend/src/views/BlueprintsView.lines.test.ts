import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0667 D8 (order gwo_589b1792026bd84e1da4e798), his "build first, so you dont phrase it weird in the /blueprint": the blueprints page has one
 * plain section about an organization's own release line, between "the management system" and the proof band. It says only what the V0667
 * release has (D1 to D5), names no future feature as present, and points to chapter 40 of the docs. Source-pinned, as the page's other tests are.
 */
const SRC = fs.readFileSync(path.resolve(__dirname, 'BlueprintsView.vue'), 'utf8')

function section(): string {
  const m = SRC.match(/<section class="bp-lines"[\s\S]*?<\/section>/)
  expect(m, 'the page has no <section class="bp-lines">').toBeTruthy()
  return m![0]
}

describe('the blueprints page: a release line of your own', () => {
  it('the section sits between the management system and the proof band, once', () => {
    expect((SRC.match(/<section class="bp-lines"/g) || []).length).toBe(1)
    const mgmt = SRC.indexOf('<section class="bp-mgmt">')
    const lines = SRC.indexOf('<section class="bp-lines"')
    const proof = SRC.indexOf('<section class="bp-proof')
    expect(mgmt).toBeGreaterThan(0)
    expect(lines).toBeGreaterThan(mgmt)
    expect(proof).toBeGreaterThan(lines)
  })

  it('it says what a line is, who decides and that every change still goes through us', () => {
    const s = section().replace(/\s+/g, ' ')
    for (const words of ['release line', 'its members propose', 'its deciders vote', 'signed checker', 'veto', 'never leaves our release']) {
      expect(s.toLowerCase(), words).toContain(words.toLowerCase())
    }
  })

  it('it links to chapter 40 of the docs and keeps the page\'s own t() convention', () => {
    const s = section()
    expect(s).toContain('/docs/40')
    expect(s).toMatch(/t\('blueprintsView\.lines\.label'/)
    expect(s).toMatch(/t\('blueprintsView\.lines\.title'/)
    expect(s).toMatch(/t\('blueprintsView\.lines\.body'/)
  })

  it('it promises nothing the release does not have: no build, channel, lean line or compliance pack is named as present', () => {
    const s = section().toLowerCase()
    for (const w of ['scoped channel', 'lean', 'compliance pack', 'we build it for you', 'planned']) {
      expect(s, w).not.toContain(w)
    }
  })

  it('it never speaks of a payout: a line is code governance', () => {
    expect(section().toLowerCase()).not.toMatch(/payout|stake|token|apy/)
  })
})
