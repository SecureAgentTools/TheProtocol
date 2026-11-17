// V0664 C3 (order gwo_4110e12c11a69a93de878829): My proxies, read. A proxy reports its status as its own agent (C2: POST
// /api/v1/agents/me/proxy-status, names and counts only); its owner reads every reporting agent at once (GET
// /api/v1/developers/me/proxy-status) and an agent's recent ledger (GET /api/v1/teg/transactions/history/{did}). These are
// the pure readers: whatever a field holds that is not what C2 promises reads as nothing, never as a guess.
type Json = any

export interface MappingStatus { name: string; pending: number; done: number; dead: number; paused: boolean; breaker: string | null }
export interface SourceStatus { name: string; finished: boolean; lastReadAt: string | null }
export interface ProxyRow {
  did: string; name: string; sdkVersion: string; reportedAt: string; ageS: number; uptimeS: number
  mappings: MappingStatus[]; sources: SourceStatus[]; totals: { pending: number; done: number; dead: number }
}

const count = (v: Json): number => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0)
const text = (v: Json): string => (typeof v === 'string' ? v : '')
const obj = (v: Json): Record<string, Json> => (v && typeof v === 'object' && !Array.isArray(v) ? v : {})

export function normalizeProxies(data: Json): ProxyRow[] {
  const items: Json[] = Array.isArray(data?.items) ? data.items : []
  const out: ProxyRow[] = []
  for (const it of items) {
    const did = text(it?.agent_did)
    if (!did) continue
    const r = obj(it?.report)
    const mappings = Object.entries(obj(r.mappings)).map(([name, m]): MappingStatus => ({
      name, pending: count(m?.pending), done: count(m?.done), dead: count(m?.dead), paused: m?.paused === true,
      breaker: typeof m?.breaker === 'string' && m.breaker ? m.breaker : null,
    }))
    const sources = Object.entries(obj(r.sources)).map(([name, s]): SourceStatus => ({
      name, finished: s?.finished === true, lastReadAt: typeof s?.last_read_at === 'string' ? s.last_read_at : null,
    }))
    const totals = mappings.reduce((t, m) => ({ pending: t.pending + m.pending, done: t.done + m.done, dead: t.dead + m.dead }),
      { pending: 0, done: 0, dead: 0 })
    out.push({ did, name: text(r.name) || did, sdkVersion: text(r.sdk_version), reportedAt: text(it?.reported_at),
      ageS: count(it?.age_s), uptimeS: count(r.uptime_s), mappings, sources, totals })
  }
  return out
}

export type Freshness = 'fresh' | 'quiet' | 'silent'
/** How long since the proxy last reported: fresh under 10 minutes (init writes report_every_s 300), quiet under an hour. */
export function freshness(ageS: number): Freshness {
  return ageS < 600 ? 'fresh' : ageS < 3600 ? 'quiet' : 'silent'
}

export type Attention =
  | { kind: 'dead'; mapping: string; count: number }
  | { kind: 'paused'; mapping: string }
  | { kind: 'breaker'; mapping: string; state: string }
  | { kind: 'silent' }

/** What needs the owner, mapping by mapping: records that will not be sent again, a paused mapping, an open breaker; and a
 *  proxy that has stopped reporting. */
export function attention(p: ProxyRow): Attention[] {
  const out: Attention[] = []
  for (const m of p.mappings) {
    if (m.dead > 0) out.push({ kind: 'dead', mapping: m.name, count: m.dead })
    if (m.paused) out.push({ kind: 'paused', mapping: m.name })
    if (m.breaker) out.push({ kind: 'breaker', mapping: m.name, state: m.breaker })
  }
  if (freshness(p.ageS) === 'silent') out.push({ kind: 'silent' })
  return out
}

export interface LedgerRow { id: string; type: string; amount: string; at: string }
/** An agent's recent ledger rows, newest first; a row without an id is not a row. */
export function normalizeLedger(data: Json): LedgerRow[] {
  const txs: Json[] = Array.isArray(data?.transactions) ? data.transactions : []
  return txs
    .map((t): LedgerRow => ({ id: text(t?.id) || text(t?.transaction_id), type: text(t?.event_type) || text(t?.type),
      amount: t?.amount === undefined || t?.amount === null ? '' : String(t.amount), at: text(t?.timestamp) || text(t?.created_at) }))
    .filter((r) => r.id)
    .sort((a, b) => b.at.localeCompare(a.at))
}

/** Every fact that needs the owner, one group per mapping (in the report's order), then the proxy's own (it has stopped
 *  reporting): a line per mapping names it once. */
export function attentionGroups(p: ProxyRow): Array<{ mapping: string | null; facts: Attention[] }> {
  const out: Array<{ mapping: string | null; facts: Attention[] }> = []
  for (const a of attention(p)) {
    const mapping = a.kind === 'silent' ? null : a.mapping
    const g = out.find((x) => x.mapping === mapping)
    if (g) g.facts.push(a)
    else out.push({ mapping, facts: [a] })
  }
  return out
}

/** Whole seconds from an ISO time to now (0 for a time in the future); null for a time it cannot read. */
export function secondsSince(iso: string, now: number): number | null {
  const at = Date.parse(iso || '')
  if (!Number.isFinite(at)) return null
  return Math.max(0, Math.floor((now - at) / 1000))
}

export type LedgerKind = 'transfer' | 'fee' | 'issued' | 'other'
/** A ledger event as the kind of move it is; an event this console does not know is 'other' and keeps its own name. */
export function ledgerKind(type: string): LedgerKind {
  if (/FeeCollected$/.test(type)) return 'fee'
  if (/Transfer(red|Completed)$/.test(type)) return 'transfer'
  if (/Issued$/.test(type)) return 'issued'
  return 'other'
}

/** A ledger amount (a decimal string, up to 18 places) without its trailing zeros, grouped and pointed as the language
 *  writes numbers. Exact: the digits are never turned into a float. A value that is not a decimal is shown as it came. */
export function formatAmount(amount: string, locale: string): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec((amount || '').trim())
  if (!m) return amount || ''
  const [, sign, whole, frac = ''] = m
  const parts = new Intl.NumberFormat(locale).formatToParts(1.5)
  const point = parts.find((x) => x.type === 'decimal')?.value || '.'
  const grouped = BigInt(whole!).toLocaleString(locale)
  const tail = frac.replace(/0+$/, '')
  return `${sign}${grouped}${tail ? point + tail : ''}`
}

/** The tail of a DID a card has room for: its network's first name (eu.theprotocol.cloud reads eu), the id's first eight
 *  and last four characters; the method (did:theprotocol) is every agent's, so it is left out. The whole DID stays in the
 *  element's title and in what Copy DID copies. */
export function didTail(did: string): string {
  const parts = did.split(':')
  if (parts.length < 3 || parts[0] !== 'did') return did
  const id = parts[parts.length - 1]!
  const network = parts.slice(2, -1).map((x) => x.split('.')[0])
  return [...network, id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id].join(':')
}

/** The proxies that need their owner first: a silent one, then one with records given up, then one paused or with a breaker
 *  set; within each, and for the rest, the order the registry gave (newest report first). */
export function needsFirst(rows: ProxyRow[]): ProxyRow[] {
  const rank = (p: ProxyRow) => {
    const a = attention(p)
    if (a.some((x) => x.kind === 'silent')) return 0
    if (a.some((x) => x.kind === 'dead')) return 1
    return a.length ? 2 : 3
  }
  return rows.map((p, i) => ({ p, i, r: rank(p) })).sort((x, y) => x.r - y.r || x.i - y.i).map((x) => x.p)
}
