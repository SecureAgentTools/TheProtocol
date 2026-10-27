/**
 * §FESUITE (2026-10-09): when the one batch balance read failed, the store's fallback read balances one by one for the
 * WHOLE agent list (up to 25), not for the agents the batch asked about (local agents with credentials in this browser).
 * The recovery sweep on V0587 caught it on the shared frame admin (138 of its 200 listed agents revoked): a console that
 * booted while the API failed went on, once the API answered, to ask the balance of revoked agents (the route answers 404
 * for anything not active), of agents with no credentials here and of foreign agents. The multi-batch path always passed
 * its own batch. The store, the registry answered per test through its own client.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const ui = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }))
vi.mock('./ui', () => ({ useUIStore: () => ui }))
vi.mock('./globalReset', () => ({ globalReset: vi.fn() }))

import { apiClient } from '@/services/api/client'
import { authService } from '@/services/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentDidsCache } from '@/services/agentDidsCache'
import { useAuthStore } from './auth'

const LOCAL = 'did:theprotocol:local-with-secret'
const NO_SECRET = 'did:theprotocol:active-no-secret'
const REVOKED = 'did:theprotocol:revoked'
const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const notFound = () => new AxiosError('Request failed with status code 404', 'ERR_BAD_REQUEST', undefined, undefined,
  { status: 404, statusText: '', data: { detail: 'Agent not found or not authorized' }, headers: {}, config: {} } as any)

let balanceReads: string[] = []

function registry() {
  vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    if (url === '/developers/me/agents') {
      return { data: [
        { did: LOCAL, name: 'Local', status: 'active' },
        { did: NO_SECRET, name: 'No secret here', status: 'active' },
        { did: REVOKED, name: 'Revoked', status: 'revoked' },
      ] } as any
    }
    const m = url.match(/^\/developers\/me\/agents\/([^/]+)\/balance$/)
    if (m) {
      const did = decodeURIComponent(m[1])
      balanceReads.push(did)
      if (did !== LOCAL) throw notFound()
      return { data: { liquid_balance: '5', staked_balance: '0', total_balance: '5' } } as any
    }
    return { data: [] } as any
  })
  // the batch read gets no answer: the fallback runs
  vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
    if (url === '/developers/me/agents/balances') throw noAnswer()
    return { data: {} } as any
  })
}

describe('the balance fallback after a failed batch read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    balanceReads = []
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    // a valid developer session, as the store asks it (auth.agentRetry.test.ts does the same)
    vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
    vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
    vi.spyOn(authService, 'isAuthenticated').mockReturnValue(true)
    vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null as any)
    vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({
      [LOCAL]: { client_id: 'cid', client_secret: 'sec', name: 'Local' },
    } as any)
    registry()
  })

  it('reads one by one only the agents the batch asked about (local, with a secret here)', async () => {
    const store = useAuthStore()
    store.token = 'dev.jwt'
    store.user = { id: 7, role: 'developer', email: 'd@x' } as any
    await store.fetchAvailableAgents({ force: true })
    // the list is published before its balances hydrate (§LAZYBAL): wait for the fallback to have run
    await vi.waitFor(() => expect(balanceReads.length).toBeGreaterThan(0), { timeout: 3000 })
    for (let i = 0; i < 10; i++) await Promise.resolve()
    expect(balanceReads, 'the fallback read agents the batch never asked about (revoked, no secret here)').toEqual([LOCAL])
    const local = (store.availableAgents as any[]).find((a) => a.did === LOCAL)
    expect(Number(local?.liquidBalance ?? local?.liquid_balance), 'the one balance the fallback read is shown').toBe(5)
  })
})
