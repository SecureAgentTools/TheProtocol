<!-- POCKET · Trade (2026-07-09, §POCKETBRIDGE3 Trade Desk 2.0 2026-08-22) — the AGORA exchange in
     your pocket. Markets (search/sort/watchlist/network board) → candles → order sheet with REAL
     fill receipts, plus the FIRM drawer grown into the org's MONEY COCKPIT: three pools (listing
     desks · org account · escrow-locked), permission-aware, all on existing rails. Δ=0 by
     construction (escrow mover). Passport buys ride the existing /exchange/passport rail (D3-5). -->
<template>
  <div class="pt-wrap" ref="ptrEl" @touchstart.passive="ptr.onTouchStart" @touchmove.passive="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
    <div class="pkx-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pkx-spin': ptr.ptrArmed.value }" />
    </div>
    <!-- ══════════ MARKETS LAYER ══════════ -->
    <template v-if="!sel">
      <div class="pt-head" data-tour="pk-trade">
        <h1 class="pt-title">{{ t('pocket.tabs.trade', 'Trade') }}</h1>
        <span class="pt-sub">{{ t('pocket.trade.sub', 'the AGORA market') }} <span class="pt-live" role="img" :class="{ stale }" :aria-label="stale ? t('pocket.trade.staleAria', 'data may be stale: last refresh failed') : t('pocket.trade.liveAria', 'live')" :title="stale ? t('pocket.trade.staleTitle', 'refresh failed: showing last data') : ''"></span></span>
        <button class="pt-firm-btn" @click="openFirm" :aria-label="t('pocket.trade.firmTreasury', 'Firm treasury')">
          <Icon name="mdi:domain" /> {{ t('pocket.trade.firm', 'Firm') }}
        </button>
      </div>

      <!-- §PB3 A4 — fired price alerts (session + server-fired seen on read) -->
      <div v-if="firedBanner.length" class="pt-alert-banner" data-testid="pt-alert-banner" role="alert">
        <Icon name="mdi:bell-ring" />
        <div class="pt-alert-banner-txt">
          <b v-for="f in firedBanner" :key="f.id">${{ f.symbol }} {{ f.fired_direction === 'up' ? '▲' : '▼' }} {{ tp('pocket.trade.firedPast', 'past ±{pct}% (last {price})', { pct: f.pct, price: px2(f.fired_price) }) }}</b>
        </div>
        <button class="pt-x" @click="dismissFired" :aria-label="t('pocket.trade.dismissAlerts', 'Dismiss alerts')"><Icon name="mdi:close" /></button>
      </div>

      <!-- §PB3 A1 — search + sort -->
      <div class="pt-controls">
        <div class="pt-search-box" data-tour="pk-trade-tools">
          <Icon name="mdi:magnify" />
          <input v-model="q" class="pt-search" data-testid="pt-search" type="search" :placeholder="t('pocket.trade.searchPlaceholder', 'Search tickers…')" :aria-label="t('pocket.trade.searchLabel', 'Search listings')" />
        </div>
        <select v-model="sortKey" class="pt-sort" data-testid="pt-sort" :aria-label="t('pocket.trade.sortLabel', 'Sort listings')">
          <option value="volume">{{ t('pocket.trade.sortVolume', '24h volume') }}</option>
          <option value="change">{{ t('pocket.trade.sortChange', '24h change') }}</option>
          <option value="last">{{ t('pocket.trade.sortLast', 'last price') }}</option>
          <option value="name">{{ t('pocket.trade.sortName', 'name') }}</option>
        </select>
      </div>

      <!-- §PB3 A2 — venue segment -->
      <div class="pt-seg pt-venueseg">
        <button :class="{ active: seg === 'local' }" @click="seg = 'local'">{{ t('pocket.trade.thisVenue', 'This market') }}</button>
        <button :class="{ active: seg === 'network' }" data-testid="pt-seg-network" @click="openNetwork">{{ t('pocket.trade.network', 'Network') }}</button>
      </div>

      <!-- §PB3 A3 — watchlist strip (synced to the account, D3-2) -->
      <div v-if="starred.length" class="pt-watch-strip" data-testid="pt-watch-strip" :aria-label="t('pocket.trade.watchlist', 'Watchlist')">
        <span class="pt-league-lab"><Icon name="mdi:star" /> {{ t('pocket.trade.watch', 'Watch') }}</span>
        <button v-for="w in starred" :key="watchKey(w)" class="pt-watch-chip" @click="openWatch(w)">
          ${{ w.symbol }}<small v-if="w.venue"> · {{ w.venue }}</small>
          <b v-if="watchLast(w) != null" :class="watchChg(w) == null ? '' : watchChg(w)! >= 0 ? 'up' : 'down'">{{ px2(watchLast(w)) }}</b>
        </button>
        <span v-if="watchSyncNote" class="pt-sync-note">{{ watchSyncNote }}</span>
      </div>

      <template v-if="seg === 'local'">
        <!-- index strip -->
        <div v-if="index" class="pt-index" :class="idxDir">
          <span class="pt-index-name"><Icon name="mdi:chart-areaspline" /> AGORA-10</span>
          <span class="pt-index-val">{{ fmt(index.index_value) }}</span>
          <span class="pt-index-chg">{{ pct(avgChg) }} <small>· {{ index.count }} {{ t('pocket.trade.names', 'names') }}</small></span>
        </div>

        <!-- league strip: top traders -->
        <div v-if="traders.length" class="pt-league" role="region" tabindex="0" :aria-label="t('pocket.trade.topTraders', 'Top traders 24h')">
          <span class="pt-league-lab"><Icon name="mdi:trophy" /> 24h</span>
          <!-- loop var is `tr`, NOT `t`: `t` is the translate function here. -->
          <span v-for="(tr, i) in traders.slice(0, 5)" :key="tr.agent_did" class="pt-league-chip">
            <b>#{{ i + 1 }}</b> ·{{ handle(tr.agent_did) }} <small>{{ compact(tr.volume) }} {{ t('pocket.trade.vol', 'vol') }}</small>
          </span>
        </div>

        <!-- markets -->
        <div v-if="loading" class="pt-list"><div v-for="n in 4" :key="n" class="pt-skel"></div></div>
        <ul v-else class="pt-list">
          <li v-for="l in displayListings" :key="l.id" class="pt-mkt" @click="openDetail(l)">
            <div class="pt-mkt-id">
              <span class="pt-sym">${{ l.symbol }}</span>
              <span class="pt-name">{{ l.display_name }}</span>
            </div>
            <svg class="pt-spark" viewBox="0 0 72 24" preserveAspectRatio="none" aria-hidden="true">
              <polyline class="pt-spark-line" :points="spark(l.symbol)" fill="none"
                :stroke="!hasChg(l) ? 'rgba(230,237,243,0.28)' : chg(l) >= 0 ? '#34d399' : '#ff8a8a'" stroke-width="1.6" stroke-linejoin="round" />
            </svg>
            <div class="pt-mkt-px">
              <span class="pt-last" :class="flash[l.symbol]">{{ l.stats?.last ? px2(l.stats.last) : '—' }}</span>
              <span class="pt-chg" :class="!hasChg(l) ? 'flat' : chg(l) >= 0 ? 'up' : 'down'">{{ pct(l.stats?.change_24h_pct) }}</span>
            </div>
            <button class="pt-star" :class="{ on: isStarred(l.symbol) }" :data-testid="'pt-star-' + l.symbol" @click.stop="toggleStar(l.symbol)" :aria-label="starAria(isStarred(l.symbol), l.symbol)">
              <Icon :name="isStarred(l.symbol) ? 'mdi:star' : 'mdi:star-outline'" />
            </button>
          </li>
          <li v-if="!displayListings.length && listings.length && q" class="pt-empty">
            <Icon name="mdi:magnify" class="pt-empty-ico" />
            <p>{{ tp('pocket.trade.noMatch', 'No listing matches “{q}”.', { q }) }}</p>
          </li>
          <li v-if="!listings.length && !loadErr" class="pt-empty">
            <Icon name="mdi:chart-line" class="pt-empty-ico" />
            <p>{{ t('pocket.trade.noListings', 'No listings on this market yet.') }}</p>
          </li>
          <li v-if="loadErr" class="pt-empty">
            <Icon name="mdi:alert-circle-outline" class="pt-empty-ico warn" />
            <p>{{ loadErr }}</p><button class="pt-ghost" @click="loadMarkets">{{ t('cta.retry', 'Retry') }}</button>
          </li>
        </ul>
        <p v-if="!loading && listings.length" class="pt-scope" data-testid="pt-scope">{{ tp('pocket.trade.scope', 'approved listings on this market, sorted by {sort}', { sort: sortLabel }) }}</p>
        <!-- §FOREIGNACT — "this venue" is the ACTING agent's venue: since the
             order rail already went to its home registry, the book now comes
             from there too, so browse and trade cannot disagree. -->
        <ActingContextNotice />
      </template>

      <!-- ══ §PB3 A2/D3-5 — NETWORK BOARD (federation tickers + passport doors) ══ -->
      <template v-else>
        <div v-if="fedLoading" class="pt-list"><div v-for="n in 3" :key="n" class="pt-skel"></div></div>
        <p v-else-if="fedErr" class="pt-err-note" data-testid="pt-fed-err">{{ t('pocket.trade.boardUnavailable', 'Network board unavailable') }}: {{ fedErr }} <button class="pt-retry" @click="loadFed(true)">{{ t('cta.retry', 'Retry') }}</button></p>
        <template v-else-if="fed">
          <div v-for="v in fed.venues" :key="v.venue" class="pt-fed-venue" data-testid="pt-fed-venue">
            <div class="pt-fed-head">
              <span class="pt-fed-name"><Icon name="mdi:earth" /> {{ v.venue }}</span>
              <span class="pt-fed-ccy">{{ v.currency || '' }}</span>
              <span v-if="v.venue === localVenue" class="pt-fed-here" data-testid="pt-fed-here">{{ t('pocket.trade.thisMarketTag', 'this market') }}</span>
            </div>
            <ul class="pt-list">
              <li v-for="fl in v.listings" :key="v.venue + fl.symbol" class="pt-mkt fed">
                <div class="pt-mkt-id">
                  <span class="pt-sym">${{ fl.symbol }}</span>
                  <span class="pt-name">{{ fl.display_name || '' }}</span>
                </div>
                <div class="pt-mkt-px">
                  <span class="pt-last">{{ fl.last ? px2(fl.last) : '—' }}</span>
                  <span class="pt-chg" :class="fl.change_24h_pct == null ? 'flat' : num(fl.change_24h_pct) >= 0 ? 'up' : 'down'">{{ pct(fl.change_24h_pct) }}</span>
                </div>
                <div class="pt-fed-acts">
                  <button class="pt-star" :class="{ on: isStarred(fl.symbol, starVenue(v)) }" @click.stop="toggleStar(fl.symbol, starVenue(v))" :aria-label="tp('pocket.trade.starOn', 'Star {sym} on {venue}', { sym: fl.symbol, venue: v.venue })">
                    <Icon :name="isStarred(fl.symbol, starVenue(v)) ? 'mdi:star' : 'mdi:star-outline'" />
                  </button>
                  <!-- §FESUITE (2026-10-10, the operator batch; his question "passport buy on own frame ... check if this is
                       intended"): the board lists this registry's own venue on purpose (its self-include), but a
                       passport buy is for a FOREIGN market (routers/exchange.py), and the desktop already gives the local
                       venue a local buy: here too, this market's listing opens its own buy sheet, never a passport -->
                  <button v-if="(fl.status || 'trading') === 'trading' && v.venue === localVenue" class="pt-passport-btn pt-local-buy" data-testid="pt-local-buy" @click="buyHere(fl)" :aria-label="tp('pocket.trade.buyHereAria', 'Buy {sym} on this market', { sym: fl.symbol })">
                    <Icon name="mdi:cart-outline" /> {{ t('pocket.trade.buy', 'Buy') }}
                  </button>
                  <button v-else-if="(fl.status || 'trading') === 'trading'" class="pt-passport-btn" data-testid="pt-passport-door" @click="openPassport(fl, v)" :aria-label="tp('pocket.trade.passportBuyAria', 'Passport buy {sym}', { sym: fl.symbol })">
                    <Icon name="mdi:swap-horizontal" /> {{ t('pocket.trade.buy', 'Buy') }}
                  </button>
                </div>
              </li>
              <li v-if="!v.listings.length" class="pt-empty"><p>{{ t('pocket.trade.noneShared', 'no listings shared') }}</p></li>
            </ul>
          </div>
          <p class="pt-scope" data-testid="pt-fed-scope">
            {{ venuesAnswering }}
            {{ t('pocket.trade.passportAsync', 'Passport buys settle asynchronously (minutes to hours).') }}
          </p>
        </template>
      </template>

      <!-- my positions (across acting agent) -->
      <p v-if="posErr" class="pt-err-note" data-testid="pt-pos-err">{{ t('pocket.trade.posUnavailable', 'Positions unavailable') }}: {{ posErr }}</p>
      <template v-if="portfolio && portfolio.positions.length">
        <label class="pt-lab">{{ t('pocket.trade.positions', 'Positions') }} · {{ shortDid(portfolio.agent_did) }}</label>
        <ul class="pt-pos-list">
          <li v-for="p in portfolio.positions" :key="p.symbol" class="pt-pos" @click="openBySymbol(p.symbol)">
            <span class="pt-sym">${{ p.symbol }}</span>
            <span class="pt-pos-qty">{{ tp('pocket.trade.shAvg', '{qty} pts · avg {avg}', { qty: p.qty, avg: px2(p.avg_cost) }) }}</span>
            <span class="pt-pos-pnl" :class="p.unrealized_pnl == null ? 'flat' : num(p.unrealized_pnl) >= 0 ? 'up' : 'down'">
              {{ p.unrealized_pnl == null ? '—' : (num(p.unrealized_pnl) >= 0 ? '+' : '') + fmt(p.unrealized_pnl) }}
            </span>
          </li>
        </ul>
        <!-- §POCKETBRIDGE2 W4.1 — dividends reach the pocket (read-only;
             DECLARING them stays a desktop org action, and the drawer says so). -->
        <p v-if="num(portfolio.dividends_received) > 0" class="pt-divs" data-testid="pt-dividends">
          <Icon name="mdi:hand-coin-outline" /> {{ t('pocket.trade.dividendsReceived', 'distributions received') }} <b>{{ fmt(portfolio.dividends_received) }}</b>
        </p>
        <!-- §POCKETBRIDGE4 WS-T — portfolio analytics; every cap stated inline -->
        <div v-if="pAna" class="pt-ana" data-testid="pt-portfolio-ana">
          <div class="pt-ana-head">
            <span class="pt-ana-eq">{{ fmt(pAna.equity) }} <small>{{ posCcy }}</small></span>
            <span class="pt-ana-day" :class="pAna.day == null ? 'flat' : pAna.day >= 0 ? 'up' : 'down'" data-testid="pt-ana-day">
              {{ pAna.day == null ? '24h —' : (pAna.day >= 0 ? '+' : '') + fmt(pAna.day) + ' · 24h' }}
            </span>
          </div>
          <svg v-if="sparkPoints" class="pt-ana-spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
            <polyline :points="sparkPoints" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" />
          </svg>
          <p class="pt-ana-note">{{ pAna.note }}</p>
        </div>
      </template>
    </template>

    <!-- ══════════ TICKER DETAIL LAYER ══════════ -->
    <template v-else>
      <div class="pt-head">
        <button class="pt-back" @click="closeDetail" :aria-label="t('pocket.trade.backToMarkets', 'Back to markets')"><Icon name="mdi:chevron-left" /></button>
        <div class="pt-head-id">
          <h1 class="pt-title">${{ sel.symbol }}</h1>
          <span class="pt-sub">{{ sel.display_name }} · {{ posCcy }}</span>
        </div>
        <button class="pt-star head" :class="{ on: isStarred(sel.symbol) }" :data-testid="'pt-star-' + sel.symbol" @click="toggleStar(sel.symbol)" :aria-label="starAria(isStarred(sel.symbol), sel.symbol)">
          <Icon :name="isStarred(sel.symbol) ? 'mdi:star' : 'mdi:star-outline'" />
        </button>
        <div class="pt-head-px">
          <span class="pt-last big" :class="flash[sel.symbol]">{{ sel.stats?.last ? px2(sel.stats.last) : '—' }}</span>
          <span class="pt-chg" :class="!hasChg(sel) ? 'flat' : chg(sel) >= 0 ? 'up' : 'down'">{{ pct(sel.stats?.change_24h_pct) }}</span>
        </div>
      </div>

      <!-- timeframe + chart -->
      <div class="pt-tfs">
        <button v-for="f in ['1m','15m','1h','1d']" :key="f" class="pt-tf" :class="{ active: tf === f }" @click="setTf(f)">{{ f }}</button>
        <span v-if="hover" class="pt-ohlc">O {{ fmt(hover.o) }} H {{ fmt(hover.h) }} L {{ fmt(hover.l) }} C {{ fmt(hover.c) }}</span>
      </div>
      <div class="pt-chart" :class="{ ready: candles.length }">
        <CandleChart :candles="candles" :height="230" @hover="hover = $event" />
      </div>

      <!-- §PB3 A4 — price alerts on this ticker -->
      <div class="pt-alert-row">
        <button class="pt-alert-btn" data-testid="pt-alert-btn" @click="alertForm = !alertForm" :aria-label="tp('pocket.trade.alertFor', 'Price alert for {sym}', { sym: sel.symbol })">
          <Icon name="mdi:bell-ring" /> {{ t('pocket.trade.alert', 'Alert') }}
        </button>
        <span v-for="a in myAlerts" :key="a.id" class="pt-alert-chip" :class="{ fired: !!a.fired_at }" data-testid="pt-alert-chip">
          ±{{ a.pct }}% <small>@{{ px2(a.baseline) }}</small><b v-if="a.fired_at">&nbsp;{{ a.fired_direction === 'up' ? '▲' : '▼' }} {{ t('pocket.trade.fired', 'fired') }}</b>
          <button class="pt-x" @click="removeAlert(a)" :aria-label="t('pocket.trade.removeAlert', 'Remove alert')"><Icon name="mdi:close" /></button>
        </span>
      </div>
      <div v-if="alertForm" class="pt-alert-form" data-testid="pt-alert-form">
        <span>{{ tp('pocket.trade.tellMeIf', 'Tell me if ${sym} moves ±', { sym: sel.symbol }) }}</span>
        <input v-model.number="alertPct" class="pt-in slim" type="number" min="0.5" step="0.5" inputmode="decimal" :aria-label="t('pocket.trade.alertPct', 'Alert percent')" />
        <span>{{ tp('pocket.trade.pctFrom', '% from {price}', { price: px2(sel.stats?.last) }) }}</span>
        <button class="pt-ghost slim" data-testid="pt-alert-create" :disabled="!num(sel.stats?.last)" @click="addAlert">{{ t('pocket.trade.set', 'Set') }}</button>
      </div>
      <p v-if="alertNote" class="pt-note" data-testid="pt-alert-note">{{ alertNote }}</p>

      <!-- book + tape -->
      <div class="pt-market-grid">
        <div class="pt-book">
          <label class="pt-lab">{{ t('pocket.trade.book', 'Book') }}</label>
          <div v-for="a in bookAsks" :key="'a' + a.price" class="pt-lvl ask">
            <span class="pt-lvl-bar" :style="{ width: lvlW(a.qty) }"></span>
            <span class="pt-lvl-px">{{ px2(a.price) }}</span><span class="pt-lvl-qty">{{ a.qty }}</span>
          </div>
          <div class="pt-spread">{{ spreadTxt }}</div>
          <div v-for="b in bookBids" :key="'b' + b.price" class="pt-lvl bid">
            <span class="pt-lvl-bar" :style="{ width: lvlW(b.qty) }"></span>
            <span class="pt-lvl-px">{{ px2(b.price) }}</span><span class="pt-lvl-qty">{{ b.qty }}</span>
          </div>
        </div>
        <div class="pt-tape">
          <label class="pt-lab">{{ t('pocket.trade.tape', 'Tape') }}</label>
          <!-- loop var is `f`, NOT `t`: `t` is the translate function here. -->
          <div v-for="(f, i) in tape.slice(0, 9)" :key="f.seq ?? i" class="pt-fill" :class="tickDir(i)">
            <span>{{ px2(f.price) }}</span><span>{{ f.qty }}</span><span class="pt-fill-t">{{ hhmm(f.at) }}</span>
          </div>
          <div v-if="!tape.length" class="pt-tape-empty">{{ t('pocket.trade.noFills', 'no fills yet') }}</div>
        </div>
      </div>

      <!-- my position on this ticker -->
      <div v-if="myPos" class="pt-mypos">
        <Icon name="mdi:wallet" />
        <span>{{ tp('pocket.trade.shAvg', '{qty} pts · avg {avg}', { qty: myPos.qty, avg: px2(myPos.avg_cost) }) }}</span>
        <span class="pt-pos-pnl" :class="num(myPos.unrealized_pnl) >= 0 ? 'up' : 'down'">
          {{ myPos.unrealized_pnl == null ? '' : (num(myPos.unrealized_pnl) >= 0 ? '+' : '') + fmt(myPos.unrealized_pnl) + ' ' + myPos.currency }}
        </span>
      </div>

      <!-- §PB3 A8 — last fill receipt stays visible after the sheet closes -->
      <p v-if="lastReceipt" class="pt-receipt" :class="lastReceipt.ok ? 'ok' : 'bad'" data-testid="pt-receipt">{{ lastReceipt.txt }}</p>
      <!-- §PB3 A7 — a cancel states what came back -->
      <p v-if="cancelNote" class="pt-receipt ok" data-testid="pt-cancel-note">{{ cancelNote }}</p>

      <!-- open orders on this ticker -->
      <p v-if="ordersErr" class="pt-err-note" data-testid="pt-orders-err">{{ t('pocket.trade.ordersUnavailable', 'Open orders unavailable') }}: {{ ordersErr }}</p>
      <div v-if="openOrders.length" class="pt-orders">
        <span v-for="o in openOrders" :key="o.id" class="pt-order-chip" :class="o.side">
          {{ sideLabel(o.side) }} {{ o.remaining ?? o.qty }} @ {{ o.price ? fmt(o.price) : t('pocket.trade.mkt', 'mkt') }}
          <small v-if="filledOf(o) > 0" class="pt-chip-fill">{{ tp('pocket.trade.filledOf', 'filled {n}/{total}', { n: filledOf(o), total: o.qty }) }}</small>
          <button class="pt-x" @click="cancel(o)" :aria-label="t('pocket.trade.cancelOrder', 'Cancel order')"><Icon name="mdi:close" /></button>
        </span>
      </div>

      <!-- §PB3 A6 — order history (client split of /orders/mine, latest 100) -->
      <button class="pt-hist-toggle" data-testid="pt-hist-toggle" @click="showHist = !showHist">
        <Icon :name="showHist ? 'mdi:chevron-up' : 'mdi:history'" /> {{ showHist ? t('pocket.trade.hideHistory', 'Hide history') : t('pocket.trade.orderHistory', 'Order history') }}
      </button>
      <div v-if="showHist" class="pt-history" data-testid="pt-history">
        <div v-for="o in histOrders" :key="o.id" class="pt-hist-row" :class="o.side">
          <span class="pt-hist-side">{{ sideLabel(o.side) }}</span>
          <span>{{ o.qty }} @ {{ o.price ? px2(o.price) : t('pocket.trade.mkt', 'mkt') }}</span>
          <span class="pt-hist-fill">{{ filledOf(o) > 0 ? tp('pocket.trade.filledOf', 'filled {n}/{total}', { n: filledOf(o), total: o.qty }) : t('pocket.trade.noFill', 'no fill') }}</span>
          <span class="pt-hist-st">{{ orderStatusLabel(o.status) }}</span>
          <span class="pt-fill-t">{{ hhmm(o.created_at) }}</span>
        </div>
        <p v-if="!histOrders.length" class="pt-tape-empty">{{ t('pocket.trade.noPastOrders', 'no past orders on this ticker (as this agent)') }}</p>
        <p class="pt-note">{{ t('pocket.trade.historyCap', 'latest 100 orders across the market: older history is on desktop') }}</p>
      </div>

      <!-- halted banner -->
      <div v-if="isHalted" class="pt-halted"><Icon name="mdi:pause-octagon" /> {{ t('pocket.trade.halted', 'Trading halted on this listing') }}</div>

      <!-- buy / sell -->
      <div class="pt-cta">
        <button class="pt-buy" :disabled="isHalted" @click="openSheet('buy')"><Icon name="mdi:arrow-up-bold" /> {{ t('pocket.trade.buy', 'Buy') }}</button>
        <button class="pt-sell" :disabled="isHalted" @click="openSheet('sell')"><Icon name="mdi:arrow-down-bold" /> {{ t('pocket.trade.sell', 'Sell') }}</button>
      </div>
    </template>

    <!-- ══════════ ORDER SHEET ══════════ -->
    <transition name="pt-sheet">
      <div v-if="sheet" class="pt-sheet-veil" @click.self="sheet = null">
        <div class="pt-sheet" role="dialog" aria-modal="true">
          <div class="pt-sheet-grab"></div>
          <h2 class="pt-sheet-title" :class="sheet">{{ sheet === 'buy' ? t('pocket.trade.buy', 'Buy') : t('pocket.trade.sell', 'Sell') }} ${{ sel?.symbol }}</h2>

          <label class="pt-lab">{{ t('pocket.trade.tradingAs', 'Trading as') }}</label>
          <select v-if="credAgents.length" v-model="actorDid" class="pt-in">
            <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shortDid(a.did) }}</option>
          </select>
          <p v-else class="pt-warn-note">{{ noAgentReason }}</p>

          <div class="pt-row">
            <div class="pt-col">
              <label class="pt-lab">{{ t('pocket.trade.type', 'Type') }}</label>
              <div class="pt-seg">
                <button :class="{ active: otype === 'limit' }" @click="otype = 'limit'">{{ t('pocket.trade.limit', 'Limit') }}</button>
                <button :class="{ active: otype === 'market' }" @click="otype = 'market'">{{ t('pocket.trade.market', 'Market') }}</button>
              </div>
            </div>
            <div class="pt-col">
              <label class="pt-lab">{{ t('pocket.trade.quantity', 'Quantity') }}</label>
              <div class="pt-step">
                <button @click="qty = Math.max(1, qty - 1)" :aria-label="t('pocket.trade.less', 'Less')">−</button>
                <input v-model.number="qty" type="number" min="1" inputmode="numeric" />
                <button @click="qty = qty + 1" :aria-label="t('pocket.trade.more', 'More')">+</button>
              </div>
            </div>
          </div>

          <template v-if="otype === 'limit'">
            <label class="pt-lab">{{ tp('pocket.trade.limitPrice', 'Limit price ({ccy})', { ccy: posCcy }) }}</label>
            <input v-model="price" class="pt-in" type="text" inputmode="decimal" :placeholder="sel?.stats?.last || '0.00'" />
          </template>

          <div class="pt-est">
            <span>{{ sheet === 'buy' ? t('pocket.trade.estCost', 'Est. cost') : t('pocket.trade.estProceeds', 'Est. proceeds') }}</span>
            <b>{{ estTxt }}</b>
          </div>
          <p v-if="sheet === 'buy' && otype === 'market'" class="pt-note">{{ t('pocket.trade.marketCapNote', 'market buys escrow last +10% as a price cap — the unused part returns with the fill') }}</p>

          <div v-if="burst" class="pt-burst" aria-hidden="true"><Icon name="mdi:check-circle" /></div>
          <button class="pt-confirm" :class="sheet" :disabled="placing || !canPlace" @click="place">
            <Icon :name="lock.enabled.value ? 'mdi:fingerprint' : (sheet === 'buy' ? 'mdi:arrow-up-bold' : 'mdi:arrow-down-bold')" />
            {{ placing ? (verifying ? t('pocket.send.confirmBio', 'Confirm biometrics…') : t('pocket.trade.placing', 'Placing…')) : confirmTxt }}
          </button>
          <p v-if="orderMsg" class="pt-result" :class="orderMsg.ok ? 'ok' : 'bad'">{{ orderMsg.txt }}</p>
        </div>
      </div>
    </transition>

    <!-- ══════════ §PB3 D3-5 · PASSPORT SHEET (cross-venue buy on the existing rail) ══════════ -->
    <transition name="pt-sheet">
      <div v-if="pp" class="pt-sheet-veil" @click.self="pp = null">
        <div class="pt-sheet" role="dialog" aria-modal="true">
          <div class="pt-sheet-grab"></div>
          <h2 class="pt-sheet-title buy"><Icon name="mdi:swap-horizontal" /> {{ t('pocket.trade.passportBuy', 'Passport buy') }} ${{ pp.listing.symbol }} <small class="pt-fed-ccy">{{ t('pocket.trade.on', 'on') }} {{ pp.venue.venue }}</small></h2>

          <label class="pt-lab">{{ t('pocket.trade.tradingAs', 'Trading as') }}</label>
          <select v-if="credAgents.length" v-model="actorDid" class="pt-in">
            <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shortDid(a.did) }}</option>
          </select>
          <p v-else class="pt-warn-note">{{ noAgentReason }}</p>

          <div class="pt-row">
            <div class="pt-col">
              <label class="pt-lab">{{ t('pocket.trade.quantity', 'Quantity') }}</label>
              <div class="pt-step">
                <button @click="ppQty = Math.max(1, ppQty - 1)" :aria-label="t('pocket.trade.less', 'Less')">−</button>
                <input v-model.number="ppQty" type="number" min="1" inputmode="numeric" />
                <button @click="ppQty = ppQty + 1" :aria-label="t('pocket.trade.more', 'More')">+</button>
              </div>
            </div>
            <div class="pt-col">
              <label class="pt-lab">{{ tp('pocket.trade.limitPrice', 'Limit price ({ccy})', { ccy: pp.venue.currency || t('pocket.trade.venueCcy', 'market ccy') }) }}</label>
              <input v-model="ppPrice" class="pt-in" type="text" inputmode="decimal" :placeholder="pp.listing.last || '0.00'" />
            </div>
          </div>
          <p class="pt-note">{{ tp('pocket.trade.ppNote1', 'funds convert over the FX rail with a {pct}% buffer; a placed order is', { pct: ppBuffer }) }} <b>{{ t('pocket.trade.ppAccepted', 'accepted, not filled') }}</b> {{ t('pocket.trade.ppNote2', '— passport fills take minutes to hours.') }}</p>

          <button class="pt-confirm buy" :disabled="ppBusy || !canPassport" @click="placePassport">
            <Icon :name="lock.enabled.value ? 'mdi:fingerprint' : 'mdi:swap-horizontal'" />
            {{ ppBusy ? t('pocket.trade.placing', 'Placing…') : tp('pocket.trade.passportBuyN', 'Passport buy {qty} ${sym}', { qty: ppQty, sym: pp.listing.symbol }) }}
          </button>
          <p v-if="ppMsg" class="pt-result" :class="ppMsg.ok ? 'ok' : 'bad'" data-testid="pt-pp-result">{{ ppMsg.txt }}</p>
        </div>
      </div>
    </transition>

    <!-- ══════════ FIRM DRAWER → §PB3 A5 · THE ORG MONEY COCKPIT ══════════ -->
    <transition name="pt-sheet">
      <div v-if="firmOpen" class="pt-sheet-veil" @click.self="firmOpen = false">
        <div class="pt-sheet" role="dialog" aria-modal="true">
          <div class="pt-sheet-grab"></div>
          <h2 class="pt-sheet-title firm"><Icon name="mdi:domain" /> {{ t('pocket.trade.firmMoney', 'Organization balances') }}</h2>

          <div v-if="orgsLoading" class="pt-skel" style="height:64px"></div>
          <p v-else-if="orgsErr" class="pt-err-note" data-testid="pt-orgs-err">{{ t('pocket.trade.orgsFailed', 'Could not load your organizations') }}: {{ orgsErr }} <button class="pt-retry" @click="openFirm">{{ t('cta.retry', 'Retry') }}</button></p>
          <p v-else-if="!orgs.length" class="pt-warn-note">{{ t('pocket.trade.noOrgs', "You're not a member of any organization on this registry.") }}</p>
          <template v-else>
            <label class="pt-lab">{{ t('pocket.trade.organization', 'Organization') }}</label>
            <select v-model="orgId" class="pt-in" @change="loadTreasury">
              <option v-for="o in orgs" :key="o.id" :value="o.id">{{ o.name }}</option>
            </select>

            <!-- ── POOL 1 · LISTING DESKS (IPO proceeds + org fee cut land HERE) ── -->
            <div class="pt-pool" data-testid="pt-pool1">
              <div class="pt-pool-head"><Icon name="mdi:store-outline" /> {{ t('pocket.trade.listingDesks', 'Listing desks') }} <small>{{ t('pocket.trade.workingCapital', 'desk balances') }}</small></div>
              <p v-if="treErr" class="pt-err-note" data-testid="pt-tre-err">{{ treErr }}</p>
              <ReadFailedNotice v-else-if="treFailed" dense :retry="loadTreasury" />
              <template v-else-if="treasury">
                <div class="pt-tre-bal">
                  <span class="pt-lab" style="margin:0">{{ t('pocket.trade.deskCashAll', 'Desk cash · all listings') }}</span>
                  <b>{{ treasury.totals?.balance == null ? '—' : fmt(treasury.totals.balance) }} <small>{{ treasury.currency || posCcy }}</small></b>
                </div>
                <div v-for="tl in treasury.listings || []" :key="tl.symbol" class="pt-desk">
                  <div class="pt-desk-head">
                    <span class="pt-sym">${{ tl.symbol }}</span>
                    <span class="pt-desk-st">{{ listingStatusLabel(tl.status) }}</span>
                    <b class="pt-desk-bal">{{ tl.balance == null ? t('pocket.trade.tegUnreachable', 'TEG unreachable') : fmt(tl.balance) }}</b>
                  </div>
                  <div class="pt-desk-rows">
                    <span>{{ t('pocket.trade.raised', 'raised') }} <b>{{ fmt(tl.raised) }}</b></span>
                    <span>{{ t('pocket.trade.feesEarned', 'fees collected') }} <b>{{ fmt(tl.fees_earned) }}</b></span>
                    <span>{{ t('pocket.trade.dividendsPaid', 'distributions paid') }} <b>{{ fmt(tl.dividends_paid) }}</b></span>
                    <span>{{ t('pocket.trade.deskHolds', 'desk holds') }} <b>{{ !(tl.symbol in deskQty) ? '…' : deskQty[tl.symbol] === null ? t('pocket.common.requestFailed', 'request failed') : tp('pocket.trade.shares', '{n} pts', { n: deskQty[tl.symbol] }) }}</b></span>
                  </div>
                </div>
                <p v-if="!(treasury.listings || []).length" class="pt-warn-note">{{ t('pocket.trade.noOrgListing', 'This org has no listing on this market.') }}</p>
                <p class="pt-note">{{ t('pocket.trade.deskCycleNote', 'Desk cash CYCLES: treasury buys, market-making and distributions spend it, and trading fees plus launch sales refill it. A low desk after activity is cycled, not broken.') }}</p>
              </template>
              <div v-else class="pt-skel" style="height:48px"></div>
            </div>

            <!-- own-listing actions (org-admin; backend enforces) -->
            <template v-if="ownSymbol">
              <label class="pt-lab">${{ ownSymbol }} · {{ t('pocket.trade.deskActions', 'desk actions') }}</label>
              <div class="pt-row">
                <div class="pt-col"><div class="pt-step">
                  <button @click="fQty = Math.max(1, fQty - 1)">−</button>
                  <input v-model.number="fQty" type="number" min="1" inputmode="numeric" />
                  <button @click="fQty = fQty + 1">+</button>
                </div></div>
                <div class="pt-col">
                  <input v-model="fPrice" class="pt-in" type="text" inputmode="decimal" :placeholder="t('pocket.trade.limitPricePlaceholder', 'limit price')" />
                </div>
              </div>
              <div class="pt-cta">
                <button class="pt-buy" :disabled="firmBusy" @click="firmAct('buyback')"><Icon name="mdi:arrow-up-bold" /> {{ t('pocket.trade.buyback', 'Treasury buy') }}</button>
                <button class="pt-sell" :disabled="firmBusy" @click="firmAct('sell')"><Icon name="mdi:arrow-down-bold" /> {{ t('pocket.trade.sell', 'Sell') }}</button>
              </div>
              <p class="pt-note">{{ t('pocket.trade.deskActionNote', "Buys/sells the firm's OWN points from the listing desk (org-admin only: the market enforces it). Declaring a distribution stays on desktop.") }}</p>
            </template>
            <p v-if="firmMsg" class="pt-result" :class="firmMsg.ok ? 'ok' : 'bad'">{{ firmMsg.txt }}</p>

            <!-- ── POOL 2 · ORG ACCOUNT (mig 0146 — deliberate funding only) ── -->
            <div class="pt-pool" data-testid="pt-pool2">
              <div class="pt-pool-head"><Icon name="mdi:wallet" /> {{ t('pocket.trade.orgAccount', 'Org account') }}</div>
              <p v-if="acctErr" class="pt-err-note">{{ acctErr }}</p>
              <template v-else-if="acct">
                <div class="pt-tre-bal">
                  <span class="pt-lab" style="margin:0">{{ acct.exists ? t('pocket.trade.accountBalance', 'Account balance') : t('pocket.trade.noOrgAccount', 'No org account yet') }}</span>
                  <b v-if="acct.exists">{{ acct.balance == null ? t('pocket.trade.tegUnreachable', 'TEG unreachable') : fmt(acct.balance) }} <small>{{ posCcy }}</small></b>
                  <small v-else>{{ t('pocket.trade.ownerCreates', 'the org owner creates it (desktop)') }}</small>
                </div>
                <template v-if="acct.exists">
                  <label class="pt-lab">{{ t('pocket.trade.fundAgentLabel', 'Fund an agent from this account') }} <small>{{ t('pocket.trade.orgAdmin', '(org admin)') }}</small></label>
                  <div class="pt-row">
                    <div class="pt-col">
                      <select v-model="fundDid" class="pt-in" :aria-label="t('pocket.trade.agentToFund', 'Agent to fund')">
                        <option value="" disabled>{{ t('pocket.trade.agentPick', 'agent…') }}</option>
                        <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shortDid(a.did) }}</option>
                      </select>
                    </div>
                    <div class="pt-col">
                      <input v-model="fundAmt" class="pt-in" type="text" inputmode="decimal" :placeholder="t('pocket.trade.amountPlaceholder', 'amount')" :aria-label="t('pocket.stake.amount', 'Amount')" />
                    </div>
                  </div>
                  <button class="pt-confirm firmfund" data-testid="pt-fund-btn" :disabled="fundBusy || !fundDid || !num(fundAmt)" @click="fundAgent">
                    <Icon :name="lock.enabled.value ? 'mdi:fingerprint' : 'mdi:wallet'" /> {{ fundBusy ? t('pocket.trade.funding', 'Funding…') : t('pocket.trade.fundAgent', 'Fund agent') }}
                  </button>
                  <p v-if="fundMsg" class="pt-result" :class="fundMsg.ok ? 'ok' : 'bad'" data-testid="pt-fund-msg">{{ fundMsg.txt }}</p>
                </template>
                <p class="pt-note">{{ t('pocket.trade.orgAccountNote', "Units arrive here when one of the organization's agents remits them under its own authorization (by API or on the desktop), or when the organization is paid as a firm; launch proceeds and trading fees go to the listing desks above, never here. The owner's sweep is the way out: it moves the whole balance to one of the owner's agents.") }}</p>
              </template>
              <div v-else class="pt-skel" style="height:40px"></div>
            </div>

            <!-- ── POOL 3 · LOCKED IN ESCROW (public solvency card) ── -->
            <div class="pt-pool" data-testid="pt-pool3">
              <div class="pt-pool-head"><Icon name="mdi:lock" /> {{ t('pocket.trade.lockedBuybacks', 'Locked in open treasury buys') }}</div>
              <template v-if="lockedRows.length">
                <div v-for="r in lockedRows" :key="r.symbol" class="pt-desk-rows one">
                  <span>${{ r.symbol }} <b>{{ fmt(r.locked) }}</b></span>
                </div>
                <div class="pt-tre-bal slim"><span class="pt-lab" style="margin:0">{{ t('pocket.trade.totalLocked', 'Total locked') }}</span><b>{{ fmt(lockedTotal) }} <small>{{ posCcy }}</small></b></div>
                <p class="pt-note">{{ t('pocket.trade.lockedNote', "cash held inside the desks' open treasury-buy orders, from this market's public solvency card; it returns to the desk when orders fill or cancel.") }}</p>
              </template>
              <p v-else-if="solvencyMiss" class="pt-warn-note">{{ t('pocket.trade.solvencyMissing', "Solvency card unavailable on this market: locked escrow can't be derived, so no number is shown.") }}</p>
              <p v-else class="pt-note">{{ t('pocket.trade.noLocked', 'no cash locked in open treasury-buy orders right now (per the public solvency card)') }}</p>
            </div>

            <p class="pt-note">{{ t('pocket.trade.permissionNote', 'Desk figures are org-MEMBER gated; funding and desk actions are org-ADMIN — the rails enforce both, this screen only renders what your permission returns.') }}</p>
          </template>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import CandleChart, { type ChartHover } from '@/components/exchange/CandleChart.vue'
