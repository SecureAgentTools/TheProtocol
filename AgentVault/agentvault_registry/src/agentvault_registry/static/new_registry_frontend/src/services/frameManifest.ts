/**
 * §FEFRAME W2 — the frame manifest: who this registry is and who its federation peers are, as the SERVER says.
 *
 * GET /api/v1/public/registry-config carries `self` and `peers[]` (core/federation_view.py): one resolver over the
 * peer rows the federation admitted and the cards it verified. The console used to answer the same question from an
 * A/B/C seed of three retired frames (config/frames.ts) with their currencies and ledger sockets hard-coded; on EU and
 * ASIA that seed named nothing that exists, and EU's one peer was drawn as "Frame B".
 *
 * Pure: types and lookups only. The fetch and the reactive state live in composables/useFrameManifest.ts.
 */

export type FrameRole = 'frame' | 'operator'

export interface FrameEntry {
  /** the registry's own name, lowercased: the key every lookup uses (never a letter) */
  key: string
  name: string
  display_name: string
  trust_domain: string | null
  role: FrameRole
  /** an operator's frame (its key); null for a frame */
  parent: string | null
  /** the public API origin */
  public_url: string | null
  /** where a person opens this registry's console (an origin; `<console>/#/<route>` lands on every host) */
  console_url: string | null
  /** the settlement currency code on its card */
  currency: string | null
  currency_name: string | null
  theme: string | null
  icon_url: string | null
  /** wss://<frame console host>/ws/events; an operator streams its parent's ledger */
  ledger_ws: string | null
  tier: string | null
  verified: boolean
}

export interface FrameManifest {
  manifest_version: number
  self: FrameEntry
  peers: FrameEntry[]
  /** at least two frames in this federation */
  multi_frame: boolean
}

/** A registry-config body that carries a manifest (an older registry answers without `self`). */
export function manifestFrom(body: any): FrameManifest | null {
  if (!body || typeof body !== 'object' || !body.self || typeof body.self !== 'object' || !body.self.key) return null
  const norm = (e: any): FrameEntry => ({
    key: String(e.key || '').toLowerCase(),
    name: String(e.name || e.key || ''),
    display_name: String(e.display_name || e.name || e.key || ''),
    trust_domain: e.trust_domain ? String(e.trust_domain).toLowerCase() : null,
    role: e.role === 'operator' ? 'operator' : 'frame',
    parent: e.parent ? String(e.parent).toLowerCase() : null,
    public_url: e.public_url || null,
    console_url: e.console_url || e.public_url || null,
    currency: e.currency ? String(e.currency).toUpperCase() : null,
    currency_name: e.currency_name || null,
    theme: e.theme || null,
    icon_url: e.icon_url || null,
    ledger_ws: e.ledger_ws || null,
    tier: e.tier || null,
    verified: !!e.verified,
  })
  return {
    manifest_version: Number(body.manifest_version || 1),
    self: norm(body.self),
    peers: Array.isArray(body.peers) ? body.peers.filter((p: any) => p && p.key).map(norm) : [],
    multi_frame: !!body.multi_frame,
  }
}

/** Every entry, self first. */
export function allEntries(m: FrameManifest): FrameEntry[] {
  return [m.self, ...m.peers]
}

export function entryByKey(m: FrameManifest, key: string | null | undefined): FrameEntry | null {
  if (!key) return null
  const k = key.toLowerCase()
  return allEntries(m).find((e) => e.key === k) ?? null
}

/** The frame an entry belongs to: itself when it is a frame, its parent when it is an operator (null when the parent
 *  is not in this manifest). */
export function frameOf(m: FrameManifest, e: FrameEntry | null | undefined): FrameEntry | null {
  if (!e) return null
  if (e.role === 'frame') return e
  return entryByKey(m, e.parent)
}

/** The frames of this federation, this console's own frame first (an operator console: its parent). */
export function framesOf(m: FrameManifest): FrameEntry[] {
  const own = frameOf(m, m.self)
  const out: FrameEntry[] = own ? [own] : []
  for (const e of allEntries(m)) if (e.role === 'frame' && !out.some((f) => f.key === e.key)) out.push(e)
  return out
}

/** One ledger stream per frame: `{ frame, url }`, own frame first. A frame whose manifest names no socket is left out
 *  (never guessed from a host). */
