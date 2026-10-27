/**
 * §FEFRAME W1 (V0502) — login safety, measured without a browser.
 *
 * 1. An agent sign-in goes out on the BARE client with the agent's client credentials and nothing else: no developer
 *    token, for a foreign registry and for this one alike (the apiClient path handed the home developer JWT to other
 *    registries).
 * 2. Only a 401 says a secret is wrong; a refused cross-origin request is "unreachable", never "rejected".
 * 3. Saved credentials belong to a developer: another account's rows are invisible, unclaimed legacy rows stay usable
 *    and are claimed, "forget all" never touches another account's rows.
 * 4. An axios failure is read by its status (the handler's status branches were dead).
 * 5. The per-registry session store forgets everything, including refresh tokens a reload left in storage.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

const { posted } = vi.hoisted(() => ({ posted: [] as Array<{ url: string; body: any; config: any }> }))
vi.mock('axios', async (orig) => {
  const real: any = await orig()
  const fake = {
    post: vi.fn(async (url: string, body: any, config: any) => {
      posted.push({ url, body, config })
      return { data: { access_token: 'agent.jwt', token_type: 'bearer' } }
    }),
    get: vi.fn(),
    // the shared apiClient (imported through the session store) registers its interceptors at import
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  }
  return { ...real, default: { ...real.default, create: () => fake } }
})

import { mintAgentTokenAt, classifyAgentMintFailure } from '@/services/api/peerDirect'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { credentialVault, PLAIN_KEY } from '@/services/credentialVault'
import { httpErrorFields, messageOf } from '@/utils/httpError'

describe('agent sign-in on the bare client', () => {
  beforeEach(() => { posted.length = 0 })

  it('mints at a FOREIGN registry with the client credentials and no Authorization header', async () => {
    const out = await mintAgentTokenAt('https://asia.theprotocol.cloud', 'cid', 'sec')
    expect(out.access_token).toBe('agent.jwt')
    expect(posted).toHaveLength(1)
    expect(posted[0].url).toBe('https://asia.theprotocol.cloud/api/v1/auth/agent/token')
    const body = new URLSearchParams(String(posted[0].body))
    expect(body.get('username')).toBe('cid')
    expect(body.get('password')).toBe('sec')
    expect(body.get('grant_type')).toBe('password')
    const headers = posted[0].config?.headers || {}
    expect(Object.keys(headers).map(k => k.toLowerCase())).toEqual(['content-type'])
  })

  it('mints at THIS registry on a relative base, still without a developer token', async () => {
    await mintAgentTokenAt(null, 'cid', 'sec')
    expect(posted[0].url).toBe('/api/v1/auth/agent/token')
    expect(JSON.stringify(posted[0].config)).not.toMatch(/authorization/i)
  })

  it('classifies failures: only a 401 is a wrong secret', () => {
    expect(classifyAgentMintFailure({ message: 'Network Error' })).toBe('unreachable')
    expect(classifyAgentMintFailure({ response: { status: 401 } })).toBe('rejected')
    expect(classifyAgentMintFailure({ response: { status: 403 } })).toBe('suspended')
    expect(classifyAgentMintFailure({ response: { status: 502 } })).toBe('other')
  })
})

describe('saved credentials belong to a developer', () => {
  const row = (did: string, extra: Record<string, unknown> = {}) =>
    ({ did, client_id: `c-${did}`, client_secret: `s-${did}`, ...extra })

  beforeEach(async () => {
    agentCredentialsStore.setCurrentOwner(null)
    await credentialVault.setAll({})
  })

  it('stamps the logged-in developer on a new row, and hides it from another developer', async () => {
    agentCredentialsStore.setCurrentOwner(7)
    agentCredentialsStore.storeCredentials(row('did:a'))
    expect(agentCredentialsStore.getCredentials('did:a')?.owner_developer_id).toBe('7')
    agentCredentialsStore.setCurrentOwner(8)
    expect(agentCredentialsStore.getCredentials('did:a')).toBeNull()
    expect(agentCredentialsStore.getAllCredentials()).toEqual({})
    agentCredentialsStore.setCurrentOwner(null)
    expect(agentCredentialsStore.getCredentials('did:a')).toBeNull()
  })

  it('keeps an unclaimed legacy row usable and claims it for the confirmed owner only', async () => {
    await credentialVault.setAll({ 'did:legacy': row('did:legacy') })      // saved before V0502: no owner
    agentCredentialsStore.setCurrentOwner(7)
    expect(agentCredentialsStore.getCredentials('did:legacy')).not.toBeNull()
    expect(agentCredentialsStore.claim(['did:legacy', 'did:absent'])).toBe(1)
    agentCredentialsStore.setCurrentOwner(8)
    expect(agentCredentialsStore.getCredentials('did:legacy')).toBeNull()
    expect(agentCredentialsStore.claim(['did:legacy'])).toBe(0)           // never taken over from another account
  })

  it('"forget all" removes only what the logged-in developer can see', async () => {
    agentCredentialsStore.setCurrentOwner(7)
    agentCredentialsStore.storeCredentials(row('did:mine'))
    agentCredentialsStore.setCurrentOwner(8)
    agentCredentialsStore.storeCredentials(row('did:theirs'))
    agentCredentialsStore.clearAll()
    const raw = JSON.parse(localStorage.getItem(PLAIN_KEY) || '{}')
    expect(Object.keys(raw)).toEqual(['did:mine'])
  })

  it('a rejected secret is flagged on merge and cleared by the next success', async () => {
    agentCredentialsStore.setCurrentOwner(7)
    agentCredentialsStore.storeCredentials(row('did:r'))
    agentCredentialsStore.markRejected('did:r')
    const [merged] = agentCredentialsStore.mergeWithStoredCredentials([{ did: 'did:r' }])
    expect(merged.hasCredentials).toBe(true)
    expect(merged.hasInvalidCredentials).toBe(true)
    agentCredentialsStore.clearRejected('did:r')
    const [again] = agentCredentialsStore.mergeWithStoredCredentials([{ did: 'did:r' }])
    expect(again.hasInvalidCredentials).toBe(false)
  })
})

describe('an HTTP failure is read by its status', () => {
  it('reads the status and the RFC 7807 detail of an axios error', () => {
    const f = httpErrorFields({ isAxiosError: true, response: { status: 404, statusText: 'Not Found', data: { detail: 'Agent not found' } } })
    expect(f).toMatchObject({ statusCode: 404, message: 'Agent not found' })
  })

  it('names a failure with no response a network error, and ignores plain errors', () => {
    expect(httpErrorFields({ isAxiosError: true })).toMatchObject({ code: 'NETWORK_ERROR' })
    expect(httpErrorFields(new Error('boom'))).toBeNull()
  })

  it("words FastAPI's validation list and the unified envelope", () => {
    expect(messageOf({ detail: [{ msg: 'field required' }, { msg: 'too short' }] })).toBe('field required; too short')
    expect(messageOf({ error: { detail: 'from the envelope' } })).toBe('from the envelope')
    expect(messageOf({}, 'Bad Request')).toBe('Bad Request')
  })
})

describe('the per-registry session store forgets everything', () => {
  it('resetAll drops the sessions and every gcc_refresh key in storage', async () => {
    const { setActivePinia, createPinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useCommandSessions } = await import('@/stores/commandSessions')
    const cs = useCommandSessions()
    sessionStorage.setItem('gcc_refresh:asia', 'r1')
    sessionStorage.setItem('gcc_refresh:amsterdam', 'r2')
    sessionStorage.setItem('unrelated', 'keep')
    cs.sessions['asia'] = { adminToken: 't', adminEmail: 'e', status: 'connected', error: null, agentTokens: {},
      agentVia: {}, activeAgentDid: null, baseUrl: 'https://asia.theprotocol.cloud', via: 'direct', since: null }
    cs.resetAll()
    expect(Object.keys(cs.sessions)).toEqual([])
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBeNull()
    expect(sessionStorage.getItem('gcc_refresh:amsterdam')).toBeNull()
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  }, 20_000)   // the first import of the store graph (client, stores, the vault) takes seconds under a parallel suite
})
