/**
 * D6-783 (2026-10-17): the InfoTooltip topics name a frame's money as its units, and send no one to a retired page.
 *
 * flare-grant, payment-required and pricing-tier said AVT ("Buy AVT via /buy-avt", "0.1 AVT"). Each frame has its own
 * unit, and /buy-avt is a legacy alias of /become-a-backer, the euro lane's page, which opens only where that lane is
 * switched on (it is off on the public network: the page sends a visitor to /pricing). Flare comes from the registry's
 * Flare Shop, paid in units, or from an administrator. The English bundle is the source; the other bundles fall back to
 * it and their translations wait in the translations backlog.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { TUTORIAL_REGISTRY } from './useTutorialRegistry'

const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../i18n/locales/en.json'), 'utf8'))
const topic = (id: string): { title?: string; body?: string } => en.tutorial.topics[id] || {}
const REWRITTEN = ['flare-grant', 'payment-required', 'pricing-tier']

describe('the tutorial topics an InfoTooltip shows', () => {
  it('name no unit of a single frame and no retired page, in any topic', () => {
    const ids = Object.keys(TUTORIAL_REGISTRY)
    expect(ids.length).toBeGreaterThanOrEqual(12)
    for (const id of ids) {
      const text = `${topic(id).title || ''} ${topic(id).body || ''}`
      expect(text, id).not.toMatch(/\b(?:AVT|JDAY|BVT)\b/)
      expect(text, id).not.toMatch(/\/buy-avt|\/become-a-backer|founders-wall/)
    }
  })

  it('say units where the three money topics speak of money, plainly', () => {
    for (const id of REWRITTEN) {
      const body = topic(id).body || ''
      expect(body, id).toMatch(/\bunits\b/)
      expect(body, id).not.toMatch(/—|\btokens?\b|\byield|\bAPY\b|\breturns?\b|\bIPO\b|\bshares?\b|\bdividend/i)
    }
  })

  it('point the flare topic at the pages the console names: the Flare Shop and My Flare', () => {
    const body = topic('flare-grant').body || ''
    expect(body).toContain(en.nav.items.flareShop)
    expect(body).toContain(en.nav.items.myFlare)
  })
})
