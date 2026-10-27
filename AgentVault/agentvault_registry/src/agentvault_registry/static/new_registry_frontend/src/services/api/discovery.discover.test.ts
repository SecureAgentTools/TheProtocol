import { describe, it, expect, beforeEach, vi } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { discoveryService, type DiscoverParams } from './discovery'

const answer = (data: unknown) => (apiClient.get as any).mockResolvedValueOnce({ data })
const sent = (): Record<string, unknown> => (apiClient.get as any).mock.calls.at(-1)[1].params

beforeEach(() => (apiClient.get as any).mockReset())

describe('§FESUITE discover(): every filter the page sets reaches the registry, and what it applied comes back', () => {
  it('sends include_unbonded when the box asks for it, and nothing when it does not', async () => {
    // the box set it and the query builder dropped it, for everyone (49-discovery, 2026-10-02)
    answer({ items: [], total: 0 })
    await discoveryService.discover({ q: 'x', include_unbonded: true })
    expect(sent().include_unbonded).toBe(true)
    answer({ items: [], total: 0 })
    await discoveryService.discover({ q: 'x' })
    expect('include_unbonded' in sent()).toBe(false)
  })

  it('drops no parameter the type declares (a new one must be added here, and to the query)', async () => {
    // Required<> makes vue-tsc refuse this literal the day DiscoverParams gains a field it does not name
    const every: Required<DiscoverParams> = {
      q: ' a ', origins: ['local', 'peer'], pricing: 'paid', tag: ' t ', verified_only: true, active_24h: true,
      encircled_only: true, foreign_only: true, answerable_only: true, bonded_only: true, include_unbonded: true,
      sort: 'newest', limit: 5, offset: 10,
    }
    answer({ items: [] })
    await discoveryService.discover(every)
    const missing = Object.keys(every).filter((k) => !(k in sent()))
    expect(missing).toEqual([])
    expect(sent()).toMatchObject({ q: 'a', origins: 'local,peer', tag: 't', limit: 5, offset: 10, sort: 'newest' })
  })

  it('returns the registry\'s applied_filters echo, or null when it sent none', async () => {
    answer({ items: [], applied_filters: { q: 'x', include_unbonded: false } })
    expect((await discoveryService.discover({ q: 'x', include_unbonded: true })).applied)
      .toEqual({ q: 'x', include_unbonded: false })
    answer({ items: [] })
    expect((await discoveryService.discover({ q: 'x' })).applied).toBeNull()
    answer({ items: [], applied_filters: 'not an object' })
    expect((await discoveryService.discover({ q: 'x' })).applied).toBeNull()
  })
})
