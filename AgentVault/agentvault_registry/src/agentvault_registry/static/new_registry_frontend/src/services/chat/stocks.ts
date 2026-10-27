/**
 * §SHOWCASESTOCKS — one brain for what a share costs.
 *
 * WHY THIS EXISTS AS A MODULE. The first cut read `row.last_price`, a field that
 * does not exist, so every card silently fell back to `ipo_price` and the whole
 * venue looked frozen at its founding prices — SMKD showing 2.5 while the book
 * was 49/51, SLG showing 26.74 after trading at 1069.6. That is not a typo, it
 * is what happens when a shape is guessed instead of read. The live numbers live
 * under `stats`, and putting the mapping in ONE pure module means the landing
 * showcase and Pocket cannot drift into two different opinions about a price.
 *
 * PRICE TRUTH, stated in order of what it actually is:
 *   1. `stats.last`      — what it last TRADED at. The only real price.
 *   2. `stats.best_ask`  — what you would pay right now if you crossed.
 *   3. `ipo_price`       — the FOUNDING price of the float. Not a market price,
 *                          and labelled as such, because quoting it as though it
 *                          were is exactly the lie that was shipped.
 *
 * FX: a viewer on BVT reading an AVT listing is the common case across a
 * federation, so a converted figure is offered ALONGSIDE the native one, never
 * instead of it — the §FOREIGNACT rule. Amount and unit travel together, and an
 * unavailable rate yields no converted figure rather than a guess.
 */

export type FxPair = { a: string; b: string; a_per_b: string; b_per_a: string }
export type FxRates = { available?: boolean; pairs?: FxPair[] } | null

export type StockRow = {
  symbol: string
  displayName: string
  currency: string
  /** what it last traded at — null when it has never traded */
  last: string | null
  bid: string | null
  ask: string | null
  /** the founding float price; NEVER presented as a market price */
  ipo: string | null
  status: string
  origin: string
  isLocal: boolean
  trades24h: number | null
  change24h: string | null
}

function s(v: any): string | null {
  if (v === null || v === undefined) return null
  const t = String(v)
  return t.length ? t : null
}

/** Trim insignificant trailing zeros. A NORMALISATION, never a rounding:
 *  `1000`, `0.000001` and `1e18` all survive untouched. */
export function trim(v: string | null): string | null {
  if (v == null) return null
  if (!/^-?\d+(\.\d+)?$/.test(v)) return v
  if (!v.includes('.')) return v
  const out = v.replace(/0+$/, '').replace(/\.$/, '')
  return out === '' || out === '-' ? '0' : out
}

/** Merge live prices from `/agora/federation-tickers` into rows that came
 *  from the federated catalog.
 *
 *  🔴 WHY THIS IS NEEDED, AND WHY IT WAS THE SAME BUG TWICE. The network catalog
 *  carries NO `stats` for foreign rows, so `effectivePrice` fell through to
 *  `ipo_price` for every listing on another venue — SYBIL quoted at its founding
 *  5.0 while it last traded at 105.1, which is why a passport buy came back
 *  "price outside ±25% band around 105.100000000000000000". The venue was right
 *  and the price we sent was a fossil. `federation-tickers` is the rail that
 *  actually carries foreign `last`, and not asking it was the identical mistake
 *  to reading `last_price` instead of `stats.last` on the local side. */
export function mergeTickers(rows: StockRow[], tickers: any): StockRow[] {
  const live = new Map<string, { last: string | null; ask: string | null; venue: string }>()
  for (const v of (tickers?.venues ?? [])) {
    for (const l of (v?.listings ?? [])) {
      const sym = String(l?.symbol ?? '').toUpperCase()
      if (sym) live.set(sym, { last: trim(s(l?.last)), ask: trim(s(l?.best_ask)),
                               venue: String(v?.venue ?? '') })
    }
  }
  return rows.map(r => {
    // Local rows already carry a live book from the local venue; never let a
    // cached ticker overwrite it.
    if (r.isLocal) return r
    const hit = live.get(r.symbol)
    if (!hit) return r
    // 🔴 THE ASK, AND THE GUARD THAT HID IT. This used to bail on `r.last`, so a
    // foreign row that already knew its last trade never picked up an ask — and
    // effectivePrice then priced the buy at the LAST TRADE. You must MEET the ask
    // to buy: measured 2026-08-26, FLUX last 21.38 against ask 23.00 relayed and
    // never filled. Fill in whichever half is missing; never overwrite either.
    return { ...r, last: r.last || hit.last, ask: r.ask || hit.ask }
  })
}

/** Normalise a row from `/agora/listings` OR `/agora/network-listings`.
 *  The two shapes differ: the local one carries `stats`, the federated catalog
 *  carries `origin` + `is_local` and may carry no stats at all. */
