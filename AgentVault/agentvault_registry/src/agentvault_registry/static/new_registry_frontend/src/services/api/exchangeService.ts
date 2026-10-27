/**
 * AGORA exchange API client (2026-06-12).
 *
 * Endpoint map (auth injected by client.ts URL rules — see isAgentEndpoint):
 *   GET  /api/v1/agora/listings                       public
 *   GET  /api/v1/agora/listings/{ref}                 public
 *   GET  /api/v1/agora/listings/{ref}/book            public
 *   GET  /api/v1/agora/listings/{ref}/trades          public
 *   GET  /api/v1/agora/listings/{ref}/candles         public
 *   GET  /api/v1/agora/top-traders                    public
 *   POST /api/v1/agora/orders                         agent JWT
 *   DEL  /api/v1/agora/orders/{id}                    agent JWT
 *   GET  /api/v1/agora/orders/mine                    agent JWT
 *   GET  /api/v1/agora/portfolio                      agent JWT
 *   POST /api/v1/agora/listings/{ref}/launch/buy         agent JWT
 *   POST /api/v1/agora/listings                       developer JWT (org owner)
 *   POST /api/v1/agora/listings/{ref}/distributions       developer JWT (org admin)
 */
import { apiClient } from './client'

export interface ListingStats {
  last: string | null
  best_bid: string | null
  best_ask: string | null
  volume_24h_qty: string
  volume_24h_notional: string
  trades_24h: number
  low_24h: string | null
  high_24h: string | null
  change_24h_pct: string | null
  market_cap: string | null
  ipo_remaining: number
}

export interface Listing {
  id: string
  symbol: string
  display_name: string
  organization_id: string
  currency: string
  total_shares: number
  ipo_price: string
  ipo_float: number
  ipo_sold: number
  fee_bps: number
  tick: string
  band_pct: number
  approved: boolean
  status: 'ipo' | 'trading' | 'halted' | 'delisted'
  cb_pct?: number          // §#84 circuit-breaker threshold (bps; 0/undefined = off)
  cb_halted_until?: string | null
  treasury_agent_did: string
  created_at: string | null
  stats?: ListingStats | null
}

export interface BookLevel { price: string; qty: number }
export interface Book { bids: BookLevel[]; asks: BookLevel[] }
export interface Tape {
  seq: number; price: string; qty: number; notional: string
  at: string; buyer_did: string; seller_did: string
}
export interface Candle { t: string; o: string; h: string; l: string; c: string; v: number }
export interface PlaceOrderResult {
  order_id: string; status: string; side: string; order_type: string
  price: string | null; qty: number; remaining: number; escrow_amount: string
  fills: { trade_id: string; price: string; qty: number; notional: string }[]
}
export interface MyOrder {
  id: string; symbol: string; side: string; type: string; price: string | null
  qty: number; remaining: number; status: string; escrow_amount: string; created_at: string
}
export interface Position {
  symbol: string; listing_id: string; qty: number; locked_qty: number
  avg_cost: string; last: string | null; unrealized_pnl: string | null; currency: string
}
export interface Portfolio { agent_did: string; positions: Position[]; dividends_received: string }
export interface TopTrader { agent_did: string; volume: string; trades: number }

/* §COCKPITBOOK — the ACCOUNT-WIDE book.
 * `Portfolio` above answers for ONE agent (agent-tier, and rightly so: shares are held by
 * an agent, not by a person). These types answer "what does this developer's fleet hold",
 * which no per-agent rail can say without being asked thousands of times. */
export interface BookHolder { agent_did: string; name: string | null; qty: number }
export interface BookPosition {
  listing_id: string
  symbol: string
  display_name: string | null
  currency: string
  qty: number
  locked_qty: number
  cost_basis: string
  avg_cost: string | null
  /** null = this listing has never traded. NOT a price of zero. */
  last: string | null
  last_trade_at: string | null
  ipo_price: string | null
  listing_status: string | null
  /** null when `last` is null — an unmarked position has no value, not a zero one. */
  market_value: string | null
  unrealized_pnl: string | null
  holders: number
  top_holders: BookHolder[]
}
export interface BookCurrency {
  currency: string
  cost_basis: string
  market_value: string
  unrealized_pnl: string
  positions: number
  /** How many positions in this currency carry NO mark, so the reader knows the total
   *  above is a floor rather than the whole book. */
  unpriced_positions: number
}
export interface MyBook {
  positions: BookPosition[]
  /** One entry per currency. NEVER summed together (§SUMSPLIT / §FOREIGNACT). */
  currencies: BookCurrency[]
  agents_holding: number
  dividends: { legs: number; amount: string }
  as_of: string
}

