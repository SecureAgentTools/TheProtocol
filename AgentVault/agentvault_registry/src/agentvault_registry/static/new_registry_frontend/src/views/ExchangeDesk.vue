<template>
  <div class="exchange-desk">
    <!-- ── HERO ─────────────────────────────────────────────────────── -->
    <header class="ag-hero">
      <div class="ag-hero-l">
        <div class="ag-eyebrow">
          <Icon name="mdi:chart-candlestick" /> AGORA · ORGANIZATION MARKET
          <span class="ag-feed" :class="{ on: wsLive }"><i></i>{{ wsLive ? 'LIVE FEED' : 'POLLING' }}</span>
        </div>
        <h1>AGORA Desk</h1>
        <p class="ag-sub">Org points, agent-traded. Every money leg escrow-settled on TEG rails, supply Δ=0 by construction.</p>
      </div>
      <div class="ag-hero-r" v-if="agents.length">
        <div class="ag-shield" v-if="participantVerified">
          <Icon name="mdi:shield-check" /> VERIFIED PARTICIPANT
        </div>
        <button class="ag-list-btn" v-if="myOrgs.length" @click="openListModal" data-tour="agora-list-org">
          <Icon name="mdi:rocket-launch" /> LIST YOUR ORG
        </button>
        <!-- 2026-06-30: in-view agent SELECTOR removed (Commander) — the single
             source of truth is the top header AgentSwitcher; two pickers for the
             same identity was confusing. This is now a READ-ONLY indicator of who
             the header has you acting as on the desk. -->
        <div class="ag-acting" v-if="authStore.activeAgent">
          <span class="ag-acting-label">ACTING AGENT</span>
          <div class="ag-acting-chip">
            <UserAvatar
              :user="authStore.activeAgent"
              :display-name="authStore.activeAgent.name || authStore.activeAgent.did?.slice(0, 8)"
              :granted-at="authStore.activeAgent.flare_granted_at || null"
              size="xs"
              class="ag-acting-avatar"
            />
            <span class="ag-acting-name">{{ authStore.activeAgent.name || shortDid(authStore.activeAgent.did) }}</span>
          </div>
        </div>
        <div class="ag-acting ag-acting--empty" v-else>
          <span class="ag-acting-label">ACTING AGENT</span>
          <div class="ag-acting-chip ag-acting-chip--empty">
            <Icon name="mdi:arrow-up-thin" />
            <span class="ag-acting-hint">Pick an agent in the header to trade</span>
          </div>
        </div>
      </div>
    </header>

    <!-- ── MARQUEE (live trades) ────────────────────────────────────── -->
    <!-- The ticker tape is decoration over the trades panel's own tape: a moving line read aloud is noise, so assistive
         tech skips it (nothing in it takes focus); it stands still for a reduced-motion setting. -->
    <div class="ag-marquee" v-if="marquee.length" aria-hidden="true" @mouseenter="marqueePaused = true" @mouseleave="marqueePaused = false">
      <div class="ag-marquee-track" :class="{ paused: marqueePaused }">
        <span v-for="(m, i) in marquee" :key="i" class="ag-marquee-item" :class="m.dir">
          <b>${{ m.symbol }}</b>
          <span class="ag-mq-px">{{ m.dir === 'down' ? '▼' : m.dir === 'up' ? '▲' : '·' }} {{ fmtPxS(m.price) }}</span>
          <span class="ag-mq-qty">× {{ m.qty }}</span>
          <span class="dim">{{ m.currency }}</span>
        </span>
      </div>
    </div>

    <!-- ── GLOBAL STATS STRIP ───────────────────────────────────────── -->
    <!-- §FESUITE (the loading sweep): the strip waits for the listings' own read; a 0 says "none". -->
    <section class="stat-grid">
      <div class="stat-tile">
        <span class="stat-label">LISTINGS</span>
        <span class="stat-num tick" :key="'li' + listings.length">{{ listingsRead === 'read' ? listings.length : '—' }}</span>
        <span class="stat-sub">{{ listingsRead === 'read' ? tradingCount : '—' }} trading now</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">24H VOLUME</span>
        <span class="stat-num tick" :key="'vo' + totalVolume24h">{{ listingsRead === 'read' ? totalVolume24h : '—' }} <i class="stat-ccy">{{ venueCcy }}</i></span>
        <span class="stat-sub">notional across the market</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">24H TRADES</span>
        <span class="stat-num tick" :key="'tr' + totalTrades24h">{{ listingsRead === 'read' ? totalTrades24h : '—' }}</span>
        <span class="stat-sub">price-time matched fills</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">Σ LISTED VALUE</span>
        <span class="stat-num tick" :key="'mc' + totalMcap">{{ listingsRead === 'read' ? totalMcap : '—' }} <i class="stat-ccy">{{ venueCcy }}</i></span>
        <span class="stat-sub">last price × total points</span>
      </div>
    </section>

    <div class="ag-grid">
      <!-- ── LISTINGS RAIL ──────────────────────────────────────────── -->
      <aside class="ag-rail">
        <div class="ag-card">
          <div class="ag-card-head"><Icon name="mdi:chart-line" /> MARKETS</div>
          <!-- §FESUITE (the loading sweep): "no listings yet" only after the listings' own read; before it the rail
               said the venue was empty on every visit. A venue that could not be read says that instead. -->
          <div v-if="!listings.length && listingsRead !== 'read'" class="ag-empty" role="status">
            <span>{{ listingsRead === 'unread' ? 'The listings could not be read just now.' : 'Loading…' }}</span>
          </div>
          <div v-else-if="!listings.length" class="ag-empty">
            <Icon name="mdi:telescope" />
            <span>No listings yet — first org tickers incoming.</span>
          </div>
          <button
            v-for="l in railRows" :key="l.id"
            class="ag-row" :class="{ active: sel?.id === l.id, halted: l.status === 'halted', delisted: l.status === 'delisted' }"
            @click="selectListing(l.symbol)"
          >
            <span class="ag-row-accent"></span>
            <span class="ag-row-body">
              <span class="ag-row-top">
                <i class="ag-dot" :class="'dot-' + l.status"></i>
                <span class="ag-row-sym">${{ l.symbol }}</span>
                <span class="ag-row-px tick" :key="l.symbol + (l.stats?.last ?? '')">{{ fmtPxS(l.stats?.last) }}</span>
              </span>
              <span class="ag-row-bot">
                <span class="ag-row-name">{{ l.display_name }}</span>
                <span class="ag-row-spark" :class="chgClass(l.stats?.change_24h_pct)">
                  <Sparkline v-if="(sparks[l.symbol]?.length ?? 0) >= 2" :points="sparks[l.symbol]" :width="56" :height="14" />
                </span>
                <span class="ag-row-chg" :class="chgClass(l.stats?.change_24h_pct)">{{ chgFmt(l.stats?.change_24h_pct) }}</span>
              </span>
              <span class="ag-row-vol"><i :style="{ width: relVol(l) + '%' }"></i></span>
            </span>
          </button>
          <button v-if="railDelisted" type="button" class="ag-rail-more" data-testid="ag-rail-delisted"
                  :aria-pressed="railShowDelisted ? 'true' : 'false'" @click="railShowDelisted = !railShowDelisted">
            {{ railShowDelisted ? 'Hide' : 'Show' }} {{ railDelisted }} delisted
          </button>
        </div>

        <div class="ag-card">
          <div class="ag-card-head"><Icon name="mdi:trophy" /> TOP TRADERS · 24H</div>
          <div v-for="(t, i) in topTraders" :key="t.agent_did" class="ag-trader" :class="'rank-' + (i + 1)">
            <span class="ag-trader-bar" :style="{ width: traderBarW(t) }"></span>
            <span class="ag-trader-rank">{{ i + 1 }}</span>
            <span class="ag-trader-did" :title="t.agent_did">{{ shortDid(t.agent_did) }}</span>
            <span class="ag-trader-vol">{{ fmtNum(parseFloat(t.volume)) }}</span>
          </div>
          <div v-if="!topTraders.length" class="ag-empty">
            <Icon name="mdi:timer-sand" />
            <span>quiet tape — no trades in 24h</span>
          </div>
        </div>
      </aside>

      <!-- ── MAIN STAGE ─────────────────────────────────────────────── -->
      <main class="ag-stage" v-if="sel">
        <div class="ag-card ag-chart-card" :class="{ 'is-halted': sel.status === 'halted' }">
          <div v-if="wa.firedBanner.value.length" class="ag-fired" data-testid="ag-fired" role="alert">
            <Icon name="mdi:bell-ring" />
            <span v-for="f in wa.firedBanner.value" :key="f.id">${{ f.symbol }} {{ f.fired_direction === 'up' ? '▲' : '▼' }} past ±{{ f.pct }}% (last {{ fmtPxS(f.fired_price) }})</span>
            <button class="ag-x" @click="wa.dismissFired()" aria-label="Dismiss"><Icon name="mdi:close" /></button>
          </div>
          <div class="ag-stage-head">
            <div class="ag-stage-id">
              <span class="ag-stage-sym">${{ sel.symbol }}</span>
              <span class="ag-stage-name">{{ sel.display_name }}</span>
              <span class="ag-badge" :class="'st-' + sel.status">{{ sel.status.toUpperCase() }}</span>
              <span v-if="selRegAuth" class="ag-badge ag-reg" data-tour="agora-reg-chip" data-testid="agora-reg-chip"
                    :title="'Regulatory authorization on file: ' + selRegAuth.authority + ' (' + selRegAuth.jurisdiction + '), reference ' + selRegAuth.reference_id + (selRegAuth.valid_until ? ', valid until ' + new Date(selRegAuth.valid_until).toLocaleDateString(appLocale()) : ', open-ended') + '. Published on the signed registry card.'">
                REGULATED · {{ selRegAuth.reference_id }}</span>
              <!-- §POCKETBRIDGE4 WS-P — the SAME synced watchlist Pocket writes -->
              <button class="ag-star" :class="{ on: wa.isStarred(sel.symbol, null) }" :data-testid="'ag-star-' + sel.symbol"
                @click="wa.toggleStar(sel.symbol, null)" :aria-label="(wa.isStarred(sel.symbol, null) ? 'Unstar' : 'Star') + ' ' + sel.symbol">
                <Icon :name="wa.isStarred(sel.symbol, null) ? 'mdi:star' : 'mdi:star-outline'" />
              </button>
            </div>
            <div class="ag-stage-tools">
              <!-- §POCKETBRIDGE4 WS-P — price alert on the selected listing (server-watched; push opt-in) -->
              <div class="ag-alert" data-testid="ag-alert">
                <button class="ag-div-btn" @click="alertOpen = !alertOpen" :title="'Price alert for ' + sel.symbol">
                  <Icon name="mdi:bell-ring" /> ALERT<b v-if="selAlerts.length"> ·{{ selAlerts.length }}</b>
                </button>
                <div v-if="alertOpen" class="ag-alert-pop">
                  <div class="ag-alert-row">
                    <span>±</span>
                    <input v-model.number="alertPct" type="number" min="0.5" step="0.5" aria-label="Alert percent" />
                    <span>% from {{ fmtPxS(sel.stats?.last) }}</span>
                    <button class="ag-div-btn" data-testid="ag-alert-set" :disabled="!Number(sel.stats?.last)" @click="setAlert">SET</button>
                  </div>
                  <div v-for="a in selAlerts" :key="a.id" class="ag-alert-row armed" :class="{ fired: !!a.fired_at }">
                    <span>±{{ a.pct }}% @{{ fmtPxS(a.baseline) }}<b v-if="a.fired_at">&nbsp;{{ a.fired_direction === 'up' ? '▲' : '▼' }} fired</b></span>
                    <button class="ag-x" @click="wa.removeAlertRule(a)" aria-label="Remove alert"><Icon name="mdi:close" /></button>
                  </div>
                  <p class="ag-alert-note">{{ wa.alertNote.value || 'in-app now · the registry watches this market when the app is closed (push is opt-in, off by default)' }}</p>
                </div>
              </div>
              <button class="ag-div-btn" v-if="ownsSelected" @click="divModal.show = true" title="Declare a distribution on your listing">
                <Icon name="mdi:hand-coin-outline" /> DISTRIBUTION
              </button>
              <div class="ag-chg-big" :class="chgClass(sel.stats?.change_24h_pct)">
                <span class="ag-chg-big-num">{{ chgFmt(sel.stats?.change_24h_pct) }}</span>
                <span class="ag-chg-big-lbl">24H</span>
              </div>
              <div class="ag-tf">
                <button v-for="tf in TFS" :key="tf" :class="{ on: tf === selTf }" @click="setTf(tf)">{{ tf }}</button>
              </div>
            </div>
          </div>

          <div v-if="sel.status === 'halted'" class="ag-haltbar">
            <Icon name="mdi:alert" /> Trading halted by market admin, orders are rejected until resume.
          </div>

          <div class="ag-stats-row" v-if="sel.stats">
            <span>LAST <b class="tick" :class="lastDir" :key="'L' + (sel.stats.last ?? '')">{{ fmtPxS(sel.stats.last) }}</b></span>
            <span>BID <b class="up">{{ fmtPxS(sel.stats.best_bid) }}</b></span>
            <span>ASK <b class="down">{{ fmtPxS(sel.stats.best_ask) }}</b></span>
            <span>24H RANGE <b>{{ fmtPxS(sel.stats.low_24h) }} – {{ fmtPxS(sel.stats.high_24h) }}</b></span>
            <span>VOL <b>{{ fmtNum(parseFloat(sel.stats.volume_24h_qty || '0')) }}</b></span>
            <span>MCAP <b>{{ fmtBig(sel.stats.market_cap) }}</b></span>
          </div>

          <div class="ag-ohlc" v-if="ohlcShow">
            <span class="ag-ohlc-t">{{ ohlcShow.label }}</span>
            <span>O <b>{{ ohlcShow.o }}</b></span>
            <span>H <b class="up">{{ ohlcShow.h }}</b></span>
            <span>L <b class="down">{{ ohlcShow.l }}</b></span>
            <span>C <b :class="ohlcShow.rising ? 'up' : 'down'">{{ ohlcShow.c }}</b></span>
            <span>VOL <b>{{ ohlcShow.v }}</b></span>
          </div>

          <CandleChart v-if="marketShown === 'ok'" :candles="candles" :height="380" @hover="chartHover = $event" />
          <ReadFailedNotice v-else-if="marketShown === 'failed'" text="This listing's market could not be read just now." :retry="refreshMarket" />
          <div v-else class="ag-empty" role="status"><span>Loading…</span></div>
        </div>

        <div class="ag-duo">
          <!-- order book: center-spread ladder -->
          <div class="ag-card">
            <div class="ag-card-head"><Icon name="mdi:scale-balance" /> ORDER BOOK <span class="ag-head-sub">click a level to prefill</span></div>
            <div class="ag-book-cols"><span>PRICE</span><span>SIZE</span><span>TOTAL</span></div>
            <div class="ag-book" data-tour="agora-orderbook">
              <div class="ag-book-side">
                <div v-for="lvl in bookCum.asks" :key="'a' + lvl.price"
                     class="ag-lvl ask" :class="{ flash: flashKeys.has('a' + lvl.price) }"
                     @click="prefill('buy', lvl.price)">
                  <span class="ag-lvl-bar" :style="{ width: cumW(lvl.cum) }"></span>
                  <span class="ag-lvl-px">{{ fmtPxS(lvl.price) }}</span>
                  <span class="ag-lvl-q">{{ lvl.qty }}</span>
                  <span class="ag-lvl-cum">{{ lvl.cum }}</span>
                </div>
                <div v-if="!bookCum.asks.length && marketShown === 'ok'" class="ag-side-empty">no asks resting</div>
              </div>
              <div class="ag-spread-row">
                <span class="ag-spread-mid tick" :class="lastDir" :key="'mid' + (sel.stats?.last ?? '')">
                  {{ lastDir === 'down' ? '▼' : lastDir === 'up' ? '▲' : '' }} {{ fmtPxS(sel.stats?.last) }}
                </span>
                <span class="ag-spread-meta" v-if="spreadInfo">SPREAD {{ spreadInfo.abs }} · {{ spreadInfo.pct }}%</span>
                <span class="ag-spread-meta" v-else-if="marketShown === 'ok'">ONE-SIDED BOOK</span>
              </div>
              <div class="ag-book-side">
                <div v-for="lvl in bookCum.bids" :key="'b' + lvl.price"
                     class="ag-lvl bid" :class="{ flash: flashKeys.has('b' + lvl.price) }"
                     @click="prefill('sell', lvl.price)">
                  <span class="ag-lvl-bar" :style="{ width: cumW(lvl.cum) }"></span>
                  <span class="ag-lvl-px">{{ fmtPxS(lvl.price) }}</span>
                  <span class="ag-lvl-q">{{ lvl.qty }}</span>
                  <span class="ag-lvl-cum">{{ lvl.cum }}</span>
                </div>
                <div v-if="!bookCum.bids.length && marketShown === 'ok'" class="ag-side-empty">no bids resting</div>
              </div>
            </div>
          </div>

          <!-- depth + tape stack -->
          <div class="ag-stack">
            <div class="ag-card">
              <div class="ag-card-head"><Icon name="mdi:chart-line" /> MARKET DEPTH</div>
              <DepthChart v-if="marketShown === 'ok'" :bids="book.bids" :asks="book.asks" :height="148" />
            </div>
            <div class="ag-card">
              <div class="ag-card-head">
                <Icon name="mdi:swap-horizontal" /> TAPE
                <span class="ag-live" :class="{ on: wsLive }">{{ wsLive ? 'LIVE' : 'POLL' }}</span>
              </div>
              <div class="ag-tape" tabindex="0" role="region" aria-label="Tape">
                <div v-for="(t, i) in tape" :key="t.seq" class="ag-tape-row" :class="{ fresh: t.seq === freshSeq }">
                  <span class="ag-tape-px" :class="tapeDir(i)">{{ tapeDir(i) === 'down' ? '▼' : tapeDir(i) === 'up' ? '▲' : '·' }} {{ fmtPxS(t.price) }}</span>
                  <span class="ag-tape-q">{{ t.qty }}</span>
                  <span class="ag-tape-t">{{ timeOnly(t.at) }}</span>
                </div>
                <div v-if="!tape.length && marketShown === 'ok'" class="ag-empty">
                  <Icon name="mdi:timer-sand" />
                  <span>awaiting the first fill</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- IPO -->
        <div class="ag-card ag-ipo-card" v-if="sel.stats && sel.stats.ipo_remaining > 0 && sel.approved">
          <div class="ag-card-head">
            <Icon name="mdi:rocket-launch" /> LAUNCH
            <span class="ag-price-chip">{{ fmtPxS(sel.ipo_price) }} {{ sel.currency }} / POINT</span>
          </div>
          <div class="ag-ipo">
            <div class="ag-ipo-bar"><div class="ag-ipo-fill" :style="{ width: ipoPct + '%' }"></div></div>
            <span class="ag-ipo-txt">{{ fmtNum(sel.ipo_sold) }} / {{ fmtNum(sel.ipo_float) }} sold · <b>{{ fmtNum(sel.stats.ipo_remaining) }}</b> remaining at fixed price</span>
            <div class="ag-ipo-form">
              <input class="ag-input" type="number" min="1" step="1" v-model.number="ipoQty" placeholder="qty" aria-label="Points to buy at the launch price" />
              <button class="ag-btn buy" :disabled="!canIpo || ipoBusy" @click="doIpoBuy">
                Buy at launch · {{ ipoCost }}
              </button>
            </div>
          </div>
        </div>

        <!-- §T76 solvency + §T77 cap-table — credibility duo -->
        <div class="ag-duo">
          <!-- SOLVENCY CARD (T76) -->
          <div class="ag-card ag-cred" v-if="solvency">
            <div class="ag-card-head">
              <Icon name="mdi:shield-check" /> SOLVENCY
              <span class="ag-sig" :class="{ on: solvencySigned }" :title="solvencySigned ? 'EdDSA-signed by the market' : 'unsigned card'">
                <Icon name="mdi:certificate" /> {{ solvencySigned ? 'SIGNED' : 'UNSIGNED' }}
              </span>
            </div>
            <div class="ag-cred-badge" :class="solvency.treasury_solvency.backed === true ? 'ok' : solvency.treasury_solvency.backed === false ? 'bad' : 'unk'">
              <Icon :name="solvency.treasury_solvency.backed === true ? 'mdi:check-circle' : solvency.treasury_solvency.backed === false ? 'mdi:alert-circle' : 'mdi:help-circle'" />
              <span>Solvency: <b>{{ solvency.treasury_solvency.backed === true ? 'Backed' : solvency.treasury_solvency.backed === false ? 'Uncovered' : 'Unknown' }}</b></span>
            </div>
            <div class="ag-cred-rows">
              <div class="ag-cred-row" :class="solvency.float_integrity.ix1 ? 'ok' : 'bad'">
                <Icon :name="solvency.float_integrity.ix1 ? 'mdi:check' : 'mdi:close'" />
                <span>Launch allocation verified</span><i>{{ solvency.float_integrity.ix1 ? 'I-X1 conserved' : 'unverified' }}</i>
              </div>
              <div class="ag-cred-row" v-if="solvency.dividend_coverage.has_unpaid" :class="solvency.dividend_coverage.covered ? 'ok' : 'bad'">
                <Icon :name="solvency.dividend_coverage.covered ? 'mdi:check' : 'mdi:alert'" />
                <span>Distribution coverage</span><i>{{ solvency.dividend_coverage.covered ? 'pot funded' : 'pending pot' }}</i>
              </div>
              <div class="ag-cred-row dim" v-else>
                <Icon name="mdi:hand-coin-outline" /><span>Distribution coverage</span><i>none outstanding</i>
              </div>
            </div>
            <div class="ag-cred-inv">
              <span class="ag-cred-inv-lbl">MARKET INVARIANTS</span>
              <span class="ag-pill" :class="invCls(solvency.float_integrity.ix1)">I-X1</span>
              <span class="ag-pill" :class="invCls(venueInv?.ix3)">I-X3</span>
              <span class="ag-pill" :class="invCls(venueInv?.ix4)">I-X4</span>
              <span class="ag-pill" :class="invCls(venueInv?.ix5)">I-X5</span>
            </div>
          </div>

          <!-- CAP-TABLE (T77) -->
          <div class="ag-card ag-captable" v-if="holders">
            <div class="ag-card-head"><Icon name="mdi:account-group" /> HOLDER REGISTER
              <span class="ag-head-sub">{{ holders.holder_count }} holder{{ holders.holder_count === 1 ? '' : 's' }}</span>
            </div>
            <div class="ag-ct-summary">
              <span><i>TOTAL POINTS</i><b>{{ fmtNum(holders.total_shares) }}</b></span>
              <span><i>HOLDERS</i><b>{{ holders.holder_count }}</b></span>
              <span><i>TREASURY</i><b>{{ fmtNum(holders.treasury_qty) }} <em class="dim">{{ treasuryPct() }}</em></b></span>
            </div>
            <div class="ag-ct-cols"><span>HOLDER</span><span>POINTS</span><span>%</span></div>
            <!-- §FESUITE: a scrolling list is reachable by keyboard (axe scrollable-region-focusable) -->
            <div class="ag-ct-rows" tabindex="0" role="region" aria-label="Holder register">
              <div v-for="h in holders.holders" :key="h.agent_did" class="ag-ct-row">
                <span class="ag-ct-did" :title="h.agent_did">{{ shortDid(h.agent_did) }}</span>
                <span class="ag-ct-qty">{{ fmtNum(h.qty) }}</span>
                <span class="ag-ct-pct">{{ pctFmt(h.pct) }}</span>
              </div>
              <div v-if="!holders.holders.length" class="ag-side-empty">no external holders, treasury holds the points</div>
            </div>
          </div>
        </div>

        <!-- §TICKERFUND (O-E) — what a holder actually prices on: the firm's
             record, the treasury (member-gated rail; boundary said honestly),
             the dividend history. Records only. -->
        <FundamentalsPanel :listing-ref="sel.symbol" :organization-id="sel.organization_id || null" :currency="sel.currency" />
      </main>

      <main class="ag-stage" v-else>
        <div class="ag-card ag-empty-stage">
          <Icon name="mdi:chart-candlestick" />
          <p>Select a market — or be the first org to list.</p>
        </div>
      </main>

      <!-- ── RIGHT RAIL: trade + me ─────────────────────────────────── -->
      <aside class="ag-rail-r" data-tour="agora-ticket">
        <div class="ag-card" v-if="sel">
          <div class="ag-card-head"><Icon name="mdi:swap-horizontal" /> TRADE ${{ sel.symbol }}</div>

          <div class="ag-bal-row" v-if="actingDid">
            <span class="ag-bal-lbl"><Icon name="mdi:wallet" /> AVAILABLE</span>
            <b class="ag-bal-num tick" :key="'bal' + (balance ?? '')">{{ balanceFmt }} <i class="dim">{{ sel.currency }}</i></b>
          </div>

          <div class="ag-seg" data-tour="agora-side" role="group" aria-label="Side">
            <button type="button" class="buy" :class="{ on: form.side === 'buy' }" :aria-pressed="form.side === 'buy'" @click="form.side = 'buy'">BUY</button>
            <button type="button" class="sell" :class="{ on: form.side === 'sell' }" :aria-pressed="form.side === 'sell'" @click="form.side = 'sell'">SELL</button>
          </div>
          <div class="ag-seg sm" data-tour="agora-type" role="group" aria-label="Order type">
            <button type="button" :class="{ on: form.type === 'limit' }" :aria-pressed="form.type === 'limit'" @click="form.type = 'limit'">LIMIT</button>
            <button type="button" :class="{ on: form.type === 'market' }" :aria-pressed="form.type === 'market'" @click="form.type = 'market'">MARKET</button>
          </div>

          <label class="ag-field" v-if="form.type === 'limit'">
            <span>PRICE ({{ sel.currency }})</span>
            <input class="ag-input" v-model="form.price" placeholder="0.00" inputmode="decimal" />
          </label>
          <label class="ag-field">
            <span>QTY (points)</span>
            <span class="ag-qty-wrap" data-tour="agora-qty">
              <input class="ag-input" type="number" min="1" v-model.number="form.qty" placeholder="0" />
              <button class="ag-max" :disabled="!canMax" @click.prevent="setMaxQty">MAX</button>
            </span>
          </label>

          <!-- §T78 — time-in-force + post-only. §FESUITE: a group, not a <label>: a label's control is its first
               labelable descendant, so clicking the caption "TIME IN FORCE" pressed GTC. -->
          <div class="ag-field" role="group" aria-labelledby="ag-tif-cap">
            <span id="ag-tif-cap">TIME IN FORCE</span>
            <span class="ag-seg sm ag-tif">
              <button type="button" :class="{ on: form.tif === 'gtc' }" :aria-pressed="form.tif === 'gtc'" @click="form.tif = 'gtc'" title="Good-til-cancelled — rests on the book until filled or cancelled">GTC</button>
              <button type="button" :class="{ on: form.tif === 'ioc' }" :aria-pressed="form.tif === 'ioc'" @click="form.tif = 'ioc'" title="Immediate-or-cancel — fills what it can now, cancels the rest">IOC</button>
              <button type="button" :class="{ on: form.tif === 'fok' }" :aria-pressed="form.tif === 'fok'" @click="form.tif = 'fok'" title="Fill-or-kill — fully fills now or rejects entirely">FOK</button>
            </span>
          </div>
          <label class="ag-postonly" v-if="form.type === 'limit'" title="Reject rather than cross the spread — guarantees a maker (resting) order">
            <input type="checkbox" v-model="form.postOnly" />
            <span>Post-only <i>(maker — reject if it would cross)</i></span>
          </label>
          <!-- §#86 — stop / stop-limit trigger -->
          <label class="ag-postonly" title="Arm a stop: the order rests until `last` crosses the trigger, then fires as a market order (or as your limit, if a limit price is set)">
            <input type="checkbox" v-model="form.stop" />
            <span>Stop trigger <i>(rest until price crosses)</i></span>
          </label>
          <label class="ag-field" v-if="form.stop">
            <span>STOP PRICE ({{ sel.currency }})</span>
            <input class="ag-input" v-model="form.stopPrice" placeholder="0.00" inputmode="decimal" />
            <small style="display:block;margin-top:4px;opacity:.6;font-size:11px;line-height:1.4">{{ form.side === 'buy' ? 'buy-stop — set ABOVE last' : 'sell-stop — set BELOW last' }} · {{ form.type === 'limit' ? 'stop-limit (fires as your limit)' : 'stop-market (fires at market)' }}</small>
          </label>

          <div class="ag-receipt" v-if="receipt">
            <div class="ag-rcpt-row"><span>{{ form.type === 'limit' ? 'LIMIT PRICE' : 'EST. PRICE' }}</span><b>{{ receipt.px }}</b></div>
            <div class="ag-rcpt-row"><span>NOTIONAL</span><b>{{ receipt.notional }} {{ receipt.ccy }}</b></div>
            <div class="ag-rcpt-row" v-if="form.side === 'sell'"><span>FEE · {{ sel.fee_bps }} BPS</span><b>−{{ receipt.fee }}</b></div>
            <div class="ag-rcpt-row dim" v-else><span>FEE · {{ sel.fee_bps }} BPS</span><b>seller-side</b></div>
            <div class="ag-rcpt-total">
              <span>{{ form.side === 'buy' ? 'ESCROW ON PLACE' : 'YOU RECEIVE ≈' }}</span>
              <b :class="form.side === 'buy' ? 'up' : 'down'">{{ receipt.total }} {{ receipt.ccy }}</b>
            </div>
            <div class="ag-rcpt-band">price band ±{{ sel.band_pct }}% around last</div>
          </div>

          <button class="ag-btn big" :class="form.side" :disabled="!canPlace || placing" @click="maybeConfirmPlace" data-tour="agora-place">
            {{ placing ? 'placing…' : (form.side === 'buy' ? 'PLACE BUY' : 'PLACE SELL') }}
          </button>
          <p class="ag-hint">{{ placeHint }}</p>
        </div>

        <div class="ag-card">
          <div class="ag-card-head"><Icon name="mdi:format-list-bulleted" /> MY OPEN ORDERS</div>
          <TransitionGroup name="ag-mo" tag="div">
            <div v-for="o in openOrders" :key="o.id" class="ag-myorder">
              <span class="ag-mo-sym">${{ o.symbol }}</span>
              <span :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side.toUpperCase() }}</span>
              <span class="ag-mo-qty">{{ o.remaining }}/{{ o.qty }}</span>
              <span class="ag-mo-px">@ {{ o.price ? fmtPxS(o.price) : 'mkt' }}</span>
              <span class="ag-chip" :class="'chip-' + o.status">{{ o.status }}</span>
              <button type="button" class="ag-x" :disabled="cancelling.has(o.id)" :title="'cancel ' + o.side + ' $' + o.symbol" :aria-label="'Cancel ' + o.side + ' order on $' + o.symbol + ' (' + o.remaining + ' of ' + o.qty + ')'" :data-testid="'ag-cancel-' + o.id" @click="doCancel(o.id)"><Icon name="mdi:close" /></button>
            </div>
          </TransitionGroup>
          <ReadFailedNotice v-if="mineFailed" dense text="Your orders could not be read just now." :retry="refreshMine" />
          <div v-else-if="mineRead && !openOrders.length" class="ag-empty">
            <Icon name="mdi:inbox" />
            <span>none — resting orders appear here</span>
          </div>
        </div>

        <div class="ag-card">
          <div class="ag-card-head"><Icon name="mdi:wallet" /> HOLDINGS</div>
          <div class="ag-pf-hero" v-if="positions.length">
            <span class="ag-pf-lbl">TOTAL VALUE</span>
            <span class="ag-pf-num tick" :key="'pf' + pfTotalFmt">{{ pfTotalFmt }} <i>{{ venueCcy }}</i></span>
          </div>
          <div class="ag-alloc" v-if="pfAlloc.length">
            <i v-for="seg in pfAlloc" :key="seg.symbol"
               :style="{ width: seg.pct + '%', opacity: seg.alpha }"
               :title="'$' + seg.symbol + ' · ' + seg.pct.toFixed(1) + '%'"></i>
          </div>
          <div v-for="p in positions" :key="p.listing_id" class="ag-pos">
            <span class="ag-pos-sym">${{ p.symbol }}</span>
            <span class="ag-pos-qty">{{ p.qty }}<span class="ag-pos-lock" v-if="p.locked_qty"><Icon name="mdi:lock" />{{ p.locked_qty }}</span></span>
            <span class="dim">avg {{ fmtPxS(p.avg_cost) }}</span>
            <span :class="pnlClass(p.unrealized_pnl)">{{ pnlFmt(p.unrealized_pnl) }}</span>
          </div>
          <ReadFailedNotice v-if="mineFailed" dense text="Your holdings could not be read just now." :retry="refreshMine" />
          <div v-else-if="mineRead && !positions.length" class="ag-empty">
            <Icon name="mdi:wallet" />
            <span>no positions yet — fill an order to start</span>
          </div>
          <div class="ag-divs" v-if="portfolio">
            <Icon name="mdi:hand-coin-outline" /> distributions received <b>{{ fmtNum(parseFloat(portfolio.dividends_received || '0')) }}</b>
          </div>
        </div>
      </aside>
    </div>

    <!-- §V0064 P2 — list-your-org modal (in-view overlay: scoped tokens survive) -->
    <div class="ag-modal" v-if="listModal.show" @click.self="listModal.show = false">
      <div class="ag-modal-card">
        <div class="ag-card-head"><Icon name="mdi:rocket-launch" /> LIST YOUR ORGANIZATION</div>
        <label class="ag-field"><span>ORGANIZATION</span>
          <select class="ag-input" v-model="listModal.org_id">
            <option v-for="o in myOrgs" :key="o.id" :value="o.id">{{ o.name }}</option>
          </select>
        </label>
        <label class="ag-field"><span>TICKER (2–6 UPPERCASE)</span>
          <input class="ag-input" v-model="listModal.symbol" placeholder="QCC" maxlength="6" style="text-transform: uppercase" />
        </label>
        <div class="ag-modal-grid">
          <label class="ag-field"><span>TOTAL POINTS</span>
            <input class="ag-input" type="number" min="1000" v-model.number="listModal.total_shares" />
          </label>
          <label class="ag-field"><span>LAUNCH ALLOCATION</span>
            <input class="ag-input" type="number" min="100" v-model.number="listModal.ipo_float" />
          </label>
          <label class="ag-field"><span>LAUNCH PRICE ({{ venueCcy }})</span>
            <input class="ag-input" v-model="listModal.ipo_price" inputmode="decimal" />
          </label>
        </div>
        <label class="ag-field"><span>LISTING-FEE AGENT (yours, pays 1,000 {{ venueCcy }})</span>
          <select class="ag-input" v-model="listModal.funding_agent_did">
            <option v-for="a in agents" :key="a.did" :value="a.did">{{ a.name || shortDid(a.did) }}</option>
          </select>
        </label>
        <p class="ag-hint">Retained points (total − launch allocation) vest to your org treasury on approval; the launch allocation sells at the fixed launch price. The market admin approves before trading opens.</p>
        <div class="ag-modal-row">
          <button class="ag-btn" @click="listModal.show = false">Cancel</button>
          <button class="ag-btn buy" :disabled="listModal.busy || !listModal.org_id || listModal.symbol.trim().length < 2 || !listModal.funding_agent_did" @click="doCreateListing">
            {{ listModal.busy ? 'submitting…' : 'Submit listing' }}
          </button>
        </div>
      </div>
    </div>

    <!-- §V0064 P2 — declare-dividend modal -->
    <div class="ag-modal" v-if="divModal.show && sel" @click.self="divModal.show = false">
      <div class="ag-modal-card">
        <div class="ag-card-head"><Icon name="mdi:hand-coin-outline" /> DECLARE DISTRIBUTION · ${{ sel.symbol }}</div>
        <label class="ag-field"><span>PER POINT ({{ sel.currency }})</span>
          <input class="ag-input" v-model="divModal.per_share" inputmode="decimal" />
        </label>
        <div class="ag-receipt">
          <div class="ag-rcpt-row"><span>TOTAL POINTS</span><b>{{ fmtNum(sel.total_shares) }}</b></div>
          <div class="ag-rcpt-total"><span>POT (FROM ORG TREASURY)</span><b>{{ divPotPreview }}</b></div>
          <div class="ag-rcpt-band">the pot escrows once, then drains per-holder via settlement — treasury must cover it</div>
        </div>
        <div class="ag-modal-row">
          <button class="ag-btn" @click="divModal.show = false">Cancel</button>
          <button class="ag-btn buy" :disabled="divModal.busy || !(parseFloat(divModal.per_share) > 0)" @click="doDeclareDividend">
            {{ divModal.busy ? 'declaring…' : 'Declare distribution' }}
          </button>
        </div>
      </div>
    </div>

    <ConfirmActionModal
      :show="confirm.show"
      :title="confirm.title"
      :message="confirm.message"
      tone="warn"
      :required-match="confirm.match"
      confirm-text="Execute order"
      :busy="placing"
      @confirm="doPlace"
      @close="confirm.show = false"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AGORA Exchange Desk (2026-06-12, AAA+ pass) — flagship trading view.
 * Patterns: ForexDesk agent-picking (authStore.switchAgent), Design_Language
 * house cards (NOT sk-card), CandleChart/DepthChart custom (no chart deps),
 * same-origin WS with poll fallback, Sparkline reuse from GCC.
 * Strategy doc: STRATEGY_2026-06-12_AGORA_LOCKED_IMPLEMENTATION.md.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { typedAmount } from '@/services/money/typedAmount'
