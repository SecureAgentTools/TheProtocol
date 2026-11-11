/**
 * V0658 (q): reading follows ownership, acting needs the party agent.
 *
 * The owner's reads (GET /guild/owned, GET /contracts/v2/owned, and a developer's GET /guild/orders/{id}) name which
 * parties of a row are the reader's (`my_parties`: an agent he created, via "agent", or an agent a member brought into
 * an organization he owns, via "organization"). A view asks two things of a row: is the acting agent a party of it (then
 * that agent acts, as before), and if not, which of the reader's parties to name, so the owner sees the order or the
 * contract whichever agent is selected and is told which one may act on it.
 */
import type { MyParty } from '@/services/api/guild'

const PARTY_FIELDS = ['poster_did', 'worker_did', 'client_did', 'provider_did'] as const

/** The reader's parties on a row, as the registry named them (an empty list when it named none). */
export function myParties(row: unknown): MyParty[] {
  const p = (row as { my_parties?: unknown } | null | undefined)?.my_parties
  if (!Array.isArray(p)) return []
  return p.filter((x): x is MyParty => !!x && typeof (x as MyParty).agent_did === 'string' && !!(x as MyParty).agent_did)
}

function same(a: unknown, b: unknown): boolean {
  return typeof a === 'string' && typeof b === 'string' && !!a && a.toLowerCase() === b.toLowerCase()
}

/** Is the acting agent one of the row's parties (the poster or the worker, the client or the provider)? */
export function actingIsParty(row: unknown, actingDid: string | null | undefined): boolean {
  if (!row || !actingDid) return false
  const r = row as Record<string, unknown>
  return PARTY_FIELDS.some((k) => same(r[k], actingDid))
}

/** The reader's party to name: the first of his parties when the acting agent is none of the row's parties; null when
 *  the acting agent is one (it acts, as before) or when none of the parties is the reader's. */
export function ownerParty(row: unknown, actingDid: string | null | undefined): MyParty | null {
  const mine = myParties(row)
  if (!mine.length || actingIsParty(row, actingDid)) return null
  return mine[0]
}

/** How a view calls a party: its name, else a short form of its DID. */
export function partyName(p: Pick<MyParty, 'name' | 'agent_did'>): string {
  if (p.name && p.name.trim()) return p.name.trim()
  const d = String(p.agent_did || '')
  return d.length > 26 ? `${d.slice(0, 15)}…${d.slice(-5)}` : d
}