export function normalizeListing(row: any): StockRow {
  const st = row?.stats ?? {}
  return {
    symbol: String(row?.symbol ?? '').toUpperCase(),
    displayName: String(row?.display_name ?? ''),
    currency: String(row?.currency ?? ''),
    last: trim(s(st.last)),
    bid: trim(s(st.best_bid)),
    ask: trim(s(st.best_ask)),
    ipo: trim(s(row?.ipo_price)),
    status: String(row?.status ?? ''),
    origin: String(row?.origin ?? ''),
    isLocal: row?.is_local !== false,
    trades24h: st.trades_24h != null ? Number(st.trades_24h) : null,
    change24h: trim(s(st.change_24h)),
  }
}

/** The number a buyer would actually pay, and WHICH number it is. Never
 *  collapses the three into one figure, because "last traded" and "nobody has
 *  ever traded this" are different facts a reader is entitled to. */
export function effectivePrice(r: StockRow): { value: string | null; basis: 'ask' | 'last' | 'ipo' | 'none' } {
  if (r.ask) return { value: r.ask, basis: 'ask' }
  if (r.last) return { value: r.last, basis: 'last' }
  if (r.ipo) return { value: r.ipo, basis: 'ipo' }
  return { value: null, basis: 'none' }
}

/** Can this actually be bought, and if not, WHY. A listing that cannot trade
 *  must say so where a reader is choosing — "nothing happened" after a click is
 *  the worst possible answer, and `halted` / `delisted` / `ipo` are facts the
 *  venue already publishes. */
export function tradability(r: StockRow, opts?: { maxPerTx?: number; balance?: number }):
    { ok: boolean; reason: string } {
  const st = (r.status || '').toLowerCase()
  if (st === 'halted') return { ok: false, reason: 'halted by the market' }
  if (st === 'delisted') return { ok: false, reason: 'delisted' }
  if (st === 'ipo') return { ok: false, reason: 'still at launch: buy from the launch allocation' }
  if (st && st !== 'trading') return { ok: false, reason: st }
  const eff = effectivePrice(r)
  if (!eff.value) return { ok: false, reason: 'no price on the book yet' }
  // 🔴 A FOREIGN ROW PRICED FROM ITS FLOAT IS NOT A PRICE, IT IS A FOSSIL.
  // Measured by buying every listing once: sending `ipo_price` to a foreign
  // venue came back "price outside ±25% band around 134.81" (NEKO) and
  // "…around 358.83" (ZAP), because op-london and op-newyork are not in the
  // federation-tickers rail, so no live price for them reaches this registry.
  // Refusing with the reason beats relaying a number the venue will reject.
  if (!r.isLocal && eff.basis === 'ipo') {
    return { ok: false, reason: `no live price reaches this registry from ${r.origin || 'that market'}` }
  }
  const px = Number(eff.value)
  if (opts?.maxPerTx != null && isFinite(px) && px > opts.maxPerTx) {
    return { ok: false, reason: `above your ${opts.maxPerTx} per-payment cap` }
  }
  if (opts?.balance != null && isFinite(px) && px > opts.balance) {
    return { ok: false, reason: 'costs more than your balance' }
  }
  return { ok: true, reason: '' }
}

/** Convert across the currency triangle. Returns null when no rate is
 *  published — an unavailable rate must produce no figure, never a guess. */
export function fxConvert(amount: string | null, from: string, to: string, rates: FxRates): string | null {
  if (!amount || !from || !to) return null
  if (from === to) return amount
  const pairs = rates?.pairs
  if (!Array.isArray(pairs)) return null
  const n = Number(amount)
  if (!isFinite(n)) return null
  for (const p of pairs) {
    // a_per_b = how many A one B buys.
    if (p.a === to && p.b === from) {
      const r = Number(p.a_per_b); if (!isFinite(r)) return null
      return trim((n * r).toFixed(6))
    }
    if (p.a === from && p.b === to) {
      const r = Number(p.b_per_a); if (!isFinite(r)) return null
      return trim((n * r).toFixed(6))
    }
  }
  return null
}

const BASIS_WORD: Record<string, string> = {
  ask: 'best ask', last: 'last traded', ipo: 'launch price, never traded', none: 'no price',
}

/** One line of honest price for a listing, from a viewer's seat. */
export function priceLine(r: StockRow, viewerCcy: string | null, rates: FxRates,
                          opts?: { maxPerTx?: number; balance?: number }): string {
  const { value, basis } = effectivePrice(r)
  if (!value) return `${r.symbol} — no price yet (${r.status || 'unknown'})`
  let line = `${r.symbol}  ${value} ${r.currency}`
  if (viewerCcy && viewerCcy !== r.currency) {
    const conv = fxConvert(value, r.currency, viewerCcy, rates)
    // Offered alongside, never instead of, and omitted entirely when the rate
    // is not published rather than silently showing the native figure as if it
    // were the viewer's.
    if (conv) line += `  (≈ ${conv} ${viewerCcy})`
  }
  line += `  · ${BASIS_WORD[basis]}`
  if (!r.isLocal && r.origin) line += `  · ${r.origin}`
  // Say when it cannot be bought, right where someone is choosing.
  const t = tradability(r, opts)
  if (!t.ok) line += `  · NOT TRADEABLE (${t.reason})`
  if (r.trades24h != null && r.trades24h > 0) line += `  · ${r.trades24h} trade${r.trades24h === 1 ? '' : 's'}/24h`
  return line
}
