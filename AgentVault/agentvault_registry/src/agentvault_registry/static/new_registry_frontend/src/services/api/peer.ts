// Cross-registry console reads: a session the hub holds on another registry is read AT that registry, with that
// registry's own token (stores/sessions.ts keeps the road: its address and the token it minted).
//
// §FEFRAME W4 (V0507): the admin relay (`/admin/peer/{key}/…` on THIS registry, backend routers/admin_peer_proxy.py)
// is gone. It reached only the retired frames (its allowlist came from PEER_REGISTRY_{A,B,C}_URL / COMMAND_RELAY_URL_MAP,
// set on no live registry), so every call through it answered 404 on EU, ASIA, the operators and the sandbox. A session
// is direct or it does not exist; a call for a registry the hub holds no direct session on says so instead of guessing.

import { directGet, apiBase } from './peerDirect'
import axios from 'axios'

/** The road of a session the hub holds: that registry's address when `token` is the one the hub minted there. */
type DirectRoad = (key: string, token: string) => string | null
let directRoad: DirectRoad = () => null

/** Set by the session hub when it is created (stores/sessions.ts): this module must not import the store (a cycle). */
export function setDirectRoadResolver(fn: DirectRoad): void {
  directRoad = fn
}

function directBaseFor(key: string, token: string): string {
  let base: string | null = null
  try { base = directRoad(key, token) } catch { base = null }
  if (!base) throw new Error(`No session on ${key} from this console: connect it in the Multi-Frame Console first`)
  return base
}

/** Authenticated GET on a foreign registry (admin or agent token), at that registry's own address. */
export async function peerGet<T = any>(
  key: string,
  path: string,
  peerToken: string,
  params?: Record<string, any>,
): Promise<T> {
  return directGet<T>(directBaseFor(key, peerToken), path, peerToken, params)
}

/** Authenticated POST on a foreign registry (admin or agent token), at that registry's own address. */
export async function peerPost<T = any>(
  key: string,
  path: string,
  peerToken: string,
  body?: any,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const r = await axios.post(`${apiBase(directBaseFor(key, peerToken))}/${path.replace(/^\//, '')}`, body ?? {}, {
    timeout: 25_000,
    headers: { Authorization: `Bearer ${peerToken}`, ...(extraHeaders || {}) },
  })
  return r.data as T
}

export interface PeerAgent { name: string; client_id?: string; did?: string; humanReadableId?: string }

/**
 * List a foreign registry's agents (for the agent picker) using its own token.
 *
 * §FOREIGNDEV — `baseUrl` names that registry's address; without it the hub's road for the session is used.
 */
export async function peerListAgents(key: string, adminToken: string, baseUrl?: string | null): Promise<PeerAgent[]> {
  let answered = false
  let lastError: unknown = null
  for (const path of ['admin/agents', 'developers/me/agents', 'agents']) {
    try {
      const d = baseUrl
        ? await directGet<any>(baseUrl, path, adminToken, { limit: 200 })
        : await peerGet<any>(key, path, adminToken, { limit: 200 })
      answered = true
      const arr = Array.isArray(d) ? d : (d?.agents ?? d?.items ?? d?.data ?? [])
      if (Array.isArray(arr) && arr.length) {
        return arr.map((a: any) => ({
          name: a.name || a.human_readable_id || a.humanReadableId || a.did || a.client_id || 'agent',
          client_id: a.client_id || a.clientId,
          did: a.did,
          humanReadableId: a.human_readable_id || a.humanReadableId,
        }))
      }
    } catch (e) { lastError = e /* try next shape */ }
  }
  // §FESUITE (2026-10-05): no shape answered at all: a failed read, which the caller says as one (it read "You own no
  // agents there" before); a shape that answered with an empty list is still none
  if (!answered) throw lastError ?? new Error('the agent list could not be read')
  return []
}
