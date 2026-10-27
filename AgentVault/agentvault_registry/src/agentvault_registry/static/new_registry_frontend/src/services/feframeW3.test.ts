// @vitest-environment node
/**
 * §FEFRAME W3 — the token a request carries comes from the server's own route map, and a 401 ends the session only
 * when the session itself is refused. Each test has its control: the old substring rule's answer.
 */
import { describe, it, expect } from 'vitest'
import { tierOf, apiPath, compileTemplate, actsAsAgent, asksAboutSession, tierDisagreements, AUTH_TIER_ROWS }
  from '@/services/api/authTiers'
import { isAgentEndpoint } from '@/services/api/tier'

describe('the token map is the server\'s', () => {
  it('carries the generated rows', () => {
    expect(AUTH_TIER_ROWS).toBeGreaterThan(150)
  })

  it('reads FastAPI templates: one segment per {x}, the rest for {x:path}, literals escaped', () => {
    expect(compileTemplate('/api/v1/agents/{agent_did}').test('/api/v1/agents/did:theprotocol:x')).toBe(true)
    expect(compileTemplate('/api/v1/agents/{agent_did}').test('/api/v1/agents/a/b')).toBe(false)
    expect(compileTemplate('/static/{p:path}').test('/static/a/b/c.js')).toBe(true)
    expect(compileTemplate('/api/v1/x.y').test('/api/v1/xzy')).toBe(false)
  })

  it('normalizes what the client sends: relative, absolute, query, trailing slash', () => {
    expect(apiPath('/teg/transfer')).toBe('/api/v1/teg/transfer')
    expect(apiPath('/teg/transfer?x=1#y')).toBe('/api/v1/teg/transfer')
    expect(apiPath('https://sandbox-b.theprotocol.cloud/api/v1/teg/transfer/')).toBe('/api/v1/teg/transfer')
    expect(apiPath('/api/v1/agents/spawn')).toBe('/api/v1/agents/spawn')
    expect(apiPath('/teg/transfer', 'https://eu.theprotocol.cloud/api/v1')).toBe('/api/v1/teg/transfer')
  })

  it('the routes the old rules sent the wrong token to', () => {
    // agent-tier routes the old rules sent a DEVELOPER token to (a 401)
    for (const [m, u] of [['get', '/agents/me'], ['post', '/bridge/transfer'], ['post', '/agents/reputation-bond/deposit'],
      ['get', '/enforcement/my-status'], ['post', '/agent/enable-mtls']] as const) {
      expect(tierOf(m, u)).toBe('agent')
      expect(isAgentEndpoint(u, m)).toBe(false)          // the control: the old rule
    }
    // developer-tier routes the old rules sent an AGENT token to (a 401)
    for (const [m, u] of [['get', '/teg/staking/balance/did:theprotocol:x'], ['post', '/teg/rewards/claim'],
      ['get', '/teg/policies']] as const) {
      expect(tierOf(m, u)).toBe('developer')
      expect(isAgentEndpoint(u, m)).toBe(true)
    }
  })

  it('keeps what both agree on, and the §COCKPITBOOK collision stays a developer route', () => {
    expect(tierOf('post', '/agora/orders')).toBe('agent')
    expect(tierOf('post', '/agents/spawn')).toBe('agent')
    expect(tierOf('post', '/teg/transfer')).toBe('agent')
    expect(tierOf('get', '/exchange/portfolio')).toBe('agent')
    expect(tierOf('get', '/developers/me/exchange/portfolio')).toBe('developer')
    expect(tierOf('get', '/developers/me')).toBe('developer')
    expect(tierOf('post', '/developers/me/agents/did:theprotocol:x/session-token')).toBe('developer')
    expect(tierOf('post', '/agents/did:theprotocol:x/capabilities/issue-as-owner')).toBe('developer')
    expect(tierOf('get', '/no/such/route')).toBe('developer')
    expect(tierOf('get', '/chat/conversations')).toBe('either')
  })

  it('an either route keeps the old answer for one release, and a disagreement is counted', () => {
    // either + the old rule said agent (dispute reads) -> agent; either + the old rule said developer (chat) -> developer
    expect(actsAsAgent('/disputes/d-1', 'get')).toBe(true)
    expect(actsAsAgent('/chat/conversations', 'get')).toBe(false)
    const before = Object.keys(tierDisagreements).length
    expect(actsAsAgent('/teg/rewards/claim', 'post')).toBe(false)      // the map wins
    expect(Object.keys(tierDisagreements).length).toBe(before + 1)
    expect(Object.keys(tierDisagreements).some(k => k.includes('/api/v1/teg/rewards/claim map=developer old=agent'))).toBe(true)
  })
})

