/**
 * §SHOWN P0.14b — the presentation hash must be STABLE, or it must not exist.
 *
 * The plan makes this a 🔴 gate before P3 builds on it, for a good reason: a hash
 * that flaps trains everyone to ignore the mismatch that matters, which is strictly
 * worse than having no hash at all. So the properties are asserted BOTH ways —
 * identical inputs must agree, and each thing that SHOULD change it must change it.
 * A determinism test with no sensitivity test would pass for a function that
 * returns a constant.
 */
import { describe, it, expect } from 'vitest'
import {
  buildPresentation, canonicalPresentation, presentationHash, RENDER_VERSION,
} from './presentation'

const t = (_k: string, fb: string) => fb
const V2 = {
  schema: 'facts.v2', verb: 'contracts.engage', action_ref: 'inv-8841',
  mandate_id: 'lm_abc', agent_did: 'did:theprotocol:aaa',
  amount: '42.50', currency: 'BVT', counterparty_did: 'did:theprotocol:acme',
  counterparty_home_registry: null, auto_stepped_up: true, action_type: 'contracts.engage',
}

describe('presentation hash', () => {
  it('is deterministic across repeated builds of the same facts', async () => {
    const a = await presentationHash(buildPresentation(V2, t), 'en')
    const b = await presentationHash(buildPresentation({ ...V2 }, t), 'en')
    expect(a).toBeTruthy()
    expect(a).toBe(b)
  })

  it('does NOT depend on key order in the facts object', async () => {
    const reversed = Object.fromEntries(Object.entries(V2).reverse())
    expect(await presentationHash(buildPresentation(reversed, t), 'en'))
      .toBe(await presentationHash(buildPresentation(V2, t), 'en'))
  })

  it('CHANGES when the unit changes — the §FOREIGNACT case this exists for', async () => {
    const avt = { ...V2, currency: 'AVT' }
    expect(await presentationHash(buildPresentation(avt, t), 'en'))
      .not.toBe(await presentationHash(buildPresentation(V2, t), 'en'))
  })

  it('CHANGES when the counterparty changes', async () => {
    const other = { ...V2, counterparty_did: 'did:theprotocol:someone-else' }
    expect(await presentationHash(buildPresentation(other, t), 'en'))
      .not.toBe(await presentationHash(buildPresentation(V2, t), 'en'))
  })

  it('CHANGES when the amount loses a significant zero', async () => {
    const rounded = { ...V2, amount: '42.5' }
    expect(await presentationHash(buildPresentation(rounded, t), 'en'))
      .not.toBe(await presentationHash(buildPresentation(V2, t), 'en'))
  })

  it('CHANGES with the locale, because the words on the screen changed', async () => {
    const lines = buildPresentation(V2, t)
    expect(await presentationHash(lines, 'de')).not.toBe(await presentationHash(lines, 'en'))
  })

  it('CHANGES when a translated LABEL changes, not just a value', async () => {
    const de = (_k: string, fb: string) => (fb === 'Amount' ? 'Betrag' : fb)
    expect(await presentationHash(buildPresentation(V2, de), 'de'))
      .not.toBe(await presentationHash(buildPresentation(V2, t), 'de'))
  })

  it('renders a unitless legacy amount as "unit unrecorded", and hashes that', async () => {
    const legacy = { action_type: 'contracts.engage', amount: '7.25', mandate_id: 'lm_x' }
    const lines = buildPresentation(legacy, t)
    const amt = lines.find(l => l.key === 'amount')
    expect(amt?.value).toBe('7.25 unit unrecorded')
    expect(await presentationHash(lines, 'en')).toBeTruthy()
  })

  it('distinguishes "no counterparty at this stage" from a missing key', async () => {
    const declared = buildPresentation({ ...V2, counterparty_did: null }, t)
    const { counterparty_did: _drop, ...absent } = V2
    expect(declared.some(l => l.key === 'counterparty')).toBe(true)
    expect(buildPresentation(absent, t).some(l => l.key === 'counterparty')).toBe(false)
  })

  it('cannot be forged by a value that impersonates a line boundary', async () => {
    // Without control-character separators, a counterparty containing the delimiter
    // could make two different presentations canonicalise identically.
    const sneaky = { ...V2, counterparty_did: `x,Amount,999999 AVT` }
    const c1 = canonicalPresentation(buildPresentation(sneaky, t), 'en')
    const c2 = canonicalPresentation(buildPresentation(V2, t), 'en')
    expect(c1).not.toBe(c2)
    expect(c1.includes(String.fromCharCode(31))).toBe(true)
  })

  it('returns null rather than a fake hash when the platform cannot compute one', async () => {
    const real = globalThis.crypto
    try {
      Object.defineProperty(globalThis, 'crypto', { value: undefined, configurable: true })
      expect(await presentationHash(buildPresentation(V2, t), 'en')).toBeNull()
    } finally {
      Object.defineProperty(globalThis, 'crypto', { value: real, configurable: true })
    }
  })

  it('declares a render version, so a template change is not read as a mismatch', () => {
    expect(RENDER_VERSION).toMatch(/^cockpit-decision\/\d+$/)
  })
})

/**
 * §MEMBERSHIP (2026-10-02) — a member's binding vote and commons ballot are signed on the phone, so the phone must
 * show what they decide, and the hash must move when what they decide moves. A money decision is untouched.
 */
describe('membership decisions', () => {
  const VOTE = {
    action: 'Cast a governance vote', kind: 'governance.vote', registry: 'Sandbox Alpha',
    proposal_id: 7, proposal_title: 'Lower the transfer fee', choice: 'for', weight: '1.37',
  }
  const BALLOT = { action: 'Cast a commons ballot', kind: 'commons.ballot', registry: 'Sandbox Alpha', season_id: 3,
    season_title: 'Autumn', total_points: 100, submissions: 2, allocation_digest: 'ab12' }

  it('a vote shows its action, proposal, choice, weight and registry, in that order', () => {
    const lines = buildPresentation(VOTE, t)
    expect(lines.map(l => [l.key, l.value])).toEqual([
      ['verb', 'Cast a governance vote'], ['proposal', '#7 Lower the transfer fee'], ['choice', 'For'],
      ['weight', '1.37'], ['registry', 'Sandbox Alpha'],
    ])
  })

  it('a ballot shows its season (number and title, as the server sends them) and the points given', () => {
    const lines = buildPresentation(BALLOT, t)
    expect(lines.map(l => [l.key, l.value])).toEqual([
      ['verb', 'Cast a commons ballot'], ['season', '#3 Autumn'], ['points', '100'], ['registry', 'Sandbox Alpha'],
    ])
    expect(buildPresentation({ ...BALLOT, season_title: '' }, t).find(l => l.key === 'season')?.value).toBe('#3')
  })

  it('CHANGES when the choice or the points change', async () => {
    const a = await presentationHash(buildPresentation(VOTE, t), 'en')
    const b = await presentationHash(buildPresentation({ ...VOTE, choice: 'against' }, t), 'en')
    expect(a).not.toBe(b)
    const c = await presentationHash(buildPresentation(BALLOT, t), 'en')
    const d = await presentationHash(buildPresentation({ ...BALLOT, total_points: 60 }, t), 'en')
    expect(c).not.toBe(d)
  })

  it('control: a money decision renders exactly the lines it had before, even with a stray "registry" key', () => {
    const before = buildPresentation(V2, t)
    const after = buildPresentation({ ...V2, registry: 'Sandbox Alpha', weight: '9', choice: 'for' }, t)
    expect(after).toEqual(before)
  })
})
