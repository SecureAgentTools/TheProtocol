/**
 * V0657 (b): what the console sends and reads for orgs v2.
 *  - the hosted logo (a form upload), "show my org", the join requests and the public list ask the routes they name;
 *  - a discovered agent carries the organization its home states: from the card (a single read) and from the discover
 *    list's `org` field; a card's own provider.name is never taken for one.
 * RED on e143dd798: none of these calls exist and no agent carries an orgMark.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const h = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('./client', () => ({ apiClient: h, default: h }))
vi.mock('@/services/api/client', () => ({ apiClient: h, default: h }))

import { organizationService } from './organizationService'
import { discoveryService } from './discovery'
import { ORG_EXTENSION_URI } from '@/services/orgMark'

beforeEach(() => Object.values(h).forEach((f) => f.mockReset()))

describe('orgs v2 calls', () => {
  it('uploads the logo as a form, and the mark, the requests and the list ask their routes', async () => {
    h.put.mockResolvedValue({ data: { logo: '/api/v1/organizations/o1/logo?v=1' } })
    await organizationService.uploadLogo('o1', new Blob(['x'], { type: 'image/png' }))
    expect(h.put.mock.calls[0][0]).toBe('/organizations/o1/logo')
    expect(h.put.mock.calls[0][1]).toBeInstanceOf(FormData)
    await organizationService.setAgentMark('o1', 'did:theprotocol:eu:a', false)
    expect(h.put).toHaveBeenLastCalledWith('/organizations/o1/agents/did%3Atheprotocol%3Aeu%3Aa/mark', { show: false })
    h.get.mockResolvedValue({ data: { items: [], can_decide: false } })
    await organizationService.listAgentRequests('o1')
    expect(h.get).toHaveBeenLastCalledWith('/organizations/o1/agent-requests', { params: { status: 'pending' } })
    h.post.mockResolvedValue({ data: { id: 'oar_1' } })
    await organizationService.createAgentRequest('o1', { agent_did: 'did:x', note: 'n' })
    expect(h.post).toHaveBeenLastCalledWith('/organizations/o1/agent-requests', { agent_did: 'did:x', note: 'n' })
    await organizationService.decideAgentRequest('o1', 'oar_1', 'decline', { note: 'not now' })
    // V0658 (s): a decision's 409 is an answer the panel words itself (an accept that would move the agent out of
    // another organization asks first), never the client's global alarm
    expect(h.post).toHaveBeenLastCalledWith('/organizations/o1/agent-requests/oar_1/decline', { note: 'not now' },
      { expectedStatuses: [409] })
    h.delete.mockResolvedValue({ data: { status: 'withdrawn' } })
    await organizationService.withdrawAgentRequest('o1', 'oar_1')
    expect(h.delete).toHaveBeenLastCalledWith('/organizations/o1/agent-requests/oar_1')
    await organizationService.deleteLogo('o1')
    expect(h.delete).toHaveBeenLastCalledWith('/organizations/o1/logo')
    h.get.mockResolvedValue({ data: { organizations: [], total: 0, home: {} } })
    await organizationService.listListedOrganizations()
    expect(h.get).toHaveBeenLastCalledWith('/organizations/public/listed')
  })
})

describe('a discovered agent carries its home\'s organization mark', () => {
  const params = { version: 1, id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions', logo: null,
    home: { name: 'EU', origin: 'https://eu.example', console: null }, page: null }

  it('from the card, never from its provider.name', async () => {
    vi.spyOn(discoveryService, 'fetchAgentMetadata').mockResolvedValue([])
    h.get.mockResolvedValueOnce({ data: { id: 'c1', name: 'a', agent_did: 'did:x:1', is_active: true,
      card_data: { name: 'a', provider: { name: 'Acme Labs' }, extensions: [{ uri: ORG_EXTENSION_URI, params }] } } })
    const a = await discoveryService.lookupByDID('did:x:1')
    expect(a.orgMark?.name).toBe('TheProtocol Sessions')
    h.get.mockResolvedValueOnce({ data: { id: 'c2', name: 'b', agent_did: 'did:x:2', is_active: true,
      card_data: { name: 'b', provider: { name: 'Acme Labs' } } } })
    expect((await discoveryService.lookupByDID('did:x:2')).orgMark).toBeNull()
  })

  it('from the discover list\'s org field', async () => {
    h.get.mockResolvedValueOnce({ data: { items: [{ id: 'c1', did: 'did:x:1', name: 'a', is_local: true, org: params },
      { id: 'c2', did: 'did:x:2', name: 'b', is_local: false, org: null }], total: 2 } })
    const out: any = await discoveryService.discover({ q: 'a' })
    const items = out.items || out.results || out.agents
    expect(items[0].orgMark?.slug).toBe('sessions')
    expect(items[1].orgMark).toBeNull()
  })
})