import { useRoute } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import Sparkline from '@/components/command/Sparkline.vue'
import FundamentalsPanel from '@/components/exchange/FundamentalsPanel.vue'
import CandleChart, { type ChartHover } from '@/components/exchange/CandleChart.vue'
import DepthChart from '@/components/exchange/DepthChart.vue'
import { exchangeService, type Book, type Candle, type Listing, type MyOrder, type Portfolio, type Tape, type TopTrader, type SolvencyListing, type HoldersResult } from '@/services/api/exchangeService'
import { railOrder, railVisible } from '@/services/exchange/railOrder'
import { jurisdictionAdminService, type PublicAuthorization } from '@/services/api/jurisdictionAdmin'
import { tegApi } from '@/services/api/teg'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useFrames } from '@/composables/useFrames'
import { esSocketUrl } from '@/config/frames'
// §POCKETBRIDGE4 WS-P — shared watchlist/alert brain (synced prefs, mig 0152)
import { useWatchAlerts } from '@/composables/useWatchAlerts'

const authStore = useAuthStore()
const uiStore = useUIStore()
const route = useRoute()

const TFS = ['1m', '15m', '1h', '1d'] as const
const BIG_ORDER_NOTIONAL = 10000

// ── state ────────────────────────────────────────────────────────────
const listings = ref<Listing[]>([])
/** §FESUITE (the loading sweep): 'reading' until the first answer, 'unread' if it failed; a later failed refresh keeps the shown list. */
const listingsRead = ref<'reading' | 'read' | 'unread'>('reading')
const sel = ref<Listing | null>(null)
// §POCKETBRIDGE4 WS-P
const wa = useWatchAlerts()
const alertOpen = ref(false)
const alertPct = ref(5)
const selAlerts = computed(() => wa.alertRules.value.filter(a => sel.value && a.symbol === sel.value.symbol && !(a.venue || null)))
async function setAlert() {
  if (!sel.value || !Number(sel.value.stats?.last)) return
  await wa.addAlertRule(sel.value.symbol, alertPct.value, Number(sel.value.stats!.last))
}
const selTf = ref<string>('1h')
const candles = ref<Candle[]>([])
const book = ref<Book>({ bids: [], asks: [] })
// §FESUITE (2026-10-05): the symbol the book, the tape and the chart on screen answer. A failed market read left the
// previous listing's book, tape and chart under the newly picked symbol (nothing cleared them), or drew "no asks resting",
// "no bids resting", "book is thin", "awaiting the first fill" and "no trades yet" over a read that never answered. A
// picked listing starts empty now, its market says Loading… until read and that the read failed after a failure (a failed
// refresh of the same listing keeps what was shown), and an answer for a listing no longer picked is dropped.
const marketFor = ref<string | null>(null)
const marketFailed = ref(false)
const marketShown = computed<'loading' | 'ok' | 'failed'>(() =>
  sel.value && marketFor.value === sel.value.symbol ? 'ok' : marketFailed.value ? 'failed' : 'loading')
