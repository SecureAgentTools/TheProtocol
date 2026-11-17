/**
 * V0663, the Directory read path, step 3 (order gwo_0936844934f713153ede256c): the registries the federated index knows,
 * as this registry read them (GET /public/directory/registries, services/directory_registries on the registry).
 *
 * The registry verified every card itself, against the key at the origin the card names: the index can omit a card,
 * never vouch for one. So here only a verified row names a registry; an unverified one carries the index's words
 * (indexName, indexUrl) and its reason, and nothing of its own. Four states: ok, error (with the registry's reason; a
 * broken index is never drawn as an empty list), unconfigured (this registry reads no index), and an answer that is not
 * this shape, which is an error too.
 */

export type IndexRelation = 'self' | 'peer' | 'known' | 'candidate' | 'unverified'

export interface IndexRegistry {
  /** from the registry's own signed card; null unless verified */
  name: string | null
  trustDomain: string | null
  tier: string | null
  publicUrl: string | null
  location: string | null
  currency: string | null
  verified: boolean
  /** "ok", or why the card did not verify here */
  reason: string
  relation: IndexRelation
  /** false where the index lists another address than the card; null when unverified */
  addressAgrees: boolean | null
  /** the index's own words about the row */
  indexName: string | null
  indexUrl: string | null
  indexReachable: boolean
}

export interface IndexRegistriesAnswer {
  state: 'ok' | 'error' | 'unconfigured'
  error: string | null
  servesCards: boolean
  truncated: boolean
  counts: { index: number; read: number; verified: number; unverified: number }
  registries: IndexRegistry[]
}

const RELATIONS: readonly IndexRelation[] = ['self', 'peer', 'known', 'candidate']
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

function empty(state: IndexRegistriesAnswer['state'], error: string | null): IndexRegistriesAnswer {
  return { state, error, servesCards: true, truncated: false, counts: { index: 0, read: 0, verified: 0, unverified: 0 },
    registries: [] }
}

function row(r: any): IndexRegistry {
  const ix = r && typeof r.index === 'object' && r.index ? r.index : {}
  const verified = r?.verified === true
  const relation = verified && RELATIONS.includes(r?.relation) ? (r.relation as IndexRelation) : 'unverified'
  return {
    name: verified ? str(r.name) : null,
    trustDomain: verified ? str(r.trust_domain) : null,
    tier: verified ? str(r.tier) : null,
    publicUrl: verified ? str(r.public_url) : null,
    location: verified ? str(r.location) : null,
    currency: verified ? str(r.currency) : null,
    verified,
    reason: str(r?.reason) || (verified ? 'ok' : 'not verified'),
    relation,
    addressAgrees: verified ? r.address_agrees !== false : null,
    indexName: str(ix.name),
    indexUrl: str(ix.public_url),
    indexReachable: ix.reachable === true,
  }
}

/** The registry's answer (HTTP status and body) as one shape. */
export function normaliseIndexRegistries(status: number, body: any): IndexRegistriesAnswer {
  if (!body || typeof body !== 'object') return empty('error', `the registry answered ${status} with no body it could read`)
  if (body.configured === false) return empty('unconfigured', null)
  if (status >= 400 || typeof body.error === 'string') {
    return empty('error', str(body.error) || `the registry answered ${status}`)
  }
  if (!Array.isArray(body.registries)) return empty('error', 'the registry answered without a registries list')
  const c = body.counts && typeof body.counts === 'object' ? body.counts : {}
  return {
    state: 'ok',
    error: null,
    servesCards: body.index_serves_cards !== false,
    truncated: body.truncated === true,
    counts: { index: num(c.index), read: num(c.read), verified: num(c.verified), unverified: num(c.unverified) },
    registries: body.registries.filter((r: any) => r && typeof r === 'object').map(row),
  }
}

/** This registry, its peers, known, candidates, then what did not verify; by name within each. */
export function orderIndexRegistries(list: readonly IndexRegistry[]): IndexRegistry[] {
  const rank = (r: IndexRegistry) => (r.verified ? RELATIONS.indexOf(r.relation) : RELATIONS.length)
  const label = (r: IndexRegistry) => (r.name ?? r.indexName ?? '').toLowerCase()
  return [...list].sort((a, b) => rank(a) - rank(b) || label(a).localeCompare(label(b)))
}
