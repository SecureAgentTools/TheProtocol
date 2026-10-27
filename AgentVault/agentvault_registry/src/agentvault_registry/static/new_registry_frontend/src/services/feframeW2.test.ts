// @vitest-environment node
/**
 * §FEFRAME W2 — the frontend's frame identity comes from the server's frame manifest, never from a seed.
 * Each test has its control: the old seed's answer (A/B/C, AVT, the grey `¤`) must not come back.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { describeCurrency, registerCurrencyNames } from '@/config/currencies'
import { FRAMES, framesFromManifest, setFramesFromManifest, esSocketUrl, esStatsUrl, frameByTrustDomain } from '@/config/frames'
import { manifestFrom, currencyNames } from '@/services/frameManifest'

const EU = manifestFrom({
  manifest_version: 1, multi_frame: true,
  self: { key: 'eu', name: 'EU', display_name: 'EU', trust_domain: 'eu.theprotocol.cloud', role: 'frame',
    public_url: 'https://eu.theprotocol.cloud', console_url: 'https://theprotocol.cloud', currency: 'ECU',
    currency_name: 'European Compute Unit', ledger_ws: 'wss://eu.theprotocol.cloud/ws/events' },
  peers: [
    { key: 'asia', name: 'ASIA', display_name: 'ASIA', trust_domain: 'asia.theprotocol.cloud', role: 'frame',
      public_url: 'https://asia.theprotocol.cloud', currency: 'ACU', ledger_ws: 'wss://asia.theprotocol.cloud/ws/events' },
    { key: 'amsterdam', name: 'amsterdam', display_name: 'Amsterdam', trust_domain: 'eu.theprotocol.cloud',
      role: 'operator', parent: 'eu', public_url: 'https://amsterdam.op.theprotocol.cloud', currency: 'ECU' },
  ],
})!

// the same federation from amsterdam's console
const AMS = manifestFrom({ ...EU, self: EU.peers[1], peers: [EU.self, EU.peers[0]] } as any)!

afterEach(() => { FRAMES.splice(0, FRAMES.length) })

describe('currency presentation is derived, never seeded', () => {
  it('names a code from the manifest, and derives a stable distinct accent and glyph', () => {
    const before = describeCurrency('SBXZ')
    expect(before.code).toBe('SBXZ')
    expect(before.name).toBe('SBXZ')                    // unnamed: the code is its own name
    expect(before.glyph).not.toBe('¤')                  // the old seed drew every real currency as a grey ¤
    registerCurrencyNames({ SBXZ: 'Sandbox Zeta Unit' })
    expect(describeCurrency('sbxz').name).toBe('Sandbox Zeta Unit')
    expect(describeCurrency('SBXZ').accent).toBe(before.accent)            // stable across calls
    expect(describeCurrency('ECU').accent).not.toBe(describeCurrency('ACU').accent)
  })

  it('an unknown identity renders NO unit, never another frame\'s', () => {
    const d = describeCurrency('')
    expect(d.code).toBe('')
    expect(d.name).toBe('')
    expect(describeCurrency(null).code).not.toBe('AVT')
  })

  it('the manifest names every frame currency it knows', () => {
    expect(currencyNames(EU)).toEqual({ ECU: 'European Compute Unit' })
  })
})

describe('frames come from the manifest', () => {
  it('own frame first, read as `local`; a peer through this registry\'s per-frame proxy; operators are no frame', () => {
    const fr = framesFromManifest(EU)
    expect(fr.map(f => f.key)).toEqual(['eu', 'asia'])
    expect(fr[0].adminFrameParam).toBe('local')
    expect(fr[0].es?.statsPath).toBe('/api/v1/public/eventstore-stats')
    expect(fr[1].adminFrameParam).toBeUndefined()
    expect(fr[1].es?.statsPath).toBe('/api/v1/public/eventstore-stats/asia')
    expect(fr.map(f => f.label)).toEqual(['EU', 'ASIA'])
    expect(fr.map(f => f.currency)).toEqual(['ECU', 'ACU'])
    expect(fr.some(f => /^[ABC]$/.test(f.key))).toBe(false)              // no letters
  })

  it('an operator console\'s own frame is its parent', () => {
    const fr = framesFromManifest(AMS)
    expect(fr.map(f => f.key)).toEqual(['eu', 'asia'])
    expect(fr[0].adminFrameParam).toBe('local')
  })

  it('FRAMES is filled in place, so a plain module that imported it sees the frames', () => {
    expect(FRAMES.length).toBe(0)                                         // empty until the manifest lands
    setFramesFromManifest(EU)
    expect(FRAMES.map(f => f.key)).toEqual(['eu', 'asia'])
    expect(frameByTrustDomain(FRAMES, 'ASIA.theprotocol.cloud')?.key).toBe('asia')
  })

  it('each frame streams its own ledger on its public host; stats go through this registry', () => {
    setFramesFromManifest(EU)
    expect(esSocketUrl('eu')).toBe('wss://eu.theprotocol.cloud/ws/events')
    expect(esSocketUrl('asia')).toBe('wss://asia.theprotocol.cloud/ws/events')
    expect(esStatsUrl('asia')).toBe('/api/v1/public/eventstore-stats/asia')
    expect(esStatsUrl('')).toBe('/api/v1/public/eventstore-stats')
    // the control: a retired letter names no frame, and its socket is this console's own, never a seed lane
    expect(esSocketUrl('B')).toBe('ws://localhost/ws/events')
  })
})
