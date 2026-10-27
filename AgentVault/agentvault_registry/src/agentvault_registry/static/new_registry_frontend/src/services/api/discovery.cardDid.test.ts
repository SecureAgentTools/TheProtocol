import { describe, it, expect, beforeEach, vi } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { discoveryService } from './discovery'

beforeEach(() => { (apiClient.get as any).mockReset(); vi.restoreAllMocks() })

describe("an agent's view names the agent its card names, never another one of the same name", () => {
  it("takes the card row's agent_did, and no number from the viewer's other agent called the same", async () => {
    // the viewer once owned an agent named Sundial (deleted since); the card on screen is the new Sundial
    vi.spyOn(discoveryService, 'fetchAgentMetadata').mockResolvedValue([
      { name: 'Sundial', did: 'did:theprotocol:x:old', liquid_balance: 99, staked_balance: 1, reputation_score: 7 } as any,
    ])
    ;(apiClient.get as any).mockResolvedValueOnce({ data: {
      id: 'card-new-1', name: 'Sundial', agent_did: 'did:theprotocol:x:new', is_active: true, card_data: { name: 'Sundial' },
    } })
    const a = await discoveryService.lookupByDID('did:theprotocol:x:new')
    expect(a.did).toBe('did:theprotocol:x:new')
    expect(a.liquid_balance).toBe(0)
    expect(a.reputation_score).toBe(0)
  })

  it('still merges the numbers of the same agent (the control)', async () => {
    vi.spyOn(discoveryService, 'fetchAgentMetadata').mockResolvedValue([
      { name: 'Quill', did: 'did:theprotocol:x:quill', liquid_balance: 42, staked_balance: 8, reputation_score: 3 } as any,
    ])
    ;(apiClient.get as any).mockResolvedValueOnce({ data: {
      id: 'card-quill-1', name: 'Quill', agent_did: 'did:theprotocol:x:quill', is_active: true, card_data: { name: 'Quill' },
    } })
    const a = await discoveryService.lookupByDID('did:theprotocol:x:quill')
    expect(a.did).toBe('did:theprotocol:x:quill')
    expect(a.liquid_balance).toBe(42)
    expect(a.total_balance).toBe(50)
  })
})