import { useAuthStore } from '@/stores/auth'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { exchangeService, type Listing, type Candle, type Portfolio, type Position, type TopTrader, type FederationTickers, type FedListing, type FedVenue } from '@/services/api/exchangeService'
import { organizationService } from '@/services/api/organizationService'
import { usePocketLock } from '@/composables/usePocketLock'
import type { WatchEntry, PriceAlertRule } from '@/services/api/pocketPrefs'
import { isExpired } from '@/services/priceAlerts'
import { useWatchAlerts } from '@/composables/useWatchAlerts'
import { useI18n } from '@/composables/useI18n'
import { useAlive } from '@/composables/useAlive'
import { localVenueOf } from '@/services/exchange/localVenue'

const { t, tp } = useI18n()
const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { sel.value ? void refreshDetail(true) : void loadMarkets() })
const auth = useAuthStore()
const lock = usePocketLock()

/* ── helpers ─────────────────────────────────────────────── */
const num = (s: any) => Number(s ?? 0)
const fmt = (s: any) => { const n = num(s); return n >= 1000 ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : n.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) }
const px2 = (s: any) => { const n = num(s); return n >= 1000 ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : n.toFixed(2) }
const pct = (s: any) => s == null ? '—' : `${num(s) >= 0 ? '+' : ''}${num(s).toFixed(2)}%`
const shortDid = (d: string) => !d ? '—' : d.length > 18 ? d.slice(0, 10) + '…' + d.slice(-4) : d
// param is `ts`, NOT `t`: `t` is the translate function in this scope.
const hhmm = (ts: string) => { try { return new Date(ts).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) } catch { return '' } }

