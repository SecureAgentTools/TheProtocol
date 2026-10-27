/**
 * services/frameHost.ts — §FRESHFRAME (2026-09-14): the landing page notices WHERE it is.
 *
 * The same bundle is served by every frame at its own hostname, so anything the front door tells a
 * visitor to COPY or TYPE (the MCP endpoints, the SDK snippets' registry base and trust domain) must
 * be derived from the host that serves the page, never from a flagship literal: a visitor on a fresh
 * frame used to copy `api.theprotocol.cloud/mcp/sse`, the flagship's registry, from a frame that has
 * its own. Measured 2026-09-14 on sandbox-a.theprotocol.cloud, theprotocol.cloud and
 * api.theprotocol.cloud: `/mcp/sse` and `/mcp/rpc?mode=gateway` answer on every console host
 * (`location /mcp/` in every console vhost), while the bare `/mcp?mode=gateway` answers a 301 on
 * every console but api. (a POST redirected is a POST downgraded), so the gateway and toolset forms
 * use `/mcp/rpc`. ONE hostname rule survives: the apex (`theprotocol.cloud`, `www.`) publishes the
 * flagship's documented address, api.theprotocol.cloud, the one the MCP Registry lists; every other
 * host publishes itself.
 *
 * Pure: no DOM at import (the landing page is on the do-not-Playwright list, so every decision here is
 * unit-tested and the template only binds).
 */

export const FLAGSHIP_API_ORIGIN = 'https://api.theprotocol.cloud'
const APEX_HOSTS = new Set(['theprotocol.cloud', 'www.theprotocol.cloud'])

/** The origin a visitor should address this frame's registry at, from the origin serving the page. */
export function registryBase(origin: string): string {
  let host = ''
  try { host = new URL(origin).hostname.toLowerCase() } catch { return origin.replace(/\/+$/, '') }
  if (APEX_HOSTS.has(host)) return FLAGSHIP_API_ORIGIN
  return origin.replace(/\/+$/, '')
}

export interface McpEndpoints {
  publicSse: string; adminSse: string; gateway: string; toolsets: string
  /** the same four without the scheme, for the on-screen `<code>` beside each copy button */
  publicSseShort: string; adminSseShort: string; gatewayShort: string; toolsetsShort: string
}

export function mcpEndpoints(base: string): McpEndpoints {
  const b = base.replace(/\/+$/, '')
  const short = (u: string) => u.replace(/^https?:\/\//, '')
  const publicSse = `${b}/mcp/sse`
  const adminSse = `${b}/mcp/admin/sse`
  const gateway = `${b}/mcp/rpc?mode=gateway`
  const toolsets = `${b}/mcp/rpc?toolsets=wallet,discovery`
  return {
    publicSse, adminSse, gateway, toolsets,
    publicSseShort: short(publicSse), adminSseShort: short(adminSse),
    gatewayShort: short(gateway).replace(/^[^/]+/, ''), toolsetsShort: short(toolsets).replace(/^[^/]+/, ''),
  }
}

/** A toolset-scoped MCP endpoint on this frame, in the `/mcp/rpc` form every console routes (§FRESHFRAME). */
export function mcpToolsetUrl(base: string, toolsets: string): string {
  return `${base.replace(/\/+$/, '')}/mcp/rpc?toolsets=${toolsets}`
}

export interface SdkSnippetHost { registryUrl: string; host: string; trustDomain: string }

/** What the SDK snippets print: the registry base, its bare host, and the trust domain (the card's, else the host). */
export function sdkSnippetHost(base: string, trustDomain?: string | null): SdkSnippetHost {
  const registryUrl = base.replace(/\/+$/, '')
  let host = registryUrl
  try { host = new URL(registryUrl).host } catch { /* keep as given */ }
  const td = (trustDomain || '').trim().toLowerCase()
  return { registryUrl, host, trustDomain: td || host }
}

export type RosterDecision = 'unknown' | 'here' | 'absent'

/**
 * Does this deployment publish the flagship showcase roster? The server's own answer decides
 * (`/api/v1/public/showcase/agents`: `enabled:false` with a reason on a deployment whose public host
 * is not the catalog's, the §SHOWCASEGATE `foreign_catalog` rule; the flagship answers with its agents
 * and no `enabled` key). `unknown` until the rail has answered: a fresh frame must never flash the
 * flagship's roster, and the flagship loses nothing but one round trip.
 */
export function rosterDecision(rail: { enabled?: boolean; agents?: unknown[]; count?: number } | null | undefined): RosterDecision {
  if (rail == null) return 'unknown'
  if (rail.enabled === false) return 'absent'
  const n = Array.isArray(rail.agents) ? rail.agents.length : Number(rail.count || 0)
  return n > 0 ? 'here' : 'absent'
}

export type TickerState = 'loading' | 'live' | 'empty' | 'unreachable'

/**
 * The AGORA strip's state, so an empty network reads as empty and a dead feed reads as dead (§DISCMIX:
 * a strip that removes EVERYTHING is indistinguishable from an outage unless it says what it withheld).
 */
export function tickerState(loadedOnce: boolean, venueCount: number, lastError: string | null): TickerState {
  if (venueCount > 0) return 'live'
  if (!loadedOnce) return 'loading'
  return lastError ? 'unreachable' : 'empty'
}