const tape = ref<Tape[]>([])
const myOrders = ref<MyOrder[]>([])
const portfolio = ref<Portfolio | null>(null)
// §FESUITE (the failing-reads census, 2026-10-04): with every read failed the desk said "none — resting orders appear
// here" and "no positions yet". A 4xx is the venue's answer (an agent that is not a participant yet has none); a failure
// with no answer, or a 5xx, read nothing, and with nothing read the desk says so.
const mineFailed = ref(false)
// and the venue answered at least once: only then may the desk say "none" (with no acting agent it never asks)
const mineRead = ref(false)
const topTraders = ref<TopTrader[]>([])
const sparks = ref<Record<string, number[]>>({})
const balance = ref<string | null>(null)
// REGAUTH (SPEC 2026-08-15) — public proof chip: LIVE regulatory authorizations
// from the unauthenticated proof endpoint (the same set the signed card carries).
const regAuths = ref<PublicAuthorization[]>([])

async function loadRegAuths() {
  try { regAuths.value = (await jurisdictionAdminService.publicAuthorizations()).authorizations } catch { /* proof chip is optional */ }
}

const selRegAuth = computed<PublicAuthorization | null>(() => {
  const sym = sel.value?.symbol
  if (!sym) return null
  const covers = regAuths.value.filter(a =>
    (a.action === 'exchange.listing' || a.action === 'exchange.ipo') &&
    (a.subject_ref === sym || a.subject_ref === null))
  // Prefer the per-subject record over a registry-wide one.
  return covers.find(a => a.subject_ref === sym) || covers[0] || null
})
const chartHover = ref<ChartHover | null>(null)
const lastDir = ref<'up' | 'down' | 'flat'>('flat')
const marquee = ref<{ symbol: string; price: string; qty: number; currency: string; dir: string }[]>([])
const marqueePaused = ref(false)
const freshSeq = ref<number>(-1)
const flashKeys = ref<Set<string>>(new Set())
const wsLive = ref(false)
const placing = ref(false)
const ipoQty = ref<number>(0)
/* §FESUITE — one press buys once: the launch buy had no in-flight state, so a double press bought twice; a cancel
   pressed twice answered the second with a red "Cancel failed" for an order already gone. */