/* Machine values the venue returns, given words. An unknown value renders raw:
   naming a state we do not know would be an invention, not a translation. */
const sideLabel = (s?: string) => {
  const v = String(s || '').toLowerCase()
  return v === 'buy' ? t('pocket.trade.sideBuy', 'buy') : v === 'sell' ? t('pocket.trade.sideSell', 'sell') : v
}
const ORDER_ST: Record<string, [string, string]> = {
  open: ['pocket.trade.ordOpen', 'open'],
  partial: ['pocket.trade.ordPartial', 'partial'],
  filled: ['pocket.trade.ordFilled', 'filled'],
  cancelled: ['pocket.trade.ordCancelled', 'cancelled'],
  canceled: ['pocket.trade.ordCancelled', 'cancelled'],
  rejected: ['pocket.trade.ordRejected', 'rejected'],
  expired: ['pocket.trade.ordExpired', 'expired'],
}
const orderStatusLabel = (s?: string) => {
  const e = ORDER_ST[String(s || '').toLowerCase()]
  return e ? t(e[0], e[1]) : String(s || '')
}
const LISTING_ST: Record<string, [string, string]> = {
  trading: ['pocket.trade.lstTrading', 'trading'],
  halted: ['pocket.trade.lstHalted', 'halted'],
  ipo: ['pocket.trade.lstIpo', 'launch'],
  delisted: ['pocket.trade.lstDelisted', 'delisted'],
  pending: ['pocket.trade.lstPending', 'pending'],
}
const listingStatusLabel = (s?: string) => {
  const e = LISTING_ST[String(s || '').toLowerCase()]
  return e ? t(e[0], e[1]) : String(s || '')
}
const starAria = (on: boolean, sym: string) =>
  on ? tp('pocket.trade.unstarSym', 'Unstar {sym}', { sym }) : tp('pocket.trade.starSym', 'Star {sym}', { sym })
