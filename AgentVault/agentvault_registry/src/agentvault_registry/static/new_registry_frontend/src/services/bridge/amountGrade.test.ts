import { describe, it, expect } from 'vitest'
import { AmountGrader, SAMPLE_CAP, MIN_SAMPLES } from './amountGrade'

const feed = (g: AmountGrader, cur: string, vals: number[]) => vals.forEach(v => g.observe(cur, v))

describe('AmountGrader', () => {
  it('returns null (not 0) for an event with no amount', () => {
    const g = new AmountGrader()
    // The distinction the whole module turns on: a birth or a corridor
    // announcement is NOT the smallest payment on the network. If this ever
    // returns 0, every amountless event silently becomes a dim tiny transfer.
    expect(g.grade('AVT', null).grade).toBeNull()
    expect(g.grade('AVT', undefined).grade).toBeNull()
    expect(g.grade('AVT', NaN).grade).toBeNull()
    expect(g.grade('AVT', null).basis).toBe('none')
  })

  it('falls back to the fixed ladder while the sample is too thin', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', [1, 2, 3])          // < MIN_SAMPLES
    const r = g.grade('AVT', 500_000)
    expect(r.basis).toBe('fallback')
    expect(r.samples).toBe(3)
    expect(r.grade).toBe(1)            // classifyAmount(500k) = 4, 4/4
  })

  it('switches to observed once the sample can carry it', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: MIN_SAMPLES }, (_, i) => i + 1))
    const r = g.grade('AVT', 5)
    expect(r.basis).toBe('observed')
    expect(r.samples).toBe(MIN_SAMPLES)
  })

  it('GRADES PER CURRENCY — the entire point of the module', () => {
    const g = new AmountGrader()
    // Two currencies at wildly different scales, exactly like AVT vs a frame
    // whose typical settlement is 1000x larger.
    feed(g, 'AVT', Array.from({ length: 50 }, (_, i) => i + 1))            // 1..50
    feed(g, 'BVT', Array.from({ length: 50 }, (_, i) => (i + 1) * 1000))   // 1000..50000

    const inAvt = g.grade('AVT', 1000).grade!
    const inBvt = g.grade('BVT', 1000).grade!
    // The SAME raw number is enormous in AVT and near-minimal in BVT.
    expect(inAvt).toBe(1)
    expect(inBvt).toBeLessThanOrEqual(0.02)
    expect(inAvt).toBeGreaterThan(inBvt)
    // A fixed global ladder would have given these two identical answers, which
    // is the defect this module exists to prevent.
  })

  it('is monotonic: a larger amount never grades lower', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: 100 }, () => Math.random() * 1000))
    let prev = -1
    for (const a of [0.5, 5, 50, 500, 5000, 50000]) {
      const cur = g.grade('AVT', a).grade!
      expect(cur).toBeGreaterThanOrEqual(prev)
      prev = cur
    }
  })

  it('never lets a currency sample grow past the cap', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: SAMPLE_CAP * 3 }, (_, i) => i + 1))
    expect(g.samples('AVT')).toBe(SAMPLE_CAP)
  })

  it('keeps the ring measuring the RECENT network', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: SAMPLE_CAP }, () => 1))       // all tiny
    feed(g, 'AVT', Array.from({ length: SAMPLE_CAP }, () => 100_000)) // all huge
    // Every original observation has been overwritten, so a mid value is now
    // at the BOTTOM of the distribution, not the top.
    expect(g.grade('AVT', 50).grade).toBe(0)
  })

  it('does not merge a missing currency into a real one', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: 20 }, () => 1))
    feed(g, null as any, Array.from({ length: 20 }, () => 100_000))
    // If the buckets merged, 100 would grade above the AVT floor.
    expect(g.grade('AVT', 100).grade).toBe(1)
    expect(g.grade(null, 100).grade).toBe(0)
  })

  it('ignores zero and non-finite observations', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', [0, NaN, Infinity, -0])
    expect(g.samples('AVT')).toBe(0)
  })

  it('treats currency case and whitespace as the same bucket', () => {
    const g = new AmountGrader()
    feed(g, 'avt', Array.from({ length: 20 }, (_, i) => i + 1))
    expect(g.samples(' AVT ')).toBe(20)
  })

  it('grades magnitude, so a refund of -500 reads like 500', () => {
    const g = new AmountGrader()
    feed(g, 'AVT', Array.from({ length: 20 }, (_, i) => i + 1))
    expect(g.grade('AVT', -500).grade).toBe(g.grade('AVT', 500).grade)
  })
})

// ── §BRIDGE R14.2 — the classifier option C is built on ──────────────────────
import { classifyEventType, eventTypeCensus, classifyEnvelope } from './grammar'
import { REAL_ENVELOPES } from './__fixtures__/realEnvelopes'

describe('classifyEventType', () => {
  it('separates the three cases toVerb() collapses into one null', () => {
    expect(classifyEventType('TokensTransferred')).toBe('drawn')
    expect(classifyEventType('LedgerBalanceChanged')).toBe('counted')
    expect(classifyEventType('SomethingThisBuildHasNeverHeardOf')).toBe('unknown')
    expect(classifyEventType(null)).toBe('unknown')
    expect(classifyEventType('')).toBe('unknown')
  })

  it('matches the census the ledger caption is derived from', () => {
    const c = eventTypeCensus()
    // The numbers in BRIDGE_R11_TAXONOMY.md, asserted rather than trusted.
    expect(c.drawn).toBe(115)
    expect(c.counted).toBe(81)
  })

  it('never classifies an unknown type as counted', () => {
    // The failure that matters: weather driven by types we cannot name would be
    // the stage inventing activity it has no basis for.
    for (const t of ['', 'Zzz', 'TokensTransferredX', 'ledgerbalancechanged']) {
      expect(classifyEventType(t)).not.toBe('counted')
    }
  })
})

describe('classifyEnvelope against REAL captured envelopes', () => {
  it('reads the type through the real wrapper, not off the top level', () => {
    // The bug this kills: a live envelope is { type: 'event', event: {...} },
    // so `envelope.type` === 'event' and `envelope.event_type` is undefined.
    // Anything reading those classifies EVERYTHING as unknown and the feature
    // built on it fires zero times, silently, forever.
    const raw = (REAL_ENVELOPES as any)['TokensTransferred']
    expect(raw.event_type).toBeUndefined()          // the trap, asserted
    expect(raw.type).toBe('event')                  // the decoy, asserted
    expect(classifyEnvelope(raw)).toBe('drawn')     // and the truth
  })

  it('classifies the real LedgerBalanceChanged as counted, not unknown', () => {
    const raw = (REAL_ENVELOPES as any)['LedgerBalanceChanged']
    expect(raw).toBeTruthy()
    expect(classifyEnvelope(raw)).toBe('counted')
  })

  it('classifies EVERY captured envelope as drawn or counted, never unknown', () => {
    // If a real type on this network reads as unknown, either the table is
    // stale or the unwrap is wrong. Both are defects; neither is invisible now.
    const bad: string[] = []
    for (const [name, env] of Object.entries(REAL_ENVELOPES as any)) {
      if (classifyEnvelope(env) === 'unknown') bad.push(name)
    }
    expect(bad).toEqual([])
  })

  it('is not fooled by junk', () => {
    expect(classifyEnvelope(null)).toBe('unknown')
    expect(classifyEnvelope({})).toBe('unknown')
    expect(classifyEnvelope({ type: 'event' })).toBe('unknown')
  })
})