class ExchangeService {
  async listings(): Promise<{ listings: Listing[]; count: number }> {
    const { data } = await apiClient.get('/agora/listings')
    return data
  }

  async listing(ref: string): Promise<Listing> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}`)
    return data
  }

  async book(ref: string, depth = 12): Promise<Book> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}/book`, { params: { depth } })
    return data
  }

  async trades(ref: string, limit = 50): Promise<{ trades: Tape[] }> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}/trades`, { params: { limit } })
    return data
  }

  async candles(ref: string, tf = '1h', limit = 120): Promise<{ tf: string; candles: Candle[] }> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}/candles`, { params: { tf, limit } })
    return data
  }

  async topTraders(hours = 24, limit = 10): Promise<{ traders: TopTrader[] }> {
    const { data } = await apiClient.get('/agora/top-traders', { params: { hours, limit } })
    return data
  }

  // §V0113 Org Consolidated Treasury — holding-company roll-up (org-member gated server-side).
  async orgTreasury(orgId: string): Promise<{
    organization_id: string
    currency: string | null
    listing_count: number
    totals: { balance: string; raised: string; fees_earned: string; dividends_paid: string }
    listings: Array<{
      symbol: string; treasury_agent_did: string; currency: string; status: string
      balance: string | null; available: string | null
      raised: string; fees_earned: string; dividends_paid: string
      ipo_sold: number; ipo_float: number; total_shares: number; ipo_price: string
    }>
  }> {
    const { data } = await apiClient.get(`/agora/organizations/${encodeURIComponent(orgId)}/treasury`)
    return data
  }

  async placeOrder(body: {
    listing: string; side: 'buy' | 'sell'; order_type: 'limit' | 'market'
    qty: number; price?: string; client_order_id?: string; ttl_seconds?: number
    tif?: 'gtc' | 'ioc' | 'fok'; post_only?: boolean; stop_price?: string
  }): Promise<PlaceOrderResult> {
    const { data } = await apiClient.post('/agora/orders', body)
    return data
  }

  async cancelOrder(orderId: string): Promise<{ order_id: string; status: string }> {
    const { data } = await apiClient.delete(`/agora/orders/${encodeURIComponent(orderId)}`)
    return data
  }

  async myOrders(listing?: string): Promise<{ orders: MyOrder[] }> {
    const { data } = await apiClient.get('/agora/orders/mine', { params: listing ? { listing } : {} })
    return data
  }

  /** Every AGORA position held by any agent this developer owns, in ONE call. */
  async myBook(topHolders = 5): Promise<MyBook> {
    const { data } = await apiClient.get('/developers/me/holdings-book', {
      params: { top_holders: topHolders },
    })
    return data
  }

  async portfolio(): Promise<Portfolio> {
    const { data } = await apiClient.get('/agora/portfolio')
    return data
  }

  async ipoBuy(ref: string, qty: number): Promise<{ purchase_id: string; status: string; qty: number; amount: string }> {
    const { data } = await apiClient.post(`/agora/listings/${encodeURIComponent(ref)}/launch/buy`, { qty })
    return data
  }

  async createListing(body: {
    organization_id: string; symbol: string; total_shares: number; ipo_float: number
    ipo_price: string; funding_agent_did: string; display_name?: string
  }): Promise<Listing & { note?: string }> {
    const { data } = await apiClient.post('/agora/listings', body)
    return data
  }

  async declareDividend(ref: string, perShare: string): Promise<{ dividend_id: string; total_amount: string; status: string }> {
    const { data } = await apiClient.post(`/agora/listings/${encodeURIComponent(ref)}/distributions`, { per_share: perShare })
    return data
  }

  // §V0113 Phase 2 — org treasury spend actions (org-admin gated server-side).
  async treasuryDividend(orgId: string, symbol: string, perShare: string): Promise<{ dividend_id: string; total_amount: string; status: string }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/distribution`, { per_share: perShare })
    return data
  }

  async treasuryBuyback(orgId: string, symbol: string, qty: number, limitPrice: string): Promise<{ order_id: string; order_status: string; status: string }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/buy`, { qty, limit_price: limitPrice })
    return data
  }

  async treasuryTransfer(orgId: string, symbol: string, destDid: string, amount: string, reserveFloor?: string): Promise<{ transaction_id: string; status: string }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/transfer`, { dest_did: destDid, amount, reserve_floor: reserveFloor })
    return data
  }

  async treasurySweep(orgId: string, fromSymbol: string, toSymbol: string, amount: string): Promise<{ transaction_id: string; status: string }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(fromSymbol)}/sweep`, { to_symbol: toSymbol, amount })
    return data
  }

  // §P1.1 re-float retained treasury shares into the buyable float (reprices to market by default)
  async treasuryRefloat(orgId: string, symbol: string, qty: number, offerPrice?: string, minRetained?: number): Promise<{ status: string; buyable_now: number; offer_price: string; treasury_remaining: number }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/refloat`, { qty, offer_price: offerPrice, min_retained: minRetained })
    return data
  }

  // §P1.2 treasury market-sell (distribute shares at market via the CLOB)
  async treasurySell(orgId: string, symbol: string, qty: number, orderType: string, limitPrice?: string, minRetained?: number): Promise<{ status: string; order_id: string; order_status: string }> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/sell`, { qty, order_type: orderType, limit_price: limitPrice, min_retained: minRetained })
    return data
  }

  // §P2.1 treasury market-maker config (read/upsert)
  async treasuryMMGet(orgId: string, symbol: string): Promise<any> {
    const { data } = await apiClient.get(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/mm`)
    return data
  }
  async treasuryMMSet(orgId: string, symbol: string, cfg: { enabled?: boolean; spread_bps?: number; quote_qty?: number; reserve_shares?: number; cash_floor?: string; ref_mode?: string }): Promise<any> {
    const { data } = await apiClient.put(`/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/mm`, cfg)
    return data
  }

  // §P3.1 share-weighted shareholder governance
  async listProposals(listingRef: string): Promise<{ symbol: string; proposals: any[] }> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(listingRef)}/proposals`)
    return data
  }
  async getProposal(proposalId: string): Promise<any> {
    const { data } = await apiClient.get(`/agora/proposals/${encodeURIComponent(proposalId)}`)
    return data
  }
  async createProposal(orgId: string, body: { symbol: string; title: string; description: string; duration_seconds: number; quorum_pct?: number; pass_pct?: number }): Promise<any> {
    const { data } = await apiClient.post(`/agora/organizations/${encodeURIComponent(orgId)}/proposals`, body)
    return data
  }
  async tallyProposal(proposalId: string): Promise<any> {
    const { data } = await apiClient.post(`/agora/proposals/${encodeURIComponent(proposalId)}/tally`)
    return data
  }
  // §P3.1 — cast a share-weighted vote. AGENT-JWT endpoint: the request interceptor in
  // client.ts routes /exchange/proposals/*/vote to the active agent token (not the dev JWT).
  async castVote(proposalId: string, inFavor: boolean, reason?: string): Promise<any> {
    const { data } = await apiClient.post(`/agora/proposals/${encodeURIComponent(proposalId)}/vote`, { in_favor: inFavor, reason })
    return data
  }

  // ── §2026-06-22 P2.2 maker-rebate + designated market-makers ─────────────
  // Set the maker rebate on a listing (ORG-ADMIN; dev JWT). NOTE: maker_rebate_bps is
  // REQUIRED in the body even when only flipping rebate_requires_registration.
  async setMakerRebate(orgId: string, symbol: string, makerRebateBps: number, rebateRequiresRegistration?: boolean): Promise<MakerRebateInfo> {
    const { data } = await apiClient.put(
      `/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/maker-rebate`,
      { maker_rebate_bps: makerRebateBps, rebate_requires_registration: rebateRequiresRegistration },
    )
    return data
  }

  // Grant / revoke a designated MM seat (ORG-ADMIN; dev JWT).
  async grantMarketMaker(orgId: string, symbol: string, body: { agent_did: string; status: 'active' | 'suspended' | 'revoked'; min_uptime_pct?: number; max_spread_bps?: number }): Promise<any> {
    const { data } = await apiClient.post(
      `/agora/organizations/${encodeURIComponent(orgId)}/listings/${encodeURIComponent(symbol)}/market-makers`,
      body,
    )
    return data
  }

  // PUBLIC — designated market-makers committed to a listing (+ rebate config).
  async marketMakers(ref: string): Promise<MarketMakerList> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}/market-makers`)
    return data
  }

  // §P5 (5.6) admin fee-edit — set fee_bps / fee_org_split_bps / maker_rebate_bps (ORG-ADMIN; dev JWT).
  // Only the provided fields update; the service re-validates the rebate fits the protocol slice.
  async setListingFees(orgId: string, symbol: string, body: { fee_bps?: number; fee_org_split_bps?: number; maker_rebate_bps?: number }): Promise<any> {
    const { data } = await apiClient.put(
      `/agora/organizations/${encodeURIComponent(orgId)}/treasury/${encodeURIComponent(symbol)}/fees`,
      body,
    )
    return data
  }

  // ── §2026-06-22 P5 (5.4) public cap-table + AGORA index ──────────────────
  // PUBLIC cap-table — external shareholders (EXCLUDES keyless org treasury). pct is a decimal STRING.
  async holders(ref: string, limit = 50, offset = 0): Promise<HoldersResult> {
    const { data } = await apiClient.get(`/agora/listings/${encodeURIComponent(ref)}/holders`, { params: { limit, offset } })
    return data
  }

  // PUBLIC value-weighted "AGORA N" index (points × last price). index_value/weight_pct/market_cap are decimal STRINGS.
  async index(topN = 10): Promise<AgoraIndex> {
    const { data } = await apiClient.get('/agora/index', { params: { top_n: topN } })
    return data
  }

  // ── §2026-06-22 P4 public solvency card (signed credibility attestation) ──
  // PUBLIC — the venue's signed solvency/float attestation over ALL its listings.
  // Filter to a listing's symbol in `listings[]`. Returns null when the venue serves no card.
  async solvencyCard(): Promise<SolvencyCard | null> {
    try {
      // §FESUITE: the card was served at /exchange/solvency-card (and /.well-known/solvency-card.json) only; the /agora
      // alias never reached it, so the desk answered "no card" even where one exists (EU: 200 there, 404 here).
      // §DOCSFIX D6-655: /agora/solvency-card answers from this release on; the desk keeps the older name, which every
      // registry serves.
      // PUBLIC and OPTIONAL: a venue serves it only behind EXCHANGE_SOLVENCY_CARD_ENABLED (default off), so 404 is the
      // ordinary answer "no card here". It is read outside apiClient, whose global handler toasted every such 404 as
      // "Not Found: Request failed" on the desk of every venue without the card.
      const base = String(apiClient.defaults.baseURL || '/api/v1').replace(/\/$/, '')
      const r = await fetch(`${base}/exchange/solvency-card`, { headers: { Accept: 'application/json' } })
      if (!r.ok) return null
      return (await r.json()) as SolvencyCard
    } catch { return null } // venue may not serve a solvency card (flag/feature off)
  }

  /**
   * §V0064 P2 — equity-map: THIS venue's listed orgs keyed by org id, each
   * carrying its member agent DIDs. Powers the $TICKER chip on MyAgents /
   * Discovery (join Agent → org → listing without widening the agent schema).
   * Flattened to a did→equity lookup for cheap per-card resolution. Returns {}
   * when the venue is dark or unreachable — callers render chip-less.
   */
  async equityByDid(): Promise<Record<string, EquityChip>> {
    const byDid: Record<string, EquityChip> = {}
    try {
      const { data } = await apiClient.get('/agora/equity-map')
      for (const [orgId, e] of Object.entries((data?.orgs || {}) as Record<string, EquityOrg>)) {
        const chip: EquityChip = {
          organization_id: orgId, symbol: e.symbol, currency: e.currency,
          last: e.last, status: e.status,
        }
        for (const did of e.agent_dids || []) byDid[did] = chip
      }
    } catch { /* dark venue — no chips */ }
    return byDid
  }

  // ── §POCKETBRIDGE3 (A2/D3-5) — federation board + passport trading ──────
  /**
   * Cross-venue tickers (PUBLIC, 15s server cache, 4s per-venue probe).
   * HONESTY CONTRACT: a dark/unreachable/empty venue is simply OMITTED from
   * `venues` — the caller must state "venues answering right now", never
   * imply the list is the whole federation.
   */
  /** §SHOWCASESTOCKS — the network-wide catalog: this venue's listings UNION
   *  the federated stock cards from every peer venue. `/agora/listings` is
   *  LOCAL only, which is why the showcase reported "no foreign stocks listed"
   *  while nine were trading on four other venues. */
  async networkListings(): Promise<{ listings: any[]; sources?: any[]; count?: number }> {
    const { data } = await apiClient.get('/agora/network-listings')
    return data
  }

  /** Live cross-frame spot for every pair in the currency triangle. Public.
   *  A missing rate must yield NO converted figure rather than a guess, so
   *  callers treat a failure here as "show the native price only". */
  async fxRates(): Promise<any> {
    const { data } = await apiClient.get('/teg/fx/rates')
    return data
  }

  /** The caller's own signed holding certificate for one symbol. */
  async shareCertificate(symbol: string): Promise<any> {
    const { data } = await apiClient.get('/agora/certificate', { params: { symbol } })
    return data
  }

  async federationTickers(): Promise<FederationTickers> {
    const { data } = await apiClient.get('/agora/federation-tickers')
    return data
  }

  /**
   * Passport order on a peer venue (agent JWT + exchange.trade; the home
   * registry must have EXCHANGE_PASSPORT_ENABLED). A 200 is ACCEPTANCE, not a
   * fill — buys come back `status: "funding"` and settle asynchronously
   * (minutes to hours); poll passportOrderStatus. Buy-only from Pocket v1,
   * matching the desktop surface.
   */
  async passportOrder(body: {
    venue_registry: string; listing: string; qty: number
    price: string; side?: 'buy' | 'sell'; fx_buffer_pct?: number
  }): Promise<any> {
    const { data } = await apiClient.post('/agora/passport/orders', body)
    return data
  }

  /** The venue's view of up to 50 of YOUR passport orders (mainframes only until the next fleet roll). */
  async passportOrderStatus(venue_registry: string, order_ids: string[]): Promise<any> {
    const { data } = await apiClient.post('/agora/passport/order-status', { venue_registry, order_ids })
    return data
  }
}

// §POCKETBRIDGE3 — federation-tickers response (routers/exchange.py federation_tickers)
export interface FedListing {
  symbol: string; display_name?: string; organization_id?: string
  last?: string | null; change_24h_pct?: number | null; market_cap?: string | null
  volume_24h_notional?: string | null; trades_24h?: number
  ipo_remaining?: number; ipo_price?: string | null; status?: string
  currency?: string; spark?: number[]
}
export interface FedVenue {
  venue: string; currency?: string
  listings: FedListing[]
  trades?: { symbol: string; price: string; qty: number; at: string }[]
}
export interface FederationTickers { venues: FedVenue[]; fetched_at?: string }

// §2026-06-22 P2.2 — maker-rebate + designated MM
export interface MakerRebateInfo {
  symbol: string; maker_rebate_bps: number; rebate_requires_registration: boolean
  fee_bps: number; fee_org_split_bps: number | null; rebate_enabled_globally: boolean; note?: string
}
export interface MarketMakerEntry {
  agent_did: string; status: string; min_uptime_pct: number | null; max_spread_bps: number | null; since: string | null
}
export interface MarketMakerList {
  symbol: string; maker_rebate_bps: number; rebate_requires_registration: boolean
  market_makers: MarketMakerEntry[]; active_count: number
}

// §2026-06-22 P5 (5.4) — cap-table. pct is a decimal STRING (e.g. "12.5000…") or null.
export interface Holder { agent_did: string; qty: number; pct: string | null }
export interface HoldersResult {
  symbol: string; total_shares: number; holder_count: number; treasury_qty: number
  limit: number; offset: number; holders: Holder[]
}

// §2026-06-22 P5 (5.4) — AGORA index. index_value / market_cap / weight_pct are decimal STRINGS.
export interface IndexConstituent { symbol: string; last: string; total_shares: number; market_cap: string; weight_pct: string | null }
export interface AgoraIndex { as_of: string; index_value: string; count: number; constituents: IndexConstituent[] }

// §2026-06-22 P4 — signed solvency card (venue-wide; filter listings[] to a symbol).
export interface SolvencyListing {
  symbol: string; organization_id: string | null; currency: string; status: string
  float_integrity: { ix1: boolean | null; positions_sum: number | null; expected_shares: number | null }
  treasury_solvency: {
    treasury_did: string; treasury_balance: string | null; obligations: string
    obligation_breakdown: { unpaid_dividend_legs: string; open_buyback_escrow: string; mm_cash_floor: string }
    backed: boolean | null
  }
  dividend_coverage: { has_unpaid: boolean | null; covered?: boolean; total_amount?: string; pending_legs_sum?: string; status?: string; [k: string]: any }
  notes: string[]
}
export interface SolvencyCard {
  solvency_card_version: string; registry_spiffe_id: string; currency: string; count: number
  digest: string; as_of: string | null; freshness: string; updated_at: string
  venue: { ix3: boolean | null; ix4: boolean | null; ix5: boolean | null; delta: string | null; ok: boolean | null }
  listings: SolvencyListing[]
  signature?: { alg: string; kid: string; value: string } | null
}

export interface EquityOrg {
  symbol: string; currency: string; last: string | null; status: string; agent_dids: string[]
}
export interface EquityChip {
  organization_id: string; symbol: string; currency: string; last: string | null; status: string
}

export const exchangeService = new ExchangeService()