const buzz = (ms: number | number[]) => { try { navigator.vibrate?.(ms) } catch { /* no haptics */ } }
const chg = (l: Listing) => num(l.stats?.change_24h_pct)
const hasChg = (l: Listing) => l.stats?.change_24h_pct != null
// §POCKETBRIDGE2 hotfix (his find: every top trader rendered "-sury") — org
// treasury desks carry their ticker IN the DID (org-<symbol>-treasury): show
// the ticker; anything else shows the id HEAD (tails collide, heads differ).
const handle = (d: string) => {
  const m = /^did:[a-z0-9]+:org-(.+)-treasury$/i.exec(d || '')
  if (m) return '$' + m[1].toUpperCase()
  return (d || '').replace(/^did:[a-z0-9]+:/i, '').slice(0, 8)
}
const compact = (s: any) => { const n = num(s); return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : n.toFixed(0) }

/* ── markets ─────────────────────────────────────────────── */
const listings = ref<Listing[]>([])
const index = ref<any>(null)
const traders = ref<TopTrader[]>([])
const loading = ref(true)
const loadErr = ref('')
const stale = ref(false)
const sparks = ref<Record<string, string>>({})
const flash = ref<Record<string, string>>({})
const lastSeen: Record<string, number> = {}
const avgChg = computed(() => {
  const cs = listings.value.map(l => num(l.stats?.change_24h_pct)).filter(n => !Number.isNaN(n))
  return cs.length ? cs.reduce((a, b) => a + b, 0) / cs.length : 0
})
const idxDir = computed(() => avgChg.value >= 0 ? 'up' : 'down')

/* §PB3 A1 — search + sort (client-side; 9-50 rows is client scale) */
const q = ref('')
const sortKey = ref<'volume' | 'change' | 'last' | 'name'>('volume')
const sortLabel = computed(() => ({
  volume: t('pocket.trade.sortVolume', '24h volume'),
  change: t('pocket.trade.sortChange', '24h change'),
  last: t('pocket.trade.sortLast', 'last price'),
  name: t('pocket.trade.sortName', 'name'),
}[sortKey.value]))
const displayListings = computed(() => {
  const needle = q.value.trim().toLowerCase()
  let out = listings.value
  if (needle) out = out.filter(l => l.symbol.toLowerCase().includes(needle) || (l.display_name || '').toLowerCase().includes(needle))
  const k = sortKey.value
  return [...out].sort((a, b) =>
    k === 'volume' ? num(b.stats?.volume_24h_notional) - num(a.stats?.volume_24h_notional)
    : k === 'change' ? chg(b) - chg(a)
    : k === 'last' ? num(b.stats?.last) - num(a.stats?.last)
    : a.symbol.localeCompare(b.symbol))
})

function markFlash(sym: string, px: number) {
  const prev = lastSeen[sym]
  if (prev != null && px !== prev) {
    flash.value[sym] = px > prev ? 'flash-up' : 'flash-down'
    buzz(8)
    setTimeout(() => { if (flash.value[sym]) flash.value = { ...flash.value, [sym]: '' } }, 700)
  }
  lastSeen[sym] = px
}

async function loadMarkets() {
  loadErr.value = ''
  try {
    const [ls, idx, tt] = await Promise.all([
      exchangeService.listings(),
      exchangeService.index(10).catch(() => null),
      exchangeService.topTraders(24, 5).catch(() => ({ traders: [] })),
    ])
    listings.value = (ls.listings || [])
      .filter((l: any) => l.status === 'approved' || l.status === 'trading' || !l.status)
      .sort((a: any, b: any) => num(b.stats?.volume_24h_notional) - num(a.stats?.volume_24h_notional))
    index.value = idx
    traders.value = tt.traders || []
    for (const l of listings.value) if (l.stats?.last != null) markFlash(l.symbol, num(l.stats.last))
    stale.value = false
    void loadSparks()
    sweepAlerts()
  } catch (e: any) {
    if (!listings.value.length) loadErr.value = e?.response?.data?.detail || e?.message || t('pocket.trade.marketDataUnavailable', 'Market data unavailable')
    stale.value = true
  } finally { loading.value = false }
}

async function loadSparks() {
  for (const l of listings.value) {
    if (sparks.value[l.symbol]) continue
    try {
      const { candles } = await exchangeService.candles(l.symbol, '1h', 24)
      const cs = candles.map(c => num(c.c))
      if (!cs.length) continue
      const min = Math.min(...cs), max = Math.max(...cs), span = max - min || 1
      sparks.value[l.symbol] = cs.map((v, i) => `${(i / Math.max(cs.length - 1, 1)) * 72},${22 - ((v - min) / span) * 20}`).join(' ')
    } catch { /* sparkline optional */ }
  }
}
const spark = (sym: string) => sparks.value[sym] || '0,12 72,12'

/* ── §PB3 A2 — federation board (lazy; the fan-out costs seconds) ───────── */
const seg = ref<'local' | 'network'>('local')
const fed = ref<FederationTickers | null>(null)
const fedLoading = ref(false)
const fedErr = ref('')
/* Counted noun composed in JS (the one/many pair), never through a
   params-carrying t() — see PocketHome for the same shape. */
const venuesAnswering = computed(() => {
  const n = fed.value?.venues.length ?? 0
  return tp(n === 1 ? 'pocket.trade.venueAnsweringOne' : 'pocket.trade.venueAnsweringMany',
            n === 1 ? '{n} market answering right now: markets that are dark or unreachable are not listed.'
                    : '{n} markets answering right now: markets that are dark or unreachable are not listed.',
            { n })
})
let fedAt = 0
function openNetwork() { seg.value = 'network'; void loadFed() }
/** this registry's own venue on the network board: the one whose listings this registry lists itself (the desktop's
 *  rule, StockDiscovery.detectLocalVenue); '' while either list is unread */
