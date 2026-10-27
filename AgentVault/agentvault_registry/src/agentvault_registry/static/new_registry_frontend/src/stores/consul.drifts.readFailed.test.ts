import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-04) — /admin/compliance said "No drift events recorded." with its drift read failed (the census on
 * V0571, fes-20261004T161229Z-d0d7: a FALSE "none"): the store's catch filled the page's shared banner and never
 * driftsError, which is what the drift panel reads to tell a failed read from none. The service does not swallow (it
 * awaits the client), so this store is the layer that decides.
 */
const api = vi.hoisted(() => ({ getDrifts: vi.fn() }))
vi.mock('@/services/api/consulApi', () => ({ consulApi: api }))

import { useConsulStore } from './consul'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: { detail: 'Bad Gateway' } } })

describe('the drift panel tells a failed read from "none"', () => {
  beforeEach(() => { setActivePinia(createPinia()); api.getDrifts.mockReset() })

  it('a failed read sets driftsError, so the panel never draws "No drift events recorded."', async () => {
    const store = useConsulStore()
    api.getDrifts.mockRejectedValueOnce(answered(502))
    await store.loadDrifts()
    expect(store.driftsError).toMatch(/Failed to load federation drifts/)
    expect(store.drifts).toEqual([])
    expect(store.loadingDrifts).toBe(false)
  })

  it('a read that answers clears it, an empty answer included (that one is "none")', async () => {
    const store = useConsulStore()
    api.getDrifts.mockRejectedValueOnce(answered(502))
    await store.loadDrifts()
    api.getDrifts.mockResolvedValueOnce({ drifts: [], by_type: {} })
    await store.loadDrifts()
    expect(store.driftsError).toBeNull()
    expect(store.drifts).toEqual([])
  })
})
