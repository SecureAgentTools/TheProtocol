import { describe, it, expect, afterEach } from 'vitest'
import { FRAMES, setFramesFromManifest } from '@/config/frames'
import { manifestFrom } from '@/services/frameManifest'
import { directoryFromPublicTopology, hostLabel } from './publicDirectory'

/**
 * REAL payload, trimmed from a live `GET /api/v1/public/topology` on frame-c
 * (2026-08-21). Invented fixtures are how the R1 grammar bug survived 82 green
 * tests, so this one is captured, not imagined.
 */
const REAL = {
  registries: [
    { name: 'Frame-B', publicUrl: 'https://frame-b.theprotocol.cloud', domain: 'frame-b.theprotocol.cloud',
      hopDepth: 1, trust_domain: 'frame-b.theprotocol.cloud', display_name: 'Texas (The Lone Star Reserve)',
      exchange: { enabled: true, currency: 'JDAY', passport_enabled: true } },
    { name: 'Registry-A', publicUrl: 'https://api.theprotocol.cloud', domain: 'api.theprotocol.cloud',
      hopDepth: 1, trust_domain: 'agentvault.com', display_name: 'LV-223',
      exchange: { enabled: true, currency: 'AVT', passport_enabled: true } },
    { name: 'Frame-C', publicUrl: 'https://frame-c.theprotocol.cloud', domain: 'frame-c.theprotocol.cloud',
      hopDepth: 0, trust_domain: 'frame-c.theprotocol.cloud', display_name: 'Tehran (The Long Game)',
      exchange: { enabled: true, currency: 'BVT', passport_enabled: true } },
    { name: 'op-abudhabi', publicUrl: 'https://op-abudhabi.op.theprotocol.cloud', domain: 'op-abudhabi.op.theprotocol.cloud',
      hopDepth: 1, trust_domain: 'frame-c.theprotocol.cloud', display_name: 'Abu Dhabi (The Patient Fortune)',
      exchange: { enabled: false, currency: null, passport_enabled: true } },
    { name: 'op-london', publicUrl: 'https://op-london.op.theprotocol.cloud', domain: 'op-london.op.theprotocol.cloud',
      hopDepth: 1, trust_domain: 'agentvault.com', display_name: 'London (Still Clearing)',
      exchange: { enabled: false, currency: null, passport_enabled: true } },
  ],
}

/** The keys the ADMIN directory really uses on frame-c, measured the same day. */
const REAL_DIRECTORY_KEYS = [
  'frame-b', 'frame-c', 'op-abudhabi', 'op-berlin', 'op-chicago', 'op-doha', 'op-houston',
  'op-london', 'op-losangeles', 'op-newyork', 'op-paris', 'op-riyadh', 'op-singapore',
  'op-telaviv', 'op-washington', 'qatest16', 'registry-a',
]

