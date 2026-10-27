/**
 * grammarReal.test.ts — the grammar against REAL captured traffic.
 *
 * The P1 suite (grammar.test.ts, 57 green) proves the grammar's SHAPE. This one
 * proves it against payloads nobody wrote: envelopes lifted verbatim off the
 * live frame-c websocket. Every assertion here FAILS on the pre-2026-08-19
 * grammar, which is the only reason to trust it.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { FRAMES, setFramesFromManifest } from '@/config/frames'
import { manifestFrom } from '@/services/frameManifest'
import { toVerb, involvesDids, normalizeFrameHint, type GrammarContext } from './grammar'
import { REAL_ENVELOPES } from './__fixtures__/realEnvelopes'

const CTX = (mine?: string[]): GrammarContext => ({
  frame: 'C',
  frameCurrency: 'BVT',
  mineDids: mine ? new Set(mine.map(d => d.toLowerCase())) : null,
  localRegistry: 'frame-c',
  now: Date.parse('2026-08-19T00:45:00Z'),
})

/** The party fields as the real payload actually spells them. */
function partiesOf(t: keyof typeof REAL_ENVELOPES): { from?: string; to?: string } {
  const d: any = (REAL_ENVELOPES[t] as any).event?.data ?? (REAL_ENVELOPES[t] as any).data
  return { from: d.from ?? d.sender_did ?? d.buyer_did, to: d.to ?? d.receiver_did ?? d.seller_did }
}

describe('real payloads — party extraction', () => {
  const twoSided = [
    'TokensTransferred', 'FxSwapSettled', 'FxRouteSettled',
    'TransactionFeeCollected', 'CrossRegistryTransferCompleted',
    'CrossFrameTransferInitiated', 'CrossFrameTransferSettled', 'ExchangeTradeExecuted',
  ] as const

  for (const t of twoSided) {
    it(`${t}: resolves BOTH parties from the real payload`, () => {
      const d = toVerb(REAL_ENVELOPES[t], CTX())
      expect(d, `${t} produced no descriptor`).not.toBeNull()
      const { from, to } = partiesOf(t)
      expect(d!.fromDid, `${t} fromDid`).toBe(from)
      expect(d!.toDid, `${t} toDid`).toBe(to)
    })

    it(`${t}: mine=true when the viewer owns the SENDER`, () => {
      const { from } = partiesOf(t)
      const d = toVerb(REAL_ENVELOPES[t], CTX([from!]))
      expect(d!.mine, `${t} did not recognise its own sender`).toBe(true)
    })

    it(`${t}: mine=true when the viewer owns the RECEIVER`, () => {
      const { to } = partiesOf(t)
      const d = toVerb(REAL_ENVELOPES[t], CTX([to!]))
      expect(d!.mine, `${t} did not recognise its own receiver`).toBe(true)
    })

    it(`${t}: mine=false for a stranger (the test can fail)`, () => {
      const d = toVerb(REAL_ENVELOPES[t], CTX(['did:theprotocol:nobody-at-all-0000']))
      expect(d!.mine).toBe(false)
    })
  }
})

describe('LedgerBalanceChanged — parties live in an ARRAY', () => {
  const env: any = REAL_ENVELOPES.LedgerBalanceChanged
  const entries: any[] = env.event.data.entries

  it('the fixture really has more than one entry (else this proves nothing)', () => {
    expect(entries.length).toBeGreaterThan(1)
  })

  it('finds the party in entry[0]', () => {
    expect(involvesDids(env, new Set([entries[0].agent_did.toLowerCase()]))).toBe(true)
  })

  it('finds the party in the LAST entry — a first-match lookup misses this', () => {
    const last = entries[entries.length - 1].agent_did.toLowerCase()
    expect(involvesDids(env, new Set([last]))).toBe(true)
  })

  it('still draws NOTHING (accounting shadow; honesty rule)', () => {
    expect(toVerb(env, CTX([entries[0].agent_did]))).toBeNull()
  })

  it('says false for a stranger', () => {
    expect(involvesDids(env, new Set(['did:theprotocol:nobody-0000']))).toBe(false)
  })
})

