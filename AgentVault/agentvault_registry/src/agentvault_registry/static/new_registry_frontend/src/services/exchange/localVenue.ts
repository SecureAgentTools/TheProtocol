/**
 * §FESUITE (2026-10-10, the operator batch) — which venue on the federation board is THIS registry's own market.
 *
 * The board (/agora/federation-tickers) lists this registry's own venue beside its peers on purpose (the self-include in
 * routers/exchange.py), so a person sees every market. Its listings are bought here, on this market, never through a
 * passport: the passport rail exists for a FOREIGN market. The desktop screener tells them apart by symbol
 * (StockDiscovery.detectLocalVenue: the venue whose listings this registry also lists itself); Pocket now asks the same
 * rule, here. '' while either list is empty (unread, or a market with nothing listed): no venue is called local then.
 */
export interface BoardVenue {
  venue: string
  listings?: { symbol?: string | null }[]
}

export function localVenueOf(venues: BoardVenue[], ownSymbols: string[]): string {
  const own = new Set(ownSymbols.filter(Boolean))
  if (!own.size) return ''
  const v = venues.find((x) => (x.listings || []).some((l) => !!l.symbol && own.has(l.symbol)))
  return v?.venue || ''
}
