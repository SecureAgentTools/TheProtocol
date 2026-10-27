import { describe, it, expect } from 'vitest'
import {
  awaitsDecision, paymentStarted, ballotProblem, ballotTotal, cleanAllocations, cleanEvidence, evidenceUrlOk, leadSeason, pointsLeft, seasonPhase,
  setPoints, submissionProblem,
  submitterLabel,
} from './commons'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the commons' arithmetic as the console does it before asking the server: a ballot
 * holds whole points and never more than 100 in all, a season's phase follows its window, a submission needs evidence.
 */
const NOW = Date.parse('2026-10-02T12:00:00Z')

describe('a season\'s phase', () => {
  it('open inside its window, ended after it (the server refuses both acts then), and the settled states as they are', () => {
    expect(seasonPhase({ status: 'open', ends_at: '2026-10-09T00:00:00Z' }, NOW)).toBe('open')
    expect(seasonPhase({ status: 'open', ends_at: '2026-10-01T00:00:00Z' }, NOW)).toBe('ended')
    expect(seasonPhase({ status: 'closed', ends_at: null }, NOW)).toBe('closed')
    expect(seasonPhase({ status: 'paid', ends_at: null }, NOW)).toBe('paid')
    expect(seasonPhase({ status: 'cancelled', ends_at: null }, NOW)).toBe('cancelled')
  })
  it('control: an open season with no end date stays open, and nothing is no phase', () => {
    expect(seasonPhase({ status: 'open', ends_at: null }, NOW)).toBe('open')
    expect(seasonPhase(null, NOW)).toBeNull()
  })
})

describe('which season the page leads with', () => {
  it('the open one, else the one waiting for payment, else the newest', () => {
    expect(leadSeason([{ id: 3, status: 'paid' }, { id: 2, status: 'open' }])?.id).toBe(2)
    expect(leadSeason([{ id: 3, status: 'paid' }, { id: 2, status: 'closed' }])?.id).toBe(2)
    expect(leadSeason([{ id: 3, status: 'cancelled' }, { id: 2, status: 'paid' }])?.id).toBe(3)
    expect(leadSeason([])).toBeNull()
  })
})

describe('a ballot', () => {
  it('keeps whole positive points only, keyed by submission id', () => {
    expect(cleanAllocations({ 1: 10, 2: 0, 3: -4, 4: '7', 5: 2.9, 6: 'x' })).toEqual({ 1: 10, 4: 7, 5: 2 })
    expect(ballotTotal({ 1: 10, 4: '7' })).toBe(17)
  })
  it('counts what is left, and names an empty or an over-full ballot', () => {
    expect(pointsLeft({ 1: 30, 2: 40 })).toBe(30)
    expect(ballotProblem({})).toBe('empty')
    expect(ballotProblem({ 1: 0 })).toBe('empty')
    expect(ballotProblem({ 1: 60, 2: 41 })).toBe('over')
    expect(ballotProblem({ 1: 60, 2: 40 })).toBeNull()
    expect(pointsLeft({ 1: 60, 2: 41 })).toBe(0)
  })
  it('a field can never take more than the others leave: 80 typed beside 30 becomes 70', () => {
    expect(setPoints({ 1: 30 }, 2, 80)).toEqual({ 1: 30, 2: 70 })
    expect(setPoints({ 1: 30, 2: 70 }, 2, 10)).toEqual({ 1: 30, 2: 10 })     // lowering is always free
    expect(setPoints({ 1: 30 }, 1, 0)).toEqual({})                           // zero removes the field
    expect(setPoints({ 1: 30 }, 1, -5)).toEqual({})
    expect(setPoints({ 1: 30 }, 2, 'abc')).toEqual({ 1: 30 })
    expect(setPoints({ 1: 100 }, 2, 5)).toEqual({ 1: 100 })                  // nothing left: the new field stays empty
  })
})