const localVenue = computed(() => localVenueOf(fed.value?.venues || [], listings.value.map((l) => l.symbol)))
/** a star on the local venue is the Market tab's star (no venue), so a listing is starred once */
function starVenue(v: FedVenue): string | null { return v.venue === localVenue.value ? null : v.venue }
/** this market's listing from the board: its own ticker and buy sheet, as the Market tab opens them */
function buyHere(fl: FedListing) {
  seg.value = 'local'
  openBySymbol(fl.symbol)
  if (sel.value?.symbol === fl.symbol) openSheet('buy')
}
async function loadFed(force = false) {
  if (!force && fed.value && Date.now() - fedAt < 60_000) return
  fedLoading.value = !fed.value
  fedErr.value = ''
  try {
    fed.value = await exchangeService.federationTickers()
    fedAt = Date.now()
    sweepAlerts()
  } catch (e: any) {
    fedErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { fedLoading.value = false }
}

/* ── §PB3 A3 — watchlist (synced, D3-2) — §PB4: ONE brain shared with the
   desktop surfaces (composables/useWatchAlerts); names preserved for the
   template + batteries. ── */
const wa = useWatchAlerts()
const { starred, watchSyncNote, watchKey, isStarred, loadWatch } = wa
async function toggleStar(sym: string, venue?: string | null) {
  buzz(6)
  await wa.toggleStar(sym, venue)
}
function watchLast(w: WatchEntry): number | null {
  if (!w.venue) { const l = listings.value.find(x => x.symbol === w.symbol); return l?.stats?.last != null ? num(l.stats.last) : null }
  const v = fed.value?.venues.find(x => x.venue === w.venue)
  const fl = v?.listings.find(x => x.symbol === w.symbol)
  return fl?.last != null ? num(fl.last) : null
}
function watchChg(w: WatchEntry): number | null {
  if (!w.venue) { const l = listings.value.find(x => x.symbol === w.symbol); return l?.stats?.change_24h_pct != null ? num(l.stats.change_24h_pct) : null }
  const v = fed.value?.venues.find(x => x.venue === w.venue)
  const fl = v?.listings.find(x => x.symbol === w.symbol)
  return fl?.change_24h_pct != null ? num(fl.change_24h_pct) : null
}
function openWatch(w: WatchEntry) {
  if (!w.venue) { openBySymbol(w.symbol); return }
  openNetwork()
}

/* ── §PB3 A4 — price alerts — §PB4: shared brain (useWatchAlerts). ── */
const { alertRules, alertNote, firedBanner, loadAlerts, dismissFired } = wa
const alertForm = ref(false)
const alertPct = ref(5)
const myAlerts = computed(() => alertRules.value.filter(r => sel.value && r.symbol === sel.value.symbol && !(r.venue || null) && !isExpired(r)))
async function addAlert() {
  if (!sel.value || !num(sel.value.stats?.last)) return
  alertForm.value = false
  buzz(6)
  await wa.addAlertRule(sel.value.symbol, alertPct.value, num(sel.value.stats!.last))
}
async function removeAlert(a: PriceAlertRule) { await wa.removeAlertRule(a) }
function sweepAlerts() {
  const fired = wa.sweep((sym, venue) => {
    if (!venue) { const l = listings.value.find(x => x.symbol === sym); return l?.stats?.last != null ? num(l.stats.last) : null }
    const v = fed.value?.venues.find(x => x.venue === venue)
    const fl = v?.listings.find(x => x.symbol === sym)
    return fl?.last != null ? num(fl.last) : null
  })
  if (fired.length) buzz([20, 60, 20])
}

/* ── detail ──────────────────────────────────────────────── */
const sel = ref<Listing | null>(null)
const tf = ref<'1m' | '15m' | '1h' | '1d'>('15m')
const candles = ref<Candle[]>([])
const hover = ref<ChartHover | null>(null)
const bookBids = ref<any[]>([])
const bookAsks = ref<any[]>([])
const tape = ref<any[]>([])
const allOrders = ref<any[]>([])
const posCcy = computed(() => (sel.value as any)?.currency || portfolio.value?.positions?.[0]?.currency || currentOwnCurrency())
const maxLvl = computed(() => Math.max(1, ...bookBids.value.map(b => num(b.qty)), ...bookAsks.value.map(a => num(a.qty))))
const lvlW = (q2: any) => `${Math.max(6, (num(q2) / maxLvl.value) * 100)}%`
const spreadTxt = computed(() => {
  const b = num(sel.value?.stats?.best_bid), a = num(sel.value?.stats?.best_ask)
  return b && a ? `spread ${px2(a - b)}` : '· · ·'
})
// tick rule: color a fill by comparing to the NEXT (older) fill's price
const tickDir = (i: number) => {
  const cur = num(tape.value[i]?.price), prev = num(tape.value[i + 1]?.price)
  return !prev || cur === prev ? '' : cur > prev ? 'buy' : 'sell'
}
const isHalted = computed(() => ['halted', 'suspended', 'delisted'].includes(((sel.value as any)?.status || '').toLowerCase()))
const myPos = computed<Position | null>(() =>
  portfolio.value?.positions.find(p => p.symbol === sel.value?.symbol) || null)

const TERMINAL = ['filled', 'cancelled', 'canceled', 'expired', 'rejected']
const openOrders = computed(() => allOrders.value.filter((o: any) => !TERMINAL.includes((o.status || '').toLowerCase())))
const histOrders = computed(() => allOrders.value.filter((o: any) => TERMINAL.includes((o.status || '').toLowerCase())))
const showHist = ref(false)
const filledOf = (o: any) => Math.max(0, num(o.qty) - num(o.remaining ?? o.qty))
const lastReceipt = ref<{ ok: boolean; txt: string } | null>(null)
const cancelNote = ref('')

function openDetail(l: Listing) { sel.value = l; hover.value = null; lastReceipt.value = null; cancelNote.value = ''; showHist.value = false; alertForm.value = false; alertNote.value = ''; void refreshDetail(true); buzz(6) }
function openBySymbol(sym: string) { const l = listings.value.find(x => x.symbol === sym); if (l) openDetail(l) }
function closeDetail() { sel.value = null; candles.value = []; tape.value = []; bookBids.value = []; bookAsks.value = [] }
function setTf(f: any) { tf.value = f; void loadCandles() }

async function loadCandles() {
  if (!sel.value) return
  try { candles.value = (await exchangeService.candles(sel.value.symbol, tf.value, 64)).candles } catch { /* keep last */ }
}
async function refreshDetail(full = false) {
  const s = sel.value; if (!s) return
  try {
    const [li, bk, tp] = await Promise.all([
      exchangeService.listing(s.symbol),
      exchangeService.book(s.symbol, 5),
      exchangeService.trades(s.symbol, 12),
    ])
    if (sel.value?.symbol !== s.symbol) return
    sel.value = li
    if (li.stats?.last != null) markFlash(li.symbol, num(li.stats.last))
    bookAsks.value = [...(bk.asks || [])].slice(0, 5).reverse()
    bookBids.value = (bk.bids || []).slice(0, 5)
    tape.value = tp.trades || []
    stale.value = false
    sweepAlerts()
    if (full) { void loadCandles(); void loadMyOrders() }
  } catch { stale.value = true }
}
async function loadMyOrders() {
  if (!sel.value || !actorDid.value) return
  try {
    if (!await ensureAgent()) return
    const r = await exchangeService.myOrders(sel.value.symbol)
    allOrders.value = r.orders || []
    ordersErr.value = ''
  } catch (e: any) {
    // §POCKETBRIDGE2 W1 — a failed read is not "no open orders".
    ordersErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  }
}
// §PB3 A7 — a cancel names what came back. Buy escrow refunds ride the async
// settlement worker, so the wording is "returns shortly", never "returned".
async function cancel(o: any) {
  try {
    await exchangeService.cancelOrder(o.id)
    buzz([10, 30, 10])
    if ((o.side || '').toLowerCase() === 'buy') {
      const esc = num(o.escrow_amount)
      const est = esc > 0 && num(o.qty) > 0 ? esc * (num(o.remaining ?? o.qty) / num(o.qty)) : num(o.remaining ?? o.qty) * num(o.price)
      cancelNote.value = tp('pocket.trade.cancelEscrow', 'Cancelled — ≈{amount} {ccy} escrow returns to your balance shortly', { amount: px2(est), ccy: posCcy.value })
    } else {
      cancelNote.value = tp('pocket.trade.cancelShares', 'Cancelled: {n} pts unlocked in your position', { n: num(o.remaining ?? o.qty) })
    }
    void loadMyOrders(); void refreshDetail(); void loadPortfolio()
  }
  catch (e: any) { orderMsg.value = { ok: false, txt: e?.response?.data?.detail || t('pocket.trade.cancelFailed', 'Cancel failed') } }
}

/* ── acting agent + portfolio ────────────────────────────── */
// §POCKETBRIDGE #PK3 — the ONE shared agent-context brain (sealed-vault aware).
const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()
const actorDid = ref('')
const portfolio = ref<Portfolio | null>(null)
const ordersErr = ref(''); const posErr = ref(''); const orgsErr = ref('')

const ensureAgent = () => ensureAgentFor(actorDid.value)
async function loadPortfolio() {
  if (!actorDid.value) return
  posErr.value = ''
  try { if (!await ensureAgent()) { posErr.value = noAgentReason.value || t('pocket.trade.agentUnavailable', 'agent unavailable'); return } portfolio.value = await exchangeService.portfolio() }
  catch (e: any) { posErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed') }
}

/* ── §POCKETBRIDGE4 WS-T — portfolio analytics ─────────────
 * Equity + 24h line derived from data the venue already serves (positions ×
 * hourly closes). Honest caps are STATED, never implied: the sparkline covers
 * the top positions by value, unpriced positions are named as excluded, and
 * the 24h delta exists only when a 24h-ago price actually does. */
const pAna = ref<{ points: number[]; equity: number; day: number | null; note: string } | null>(null)
async function loadPortfolioAnalytics() {
  const all = portfolio.value?.positions || []
  const priced = all.filter(p => p.last != null && num(p.qty) > 0)
  if (!priced.length) { pAna.value = null; return }
  const ranked = [...priced].sort((a, b) => num(b.qty) * num(b.last) - num(a.qty) * num(a.last))
  const take = ranked.slice(0, 6)
  const series = await Promise.all(take.map(async p => {
    try { const { candles } = await exchangeService.candles(p.symbol, '1h', 25); return { p, cs: candles.map(c => num(c.c)).filter(Number.isFinite) } }
    catch { return { p, cs: [] as number[] } }
  }))
  const N = 24
  const points: number[] = []
  let anyHistory = false
  for (let i = 0; i < N; i++) {
    let eq = 0
    for (const { p, cs } of series) {
      const idx = cs.length - N + i
      const px = cs.length ? (idx >= 0 ? cs[idx] : cs[0]) : num(p.last)
      if (cs.length > 1) anyHistory = true
      eq += num(p.qty) * px
    }
    points.push(eq)
  }
  const equity = take.reduce((s, p) => s + num(p.qty) * num(p.last), 0)
  const day = anyHistory && points.length >= 2 ? equity - points[0] : null
  const parts = [t('pocket.trade.anaHourly', 'hourly closes, last 24h')]
  if (priced.length > take.length) parts.push(tp('pocket.trade.anaTop', 'top {n} of {total} positions by value', { n: take.length, total: priced.length }))
  if (all.length > priced.length) parts.push(tp('pocket.trade.anaUnpriced', '{n} unpriced excluded', { n: all.length - priced.length }))
  if (!anyHistory) parts.push(t('pocket.trade.anaNoHistory', 'no price history yet — flat line is the current mark'))
  pAna.value = { points, equity, day, note: parts.join(' · ') }
}
watch(portfolio, () => { void loadPortfolioAnalytics().catch(() => { pAna.value = null }) })
const sparkPoints = computed(() => {
  const pts = pAna.value?.points || []
  if (pts.length < 2) return ''
  const min = Math.min(...pts), max = Math.max(...pts)
  const span = max - min
  return pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * 100
    const y = span > 0 ? 24 - ((v - min) / span) * 20 : 14
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

/* ── order sheet ─────────────────────────────────────────── */
const sheet = ref<'buy' | 'sell' | null>(null)
const otype = ref<'limit' | 'market'>('limit')
const qty = ref(1)
const price = ref('')
const placing = ref(false)
const verifying = ref(false)
const orderMsg = ref<{ ok: boolean; txt: string } | null>(null)
const burst = ref(false)

function openSheet(side: 'buy' | 'sell') {
  sheet.value = side; orderMsg.value = null
  price.value = sel.value?.stats?.last || ''
  if (!actorDid.value && credAgents.value.length) actorDid.value = credAgents.value[0].did
  buzz(6)
}
const canPlace = computed(() => !!sel.value && !!actorDid.value && qty.value >= 1 && (otype.value === 'market' || num(price.value) > 0))
const estTxt = computed(() => {
  const px = otype.value === 'limit' ? num(price.value) : num(sel.value?.stats?.last)
  return px ? `≈ ${px2(px * qty.value)} ${posCcy.value}` : '—'
})
const confirmTxt = computed(() => tp('pocket.trade.confirmTxt', '{side} {qty} ${sym} · {price}', {
  side: sheet.value === 'buy' ? t('pocket.trade.buy', 'Buy') : t('pocket.trade.sell', 'Sell'),
  qty: qty.value, sym: sel.value?.symbol,
  price: otype.value === 'limit' ? px2(price.value) : t('pocket.trade.marketLower', 'market'),
}))

// §PB3 A8 — a fill is a RECEIPT: the place response carries synchronous fills
// (matching runs under the listing lock), so the truth is already in hand.
// A market/IOC remainder auto-cancels server-side — status 'cancelled' WITH
// fills means "filled what the book had", not failure.
function receiptFor(r: any, side: string, symbol: string): { ok: boolean; txt: string } {
  const fills: any[] = r.fills || []
  const filled = Math.max(0, num(r.qty) - num(r.remaining))
  const st = (r.status || '').toLowerCase()
  if (fills.length) {
    const notional = fills.reduce((s, f) => s + num(f.notional), 0)
    const fqty = fills.reduce((s, f) => s + num(f.qty), 0) || filled || 1
    const avg = notional / fqty
    const money = side === 'buy'
      ? tp('pocket.trade.rcPaid', 'paid {amount}', { amount: px2(notional) })
      : tp('pocket.trade.rcProceeds', 'proceeds ≈ {amount} before market fees', { amount: px2(notional) })
    const remainder = num(r.remaining) > 0
      ? (st === 'cancelled' || st === 'canceled'
          ? ' ' + tp('pocket.trade.rcRemCancelled', '— remainder of {n} cancelled (book ran out)', { n: num(r.remaining) })
          : ' ' + tp('pocket.trade.rcRemOpen', '— {n} still open on the book', { n: num(r.remaining) }))
      : ''
    return { ok: true, txt: tp('pocket.trade.rcFilled', 'Filled {qty} ${sym} @ {avg} — {money} {ccy}', { qty: fqty, sym: symbol, avg: px2(avg), money, ccy: posCcy.value }) + remainder }
  }
  if (st === 'cancelled' || st === 'canceled') return { ok: false, txt: t('pocket.trade.rcNoFill', 'No fill — the book had no matching liquidity; nothing was paid') }
  if (st === 'rejected') return { ok: false, txt: t('pocket.trade.rcRejected', 'Rejected') + (r.reject_reason ? ' — ' + r.reject_reason : '') }
  return { ok: true, txt: tp('pocket.trade.rcAccepted', 'Accepted — {side} {qty} ${sym} waiting on the book', { side: sideLabel(side), qty: num(r.qty), sym: symbol })
    + (r.escrow_amount ? ' ' + tp('pocket.trade.rcEscrowed', '({amount} {ccy} escrowed)', { amount: px2(r.escrow_amount), ccy: posCcy.value }) : '') }
}

async function place() {
  if (!canPlace.value || placing.value || !sel.value || !sheet.value) return
  placing.value = true; orderMsg.value = null
  try {
    if (lock.enabled.value) {
      verifying.value = true
      const ok = await lock.verify().catch(() => false)
      verifying.value = false
      if (!ok) { orderMsg.value = { ok: false, txt: t('pocket.stake.bioFailed', 'Biometric confirmation failed.') }; return }
    }
    if (!await ensureAgent()) { orderMsg.value = { ok: false, txt: t('pocket.send.authFailed', 'Could not authenticate as that agent.') }; return }
    const r = await exchangeService.placeOrder({
      listing: sel.value.symbol, side: sheet.value, order_type: otype.value,
      qty: qty.value, price: otype.value === 'limit' ? String(price.value) : undefined,
      client_order_id: `pkt-${Date.now()}`,
    })
    buzz([15, 40, 15])
    const receipt = receiptFor(r, sheet.value, sel.value.symbol)
    orderMsg.value = receipt
    lastReceipt.value = receipt
    cancelNote.value = ''
    burst.value = true
    setTimeout(() => { burst.value = false; sheet.value = null }, 2200)
    void refreshDetail(); void loadMyOrders(); void loadPortfolio()
  } catch (e: any) {
    buzz([60])
    orderMsg.value = { ok: false, txt: e?.response?.data?.detail || e?.message || t('pocket.trade.orderRejected', 'Order rejected') }
  } finally { placing.value = false; verifying.value = false }
}

/* ── §PB3 D3-5 — passport sheet (existing rail; buy-only like desktop) ──── */
const pp = ref<{ listing: FedListing; venue: FedVenue } | null>(null)
const ppQty = ref(1)
const ppPrice = ref('')
const ppBuffer = 3
const ppBusy = ref(false)
const ppMsg = ref<{ ok: boolean; txt: string } | null>(null)
function openPassport(fl: FedListing, v: FedVenue) {
  pp.value = { listing: fl, venue: v }
  ppQty.value = 1
  ppPrice.value = fl.last || ''
  ppMsg.value = null
  if (!actorDid.value && credAgents.value.length) actorDid.value = credAgents.value[0].did
  buzz(6)
}
const canPassport = computed(() => !!pp.value && !!actorDid.value && ppQty.value >= 1 && num(ppPrice.value) > 0)
async function placePassport() {
  if (!canPassport.value || ppBusy.value || !pp.value) return
  ppBusy.value = true; ppMsg.value = null
  try {
    if (lock.enabled.value && !(await lock.verify().catch(() => false))) {
      ppMsg.value = { ok: false, txt: t('pocket.stake.bioFailed', 'Biometric confirmation failed.') }; return
    }
    if (!await ensureAgent()) { ppMsg.value = { ok: false, txt: t('pocket.send.authFailed', 'Could not authenticate as that agent.') }; return }
    const r = await exchangeService.passportOrder({
      venue_registry: pp.value.venue.venue, listing: pp.value.listing.symbol,
      qty: ppQty.value, price: String(ppPrice.value), side: 'buy', fx_buffer_pct: ppBuffer,
    })
    buzz([15, 40, 15])
    ppMsg.value = { ok: true, txt: tp('pocket.trade.ppAcceptedMsg',
      'Accepted on {venue} — status {status}; sent {amount} over FX. Passport fills take minutes to hours — check back or track on desktop.',
      { venue: pp.value.venue.venue,
        status: r.status || t('pocket.trade.ppFunding', 'funding'),
        amount: r.sent_amount ? fmt(r.sent_amount) + ' ' + (r.sent_currency || '') : t('pocket.trade.ppFunds', 'funds') }) }
  } catch (e: any) {
    ppMsg.value = { ok: false, txt: e?.response?.data?.detail || e?.message || t('pocket.trade.ppRefused', 'Passport order refused') }
  } finally { ppBusy.value = false }
}

/* ── §PB3 A5 — the firm money cockpit ────────────────────── */
const firmOpen = ref(false)
const orgs = ref<any[]>([])
const orgsLoading = ref(false)
const orgId = ref('')
const treasury = ref<any>(null)
const treErr = ref('')
const treFailed = ref(false)
const acct = ref<any>(null)
const acctErr = ref('')
const deskQty = ref<Record<string, number | null>>({})
const solvency = ref<any>(null)
const solvencyMiss = ref(false)
const fQty = ref(1)
const fPrice = ref('')
const firmBusy = ref(false)
const firmMsg = ref<{ ok: boolean; txt: string } | null>(null)
const fundDid = ref('')
const fundAmt = ref('')
const fundBusy = ref(false)
const fundMsg = ref<{ ok: boolean; txt: string } | null>(null)
const ownSymbol = computed(() => listings.value.find(l => (l as any).organization_id === orgId.value)?.symbol || '')
const orgSymbols = computed<string[]>(() => (treasury.value?.listings || []).map((t: any) => t.symbol))
const lockedRows = computed<{ symbol: string; locked: number }[]>(() => {
  const rows: { symbol: string; locked: number }[] = []
  for (const l of solvency.value?.listings || []) {
    if (!orgSymbols.value.includes(l.symbol)) continue
    const locked = num(l?.treasury_solvency?.obligation_breakdown?.open_buyback_escrow)
    if (locked > 0) rows.push({ symbol: l.symbol, locked })
  }
  return rows
})
const lockedTotal = computed(() => lockedRows.value.reduce((s, r) => s + r.locked, 0))

async function openFirm() {
  firmOpen.value = true; firmMsg.value = null; fundMsg.value = null
  if (orgs.value.length) return
  orgsLoading.value = true
  orgsErr.value = ''
  try {
    orgs.value = await organizationService.listOrganizations()
    if (orgs.value.length) { orgId.value = orgs.value[0].id; void loadTreasury() }
  } catch (e: any) {
    // §POCKETBRIDGE2 W1 — an error stated as a fact about membership was the
    // worst kind of wrong ("You're not a member of any organization").
    orgsErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { orgsLoading.value = false }
}
async function loadTreasury() {
  treasury.value = null; acct.value = null; firmMsg.value = null; fundMsg.value = null
  treErr.value = ''; treFailed.value = false; acctErr.value = ''; deskQty.value = {}
  if (!orgId.value) return
  // Pool 1 — the §V0113 desk roll-up (org-member gated server-side)
  try { treasury.value = await exchangeService.orgTreasury(orgId.value) }
  catch (e: any) {
    // §FESUITE (V0575): the market's refusal is its answer; a read that got no answer (or a server error, or an error
    // page) is not "this account is not a member": the org came from this person's own list
    const st: number | undefined = e?.response?.status
    const detail = typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : ''
    if (st === 403) treErr.value = detail || t('pocket.trade.deskMemberOnly', 'Desk figures are org-member only — this account is not a member.')
    else if (st && st < 500 && detail) treErr.value = detail
    else treFailed.value = true
  }
  // Pool 2 — the mig-0146 org account (member-readable)
  try { acct.value = await organizationService.getOrgTreasuryAccount(orgId.value) }
  catch (e: any) { acctErr.value = e?.response?.data?.detail || e?.message || t('pocket.trade.orgAcctUnavailable', 'org account unavailable') }
  // Pool 3 — public solvency card (null = the venue serves no card)
  if (!solvency.value && !solvencyMiss.value) {
    solvency.value = await exchangeService.solvencyCard()
    if (!solvency.value) solvencyMiss.value = true
  }
  // Desk share holdings: the cap-table's treasury_qty per listing (public read)
  for (const t of treasury.value?.listings || []) {
    exchangeService.holders(t.symbol, 1, 0)
      .then(h => { deskQty.value = { ...deskQty.value, [t.symbol]: num(h.treasury_qty) } })
      .catch(() => { deskQty.value = { ...deskQty.value, [t.symbol]: null } })
  }
}
async function firmAct(kind: 'buyback' | 'sell') {
  if (!orgId.value || !ownSymbol.value || firmBusy.value) return
  firmBusy.value = true; firmMsg.value = null
  try {
    if (lock.enabled.value && !(await lock.verify().catch(() => false))) {
      firmMsg.value = { ok: false, txt: t('pocket.stake.bioFailed', 'Biometric confirmation failed.') }; return
    }
    const r = kind === 'buyback'
      ? await exchangeService.treasuryBuyback(orgId.value, ownSymbol.value, fQty.value, String(fPrice.value || sel?.value?.stats?.last || '0'))
      : await exchangeService.treasurySell(orgId.value, ownSymbol.value, fQty.value, fPrice.value ? 'limit' : 'market', fPrice.value || undefined)
    buzz([15, 40, 15])
    firmMsg.value = { ok: true, txt: tp('pocket.trade.firmActOk', '{action} {status}', {
      action: kind === 'buyback' ? t('pocket.trade.buyback', 'Treasury buy') : t('pocket.trade.treasurySell', 'Treasury sell'),
      status: r.order_status || r.status || t('pocket.trade.acceptedWord', 'accepted') }) }
    void loadTreasury()
  } catch (e: any) {
    firmMsg.value = { ok: false, txt: e?.response?.data?.detail || tp('pocket.trade.firmActRejected', '{action} rejected (org-admin only)', { action: kind }) }
  } finally { firmBusy.value = false }
}
// Pool 2 door: fund an ORG AGENT from the org account (admin; the rail
// enforces both the role and the org membership; Idempotency-Key REQUIRED).
async function fundAgent() {
  if (!orgId.value || !fundDid.value || !num(fundAmt.value) || fundBusy.value) return
  fundBusy.value = true; fundMsg.value = null
  try {
    if (lock.enabled.value && !(await lock.verify().catch(() => false))) {
      fundMsg.value = { ok: false, txt: t('pocket.stake.bioFailed', 'Biometric confirmation failed.') }; return
    }
    const idem = (globalThis.crypto?.randomUUID?.() ?? `pkfund-${Date.now()}`)
    await organizationService.fundOrgAgent(orgId.value, fundDid.value, String(fundAmt.value), idem)
    buzz([15, 40, 15])
    fundMsg.value = { ok: true, txt: tp('pocket.trade.fundedMsg', 'Funded {amount} {ccy} → {did}', { amount: fmt(fundAmt.value), ccy: posCcy.value, did: shortDid(fundDid.value) }) }
    fundAmt.value = ''
    void loadTreasury()
  } catch (e: any) {
    fundMsg.value = { ok: false, txt: e?.response?.data?.detail || e?.message || t('pocket.trade.fundRefused', 'Funding refused (org-admin only)') }
  } finally { fundBusy.value = false }
}

/* ── §PB3 WS-B — the trade DOOR: /pocket/trade?sym=QCC[&side=buy&qty=5&px=120]
   used by voice, the assistant panel and the price-alert notification click.
   Query-only navigation does not remount (§NOTIFLOG) — watch, don't mount. ── */
const route = useRoute()
const router = useRouter()
let doorPending: { sym: string; side?: 'buy' | 'sell'; qty?: number; px?: string } | null = null
function consumeTradeQuery() {
  const sym = typeof route.query.sym === 'string' ? route.query.sym.toUpperCase() : ''
  if (!sym) return
  const side = route.query.side === 'buy' || route.query.side === 'sell' ? route.query.side : undefined
  doorPending = {
    sym, side,
    qty: route.query.qty ? Math.max(1, Math.floor(num(route.query.qty))) : undefined,
    px: typeof route.query.px === 'string' ? route.query.px : undefined,
  }
  const qq = { ...route.query } as Record<string, any>
  delete qq.sym; delete qq.side; delete qq.qty; delete qq.px
  router.replace({ query: qq }).catch(() => {})
  applyDoor()
}
function applyDoor() {
  if (!doorPending || loading.value) return
  const d = doorPending
  const l = listings.value.find(x => x.symbol === d.sym)
  if (!l) { doorPending = null; q.value = d.sym; return }  // not on this venue — leave it in search, honestly visible
  doorPending = null
  openDetail(l)
  if (d.side) {
    openSheet(d.side)
    if (d.qty) qty.value = d.qty
    if (d.px) { otype.value = 'limit'; price.value = d.px }
    else if (!d.px && d.qty) otype.value = 'market'
  }
}
watch(() => route.fullPath, () => { if (route.name === 'pocket-trade') consumeTradeQuery() })

/* ── lifecycle + polling ─────────────────────────────────── */
let pollT: any = null
// §PB3 — Escape closes the topmost sheet (batch-2 W2 discipline; he tests on desktop)
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (pp.value) { pp.value = null; return }
  if (sheet.value) { sheet.value = null; return }
  if (firmOpen.value) { firmOpen.value = false; return }
  if (alertForm.value) { alertForm.value = false }
}
const alive = useAlive()
onMounted(async () => {
  window.addEventListener('keydown', onKey)
  if (credAgents.value.length) actorDid.value = (auth as any).activeAgent?.did || credAgents.value[0].did
  void loadWatch()
  void loadAlerts()
  await loadMarkets()
  // §FESUITE (the leave sweep): a page left during its first read starts no 5 s poll when it lands
  if (!alive()) return
  consumeTradeQuery()
  applyDoor()
  void loadPortfolio()
  let tick = 0
  pollT = setInterval(() => {
    tick++
    if (sel.value) void refreshDetail()            // detail: every 5s
    else if (tick % 3 === 0) void loadMarkets()    // markets: every 15s
    if (seg.value === 'network' && tick % 12 === 0) void loadFed(true)  // board: every 60s while open
  }, 5000)
})
onBeforeUnmount(() => { if (pollT) clearInterval(pollT); window.removeEventListener('keydown', onKey) })
</script>

<style scoped>
.pt-wrap { max-width: 560px; margin: 0 auto; padding: 1rem 1rem 5.5rem; box-sizing: border-box; }
.pt-head { display: flex; align-items: center; gap: 0.55rem; margin-bottom: 0.8rem; }
.pt-head-id { flex: 1 1 auto; min-width: 0; }
.pt-title { font-size: 1.15rem; margin: 0; }
.pt-sub { font-size: 0.72rem; opacity: 0.5; display: block; }
.pt-live { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #34d399; margin-left: 0.25rem; vertical-align: middle; animation: pt-pulse 2s ease-in-out infinite; }
@keyframes pt-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(52,211,153,0.5); } 50% { opacity: 0.55; box-shadow: 0 0 0 4px rgba(52,211,153,0); } }
.pt-back { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #e6edf3; width: 44px; height: 44px; display: grid; place-items: center; cursor: pointer; flex: 0 0 auto; }
.pt-back :deep(svg) { width: 1.2rem; height: 1.2rem; }
.pt-err-note { font-size: 0.74rem; color: #ff9a9a; margin: 0.3rem 0; }
.pt-retry { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; color: inherit; padding: 0.3rem 0.7rem; min-height: 36px; cursor: pointer; margin-left: 0.4rem; }
.pt-scope { font-size: 0.66rem; opacity: 0.45; margin: 0.2rem 0 0; }
.pt-divs { display: flex; align-items: center; gap: 0.35rem; font-size: 0.74rem; opacity: 0.75; margin: 0.2rem 0 0.5rem; }
.pt-divs svg { width: 0.9rem; height: 0.9rem; color: #34d399; }
/* §POCKETBRIDGE4 — portfolio analytics */
.pt-ana { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 0.55rem 0.7rem; margin: 0.15rem 0 0.6rem; }
.pt-ana-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.pt-ana-eq { font-size: 1.02rem; font-weight: 800; font-variant-numeric: tabular-nums; }
.pt-ana-eq small { font-size: 0.62rem; font-weight: 600; opacity: 0.55; }
.pt-ana-day { font-size: 0.72rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.pt-ana-day.up { color: #34d399; }
.pt-ana-day.down { color: #f87171; }
.pt-ana-day.flat { opacity: 0.5; }
.pt-ana-spark { display: block; width: 100%; height: 30px; margin: 0.3rem 0 0.15rem; color: rgba(0,212,255,0.75); }
.pt-ana-note { margin: 0; font-size: 0.6rem; opacity: 0.5; }
.pt-firm-btn { margin-left: auto; display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(167,139,250,0.1); border: 1px solid rgba(167,139,250,0.3); color: #a78bfa; border-radius: 10px; padding: 0.4rem 0.65rem; min-height: 44px; font-size: 0.75rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pt-firm-btn :deep(svg) { width: 0.9rem; height: 0.9rem; }
.pt-head-px { margin-left: auto; text-align: right; }

/* §PB3 A1 — controls */
.pt-controls { display: flex; gap: 0.45rem; margin-bottom: 0.55rem; }
.pt-search-box { flex: 1 1 auto; display: flex; align-items: center; gap: 0.35rem; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 0 0.6rem; min-height: 44px; }
.pt-search-box :deep(svg) { width: 1rem; height: 1rem; opacity: 0.5; flex: 0 0 auto; }
.pt-search { flex: 1 1 auto; min-width: 0; background: none; border: none; outline: none; color: #e6edf3; font-size: 16px; min-height: 44px; }
/* W2: 16px on ALL form controls (selects included) — iOS zoom + the sweep */
.pt-sort { flex: 0 0 auto; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; color: #e6edf3; font-size: 16px; min-height: 44px; padding: 0 0.5rem; outline: none; max-width: 34vw; }
.pt-venueseg { margin-bottom: 0.55rem; }

/* §PB3 A3 — watchlist */
.pt-watch-strip { display: flex; align-items: center; gap: 0.35rem; overflow-x: auto; padding-bottom: 0.35rem; margin-bottom: 0.4rem; scrollbar-width: none; }
.pt-watch-strip::-webkit-scrollbar { display: none; }
.pt-watch-chip { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.7rem; font-weight: 700; background: rgba(251,191,36,0.07); border: 1px solid rgba(251,191,36,0.3); color: #e6edf3; border-radius: 999px; padding: 0.3rem 0.6rem; min-height: 44px; cursor: pointer; white-space: nowrap; -webkit-tap-highlight-color: transparent; }
.pt-watch-chip small { opacity: 0.5; }
.pt-watch-chip b { font-variant-numeric: tabular-nums; }
.pt-watch-chip b.up { color: #34d399; } .pt-watch-chip b.down { color: #ff8a8a; }
.pt-sync-note { font-size: 0.62rem; color: #fbbf24; flex: 0 0 auto; }
.pt-star { background: none; border: none; color: rgba(230,237,243,0.4); width: 32px; height: 32px; display: grid; place-items: center; cursor: pointer; position: relative; -webkit-tap-highlight-color: transparent; }
.pt-star::before { content: ''; position: absolute; inset: -6px; }
.pt-star :deep(svg) { width: 1.05rem; height: 1.05rem; }
.pt-star.on { color: #fbbf24; }
.pt-star.head { width: 44px; height: 44px; flex: 0 0 auto; }

/* §PB3 A4 — alerts */
.pt-alert-banner { display: flex; align-items: center; gap: 0.5rem; background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.4); border-radius: 12px; padding: 0.5rem 0.7rem; margin-bottom: 0.55rem; }
.pt-alert-banner :deep(svg) { width: 1rem; height: 1rem; color: #fbbf24; flex: 0 0 auto; }
.pt-alert-banner-txt { flex: 1 1 auto; display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.76rem; }
.pt-alert-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.35rem; margin: 0.5rem 0 0; }
.pt-alert-btn { display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.35); color: #fbbf24; border-radius: 10px; padding: 0.3rem 0.6rem; min-height: 44px; font-size: 0.74rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pt-alert-btn :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pt-alert-chip { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.68rem; font-variant-numeric: tabular-nums; border: 1px solid rgba(251,191,36,0.3); background: rgba(251,191,36,0.05); border-radius: 999px; padding: 0.24rem 0.3rem 0.24rem 0.55rem; }
.pt-alert-chip.fired { border-color: rgba(52,211,153,0.5); }
.pt-alert-chip small { opacity: 0.55; }
.pt-alert-chip b { color: #34d399; }
.pt-alert-form { display: flex; align-items: center; gap: 0.35rem; font-size: 0.78rem; margin-top: 0.4rem; flex-wrap: wrap; }
.pt-in.slim { width: 74px; min-height: 44px; padding: 0.3rem 0.5rem; }
.pt-ghost.slim { margin-top: 0; min-height: 44px; padding: 0.3rem 0.8rem; }

/* §PB3 A2 — federation board */
.pt-fed-venue { margin-bottom: 0.7rem; }
.pt-fed-head { display: flex; align-items: baseline; gap: 0.4rem; margin-bottom: 0.35rem; }
.pt-fed-name { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.74rem; font-weight: 800; letter-spacing: 0.03em; }
.pt-fed-name :deep(svg) { width: 0.9rem; height: 0.9rem; color: var(--nc-primary, #00d4ff); }
.pt-fed-ccy { font-size: 0.64rem; opacity: 0.5; }
.pt-fed-here { font-size: 0.62rem; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--nc-primary, #00d4ff); border: 1px solid currentColor; border-radius: 6px; padding: 0 0.3rem; }
.pt-mkt.fed { grid-template-columns: 1fr auto auto; cursor: default; }
.pt-fed-acts { display: flex; align-items: center; gap: 0.2rem; }
.pt-passport-btn { display: inline-flex; align-items: center; gap: 0.25rem; background: rgba(52,211,153,0.09); border: 1px solid rgba(52,211,153,0.35); color: #34d399; border-radius: 10px; padding: 0.3rem 0.55rem; min-height: 44px; font-size: 0.7rem; font-weight: 800; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pt-passport-btn :deep(svg) { width: 0.85rem; height: 0.85rem; }

.pt-index { display: flex; align-items: baseline; gap: 0.5rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 0.55rem 0.75rem; margin-bottom: 0.55rem; }
.pt-index-name { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.68rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.6; font-weight: 700; }
.pt-index-name :deep(svg) { width: 0.85rem; height: 0.85rem; }
.pt-index-val { font-variant-numeric: tabular-nums; font-weight: 800; font-size: 1rem; }
.pt-index-chg { font-variant-numeric: tabular-nums; font-size: 0.75rem; font-weight: 700; }
.pt-index.up .pt-index-chg { color: #34d399; } .pt-index.down .pt-index-chg { color: #ff8a8a; }

.pt-league { display: flex; align-items: center; gap: 0.35rem; overflow-x: auto; padding-bottom: 0.35rem; margin-bottom: 0.5rem; scrollbar-width: none; }
.pt-league::-webkit-scrollbar { display: none; }
.pt-league-lab { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.05em; color: #fbbf24; font-weight: 800; flex: 0 0 auto; }
.pt-league-lab :deep(svg) { width: 0.8rem; height: 0.8rem; }
.pt-league-chip { flex: 0 0 auto; font-size: 0.66rem; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); border-radius: 999px; padding: 0.22rem 0.55rem; white-space: nowrap; }
.pt-league-chip b { color: #fbbf24; margin-right: 0.15rem; }
.pt-league-chip small { opacity: 0.55; margin-left: 0.2rem; }

.pt-lab { display: block; font-size: 0.68rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 600; margin: 0.7rem 0 0.35rem; }
.pt-list, .pt-pos-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.pt-skel { height: 58px; border-radius: 14px; background: linear-gradient(100deg, rgba(255,255,255,0.03) 40%, rgba(255,255,255,0.07) 50%, rgba(255,255,255,0.03) 60%); background-size: 200% 100%; animation: pt-sh 1.2s infinite; }
@keyframes pt-sh { to { background-position-x: -200%; } }

.pt-mkt { display: grid; grid-template-columns: 1fr 72px auto auto; align-items: center; gap: 0.5rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; padding: 0.65rem 0.5rem 0.65rem 0.8rem; cursor: pointer; transition: background 0.15s, transform 0.1s; -webkit-tap-highlight-color: transparent; }
.pt-mkt:active { background: rgba(255,255,255,0.06); transform: scale(0.985); }
.pt-spark-line { stroke-dasharray: 160; stroke-dashoffset: 160; animation: pt-draw 0.9s ease-out forwards; }
@keyframes pt-draw { to { stroke-dashoffset: 0; } }
.pt-sym { font-weight: 800; font-size: 0.92rem; letter-spacing: 0.01em; }
.pt-name { display: block; font-size: 0.68rem; opacity: 0.55; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 34vw; }
.pt-spark { width: 72px; height: 24px; opacity: 0.9; }
.pt-mkt-px { text-align: right; }
.pt-last { font-variant-numeric: tabular-nums; font-weight: 800; font-size: 0.95rem; display: block; border-radius: 6px; padding: 0 0.2rem; transition: background 0.4s, color 0.4s; }
.pt-last.big { font-size: 1.25rem; }
.pt-last.flash-up { background: rgba(52,211,153,0.22); color: #34d399; }
.pt-last.flash-down { background: rgba(255,138,138,0.22); color: #ff8a8a; }
.pt-chg { font-variant-numeric: tabular-nums; font-size: 0.7rem; font-weight: 700; }
.pt-chg.up { color: #34d399; } .pt-chg.down { color: #ff8a8a; } .pt-chg.flat { color: rgba(230,237,243,0.4); }

.pt-empty { text-align: center; padding: 1.6rem 0.8rem; opacity: 0.65; font-size: 0.85rem; }
.pt-empty-ico { width: 2rem; height: 2rem; opacity: 0.4; display: block; margin: 0 auto 0.4rem; }
.pt-empty-ico.warn { color: #fbbf24; opacity: 0.8; }
.pt-ghost { background: none; border: 1px solid rgba(255,255,255,0.16); color: #e6edf3; border-radius: 10px; padding: 0.4rem 1rem; margin-top: 0.5rem; cursor: pointer; }

.pt-tfs { display: flex; align-items: center; gap: 0.3rem; margin: 0.25rem 0 0.4rem; }
.pt-tf { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 9px; padding: 0.3rem 0.6rem; min-height: 44px; min-width: 44px; color: rgba(230,237,243,0.6); font-size: 0.72rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pt-tf.active { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.3); color: var(--nc-primary, #00d4ff); }
.pt-ohlc { margin-left: auto; font-size: 0.6rem; font-variant-numeric: tabular-nums; opacity: 0.65; white-space: nowrap; }
.pt-chart { border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; overflow: hidden; background: rgba(255,255,255,0.02); opacity: 0.35; transition: opacity 0.4s; }
.pt-chart.ready { opacity: 1; }

.pt-market-grid { display: grid; grid-template-columns: 1.15fr 1fr; gap: 0.6rem; margin-top: 0.2rem; }
.pt-lvl { position: relative; display: flex; justify-content: space-between; font-size: 0.72rem; font-variant-numeric: tabular-nums; padding: 0.14rem 0.3rem; border-radius: 5px; overflow: hidden; }
.pt-lvl-bar { position: absolute; right: 0; top: 0; bottom: 0; opacity: 0.14; border-radius: 5px; }
.pt-lvl.ask .pt-lvl-bar { background: #ff8a8a; } .pt-lvl.bid .pt-lvl-bar { background: #34d399; }
.pt-lvl.ask .pt-lvl-px { color: #ff8a8a; } .pt-lvl.bid .pt-lvl-px { color: #34d399; }
.pt-lvl-px, .pt-lvl-qty { position: relative; }
.pt-spread { text-align: center; font-size: 0.6rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.45; padding: 0.2rem 0; }
.pt-fill { display: grid; grid-template-columns: 1fr auto auto; gap: 0.4rem; font-size: 0.7rem; font-variant-numeric: tabular-nums; padding: 0.12rem 0.2rem; }
.pt-fill.buy span:first-child { color: #34d399; } .pt-fill.sell span:first-child { color: #ff8a8a; }
.pt-fill-t { opacity: 0.4; font-size: 0.6rem; }
.pt-tape-empty { font-size: 0.72rem; opacity: 0.45; padding: 0.4rem 0.2rem; }

.pt-mypos { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.7rem; background: rgba(0,212,255,0.06); border: 1px solid rgba(0,212,255,0.2); border-radius: 12px; padding: 0.55rem 0.75rem; font-size: 0.8rem; }
.pt-mypos :deep(svg) { width: 1rem; height: 1rem; color: var(--nc-primary, #00d4ff); }
.pt-pos { display: flex; align-items: center; gap: 0.6rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 0.55rem 0.75rem; cursor: pointer; }
.pt-pos-qty { font-size: 0.74rem; opacity: 0.7; flex: 1 1 auto; }
.pt-pos-pnl { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 0.8rem; }
.pt-pos-pnl.up { color: #34d399; } .pt-pos-pnl.down { color: #ff8a8a; } .pt-pos-pnl.flat { color: rgba(230,237,243,0.4); }
.pt-halted { display: flex; align-items: center; gap: 0.4rem; margin-top: 0.7rem; background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24; border-radius: 12px; padding: 0.55rem 0.75rem; font-size: 0.78rem; font-weight: 600; }
.pt-halted :deep(svg) { width: 1rem; height: 1rem; }
.pt-live.stale { background: #fbbf24; animation: none; }

.pt-receipt { font-size: 0.76rem; margin: 0.5rem 0 0; background: rgba(52,211,153,0.07); border: 1px solid rgba(52,211,153,0.3); border-radius: 10px; padding: 0.45rem 0.65rem; }
.pt-receipt.bad { background: rgba(255,138,138,0.07); border-color: rgba(255,138,138,0.3); color: #ff9a9a; }
.pt-receipt.ok { color: #a7f3d0; }

.pt-orders { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.6rem; }
.pt-order-chip { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.68rem; font-variant-numeric: tabular-nums; border-radius: 999px; padding: 0.24rem 0.3rem 0.24rem 0.6rem; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); }
.pt-order-chip.buy { border-color: rgba(52,211,153,0.35); } .pt-order-chip.sell { border-color: rgba(255,138,138,0.35); }
.pt-chip-fill { opacity: 0.6; }
.pt-x { background: rgba(255,255,255,0.08); border: none; color: #e6edf3; width: 1.5rem; height: 1.5rem; border-radius: 50%; display: grid; place-items: center; cursor: pointer; position: relative; flex: 0 0 auto; }
/* W2: the visual stays a small circle; the HIT AREA meets the 44px floor. */
.pt-x::before { content: ''; position: absolute; inset: -12px; }
.pt-x :deep(svg) { width: 0.7rem; height: 0.7rem; }

/* §PB3 A6 — history */
.pt-hist-toggle { display: inline-flex; align-items: center; gap: 0.35rem; background: none; border: 1px solid rgba(255,255,255,0.12); color: rgba(230,237,243,0.75); border-radius: 10px; padding: 0.35rem 0.7rem; min-height: 44px; font-size: 0.72rem; font-weight: 700; cursor: pointer; margin-top: 0.6rem; -webkit-tap-highlight-color: transparent; }
.pt-hist-toggle :deep(svg) { width: 0.9rem; height: 0.9rem; }
.pt-history { margin-top: 0.4rem; }
.pt-hist-row { display: grid; grid-template-columns: auto 1fr auto auto auto; gap: 0.5rem; align-items: baseline; font-size: 0.7rem; font-variant-numeric: tabular-nums; padding: 0.22rem 0.2rem; border-bottom: 1px dashed rgba(255,255,255,0.06); }
.pt-hist-side { font-weight: 800; text-transform: uppercase; font-size: 0.62rem; }
.pt-hist-row.buy .pt-hist-side { color: #34d399; } .pt-hist-row.sell .pt-hist-side { color: #ff8a8a; }
.pt-hist-fill { opacity: 0.7; }
.pt-hist-st { opacity: 0.55; text-transform: lowercase; }

.pt-cta { display: flex; gap: 0.55rem; margin-top: 0.9rem; margin-bottom: 0.4rem; }
.pt-buy, .pt-sell { flex: 1 1 0; display: inline-flex; align-items: center; justify-content: center; gap: 0.35rem; border-radius: 14px; padding: 0.85rem; font-size: 0.95rem; font-weight: 800; cursor: pointer; border: none; -webkit-tap-highlight-color: transparent; transition: transform 0.08s; }
.pt-buy:active, .pt-sell:active { transform: scale(0.97); }
.pt-buy { background: linear-gradient(135deg, #059669, #34d399); color: #04110b; }
.pt-sell { background: linear-gradient(135deg, #b91c1c, #ff8a8a); color: #180404; }
.pt-buy:disabled, .pt-sell:disabled { opacity: 0.5; }
.pt-buy :deep(svg), .pt-sell :deep(svg) { width: 1rem; height: 1rem; }

.pt-sheet-veil { position: fixed; inset: 0; background: rgba(2,6,12,0.66); backdrop-filter: blur(3px); z-index: 60; display: flex; align-items: flex-end; }
.pt-sheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0b1320; border: 1px solid rgba(255,255,255,0.1); border-bottom: none; border-radius: 22px 22px 0 0; padding: 0.6rem 1.1rem calc(1.1rem + env(safe-area-inset-bottom)); box-sizing: border-box; max-height: 86vh; overflow-y: auto; }
.pt-sheet-grab { width: 42px; height: 4px; border-radius: 4px; background: rgba(255,255,255,0.18); margin: 0.15rem auto 0.7rem; }
.pt-sheet-title { font-size: 1rem; margin: 0 0 0.5rem; display: flex; align-items: center; gap: 0.4rem; }
.pt-sheet-title.buy { color: #34d399; } .pt-sheet-title.sell { color: #ff8a8a; } .pt-sheet-title.firm { color: #a78bfa; }
.pt-sheet-title :deep(svg) { width: 1.05rem; height: 1.05rem; }
.pt-sheet-enter-active, .pt-sheet-leave-active { transition: opacity 0.22s; }
.pt-sheet-enter-active .pt-sheet, .pt-sheet-leave-active .pt-sheet { transition: transform 0.24s cubic-bezier(0.2, 0.9, 0.3, 1); }
.pt-sheet-enter-from, .pt-sheet-leave-to { opacity: 0; }
.pt-sheet-enter-from .pt-sheet, .pt-sheet-leave-to .pt-sheet { transform: translateY(100%); }

.pt-in { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 0.7rem 0.85rem; min-height: 44px; color: #e6edf3; font-size: 16px; outline: none; }
.pt-in:focus { border-color: rgba(0,212,255,0.45); }
.pt-row { display: flex; gap: 0.55rem; } .pt-col { flex: 1 1 0; min-width: 0; }
.pt-seg { display: flex; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; overflow: hidden; }
.pt-seg button { flex: 1 1 0; background: none; border: none; color: rgba(230,237,243,0.6); padding: 0.62rem 0; min-height: 44px; font-size: 0.8rem; font-weight: 700; cursor: pointer; }
.pt-seg button.active { background: rgba(0,212,255,0.12); color: var(--nc-primary, #00d4ff); }
.pt-step { display: flex; align-items: stretch; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; overflow: hidden; }
.pt-step button { width: 44px; min-height: 44px; background: none; border: none; color: #e6edf3; font-size: 1.1rem; cursor: pointer; }
.pt-step input { flex: 1 1 0; min-width: 0; background: none; border: none; color: #e6edf3; text-align: center; font-size: 16px; font-weight: 700; outline: none; -moz-appearance: textfield; }
.pt-step input::-webkit-outer-spin-button, .pt-step input::-webkit-inner-spin-button { -webkit-appearance: none; }
.pt-est { display: flex; justify-content: space-between; align-items: baseline; font-size: 0.8rem; opacity: 0.85; margin: 0.75rem 0.1rem; }
.pt-est b { font-variant-numeric: tabular-nums; font-size: 0.95rem; }
.pt-confirm { width: 100%; display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; border: none; border-radius: 14px; padding: 0.9rem; font-size: 0.95rem; font-weight: 800; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pt-confirm.buy { background: linear-gradient(135deg, #059669, #34d399); color: #04110b; }
.pt-confirm.sell { background: linear-gradient(135deg, #b91c1c, #ff8a8a); color: #180404; }
.pt-confirm.firmfund { background: linear-gradient(135deg, #6d28d9, #a78bfa); color: #12041c; margin-top: 0.4rem; }
.pt-confirm:disabled { opacity: 0.45; }
.pt-confirm :deep(svg) { width: 1.05rem; height: 1.05rem; }
.pt-result { font-size: 0.8rem; margin: 0.6rem 0 0; text-align: center; }
.pt-burst { display: grid; place-items: center; margin: 0.3rem 0 0.5rem; }
.pt-burst :deep(svg) { width: 3.2rem; height: 3.2rem; color: #34d399; animation: pt-pop 0.5s cubic-bezier(0.2, 1.6, 0.4, 1); filter: drop-shadow(0 0 14px rgba(52,211,153,0.55)); }
@keyframes pt-pop { 0% { transform: scale(0.2); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
.pt-result.ok { color: #34d399; } .pt-result.bad { color: #ff8a8a; }
.pt-warn-note { font-size: 0.78rem; opacity: 0.65; margin: 0.5rem 0; }
.pt-note { font-size: 0.68rem; opacity: 0.5; margin: 0.5rem 0 0; }
.pt-tre { margin-top: 0.4rem; }
.pt-tre-bal { display: flex; justify-content: space-between; align-items: baseline; background: rgba(167,139,250,0.07); border: 1px solid rgba(167,139,250,0.25); border-radius: 12px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem; }
.pt-tre-bal.slim { margin-top: 0.4rem; margin-bottom: 0; }
.pt-tre-bal b { font-variant-numeric: tabular-nums; font-size: 1rem; }
.pt-tre-bal small { font-size: 0.6rem; opacity: 0.5; }

/* §PB3 A5 — pools */
.pt-pool { margin-top: 0.9rem; border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 0.6rem 0.7rem; background: rgba(255,255,255,0.02); }
.pt-pool-head { display: flex; align-items: center; gap: 0.35rem; font-size: 0.74rem; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: #a78bfa; margin-bottom: 0.45rem; }
.pt-pool-head :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pt-pool-head small { text-transform: none; letter-spacing: 0; font-weight: 600; opacity: 0.55; }
.pt-desk { border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 0.5rem 0.65rem; margin-bottom: 0.4rem; background: rgba(255,255,255,0.02); }
.pt-desk-head { display: flex; align-items: baseline; gap: 0.45rem; }
.pt-desk-st { font-size: 0.6rem; opacity: 0.5; text-transform: lowercase; }
.pt-desk-bal { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 0.9rem; }
.pt-desk-rows { display: flex; flex-wrap: wrap; gap: 0.3rem 0.8rem; font-size: 0.66rem; opacity: 0.75; margin-top: 0.3rem; }
.pt-desk-rows b { font-variant-numeric: tabular-nums; }
.pt-desk-rows.one { margin-top: 0.15rem; }
</style>
