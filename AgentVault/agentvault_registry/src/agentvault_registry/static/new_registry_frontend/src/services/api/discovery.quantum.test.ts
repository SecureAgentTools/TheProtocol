import { describe, it, expect, beforeEach, vi } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { discoveryService } from './discovery'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'

/**
 * V0660 (e): discover() and the quantum workload extension (V0660 (a)'s discover parameters, item facets and
 * facets.quantum). With no quantum filter the request is the one before V0660, key for key; the filters go out as the
 * registry's quantum_* parameters; the item's and the page's quantum facets come back, and read null where the frame
 * sent none (an off frame sends no such field).
 */
const answer = (data: unknown) => (apiClient.get as any).mockResolvedValueOnce({ data })
const sent = (): Record<string, unknown> => (apiClient.get as any).mock.calls.at(-1)[1].params

beforeEach(() => (apiClient.get as any).mockReset())

describe('the quantum filters on the discover request', () => {
  it('none asked: the query carries exactly the keys it carried before V0660', async () => {
    answer({ items: [], total: 0 })
    await discoveryService.discover({ q: 'x', bonded_only: true })
    expect(Object.keys(sent()).sort()).toEqual(['bonded_only', 'limit', 'offset', 'q', 'sort'])
    answer({ items: [], total: 0 })
    await discoveryService.discover({ q: 'x', quantum: {} })
    expect(Object.keys(sent()).some((k) => k.startsWith('quantum'))).toBe(false)
  })

  it('asked: each filter is its own quantum_* parameter; anything else in the bag is not sent', async () => {
    answer({ items: [], total: 0 })
    await discoveryService.discover({ quantum: { quantum_modality: 'superconducting', quantum_min_qubits: '20', quantum_rung: '2', other: 'x' } })
    expect(sent()).toMatchObject({ quantum_modality: 'superconducting', quantum_min_qubits: '20', quantum_rung: '2' })
    expect('other' in sent()).toBe(false)
    expect('quantum' in sent()).toBe(false)
  })
})

describe('the quantum facets in the answer', () => {
  it('an item carries its quantum facets; a page carries facets.quantum', async () => {
    answer({ items: [{ id: 'c1', agent_did: fx.did, name: 'Lattice Works', is_local: true, quantum: fx.discoverItemFacets },
      { id: 'c2', agent_did: 'did:theprotocol:plain', name: 'Plain', is_local: true, quantum: null }],
    total: 2, facets: { total: 2, quantum: fx.discoverFacets } })
    const r = await discoveryService.discover({})
    expect(r.results[0].quantum).toEqual(fx.discoverItemFacets)
    expect(r.results[1].quantum).toBeNull()
    expect(r.facets.quantum?.total).toBe(1)
    expect(r.facets.quantum?.modalities.map((m) => m.name)).toEqual(['simulator', 'superconducting'])
  })

  it('a frame that does not serve the extension sends no such field: both read null', async () => {
    answer({ items: [{ id: 'c1', agent_did: 'did:theprotocol:a', name: 'A', is_local: true }], total: 1, facets: { total: 1 } })
    const r = await discoveryService.discover({})
    expect(r.results[0].quantum).toBeNull()
    expect(r.facets.quantum).toBeNull()
  })
})