export function ledgersOf(m: FrameManifest): { frame: FrameEntry; url: string }[] {
  const out: { frame: FrameEntry; url: string }[] = []
  for (const f of framesOf(m)) {
    const url = f.key === m.self.key ? m.self.ledger_ws : f.ledger_ws
    if (url && !out.some((x) => x.url === url)) out.push({ frame: f, url })
  }
  if (m.self.role === 'operator' && m.self.ledger_ws && !out.some((x) => x.url === m.self.ledger_ws)) {
    const own = frameOf(m, m.self)
    if (own) out.unshift({ frame: own, url: m.self.ledger_ws })
  }
  return out
}

/** The entry a ledger event or a card came from, by the trust domain or the registry name it carries. For a trust
 *  domain shared by a frame and its operators, the FRAME answers (a ledger belongs to the frame). */
export function entryByTrustDomain(m: FrameManifest, td: string | null | undefined): FrameEntry | null {
  if (!td) return null
  const t = td.toLowerCase()
  const hits = allEntries(m).filter((e) => e.trust_domain === t)
  return hits.find((e) => e.role === 'frame') ?? hits[0] ?? null
}

export function entryByName(m: FrameManifest, name: string | null | undefined): FrameEntry | null {
  if (!name) return null
  const n = name.toLowerCase()
  return allEntries(m).find((e) => e.key === n || e.name.toLowerCase() === n || e.display_name.toLowerCase() === n) ?? null
}

/** The entry whose console or public origin is `origin` (a URL's origin; hosts compare lowercase). */
export function entryByOrigin(m: FrameManifest, origin: string | null | undefined): FrameEntry | null {
  if (!origin) return null
  let o: string
  try { o = new URL(origin).origin.toLowerCase() } catch { return null }
  return allEntries(m).find((e) => [e.console_url, e.public_url].some((u) => {
    try { return !!u && new URL(u).origin.toLowerCase() === o } catch { return false }
  })) ?? null
}

/** The home trust domain a DID names: the issuer segment of `did:<method>:<issuer>:<id>` (fresh mints since
 *  §DIDWIDEN); null for a DID without one (a legacy `did:theprotocol:<id>`). */
export function didIssuer(did: string | null | undefined): string | null {
  if (!did) return null
  const parts = String(did).split(':')
  return parts.length >= 4 && parts[0] === 'did' && parts[2] ? parts[2].toLowerCase() : null
}

/** The entry a registry URL names: by its origin, else by its host alone (a federation address can carry a port of
 *  its own). */
export function entryByRegistryUrl(m: FrameManifest, url: string | null | undefined): FrameEntry | null {
  const exact = entryByOrigin(m, url)
  if (exact || !url) return exact
  let host: string
  try { host = new URL(url).hostname.toLowerCase() } catch { return null }
  return allEntries(m).find((e) => [e.console_url, e.public_url].some((u) => {
    try { return !!u && new URL(u).hostname.toLowerCase() === host } catch { return false }
  })) ?? null
}

/** The unit an amount of a cross-registry settlement is in: the currency of the frame the party's DID belongs to (its
 *  issuer's trust domain), else of the frame the party's registry URL names; null when neither is known, and the
 *  caller then names no unit, never another frame's. A slash is in the defendant frame's unit, a compensation in the
 *  origin's (routers/federation_disputes.py: the origin's treasury pays it). */
export function settlementUnit(m: FrameManifest | null | undefined, did: string | null | undefined,
                               url: string | null | undefined): string | null {
  if (!m) return null
  const td = didIssuer(did)
  const byDid = td ? entryByTrustDomain(m, td) : null
  if (byDid?.currency) return byDid.currency
  return entryByRegistryUrl(m, url)?.currency ?? null
}

/** code -> name, from every entry that states one (the server's words, never a seed). */
export function currencyNames(m: FrameManifest): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of allEntries(m)) if (e.currency && e.currency_name && !out[e.currency]) out[e.currency] = e.currency_name
  return out
}

/** `<console>/#/<route>` on the entry's own console, or null when it has none. */
export function consoleLink(e: FrameEntry | null | undefined, route = ''): string | null {
  if (!e?.console_url) return null
  const base = e.console_url.replace(/\/+$/, '')
  const r = String(route || '').replace(/^#?\/*/, '')
  return r ? `${base}/#/${r}` : `${base}/`
}
