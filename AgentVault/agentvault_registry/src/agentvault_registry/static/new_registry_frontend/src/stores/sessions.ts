/**
 * §FEFRAME W3 (V0504) — ONE session hub: every registry this console holds a session on.
 *
 *   home     this console's own developer session (stores/auth.ts owns it; the hub reads it through apiClient)
 *   foreign  a developer session AT a peer registry: signed in at the peer's own API, with its own refresh token; the
 *            road it came in on (`baseUrl`, the account) is kept for the tab, so a reload reconnects there (W4, V0507:
 *            the admin relay, the only other road, is gone: it reached only the retired frames)
 *   agents   agent tokens per (registry, DID) with their expiry, re-minted before they lapse: the OWNER rail where the
 *            hub holds your developer session on that registry (no secret), else your saved credential at the agent's
 *            own registry
 *
 * Persistence: access tokens in MEMORY only; refresh tokens in sessionStorage `gcc_refresh:<key>` (unchanged);
 * the road in sessionStorage `tp_hub_sessions`; passwords never. `resetAll` (the home session's end) clears all of it.
 *
 * It replaces the Galactic Command session store: `stores/commandSessions.ts` re-exports this one, so its importers
 * (Galactic Command, Bridge, the vault import, the reconcile modal, the multi-frame facade) share one state.
 * Keys are the frame manifest's (`asia`, `sbx-beta`, an operator's name); legacy directory keys resolve through the
 * alias table (§BLOGSHOTS).
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import axios, { type AxiosInstance } from 'axios'
import { setDirectRoadResolver } from '@/services/api/peer'
import { apiBase, directLogin, directRefresh, isCorsOrNetworkFailure, mintAgentTokenAt, classifyAgentMintFailure }
  from '@/services/api/peerDirect'
import { buildAliasMap, resolveSessionKey } from '@/services/bridge/keyAlias'
import { HUB_META_KEY, REFRESH_KEY, droppedHubKeys, needsMint, parseHubMeta, type HubMeta } from '@/services/sessionHub'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { currentFrameManifest } from '@/composables/useFrameManifest'

export interface CommandSession {
  /** That registry's DEVELOPER access token (the name is historical: the first sessions were admin consoles). */
  adminToken: string | null
  adminEmail: string | null
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  error: string | null
  /** Agent JWTs minted for this registry, keyed by agent DID. */
  agentTokens: Record<string, string>
  /** How each agent token was minted ('owner' | 'secret'), for the console to say. */
  agentVia: Record<string, string>
  /** Which agent acts as "my agent" on this registry (Model-L sender). */
  activeAgentDid: string | null
  /** That registry's own public base URL. Present => the console talks to it DIRECTLY. */
  baseUrl: string | null
  /** 'direct' once the session is signed in at `baseUrl` (the only road since V0507); null before. */
  via: 'direct' | null
  since: string | null
}

const blank = (): CommandSession => ({
  adminToken: null, adminEmail: null, status: 'disconnected', error: null, agentTokens: {}, agentVia: {},
  activeAgentDid: null, baseUrl: null, via: null, since: null,
})

const norm = (k: string) => String(k || '').toLowerCase()

function readMeta(): Record<string, HubMeta> {
  try { return parseHubMeta(sessionStorage.getItem(HUB_META_KEY)) } catch { return {} }
}

function writeMeta(meta: Record<string, HubMeta>): void {
  try {
    if (Object.keys(meta).length) sessionStorage.setItem(HUB_META_KEY, JSON.stringify(meta))
    else sessionStorage.removeItem(HUB_META_KEY)
  } catch { /* storage blocked */ }
}

