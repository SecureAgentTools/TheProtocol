/** guildActions.test.ts — §POCKETBRIDGE2 W5. The gating table, pinned. */
import { describe, it, expect } from 'vitest'
import { roleOn, actionsFor } from './guildActions'

const POSTER = 'did:theprotocol:poster'
const WORKER = 'did:theprotocol:worker'
const OTHER = 'did:theprotocol:other'
const order = (status: string, extra: Record<string, any> = {}) =>
  ({ id: 'o1', status, poster_did: POSTER, worker_did: WORKER, ...extra })

describe('roleOn', () => {
  it('names poster, worker, observer', () => {
    expect(roleOn(order('open'), POSTER)).toBe('poster')
    expect(roleOn(order('open'), WORKER)).toBe('worker')
    expect(roleOn(order('open'), OTHER)).toBe('observer')
    expect(roleOn(order('open'), null)).toBe('observer')
    expect(roleOn(null, POSTER)).toBe('observer')
  })
})

describe('actionsFor — the whole gating table', () => {
  const keys = (o: any, did: string) => actionsFor(o, did).actions.map(a => a.key)

  it('poster on open with bids: award + cancel', () => {
    expect(keys(order('open', { bid_count: 3 }), POSTER)).toEqual(['award', 'cancel'])
  })
  it('poster on open with no bids: cancel only, and the note explains', () => {
    const r = actionsFor(order('open', { bid_count: 0 }), POSTER)
    expect(r.actions.map(a => a.key)).toEqual(['cancel'])
    expect(r.note).toContain('No bids yet')
  })
  it('poster on submitted: verify, marked as a money action', () => {
    const r = actionsFor(order('submitted'), POSTER)
    expect(r.actions).toEqual([{ key: 'verify', label: 'Verify delivery', money: true }])
  })
  it('poster on awarded: nothing, with a waiting note', () => {
    const r = actionsFor(order('awarded'), POSTER)
    expect(r.actions).toEqual([])
    expect(r.note).toContain('waiting on the worker')
  })
  it('worker on awarded and in_progress: submit', () => {
    expect(keys(order('awarded'), WORKER)).toEqual(['submit'])
    expect(keys(order('in_progress'), WORKER)).toEqual(['submit'])
  })
  it('worker on submitted: nothing, note says money moves at acceptance', () => {
    const r = actionsFor(order('submitted'), WORKER)
    expect(r.actions).toEqual([])
    expect(r.note).toContain('acceptance')
  })
  it('observer on open: bid; on anything else: an explanation, never silence', () => {
    expect(keys(order('open'), OTHER)).toEqual(['bid'])
    const r = actionsFor(order('settled'), OTHER)
    expect(r.actions).toEqual([])
    expect(r.note.length).toBeGreaterThan(0)
  })
  it('no acting agent: empty with the pick-an-agent reason (S5)', () => {
    const r = actionsFor(order('open'), null)
    expect(r.actions).toEqual([])
    expect(r.note).toContain('acting agent')
  })
  it('settled says settled to both sides', () => {
    expect(actionsFor(order('settled'), POSTER).note).toContain('paid')
    expect(actionsFor(order('settled'), WORKER).note).toContain('paid')
  })
})
