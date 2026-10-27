/**
 * services/cardAuth.ts — §CARDAUTH (agentvault2-56, 2026-10-23).
 *
 * Read the auth a card declares, whichever way it declares it, exactly like its price (services/cardPricing.ts) and
 * its endpoint (§CARDLINK). Two dialects are legal:
 *   1. the legacy `authSchemes` list (`[{scheme: "none", ...}]`, what the older cards on this network carry), and
 *   2. the A2A v1.0 `securitySchemes` map (OpenAPI-style: apiKey, http bearer or basic, oauth2, openIdConnect,
 *      mutualTLS) with the `security` requirement naming which of them a call needs.
 * The console read only the first, so an agent that sells access its own way (an API key in a header of its own) showed
 * as an open, free endpoint: no Authentication row, and a curl example without its key header. Found on journal 52's
 * worked example, Sundial.
 *
 * PURE on purpose (no imports), like cardPricing: node-unit-testable, and importing it drags nothing in behind it.
 */

export interface CardAuthScheme {
  /** apiKey | bearer | basic | oauth2 | openIdConnect | mtls | none, or the legacy row's own word */
  scheme: string
  /** the scheme's name in the card's securitySchemes (absent on a legacy row) */
  name?: string
  /** an apiKey sent in a header: that header's name */
  header?: string | null
  /** an apiKey sent in the query string: that parameter's name */
  query?: string | null
  /** the card's own words about it (where to get the credential, what it costs), shown as plain text */
  description?: string | null
  /** an oauth2 token URL or an OpenID Connect discovery URL, as the card states it */
  tokenUrl?: string | null
  /** true for a row read from securitySchemes: its credential is the agent's own, not one this network issues */
  declared?: boolean
  [k: string]: unknown
}

const DESCRIPTION_MAX = 400

function row(name: string, spec: any): CardAuthScheme {
  const type = String(spec?.type || '').toLowerCase()
  const http = String(spec?.scheme || '').toLowerCase()
  const scheme = type === 'apikey' ? 'apiKey'
    : type === 'http' ? (http === 'basic' ? 'basic' : 'bearer')
    : type === 'oauth2' ? 'oauth2'
    : type === 'openidconnect' ? 'openIdConnect'
    : type === 'mutualtls' ? 'mtls'
    : String(spec?.type || name)
  const flows = spec?.flows || {}
  const cc = flows.clientCredentials || flows.client_credentials || flows.authorizationCode || flows.authorization_code || {}
  const where = String(spec?.in || '').toLowerCase()
  return {
    scheme,
    name,
    header: scheme === 'apiKey' && where === 'header' && typeof spec?.name === 'string' ? spec.name : null,
    query: scheme === 'apiKey' && where === 'query' && typeof spec?.name === 'string' ? spec.name : null,
    description: typeof spec?.description === 'string' && spec.description.trim()
      ? spec.description.trim().slice(0, DESCRIPTION_MAX) : null,
    tokenUrl: (typeof cc.tokenUrl === 'string' && cc.tokenUrl) || (typeof spec?.openIdConnectUrl === 'string' && spec.openIdConnectUrl) || null,
    declared: true,
  }
}

/** One row per scheme a call can bring, in the card's order; [] when the card declares nothing. */
export function cardAuthSchemes(cd: Record<string, any> | null | undefined): CardAuthScheme[] {
  if (!cd || typeof cd !== 'object') return []
  if (Array.isArray(cd.authSchemes) && cd.authSchemes.length) return cd.authSchemes as CardAuthScheme[]
  const defs = cd.securitySchemes
  if (!defs || typeof defs !== 'object' || Array.isArray(defs)) return []
  // `security` lists alternatives (any one requirement object will do; the schemes inside one go together). An empty
  // requirement object means a call may come with no credential at all.
  const named: string[] = []
  let open = false
  if (Array.isArray(cd.security)) {
    for (const req of cd.security) {
      if (!req || typeof req !== 'object' || Array.isArray(req)) continue
      const keys = Object.keys(req)
      if (!keys.length) open = true
      for (const k of keys) if (!named.includes(k)) named.push(k)
    }
  }
  const names = named.length ? named.filter((n) => Object.prototype.hasOwnProperty.call(defs, n)) : Object.keys(defs)
  const out = names.map((n) => row(n, defs[n]))
  if (open) out.push({ scheme: 'none', declared: true })
  return out
}

/** Does a call need a credential of the agent's own? (a declared scheme other than "none") */
export function needsOwnCredential(rows: CardAuthScheme[] | null | undefined): boolean {
  return !!rows?.some((r) => r.declared && r.scheme !== 'none')
}
