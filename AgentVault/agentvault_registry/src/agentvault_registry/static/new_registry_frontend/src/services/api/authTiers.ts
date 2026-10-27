/**
 * §FEFRAME W3 (V0504) — which token a request takes, from the server's own dependency tree.
 *
 * `authTiers.generated.json` is written by `agentvault_registry/core/auth_tiers.py` from the FastAPI dependency tree
 * and checked against the running app by `tests/test_auth_tiers.py`, so it cannot drift from the routes it describes.
 * Its rows keep FastAPI's REGISTRATION order and this module takes the FIRST template that matches, as the router does:
 * a literal `d` row registered before a templated agent row shadows it here exactly as it does on the server.
 *
 *   'agent'      the route depends on the agent-JWT verifier: the request acts AS the selected agent
 *   'either'     the route takes an agent OR a developer token (the read-actor resolvers)
 *   'developer'  everything else (developer-tier or public): this console's developer token
 *
 * It replaces the substring rules of `tier.ts`, which sent an agent token to /teg/staking/balance (developer-tier, a
 * 401) and a developer token to /agents/me, /bridge/transfer and the reputation bond (agent-tier, a 401): 92
 * disagreements over 1,440 operations, measured 2026-10-01. For one release `tier.ts` still answers the 'either'
 * routes (who you are on them is a product decision, not a correction) and every disagreement is counted.
 */
import doc from './authTiers.generated.json'
import { isAgentEndpoint } from './tier'

export type AuthTier = 'agent' | 'either' | 'developer'
type Code = 'a' | 'e' | 'd'
interface Row { method: string; re: RegExp; tier: AuthTier }

const API_PREFIX = '/api/v1'

function esc(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function trimSlash(p: string): string {
  return p.length > 1 ? p.replace(/\/+$/, '') : p
}

/** A FastAPI path template as a regex: `{x}` is one segment, `{x:path}` the rest. */
export function compileTemplate(path: string): RegExp {
  const t = trimSlash(path)
  let out = ''
  let last = 0
  for (const m of t.matchAll(/\{([^}]+)\}/g)) {
    out += esc(t.slice(last, m.index)) + (m[1].endsWith(':path') ? '.+' : '[^/]+')
    last = (m.index ?? 0) + m[0].length
  }
  out += esc(t.slice(last))
  return new RegExp('^' + out + '$')
}

const ROWS: Row[] = ((doc as unknown as { routes: [string, string, Code][] }).routes || []).map(([method, path, code]) => ({
  method: method.toUpperCase(),
  re: compileTemplate(path),
  tier: code === 'a' ? 'agent' : code === 'e' ? 'either' : 'developer',
}))

/** The request's path as the server sees it: `/api/v1/...`, no query, no trailing slash. A URL on another origin keeps
 *  its own path; a relative one is read against the client's baseURL (`/api/v1` by default). */
export function apiPath(url: string, baseURL?: string): string {
  let u = (url || '').split('#')[0].split('?')[0]
  if (/^https?:\/\//i.test(u)) {
    try { u = new URL(u).pathname } catch { /* keep as is */ }
  } else if (!u.startsWith('/api/')) {
    let base = baseURL || API_PREFIX
    if (/^https?:\/\//i.test(base)) {
      try { base = new URL(base).pathname } catch { base = API_PREFIX }
    }
    u = base.replace(/\/+$/, '') + (u.startsWith('/') ? u : '/' + u)
  }
  return trimSlash(u)
}

/** The tier of one request: the first matching row, else 'developer' (a route no agent template can meet). */
export function tierOf(method: string | undefined, url: string | undefined, baseURL?: string): AuthTier {
  if (!url) return 'developer'
  const m = (method || 'get').toUpperCase()
  const p = apiPath(url, baseURL)
  for (const row of ROWS) {
    if (row.method === m && row.re.test(p)) return row.tier
  }
  return 'developer'
}

/** How many rows the console carries (the acceptance harness reads it: a map that failed to load is 0). */
export const AUTH_TIER_ROWS = ROWS.length

/**
 * Does this request act AS the selected agent? The server's map decides: an 'agent' route takes the agent token. An
 * 'either' route keeps the old substring answer for one release (which identity you are on a read that accepts both is
 * a product decision, not a correction). Every disagreement with the old rules is counted in `tierDisagreements`
 * (window.__tpTierDisagreements), so W4 deletes tier.ts on evidence.
 */
export const tierDisagreements: Record<string, number> = {}
if (typeof window !== 'undefined') (window as any).__tpTierDisagreements = tierDisagreements

export function actsAsAgent(url?: string, method?: string, baseURL?: string): boolean {
  const tier = tierOf(method, url, baseURL)
  const legacy = isAgentEndpoint(url, method)
  const decided = tier === 'agent' || (tier === 'either' && legacy)
  if (decided !== legacy) {
    const key = `${(method || 'get').toUpperCase()} ${apiPath(url || '', baseURL)} map=${tier} old=${legacy ? 'agent' : 'developer'}`
    tierDisagreements[key] = (tierDisagreements[key] || 0) + 1
    if (tierDisagreements[key] === 1 && typeof console !== 'undefined') {
      console.info(`[apiClient] the server's token map differs from the old rule: ${key}`)
    }
  }
  return decided
}

/** What the request interceptor put on a request, read back by the 401 handler. */
export type SentTier = 'developer' | 'agent' | 'public' | 'caller' | 'foreign'

/**
 * §FEFRAME W3 — the ONE rule: a 401 asks about THIS session only when it was refused WITH this console's own developer
 * token, a session exists, it is not the auth flow itself, and the caller did not opt out. An agent token, a foreign
 * registry, a public read or a token the caller named never asks (the 14-fragment no-logout list it replaces).
 */
export function asksAboutSession(o: {
  sent?: SentTier; hasSession: boolean; isLogin: boolean; isRefresh: boolean; onLoginPage: boolean; skip: boolean
}): boolean {
  return o.sent === 'developer' && o.hasSession && !o.isLogin && !o.isRefresh && !o.onLoginPage && !o.skip
}
