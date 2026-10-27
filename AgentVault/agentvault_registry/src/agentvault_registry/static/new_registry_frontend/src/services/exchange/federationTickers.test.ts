import { describe, it, expect, beforeEach, vi } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(async () => ({ data: { venues: [{ venue: 'a', currency: 'AVT', listings: [{ symbol: 'X', last: '1', change_24h_pct: '0', status: 'trading', currency: 'AVT' }], trades: [] }] } })) } }))
import { apiClient } from '@/services/api/client'
import { useFederationTickers, __federationTickersInternals as I } from './federationTickers'

beforeEach(() => { I.reset(); (apiClient.get as any).mockClear() })

describe('§MCFOLD federation tickers — one poll for every strip', () => {
  it('two consumers share ONE fetch and ONE timer', async () => {
    const a = useFederationTickers(), b = useFederationTickers()
    a.join(); b.join()
    await a.refresh()
    expect(I.consumers).toBe(2)
    expect(I.polling).toBe(true)
    expect((apiClient.get as any).mock.calls.length).toBe(1)
    expect(a.venues.value.length).toBe(1)
  })
  it('the poll stops only when the LAST consumer leaves', () => {
    const a = useFederationTickers(), b = useFederationTickers()
    a.join(); b.join(); a.leave()
    expect(I.polling).toBe(true)
    b.leave()
    expect(I.polling).toBe(false)
    expect(I.consumers).toBe(0)
  })
  it('§FRESHFRAME: a failed poll records lastError, a good one clears it', async () => {
    const a = useFederationTickers()
    ;(apiClient.get as any).mockRejectedValueOnce(new Error('Network Error'))
    await a.refresh()
    expect(a.venues.value.length).toBe(0)
    expect(a.lastError.value).toBe('Network Error')
    await a.refresh()
    expect(a.lastError.value).toBeNull()
    expect(a.venues.value.length).toBe(1)
  })
  it('§FRESHFRAME: an empty network answers [] with NO error (sandbox shape: venues: [])', async () => {
    const a = useFederationTickers()
    ;(apiClient.get as any).mockResolvedValueOnce({ data: { venues: [], fetched_at: 1 } })
    await a.refresh()
    expect(a.venues.value.length).toBe(0)
    expect(a.lastError.value).toBeNull()
    expect(a.loadedOnce.value).toBe(true)
  })
  it('a strip that never mounts costs no request', () => {
    expect((apiClient.get as any).mock.calls.length).toBe(0)
    expect(I.polling).toBe(false)
  })
})
