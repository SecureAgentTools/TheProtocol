import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-04) — the attestations store caught a failed read of an agent's list and emptied it, and the page said
 * "No attestations match the current filters." with its read failed. The service rejects on a failure (it does not
 * swallow), so this store is the layer that decides; it now says the read failed (myAttestationsFailed).
 */
const api = vi.hoisted(() => ({ getAttestationsByDid: vi.fn() }))
vi.mock('@/services', () => ({ attestationsApi: api }))

import { useAttestationsStore } from './attestations'

const DID = 'did:theprotocol:00000000-0000-4000-8000-000000000045'
const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the attestations list tells a failed read from "none"', () => {
  beforeEach(() => { setActivePinia(createPinia()); api.getAttestationsByDid.mockReset() })

  it('a failed read is flagged, not an empty list taken as the answer', async () => {
    const store = useAttestationsStore()
    api.getAttestationsByDid.mockRejectedValueOnce(answered(502))
    await store.loadMyAttestations(DID)
    expect(store.myAttestationsFailed).toBe(true)
    expect(store.myAttestations).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('an answer clears the flag, an empty answer included (that one is "none")', async () => {
    const store = useAttestationsStore()
    api.getAttestationsByDid.mockRejectedValueOnce(answered(502))
    await store.loadMyAttestations(DID)
    api.getAttestationsByDid.mockResolvedValueOnce({ items: [] })
    await store.loadMyAttestations(DID)
    expect(store.myAttestationsFailed).toBe(false)
    expect(store.myAttestations).toEqual([])
  })
})
