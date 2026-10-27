/**
 * §MCPTEST30 (V0640): the console never offers to act as an agent the server lists as revoked or suspended.
 *
 * GET /developers/me/agents lists every status, newest first. On sbx-beta (2026-10-24) the shared admin's ten newest
 * agents were deleted throwaways; the store took every listed row as one it could act as (canActAs: yours, here, a
 * DID), and the owner rail refused each (403 "This agent is revoked: it cannot act"). The store's own client and
 * harness (as auth.ownedAgentPick.test.ts), the registry answered per test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const ui = vi.hoisted(() => ({
  showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn(),
}))
vi.mock('./ui', () => ({ useUIStore: () => ui }))
vi.mock('./globalReset', () => ({ globalReset: vi.fn() }))

import { apiClient } from '@/services/api/client'
import { authService } from '@/services/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentDidsCache } from '@/services/agentDidsCache'
import { useAuthStore } from './auth'

const ACTIVE = 'did:theprotocol:still-active'
const GONE = ['did:theprotocol:gone-1', 'did:theprotocol:gone-2', 'did:theprotocol:gone-3']
let listRows: any[] = []
let ownerAsked: string[] = []

beforeEach(() => {
  localStorage.clear()
  listRows = []
  ownerAsked = []
  Object.values(ui).forEach(f => f.mockReset())
  vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'isAuthenticated').mockReturnValue(true)
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({} as any)
  vi.spyOn(agentCredentialsStore, 'mergeWithStoredCredentials').mockImplementation((a: any) => a)
  vi.spyOn(agentCredentialsStore, 'claim').mockReturnValue(0)
  vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null)
  vi.spyOn(agentDidsCache, 'cacheAgents').mockImplementation(() => {})
  vi.spyOn(apiClient, 'get').mockImplementation(async (url: string, cfg?: any) => {
    if (url === '/developers/me/agents' && !cfg?.params?.include_dids) return { data: listRows.map(r => ({ ...r })) } as any
    return { data: [] } as any
  })
  vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
    if (url.endsWith('/session-token')) {
      ownerAsked.push(decodeURIComponent(url.split('/')[4]))   // /developers/me/agents/{did}/session-token
      return { data: { access_token: 'owner.jwt' } } as any
    }
    return { data: { balances: {} } } as any
  })
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.restoreAllMocks()
})

function signedIn() {
  const store = useAuthStore()
  store.token = 'dev.jwt'
  store.user = { id: 7, role: 'developer', email: 'd@x' } as any
  return store
}

describe('an agent the server lists as revoked or suspended', () => {
  it('is never acted as: the one active agent behind the deleted ones is, on its own', async () => {
    listRows = [...GONE.map(did => ({ did, name: 'gone', status: 'revoked' })), { did: ACTIVE, name: 'Active', status: 'active' }]
    const store = signedIn()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent?.did, 'the only agent that can act is the one acted as').toBe(ACTIVE)
    expect(ownerAsked, 'the owner rail is never asked for a revoked agent').toEqual([ACTIVE])
    for (const did of GONE) expect(store.canActAs(store.availableAgents.find((a: any) => a.did === did))).toBe(false)
  })

  it('a saved choice that points at a revoked agent is not restored', async () => {
    listRows = [{ did: GONE[0], name: 'gone', status: 'revoked' }, { did: ACTIVE, name: 'Active', status: 'active' },
      { did: 'did:theprotocol:other-active', name: 'Other', status: 'active' }]
    localStorage.setItem('activeAgentId', GONE[0])
    const store = signedIn()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent, 'two can act, none saved that can: the console chooses none').toBeNull()
    expect(ownerAsked).toEqual([])
  })

  it('pressed in the picker, it is said as deleted or suspended, never as missing its credentials', async () => {
    listRows = [{ did: GONE[0], name: 'Old', status: 'revoked' }, { did: GONE[1], name: 'Held', status: 'suspended' }]
    const store = signedIn()
    await store.fetchAvailableAgents({ force: true })
    store.showAgentSelector = true
    expect(await store.switchAgent(GONE[0])).toBe(false)
    expect(await store.switchAgent(GONE[1])).toBe(false)
    expect(ui.showError.mock.calls.map(c => c[0])).toEqual(['Agent deleted', 'Agent suspended'])
    expect(ownerAsked).toEqual([])
  })
})
