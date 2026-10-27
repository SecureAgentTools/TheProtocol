/**
 * §FEFRAME W3 (V0504) — the session hub, measured without a browser.
 *
 * 1. A direct foreign session survives a reload: the road (`via`, `baseUrl`, the account) is remembered for the tab, so
 *    `reconnect` refreshes AT the registry. Before W3 both lived in memory, a reload sent the refresh through the admin
 *    relay, which refused a non-admin, and the refresh token was deleted.
 * 2. Direct only (W4, V0507: the admin relay is gone): a 401 at the target is an answer; a refused request (no
 *    response) says the registry does not admit this console, and a relay road an older console remembered is dropped
 *    with its refresh token.
 * 3. An agent token for an agent you own needs no secret (the owner rail); a saved credential is the second road; a
 *    token about to lapse is re-minted; a network failure does not forget the refresh token.
 * 4. resetAll forgets the roads as well as the tokens.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const directLogin = vi.fn()
const directRefresh = vi.fn()
const mintAgentTokenAt = vi.fn()
const ownerPost = vi.fn()

vi.mock('@/services/api/peerDirect', async (orig) => {
  const real: any = await orig()
  return { ...real, directLogin, directRefresh, mintAgentTokenAt }
})
vi.mock('@/services/api/peer', () => ({ setDirectRoadResolver: vi.fn() }))
vi.mock('axios', async (orig) => {
  const real: any = await orig()
  const create = () => {
    const inst: any = (cfg: any) => ownerPost(cfg.url, cfg)
    inst.defaults = { baseURL: '' }
    inst.interceptors = { request: { use: vi.fn() }, response: { use: vi.fn() } }
    inst.post = (url: string, _body?: any, cfg?: any) => ownerPost(url, cfg)
    inst.get = vi.fn()
    return inst
  }
  return { ...real, default: { ...real.default, create: (c: any) => { const i = create(); i.defaults.baseURL = c?.baseURL; return i } } }
})
vi.mock('@/composables/useFrameManifest', () => ({ currentFrameManifest: () => ({ self: { key: 'sbx-alpha' } }) }))

const ASIA = 'https://asia.theprotocol.cloud'
const jwtWithExp = (secondsFromNow: number) => {
  const b64 = (o: any) => btoa(JSON.stringify(o)).replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64({ sub: 'x', exp: Math.floor(Date.now() / 1000) + secondsFromNow })}.sig`
}

async function freshHub() {
  setActivePinia(createPinia())
  const { useSessionHub } = await import('@/stores/sessions')
  return useSessionHub()
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  for (const f of [directLogin, directRefresh, mintAgentTokenAt, ownerPost]) f.mockReset()
})

describe('a foreign session survives a reload', () => {
  it('remembers the road and reconnects AT the registry, not through the relay', async () => {
    directLogin.mockResolvedValue({ access_token: 'a1', refresh_token: 'r1' })
    const hub = await freshHub()
    expect(await hub.connectAdmin('asia', 'dev@example.com', 'pw', ASIA)).toBe(true)
    expect(hub.sessionFor('asia').via).toBe('direct')
    expect(JSON.parse(sessionStorage.getItem('tp_hub_sessions')!).asia).toMatchObject({ via: 'direct', baseUrl: ASIA })
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBe('r1')

    // the reload: a new store reads the tab's memory
    directRefresh.mockResolvedValue({ access_token: 'a2', refresh_token: 'r2' })
    const after = await freshHub()
    expect(after.sessionFor('asia')).toMatchObject({ via: 'direct', baseUrl: ASIA, status: 'disconnected', adminToken: null })
    expect(await after.reconnectRemembered()).toBe(1)
    expect(directRefresh).toHaveBeenCalledWith(ASIA, 'r1')
    expect(after.sessionFor('asia').adminToken).toBe('a2')
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBe('r2')
  })

  it('a refused refresh forgets the token; a network failure keeps it for the next try', async () => {
    sessionStorage.setItem('tp_hub_sessions', JSON.stringify({ asia: { via: 'direct', baseUrl: ASIA, email: 'e' } }))
    sessionStorage.setItem('gcc_refresh:asia', 'r1')
    directRefresh.mockRejectedValueOnce({ message: 'Network Error' })
    const hub = await freshHub()
    expect(await hub.reconnect('asia')).toBe(false)
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBe('r1')
    directRefresh.mockRejectedValueOnce({ response: { status: 401, data: { detail: 'Invalid refresh token' } } })
    expect(await hub.reconnect('asia')).toBe(false)
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBeNull()
  })
})

describe('direct only', () => {
  it('a 401 at the target is an answer', async () => {
    directLogin.mockRejectedValue({ response: { status: 401, data: { detail: 'Incorrect email or password' } } })
    const hub = await freshHub()
    expect(await hub.connectAdmin('asia', 'dev@example.com', 'wrong', ASIA)).toBe(false)
    expect(hub.sessionFor('asia').error).toMatch(/Incorrect/)
  })

  it('a refused request (no response) says the registry does not admit this console, and nothing is remembered', async () => {
    directLogin.mockRejectedValue({ message: 'Network Error' })
    const hub = await freshHub()
    expect(await hub.connectAdmin('asia', 'admin@example.com', 'pw', ASIA)).toBe(false)
    expect(hub.sessionFor('asia')).toMatchObject({ via: null, status: 'error', adminToken: null })
    expect(hub.sessionFor('asia').error).toMatch(/could not be reached from this console/)
    expect(sessionStorage.getItem('tp_hub_sessions')).toBeNull()
  })

  it('a registry with no known address is not guessed at', async () => {
    const hub = await freshHub()
    expect(await hub.connectAdmin('asia', 'admin@example.com', 'pw')).toBe(false)
    expect(directLogin).not.toHaveBeenCalled()
    expect(hub.sessionFor('asia').error).toMatch(/no known address/)
  })

  it('a relay road an older console remembered is dropped with its refresh token', async () => {
    sessionStorage.setItem('tp_hub_sessions', JSON.stringify({
      eu: { via: 'relay', baseUrl: null, email: 'e' }, asia: { via: 'direct', baseUrl: ASIA, email: 'e' },
    }))
    sessionStorage.setItem('gcc_refresh:eu', 'r-eu')
    sessionStorage.setItem('gcc_refresh:asia', 'r-asia')
    const hub = await freshHub()
    expect(hub.sessionFor('eu').via).toBeNull()
    expect(sessionStorage.getItem('gcc_refresh:eu')).toBeNull()
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBe('r-asia')
    expect(Object.keys(JSON.parse(sessionStorage.getItem('tp_hub_sessions')!))).toEqual(['asia'])
    expect(await hub.reconnect('eu')).toBe(false)
    expect(directRefresh).not.toHaveBeenCalled()
  })
})

describe('agent tokens: the owner rail first, the saved secret second', () => {
  it('mints with your developer session there, no secret', async () => {
    directLogin.mockResolvedValue({ access_token: 'dev-asia', refresh_token: 'r' })
    const owned = jwtWithExp(1800)
    ownerPost.mockResolvedValue({ data: { access_token: owned, expires_in: 1800, via: 'owner' } })
    const hub = await freshHub()
    await hub.connectAdmin('asia', 'dev@example.com', 'pw', ASIA)
    expect(await hub.ensureAgentToken('asia', 'did:theprotocol:a1')).toBe(owned)
    expect(ownerPost.mock.calls[0][0]).toBe('/developers/me/agents/did%3Atheprotocol%3Aa1/session-token')
    expect(mintAgentTokenAt).not.toHaveBeenCalled()
    // cached while fresh
    expect(await hub.ensureAgentToken('asia', 'did:theprotocol:a1')).toBe(owned)
    expect(ownerPost).toHaveBeenCalledTimes(1)
  })

  it('a token about to lapse is re-minted', async () => {
    directLogin.mockResolvedValue({ access_token: 'dev-asia', refresh_token: 'r' })
    ownerPost.mockResolvedValueOnce({ data: { access_token: jwtWithExp(30) } })
      .mockResolvedValueOnce({ data: { access_token: jwtWithExp(1800) } })
    const hub = await freshHub()
    await hub.connectAdmin('asia', 'dev@example.com', 'pw', ASIA)
    const first = await hub.ensureAgentToken('asia', 'did:x')
    const second = await hub.ensureAgentToken('asia', 'did:x')
    expect(second).not.toBe(first)
    expect(ownerPost).toHaveBeenCalledTimes(2)
  })

  it('an agent you do not own there falls to the saved credential at its own registry', async () => {
    directLogin.mockResolvedValue({ access_token: 'dev-asia', refresh_token: 'r' })
    ownerPost.mockRejectedValue({ response: { status: 404, data: { detail: 'Agent not found or not yours' } } })
    mintAgentTokenAt.mockResolvedValue({ access_token: 'by-secret' })
    const { agentCredentialsStore } = await import('@/services/agentCredentialsStore')
    vi.spyOn(agentCredentialsStore, 'getCredentials').mockReturnValue({
      did: 'did:y', client_id: 'cid', client_secret: 'secret-secret-secret', registry_url: ASIA,
    } as any)
    const hub = await freshHub()
    await hub.connectAdmin('asia', 'dev@example.com', 'pw', ASIA)
    expect(await hub.ensureAgentToken('asia', 'did:y')).toBe('by-secret')
    expect(mintAgentTokenAt).toHaveBeenCalledWith(ASIA, 'cid', 'secret-secret-secret')
    expect(hub.sessionFor('asia').agentVia['did:y']).toBe('secret')
  })

  it('says why when there is no road at all', async () => {
    const { agentCredentialsStore } = await import('@/services/agentCredentialsStore')
    vi.spyOn(agentCredentialsStore, 'getCredentials').mockReturnValue(null)
    const hub = await freshHub()
    expect(await hub.ensureAgentToken('asia', 'did:z')).toBeNull()
    expect(hub.lastAgentError['did:z']).toMatch(/no session on that registry/)
  })
})

describe('the end of the home session', () => {
  it('resetAll forgets the roads and the refresh tokens, and nothing else', async () => {
    sessionStorage.setItem('tp_hub_sessions', JSON.stringify({ asia: { via: 'direct', baseUrl: ASIA, email: 'e' } }))
    sessionStorage.setItem('gcc_refresh:asia', 'r1')
    sessionStorage.setItem('unrelated', 'keep')
    const hub = await freshHub()
    hub.resetAll()
    expect(sessionStorage.getItem('tp_hub_sessions')).toBeNull()
    expect(sessionStorage.getItem('gcc_refresh:asia')).toBeNull()
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
    expect(Object.keys(hub.sessions)).toEqual([])
  })
})
