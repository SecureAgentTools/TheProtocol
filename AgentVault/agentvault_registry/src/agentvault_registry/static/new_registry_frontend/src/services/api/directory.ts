/**
 * §DIRFEED (2026-09-06) — the FEDERATED INDEX (the Directory), read from the console.
 *
 * What this is NOT: a second registry. The Directory holds no authority, serves no agent and settles nothing.
 * It pulls the SIGNED public feeds of the frames and operators its anchors already federate with, and answers
 * one question fast across all of them: *who is out there, and where do I go to deal with them.* The answer
 * always names a HOME — the interaction goes there, over that registry's own rails, under its own rules.
 *
 * It is addressed by the registry's public config (`directory_url`), never by a build-time constant: a console
 * on another frame points at another Directory, or at none, and the page is unchanged.
 */
import { normaliseBoard, type BoardRegistry } from '@/services/membership/board'

export interface DirectoryAgent {
  cardId: string
  did: string | null
  name: string | null
  humanReadableId: string | null
  description: string | null
  issuer: string | null
  shape: string | null
  source: string
  verified: boolean
  reachable: boolean
  bond: { status: string; isBonded: boolean; amount: string | null; currency: string | null }
  enforcement: { isEnforced: boolean; status: string | null }
  home: { name: string; publicUrl: string | null; tier: string | null; location: string | null } | null
  issuerFrame: { name: string } | null
  /** The settlement currency of this agent's HOME — an index row costs an FX hop when it differs from here. */
  homeCurrency?: string | null
}

/** One registry the index reads. `hop` is how far out it sits; `hops` is how deep the index walks FROM it. */
export interface DirectorySource {
  name: string
  verified: boolean
  reason: string | null
  reachable: boolean
  agentsIndexed: number
  listingsIndexed: number
  feedSupported: boolean
  hop: number | null
  hops: number | null
  currency: string | null
}

export interface DirectoryStatus {
  agentsTotal: number
  listingsTotal: number
  registriesTotal: number
  registriesVerified: number
  lastCycleAt: number | null
  sources: DirectorySource[]
}

export interface DirectoryListing {
  symbol: string
  displayName: string | null
  currency: string | null
  status: string | null
  lastPrice: string | null
  source: string
  venue: { name: string; publicUrl: string | null; tier: string | null } | null
}

const AGENT_FIELDS = `
  cardId did name humanReadableId description issuer shape source verified reachable
  bond { status isBonded amount currency }
  enforcement { isEnforced status }
  home { name publicUrl tier location }
  issuerFrame { name }`