const ipoBusy = ref(false)
const cancelling = reactive(new Set<string>())
// §T78 — order types: TIF (GTC default) + post-only (off default = current behaviour).
const form = reactive({ side: 'buy' as 'buy' | 'sell', type: 'limit' as 'limit' | 'market', price: '', qty: 0, tif: 'gtc' as 'gtc' | 'ioc' | 'fok', postOnly: false, stop: false, stopPrice: '' })
const confirm = reactive({ show: false, title: '', message: '', match: '' })
const seenEventIds = new Set<string>()
const lastPxBySym = new Map<string, number>()
// §T76 solvency card (this listing's signed credibility row) + §T77 cap-table.
const solvency = ref<SolvencyListing | null>(null)
const solvencySigned = ref(false)
const venueInv = ref<{ ix3: boolean | null; ix4: boolean | null; ix5: boolean | null } | null>(null)
const holders = ref<HoldersResult | null>(null)

let ws: WebSocket | null = null
let wsBackoff = 2000
let pollTimer: number | undefined
let listTimer: number | undefined
let closed = false

// ── agent picking (ForexDesk pattern) ────────────────────────────────
const agents = computed(() => authStore.availableAgents || [])
const actingDid = computed(() => authStore.activeAgent?.did || '')
// 2026-06-30: onPickAgent() removed — the acting agent is chosen exclusively via
// the top header AgentSwitcher (authStore.switchAgent). The `actingDid` computed
// above reflects that single source, and `watch(actingDid, …)` auto-refreshes the
// desk when the header switches. No in-view selector → no dual-picker confusion.

// ── derived ──────────────────────────────────────────────────────────
const openOrders = computed(() => myOrders.value.filter(o => ['open', 'partial', 'funding'].includes(o.status)))
const positions = computed(() => portfolio.value?.positions ?? [])
const participantVerified = computed(() => !!portfolio.value && !!actingDid.value)
const venueCcy = computed(() => sel.value?.currency || listings.value[0]?.currency || '')
const tradingCount = computed(() => listings.value.filter(l => l.status === 'trading').length)
// §COCKPITDESK (2026-10-15): the rail folds delisted listings under one switch (sbx-alpha: 171 of 175 were delisted test
// listings below the four it trades); the selected one stays in view whatever its status (a ?sym= link to a delisted one)
const railShowDelisted = ref(false)
const railDelisted = computed(() => listings.value.filter(l => l.status === 'delisted').length)
const railRows = computed(() => railVisible(listings.value, railShowDelisted.value, sel.value?.id))

const balanceFmt = computed(() => {
  if (balance.value == null) return '—'
  return fmtNum(parseFloat(balance.value))
})

const spreadInfo = computed(() => {
  const b = parseFloat(book.value.bids[0]?.price || '0')
  const a = parseFloat(book.value.asks[0]?.price || '0')
  if (!(b > 0) || !(a > 0)) return null
  const s = a - b
  const mid = (a + b) / 2
  return { abs: s.toPrecision(3), pct: ((s / mid) * 100).toFixed(2) }
})

const bookCum = computed(() => {
  let ca = 0
  const asks = book.value.asks.map(l => ({ price: l.price, qty: l.qty, cum: (ca += l.qty) }))
  let cb = 0
  const bids = book.value.bids.map(l => ({ price: l.price, qty: l.qty, cum: (cb += l.qty) }))
  return { asks: asks.reverse(), bids, max: Math.max(1, ca, cb) }
})
function cumW(cum: number): string { return Math.max(3, Math.round((cum / bookCum.value.max) * 100)) + '%' }

const ohlcShow = computed(() => {
  if (chartHover.value) return chartHover.value
  const c = candles.value[candles.value.length - 1]
  if (!c) return null
  return {
    label: 'LATEST', o: fmtPxS(c.o), h: fmtPxS(c.h), l: fmtPxS(c.l), c: fmtPxS(c.c),
    v: c.v, rising: parseFloat(c.c) >= parseFloat(c.o),
  }
})

const receipt = computed(() => {
  if (!sel.value || !form.qty) return null
  const px = form.type === 'limit' ? parseFloat(form.price || '0') : parseFloat(sel.value.stats?.last || '0')
  if (!(px > 0)) return null
  const notional = px * form.qty
  const fee = notional * (sel.value.fee_bps / 10000)
  return {
    px: fmtPxS(px),
    notional: fmtNum(notional),
    fee: fmtNum(fee),
    total: form.side === 'buy' ? fmtNum(notional) : fmtNum(notional - fee),
    ccy: sel.value.currency,
  }
})

const canMax = computed(() => {
  if (!sel.value || !actingDid.value) return false
  if (form.side === 'sell') return positions.value.some(p => p.listing_id === sel.value!.id)
  const px = form.type === 'limit' ? parseFloat(form.price || '0') : parseFloat(sel.value.stats?.last || '0')
  return px > 0 && parseFloat(balance.value || '0') > 0
})
function setMaxQty() {
  if (!sel.value) return
  if (form.side === 'sell') {
    const pos = positions.value.find(p => p.listing_id === sel.value!.id)
    if (pos) form.qty = Math.max(0, pos.qty - (pos.locked_qty || 0))
  } else {
    const px = form.type === 'limit' ? parseFloat(form.price || '0') : parseFloat(sel.value.stats?.last || '0')
    const bal = parseFloat(balance.value || '0')
    if (px > 0 && bal > 0) form.qty = Math.floor(bal / px)
  }
}

/* §FESUITE — parseFloat read "1abc" as 1 and "1e309" as Infinity, and a quantity of 1.5 points passed: each left
   the page to be refused by the venue. One rule for prices (typedAmount), whole points for the quantity. */
const priceText = computed(() => typedAmount(form.price))
const stopText = computed(() => typedAmount(form.stopPrice))
const qtyOk = computed(() => Number.isInteger(form.qty) && form.qty > 0)
const canPlace = computed(() => {
  if (!sel.value || sel.value.status !== 'trading' || !actingDid.value) return false
  if (!qtyOk.value) return false
  if (form.type === 'limit' && !priceText.value) return false
  if (form.stop && !stopText.value) return false
  return true
})
const placeHint = computed(() => {
  if (!actingDid.value) return 'pick an acting agent to trade'
  if (!sel.value) return ''
  if (sel.value.status === 'halted') return 'listing is halted'
  if (sel.value.status !== 'trading') return 'listing is not open for trading yet'
  if (!form.qty) return 'enter a quantity'
  if (!qtyOk.value) return 'the quantity is a whole number of points'
  if (form.type === 'limit' && !form.price) return 'enter a limit price'
  if (form.type === 'limit' && !priceText.value) return 'the limit price is not a price'
  if (form.stop && !stopText.value) return 'enter a stop trigger price'
  if (form.stop) return form.side === 'buy' ? 'buy-stop arms ABOVE last; fires (escrows + matches) when last rises to the trigger' : 'sell-stop arms BELOW last; fires when last falls to the trigger'
  if (form.side === 'buy') return 'buy escrow moves to the market on placement; residue refunds on cancel'
  return 'your points lock while the sell order rests'
})

const ipoPct = computed(() => sel.value ? Math.min(100, Math.round((sel.value.ipo_sold / Math.max(1, sel.value.ipo_float)) * 100)) : 0)
const ipoCost = computed(() => {
  if (!sel.value || !ipoQty.value) return '—'
  return `${fmtNum(parseFloat(sel.value.ipo_price) * ipoQty.value)} ${sel.value.currency}`
})
// §FESUITE: whole points only (1.5 enabled the button and the venue refused it)
const canIpo = computed(() => !!sel.value && !!actingDid.value && Number.isInteger(ipoQty.value) && ipoQty.value > 0 && ipoQty.value <= (sel.value.stats?.ipo_remaining ?? 0))

const totalVolume24h = computed(() => sum(listings.value.map(l => parseFloat(l.stats?.volume_24h_notional || '0'))))
const totalTrades24h = computed(() => listings.value.reduce((a, l) => a + (l.stats?.trades_24h || 0), 0))
const totalMcap = computed(() => sum(listings.value.map(l => parseFloat(l.stats?.market_cap || '0'))))
const maxRailVol = computed(() => Math.max(1, ...listings.value.map(l => parseFloat(l.stats?.volume_24h_notional || '0'))))
const maxTraderVol = computed(() => Math.max(1, ...topTraders.value.map(t => parseFloat(t.volume || '0'))))

const pfTotal = computed(() => positions.value.reduce((a, p) => a + p.qty * parseFloat(p.last ?? p.avg_cost ?? '0'), 0))
const pfTotalFmt = computed(() => fmtNum(pfTotal.value))
const pfAlloc = computed(() => {
  const tot = pfTotal.value
  if (!(tot > 0)) return []
  const alphas = [0.95, 0.68, 0.5, 0.36, 0.26]
  return positions.value
    .map((p, i) => ({ symbol: p.symbol, pct: (p.qty * parseFloat(p.last ?? p.avg_cost ?? '0')) / tot * 100, alpha: alphas[i % alphas.length] }))
    .filter(s => s.pct > 0.5)
})

// ── fmt helpers ──────────────────────────────────────────────────────
function sum(xs: number[]): string {
  const t = xs.reduce((a, b) => a + (isFinite(b) ? b : 0), 0)
  return t >= 1e6 ? (t / 1e6).toFixed(2) + 'M' : t.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
}
function fmtPxS(p?: string | number | null): string {
  if (p == null || p === '') return '—'
  const v = typeof p === 'string' ? parseFloat(p) : p
  if (!isFinite(v)) return '—'
  if (v >= 1000) return v.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
  if (v >= 1) return v.toFixed(2)
  return v.toPrecision(3)
}
function fmtNum(v: number): string {
  if (!isFinite(v)) return '—'
  return v.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}
