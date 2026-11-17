import { describe, expect, it } from 'vitest'
import { didTail, labelOf, proposerOf, reviewerOf, sameNames, wordsOf } from './people'

const t = (k: string, fb: string, p?: Record<string, any>) => (p ? fb.replace(/\{(\w+)\}/g, (_, n) => String(p[n])) : fb)
const D1 = 'did:theprotocol:eu.theprotocol.cloud:0fc15206-ca13-4257-884f-656866dd1bb1'
const D2 = 'did:theprotocol:eu.theprotocol.cloud:7a0e9c11-5b2d-4c3e-9f10-aa22bb33cc44'

describe('the people of a code change', () => {
  it('names the proposer by the agent\'s name, with the whole DID kept beside it', () => {
    const p = proposerOf({ proposer_did: D1, proposer_name: "Ada's builder", proposer_gone: false })
    expect(p).toMatchObject({ name: "Ada's builder", gone: false, did: D1 })
    expect(labelOf(p, new Set(), t)).toEqual({ text: "Ada's builder", tail: '', full: D1 })
  })

  it('says an agent that is gone in words, never an empty name', () => {
    const p = proposerOf({ proposer_did: D1, proposer_name: null, proposer_gone: true })
    expect(p.gone).toBe(true)
    expect(labelOf(p, new Set(), t).text).toBe('An agent that no longer exists')
    expect(labelOf(proposerOf({ proposer_did: D1, proposer_name: '   ', proposer_gone: true }), new Set(), t).text).toBe('An agent that no longer exists')
  })

  it('an agent with no name to show is not called gone when the registry says it is not (a card briefly inactive or unnamed)', () => {
    const p = proposerOf({ proposer_did: D1, proposer_name: null, proposer_gone: false })
    expect(p.gone).toBe(false)
    expect(labelOf(p, new Set(), t).text).toBe('An agent with no name')
  })

  it('reads an older registry (no name fields at all) as an agent with no name, not as a gone one', () => {
    const p = proposerOf({ proposer_did: D1 })
    expect(p.gone).toBe(false)
    expect(labelOf(p, new Set(), t).text).toBe('An agent with no name')
  })

  it('names a reviewer by the public name, else "Member #n", and never shows a DID for one', () => {
    expect(labelOf(reviewerOf({ reviewer_developer_id: 7, reviewer_name: 'Grace' }), new Set(), t)).toEqual({ text: 'Grace', tail: '', full: null })
    expect(wordsOf(reviewerOf({ reviewer_developer_id: 7, reviewer_name: null }), t)).toBe('Member #7')
  })

  it('adds a tail only where two DIFFERENT people show the same name', () => {
    const a = proposerOf({ proposer_did: D1, proposer_name: 'Builder' })
    const b = proposerOf({ proposer_did: D2, proposer_name: 'builder' })                      // the same words: case does not tell them apart
    const c = proposerOf({ proposer_did: D1, proposer_name: 'Builder' })                      // the very same agent again: not a second person
    const shared = sameNames([a, b, c], t)
    expect([...shared].sort()).toEqual([D1, D2].sort())
    expect(labelOf(a, shared, t).tail).toBe('…dd1bb1')                                      // the last six characters of the DID
    expect(labelOf(b, shared, t).tail).toBe('…33cc44')
    expect(didTail(D2)).toBe('…33cc44')
    expect(sameNames([a, c], t).size).toBe(0)
  })

  it('tells two members of one name apart by their numbers', () => {
    const r1 = reviewerOf({ reviewer_developer_id: 3, reviewer_name: 'Sam' }), r2 = reviewerOf({ reviewer_developer_id: 9, reviewer_name: 'Sam' })
    const shared = sameNames([r1, r2], t)
    expect(labelOf(r1, shared, t).tail).toBe('#3'); expect(labelOf(r2, shared, t).tail).toBe('#9')
    expect(labelOf(reviewerOf({ reviewer_developer_id: 5, reviewer_name: 'Sam' }), new Set(), t).tail).toBe('')
  })

  it('the same person reviewing twice is one person: no tail', () => {
    const r = reviewerOf({ reviewer_developer_id: 3, reviewer_name: 'Sam' })
    expect(sameNames([r, { ...r }], t).size).toBe(0)
  })

  it('does not mix an agent and a member of the same name into one person', () => {
    const a = proposerOf({ proposer_did: D1, proposer_name: 'Sam' }), r = reviewerOf({ reviewer_developer_id: 3, reviewer_name: 'Sam' })
    expect(sameNames([a, r], t).size).toBe(2)
  })
})