describe('directoryFromPublicTopology', () => {
  it('produces keys that are REAL admin-directory keys (the join that matters)', () => {
    const d = directoryFromPublicTopology(REAL)
    expect(d.registries.length).toBe(5)
    for (const r of d.registries) expect(REAL_DIRECTORY_KEYS).toContain(r.key)
  })

  it('names the local registry from hopDepth 0, and never invents one', () => {
    expect(directoryFromPublicTopology(REAL).local_key).toBe('frame-c')
    const noLocal = { registries: REAL.registries.filter(r => r.hopDepth !== 0) }
    // '' means unknown. '__local__' was the bug: a key no entry carries.
    expect(directoryFromPublicTopology(noLocal).local_key).toBe('')
  })

  // §FEFRAME W2: the frames are the frame manifest's. This captured topology is the retired A/B/C cluster's, so a
  // manifest naming THOSE frames is the fixture; with no such frame a domain passes through and no unit is guessed.
  const legacy = manifestFrom({
    manifest_version: 1, multi_frame: true,
    self: { key: 'frame-a', name: 'Frame A', display_name: 'Frame A', trust_domain: 'agentvault.com', role: 'frame',
      public_url: 'https://api.theprotocol.cloud', currency: 'AVT' },
    peers: [
      { key: 'frame-b', name: 'Frame B', display_name: 'Frame B', trust_domain: 'frame-b.theprotocol.cloud',
        role: 'frame', public_url: 'https://frame-b.theprotocol.cloud', currency: 'JDAY' },
      { key: 'frame-c', name: 'Frame C', display_name: 'Frame C', trust_domain: 'frame-c.theprotocol.cloud',
        role: 'frame', public_url: 'https://frame-c.theprotocol.cloud', currency: 'BVT' },
    ],
  })!
  afterEach(() => { FRAMES.splice(0, FRAMES.length) })

  it('resolves the frame from the trust domain, through the frame manifest', () => {
    setFramesFromManifest(legacy)
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['registry-a'].frame).toBe('frame-a')
    expect(by['frame-b'].frame).toBe('frame-b')
    expect(by['frame-c'].frame).toBe('frame-c')
    expect(by['op-abudhabi'].frame).toBe('frame-c')        // an operator: its frame, by the shared trust domain
  })

  it('takes currency from the exchange, then falls back to the FRAME currency', () => {
    setFramesFromManifest(legacy)
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['frame-b'].currency).toBe('JDAY')          // from its own exchange
    expect(by['op-abudhabi'].currency).toBe('BVT')       // exchange disabled -> frame C
    expect(by['op-london'].currency).toBe('AVT')         // exchange disabled -> frame A
  })

  it('with no manifest frame for a domain, no frame and no unit are invented', () => {
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['op-london'].frame).toBe('agentvault.com')
    expect(by['op-london'].currency).toBeNull()
  })

  it('carries the HOST LABEL as an alias, which is what a credential URL matches', () => {
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['registry-a'].match.names).toContain('api')          // api.theprotocol.cloud
    expect(by['op-abudhabi'].match.names).toContain('op-abudhabi')
  })

  it('REGRESSION: a trust-domain join is ambiguous and must never be the key', () => {
    // Registry-A and op-london both sit on agentvault.com. Keying by trust
    // domain silently resolved Registry-A to op-london when measured live.
    const d = directoryFromPublicTopology(REAL)
    const sameTd = d.registries.filter(r => r.trust_domain === 'agentvault.com')
    expect(sameTd.length).toBeGreaterThan(1)
    expect(new Set(sameTd.map(r => r.key)).size).toBe(sameTd.length)
  })

  it('prefers the operator display name for humans, and keys on the slug', () => {
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['registry-a'].name).toBe('LV-223')
    expect(by['registry-a'].key).toBe('registry-a')
  })

  it('marks exactly one entry local', () => {
    expect(directoryFromPublicTopology(REAL).registries.filter(r => r.is_local).length).toBe(1)
  })

  it('drops unkeyable rows and de-duplicates rather than inventing identities', () => {
    const dirty = { registries: [
      ...REAL.registries,
      { name: '', publicUrl: 'https://nope.example' },
      { publicUrl: 'https://nameless.example' },
      null, 42, 'frame-c',
      { name: 'Frame-C', hopDepth: 0, trust_domain: 'frame-c.theprotocol.cloud' }, // dup
    ] }
    const d = directoryFromPublicTopology(dirty as any)
    expect(d.registries.length).toBe(5)
    expect(new Set(d.registries.map(r => r.key)).size).toBe(5)
  })

  it('never throws on junk, and returns an empty list rather than a wrong one', () => {
    for (const junk of [null, undefined, {}, { registries: null }, { registries: 'x' }, [], 7]) {
      const d = directoryFromPublicTopology(junk as any)
      expect(d.registries).toEqual([])
      expect(d.local_key).toBe('')
      expect(d.source).toBe('public')
    }
  })

  it('carries each registry OWN public URL — you cannot log in where you cannot address', () => {
    const by = Object.fromEntries(directoryFromPublicTopology(REAL).registries.map(r => [r.key, r]))
    expect(by['frame-b'].public_url).toBe('https://frame-b.theprotocol.cloud')
    expect(by['op-abudhabi'].public_url).toBe('https://op-abudhabi.op.theprotocol.cloud')
    // absent rather than guessed when the payload does not say
    const noUrl = directoryFromPublicTopology({ registries: [{ name: 'op-x', trust_domain: 'frame-c.theprotocol.cloud' }] })
    expect(noUrl.registries[0].public_url).toBeNull()
  })

  it('prefers the card-declared public_url over the derived publicUrl', () => {
    // The derived value is base_url with the port stripped, and for a renamed
    // operator that hostname can be DEAD: measured 2026-08-21, op-singapore's
    // derived host answered 000 and its card-declared host answered 200.
    const d = directoryFromPublicTopology({ registries: [{
      name: 'op-singapore',
      publicUrl: 'https://op-singapore.frame-b.theprotocol.cloud',   // derived, does not answer
      public_url: 'https://op-losangeles.op.theprotocol.cloud',      // the card's own statement
      trust_domain: 'frame-b.theprotocol.cloud', hopDepth: 1,
    }] })
    expect(d.registries[0].public_url).toBe('https://op-losangeles.op.theprotocol.cloud')
  })

  it('falls back to the derived URL when a card does not declare one', () => {
    const d = directoryFromPublicTopology({ registries: [{
      name: 'op-old', publicUrl: 'https://op-old.op.theprotocol.cloud',
      trust_domain: 'frame-c.theprotocol.cloud', hopDepth: 1,
    }] })
    expect(d.registries[0].public_url).toBe('https://op-old.op.theprotocol.cloud')
  })

  it('carries no relay field (§FEFRAME W4: the admin relay is gone; a session is made at the registry itself)', () => {
    for (const r of directoryFromPublicTopology(REAL).registries) expect('relay' in r).toBe(false)
    expect('relay_scope' in directoryFromPublicTopology(REAL)).toBe(false)
  })

  it('declares its source, so the UI can say where the list came from', () => {
    expect(directoryFromPublicTopology(REAL).source).toBe('public')
  })
})

describe('hostLabel', () => {
  it('takes the first label of the host', () => {
    expect(hostLabel('https://op-doha.op.theprotocol.cloud')).toBe('op-doha')
    expect(hostLabel('https://api.theprotocol.cloud')).toBe('api')
    expect(hostLabel('https://localhost:8101')).toBe('localhost')
  })
  it('returns null for anything that is not a URL', () => {
    for (const junk of [null, undefined, '', '   ', 'not a url', 42]) expect(hostLabel(junk as any)).toBeNull()
  })
})
