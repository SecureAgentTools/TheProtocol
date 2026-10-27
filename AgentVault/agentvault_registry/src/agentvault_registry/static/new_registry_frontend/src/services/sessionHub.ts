/**
 * §FEFRAME W3 (V0504) — the session hub's pure half (stores/sessions.ts is the store): what a tab remembers about each
 * registry session, when an agent token is due for a re-mint, and which road a mint takes. Pure so the decisions that
 * decide whether you stay signed in are unit-tested (services/feframeW3.test.ts).
 */
import { jwtExpiresAt } from '@/services/api/tokenExpiry'

/** What survives a reload, per registry key: the road the session came in on and the account, never a token. */
export interface HubMeta {
  baseUrl: string
  via: 'direct'
  email: string | null
  /** When the session was opened (ISO), for the console's "signed in since". */
  since?: string
}

export const HUB_META_KEY = 'tp_hub_sessions'
export const REFRESH_KEY = (k: string) => `gcc_refresh:${String(k).toLowerCase()}`

/** Parse the stored meta, dropping anything malformed (a hand-edited or older shape must not break the console). */
export function parseHubMeta(raw: string | null | undefined): Record<string, HubMeta> {
  if (!raw) return {}
  let d: any
  try { d = JSON.parse(raw) } catch { return {} }
  if (!d || typeof d !== 'object' || Array.isArray(d)) return {}
  const out: Record<string, HubMeta> = {}
  for (const [k, v] of Object.entries(d as Record<string, any>)) {
    if (!k || !v || typeof v !== 'object') continue
    // §FEFRAME W4 (V0507): only a direct session survives a reload. A road an older console remembered as 'relay' named
    // the admin relay, which is gone: it is dropped here, and its refresh token with it (stores/sessions.ts).
    if (v.via !== 'direct') continue
    const baseUrl = typeof v.baseUrl === 'string' && /^https?:\/\//i.test(v.baseUrl) ? v.baseUrl.replace(/\/+$/, '') : null
    if (!baseUrl) continue          // a direct session without an address cannot reconnect
    out[k.toLowerCase()] = {
      baseUrl, via: 'direct', email: typeof v.email === 'string' ? v.email : null,
      since: typeof v.since === 'string' ? v.since : undefined,
    }
  }
  return out
}

/** The keys the stored meta names that `parseHubMeta` drops (an older console's relay roads, malformed rows): their
 *  refresh tokens have no road to be spent on and are removed with them. */
export function droppedHubKeys(raw: string | null | undefined): string[] {
  if (!raw) return []
  let d: any
  try { d = JSON.parse(raw) } catch { return [] }
  if (!d || typeof d !== 'object' || Array.isArray(d)) return []
  const kept = parseHubMeta(raw)
  return Object.keys(d).map(k => k.toLowerCase()).filter(k => !!k && !kept[k])
}

/** True when the token is missing, unreadable as a JWT with an exp, or lapses within `marginMs`. */
export function needsMint(token: string | null | undefined, nowMs = Date.now(), marginMs = 60_000): boolean {
  if (!token) return true
  const exp = jwtExpiresAt(token)
  if (exp === null) return false                         // an opaque token is the server's to judge
  return exp - marginMs <= nowMs
}

/**
 * Which road an agent token takes (`ensureAgentToken`):
 *   'owner'   the hub holds YOUR developer session on the agent's registry: the owner rail mints it, no secret needed
 *   'secret'  a saved credential for the agent: its client secret, at the agent's own registry
 *   'none'    neither: the console says so instead of guessing
 * The owner road is tried first and falls back to the secret on a 404/403 (an agent you do not own there).
 */
export function mintRoad(o: { haveDeveloperSession: boolean; haveSecret: boolean }): Array<'owner' | 'secret'> {
  const roads: Array<'owner' | 'secret'> = []
  if (o.haveDeveloperSession) roads.push('owner')
  if (o.haveSecret) roads.push('secret')
  return roads
}

/** The words the console shows before a foreign sign-in: who you are signing in to, from where. */
export function signInSentence(target: string, here: string): string {
  return `You are signing in to ${target} from ${here}'s console. Your password goes to ${target} only; ` +
    `${here} never sees it, and the session is kept for this tab.`
}
