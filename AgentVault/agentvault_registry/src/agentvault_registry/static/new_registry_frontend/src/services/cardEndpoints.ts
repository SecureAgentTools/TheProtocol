/**
 * services/cardEndpoints.ts — §CARDLINK (2026-09-08).
 *
 * Read a card's ADDRESSES, whichever way it declares them. This is the endpoint
 * twin of `cardPricing.ts`, and its absence is what caused the defect it closes:
 * pricing has ONE rule both ends ask, endpoints had none, so every surface asked
 * whichever half its author happened to know.
 *
 * TWO DIALECTS ARE LEGAL AND BOTH ARE IN PRODUCTION:
 *   1. `supportedInterfaces[]` — the CURRENT standard. In the vendored A2A
 *      v1.0.1 schema (a byte-exact copy of `specification/a2a.proto` at tag
 *      v1.0.1 of github.com/a2aproject/A2A) `supportedInterfaces` is REQUIRED
 *      with minItems 1, each entry requires {url, protocolBinding,
 *      protocolVersion} — and AgentCard has NO top-level `url` at all.
 *   2. the legacy top-level `url` (+ `preferredTransport`) — a v0.3 field this
 *      fleet keeps through the dual-shape transition window.
 *
 * 🔴 WHY THIS FILE EXISTS. `AgentDetailModal` gated its whole "API Endpoint"
 * section on `agent.url` — dialect 2 only. So the eleven SOVEREIGN agents, whose
 * cards are canonical v1.0 (four real interfaces, no top-level url), showed NO
 * address at all, while the dual-shape showcase cards showed theirs. His report:
 * *"the subdomains of the sovereign agents … are not displayed on the modal …
 * where are the links for the reachable ones then?"* The modal was reading a
 * field the current standard has removed.
 *
 * PURE on purpose: no imports, so it stays node-unit-testable and importing it
 * can never drag the api client or the router in behind it (the cardPricing rule).
 *
 * ORDER IS THE AGENT'S OWN. `supportedInterfaces[0]` is what the agent puts
 * first, so it is the primary; the legacy `url` is appended last and only when it
 * is not already among them, because a dual-shape card names the same address
 * twice and showing it twice would be this module inventing a second endpoint.
 */

export interface CardEndpoint {
  url: string
  /** JSONRPC | REST | GRPC | … — what a caller must speak. '' when the card does not say. */
  protocolBinding: string
  protocolVersion: string
  /** true only for the legacy top-level `url`, so a surface can label the dialect if it wants. */
  legacy: boolean
}

function asText(v: any): string {
  return typeof v === 'string' ? v.trim() : ''
}

export function effectiveEndpoints(cd: any): CardEndpoint[] {
  if (!cd || typeof cd !== 'object') return []
  const out: CardEndpoint[] = []
  const seen = new Set<string>()

  const push = (url: string, binding: string, version: string, legacy: boolean) => {
    const u = asText(url)
    if (!u || seen.has(u)) return
    seen.add(u)
    out.push({
      url: u,
      protocolBinding: asText(binding),
      protocolVersion: asText(version) || '1.0',
      legacy,
    })
  }

  const ifaces = Array.isArray(cd.supportedInterfaces) ? cd.supportedInterfaces : []
  for (const i of ifaces) {
    if (!i || typeof i !== 'object') continue
    push(i.url, i.protocolBinding ?? i.protocol ?? '', i.protocolVersion ?? '', false)
  }

  // Legacy LAST: a card carrying both dialects means the same endpoint twice.
  push(cd.url, cd.preferredTransport ?? '', cd.protocolVersion ?? '', true)

  return out
}

/** The one address a reader should be handed first, or null when the card names none. */
export function primaryEndpoint(cd: any): CardEndpoint | null {
  return effectiveEndpoints(cd)[0] ?? null
}