describe('one rule decides whether a 401 asks about the session', () => {
  const base = { hasSession: true, isLogin: false, isRefresh: false, onLoginPage: false, skip: false }

  it('only a 401 refused WITH this console\'s own developer token asks', () => {
    expect(asksAboutSession({ ...base, sent: 'developer' })).toBe(true)
    for (const sent of ['agent', 'public', 'caller', 'foreign', undefined] as const) {
      expect(asksAboutSession({ ...base, sent })).toBe(false)
    }
  })

  it('never for a visitor, the auth flow itself, the login page, or a caller that opted out', () => {
    expect(asksAboutSession({ ...base, sent: 'developer', hasSession: false })).toBe(false)
    expect(asksAboutSession({ ...base, sent: 'developer', isLogin: true })).toBe(false)
    expect(asksAboutSession({ ...base, sent: 'developer', isRefresh: true })).toBe(false)
    expect(asksAboutSession({ ...base, sent: 'developer', onLoginPage: true })).toBe(false)
    expect(asksAboutSession({ ...base, sent: 'developer', skip: true })).toBe(false)
  })
})

describe('the hub remembers roads, never tokens', async () => {
  const { parseHubMeta, droppedHubKeys, needsMint, mintRoad } = await import('@/services/sessionHub')

  it('reads the stored roads and drops what cannot reconnect', () => {
    expect(parseHubMeta(null)).toEqual({})
    expect(parseHubMeta('{not json')).toEqual({})
    expect(parseHubMeta('[1,2]')).toEqual({})
    const raw = JSON.stringify({
      ASIA: { via: 'direct', baseUrl: 'https://asia.theprotocol.cloud/', email: 'e' },
      lisbon: { via: 'direct' },                       // direct without an address: dropped
      eu: { via: 'relay', baseUrl: 'https://eu.theprotocol.cloud' },   // the relay is gone (W4): dropped
      sbx: { via: 'direct', baseUrl: 'javascript:alert(1)' },   // a non-http address: dropped
      junk: { via: 'telepathy', baseUrl: 'https://x' },
    })
    const m = parseHubMeta(raw)
    expect(Object.keys(m)).toEqual(['asia'])
    expect(m.asia).toMatchObject({ via: 'direct', baseUrl: 'https://asia.theprotocol.cloud' })
    expect(droppedHubKeys(raw).sort()).toEqual(['eu', 'junk', 'lisbon', 'sbx'])
    expect(droppedHubKeys(null)).toEqual([])
  })

  it('re-mints a token that is missing or about to lapse, and leaves an opaque one to the server', () => {
    const now = 1_000_000_000_000
    const tok = (exp: number) => `x.${btoa(JSON.stringify({ exp }))}.y`
    expect(needsMint(null, now)).toBe(true)
    expect(needsMint(tok(now / 1000 - 1), now)).toBe(true)
    expect(needsMint(tok(now / 1000 + 30), now)).toBe(true)             // inside the 60 s margin
    expect(needsMint(tok(now / 1000 + 3600), now)).toBe(false)
    expect(needsMint('opaque', now)).toBe(false)
  })

  it('takes the owner road before the secret', () => {
    expect(mintRoad({ haveDeveloperSession: true, haveSecret: true })).toEqual(['owner', 'secret'])
    expect(mintRoad({ haveDeveloperSession: false, haveSecret: true })).toEqual(['secret'])
    expect(mintRoad({ haveDeveloperSession: false, haveSecret: false })).toEqual([])
  })
})

