import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-04) — AdminFx's swap and route feeds each ask the ledger twice (settled, refunded) and answered []
 * for a failed half, so the page said "No FX swaps recorded on frame X yet." with every read failed (the failing-reads
 * sweep on fe/failed-read-2's first build: a FALSE "none", gone once the reads answered). The swallow census had flagged
 * the inner `q` and attributed it to another caller by its name. Mocked at the HTTP layer, local and peer paths.
 */
const http = vi.hoisted(() => ({ get: vi.fn(), peerGet: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: http.get } }))
vi.mock('./peer', () => ({ peerGet: http.peerGet }))

import { fxService } from './fx'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })
const ev = (type: string, id: string, ts: string) => ({ event_type: type, event_id: id, timestamp: ts, data: { transaction_id: id, route_id: id } })

describe('the FX feeds tell a failed read from "none"', () => {
  beforeEach(() => { http.get.mockReset(); http.peerGet.mockReset() })

  it('swaps: one failed half fails the feed; it is never half a feed or an empty one', async () => {
    http.get.mockResolvedValueOnce({ data: { events: [ev('FxSwapSettled', 's1', '2026-10-04T10:00:00Z')] } })
    http.get.mockRejectedValueOnce(answered(502))
    await expect(fxService.swapEvents('local', 100)).rejects.toThrow('502')
    http.get.mockRejectedValue(new Error('Network Error'))
    await expect(fxService.swapEvents('local', 100)).rejects.toThrow('Network Error')
  })

  it('swaps: a 404 on both halves is "none"; answers are merged newest first', async () => {
    http.get.mockRejectedValueOnce(answered(404)).mockRejectedValueOnce(answered(404))
    await expect(fxService.swapEvents('local')).resolves.toEqual([])
    http.get.mockResolvedValueOnce({ data: { events: [ev('FxSwapSettled', 's1', '2026-10-04T10:00:00Z')] } })
    http.get.mockResolvedValueOnce({ data: { events: [ev('FxSwapRefunded', 'r1', '2026-10-04T11:00:00Z')] } })
    const rows = await fxService.swapEvents('local')
    expect(rows.map((r) => [r.txId, r.status])).toEqual([['r1', 'refunded'], ['s1', 'settled']])
  })

  it('routes: one failed half fails the feed, on a peer frame too', async () => {
    http.get.mockRejectedValueOnce(answered(500)).mockResolvedValueOnce({ data: { events: [] } })
    await expect(fxService.routeEvents('local', 50)).rejects.toThrow('500')
    http.peerGet.mockRejectedValueOnce(answered(502)).mockResolvedValueOnce({ events: [] })
    await expect(fxService.routeEvents('sbx-alpha', 50, 'peer-token')).rejects.toThrow('502')
    http.peerGet.mockResolvedValueOnce({ events: [ev('FxRouteSettled', 'rt1', '2026-10-04T12:00:00Z')] }).mockResolvedValueOnce({ events: [] })
    const rows = await fxService.routeEvents('sbx-alpha', 50, 'peer-token')
    expect(rows.map((r) => r.routeId)).toEqual(['rt1'])
  })
})