function fmtBig(s?: string | null): string {
  const v = parseFloat(s || '')
  if (!isFinite(v)) return '—'
  return v >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : fmtNum(v)
}
function pnlFmt(p?: string | null): string {
  const v = parseFloat(p || '')
  if (!isFinite(v)) return '—'
  return (v > 0 ? '+' : '') + fmtNum(v)
}
function shortDid(d: string): string { return d.length > 26 ? d.slice(0, 14) + '…' + d.slice(-8) : d }
// §T77 — pct arrives as a decimal STRING (e.g. "12.5000000…"); render 2dp.
function pctFmt(p?: string | null): string { const v = parseFloat(p || ''); return isFinite(v) ? v.toFixed(2) + '%' : '—' }
function treasuryPct(): string {
  if (!holders.value || !holders.value.total_shares) return '—'
  return ((holders.value.treasury_qty / holders.value.total_shares) * 100).toFixed(2) + '%'
}
// §T76 — invariant pill class: true=ok, false=bad, null/undefined=unknown.
function invCls(ok?: boolean | null): string { return ok === true ? 'ok' : ok === false ? 'bad' : 'unk' }
function timeOnly(iso: string): string { return new Date(iso).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
function chgClass(c?: string | null) { const v = parseFloat(c || '0'); return v > 0 ? 'up' : v < 0 ? 'down' : 'dim' }
function chgFmt(c?: string | null) { if (c == null) return '—'; const v = parseFloat(c); return `${v > 0 ? '▲' : v < 0 ? '▼' : ''}${Math.abs(v).toFixed(2)}%` }
function pnlClass(p?: string | null) { const v = parseFloat(p || '0'); return v > 0 ? 'up' : v < 0 ? 'down' : 'dim' }
function relVol(l: Listing): number { return Math.round((parseFloat(l.stats?.volume_24h_notional || '0') / maxRailVol.value) * 100) }
function traderBarW(t: TopTrader): string { return Math.max(4, Math.round((parseFloat(t.volume || '0') / maxTraderVol.value) * 100)) + '%' }
function prefill(side: 'buy' | 'sell', price: string) { form.side = side; form.type = 'limit'; form.price = fmtRaw(price) }
function fmtRaw(p: string): string { const v = parseFloat(p); return isFinite(v) ? String(v) : p }
function tapeDir(i: number): string {
  const cur = parseFloat(tape.value[i]?.price || '0')
  const prev = parseFloat(tape.value[i + 1]?.price ?? tape.value[i]?.price ?? '0')
  return cur > prev ? 'up' : cur < prev ? 'down' : 'flat'
}
function marqueeDir(symbol: string, px: number): string {
  const prev = lastPxBySym.get(symbol)
  lastPxBySym.set(symbol, px)
  if (prev == null || px === prev) return 'flat'
  return px > prev ? 'up' : 'down'
}

// ── data loading ─────────────────────────────────────────────────────
async function refreshListings() {
  try {
    const { listings: answered } = await exchangeService.listings()
    // Trading first, delisted last (railOrder): the desk opens on a listing a person can act on.
    const ls = railOrder(answered)
    listings.value = ls
    listingsRead.value = 'read'
    if (sel.value) {
      const fresh = ls.find(l => l.id === sel.value!.id)
      if (fresh) sel.value = fresh
    } else if (ls.length) {
      await selectListing(ls[0].symbol)
    }
    // §POCKETBRIDGE4 WS-P — sweep alert rules against EVERY fresh local last
    wa.sweep((sym, venue) => {
      if (venue) return null // this desk IS the local venue
      const hit = ls.find(l => l.symbol === sym)
      return hit?.stats?.last != null ? Number(hit.stats.last) : null
    })
  } catch {
    // venue may be disabled on this registry — reads stay graceful
    if (listingsRead.value !== 'read') listingsRead.value = 'unread'
  }
}

async function refreshSparks() {
  await Promise.all(listings.value.slice(0, 10).map(async l => {
    try {
      const { candles: cs } = await exchangeService.candles(l.symbol, '1h', 24)
      if (cs.length >= 2) sparks.value[l.symbol] = cs.map(c => parseFloat(c.c))
    } catch { /* sparkline is optional eye-candy */ }
  }))
}

async function selectListing(symbol: string) {
  const l = listings.value.find(x => x.symbol === symbol)
  if (!l) return
  sel.value = l
  chartHover.value = null
  if (marketFor.value !== l.symbol) {
    book.value = { bids: [], asks: [] }; tape.value = []; candles.value = []; marketFailed.value = false
  }
  solvency.value = null
  venueInv.value = null
  holders.value = null
  await Promise.all([refreshMarket(), refreshMine(), refreshCredibility()])
}

// §T76 + §T77 — the signed solvency row for this listing + its cap-table. Both
// PUBLIC reads; isolated try-blocks so a dark/disabled venue just hides the panels.
async function refreshCredibility() {
  if (!sel.value) return
  const ref_ = sel.value.symbol
  try {
    const card = await exchangeService.solvencyCard()
    solvency.value = card?.listings?.find(x => x.symbol === ref_) || null
    solvencySigned.value = !!card?.signature?.value
    venueInv.value = card?.venue ? { ix3: card.venue.ix3, ix4: card.venue.ix4, ix5: card.venue.ix5 } : null
  } catch { solvency.value = null; venueInv.value = null }
  try {
    holders.value = await exchangeService.holders(ref_, 50, 0)
  } catch { holders.value = null }
}

async function refreshMarket() {
  if (!sel.value) return
  const ref_ = sel.value.symbol
  try {
    const [b, t, c] = await Promise.all([
      exchangeService.book(ref_),
      exchangeService.trades(ref_, 40),
      exchangeService.candles(ref_, selTf.value, 120),
    ])
    if (sel.value?.symbol !== ref_) return   // another listing was picked meanwhile: this answer is not its market
    diffFlash(b)
    book.value = b
    tape.value = t.trades
    candles.value = c.candles
    marketFor.value = ref_
    marketFailed.value = false
    if (!marquee.value.length && t.trades.length && sel.value) {
      const ccy = sel.value.currency
      const seed = t.trades.slice(0, 12).reverse().map(tr => ({
        symbol: ref_, price: tr.price, qty: tr.qty, currency: ccy, dir: marqueeDir(ref_, parseFloat(tr.price)),
      }))
      marquee.value = seed.reverse()
    }
  } catch {
    // a failed refresh of the listing on screen keeps what was shown; a listing never read says its read failed
    if (sel.value?.symbol === ref_ && marketFor.value !== ref_) marketFailed.value = true
  }
}

async function refreshMine() {
  if (!actingDid.value) { balance.value = null; return }
  try {
    const [o, p] = await Promise.all([exchangeService.myOrders(), exchangeService.portfolio()])
    myOrders.value = o.orders
    portfolio.value = p
    mineFailed.value = false
    mineRead.value = true
  } catch (e: any) {
    // agent may lack participant status yet (a 4xx: an answer)
    const st = e?.response?.status
    mineFailed.value = (!st || st >= 500) && !myOrders.value.length && !portfolio.value
    if (st && st < 500) mineRead.value = true
  }
  try { balance.value = (await tegApi.getBalance()).balance } catch { balance.value = null }
}

async function refreshTop() {
  try { topTraders.value = (await exchangeService.topTraders()).traders } catch { /* optional */ }
}

function diffFlash(nb: Book) {
  const old = new Map<string, number>()
  book.value.bids.forEach(l => old.set('b' + l.price, l.qty))
  book.value.asks.forEach(l => old.set('a' + l.price, l.qty))
  const keys = new Set<string>()
  nb.bids.forEach(l => { if (old.get('b' + l.price) !== l.qty) keys.add('b' + l.price) })
  nb.asks.forEach(l => { if (old.get('a' + l.price) !== l.qty) keys.add('a' + l.price) })
  flashKeys.value = keys
  if (keys.size) setTimeout(() => { flashKeys.value = new Set() }, 700)
}

async function setTf(tf: string) {
  selTf.value = tf
  chartHover.value = null
  if (sel.value) {
    const ref_ = sel.value.symbol
    try {
      const { candles: cs } = await exchangeService.candles(ref_, tf, 120)
      if (sel.value?.symbol === ref_ && selTf.value === tf) candles.value = cs   // never another listing's or timeframe's
    } catch { /* keep */ }
  }
}

// ── actions ──────────────────────────────────────────────────────────
function maybeConfirmPlace() {
  if (!sel.value) return
  const px = form.type === 'limit' ? parseFloat(form.price || '0') : parseFloat(sel.value.stats?.last || '0')
  const notional = px * form.qty
  if (notional > BIG_ORDER_NOTIONAL) {
    confirm.title = `Large ${form.side.toUpperCase()} order`
    confirm.message = `Notional ≈ <b>${notional.toLocaleString(appLocale())} ${sel.value.currency}</b> on $${sel.value.symbol}. Type the ticker to confirm.`
    confirm.match = sel.value.symbol
    confirm.show = true
  } else {
    void doPlace()
  }
}

async function doPlace() {
  if (!sel.value || placing.value) return
  confirm.show = false
  placing.value = true
  try {
    const res = await exchangeService.placeOrder({
      listing: sel.value.symbol,
      side: form.side,
      order_type: form.type,
      qty: form.qty,
      price: form.type === 'limit' ? (priceText.value || undefined) : undefined,
      client_order_id: `desk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      // §T78 — only send non-default modifiers (keep the wire minimal; GTC + post_only:false = legacy).
      tif: form.tif !== 'gtc' ? form.tif : undefined,
      post_only: form.postOnly ? true : undefined,
      // §#86 stop / stop-limit: arms an order that rests until `last` crosses the trigger.
      stop_price: form.stop && stopText.value ? stopText.value : undefined,
    })
    const fills = res.fills?.length ? ` · ${res.fills.length} fill(s)` : ''
    uiStore.showSuccess(`Order ${res.status}${fills}`)
    form.qty = 0
    await Promise.all([refreshMarket(), refreshMine(), refreshListings()])
  } catch (e: any) {
    uiStore.showError('Order rejected', e?.response?.data?.detail || e?.message)
  } finally {
    placing.value = false
  }
}

async function doCancel(orderId: string) {
  if (cancelling.has(orderId)) return
  cancelling.add(orderId)
  try {
    const side = myOrders.value.find((o) => o.id === orderId)?.side
    await exchangeService.cancelOrder(orderId)
    // a sell held points, not money: say what comes back
    uiStore.showSuccess(side === 'sell' ? 'Order cancelled — your points unlock' : 'Order cancelled — escrow residue refunds via settlement')
    await Promise.all([refreshMarket(), refreshMine()])
  } catch (e: any) {
    uiStore.showError('Cancel failed', e?.response?.data?.detail || e?.message)
  } finally {
    cancelling.delete(orderId)
  }
}

async function doIpoBuy() {
  if (!sel.value || !canIpo.value || ipoBusy.value) return
  ipoBusy.value = true
  try {
    const r = await exchangeService.ipoBuy(sel.value.symbol, ipoQty.value)
    uiStore.showSuccess(`Launch purchase ${r.status}: ${r.qty} points`)
    ipoQty.value = 0
    await Promise.all([refreshListings(), refreshMine()])
  } catch (e: any) {
    uiStore.showError('Launch purchase failed', e?.response?.data?.detail || e?.message)
  } finally {
    ipoBusy.value = false
  }
}

// ── live updates: the home frame's ledger + poll fallback ─────────────────────
// §FEDEVENTS-4 (2026-08-03): the venue's live feed is THIS registry's HOME frame's event stream, resolved from
// deployment identity, never guessed. §FEFRAME W2 (2026-10-01): the identity is the frame manifest, and the stream
// is that frame's own ledger socket (wss://<frame public host>/ws/events; an operator's venue: its parent's), not a
// same-origin letter lane: on the apex `/ws/events` was the retired Frame A store, under EU's own venue.
const { localFrame, ensureLoaded: ensureFramesLoaded } = useFrames()
function wsUrlForFrame(): string {
  return localFrame.value ? esSocketUrl(localFrame.value.key, [localFrame.value]) : esSocketUrl('')
}

function connectWs() {
  if (closed) return
  try { ws?.close() } catch { /* noop */ }
  try {
    ws = new WebSocket(wsUrlForFrame())
  } catch { scheduleReconnect(); return }
  ws.onopen = () => {
    wsBackoff = 2000
    wsLive.value = true
    ws?.send(JSON.stringify({ action: 'subscribe', channel: 'events:ExchangeTradeExecuted' }))
    ws?.send(JSON.stringify({ action: 'subscribe', channel: 'events:ExchangeOrderPlaced' }))
  }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      const e = msg.event || msg
      if (!e?.event_type) return
      if (e.id && seenEventIds.has(e.id)) return
      if (e.id) { seenEventIds.add(e.id); if (seenEventIds.size > 500) seenEventIds.clear() }
      handleVenueEvent(e.event_type, e.data || {})
    } catch { /* non-JSON ping */ }
  }
  ws.onclose = () => { wsLive.value = false; scheduleReconnect() }
  ws.onerror = () => { try { ws?.close() } catch { /* noop */ } }
}

function scheduleReconnect() {
  if (closed) return
  setTimeout(connectWs, wsBackoff)
  wsBackoff = Math.min(wsBackoff * 2, 30000)
}

function handleVenueEvent(type: string, d: Record<string, any>) {
  if (type === 'ExchangeTradeExecuted') {
    marquee.value = [{
      symbol: d.symbol, price: d.price, qty: Number(d.qty), currency: d.currency || '',
      dir: marqueeDir(d.symbol, parseFloat(d.price)),
    }, ...marquee.value].slice(0, 24)
    if (sel.value && d.symbol === sel.value.symbol) {
      freshSeq.value = Number(d.seq)
      void refreshMarket()
      void refreshListings()
      if (d.buyer_did === actingDid.value || d.seller_did === actingDid.value) void refreshMine()
    }
  } else if (type === 'ExchangeOrderPlaced' && sel.value && d.symbol === sel.value.symbol) {
    void refreshMarket()
  }
}

// ── lifecycle ────────────────────────────────────────────────────────
onMounted(async () => {
  void wa.loadWatch(); void wa.loadAlerts()
  if (!agents.value.length) { try { await authStore.fetchAvailableAgents() } catch { /* guest */ } }
  await refreshListings()
  // ?sym= deep link (Stocks Discovery "Trade on the Desk" lands on that book)
  const wanted = typeof route.query.sym === 'string' ? route.query.sym.toUpperCase() : ''
  if (wanted && wanted !== sel.value?.symbol && listings.value.some(l => l.symbol === wanted)) {
    await selectListing(wanted)
  }
  // allSettled, not all (§FEDEVENTS-4): one transient failure here (e.g. the
  // agent token still exchanging → /exchange/my 401) used to abort the rest of
  // onMounted — killing the live WS AND both refresh timers silently. The desk
  // then sat on stale data forever while looking healthy.
  await Promise.allSettled([refreshTop(), refreshSparks(), refreshMine(), loadRegAuths()])
  // Resolve deployment identity BEFORE the first WS dial so wsUrlForFrame()
  // picks the home stream (bounded fetch; the poll fallback covers any gap).
  await ensureFramesLoaded()
  // §FESUITE (the leave sweep): a desk left during those reads has already run onBeforeUnmount, and the two timers below then ran for
  // the tab's life; `closed` is its own unmount flag, which the socket already obeyed
  if (closed) return
  connectWs()
  pollTimer = window.setInterval(() => { void refreshMarket(); if (!wsLive.value) void refreshListings() }, wsLive.value ? 20000 : 10000)
  listTimer = window.setInterval(() => { void refreshListings(); void refreshTop(); void refreshSparks() }, 30000)
})

onBeforeUnmount(() => {
  closed = true
  try { ws?.close() } catch { /* noop */ }
  if (pollTimer) clearInterval(pollTimer)
  if (listTimer) clearInterval(listTimer)
})

watch(actingDid, () => { void refreshMine() })

// ── §V0064 P2 — org-owner surfaces: list your org + declare dividends ──
import { organizationService } from '@/services/api/organizationService'

const myOrgs = ref<{ id: string; name: string }[]>([])
const listModal = reactive({ show: false, busy: false, org_id: '', symbol: '', total_shares: 1000000, ipo_float: 100000, ipo_price: '1.00', funding_agent_did: '' })
const divModal = reactive({ show: false, busy: false, per_share: '0.01' })

const ownsSelected = computed(() =>
  !!sel.value && myOrgs.value.some(o => o.id === sel.value!.organization_id))
const divPotPreview = computed(() => {
  if (!sel.value) return '—'
  const v = parseFloat(divModal.per_share || '0') * sel.value.total_shares
  return isFinite(v) ? fmtNum(v) + ' ' + sel.value.currency : '—'
})

async function loadMyOrgs() {
  try {
    const os = await organizationService.listOrganizations()
    myOrgs.value = (os || []).map((o: any) => ({ id: o.id, name: o.name }))
  } catch { myOrgs.value = [] } // guests / no orgs — buttons stay hidden
}

function openListModal() {
  listModal.org_id = myOrgs.value[0]?.id || ''
  listModal.funding_agent_did = actingDid.value || agents.value[0]?.did || ''
  listModal.symbol = ''
  listModal.show = true
}

async function doCreateListing() {
  if (listModal.busy) return
  listModal.busy = true
  try {
    const r = await exchangeService.createListing({
      organization_id: listModal.org_id,
      symbol: listModal.symbol.trim().toUpperCase(),
      total_shares: listModal.total_shares,
      ipo_float: listModal.ipo_float,
      ipo_price: listModal.ipo_price,
      funding_agent_did: listModal.funding_agent_did,
    })
    uiStore.showSuccess(`$${r.symbol} submitted: listing goes live once the market admin approves`)
    listModal.show = false
    await refreshListings()
  } catch (e: any) {
    uiStore.showError('Listing failed', e?.response?.data?.detail || e?.message)
  } finally { listModal.busy = false }
}

async function doDeclareDividend() {
  if (!sel.value || divModal.busy) return
  divModal.busy = true
  try {
    const r = await exchangeService.declareDividend(sel.value.symbol, divModal.per_share)
    uiStore.showSuccess(`Distribution declared: pot ${fmtBig(r.total_amount)} ${sel.value.currency} drains to holders via settlement`)
    divModal.show = false
  } catch (e: any) {
    uiStore.showError('Distribution failed', e?.response?.data?.detail || e?.message)
  } finally { divModal.busy = false }
}

void loadMyOrgs()
watch(() => sel.value?.stats?.last, (nv, ov) => {
  const n = parseFloat(nv || '0'), o = parseFloat(ov || '0')
  if (n && o && n !== o) lastDir.value = n > o ? 'up' : 'down'
})
</script>

<style scoped>
/* AGORA Exchange Desk — Design_Language house style (§1 tokens, §2 house card,
   §3 stat tiles, §5 deliberate grid). Theme-reactive accent, fixed semantics. */
.exchange-desk {
  --cyan: var(--nc-primary);
  --cyan-rgb: var(--nc-primary-rgb);
  position: relative; z-index: 1; min-height: 100%;
  padding: 18px 22px 40px; color: rgba(255, 255, 255, 0.88);
}
.up { color: #10b981; } .down { color: #ef4444; } .flat { opacity: 0.8; } .dim { opacity: 0.55; }

/* number-change micro-tick: re-keyed spans replay this on every change
   (transform-only — filter/brightness halos the text-shadow glow) */
.tick { display: inline-block; animation: ag-tick 0.45s ease-out; }
@keyframes ag-tick { 0% { transform: scale(1.07); } 100% { transform: scale(1); } }

/* ── hero ─────────────────────────────────────────────────────────── */
.ag-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.ag-eyebrow { display: inline-flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: 0.18em; color: rgba(var(--cyan-rgb), 0.8); font-family: ui-monospace, monospace; }
.ag-feed { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 99px; border: 1px solid rgba(255, 255, 255, 0.18); font-size: 8px; letter-spacing: 0.14em; opacity: 0.65; }
.ag-feed i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.ag-feed.on { color: #10b981; border-color: rgba(16, 185, 129, 0.5); opacity: 1; }
.ag-feed.on i { animation: ag-pulse 1.8s infinite; }
.ag-hero h1 { font-size: 28px; font-weight: 800; margin: 3px 0 4px; }
.ag-sub { font-size: 12px; opacity: 0.6; max-width: 560px; }
.ag-hero-r { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.ag-shield { display: inline-flex; align-items: center; gap: 6px; font-size: 9px; letter-spacing: 0.14em; font-family: ui-monospace, monospace; color: #10b981; border: 1px solid rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.08); padding: 4px 10px; border-radius: 99px; }
.ag-shield :deep(svg) { width: 12px; height: 12px; }
.ag-acting { display: flex; flex-direction: column; gap: 4px; min-width: 240px; }
.ag-acting-label { font-size: 9px; letter-spacing: 0.16em; opacity: 0.55; font-family: ui-monospace, monospace; }
.ag-acting-chip { display: flex; align-items: center; gap: 8px; background: rgba(var(--cyan-rgb), 0.07); border: 1px solid rgba(var(--cyan-rgb), 0.3); border-radius: 10px; padding: 7px 12px; }
.ag-acting-chip :deep(.icon-wrap svg) { width: 15px; height: 15px; color: rgba(var(--cyan-rgb), 0.85); flex: none; }
.ag-acting-avatar { flex: none; }  /* real agent avatar (UserAvatar xs=22px) + its flare encirclement / corner overlay — scoped away from the 15px robot-icon rule above */
/* 2026-06-30: read-only acting-agent indicator (selector removed — header drives it). */
.ag-acting-name { flex: 1; color: #fff; font-size: 13px; font-weight: 600; min-height: 28px; display: flex; align-items: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ag-acting--empty .ag-acting-chip--empty { border-style: dashed; opacity: 0.85; }
.ag-acting-hint { flex: 1; color: rgba(var(--cyan-rgb), 0.8); font-size: 12px; font-weight: 500; white-space: nowrap; }

/* ── marquee ──────────────────────────────────────────────────────── */
.ag-marquee {
  overflow: hidden; margin-bottom: 14px;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.14); border-bottom: 1px solid rgba(var(--cyan-rgb), 0.14);
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent);
  mask-image: linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent);
}
.ag-marquee-track { display: inline-flex; gap: 38px; padding: 7px 0; white-space: nowrap; animation: ag-scroll 38s linear infinite; }
.ag-marquee-track.paused { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) { .ag-marquee-track { animation: none; } }
@keyframes ag-scroll { from { transform: translateX(20%); } to { transform: translateX(-100%); } }
.ag-marquee-item { display: inline-flex; gap: 7px; align-items: baseline; font-family: ui-monospace, monospace; font-size: 11px; color: rgba(255, 255, 255, 0.75); }
.ag-marquee-item b { color: rgba(var(--cyan-rgb), 0.95); }
.ag-marquee-item .ag-mq-px { font-variant-numeric: tabular-nums; }
.ag-marquee-item.up .ag-mq-px { color: #10b981; }
.ag-marquee-item.down .ag-mq-px { color: #ef4444; }
.ag-mq-qty { opacity: 0.65; font-size: 10px; }

/* ── stat strip (§3) ──────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat-tile {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 10px; backdrop-filter: blur(9px);
  padding: 11px 14px; display: flex; flex-direction: column; gap: 2px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
}
.stat-label { font-size: 9px; letter-spacing: 0.16em; opacity: 0.55; font-family: ui-monospace, monospace; }
.stat-num { font-size: 23px; font-weight: 800; font-variant-numeric: tabular-nums; text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.32); }
.stat-ccy { font-style: normal; font-size: 11px; font-weight: 600; opacity: 0.5; letter-spacing: 0.08em; }
.stat-sub { font-size: 10px; opacity: 0.4; font-family: ui-monospace, monospace; }

/* ── layout (§5 deliberate columns) ───────────────────────────────── */
.ag-grid { display: grid; grid-template-columns: 286px minmax(0, 1fr) 326px; gap: 13px; align-items: start; }
.ag-rail-r { position: sticky; top: 12px; }
@media (max-width: 1280px) {
  .ag-grid { grid-template-columns: 250px minmax(0, 1fr); }
  .ag-rail-r { grid-column: 1 / -1; position: static; display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; align-items: start; }
}
/* one column on a phone: minmax(0, 1fr), never 1fr, whose minimum is its widest item's content (sbx-alpha's 172 markets
   made every card 441 px on a 412 px screen, fes-20261013T163344Z-71aa) */
@media (max-width: 899.98px) { .ag-grid { grid-template-columns: minmax(0, 1fr); } .ag-rail-r { grid-template-columns: minmax(0, 1fr); } }

/* ── house card (§2) ──────────────────────────────────────────────── */
.ag-card {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 12px; backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
  padding: 12px 14px; margin-bottom: 13px; transition: border-color 0.25s;
}
.ag-card:hover { border-color: rgba(var(--cyan-rgb), 0.3); }
.ag-card-head { font-size: 10px; letter-spacing: 0.16em; color: rgba(var(--cyan-rgb), 0.85); font-family: ui-monospace, monospace; margin-bottom: 10px; display: flex; align-items: center; gap: 7px; }
.ag-card-head :deep(svg) { width: 13px; height: 13px; opacity: 0.8; }
.ag-head-sub { margin-left: auto; font-size: 8px; letter-spacing: 0.1em; opacity: 0.4; }
.ag-empty { display: flex; flex-direction: column; align-items: center; gap: 7px; text-align: center; font-size: 11px; opacity: 0.45; padding: 18px 8px; font-family: ui-monospace, monospace; }
.ag-empty :deep(svg) { width: 22px; height: 22px; opacity: 0.7; }
.ag-empty-stage { display: grid; place-items: center; gap: 8px; min-height: 380px; opacity: 0.6; }
.ag-empty-stage :deep(svg) { width: 40px; height: 40px; }

/* ── listings rail ────────────────────────────────────────────────── */
.ag-row { position: relative; display: flex; width: 100%; text-align: left; padding: 0; border: 0; background: transparent; color: inherit; border-radius: 8px; cursor: pointer; overflow: hidden; margin-bottom: 2px; }
.ag-row:hover { background: rgba(var(--cyan-rgb), 0.07); }
.ag-row.delisted { opacity: .6; }
.ag-rail-more { display: block; width: 100%; margin-top: 6px; padding: 6px 8px; background: transparent; border: 1px dashed rgba(var(--cyan-rgb), 0.25); border-radius: 8px; color: var(--nc-text-muted, #8f9399); font-size: 11px; letter-spacing: .06em; cursor: pointer; }
.ag-rail-more:hover { color: rgba(var(--cyan-rgb), 0.9); }
.ag-row.active { background: rgba(var(--cyan-rgb), 0.1); }
.ag-row.halted { opacity: 0.55; }
.ag-row-accent { width: 3px; flex: none; border-radius: 3px; background: transparent; }
.ag-row.active .ag-row-accent { background: rgba(var(--cyan-rgb), 0.9); box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.6); }
.ag-row-body { flex: 1; min-width: 0; padding: 7px 8px 8px 7px; display: flex; flex-direction: column; gap: 3px; }
.ag-row-top { display: flex; align-items: center; gap: 7px; }
.ag-dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
.dot-trading { background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.7); }
.dot-ipo { background: rgba(var(--cyan-rgb), 0.9); box-shadow: 0 0 6px rgba(var(--cyan-rgb), 0.6); }
.dot-halted { background: #f59e0b; animation: ag-pulse 1.6s infinite; }
.dot-delisted { background: #ef4444; }
.ag-row-sym { font-weight: 800; color: rgba(var(--cyan-rgb), 0.95); font-family: ui-monospace, monospace; font-size: 13px; }
.ag-row-px { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 13px; font-weight: 700; }
.ag-row-bot { display: flex; align-items: center; gap: 8px; }
.ag-row-name { font-size: 10px; opacity: 0.55; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.ag-row-spark { flex: none; display: inline-flex; }
.ag-row-chg { flex: none; font-size: 10px; font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.ag-row-vol { height: 2px; border-radius: 2px; background: rgba(var(--cyan-rgb), 0.08); overflow: hidden; }
.ag-row-vol i { display: block; height: 100%; background: rgba(var(--cyan-rgb), 0.45); border-radius: 2px; }

/* top traders */
.ag-trader { position: relative; display: grid; grid-template-columns: 22px 1fr auto; gap: 8px; align-items: center; font-size: 11px; padding: 5px 8px; font-family: ui-monospace, monospace; border-radius: 6px; overflow: hidden; margin-bottom: 1px; }
.ag-trader-bar { position: absolute; left: 0; top: 0; bottom: 0; background: rgba(var(--cyan-rgb), 0.07); border-radius: 6px; }
.ag-trader-rank { position: relative; width: 17px; height: 17px; display: grid; place-items: center; border-radius: 50%; font-size: 9px; font-weight: 800; border: 1px solid rgba(255, 255, 255, 0.2); color: rgba(255, 255, 255, 0.6); }
.ag-trader.rank-1 .ag-trader-rank { color: #eab308; border-color: #eab308; box-shadow: 0 0 8px rgba(234, 179, 8, 0.4); }
.ag-trader.rank-2 .ag-trader-rank { color: #94a3b8; border-color: #94a3b8; }
.ag-trader.rank-3 .ag-trader-rank { color: #d97706; border-color: #d97706; }
.ag-trader-did { position: relative; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; opacity: 0.8; }
.ag-trader-vol { position: relative; font-variant-numeric: tabular-nums; }

/* ── stage / chart card ───────────────────────────────────────────── */
.ag-chart-card.is-halted { border-color: rgba(245, 158, 11, 0.5); }
.ag-chart-card.is-halted :deep(.cc-canvas) { filter: saturate(0.35) brightness(0.75); }
.ag-stage-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.ag-stage-id { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.ag-stage-sym { font-size: 22px; font-weight: 800; color: rgba(var(--cyan-rgb), 0.95); font-family: ui-monospace, monospace; text-shadow: 0 0 16px rgba(var(--cyan-rgb), 0.35); }
.ag-stage-name { opacity: 0.65; font-size: 13px; }
.ag-badge { font-size: 9px; letter-spacing: 0.14em; padding: 2px 8px; border-radius: 99px; border: 1px solid currentColor; font-family: ui-monospace, monospace; }
.ag-reg { color: #38bdf8; cursor: help; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-trading { color: #10b981; } .st-halted { color: #f59e0b; } .st-ipo { color: rgba(var(--cyan-rgb), 0.9); } .st-delisted { color: #ef4444; }
.ag-stage-tools { display: flex; align-items: center; gap: 12px; }
.ag-chg-big { display: flex; flex-direction: column; align-items: flex-end; line-height: 1.05; font-family: ui-monospace, monospace; }
.ag-chg-big-num { font-size: 19px; font-weight: 800; font-variant-numeric: tabular-nums; }
.ag-chg-big.up .ag-chg-big-num { text-shadow: 0 0 14px rgba(16, 185, 129, 0.5); }
.ag-chg-big.down .ag-chg-big-num { text-shadow: 0 0 14px rgba(239, 68, 68, 0.5); }
.ag-chg-big-lbl { font-size: 8px; letter-spacing: 0.2em; opacity: 0.5; }
.ag-tf { display: flex; gap: 4px; }
.ag-tf button { background: transparent; border: 1px solid rgba(var(--cyan-rgb), 0.25); color: rgba(255, 255, 255, 0.7); border-radius: 6px; font-size: 10px; padding: 4px 10px; cursor: pointer; font-family: ui-monospace, monospace; transition: all 0.15s; }
.ag-tf button:hover { border-color: rgba(var(--cyan-rgb), 0.5); }
.ag-tf button.on { background: rgba(var(--cyan-rgb), 0.18); color: #fff; border-color: rgba(var(--cyan-rgb), 0.6); box-shadow: 0 0 10px rgba(var(--cyan-rgb), 0.2); }
.ag-haltbar { display: flex; gap: 8px; align-items: center; color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.08); padding: 8px 12px; border-radius: 8px; font-size: 12px; margin-bottom: 10px; }
.ag-stats-row { display: flex; flex-wrap: wrap; gap: 16px; font-size: 10px; font-family: ui-monospace, monospace; opacity: 0.85; margin-bottom: 8px; }
.ag-stats-row b { font-size: 12px; margin-left: 4px; font-variant-numeric: tabular-nums; }
.ag-ohlc { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; font-size: 10px; font-family: ui-monospace, monospace; padding: 6px 10px; margin-bottom: 6px; border-radius: 7px; background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(var(--cyan-rgb), 0.12); }
.ag-ohlc b { font-variant-numeric: tabular-nums; margin-left: 3px; }
.ag-ohlc-t { color: rgba(var(--cyan-rgb), 0.85); letter-spacing: 0.1em; }

/* ── duo: book ladder + depth/tape stack ──────────────────────────── */
.ag-duo { display: grid; grid-template-columns: minmax(0, 1.06fr) minmax(0, 1fr); gap: 13px; align-items: start; }
@media (max-width: 899.98px) { .ag-duo { grid-template-columns: 1fr; } }
.ag-stack { display: flex; flex-direction: column; }

.ag-book-cols { display: grid; grid-template-columns: 1fr 64px 64px; gap: 8px; padding: 0 8px 6px; font-size: 8px; letter-spacing: 0.16em; opacity: 0.4; font-family: ui-monospace, monospace; }
.ag-book-cols span:nth-child(2), .ag-book-cols span:nth-child(3) { text-align: right; }
.ag-book-side { display: flex; flex-direction: column; gap: 1px; }
.ag-lvl { position: relative; display: grid; grid-template-columns: 1fr 64px 64px; gap: 8px; padding: 3px 8px; font-family: ui-monospace, monospace; font-size: 11px; cursor: pointer; border-radius: 4px; overflow: hidden; background: transparent; border: 0; color: inherit; text-align: left; transition: background 0.12s; }
.ag-lvl:hover { background: rgba(var(--cyan-rgb), 0.1); }
.ag-lvl-bar { position: absolute; right: 0; top: 0; bottom: 0; opacity: 0.13; transition: width 0.3s ease; }
.ag-lvl.ask .ag-lvl-bar { background: #ef4444; }
.ag-lvl.bid .ag-lvl-bar { background: #10b981; }
.ag-lvl.ask .ag-lvl-px { color: #ef4444; } .ag-lvl.bid .ag-lvl-px { color: #10b981; }
.ag-lvl-px { position: relative; font-variant-numeric: tabular-nums; font-weight: 600; }
.ag-lvl-q { position: relative; font-variant-numeric: tabular-nums; text-align: right; }
.ag-lvl-cum { position: relative; font-variant-numeric: tabular-nums; text-align: right; opacity: 0.5; }
.ag-lvl.flash { animation: ag-flash 0.7s ease-out; }
@keyframes ag-flash { 0% { background: rgba(var(--cyan-rgb), 0.35); } 100% { background: transparent; } }
.ag-side-empty { font-size: 10px; opacity: 0.35; text-align: center; padding: 10px 0; font-family: ui-monospace, monospace; }
.ag-spread-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 6px 8px; margin: 4px 0; border-top: 1px dashed rgba(var(--cyan-rgb), 0.2); border-bottom: 1px dashed rgba(var(--cyan-rgb), 0.2); background: rgba(0, 0, 0, 0.18); }
.ag-spread-mid { font-size: 17px; font-weight: 800; font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.ag-spread-meta { font-size: 9px; letter-spacing: 0.12em; opacity: 0.5; font-family: ui-monospace, monospace; }

/* ── tape ─────────────────────────────────────────────────────────── */
.ag-live { font-size: 8px; padding: 1px 6px; border-radius: 99px; border: 1px solid rgba(255, 255, 255, 0.25); opacity: 0.6; margin-left: auto; }
.ag-live.on { color: #10b981; border-color: #10b981; opacity: 1; animation: ag-pulse 2s infinite; }
@keyframes ag-pulse { 50% { opacity: 0.5; } }
.ag-tape { max-height: 286px; overflow-y: auto; }
.ag-tape-row { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; font-family: ui-monospace, monospace; font-size: 11px; padding: 3px 6px; border-radius: 4px; }
.ag-tape-row.fresh { animation: ag-flash 1.2s ease-out; }
.ag-tape-px { font-variant-numeric: tabular-nums; font-weight: 600; }
.ag-tape-px.flat { color: rgba(var(--cyan-rgb), 0.8); }
.ag-tape-q, .ag-tape-t { font-variant-numeric: tabular-nums; opacity: 0.6; }

/* ── IPO ──────────────────────────────────────────────────────────── */
.ag-price-chip { margin-left: auto; font-size: 9px; letter-spacing: 0.1em; padding: 3px 9px; border-radius: 99px; background: rgba(var(--cyan-rgb), 0.12); border: 1px solid rgba(var(--cyan-rgb), 0.35); color: #fff; font-variant-numeric: tabular-nums; }
.ag-ipo { display: flex; flex-direction: column; gap: 8px; }
.ag-ipo-bar { height: 9px; border-radius: 99px; background: rgba(var(--cyan-rgb), 0.1); overflow: hidden; border: 1px solid rgba(var(--cyan-rgb), 0.15); }
.ag-ipo-fill { position: relative; height: 100%; background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.5), rgba(var(--cyan-rgb), 1)); overflow: hidden; border-radius: 99px; }
.ag-ipo-fill::after { content: ''; position: absolute; inset: 0; background: linear-gradient(110deg, transparent 25%, rgba(255, 255, 255, 0.4) 50%, transparent 75%); animation: ag-shimmer 2.6s infinite; transform: translateX(-100%); }
@keyframes ag-shimmer { to { transform: translateX(100%); } }
.ag-ipo-txt { font-size: 11px; opacity: 0.7; font-family: ui-monospace, monospace; }
.ag-ipo-form { display: flex; gap: 8px; align-items: stretch; }
.ag-ipo-form .ag-input { max-width: 170px; }
.ag-ipo-form .ag-btn { white-space: nowrap; min-height: 44px; }

/* ── trade panel ──────────────────────────────────────────────────── */
.ag-bal-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 10px; margin-bottom: 10px; border-radius: 8px; background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(var(--cyan-rgb), 0.14); font-family: ui-monospace, monospace; }
.ag-bal-lbl { display: inline-flex; align-items: center; gap: 6px; font-size: 9px; letter-spacing: 0.14em; opacity: 0.6; }
.ag-bal-lbl :deep(svg) { width: 12px; height: 12px; }
.ag-bal-num { font-size: 14px; font-variant-numeric: tabular-nums; }
.ag-bal-num i { font-style: normal; font-size: 10px; }
.ag-seg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.ag-seg button { background: transparent; border: 1px solid rgba(var(--cyan-rgb), 0.25); border-radius: 9px; color: rgba(255, 255, 255, 0.7); padding: 11px; font-weight: 800; cursor: pointer; font-family: ui-monospace, monospace; font-size: 13px; letter-spacing: 0.08em; min-height: 44px; transition: all 0.15s; }
.ag-seg.sm button { font-size: 10px; padding: 6px; min-height: 30px; }
.ag-seg button.buy.on { background: rgba(16, 185, 129, 0.16); border-color: #10b981; color: #10b981; box-shadow: 0 0 14px rgba(16, 185, 129, 0.25); }
.ag-seg button.sell.on { background: rgba(239, 68, 68, 0.16); border-color: #ef4444; color: #ef4444; box-shadow: 0 0 14px rgba(239, 68, 68, 0.25); }
.ag-seg.sm button.on { background: rgba(var(--cyan-rgb), 0.16); border-color: rgba(var(--cyan-rgb), 0.6); color: #fff; }
.ag-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.ag-field > span:first-child { font-size: 9px; letter-spacing: 0.14em; opacity: 0.55; font-family: ui-monospace, monospace; }
/* §T78 — TIF segmented control (3-up) + post-only checkbox row */
.ag-tif { grid-template-columns: 1fr 1fr 1fr; margin-bottom: 0; }
.ag-postonly { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; cursor: pointer; font-size: 11px; opacity: 0.85; }
.ag-postonly input { width: 15px; height: 15px; accent-color: var(--nc-primary); cursor: pointer; flex: none; }
.ag-postonly i { font-style: normal; opacity: 0.5; font-size: 10px; }
.ag-input { background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(var(--cyan-rgb), 0.22); border-radius: 8px; color: #fff; padding: 10px 11px; font-size: 14px; width: 100%; font-variant-numeric: tabular-nums; }
.ag-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.7); box-shadow: 0 0 0 2px rgba(var(--cyan-rgb), 0.18); }
.ag-input[type='number'] { appearance: textfield; -moz-appearance: textfield; }
.ag-input::-webkit-outer-spin-button, .ag-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.ag-qty-wrap { position: relative; display: block; }
.ag-max { position: absolute; right: 7px; top: 50%; transform: translateY(-50%); font-size: 9px; letter-spacing: 0.1em; font-weight: 800; padding: 4px 9px; border-radius: 6px; cursor: pointer; background: rgba(var(--cyan-rgb), 0.14); border: 1px solid rgba(var(--cyan-rgb), 0.4); color: rgba(var(--cyan-rgb), 1); font-family: ui-monospace, monospace; }
.ag-max:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.28); }
.ag-max:disabled { opacity: 0.3; cursor: not-allowed; }
.ag-receipt { border: 1px dashed rgba(var(--cyan-rgb), 0.25); border-radius: 9px; padding: 9px 11px; margin-bottom: 10px; background: rgba(0, 0, 0, 0.2); font-family: ui-monospace, monospace; }
.ag-rcpt-row { display: flex; justify-content: space-between; font-size: 10px; padding: 2px 0; }
.ag-rcpt-row span { opacity: 0.55; letter-spacing: 0.08em; }
.ag-rcpt-row b { font-variant-numeric: tabular-nums; }
.ag-rcpt-total { display: flex; justify-content: space-between; align-items: baseline; margin-top: 5px; padding-top: 6px; border-top: 1px solid rgba(var(--cyan-rgb), 0.2); font-size: 11px; }
.ag-rcpt-total span { opacity: 0.7; letter-spacing: 0.08em; font-size: 9px; }
.ag-rcpt-total b { font-size: 14px; font-variant-numeric: tabular-nums; }
.ag-rcpt-band { margin-top: 6px; font-size: 8px; letter-spacing: 0.1em; opacity: 0.4; }
.ag-btn { border: 1px solid rgba(var(--cyan-rgb), 0.4); background: rgba(var(--cyan-rgb), 0.14); color: #fff; border-radius: 9px; padding: 9px 14px; font-weight: 800; cursor: pointer; letter-spacing: 0.06em; transition: all 0.15s; }
.ag-btn.big { width: 100%; padding: 13px; font-size: 14px; min-height: 48px; letter-spacing: 0.12em; }
.ag-btn.buy { background: rgba(16, 185, 129, 0.18); border-color: #10b981; }
.ag-btn.buy:hover:not(:disabled) { background: rgba(16, 185, 129, 0.32); box-shadow: 0 0 18px rgba(16, 185, 129, 0.3); }
.ag-btn.sell { background: rgba(239, 68, 68, 0.18); border-color: #ef4444; }
.ag-btn.sell:hover:not(:disabled) { background: rgba(239, 68, 68, 0.32); box-shadow: 0 0 18px rgba(239, 68, 68, 0.3); }
.ag-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.ag-hint { font-size: 10px; opacity: 0.55; margin-top: 8px; font-family: ui-monospace, monospace; }

/* ── my orders ────────────────────────────────────────────────────── */
.ag-myorder { display: grid; grid-template-columns: auto auto 1fr auto auto 24px; gap: 8px; align-items: center; font-size: 11px; font-family: ui-monospace, monospace; padding: 6px 4px; border-bottom: 1px dashed rgba(var(--cyan-rgb), 0.12); }
.ag-mo-sym { color: rgba(var(--cyan-rgb), 0.9); font-weight: 700; }
.ag-mo-qty, .ag-mo-px { font-variant-numeric: tabular-nums; }
.ag-chip { font-size: 8px; letter-spacing: 0.1em; padding: 2px 7px; border-radius: 99px; border: 1px solid currentColor; text-transform: uppercase; }
.chip-open { color: rgba(var(--cyan-rgb), 0.95); }
.chip-partial { color: #f59e0b; }
.chip-funding { color: #94a3b8; animation: ag-pulse 1.8s infinite; }
.ag-x { background: transparent; border: 0; color: rgba(239, 68, 68, 0.8); cursor: pointer; padding: 2px; min-width: 24px; min-height: 24px; border-radius: 5px; }
.ag-x:hover { background: rgba(239, 68, 68, 0.12); }
.ag-mo-leave-active { transition: all 0.35s ease; }
.ag-mo-leave-to { opacity: 0; transform: translateX(14px); }
.ag-mo-move { transition: transform 0.35s ease; }

/* ── portfolio ────────────────────────────────────────────────────── */
.ag-pf-hero { display: flex; flex-direction: column; gap: 1px; margin-bottom: 8px; }
.ag-pf-lbl { font-size: 8px; letter-spacing: 0.18em; opacity: 0.5; font-family: ui-monospace, monospace; }
.ag-pf-num { font-size: 21px; font-weight: 800; font-variant-numeric: tabular-nums; text-shadow: 0 0 12px rgba(var(--cyan-rgb), 0.3); }
.ag-pf-num i { font-style: normal; font-size: 11px; font-weight: 600; opacity: 0.5; }
.ag-alloc { display: flex; height: 8px; border-radius: 99px; overflow: hidden; gap: 2px; margin-bottom: 10px; }
.ag-alloc i { display: block; height: 100%; min-width: 3px; background: rgb(var(--cyan-rgb)); border-radius: 2px; }
.ag-pos { display: grid; grid-template-columns: auto 1fr auto auto; gap: 10px; font-size: 11px; font-family: ui-monospace, monospace; padding: 5px 4px; align-items: center; }
.ag-pos-sym { color: rgba(var(--cyan-rgb), 0.9); font-weight: 700; }
.ag-pos-qty { font-variant-numeric: tabular-nums; display: inline-flex; align-items: center; gap: 5px; }
.ag-pos-lock { display: inline-flex; align-items: center; gap: 2px; font-size: 9px; color: #f59e0b; opacity: 0.9; }
.ag-pos-lock :deep(svg) { width: 9px; height: 9px; }
.ag-divs { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(var(--cyan-rgb), 0.12); font-size: 11px; display: flex; gap: 6px; align-items: center; opacity: 0.8; font-family: ui-monospace, monospace; }
.ag-divs :deep(svg) { width: 13px; height: 13px; }

/* ── org-owner modals + buttons (§V0064 P2) ───────────────────────── */
.ag-list-btn, .ag-div-btn {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.12em; font-weight: 800;
  color: rgba(var(--cyan-rgb), 1); background: rgba(var(--cyan-rgb), 0.1);
  border: 1px solid rgba(var(--cyan-rgb), 0.4); border-radius: 99px; padding: 6px 14px;
  min-height: 30px; transition: background 0.15s;
}
.ag-list-btn:hover, .ag-div-btn:hover { background: rgba(var(--cyan-rgb), 0.22); }
.ag-list-btn :deep(svg), .ag-div-btn :deep(svg) { width: 12px; height: 12px; }
.ag-modal { position: fixed; inset: 0; z-index: 9000; display: grid; place-items: center; background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(3px); padding: 16px; }
.ag-modal-card {
  width: min(520px, 96vw); max-height: 90vh; overflow-y: auto;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%), rgba(10, 16, 24, 0.97);
  border: 1px solid rgba(var(--cyan-rgb), 0.35); border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 24px 70px -20px rgba(0, 0, 0, 0.9), 0 0 40px -18px rgba(var(--cyan-rgb), 0.5);
}
.ag-modal-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.ag-modal-row { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
@media (max-width: 639.98px) { .ag-modal-grid { grid-template-columns: 1fr; } }

/* ── §T76 solvency + §T77 cap-table ───────────────────────────────── */
.ag-sig { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-size: 8px; letter-spacing: 0.12em; opacity: 0.45; }
.ag-sig.on { color: #10b981; opacity: 1; }
.ag-sig :deep(svg) { width: 11px; height: 11px; }
.ag-cred-badge { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 9px; font-size: 13px; margin-bottom: 10px; border: 1px solid; }
.ag-cred-badge :deep(svg) { width: 18px; height: 18px; }
.ag-cred-badge b { font-weight: 800; }
.ag-cred-badge.ok { color: #10b981; background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.4); }
.ag-cred-badge.bad { color: #ef4444; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.4); }
.ag-cred-badge.unk { color: rgba(255, 255, 255, 0.6); background: rgba(255, 255, 255, 0.04); border-color: rgba(255, 255, 255, 0.15); }
.ag-cred-rows { display: flex; flex-direction: column; gap: 5px; margin-bottom: 11px; }
.ag-cred-row { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.ag-cred-row :deep(svg) { width: 14px; height: 14px; flex: none; }
.ag-cred-row span { font-weight: 600; }
.ag-cred-row i { margin-left: auto; font-style: normal; font-size: 9px; opacity: 0.55; font-family: ui-monospace, monospace; }
.ag-cred-row.ok { color: rgba(16, 185, 129, 0.95); }
.ag-cred-row.bad { color: rgba(239, 68, 68, 0.95); }
.ag-cred-row.dim { opacity: 0.55; }
.ag-cred-inv { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding-top: 9px; border-top: 1px dashed rgba(var(--cyan-rgb), 0.14); }
.ag-cred-inv-lbl { font-size: 8px; letter-spacing: 0.14em; opacity: 0.4; font-family: ui-monospace, monospace; margin-right: 2px; }
.ag-pill { font-family: ui-monospace, monospace; font-size: 9px; font-weight: 800; letter-spacing: 0.06em; padding: 3px 8px; border-radius: 99px; border: 1px solid; }
.ag-pill.ok { color: #10b981; border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.08); }
.ag-pill.bad { color: #ef4444; border-color: rgba(239, 68, 68, 0.45); background: rgba(239, 68, 68, 0.08); }
.ag-pill.unk { color: rgba(255, 255, 255, 0.45); border-color: rgba(255, 255, 255, 0.15); }
.ag-ct-summary { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 11px; }
.ag-ct-summary span { display: flex; flex-direction: column; gap: 1px; }
.ag-ct-summary i { font-style: normal; font-size: 8px; letter-spacing: 0.14em; opacity: 0.45; font-family: ui-monospace, monospace; }
.ag-ct-summary b { font-size: 13px; font-variant-numeric: tabular-nums; }
.ag-ct-summary em { font-style: normal; font-size: 10px; }
.ag-ct-cols { display: grid; grid-template-columns: 1fr 70px 60px; gap: 6px; font-size: 8px; letter-spacing: 0.12em; opacity: 0.4; font-family: ui-monospace, monospace; padding: 0 2px 5px; border-bottom: 1px dashed rgba(var(--cyan-rgb), 0.14); }
.ag-ct-cols span:not(:first-child) { text-align: right; }
.ag-ct-rows { max-height: 230px; overflow-y: auto; }
.ag-ct-row { display: grid; grid-template-columns: 1fr 70px 60px; gap: 6px; padding: 6px 2px; font-size: 11px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); align-items: center; }
.ag-ct-did { font-family: ui-monospace, monospace; opacity: 0.85; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ag-ct-qty, .ag-ct-pct { text-align: right; font-variant-numeric: tabular-nums; }
.ag-ct-pct { color: rgba(var(--cyan-rgb), 0.9); font-weight: 700; }

/* ── mobile ───────────────────────────────────────────────────────── */
@media (max-width: 639.98px) {
  .exchange-desk { padding: 12px 10px 32px; }
  .ag-hero h1 { font-size: 22px; }
  .ag-hero-r { align-items: stretch; width: 100%; }
  .ag-stats-row { gap: 10px; }
  .ag-ohlc { gap: 9px; }
  .ag-tape { max-height: 200px; }
  .ag-stage-sym { font-size: 19px; }
  .ag-book-cols, .ag-lvl { grid-template-columns: 1fr 52px 52px; }
}
/* §POCKETBRIDGE4 WS-P — star + alerts */
.ag-star { background: none; border: none; color: rgba(230,237,243,0.35); width: 34px; height: 34px; display: grid; place-items: center; cursor: pointer; }
.ag-star.on { color: #fbbf24; }
.ag-star :deep(svg) { width: 1.05rem; height: 1.05rem; }
.ag-alert { position: relative; }
.ag-alert-pop { position: absolute; right: 0; top: calc(100% + 6px); z-index: 30; min-width: 260px; background: #0b1320; border: 1px solid rgba(251,191,36,0.35); border-radius: 10px; padding: 0.5rem 0.6rem; box-shadow: 0 8px 30px rgba(0,0,0,0.5); }
.ag-alert-row { display: flex; align-items: center; gap: 0.35rem; font-size: 0.76rem; font-variant-numeric: tabular-nums; padding: 0.15rem 0; }
.ag-alert-row input { width: 64px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; color: inherit; padding: 0.25rem 0.4rem; font-size: 16px; outline: none; }
.ag-alert-row.armed { opacity: 0.85; }
.ag-alert-row.fired b { color: #34d399; }
.ag-alert-note { font-size: 0.62rem; opacity: 0.55; margin: 0.25rem 0 0; }
.ag-fired { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; background: rgba(251,191,36,0.09); border: 1px solid rgba(251,191,36,0.4); border-radius: 10px; padding: 0.4rem 0.65rem; margin-bottom: 0.5rem; font-size: 0.78rem; font-variant-numeric: tabular-nums; }
.ag-fired :deep(svg) { width: 0.95rem; height: 0.95rem; color: #fbbf24; }
.ag-x { margin-left: auto; background: rgba(255,255,255,0.07); border: none; color: inherit; width: 1.5rem; height: 1.5rem; border-radius: 50%; display: grid; place-items: center; cursor: pointer; }
.ag-x :deep(svg) { width: 0.7rem; height: 0.7rem; }
</style>