describe('frame hints are trust domains and TEG ids, resolved through the frame manifest (§FEFRAME W2)', () => {
  // The real payloads were captured on the retired A/B/C cluster: their frame fields carry THOSE trust domains. A
  // manifest naming those frames resolves them to its keys; with no such frame, a domain passes through.
  const legacy = manifestFrom({
    manifest_version: 1, multi_frame: true,
    self: { key: 'frame-a', name: 'Frame A', display_name: 'Frame A', trust_domain: 'agentvault.com', role: 'frame',
      public_url: 'https://registry.theprotocol.cloud', currency: 'AVT' },
    peers: [
      { key: 'frame-b', name: 'Frame B', display_name: 'Frame B', trust_domain: 'frame-b.theprotocol.cloud', role: 'frame',
        public_url: 'https://frame-b.theprotocol.cloud', currency: 'JDAY' },
    ],
  })!
  const eu = manifestFrom({
    manifest_version: 1, multi_frame: true,
    self: { key: 'eu', name: 'EU', display_name: 'EU', trust_domain: 'eu.theprotocol.cloud', role: 'frame',
      public_url: 'https://eu.theprotocol.cloud', console_url: 'https://theprotocol.cloud', currency: 'ECU' },
    peers: [{ key: 'asia', name: 'ASIA', display_name: 'ASIA', trust_domain: 'asia.theprotocol.cloud', role: 'frame',
      public_url: 'https://asia.theprotocol.cloud', currency: 'ACU' }],
  })!
  afterEach(() => { FRAMES.splice(0, FRAMES.length) })

  it('FxSwapSettled resolves BOTH ends to the manifest frames', () => {
    setFramesFromManifest(legacy)
    const d = toVerb(REAL_ENVELOPES.FxSwapSettled, CTX())!
    const raw: any = (REAL_ENVELOPES.FxSwapSettled as any).event.data
    expect(raw.source_frame).toMatch(/\./)          // it really is a domain
    expect(raw.dest_frame).toMatch(/\./)
    expect(d.fromFrame).toBe('frame-a')             // and we resolved it, by trust domain
    expect(d.toFrame).toBe('frame-b')
    expect(d.fromFrame).not.toBe(d.toFrame)         // a real crossing
  })

  it('normalizeFrameHint maps trust domains, origins and keys to the manifest keys', () => {
    setFramesFromManifest(eu)
    expect(normalizeFrameHint('eu.theprotocol.cloud')).toBe('eu')
    expect(normalizeFrameHint('asia.theprotocol.cloud')).toBe('asia')
    expect(normalizeFrameHint('ASIA')).toBe('asia')
    expect(normalizeFrameHint('https://theprotocol.cloud')).toBe('eu')
    expect(normalizeFrameHint(null)).toBeNull()
    // the retired frames' domains are no frame of this federation: passed through, never mapped to a letter
    expect(normalizeFrameHint('agentvault.com')).toBe('agentvault.com')
    // legacy single letters and TEG ids keep their old rule (historical payloads)
    expect(normalizeFrameHint('teg-layer-frame-b')).toBe('B')
    expect(normalizeFrameHint('frame-c')).toBe('C')
  })

  it('an UNKNOWN domain is passed through, never invented into a frame', () => {
    setFramesFromManifest(eu)
    expect(normalizeFrameHint('somewhere-else.example')).toBe('somewhere-else.example')
  })
})

describe('the quiet types stay quiet on real payloads', () => {
  // Telemetry snapshots draw nothing at all.
  for (const t of ['HagridGiniSnapshot', 'HagridConservation'] as const) {
    it(`${t} draws nothing`, () => {
      expect(toVerb(REAL_ENVELOPES[t], CTX())).toBeNull()
    })
  }

  // A swept stale 2PC row is ROUTINE. It is scenery (corridor) marked reverted,
  // and it is emphatically not an alarm — that discipline is the only reason a
  // real breach lands when one arrives. (My first draft of this test asserted
  // null here; the grammar was right and the assumption was wrong.)
  it('CrossTEGStaleSwept is corridor scenery, reverted, NEVER alarm', () => {
    const d = toVerb(REAL_ENVELOPES.CrossTEGStaleSwept, CTX())
    expect(d).not.toBeNull()
    expect(d!.verb).toBe('corridor')
    expect(d!.reverted).toBe(true)
    expect(d!.verb).not.toBe('alarm')
  })
})