export const useSessionHub = defineStore('sessionHub', () => {
  const sessions = ref<Record<string, CommandSession>>({})

  // A reload starts from what the tab remembers: each session's road, disconnected until `reconnect`. A road the
  // parser drops (an older console's relay session) leaves no refresh token behind (§FEFRAME W4).
  try {
    const raw = sessionStorage.getItem(HUB_META_KEY)
    const dropped = droppedHubKeys(raw)
    if (dropped.length) {
      for (const k of dropped) sessionStorage.removeItem(REFRESH_KEY(k))
      writeMeta(parseHubMeta(raw))
    }
  } catch { /* storage blocked */ }
  for (const [k, m] of Object.entries(readMeta())) {
    sessions.value[k] = { ...blank(), baseUrl: m.baseUrl, via: m.via, adminEmail: m.email, since: m.since || null }
  }

  function _s(key: string): CommandSession {
    const k = norm(key)
    if (!sessions.value[k]) sessions.value[k] = blank()
    return sessions.value[k]
  }

  function remember(key: string): void {
    const k = norm(key)
    const s = sessions.value[k]
    const meta = readMeta()
    if (s && s.via === 'direct' && s.baseUrl) {
      meta[k] = { baseUrl: s.baseUrl, via: s.via, email: s.adminEmail, since: s.since || new Date().toISOString() }
    } else {
      delete meta[k]
    }
    writeMeta(meta)
  }

  function storeRefresh(key: string, rt?: string): void {
    try { if (rt) sessionStorage.setItem(REFRESH_KEY(key), rt) } catch { /* storage full/blocked */ }
  }

  /** This console's own manifest key (null before the manifest lands). */
  function homeKey(): string | null {
    return currentFrameManifest()?.self?.key || null
  }
  const isHome = (key: string) => {
    const k = norm(key)
    return k === 'home' || k === 'local' || (!!homeKey() && k === homeKey())
  }

  /**
   * §FOREIGNDEV — sign in AT the target registry: it needs no rights on this one and creates no credential-testing
   * oracle here. A CORS/network refusal (no response at all) is said as such: that registry does not admit this
   * console's address yet (its derived CORS admits the consoles of its active federation peers, V0503+).
   */
  async function connectAdmin(key: string, email: string, password: string, baseUrl?: string | null): Promise<boolean> {
    const s = _s(key)
    s.status = 'connecting'; s.error = null
    if (baseUrl) s.baseUrl = baseUrl.replace(/\/+$/, '')

    if (!s.baseUrl) {
      s.error = 'this registry has no known address yet (its card has not been read): try again in a minute'
      s.adminToken = null; s.status = 'error'; s.via = null
      return false
    }
    try {
      const pair = await directLogin(s.baseUrl, email, password)
      if (!pair.access_token) throw new Error('No token returned')
      s.adminToken = pair.access_token; s.adminEmail = email; s.status = 'connected'; s.via = 'direct'
      s.since = new Date().toISOString()
      storeRefresh(key, pair.refresh_token)
      remember(key)
      return true
    } catch (e: any) {
      s.error = isCorsOrNetworkFailure(e)
        ? 'that registry could not be reached from this console (it may not admit this console\'s address yet)'
        : (e?.response?.data?.detail || e?.message || 'Login failed')
      s.adminToken = null; s.status = 'error'; s.via = null
      return false
    }
  }

  /** Re-mint from the stored refresh token (no password), on the road the session came in on. */
  async function reconnect(key: string): Promise<boolean> {
    const k = resolveKey(key)
    const s = _s(k)
    let rt: string | null = null
    try { rt = sessionStorage.getItem(REFRESH_KEY(k)) } catch { rt = null }
    if (!rt) return false
    if (s.via !== 'direct' || !s.baseUrl) return false          // no road to refresh on (never a guess)
    s.status = 'connecting'; s.error = null
    try {
      const pair = await directRefresh(s.baseUrl, rt)
      if (!pair.access_token) throw new Error('No token returned')
      s.adminToken = pair.access_token; s.status = 'connected'
      storeRefresh(k, pair.refresh_token)
      return true
    } catch (e: any) {
      const st = e?.response?.status
      s.error = e?.response?.data?.detail || e?.message || 'Reconnect failed'
      s.adminToken = null; s.status = 'error'
      // Only a REFUSED refresh token is forgotten; a network failure keeps it for the next try (§FEFRAME W3).
      if (st === 400 || st === 401 || st === 403) {
        try { sessionStorage.removeItem(REFRESH_KEY(k)) } catch { /* ignore */ }
      }
      return false
    }
  }

  /**
   * Reconnect the given keys AND every session this tab remembers, each ONCE (two spellings of one registry resolve to
   * one session; a refresh token rotates on use, so refreshing it twice at once can spend it). Sessions that already
   * hold a token are left alone. Returns the connected count.
   */
  let _reconnecting: Promise<number> | null = null
  async function reconnectAll(keys: string[]): Promise<number> {
    if (_reconnecting) return _reconnecting
    const want = new Set<string>()
    for (const key of [...keys, ...Object.keys(readMeta())]) {
      const r = resolveKey(key)
      if (!sessions.value[r]?.adminToken && hasStoredRefresh(r)) want.add(r)
    }
    _reconnecting = Promise.all([...want].map(k => reconnect(k)))
      .then(results => results.filter(Boolean).length)
      .finally(() => { _reconnecting = null })
    return _reconnecting
  }

  /** Reconnect every session this tab remembers (a reload). */
  async function reconnectRemembered(): Promise<number> {
    return reconnectAll([])
  }

  // ── per-registry clients ─────────────────────────────────────────────────────────────────────────────────────
  const clients: Record<string, AxiosInstance> = {}

  /**
   * A client for registry `key` that carries THAT registry's developer token and nothing else: a token only travels to
   * the registry that minted it. A 401 reconnects that session once (its own refresh token) and retries; it never
   * touches the home session. Null when the hub holds no session there. The home registry is `apiClient` (import it
   * directly).
   */
  function registryClient(key: string): AxiosInstance | null {
    const k = resolveKey(key)
    const s = sessions.value[k]
    if (!s?.baseUrl || s.via !== 'direct') return null
    if (!clients[k] || (clients[k].defaults.baseURL !== apiBase(s.baseUrl))) {
      const c = axios.create({ baseURL: apiBase(s.baseUrl), timeout: 30_000 })
      c.interceptors.request.use((cfg) => {
        const tok = sessions.value[k]?.adminToken
        if (tok && !cfg.headers.get?.('Authorization')) cfg.headers.set?.('Authorization', `Bearer ${tok}`)
        return cfg
      })
      c.interceptors.response.use(undefined, async (err) => {
        const cfg: any = err?.config
        if (err?.response?.status === 401 && cfg && !cfg._hubRetried && hasStoredRefresh(k)) {
          cfg._hubRetried = true
          if (await reconnect(k)) {
            cfg.headers.set?.('Authorization', `Bearer ${sessions.value[k]?.adminToken}`)
            return c(cfg)
          }
        }
        throw err
      })
      clients[k] = c
    }
    return clients[k]
  }

  // ── agent tokens ─────────────────────────────────────────────────────────────────────────────────────────────

  function keepAgentToken(key: string, did: string, token: string, via: string): void {
    const s = _s(key)
    s.agentTokens[did] = token
    s.agentVia[did] = via
    s.activeAgentDid = did
  }

  /** The secret mint the console's "connect agent" button uses, AT the registry the hub holds a session on. */
  async function mintAgentToken(key: string, clientId: string, clientSecret: string, did: string): Promise<string | null> {
    const k = resolveKey(key)
    const s = _s(k)
    try {
      if (s.via !== 'direct' || !s.baseUrl) { s.error = 'Connect the registry first.'; return null }
      const r = await mintAgentTokenAt(s.baseUrl, clientId, clientSecret)
      if (r?.access_token) { keepAgentToken(k, did, r.access_token, 'secret'); return r.access_token }
      return null
    } catch (e: any) {
      s.error = e?.response?.data?.detail || e?.message || 'Agent token request failed'
      return null
    }
  }

  /**
   * An agent token for `did` on registry `key`, minted if missing or about to lapse:
   *   1. the OWNER rail (`POST /developers/me/agents/{did}/session-token`) with your developer session there (home, or
   *      a direct foreign session): no secret needed
   *   2. your saved credential for the agent, at the agent's own registry
   * Null when neither road exists or both refuse; `lastAgentError[did]` says why in a person's words.
   */
  const lastAgentError = ref<Record<string, string>>({})
  async function ensureAgentToken(key: string, did: string): Promise<string | null> {
    const k = resolveKey(key)
    const s = _s(k)
    const cached = s.agentTokens[did]
    if (cached && !needsMint(cached)) return cached
    delete lastAgentError.value[did]
    const home = isHome(k)

    // 1. the owner rail
    const devClient = home ? null : registryClient(k)
    if (home || devClient) {
      try {
        let data: any
        if (home) {
          const { apiClient } = await import('@/services/api/client')
          data = (await apiClient.post(`/developers/me/agents/${encodeURIComponent(did)}/session-token`)).data
        } else {
          data = (await devClient!.post(`/developers/me/agents/${encodeURIComponent(did)}/session-token`)).data
        }
        if (data?.access_token) { keepAgentToken(k, did, data.access_token, 'owner'); return data.access_token }
      } catch (e: any) {
        const st = e?.response?.status
        if (st !== 404 && st !== 403) {
          lastAgentError.value[did] = e?.response?.data?.detail || e?.message || 'the owner sign-in failed'
        }
        // 404/403: not yours there (or not active): the saved credential is the next road
      }
    }

    // 2. the saved credential, at the agent's own registry
    const cred = agentCredentialsStore.getCredentials(did)
    if (cred?.client_id && cred.client_secret) {
      const origin = home ? null : (s.baseUrl || cred.registry_url || null)
      try {
        const r = await mintAgentTokenAt(origin, cred.client_id, cred.client_secret)
        if (r?.access_token) {
          agentCredentialsStore.clearRejected?.(did)
          keepAgentToken(k, did, r.access_token, 'secret')
          return r.access_token
        }
      } catch (e: any) {
        const why = classifyAgentMintFailure(e)
        if (why === 'rejected') agentCredentialsStore.markRejected?.(did)
        lastAgentError.value[did] = why === 'unreachable'
          ? 'that registry could not be reached from this console'
          : why === 'rejected' ? 'the registry refused the saved secret'
          : why === 'suspended' ? 'the agent is suspended by its registry'
          : (e?.response?.data?.detail || e?.message || 'the agent sign-in failed')
      }
      return null
    }
    if (!lastAgentError.value[did]) {
      lastAgentError.value[did] = 'no session on that registry and no saved credential for this agent'
    }
    return null
  }

  function setActiveAgent(key: string, did: string | null) { _s(key).activeAgentDid = did }
  const activeAgentFor = (key: string): { did: string; token: string } | null => {
    const s = sessions.value[resolveKey(key)]
    if (!s?.activeAgentDid) return null
    const tok = s.agentTokens[s.activeAgentDid]
    return tok ? { did: s.activeAgentDid, token: tok } : null
  }

  function disconnect(key: string) {
    const k = resolveKey(key)
    sessions.value[k] = blank()
    delete clients[k]
    try { sessionStorage.removeItem(REFRESH_KEY(k)) } catch { /* ignore */ }
    if (k !== norm(key)) { try { sessionStorage.removeItem(REFRESH_KEY(key)) } catch { /* ignore */ } }
    const meta = readMeta(); delete meta[k]; delete meta[norm(key)]; writeMeta(meta)
  }
  function disconnectAll() {
    for (const k of Object.keys(sessions.value)) disconnect(k)
  }

  /**
   * §FEFRAME W1 — everything this store holds, gone: called when the home session ends (logout, or an automatic end).
   * Walks STORAGE (a previous session's refresh tokens and roads survive a reload otherwise and would reconnect the
   * next person in this tab).
   */
  function resetAll() {
    sessions.value = {}
    aliases.value = {}
    lastAgentError.value = {}
    for (const k of Object.keys(clients)) delete clients[k]
    try {
      const doomed: string[] = []
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i)
        if (k && (k.startsWith('gcc_refresh:') || k === HUB_META_KEY)) doomed.push(k)
      }
      for (const k of doomed) sessionStorage.removeItem(k)
    } catch { /* storage blocked */ }
  }

  function hasStoredRefresh(key: string): boolean {
    try { return !!sessionStorage.getItem(REFRESH_KEY(key)) } catch { return false }
  }

  // peerGet/peerPost ask the hub which road a token came in on: its calls go to the registry that minted it.
  setDirectRoadResolver((key: string, token: string) => {
    const s = sessions.value[resolveKey(key)]
    return s?.via === 'direct' && s.baseUrl && s.adminToken === token ? s.baseUrl : null
  })

  /* §BLOGSHOTS — one registry, two spellings: every lookup resolves through the declared aliases, both directions. */
  const aliases = ref<Record<string, string>>({})
  function registerAliases(pairs: Array<{ key?: string | null; canonical?: string | null }> | null | undefined) {
    aliases.value = buildAliasMap(pairs, aliases.value)
  }
  const resolveKey = (key: string): string =>
    resolveSessionKey(key, (k) => !!sessions.value[k], aliases.value)

  const sessionFor = (key: string): CommandSession => sessions.value[resolveKey(key)] || blank()
  const adminTokenFor = (key: string): string | null => sessions.value[resolveKey(key)]?.adminToken || null
  const agentTokenFor = (key: string, did: string): string | null => sessions.value[resolveKey(key)]?.agentTokens?.[did] || null
  const isConnected = (key: string): boolean => sessions.value[resolveKey(key)]?.status === 'connected'
  const connectedKeys = computed(() => Object.keys(sessions.value).filter(k => sessions.value[k]?.status === 'connected'))
  const rememberedKeys = computed(() => Object.keys(sessions.value).filter(k => !!sessions.value[k]?.via))

  return {
    sessions, connectAdmin, reconnect, reconnectAll, reconnectRemembered, mintAgentToken, ensureAgentToken,
    lastAgentError, registryClient, disconnect, disconnectAll, resetAll,
    hasStoredRefresh, sessionFor, adminTokenFor, agentTokenFor, isConnected, connectedKeys, rememberedKeys,
    registerAliases, resolveKey, isHome, homeKey,
    setActiveAgent, activeAgentFor,
  }
})
