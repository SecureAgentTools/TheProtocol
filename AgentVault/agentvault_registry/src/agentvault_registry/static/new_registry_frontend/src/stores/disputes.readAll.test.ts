/**
 * §COCKPITDESK (2026-10-15) — the Disputes page reads its list and its tiles from one set of reads: the list holds every
 * dispute the counter read (it had held the first 100 while the tiles counted them all), and a failed refresh keeps what
 * the page already shows.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ readAll: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/disputes', async (orig) => ({ ...(await orig<any>()), disputesApi: { readAll: h.readAll } }))
vi.mock('./ui', () => ({ useUIStore: () => ({ showError: h.showError, showSuccess: vi.fn() }) }))
vi.mock('./auth', () => ({ useAuthStore: () => ({ activeAgent: null }) }))

import { useDisputesStore } from './disputes'

const d = (id: number) => ({ id: String(id), status: 'open', created_at: '2026-10-01T00:00:00Z', evidence: [] }) as any
const stats = (n: number, capped = false) => ({ total_disputes: n, open_disputes: n, resolved_disputes: 0, resolution_rate: 0,
  average_resolution_time: 0, capped })

// a block body: a function a hook returns is its teardown, and mockReset() returns the mock itself
beforeEach(() => { setActivePinia(createPinia()); h.readAll.mockReset(); h.showError.mockReset() })

describe('the Disputes list and tiles from one read set', () => {
  it('the list holds every dispute read, and the tiles count the same rows', async () => {
    const s = useDisputesStore()
    h.readAll.mockResolvedValueOnce({ rows: Array.from({ length: 205 }, (_, i) => d(i + 1)), stats: stats(205) })
    await s.fetchDisputes()
    expect(h.readAll).toHaveBeenCalledTimes(1)
    expect(s.disputes).toHaveLength(205)
    expect(s.stats.total_disputes).toBe(205)
    expect(s.statsRead).toBe(true)
    expect(s.listRead).toBe(true)
    expect(s.listFailed).toBe(false)
  })
  it('a failed refresh says so and keeps what the page shows', async () => {
    const s = useDisputesStore()
    h.readAll.mockResolvedValueOnce({ rows: [d(1), d(2)], stats: stats(2) })
    await s.fetchDisputes()
    h.readAll.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    await s.fetchDisputes()
    expect(h.showError).toHaveBeenCalled()
    expect(s.listFailed).toBe(true)
    expect(s.disputes.map((x: any) => x.id)).toEqual(['1', '2'])
    expect(s.stats.total_disputes).toBe(2)
    expect(s.statsRead).toBe(true)
  })
})
