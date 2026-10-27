/**
 * §COCKPITDESK (2026-10-15) — the AGORA desk's market rail: what a person can act on comes first.
 *
 * The venue answers its listings newest first, so on a registry with a test history the rail opened on a DELISTED
 * listing and the order ticket under it said "not open for trading" (sbx-alpha: 4 trading among 175). The rail keeps
 * the venue's order inside each group and puts the groups in the order a trader needs them: trading, then the
 * IPOs still selling, then halted, then anything this build does not know, then delisted. The desk opens on the
 * first listing of that order; a `?sym=` link still opens its own listing, delisted or not.
 */
import type { Listing } from '@/services/api/exchangeService'

const RANK: Record<string, number> = { trading: 0, ipo: 1, halted: 2, delisted: 4 }

export function railRank(status: string | null | undefined): number {
  return RANK[String(status || '')] ?? 3
}

/** A stable sort by rank: two listings of one status keep the venue's order. */
export function railOrder<T extends Pick<Listing, 'status'>>(listings: readonly T[]): T[] {
  return listings
    .map((l, i) => ({ l, i, r: railRank(l.status) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.l)
}

/** The rows the rail shows: delisted listings fold away unless asked, the selected listing always stays in view (a ?sym=
 *  link may open a delisted one). */
export function railVisible<T extends Pick<Listing, 'status'> & { id: string }>(
  listings: readonly T[], showDelisted: boolean, selectedId?: string | null,
): T[] {
  return showDelisted ? [...listings] : listings.filter((l) => l.status !== 'delisted' || l.id === selectedId)
}
