/**
 * V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: the settlements store closes a settlement with a reason, keeps
 * the registry's words when it refuses, and files the new end states under Failed, never under Pending.
 * RED on 4b79322d7: the store has no close.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ list: vi.fn(), close: vi.fn() }))
vi.mock('@/services/api/settlements', () => ({
  settlementsApi: { list: (...a: unknown[]) => h.list(...a), close: (...a: unknown[]) => h.close(...a),
    approve: vi.fn(), reject: vi.fn(), listPeerConfigs: vi.fn(), updatePeerConfig: vi.fn() },
}))

import { useSettlementsStore } from './settlements'

const rows = ['NOT_DELIVERED', 'REFUSED', 'CLOSED', 'PENDING_SLASH', 'SETTLED'].map((status, i) => ({ id: `s${i}`, status }))

describe('the settlements store and the end states', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.list.mockReset(); h.close.mockReset() })

  it('closes with a reason and reads the list again', async () => {
    const s = useSettlementsStore()
    h.close.mockResolvedValueOnce({ status: 'CLOSED' })
    h.list.mockResolvedValueOnce({ count: 0, stats: null, settlements: [] })
    await (s as any).close('s1', 'the peers never knew this address')
    expect(h.close).toHaveBeenCalledWith('s1', 'the peers never knew this address')
    expect(h.list).toHaveBeenCalled()
  })

  it("keeps the registry's words when it refuses", async () => {
    const s = useSettlementsStore()
    const detail = 'Settlement s1 is SETTLED: a settlement that moved money is not closed'
    h.close.mockRejectedValueOnce(new AxiosError('Request failed with status code 409', 'ERR_BAD_REQUEST', undefined, undefined,
      { status: 409, statusText: '', data: { detail }, headers: {}, config: {} } as any))
    await expect((s as any).close('s1', 'why')).rejects.toBeTruthy()
    expect(s.error).toBe(detail)
  })

  it('files the end states under Failed, never under Pending', async () => {
    const s = useSettlementsStore()
    s.settlements = rows as any
    s.setFilter('failed')
    expect(s.filteredSettlements.map(r => r.status).sort()).toEqual(['CLOSED', 'NOT_DELIVERED', 'REFUSED'])
    s.setFilter('pending')
    expect(s.filteredSettlements.map(r => r.status)).toEqual(['PENDING_SLASH'])
  })
})
