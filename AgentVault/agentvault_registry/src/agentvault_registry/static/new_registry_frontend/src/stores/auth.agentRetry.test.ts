/**
 * §FESUITE (2026-10-04): the store's own second try for the saved agent (f5113042), measured at the store.
 * backoffRetry.test.ts pins the timer and lifecycle 60 pins one road in a browser; these pin the wiring in auth.ts:
 * which failures arm the retry, which never do, what cancels it, and that the quiet tries say nothing.
 * The registry is the store's own client (apiClient) and the bare mint (mintAgentTokenAt), answered per test.
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

describe('the saved agent comes back after a failure for want of an answer', () => {
  it('a failed agent list is read again on its own and restores the saved agent', async () => {
    savedSecret()
    mint.fn.mockResolvedValue({ access_token: 'agent.jwt' })
    listFails = 1
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.agentFetchFailed).toBe(true)
    expect(store.activeAgent).toBeNull()

    await vi.advanceTimersByTimeAsync(5_000)            // the first step
    expect(listReads).toBe(2)
    expect(store.activeAgent?.did).toBe(SAVED)
    expect(store.agentFetchFailed).toBe(false)
  })

  it("a saved secret's sign-in that got no answer is tried again, quietly, until it answers", async () => {
    savedSecret()
    mint.fn.mockRejectedValueOnce(noAnswer()).mockRejectedValueOnce(noAnswer())
      .mockResolvedValue({ access_token: 'agent.jwt' })
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent).toBeNull()
    expect(errorsShown()).toEqual(['Agent registry not reachable'])   // one toast for the first failure

    await vi.advanceTimersByTimeAsync(5_000)            // try 2: no answer again, says nothing
    expect(mint.fn).toHaveBeenCalledTimes(2)
    expect(store.activeAgent).toBeNull()
    await vi.advanceTimersByTimeAsync(9_999)            // the second step is 10 s, not 5
    expect(mint.fn).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(mint.fn).toHaveBeenCalledTimes(3)
    expect(store.activeAgent?.did).toBe(SAVED)
    expect(errorsShown()).toEqual(['Agent registry not reachable'])   // the quiet tries added none
    expect(ui.showSuccess.mock.calls.map(c => c[0])).toContain('Agent Activated')
  })

  it("an owned agent's sign-in that got no answer is tried again too (no saved secret)", async () => {
    listRows = [{ did: OWNED, name: 'Owned' }]
    ownerToken = [noAnswer(), 'ok']
    const store = signedIn(OWNED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent).toBeNull()

    await vi.advanceTimersByTimeAsync(5_000)
    expect(store.activeAgent?.did).toBe(OWNED)
  })

  it("a saved secret's sign-in answered with a server error (503) is tried again too", async () => {
    savedSecret()
    mint.fn.mockRejectedValueOnce(status(503)).mockResolvedValue({ access_token: 'agent.jwt' })
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.activeAgent).toBeNull()

    await vi.advanceTimersByTimeAsync(5_000)
    expect(store.activeAgent?.did).toBe(SAVED)
  })
})

describe('an answer is not retried', () => {
  it.each([[401, 'rejected'], [403, 'suspended']] as const)('a %s (%s) arms no second try', async (code, why) => {
    savedSecret()
    mint.fn.mockRejectedValue(status(code))
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.lastAgentAuthFailure).toBe(why)

    await vi.advanceTimersByTimeAsync(120_000)
    expect(mint.fn).toHaveBeenCalledTimes(1)
    expect(listReads).toBe(1)
  })

  it("an owned agent's sign-in refused (401) is an answer: no second try, and the saved choice stays", async () => {
    listRows = [{ did: OWNED, name: 'Owned' }]
    ownerToken = [status(401)]
    const store = signedIn(OWNED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.lastAgentAuthFailure).toBeNull()        // never read as a refused saved secret

    await vi.advanceTimersByTimeAsync(120_000)
    expect(listReads).toBe(1)
    expect(localStorage.getItem('activeAgentId')).toBe(OWNED)
  })
})

describe('a refusal, or the console\'s own error, is not an outage', () => {
  it("a saved secret refused with neither a 401 nor a 403 (a 422) arms no second try", async () => {
    savedSecret()
    mint.fn.mockRejectedValue(status(422))
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.lastAgentAuthFailure).toBe('other')
    expect(errorsShown()).toEqual(['Agent sign-in failed'])

    await vi.advanceTimersByTimeAsync(180_000)
    expect(mint.fn).toHaveBeenCalledTimes(1)
    expect(listReads).toBe(1)
  })

  it('a refused agent list (404) is read once: "could not load", and no second read', async () => {
    savedSecret()
    listOnce = status(404)
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.agentFetchFailed).toBe(true)

    await vi.advanceTimersByTimeAsync(180_000)
    expect(listReads).toBe(1)
  })

  it("an agent list that is not the registry's JSON (a page served in its place) is the console's own error: no second read", async () => {
    savedSecret()
    listOnce = '<!doctype html><title>console</title>'
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    expect(store.agentFetchFailed).toBe(true)

    await vi.advanceTimersByTimeAsync(180_000)
    expect(listReads).toBe(1)
  })
})

describe('what cancels the second try', () => {
  it('the person clearing their agent: no try may choose one for them', async () => {
    savedSecret()
    mint.fn.mockRejectedValueOnce(noAnswer()).mockResolvedValue({ access_token: 'agent.jwt' })
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    store.clearActiveAgent()

    await vi.advanceTimersByTimeAsync(120_000)
    expect(mint.fn).toHaveBeenCalledTimes(1)
    expect(store.activeAgent).toBeNull()
  })

  it("signing out: a try armed in one session never fires in the next person's", async () => {
    savedSecret()
    listFails = 1
    vi.spyOn(authService, 'logout').mockResolvedValue(undefined as any)
    const store = signedIn(SAVED)
    await store.fetchAvailableAgents({ force: true })
    await store.logout()
    // someone signs in before the first step is due (the try's own "signed in?" check cannot tell them apart)
    store.token = 'next.jwt'
    store.user = { id: 8, role: 'developer', email: 'e@x' } as any

    await vi.advanceTimersByTimeAsync(120_000)
    expect(listReads).toBe(1)
  })
})