async function gql<T>(base: string, query: string, variables: Record<string, unknown> = {}): Promise<T> {
  const r = await fetch(`${base}/graphql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, variables }),
  })
  if (!r.ok) throw new Error(`directory http ${r.status}`)
  const body = await r.json()
  // A GraphQL error arrives inside a 200. Surfacing it is the whole point: a lane that silently renders an
  // empty list on a broken index tells the reader "nobody is out there", which is a different sentence.
  if (body?.errors?.length) throw new Error(String(body.errors[0]?.message || 'directory query failed'))
  return body?.data as T
}

export const directoryService = {
  /** Agents across the federated component, optionally narrowed by name. */
  async searchAgents(base: string, q: string, first = 12): Promise<{ total: number; edges: DirectoryAgent[] }> {
    const d = await gql<{ agents: { total: number | null; edges: DirectoryAgent[] } }>(
      base,
      `query($q: String, $n: Int!) { agents(first: $n, nameContains: $q) { total edges { ${AGENT_FIELDS} } } }`,
      { q: q || null, n: first },
    )
    return { total: d?.agents?.total ?? d?.agents?.edges?.length ?? 0, edges: d?.agents?.edges || [] }
  },

  /** Every venue in the component, in one query — the cross-frame market view a single registry cannot answer. */
  async listings(base: string, first = 12): Promise<{ total: number; edges: DirectoryListing[] }> {
    const d = await gql<{ listings: { total: number | null; edges: DirectoryListing[] } }>(
      base,
      `query($n: Int!) { listings(first: $n, tradingOnly: true) { total edges { symbol displayName currency status lastPrice source venue { name publicUrl tier } } } }`,
      { n: first },
    )
    return { total: d?.listings?.total ?? d?.listings?.edges?.length ?? 0, edges: d?.listings?.edges || [] }
  },

  /** ONE call for everything the console needs from the index: its status, its agents and its venues.
   *  Three separate queries used to sit at the back of the page's own request queue (the index answers in
   *  35 ms; the wait was the queue), so the console asks once and caches the answer. */
  async snapshot(base: string, first = 200): Promise<{ status: DirectoryStatus; agents: DirectoryAgent[]; agentsTotal: number; listings: DirectoryListing[] }> {
    const d = await gql<any>(
      base,
      `query($n: Int!) {
         status { agentsTotal listingsTotal registriesTotal registriesVerified lastCycleAt
                  sources { name verified reason reachable agentsIndexed listingsIndexed feedSupported hop hops currency } }
         agents(first: $n) { total edges { ${AGENT_FIELDS} homeCurrency } }
         listings(first: 12, tradingOnly: true) { total edges { symbol displayName currency status lastPrice source venue { name publicUrl tier } } }
       }`,
      { n: first },
    )
    return {
      status: d?.status || { agentsTotal: 0, listingsTotal: 0, registriesTotal: 0, registriesVerified: 0, lastCycleAt: null, sources: [] },
      agents: d?.agents?.edges || [],
      agentsTotal: d?.agents?.total ?? (d?.agents?.edges?.length || 0),
      listings: d?.listings?.edges || [],
    }
  },

  /** §MEMBERSHIP phase C — the registry board: every registry the index reads, with its members and its commons
   *  as the Directory last read them (stack directory/board.py). Counts only; a null block means "not checked yet".
   *
   *  An index older than the board's fields rejects the WHOLE query for naming a field it does not know (GraphQL does
   *  not skip unknown fields), which would read as "the index cannot be read" while it reads fine. So the board asks
   *  again without exactly the field the index named (never `name`, at most a few times), and says which figures that
   *  index does not carry: `figures: 'unsupported'` when membership or commons had to go. A sub-field added later
   *  (OPTIONAL_SUBFIELDS: commons.cancelledRecent, board2) is dropped alone and the figures stay supported. */
  async board(base: string): Promise<{ registries: BoardRegistry[]; registriesTotal: number; lastCycleAt: number | null;
    figures: 'supported' | 'unsupported'; dropped: string[] }> {
    const fields: Record<string, string> = {
      name: 'name', tier: 'tier', location: 'location', currency: 'currency', publicUrl: 'publicUrl',
      verified: 'verified', reachable: 'reachable',
      membership: 'membership { state mode members joined30d left30d presenceMode minBondAgeDays tenureFullDays asOf readAt checkedAt error }',
      commons: 'commons { state currency seasons { id title status budget paidTotal submissions ballots opensAt endsAt closedAt paidAt cancelledAt } cancelledRecent readAt checkedAt error }',
    }
    // sub-fields a newer index added inside a block: an older one's refusal of one drops only that sub-field
    const OPTIONAL_SUBFIELDS: Record<string, { block: string; type: string }> = {
      cancelledRecent: { block: 'commons', type: 'CommonsFigures' },
    }
    const dropped: string[] = []
    for (let attempt = 0; ; attempt++) {
      const ask = Object.entries(fields).filter(([k]) => !dropped.includes(k)).map(([, v]) => v).join('\n')
      try {
        const d = await gql<any>(base, `{ status { registriesTotal lastCycleAt } registries { ${ask} } }`)
        const registries = normaliseBoard(d?.registries)
        return {
          registries, registriesTotal: d?.status?.registriesTotal ?? registries.length, lastCycleAt: d?.status?.lastCycleAt ?? null,
          figures: dropped.includes('membership') || dropped.includes('commons') ? 'unsupported' : 'supported', dropped,
        }
      } catch (e: any) {
        const m = /Cannot query field ['"]?(\w+)['"]? on type ['"]?(\w+)/.exec(String(e?.message || ''))
        const [field, type] = [m?.[1], m?.[2]]
        const sub = field ? OPTIONAL_SUBFIELDS[field] : undefined
        if (attempt >= 5 || !field) throw e
        if (sub && type === sub.type && !dropped.includes(`${sub.block}.${field}`) && new RegExp(`\\b${field}\\b`).test(fields[sub.block] || '')) {
          fields[sub.block] = fields[sub.block].replace(new RegExp(`\\s*\\b${field}\\b`), '')
          dropped.push(`${sub.block}.${field}`)
          continue
        }
        if (type !== 'Registry' || field === 'name' || !(field in fields) || dropped.includes(field)) throw e
        dropped.push(field)
      }
    }
  },

  /** What the index is, how fresh, and WHICH registries it reads — the second bar's whole content. */
  async status(base: string): Promise<DirectoryStatus> {
    const d = await gql<{ status: DirectoryStatus }>(
      base,
      `{ status { agentsTotal listingsTotal registriesTotal registriesVerified lastCycleAt
                  sources { name verified reason reachable agentsIndexed listingsIndexed feedSupported hop hops } } }`,
    )
    return d?.status || { agentsTotal: 0, listingsTotal: 0, registriesTotal: 0, registriesVerified: 0, lastCycleAt: null, sources: [] }
  },
}
