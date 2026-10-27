/**
 * §FOREIGNDEV — talking to a foreign registry DIRECTLY, as a developer.
 *
 * WHY THIS EXISTS. Every cross-registry call in this app went through
 * `/admin/peer/{key}/…`, a relay on the LOCAL registry. That relay is
 * admin-gated, so the Multi-Frame Console — a panel whose entire purpose is
 * "hold a session on each registry you have an account on" — was unusable by
 * exactly the people it is for. Measured as a real non-admin: 403 on the relay
 * for every key.
 *
 * WHY NOT JUST UN-GATE THE RELAY. Because the gate is defending something real:
 * a relay that forwards arbitrary email/password pairs to arbitrary registries
 * turns THIS registry into a credential-testing oracle. Opening it to everyone
 * would be a genuine downgrade.
 *
 * WHY DIRECT IS BOTH POSSIBLE AND SAFER. The browser talks to the target
 * registry itself, so the target applies its own rate limiting and lockout and
 * no oracle is created here. It is the same architecture R11 #12 already chose
 * for agent tokens (`client.ts` sends an agent's calls to that agent's own
 * registry), extended to developer sessions.
 *
 * MEASURED CORS REALITY (2026-08-21, preflight `POST /auth/login`):
 *   registry-a  allows any origin  (CORS_ALLOW_ALL_ORIGINS=true)
 *   13 ops      allow any origin  (ALLOWED_ORIGINS unset -> default ["*"])
 *   frame-b/c   narrow allowlists; the apex origin was NOT on them
 * so this path works fleet-wide only once frame-b and frame-c match the others.
 * Where CORS still refuses, the caller falls back to the relay (admins only) —
 * which is why `directLogin` must throw a distinguishable error rather than
 * silently returning nothing.
 *
 * DELIBERATELY NOT `apiClient`: that instance carries interceptors which attach
 * THIS registry's token and rewrite `baseURL` for the active agent. Sending a
 * local developer token to a foreign registry would 401 at best, and leak a
 * credential to another origin at worst. A bare instance, one purpose.
 */
import axios from 'axios'

export interface PeerTokenPair { access_token: string; refresh_token?: string }

const bare = axios.create({ timeout: 25_000 })

/** `https://op-doha.op.theprotocol.cloud` -> `https://op-doha.op.theprotocol.cloud/api/v1` */
export function apiBase(baseUrl: string): string {
  const trimmed = String(baseUrl || '').trim().replace(/\/+$/, '')
  if (!trimmed) throw new Error('no registry URL')
  return trimmed.endsWith('/api/v1') ? trimmed : `${trimmed}/api/v1`
}

/** True when the failure is the browser refusing the cross-origin request
 *  (no response object at all), as opposed to the registry answering 401/403.
 *  The caller needs the difference: one is "try the relay", the other is
 *  "these credentials are wrong" and must NOT be retried anywhere. */
export function isCorsOrNetworkFailure(e: any): boolean {
  return !e?.response
}

/** Developer login AT the foreign registry. Form-encoded, like every /auth/*. */
export async function directLogin(baseUrl: string, email: string, password: string): Promise<PeerTokenPair> {
  const body = new URLSearchParams({ username: email, password })
  const r = await bare.post(`${apiBase(baseUrl)}/auth/login`, body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return {
    access_token: (r.data?.access_token as string) || '',
    refresh_token: r.data?.refresh_token as string | undefined,
  }
}

/** Re-mint at the foreign registry from its own refresh token. */
export async function directRefresh(baseUrl: string, refreshToken: string): Promise<PeerTokenPair> {
  const r = await bare.post(`${apiBase(baseUrl)}/auth/refresh`, { refresh_token: refreshToken })
  return {
    access_token: (r.data?.access_token as string) || '',
    refresh_token: r.data?.refresh_token as string | undefined,
  }
}

/**
 * §FEFRAME W1 — an AGENT token, minted where the agent lives, on the bare client.
 *
 * The agent sign-in used to go through `apiClient`, whose interceptor stamps THIS registry's developer token on every
 * request that is not agent-tier, and `/auth/agent/token` is not: so every foreign agent sign-in handed the home
 * developer JWT to another registry, the exact leak this file's header warns about. A local sign-in took the same road
 * and, on a wrong secret, ran a developer refresh and retried (two 401s for one typo). Here the request carries nothing
 * but the agent's own client credentials, for a foreign registry and for this one alike.
 *
 * `origin` null = this registry (same origin, relative base).
 */
export async function mintAgentTokenAt(
  origin: string | null,
  clientId: string,
  clientSecret: string,
): Promise<{ access_token: string; token_type?: string; expires_in?: number }> {
  const base = origin ? apiBase(origin) : '/api/v1'
  const body = new URLSearchParams({ grant_type: 'password', username: clientId, password: clientSecret })
  const r = await bare.post(`${base}/auth/agent/token`, body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return r.data
}

/**
 * Why an agent sign-in failed, in the words a person can act on. `unreachable` is the browser refusing the request
 * (no response at all: another registry's CORS, or the network), never "wrong secret"; only a 401 says the secret is
 * wrong, and only that may mark a saved credential as rejected.
 */
export type AgentMintFailure = 'unreachable' | 'rejected' | 'suspended' | 'other'
export function classifyAgentMintFailure(e: any): AgentMintFailure {
  if (!e?.response) return 'unreachable'
  if (e.response.status === 401) return 'rejected'
  if (e.response.status === 403) return 'suspended'
  return 'other'
}

/**
 * §FESUITE (2026-10-05): a request that failed for want of an answer (none at all, or a server error): the outage a
 * second try can outwait. A refusal (any 4xx) is the registry's answer, and an error that is not a failed request (the
 * console's own, e.g. a page served where JSON was asked) is no outage either: neither is tried again on its own.
 */
export function failedForWantOfAnAnswer(e: any): boolean {
  if (!e?.isAxiosError) return false
  return !e.response || e.response.status >= 500
}

/**
 * Authenticated GET at the foreign registry with ITS OWN token.
 *
 * The token and the address move together — the same rule `client.ts` states
 * for agent tokens. A token minted by registry X is meaningless at registry Y,
 * so there is no code path here that lets them come apart.
 */
export async function directGet<T = any>(
  baseUrl: string,
  path: string,
  token: string,
  params?: Record<string, any>,
): Promise<T> {
  const r = await bare.get<T>(`${apiBase(baseUrl)}/${String(path).replace(/^\/+/, '')}`, {
    params,
    headers: { Authorization: `Bearer ${token}` },
  })
  return r.data as T
}