describe('one importer reads every credential file the console produced', async () => {
  const { parseCredentialText, classifyEntries, exportVaultV2, normalizeEntries, isLoopbackUrl } = await import('@/services/credImport')
  const SEC = 'tp_secret_0123456789abcdef0123456789abcdef'
  const DID = 'did:theprotocol:sandbox-b.theprotocol.cloud:00000000-0000-4000-8000-000000000001'
  const home = (k: string) => k === 'sandbox-beta' ? { ok: true as const, url: 'https://sandbox-b.theprotocol.cloud' }
    : k === 'sandbox-alpha' ? { ok: true as const, url: null }
    : { ok: false as const, reason: `"${k}" is not a registry of this federation (retired or unknown)` }

  it('credential LINES keep the URL column', () => {
    const d = parseCredentialText('# comment\nsandbox-beta\thttps://sandbox-b.theprotocol.cloud/\tdev@example.com\tpw-1')
    expect(d.format).toBe('lines')
    expect(d.developers).toEqual([{ registry_key: 'sandbox-beta', registry_url: 'https://sandbox-b.theprotocol.cloud',
      email: 'dev@example.com', password: 'pw-1' }])
  })

  it('a vault v1 files each agent under its registry key, and its developer lines', () => {
    const d = parseCredentialText(JSON.stringify({ version: 1, registries: {
      'sandbox-beta': { developer: { email: 'dev@example.com', password: 'p' }, agents: [{ did: DID, client_id: 'c1', client_secret: SEC }] },
    } }))
    expect(d.format).toBe('vault-v1')
    expect(d.entries[0]).toMatchObject({ did: DID, registry_key: 'sandbox-beta' })
    expect(d.developers[0]).toMatchObject({ registry_key: 'sandbox-beta', email: 'dev@example.com' })
  })

  it('the v2 export re-imports as itself (registries by URL, agents with their registry_url)', () => {
    const v2 = exportVaultV2(
      [{ did: DID, client_id: 'c1', client_secret: SEC, name: 'B1', registry_url: 'https://sandbox-b.theprotocol.cloud' }],
      [{ key: 'sandbox-beta', name: 'Sandbox Beta', url: 'https://sandbox-b.theprotocol.cloud', email: 'dev@example.com' }],
      true)
    const d = parseCredentialText(JSON.stringify(v2))
    expect(d.format).toBe('vault-v2')
    expect(d.entries[0]).toMatchObject({ did: DID, client_secret: SEC, registry_url: 'https://sandbox-b.theprotocol.cloud' })
    expect(d.developers[0]).toMatchObject({ registry_key: 'sandbox-beta', email: 'dev@example.com' })
    expect(d.developers[0].password).toBeUndefined()                        // never stored, never exported
    expect(exportVaultV2([{ did: DID, client_id: 'c1', client_secret: SEC }], [], false).agents[0].client_secret).toBeUndefined()
  })

  it('reads entries grouped by registry, and the spellings other screens printed', () => {
    const grouped = normalizeEntries({ 'sandbox-beta': [{ agent_did: DID, client_id: 'c1', new_client_secret: SEC }] })!
    expect(grouped[0]).toMatchObject({ did: DID, client_secret: SEC, registry_key: 'sandbox-beta' })
    const spawned = normalizeEntries([{ child_did: DID, client_id: 'c2', client_secret: SEC, host: 'sandbox-b.theprotocol.cloud' }])!
    expect(spawned[0]).toMatchObject({ did: DID, registry_url: 'https://sandbox-b.theprotocol.cloud' })
  })

  it('resolves a registry key against the federation, and names one it does not know', () => {
    const rows = classifyEntries([
      { did: DID, client_id: 'c1', client_secret: SEC, registry_key: 'sandbox-beta' },
      { did: DID.replace(/1$/, '2'), client_id: 'c2', client_secret: SEC, registry_key: 'op-tokyo' },
      { did: DID.replace(/1$/, '3'), client_id: 'c3', client_secret: SEC, registry_key: 'sandbox-alpha' },
    ], () => false, home)
    expect(rows[0]).toMatchObject({ kind: 'new', registry_url: 'https://sandbox-b.theprotocol.cloud' })
    expect(rows[1].kind).toBe('invalid')
    expect(rows[1].error).toMatch(/op-tokyo.*retired or unknown/)
    expect(rows[2]).toMatchObject({ kind: 'new' })
    expect(rows[2].registry_url).toBeUndefined()                            // this registry: no URL
  })

  it('refuses a loopback or container address: it names no registry another browser can reach', () => {
    for (const u of ['http://localhost:8000', 'https://127.0.0.1', 'https://registry-a:8000', 'https://0.0.0.0'])
      expect(isLoopbackUrl(u)).toBe(true)
    expect(isLoopbackUrl('https://sandbox-b.theprotocol.cloud')).toBe(false)
    const r = classifyEntries([{ did: DID, client_id: 'c1', client_secret: SEC, registry_url: 'http://localhost:8000' }], () => false)
    expect(r[0].kind).toBe('invalid')
    expect(r[0].error).toMatch(/loopback/)
  })

  it('says what it could not read instead of guessing', () => {
    expect(parseCredentialText('').format).toBe('unreadable')
    expect(parseCredentialText('hello world').format).toBe('unreadable')
    expect(parseCredentialText('{"broken"').errors[0]).toMatch(/invalid JSON/)
  })
})
