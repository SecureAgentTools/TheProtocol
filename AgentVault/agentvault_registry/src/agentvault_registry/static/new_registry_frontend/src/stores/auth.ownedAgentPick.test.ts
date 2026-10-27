/**
 * §FESUITE (2026-10-10): the only agent you can act as here is acted as on its own. A member whose one agent was made
 * elsewhere (the API, another browser, a phone: owned on this registry, no secret saved in this browser) signed in acting
 * as nobody and met the agent picker on the first page that needs one (the console suite's lifecycle 82). With several
 * such agents the console chooses none: the person picks once, and it remembers. The store's own client and harness
 * (auth.agentRetry.test.ts), the registry answered per test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const mint = vi.hoisted(() => ({ fn: vi.fn() }))
vi.mock('@/services/api/peerDirect', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  mintAgentTokenAt: mint.fn,
}))
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

const SAVED = 'did:theprotocol:saved-agent'
const OWNED = 'did:theprotocol:owned-agent'
// what the registry's client throws: a request with no answer, and one answered with a status
const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const status = (s: number) => new AxiosError(`Request failed with status code ${s}`, s >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST',
  undefined, undefined, { status: s, statusText: '', data: {}, headers: {}, config: {} } as any)

/** what the registry answers: `listFails` > 0: that many agent-list reads get no answer; `listOnce`: the next list read
 *  throws it (an error) or answers it as its body (anything else); `ownerToken`: the owner sign-in's answers in turn */
let listFails = 0
let listOnce: unknown = null
let listRows: any[] = []
let ownerToken: Array<'ok' | Error> = []
let listReads = 0

function registry() {
  vi.spyOn(apiClient, 'get').mockImplementation(async (url: string, cfg?: any) => {
    if (url === '/developers/me/agents' && !cfg?.params?.include_dids) {
      listReads += 1
      if (listFails > 0) { listFails -= 1; throw noAnswer() }
      if (listOnce !== null) { const x = listOnce; listOnce = null; if (x instanceof Error) throw x; return { data: x } as any }
      return { data: listRows.map(r => ({ ...r })) } as any
    }
    return { data: [] } as any
  })
  vi.spyOn(apiClient, 'post').mockImplementation(async (url: string) => {
    if (url.endsWith('/session-token')) {
      const next = ownerToken.length > 1 ? ownerToken.shift()! : ownerToken[0]
      if (next instanceof Error || next === undefined) throw next ?? noAnswer()
      return { data: { access_token: 'owner.jwt' } } as any
    }
    return { data: { balances: {} } } as any
  })
}

/** a signed-in developer whose console saved `did` as the active agent */
function signedIn(did: string) {
  localStorage.setItem('activeAgentId', did)
  const store = useAuthStore()
  store.token = 'dev.jwt'
  store.user = { id: 7, role: 'developer', email: 'd@x' } as any
  return store
}

/** the saved secret for SAVED lives in this browser (an agent the list does not carry: the secret road) */
function savedSecret() {
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({
    [SAVED]: { client_id: 'cid', client_secret: 'sec', name: 'Saved' },
  } as any)
}

const errorsShown = () => ui.showError.mock.calls.map(c => c[0])

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  listFails = 0; listOnce = null; listRows = []; ownerToken = []; listReads = 0
  mint.fn.mockReset()
  Object.values(ui).forEach(f => f.mockReset())
  // the store boots from nothing (no stored session), then the test signs it in
  vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'isAuthenticated').mockReturnValue(true)
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({} as any)
  vi.spyOn(agentCredentialsStore, 'mergeWithStoredCredentials').mockImplementation((a: any) => a)
  vi.spyOn(agentCredentialsStore, 'claim').mockReturnValue(0)
  vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null)
  vi.spyOn(agentDidsCache, 'cacheAgents').mockImplementation(() => {})
  registry()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})


const SECOND = 'did:theprotocol:second-owned'

/** a signed-in developer with no saved choice in this browser */
function signedInFresh() {
  const store = useAuthStore()
  store.token = 'dev.jwt'
  store.user = { id: 7, role: 'developer', email: 'd@x' } as any
  return store
}

describe('the only agent you can act as here', () => {
  it('is acted as on its own, through your session (no secret, no saved choice)', async () => {
    listRows = [{ did: OWNED, name: 'Owned' }]
    ownerToken = ['ok']
    const store = signedInFresh()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent?.did, 'the console acts as the member\'s only agent').toBe(OWNED)
    expect(store.agentToken).toBe('owner.jwt')
    expect(localStorage.getItem('activeAgentId'), 'and remembers it').toBe(OWNED)
  })

  it('with two agents of yours, none is chosen for you', async () => {
    listRows = [{ did: OWNED, name: 'Owned' }, { did: SECOND, name: 'Second' }]
    ownerToken = ['ok']
    const store = signedInFresh()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent).toBeNull()
  })

  it('your saved choice still wins over the only-agent rule', async () => {
    listRows = [{ did: OWNED, name: 'Owned' }, { did: SECOND, name: 'Second' }]
    ownerToken = ['ok']
    localStorage.setItem('activeAgentId', SECOND)
    const store = signedInFresh()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent?.did).toBe(SECOND)
  })

  it('a refused session sign-in (401) leaves you acting as nobody, and is not asked again', async () => {
    listRows = [{ did: OWNED, name: 'Owned' }]
    ownerToken = [status(401)]
    const store = signedInFresh()
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent).toBeNull()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(store.activeAgent).toBeNull()
  })
})
