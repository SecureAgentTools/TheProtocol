/**
 * V0663 (his yes seq 3068): the sentences behind the reason lines. A reason names what is the case: the filters that were on
 * (Discovery), that the stream is not up yet or that nothing has moved (the ledger). BASE: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { discoveryActiveFilters, discoveryEmptyReason, ledgerEmptyReason, type DiscoveryEmptyState } from './emptyReasons'

const OFF: DiscoveryEmptyState = { query: '', registry: 'all', frames: 0, tags: [], pricing: '', certified: false, online: false, quantum: false }

describe('why a Discovery search is empty', () => {
  it('with no filter on, says so instead of telling the person to broaden a search they did not narrow', () => {
    const r = discoveryEmptyReason(OFF)
    expect(r.kind).toBe('none-yet')
    expect(r.active).toEqual([])
    expect(r.reason).toMatch(/No filter is on/)
  })

  it('names each filter that is on, in the words of the filter panel', () => {
    const on: DiscoveryEmptyState = { ...OFF, query: 'weather', registry: 'local', frames: 2, tags: ['translation', ''], pricing: 'per_request', certified: true, online: true, quantum: true }
    expect(discoveryActiveFilters(on)).toEqual([
      'the search "weather"', 'this registry only', '2 frames', 'the tag "translation"', 'the pricing "per_request"',
      'certified only', 'online only', 'the quantum filters'])
  })

  it('joins them with "and" and says the list is narrowed by each', () => {
    const r = discoveryEmptyReason({ ...OFF, query: 'x', certified: true })
    expect(r.kind).toBe('filtered')
    expect(r.reason).toBe('Nothing matches the search "x" and certified only. Each one narrows the list; clearing them shows every agent.')
    expect(discoveryEmptyReason({ ...OFF, online: true }).reason).toMatch(/^Nothing matches online only\./)
  })

  it('counts frames and tags, never lists their ids', () => {
    expect(discoveryActiveFilters({ ...OFF, frames: 1 })).toEqual(['one frame'])
    expect(discoveryActiveFilters({ ...OFF, tags: ['a', 'b', 'c'] })).toEqual(['3 tags'])
  })
})

describe('why a ledger list is empty', () => {
  it('not connected: waiting for the stream, not "nothing happened"', () => {
    expect(ledgerEmptyReason({ connected: false, scope: 'all' })).toMatchObject({ kind: 'waiting' })
  })
  it('connected and quiet: nothing has moved since the page opened, and for MINE whose', () => {
    expect(ledgerEmptyReason({ connected: true, scope: 'all' })).toEqual({ kind: 'quiet', reason: 'The ledger is quiet: no event has moved since this page opened.' })
    expect(ledgerEmptyReason({ connected: true, scope: 'mine' }).reason).toMatch(/None of your agents/)
    expect(ledgerEmptyReason({ connected: true, scope: 'mine', scopeNote: 'Only 3 of your agents are known here.' }).reason).toBe('Only 3 of your agents are known here.')
  })
})