describe('payment of a closed season', () => {
  const a = (status: string, attempted_at: string | null = null) => ({ median_points: '1', voters: 2, share: '1', amount: '5',
    status, funded_amount: null, shortfall: null, paid_at: null, attempted_at })
  it('a failed award, or one sent and never answered, waits for a decision; an unsent or settled one does not', () => {
    expect(awaitsDecision(a('failed', '2026-10-02T10:00:00Z'))).toBe(true)
    expect(awaitsDecision(a('pending', '2026-10-02T10:00:00Z'))).toBe(true)
    expect(awaitsDecision(a('pending'))).toBe(false)
    expect(awaitsDecision(a('paid', '2026-10-02T10:00:00Z'))).toBe(false)
    expect(awaitsDecision(a('written_off', '2026-10-02T10:00:00Z'))).toBe(false)
    expect(awaitsDecision(null)).toBe(false)
  })
  it('payment has started once any award was sent or settled; never-sent pending awards alone have not', () => {
    expect(paymentStarted([{ award: a('pending') }, { award: null }])).toBe(false)
    expect(paymentStarted([{ award: a('pending') }, { award: a('pending', '2026-10-02T10:00:00Z') }])).toBe(true)
    expect(paymentStarted([{ award: a('paid') }])).toBe(true)
    expect(paymentStarted([])).toBe(false)
  })
})

describe('a submission', () => {
  const ok = { kind: 'change', title: 'Fixed the tally page', evidence: [{ type: 'commit', ref: 'abc123' }] }
  it('needs a known kind, a 3 to 200 character title and at least one piece of evidence with its reference', () => {
    expect(submissionProblem(ok)).toBeNull()
    expect(submissionProblem({ ...ok, kind: 'bogus' })).toBe('unknown_kind')
    expect(submissionProblem({ ...ok, title: 'ab' })).toBe('title_length')
    expect(submissionProblem({ ...ok, evidence: [{ type: 'url', ref: '', url: '' }] })).toBe('evidence_required')
    expect(submissionProblem({ ...ok, evidence: [{ type: 'url', ref: '', url: 'https://x.test/a' }] })).toBe('evidence_shape')
    expect(submissionProblem({ ...ok, evidence: [{ type: 'url', ref: 'docs', url: 'http://x.test/a' }] })).toBe('evidence_url')
    expect(submissionProblem({ ...ok, evidence: Array.from({ length: 11 }, (_, i) => ({ type: 'other', ref: `r${i}` })) })).toBe('too_much_evidence')
  })
  it('links are https only; an empty link is no link', () => {
    expect(evidenceUrlOk('https://git.example/x')).toBe(true)
    expect(evidenceUrlOk('')).toBe(true)
    expect(evidenceUrlOk('javascript:alert(1)')).toBe(false)
    expect(evidenceUrlOk('http://a.test')).toBe(false)
  })
  it('evidence goes out trimmed, without blank rows and without an empty url', () => {
    expect(cleanEvidence([{ type: 'commit', ref: ' abc ', url: '' }, { type: 'url', ref: '', url: '' },
      { type: 'url', ref: 'page', url: ' https://a.test/p ' }]))
      .toEqual([{ type: 'commit', ref: 'abc' }, { type: 'url', ref: 'page', url: 'https://a.test/p' }])
  })
})

// §MEMBERSHIP (V0565): season 3 on sbx-alpha read "by mbrgate-invalid" three times for three members.
describe('submitterLabel', () => {
  const sub = (did: string, name: string) => ({ submitter_did: did, submitter_name: name })
  it('shows a name alone where no other submitter shares it', () => {
    const all = [sub('did:x:aaaaaa111111', 'Ada'), sub('did:x:bbbbbb222222', 'Bea')]
    expect(submitterLabel(all[0], all)).toBe('Ada')
  })
  it('adds the DID tail where different submitters share a name (any case)', () => {
    const all = [sub('did:x:a-0001-e192f8', 'mbrgate-invalid'), sub('did:x:b-0002-a4a4a4', 'MBRGATE-invalid'),
                 sub('did:x:c-0003-c0ffee', 'mbrgate-invalid')]
    expect(all.map(s => submitterLabel(s, all))).toEqual(
      ['mbrgate-invalid · …e192f8', 'MBRGATE-invalid · …a4a4a4', 'mbrgate-invalid · …c0ffee'])
  })
  it('keeps one member with several submissions plain', () => {
    const all = [sub('did:x:same-1', 'Ada'), sub('did:x:same-1', 'Ada')]
    expect(submitterLabel(all[1], all)).toBe('Ada')
  })
  it('lengthens the tail where two namesakes end alike, and shows the DID where there is no name', () => {
    const all = [sub('did:x:111111-abcdef', 'Twin'), sub('did:x:222222-abcdef', 'Twin')]
    expect(submitterLabel(all[0], all)).toBe('Twin · …11111-abcdef')
    expect(submitterLabel(all[1], all)).toBe('Twin · …22222-abcdef')
    expect(submitterLabel(sub('did:x:nameless', ''), [])).toBe('did:x:nameless')
  })
})

