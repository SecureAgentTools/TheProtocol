<template>
  <!-- Build #7 (2026-05-07): Treasury & Fee Audit Dashboard.
       Single dashboard answering: how much was minted, what's the treasury
       balance trend, who pays the most fees, what's the supply invariant Δ?
       Pulls aggregated data from /admin/treasury/aggregate. -->
  <div class="at">
    <!-- Ambient background -->
    <div class="at-ambient">
      <div class="at-grid"></div>
      <div class="at-glow at-glow-1"></div>
      <div class="at-glow at-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="at-hero" data-tour="treasury-hero">
      <div class="at-hero-inner">
        <div class="at-chip"><span class="at-chip-dot"></span>{{ t('adminTreasuryView.chip') }}</div>
        <h1 class="at-h1">{{ t('adminTreasuryView.hero.h1a') }}<span class="at-accent">{{ t('adminTreasuryView.hero.h1Accent') }}</span>{{ t('adminTreasuryView.hero.h1b') }}</h1>
        <p class="at-lead">
          {{ t('adminTreasuryView.hero.lead') }}
        </p>

        <!-- Toolbar inside hero -->
        <div class="at-toolbar">
          <!-- Period chips -->
          <div class="at-toolbar-group">
            <span class="at-toolbar-label">{{ t('adminTreasuryView.toolbar.period') }}</span>
            <button
              v-for="p in PERIODS" :key="p.value"
              class="at-period-btn"
              :class="{ 'at-period-btn--active': period === p.value }"
              :disabled="loading"
              @click="setPeriod(p.value)"
            >{{ p.label }}</button>
          </div>

          <!-- Frame switch (§FEDEVENTS): LOCAL + connected console sessions only —
               no hardcoded letters, correct on any deployment (hetzner incl.). -->
          <div class="at-toolbar-group">
            <span class="at-toolbar-label">{{ t('adminTreasuryView.toolbar.frame') }}</span>
            <div class="at-frame-switch">
              <button
                v-for="o in selectableFrames"
                :key="o.key"
                class="at-frame-btn"
                :class="{ 'at-frame-btn--active': frame === o.key }"
                :disabled="loading"
                :title="o.isLocal ? `${o.label} — this registry` : `${o.label} — connected sibling frame`"
                @click="setFrame(o.key)"
              >
                <span class="at-frame-dot" :style="{ background: o.accentHex, boxShadow: `0 0 6px ${o.accentHex}99` }"></span>{{ o.isLocal ? o.label : o.key }}
              </button>
            </div>
          </div>

          <span class="at-toolbar-spacer"></span>

          <!-- Mint button (P1, 2026-05-08) — admin_treasury gated.
               Opens ConfirmActionModal that calls the LOCAL registry's /teg/treasury/mint.
               §2026-07-06 — shown on ANY sovereign mainframe (A/B/C), not Frame A only:
               the backend gate is `_mainframe_only_dep`, so every mainframe can mint its
               own currency. Gate is now `isLocalFrameSel` (the selected frame must be THIS
               registry's own frame — you mint your own frame, never a foreign one) AND
               `canMintAvt` (= isMainframe; cloud-ops have MINTING_AUTHORITY=disabled and
               the backend 503's them, so they never see it). -->
          <button
            v-if="activeTab === 'overview' && isLocalFrameSel && authStore.isAdmin && canMintAvt"
            class="at-btn at-btn--mint"
            @click="openMintModal"
            :title="tp('adminTreasuryView.mintAvtTitle', 'Issue new {unit} (admin_treasury)', { unit: frameCurrency })"
          >
            <span class="at-btn-glyph">＋</span>
            {{ tp('adminTreasuryView.mintAvt', 'Issue {unit}', { unit: frameCurrency }) }}
          </button>

          <!-- §FEPARITY-R3 — Return to treasury (`/teg/treasury/receive`). The ONLY rail
               for moving funds back: the treasury is a system account, so a plain
               /teg/transfer to its DID 404s (PART 5). Deliberately NOT gated on
               canMintAvt — this moves value that already exists (Δ-neutral) rather than
               minting, and the backend asks only for the admin_treasury flag, so a
               cloud-op with no minting authority can still claw funds back. -->
          <button
            v-if="activeTab === 'overview' && isLocalFrameSel && authStore.isAdmin"
            class="at-btn at-btn--return"
            @click="openReceiveModal"
            :title="t('adminTreasuryView.returnToTreasuryTitle', 'Return funds from an agent to the treasury (dispute slash, penalty, clawback)')"
            data-tour="treasury-return"
          >
            <span class="at-btn-glyph">↩</span>
            {{ t('adminTreasuryView.returnToTreasury', 'Return to Treasury') }}
          </button>

          <!-- Auto-refresh toggle + last refresh -->
          <div class="at-toolbar-group">
            <label class="at-toggle">
              <input type="checkbox" v-model="autoRefresh" />
              <span class="at-toggle-track"><span class="at-toggle-knob"></span></span>
              <span class="at-toggle-label">{{ t('common.autoRefresh60s') }}</span>
            </label>
          </div>
          <div class="at-toolbar-group at-toolbar-meta">
            <span class="at-toolbar-label">{{ t('common.last') }}</span>
            <span class="at-toolbar-val">{{ lastRefreshAt || '—' }}</span>
            <button class="at-btn at-btn--ghost" :disabled="loading" @click="refresh">↻</button>
          </div>
        </div>

        <!-- Tab bar (P1, 2026-05-08) — Overview / Fee Collector -->
        <div class="at-tabs">
          <button
            class="at-tab"
            :class="{ 'at-tab--active': activeTab === 'overview' }"
            @click="setTab('overview')"
          >
            <span class="at-tab-glyph">▤</span> {{ t('adminTreasuryView.tabs.overview') }}
          </button>
          <button
            class="at-tab"
            :class="{ 'at-tab--active': activeTab === 'fee-collector' }"
            @click="setTab('fee-collector')"
          >
            <span class="at-tab-glyph">⏣</span> {{ t('adminTreasuryView.tabs.feeCollector') }}
            <span v-if="feeData && feeCurrent && feeData.balance" class="at-tab-badge">
              {{ formatAvtCompact(feeData.balance) }}
            </span>
          </button>
          <button
            class="at-tab"
            :class="{ 'at-tab--active': activeTab === 'reward-policy' }"
            @click="setTab('reward-policy')"
          >
            <span class="at-tab-glyph"><Icon name="mdi:cog" /></span> {{ t('adminTreasuryView.tabs.rewardPolicy') }}
          </button>
        </div>
      </div>
    </section>

    <!-- Body -->
    <div class="at-body">
      <!-- Loading -->
      <!-- §FESUITE (V0578): what is drawn below answers the frame and period selected above, or is not drawn. A read for
           another frame (or period) that failed or was still out left the previous answer under the new button: one
           frame's treasury balance shown as another's. -->
      <div v-if="loading && !dataCurrent" class="at-center">
        <div class="at-spinner"></div>
        <p class="at-loading-text">Aggregating EventStore + TEG…</p>
      </div>

      <!-- Error -->
      <div v-else-if="error && !dataCurrent" class="at-center">
        <p class="at-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="at-btn at-btn--ghost" @click="refresh">{{ t('adminTreasuryView.error.retry') }}</button>
      </div>

      <!-- Content -->
      <template v-else-if="data && dataCurrent">
      <ReadFailedNotice v-if="error" dense data-testid="at-stale" :retry="refresh"
        :text="`The treasury could not be read just now. What follows is from the read at ${lastRefreshAt || 'an earlier time'}.`" />
      <!-- ── Overview tab content ── -->
      <div v-if="activeTab === 'overview'">
        <!-- Hero stats — 4 cards -->
        <div class="at-stats" data-tour="treasury-stats">
          <!-- Treasury Balance -->
          <div class="at-stat-card at-stat-card--lg">
            <div class="at-stat-key">{{ t('adminTreasuryView.stats.treasuryBalance') }}</div>
            <div v-if="data.treasury.balance !== null" class="at-stat-val at-stat-val--cyan">
              {{ formatAvt(data.treasury.balance) }}
              <span class="at-stat-unit">{{ frameCurrency }}</span>
            </div>
            <div v-else class="at-stat-val at-stat-val--muted">—</div>
            <div class="at-stat-sub" :title="data.treasury.treasury_did || ''">
              <template v-if="data.treasury.balance !== null">
                <code>{{ shortDid(data.treasury.treasury_did) }}</code>
              </template>
              <template v-else>
                {{ data.treasury.error || t('adminTreasuryView.unavailable') }}
              </template>
            </div>
          </div>

          <!-- Total Minted (window) -->
          <div class="at-stat-card">
            <div class="at-stat-key">{{ t('adminTreasuryView.stats.minted') }} · {{ periodLabel }}</div>
            <div class="at-stat-val at-stat-val--green">
              {{ formatAvt(data.totals_in_window.minted) }}
              <span class="at-stat-unit">{{ frameCurrency }}</span>
            </div>
            <div class="at-stat-sub">
              {{ t('adminTreasuryView.events', { n: data.totals_in_window.mint_count }) }}
              <span v-if="data.totals_in_window.mint_truncated" class="at-stat-warn"> · {{ t('adminTreasuryView.truncated') }}</span>
            </div>
          </div>

          <!-- Fees Collected (window) -->
          <div class="at-stat-card">
            <div class="at-stat-key">{{ t('adminTreasuryView.stats.fees') }} · {{ periodLabel }}</div>
            <div class="at-stat-val at-stat-val--violet">
              {{ formatAvt(data.totals_in_window.fees_collected) }}
              <span class="at-stat-unit">{{ frameCurrency }}</span>
            </div>
            <div class="at-stat-sub">
              {{ t('adminTreasuryView.events', { n: data.totals_in_window.fee_count }) }}
              <span v-if="data.totals_in_window.fee_truncated" class="at-stat-warn"> · {{ t('adminTreasuryView.truncated') }}</span>
            </div>
          </div>

          <!-- Supply Invariant Δ -->
          <div class="at-stat-card">
            <div class="at-stat-key">{{ t('adminTreasuryView.stats.supplyInvariant') }}</div>
            <div class="at-stat-val" :class="invariantValClass">
              {{ formatDelta(data.supply_audit.delta) }}
            </div>
            <div class="at-stat-sub">
              <span class="at-stat-pill" :class="invariantPillClass">
                {{ data.supply_audit.status || '—' }}
              </span>
              ·
              <span>{{ t('adminTreasuryView.agentsTracked', { n: data.supply_audit.agent_count ?? '—' }) }}</span>
            </div>
          </div>
        </div>

        <!-- Sparkline -->
        <div class="at-section">
          <div class="at-section-head">
            <span class="at-section-title">{{ t('adminTreasuryView.flow') }} · {{ periodLabel }}</span>
            <div class="at-legend">
              <span class="at-legend-item">
                <span class="at-legend-dot at-legend-dot--green"></span>{{ t('adminTreasuryView.legend.minted') }}
              </span>
              <span class="at-legend-item">
                <span class="at-legend-dot at-legend-dot--violet"></span>{{ t('adminTreasuryView.legend.fees') }}
              </span>
            </div>
          </div>
          <div class="at-spark-wrap">
            <svg
              v-if="data.sparkline.length"
              :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
              class="at-spark"
              preserveAspectRatio="none"
              role="img"
              aria-label="Issuance and fee flow chart"
            >
              <!-- Y-axis grid lines -->
              <g class="at-spark-grid">
                <line v-for="g in 4" :key="`g-${g}`"
                  :x1="0" :x2="SPARK_W"
                  :y1="(SPARK_H / 4) * g" :y2="(SPARK_H / 4) * g" />
              </g>
              <!-- Mint area -->
              <path
                v-if="mintPath"
                :d="mintPath.area"
                class="at-spark-area at-spark-area--green"
              />
              <!-- Fee area -->
              <path
                v-if="feePath"
                :d="feePath.area"
                class="at-spark-area at-spark-area--violet"
              />
              <!-- Mint line -->
              <path
                v-if="mintPath"
                :d="mintPath.line"
                class="at-spark-line at-spark-line--green"
              />
              <!-- Fee line -->
              <path
                v-if="feePath"
                :d="feePath.line"
                class="at-spark-line at-spark-line--violet"
              />
              <!-- Bucket markers (hover hooks) -->
              <g class="at-spark-markers">
                <rect
                  v-for="(p, i) in data.sparkline" :key="`m-${i}`"
                  :x="(SPARK_W / data.sparkline.length) * i"
                  :y="0"
                  :width="SPARK_W / data.sparkline.length"
                  :height="SPARK_H"
                  fill="transparent"
                  @mouseenter="hoverBucket = i"
                  @mouseleave="hoverBucket = null"
                />
              </g>
              <!-- Hover line + tooltip target -->
              <line
                v-if="hoverBucket !== null"
                :x1="(SPARK_W / data.sparkline.length) * (hoverBucket + 0.5)"
                :x2="(SPARK_W / data.sparkline.length) * (hoverBucket + 0.5)"
                :y1="0" :y2="SPARK_H"
                class="at-spark-hover"
              />
            </svg>
            <div v-else class="at-spark-empty">{{ t('adminTreasuryView.noDataInWindow') }}</div>
            <!-- Hover tooltip -->
            <div
              v-if="hoverBucket !== null && data.sparkline[hoverBucket]"
              class="at-spark-tooltip"
              :style="tooltipStyle"
            >
              <div class="at-tt-time">{{ formatBucketTime(data.sparkline[hoverBucket].t) }}</div>
              <div class="at-tt-row">
                <span class="at-legend-dot at-legend-dot--green"></span>
                {{ formatAvt(data.sparkline[hoverBucket].minted) }} {{ t('adminTreasuryView.legend.minted').toLowerCase() }}
              </div>
              <div class="at-tt-row">
                <span class="at-legend-dot at-legend-dot--violet"></span>
                {{ formatAvt(data.sparkline[hoverBucket].fees) }} {{ t('adminTreasuryView.legend.fees').toLowerCase() }}
              </div>
            </div>
          </div>
        </div>

        <!-- Two-column: Reasons + Top Fee Payers -->
        <div class="at-twocol">
          <!-- Mints by reason -->
          <div class="at-section">
            <div class="at-section-head">
              <span class="at-section-title">{{ t('adminTreasuryView.sections.mintsByReason') }} · {{ periodLabel }}</span>
            </div>
            <div v-if="reasonRows.length" class="at-reason-list">
              <div v-for="r in reasonRows" :key="r.reason" class="at-reason-row">
                <span class="at-reason-label">{{ r.reason }}</span>
                <span class="at-reason-bar">
                  <span
                    class="at-reason-bar-fill"
                    :style="{ width: r.pct + '%' }"
                  ></span>
                </span>
                <span class="at-reason-val">{{ formatAvt(r.amount) }}</span>
                <span class="at-reason-pct">{{ r.pct.toFixed(1) }}%</span>
              </div>
            </div>
            <div v-else class="at-empty-mini">{{ t('adminTreasuryView.empty.noMintsWindow') }}</div>
          </div>

          <!-- Top fee payers -->
          <div class="at-section">
            <div class="at-section-head">
              <span class="at-section-title">{{ t('adminTreasuryView.sections.topFeePayers') }} · {{ periodLabel }}</span>
            </div>
            <div v-if="data.top_fee_payers.length" class="at-payer-list">
              <div v-for="(p, i) in data.top_fee_payers" :key="p.agent_did" class="at-payer-row">
                <span class="at-payer-rank">#{{ i + 1 }}</span>
                <code class="at-payer-did" :title="p.agent_did">{{ shortDid(p.agent_did) }}</code>
                <span class="at-payer-tx">{{ t('adminTreasuryView.txCount', { n: p.tx_count }) }}</span>
                <span class="at-payer-fee">{{ formatAvt(p.total_fees) }}</span>
                <button
                  class="at-icon-btn"
                  @click="copyText(p.agent_did)"
                  title="Copy agent DID"
                >⎘</button>
                <button
                  class="at-icon-btn"
                  @click="goToEventStoreAggregate(p.agent_did)"
                  title="Open this agent's events in EventStore Explorer"
                >⤴</button>
              </div>
            </div>
            <div v-else class="at-empty-mini">{{ t('adminTreasuryView.empty.noFeeEvents') }}</div>
          </div>
        </div>

        <!-- Recent mints -->
        <div class="at-section">
          <div class="at-section-head">
            <span class="at-section-title">{{ t('adminTreasuryView.sections.recentMints') }}</span>
            <span class="at-section-sub">{{ t('adminTreasuryView.recentMintsSub') }}</span>
          </div>
          <div v-if="data.recent_mints.length" class="at-mint-list">
            <div v-for="m in data.recent_mints" :key="m.id || m.transaction_id || m.timestamp" class="at-mint-row">
              <span class="at-mint-time" :title="m.timestamp">{{ formatHHMMSS(m.timestamp) }}</span>
              <span class="at-mint-date">{{ formatDate(m.timestamp) }}</span>
              <span class="at-mint-reason-pill" :class="reasonPillClass(m.reason)">{{ m.reason || '—' }}</span>
              <span class="at-mint-amount">+{{ formatAvt(m.amount) }} <span class="at-mint-amount-unit">{{ frameCurrency }}</span></span>
              <code class="at-mint-recipient" :title="m.agent_did || ''">{{ shortDid(m.agent_did) }}</code>
              <span class="at-mint-spacer"></span>
              <button
                v-if="m.id"
                class="at-icon-btn"
                @click="copyText(m.id)"
                title="Copy event ID"
              >⎘</button>
              <button
                v-if="m.agent_did"
                class="at-icon-btn"
                @click="goToEventStoreAggregate(m.agent_did)"
                title="Open recipient's events in EventStore Explorer"
              >⤴</button>
            </div>
          </div>
          <div v-else class="at-empty-mini">{{ t('adminTreasuryView.empty.noMintsWindow') }}</div>
        </div>

        <!-- Footer info -->
        <div class="at-footer">
          <code>/admin/treasury/aggregate?period={{ data.period }}&amp;frame={{ data.frame }}</code>
          <span> · as of {{ formatAbs(data.as_of) }}</span>
          <span v-if="data.totals_in_window.mint_truncated || data.totals_in_window.fee_truncated">
             · <span class="at-stat-warn">window truncated — older events may be excluded</span>
          </span>
        </div>
      </div><!-- /Overview -->

      <!-- ── Fee Collector tab content (P1, 2026-05-08) ── -->
      <div v-else-if="activeTab === 'fee-collector'">
        <div v-if="foreignNotConnected" class="at-banner at-banner--info">
          <span class="at-banner-glyph"><Icon name="mdi:lock" /></span>
          <div class="at-banner-text">
            {{ selectedOption.label }} is a foreign sovereign frame. Connect its admin in
            <strong>Settings → Multi-Frame Console</strong> to view its fee collector here.
          </div>
        </div>

        <template v-else>
          <!-- Loading -->
          <div v-if="feeLoading && !feeCurrent" class="at-center">
            <div class="at-spinner"></div>
            <p class="at-loading-text">{{ t('adminTreasuryView.loadingFeeCollector') }}</p>
          </div>
          <div v-else-if="feeError && !feeCurrent" class="at-center">
            <p class="at-error-text"><Icon name="mdi:alert" /> {{ feeError }}</p>
            <button class="at-btn at-btn--ghost" @click="refreshFees">{{ t('adminTreasuryView.retry') }}</button>
          </div>

          <template v-else-if="feeData && feeCurrent">
            <ReadFailedNotice v-if="feeError" dense data-testid="at-fee-stale" :retry="refreshFees"
              text="The fee collector could not be read just now. What follows is from its last read that answered." />
            <!-- Hero stat cards (3) -->
            <div class="at-stats at-stats--3">
              <div class="at-stat-card at-stat-card--lg">
                <div class="at-stat-key">{{ t('adminTreasuryView.stats.feeCollectorBalance') }}</div>
                <div v-if="feeData.balance" class="at-stat-val at-stat-val--violet">
                  {{ formatAvt(feeData.balance) }}
                  <span class="at-stat-unit">{{ frameCurrency }}</span>
                </div>
                <div v-else class="at-stat-val at-stat-val--muted">—</div>
                <div class="at-stat-sub" :title="feeData.fee_collector_did || ''">
                  <template v-if="feeData.fee_collector_did">
                    <code>{{ feeData.fee_collector_did }}</code>
                  </template>
                  <template v-else-if="feeData.teg_error">
                    {{ feeData.teg_error }}
                  </template>
                </div>
              </div>

              <div class="at-stat-card">
                <div class="at-stat-key">{{ t('adminTreasuryView.stats.inflow') }} · {{ periodLabel }}</div>
                <div class="at-stat-val at-stat-val--cyan">
                  +{{ formatAvt(feeData.totals_in_window.inflow) }}
                  <span class="at-stat-unit">{{ frameCurrency }}</span>
                </div>
                <div class="at-stat-sub">
                  {{ t('adminTreasuryView.feeEvents', { n: feeData.totals_in_window.fee_count }) }}
                  <span v-if="feeData.totals_in_window.fee_truncated" class="at-stat-warn"> · {{ t('adminTreasuryView.truncated') }}</span>
                </div>
              </div>

              <div class="at-stat-card">
                <div class="at-stat-key">{{ t('adminTreasuryView.stats.distribute') }}</div>
                <button
                  v-if="authStore.isAdmin"
                  class="at-btn at-btn--primary at-btn--xl"
                  :disabled="!feeData.balance || feeData.balance === '0'"
                  @click="openDistributeModal"
                  :title="`Move ${frameCurrency} from fee_collector to a target agent`"
                >
                  <span class="at-btn-glyph">→</span>
                  {{ t('adminTreasuryView.distributeFromPool') }}
                </button>
                <div class="at-stat-sub">
                  Phase 2 will automate this via the funding waterfall —
                  this manual control remains for ops.
                </div>
              </div>
            </div>

            <!-- Inflow sparkline -->
            <div class="at-section">
              <div class="at-section-head">
                <span class="at-section-title">{{ t('adminTreasuryView.sections.feeInflow') }} · {{ periodLabel }}</span>
                <span class="at-section-sub">{{ t('adminTreasuryView.feeInflowSub') }}</span>
              </div>
              <div class="at-spark-wrap">
                <svg
                  v-if="feeData.sparkline.length"
                  :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
                  class="at-spark"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label="Fee inflow chart"
                >
                  <g class="at-spark-grid">
                    <line v-for="g in 4" :key="`fg-${g}`"
                      :x1="0" :x2="SPARK_W"
                      :y1="(SPARK_H / 4) * g" :y2="(SPARK_H / 4) * g" />
                  </g>
                  <g v-if="feeMaxBucket > 0">
                    <rect
                      v-for="(p, i) in feeData.sparkline" :key="`fb-${i}`"
                      :x="(SPARK_W / feeData.sparkline.length) * i + 1"
                      :y="SPARK_H - (parseFloat(p.amount) / feeMaxBucket) * (SPARK_H - 4) - 2"
                      :width="(SPARK_W / feeData.sparkline.length) - 2"
                      :height="(parseFloat(p.amount) / feeMaxBucket) * (SPARK_H - 4)"
                      class="at-spark-bar"
                    />
                  </g>
                </svg>
                <div v-else-if="feeMaxBucket === 0 && feeData.sparkline.length" class="at-spark-empty">
                  {{ t('adminTreasuryView.empty.noFeesInWindow') }}
                </div>
              </div>
            </div>

            <!-- Recent fee events -->
            <div class="at-section">
              <div class="at-section-head">
                <span class="at-section-title">{{ t('adminTreasuryView.sections.recentFees') }}</span>
                <span class="at-section-sub">{{ t('adminTreasuryView.recentFeesSub', { n: feeData.recent.length }) }}</span>
              </div>
              <div v-if="feeData.recent.length" class="at-mint-list">
                <div v-for="r in feeData.recent" :key="r.id || r.transaction_id || r.timestamp" class="at-mint-row">
                  <span class="at-mint-time" :title="r.timestamp || ''">{{ formatHHMMSS(r.timestamp) }}</span>
                  <span class="at-mint-date">{{ formatDate(r.timestamp) }}</span>
                  <span v-if="r.fee_type" class="at-mint-reason-pill at-mint-reason-pill--cyan">{{ r.fee_type }}</span>
                  <span class="at-mint-amount">+{{ formatAvt(r.fee_amount) }} <span class="at-mint-amount-unit">{{ frameCurrency }}</span></span>
                  <code class="at-mint-recipient" :title="r.payer_did">{{ shortDid(r.payer_did) }}</code>
                  <span class="at-mint-spacer"></span>
                  <button
                    v-if="r.id"
                    class="at-icon-btn"
                    @click="copyText(r.id)"
                    title="Copy event ID"
                  >⎘</button>
                  <button
                    v-if="r.payer_did && r.payer_did !== 'unknown'"
                    class="at-icon-btn"
                    @click="goToEventStoreAggregate(r.payer_did)"
                    title="Open payer's events in EventStore Explorer"
                  >⤴</button>
                </div>
              </div>
              <div v-else class="at-empty-mini">{{ t('adminTreasuryView.empty.noFeesInWindow') }}</div>
            </div>

            <div class="at-footer">
              <code>/admin/fee-collector/info?period={{ feeData.period }}</code>
              <span> · as of {{ formatAbs(feeData.as_of) }}</span>
            </div>
          </template>
        </template>
      </div><!-- /Fee Collector -->

      <!-- ── Funding Policy tab content (P3, 2026-05-08) ── -->
      <div v-else-if="activeTab === 'reward-policy'">
        <div class="at-banner at-banner--info">
          <span class="at-banner-glyph"><Icon name="mdi:lightning-bolt" /></span>
          <div class="at-banner-text">
            <strong>Funding waterfall</strong> — when a grant or award is paid,
            the TEG drains sources in the configured order. Default
            <code>fee_collector → treasury</code> means fees are spent first; treasury
            tops up only when the fee pool is empty. Per-reason overrides let you
            handle e.g. dispute_compensation differently from manual_payout.
            The TEG <strong>never issues units on its own</strong> — when both sources are
            exhausted, distribution returns "exhausted" and the caller decides.
          </div>
        </div>

        <div v-if="policyLoading && !policyData" class="at-center">
          <div class="at-spinner"></div>
          <p class="at-loading-text">Loading the funding policy…</p>
        </div>
        <div v-else-if="policyError && !policyData" class="at-center">
          <p class="at-error-text"><Icon name="mdi:alert" /> {{ policyError }}</p>
          <button class="at-btn at-btn--ghost" @click="refreshPolicy">Retry</button>
        </div>

        <template v-else-if="policyData">
          <div class="at-section">
            <div class="at-section-head">
              <span class="at-section-title">CURRENT POLICY</span>
              <span class="at-section-sub">{{ Object.keys(policyData.policy).length }} reasons configured</span>
            </div>

            <div class="at-policy-grid">
              <div class="at-policy-row at-policy-row--head">
                <span>REASON</span>
                <span>WATERFALL</span>
                <span>ACTIONS</span>
              </div>
              <div
                v-for="reason in sortedPolicyReasons" :key="reason"
                class="at-policy-row"
                :class="{ 'at-policy-row--default': reason === 'default' }"
              >
                <code class="at-policy-reason">{{ reason }}</code>
                <span class="at-policy-waterfall">
                  <span
                    v-for="(source, i) in policyData.policy[reason]" :key="`${reason}-${i}-${source}`"
                    class="at-policy-source"
                    :class="`at-policy-source--${source}`"
                  >
                    {{ source }}
                  </span>
                  <span v-if="(policyData.policy[reason] || []).length === 1" class="at-policy-note">
                    only this source — exhaustion blocks distribution
                  </span>
                </span>
                <span class="at-policy-actions">
                  <button
                    class="at-btn at-btn--ghost"
                    :disabled="!authStore.isAdmin"
                    @click="openEditPolicyModal(reason)"
                    :title="authStore.isAdmin ? 'Edit waterfall for this reason' : 'admin_treasury required'"
                  >Edit</button>
                  <button
                    v-if="reason !== 'default'"
                    class="at-btn at-btn--ghost"
                    :disabled="!authStore.isAdmin"
                    @click="openResetConfirm(reason)"
                    title="Remove this reason (falls back to default)"
                  >Reset</button>
                </span>
              </div>
            </div>

            <div class="at-policy-foot">
              <button
                class="at-btn at-btn--primary"
                :disabled="!authStore.isAdmin"
                @click="openEditPolicyModal(null)"
              >
                <span class="at-btn-glyph">＋</span>
                Add reason override
              </button>
            </div>
          </div>

          <div class="at-section">
            <div class="at-section-head">
              <span class="at-section-title">VALID SOURCES</span>
            </div>
            <div class="at-policy-sources-list">
              <div class="at-policy-source-card">
                <span class="at-policy-source at-policy-source--fee_collector">fee_collector</span>
                <p class="at-policy-source-desc">
                  Accumulated transfer fees (<code>{{ feeData?.fee_collector_did || 'teg:system:fee_collector' }}</code>).
                  Drained first by default. <strong>Recycles</strong> existing units — no inflation.
                </p>
              </div>
              <div class="at-policy-source-card">
                <span class="at-policy-source at-policy-source--treasury">treasury</span>
                <p class="at-policy-source-desc">
                  System treasury (<code>did:theprotocol:teg_system_treasury</code>).
                  Used as fallback when fee pool is empty. Pre-funded supply; depletes over time.
                </p>
              </div>
            </div>
          </div>
        </template>
      </div><!-- /Reward Policy -->
      </template>
    </div>

    <!-- ── Mint AVT modal (P1, custom inline) ── -->
    <Teleport to="body">
      <div v-if="showMintModal" class="at-modal-overlay" @click.self="closeMintModal">
        <div class="at-modal" role="dialog" aria-modal="true" aria-labelledby="at-mint-title">
          <div class="at-modal-head">
            <span id="at-mint-title" class="at-modal-title">{{ tp('adminTreasuryView.mintModal.title', 'Issue new {unit}', { unit: frameCurrency }) }}</span>
            <button class="at-modal-close" :disabled="mintBusy" @click="closeMintModal" aria-label="Close">✕</button>
          </div>
          <div class="at-modal-body">
            <p class="at-modal-msg">
              Issue new {{ frameCurrency }} from void via TEG <code>/admin/token/issue</code>. Registry emits the
              <code>TokensIssued</code> event. Authorized for the <code>admin_treasury</code> flag.
            </p>

            <label class="at-form-label">Target agent DID</label>
            <input
              v-model.trim="mintForm.targetDid"
              type="text"
              placeholder="did:theprotocol:..."
              class="at-form-input"
              :disabled="mintBusy"
              autofocus
            />

            <label class="at-form-label">Amount ({{ frameCurrency }})</label>
            <input
              v-model.trim="mintForm.amount"
              type="text"
              placeholder="100"
              class="at-form-input"
              :disabled="mintBusy"
            />

            <label for="admintreasury-sel-696" class="at-form-label">Reason</label>
            <select id="admintreasury-sel-696" v-model="mintForm.reason" class="at-form-input" :disabled="mintBusy">
              <option value="admin_grant">admin_grant</option>
              <option value="dispute_compensation">dispute_compensation</option>
              <option value="audit_correction">audit_correction</option>
              <option value="genesis_grant">genesis_grant</option>
            </select>

            <p v-if="mintForm.amount && parseFloat(mintForm.amount) > 100000" class="at-form-warn">
              <Icon name="mdi:alert" /> Amount &gt; 100,000 {{ frameCurrency }} — double-check before confirming.
            </p>
            <!-- §pass71.5 — inline error anchored to the action; clearer than a fly-away toast -->
            <p v-if="mintError" class="at-form-error" role="alert">
              <strong>Issuance failed.</strong> {{ mintError }}
            </p>
          </div>
          <div class="at-modal-foot">
            <button class="at-btn at-btn--ghost" :disabled="mintBusy" @click="closeMintModal">{{ t('adminTreasuryView.mintModal.cancel') }}</button>
            <button class="at-btn at-btn--primary" :disabled="mintBusy || !canSubmitMint" @click="executeMint">
              <span v-if="mintBusy" class="at-btn-spinner"></span>
              {{ mintBusy ? t('adminTreasuryView.mintModal.busy') : t('adminTreasuryView.mintModal.submit') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── §FEPARITY-R3: Return to Treasury modal ── -->
    <Teleport to="body">
      <div v-if="showReceiveModal" class="at-modal-overlay" @click.self="closeReceiveModal">
        <div class="at-modal" role="dialog" aria-modal="true" aria-labelledby="at-recv-title">
          <div class="at-modal-head">
            <span id="at-recv-title" class="at-modal-title">{{ t('adminTreasuryView.returnToTreasury', 'Return to Treasury') }}</span>
            <button class="at-modal-close" :disabled="receiveBusy" @click="closeReceiveModal" aria-label="Close">✕</button>
          </div>
          <div class="at-modal-body">
            <p class="at-modal-msg">
              Move {{ frameCurrency }} <strong>from an agent back to the treasury</strong> via
              <code>/teg/treasury/receive</code>. This is the only rail for it — the treasury is a
              system account, so a plain transfer to its DID fails. Both sides are already in
              circulation, so this is supply-neutral (it moves value, it does not burn it).
            </p>

            <label class="at-form-label">Source agent DID</label>
            <input
              v-model.trim="receiveForm.sourceDid"
              type="text"
              placeholder="did:theprotocol:..."
              class="at-form-input"
              :disabled="receiveBusy"
              autofocus
            />

            <label class="at-form-label">Amount ({{ frameCurrency }})</label>
            <input
              v-model.trim="receiveForm.amount"
              type="text"
              placeholder="100"
              class="at-form-input"
              :disabled="receiveBusy"
            />

            <label for="admintreasury-sel-758" class="at-form-label">Reason</label>
            <select id="admintreasury-sel-758" v-model="receiveForm.reason" class="at-form-input" :disabled="receiveBusy">
              <option value="dispute_slash">dispute_slash</option>
              <option value="penalty">penalty</option>
              <option value="fee_collection">fee_collection</option>
              <option value="admin_clawback">admin_clawback</option>
            </select>

            <label class="at-form-label">Reference (optional — e.g. dispute id)</label>
            <input
              v-model.trim="receiveForm.referenceId"
              type="text"
              placeholder="dispute-1234"
              class="at-form-input"
              :disabled="receiveBusy"
            />

            <p v-if="receiveError" class="at-form-error" role="alert">
              <strong>Return failed.</strong> {{ receiveError }}
            </p>
          </div>
          <div class="at-modal-foot">
            <button class="at-btn at-btn--ghost" :disabled="receiveBusy" @click="closeReceiveModal">{{ t('adminTreasuryView.mintModal.cancel') }}</button>
            <button class="at-btn at-btn--primary" :disabled="receiveBusy || !canSubmitReceive" @click="executeReceive">
              <span v-if="receiveBusy" class="at-btn-spinner"></span>
              {{ receiveBusy ? 'Returning…' : 'Return to Treasury' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Funding Policy edit modal (P3, 2026-05-08) ── -->
    <Teleport to="body">
      <div v-if="showPolicyModal" class="at-modal-overlay" @click.self="closePolicyModal">
        <div class="at-modal" role="dialog" aria-modal="true" aria-labelledby="at-policy-title">
          <div class="at-modal-head">
            <span id="at-policy-title" class="at-modal-title">
              {{ policyForm.editingReason ? `Edit waterfall: ${policyForm.editingReason}` : t('adminTreasuryView.policyModal.addOverride') }}
            </span>
            <button class="at-modal-close" :disabled="policyBusy" @click="closePolicyModal" aria-label="Close">✕</button>
          </div>
          <div class="at-modal-body">
            <p class="at-modal-msg">
              Configure the source order. The TEG drains the first source until empty,
              then falls to the next. Drag-free editor — toggle each source.
            </p>

            <label class="at-form-label">Reason</label>
            <input
              v-if="!policyForm.editingReason"
              v-model.trim="policyForm.reason"
              type="text"
              placeholder="e.g. achievement, dispute_compensation, manual_payout"
              class="at-form-input"
              :disabled="policyBusy"
              autofocus
            />
            <input
              v-else
              :value="policyForm.editingReason"
              type="text"
              class="at-form-input"
              disabled
            />

            <label class="at-form-label">Source order (drag to reorder, click to toggle)</label>
            <div class="at-policy-source-builder">
              <button
                v-for="(source, i) in policyForm.sources" :key="`${source}-${i}`"
                class="at-policy-source-pill at-policy-source-pill--active"
                :class="`at-policy-source--${source}`"
                @click="removeSourceFromForm(i)"
                :disabled="policyBusy"
                :title="`Remove ${source} from waterfall`"
              >
                {{ i + 1 }}. {{ source }}
                <span class="at-policy-source-x">✕</span>
              </button>
            </div>
            <div class="at-policy-source-builder">
              <button
                v-for="source in availableSourcesForForm" :key="`add-${source}`"
                class="at-policy-source-pill"
                :class="`at-policy-source--${source}`"
                @click="addSourceToForm(source)"
                :disabled="policyBusy"
              >
                ＋ {{ source }}
              </button>
            </div>

            <p v-if="policyForm.sources.length === 0" class="at-form-warn">
              <Icon name="mdi:alert" /> Select at least one source.
            </p>
          </div>
          <div class="at-modal-foot">
            <button class="at-btn at-btn--ghost" :disabled="policyBusy" @click="closePolicyModal">Cancel</button>
            <button class="at-btn at-btn--primary" :disabled="policyBusy || !canSavePolicy" @click="savePolicy">
              <span v-if="policyBusy" class="at-btn-spinner"></span>
              {{ policyBusy ? 'Saving…' : 'Save policy' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Distribute from fee_collector modal (P1, custom inline) ── -->
    <Teleport to="body">
      <div v-if="showDistributeModal" class="at-modal-overlay" @click.self="closeDistributeModal">
        <div class="at-modal" role="dialog" aria-modal="true" aria-labelledby="at-distribute-title">
          <div class="at-modal-head">
            <span id="at-distribute-title" class="at-modal-title">{{ t('adminTreasuryView.distributeModal.title') }}</span>
            <button class="at-modal-close" :disabled="distributeBusy" @click="closeDistributeModal" aria-label="Close">✕</button>
          </div>
          <div class="at-modal-body">
            <p class="at-modal-msg">
              Move {{ frameCurrency }} from <code>{{ feeData?.fee_collector_did || 'fee_collector' }}</code>
              → target agent. Pool balance:
              <strong>{{ feeData?.balance ? formatAvt(feeData.balance) : '?' }} {{ frameCurrency }}</strong>.
              Authorized for <code>admin_treasury</code>.
            </p>

            <label class="at-form-label">Target agent DID</label>
            <input
              v-model.trim="distributeForm.targetDid"
              type="text"
              placeholder="did:theprotocol:..."
              class="at-form-input"
              :disabled="distributeBusy"
              autofocus
            />

            <label class="at-form-label">Amount ({{ frameCurrency }})</label>
            <input
              v-model.trim="distributeForm.amount"
              type="text"
              placeholder="10"
              class="at-form-input"
              :disabled="distributeBusy"
            />

            <label for="admintreasury-sel-900" class="at-form-label">Reason</label>
            <select id="admintreasury-sel-900" v-model="distributeForm.reason" class="at-form-input" :disabled="distributeBusy">
              <option v-if="stakingRewardsOn" value="staking_reward">staking_reward</option>
              <option value="manual_payout">manual_payout</option>
              <option value="dispute_compensation">dispute_compensation</option>
              <option value="audit_correction">audit_correction</option>
              <option value="operator_share">operator_share</option>
            </select>

            <p v-if="feeData && distributeForm.amount && parseFloat(distributeForm.amount) > parseFloat(feeData.balance || '0')" class="at-form-warn">
              <Icon name="mdi:alert" /> Amount exceeds fee_collector balance ({{ formatAvt(feeData.balance) }} {{ frameCurrency }}).
            </p>
          </div>
          <div class="at-modal-foot">
            <button class="at-btn at-btn--ghost" :disabled="distributeBusy" @click="closeDistributeModal">{{ t('adminTreasuryView.distributeModal.cancel') }}</button>
            <button class="at-btn at-btn--primary" :disabled="distributeBusy || !canSubmitDistribute" @click="executeDistribute">
              <span v-if="distributeBusy" class="at-btn-spinner"></span>
              {{ distributeBusy ? t('adminTreasuryView.distributeModal.busy') : t('adminTreasuryView.distributeModal.submit') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Reset waterfall override confirmation (2026-05-08 polish) -->
    <ConfirmActionModal
      :show="!!resetConfirmReason"
      title="Reset waterfall override"
      :message="`The reason '${resetConfirmReason}' will fall back to the default waterfall. Existing payouts already routed through this override are unaffected.`"
      tone="warn"
      confirm-text="Reset to default"
      busy-text="Resetting…"
      :busy="resetConfirmBusy"
      @close="closeResetConfirm"
      @confirm="executeReset"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * AdminTreasury — Treasury & Fee Audit Dashboard
 *
 * Build #7 (2026-05-07) — strategy-doc next-batch milestone.
 * Backend: routers/admin_health.py:get_treasury_aggregate.
 *
 * Surfaces:
 *  - Live treasury balance (Frame A only — sovereign isolation for B)
 *  - Total minted + fees collected per period window
 *  - Supply invariant Δ + status (auditor service authoritative — should be 0.0)
 *  - Sparkline of mints + fees over time
 *  - Mints grouped by reason (admin_issuance / staking_reward / etc.)
 *  - Top 10 fee-paying agents
 *  - Recent mints with drilldown to EventStore Explorer
 *  - Period chips: 24h / 7d / 30d / All
 *  - Frame switch: A / B (precedent from Build #6.1)
 *  - Auto-refresh 60s, visibility-guarded
 */
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import {
  feeCollectorAdminService,
  type FeeCollectorInfo,
  type RewardFundingPolicy,
} from '@/services/api/feeCollectorAdmin'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
import { usePolledData } from '@/composables/usePolledData'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import {
  treasuryAdminService,
  type TreasuryAggregate,
  type TreasuryPeriod,
} from '@/services/api/treasuryAdmin'
import { useCurrency } from '@/composables/useCurrency'
import { useFrames } from '@/composables/useFrames'
import { useMultiFrameSession } from '@/stores/multiFrameSession'
import { useAdminFrames } from '@/composables/useAdminFrames'
import { LOCAL_FRAME } from '@/services/api/eventStoreAdmin'
import { peerGet } from '@/services/api/peer'
import { useRegistryConfig } from '@/composables/useRegistryConfig'

const uiStore = useUIStore()
const router = useRouter()
const authStore = useAuthStore()
const { localCurrency } = useCurrency()
// §2026-06-03 cross-frame Treasury: resolve "local vs foreign" by the registry's
// OWN frame and fetch a foreign frame's treasury via the Multi-Frame peer-proxy
// (that frame's own registry reports its local treasury correctly).
// §FEDEVENTS 2026-08-03: the frame picker is LOCAL + connected console sessions
// only (no hardcoded letters, no foreign default) — local reads use the `local`
// sentinel so any deployment (hetzner-frame incl.) resolves itself.
const { frames } = useFrames()
const mf = useMultiFrameSession()
const { selectableFrames, resolveOption } = useAdminFrames()
// §pass66 — Mint button only shows on mainframe (cloud-ops have MINTING_AUTHORITY=disabled)
const { canMintAvt } = usePermissions()

// ── P1 (2026-05-08) — tab state + fee collector + modals ──
// ── P3 (2026-05-08) — added 'reward-policy' tab ──
type TreasuryTab = 'overview' | 'fee-collector' | 'reward-policy'
const activeTab = ref<TreasuryTab>('overview')

const feeData = ref<FeeCollectorInfo | null>(null)
// §FESUITE (V0578): the frame and period the fee collector on screen answers (see dataKey)
const feeKey = ref<string | null>(null)
const feeLoading = ref(false)
const feeError = ref<string | null>(null)

const showMintModal = ref(false)
const mintBusy = ref(false)
const mintForm = ref({ targetDid: '', amount: '', reason: 'admin_grant' })
// §pass71.5 (2026-05-25) — inline mint error so a failed POST doesn't disappear
// into a fly-away toast (root cause of the §pass71.1 self-ban: user spam-clicked
// because the modal stayed open with no visible feedback). Cleared on next
// submit + on modal open.
const mintError = ref<string | null>(null)

const showDistributeModal = ref(false)
const distributeBusy = ref(false)
// a payout on locked units is offered only where the registry pays one (registry-config's staking_rewards_enabled; his
// word 2026-10-25: "staking doesnt exist anymore in the way it did"), so the form starts on a manual payout
const { config: treasuryRegistryCfg } = useRegistryConfig()
const stakingRewardsOn = computed(() => treasuryRegistryCfg.value.staking_rewards_enabled === true)
const distributeForm = ref({ targetDid: '', amount: '', reason: 'manual_payout' })

// ── P3 — funding policy state ──
const policyData = ref<RewardFundingPolicy | null>(null)
const policyLoading = ref(false)
const policyError = ref<string | null>(null)
const showPolicyModal = ref(false)
const policyBusy = ref(false)
const policyForm = ref<{ editingReason: string | null; reason: string; sources: string[] }>(
  { editingReason: null, reason: '', sources: [] }
)

// State
const data = ref<TreasuryAggregate | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const period = ref<TreasuryPeriod>('7d')
// §FEDEVENTS: the selected frame KEY — LOCAL_FRAME sentinel by default (the old
// uiStore-seeded 'A' + local-nudge watch could still land a letterless
// deployment on a mislabelled foreign default). Foreign keys are only ever
// selectable while their console session lives.
const frame = ref<string>(LOCAL_FRAME)
const selectedOption = computed(() => resolveOption(frame.value))
// §FESUITE (V0578): the frame and period the figures on screen answer. A read for another frame or period that failed
// (or was still out) left the previous answer under the new button: one frame's treasury balance shown as another's.
// The fee tab also skipped its read when it held any answer, so a frame changed on the Overview tab showed the old
// frame's fee collector when the tab was opened.
const selectionKey = computed(() => `${frame.value}|${period.value}`)
const dataKey = ref<string | null>(null)
const dataCurrent = computed(() => !!data.value && dataKey.value === selectionKey.value)
const feeCurrent = computed(() => !!feeData.value && feeKey.value === selectionKey.value)
// The unit label tracks the SELECTED frame's settlement currency. Local frame →
// the card-truth localCurrency; a foreign (connected) frame → its seed
// descriptor (e.g. C → BVT even when viewed from an AVT registry).
const frameCurrency = computed<string>(() => {
  if (selectedOption.value.isLocal) return localCurrency.value
  const f = frames.value.find((x) => x.key === selectedOption.value.key)
  return (f?.currency as string) || localCurrency.value
})
// Is the selected frame this registry's own frame? (Gates mint + read routing.)
const isLocalFrameSel = computed(() => selectedOption.value.isLocal)
// Foreign frame selected but its session vanished (stale selection) → connect
// prompt rather than attempting (and mislabelling) a cross-frame read.
const foreignNotConnected = computed(
  () => !isLocalFrameSel.value && !mf.adminTokenFor(selectedOption.value.key),
)
// If the selected foreign frame's session disconnects, fall back to local.
watch(selectableFrames, (opts) => {
  if (!opts.some((o) => o.key === frame.value) && frame.value !== LOCAL_FRAME) {
    frame.value = LOCAL_FRAME
  }
})
const autoRefresh = ref(true)
const hoverBucket = ref<number | null>(null)

const PERIODS = computed<{ value: TreasuryPeriod; label: string }[]>(() => [
  { value: '24h', label: t('adminTreasuryView.periods.24h') },
  { value: '7d',  label: t('adminTreasuryView.periods.7d') },
  { value: '30d', label: t('adminTreasuryView.periods.30d') },
  { value: 'all', label: t('adminTreasuryView.periods.all') },
])

const SPARK_W = 1000  // viewBox width
const SPARK_H = 140   // viewBox height

// Lifecycle (F adoption — usePolledData composable, 2026-05-08).
// Replaces hand-rolled setInterval + visibilityState block. The composable
// handles cleanup, visibility-guard, and on-visible-return refresh
// automatically. autoRefresh toggle still controlled inline via watch.
const polled = usePolledData(refresh, {
  interval: 60_000,
  immediate: true,        // fire on mount
  pauseWhenHidden: true,  // skip while tab hidden
  autoStart: true,        // start polling immediately
})
watch(autoRefresh, (on) => { on ? polled.resume() : polled.pause() })

// Re-fetch when period/frame changes
watch([period, frame], () => {
  void refresh()
})

async function refresh() {
  const asked = selectionKey.value
  loading.value = true
  error.value = null
  try {
    const opt = selectedOption.value
    let result: TreasuryAggregate
    if (opt.isLocal) {
      // Local frame → direct local-backend call with the `local` sentinel
      // (backend resolves its own EventStore + TEG treasury balance via
      // _is_local_frame() — no letter guessing on any deployment).
      result = await treasuryAdminService.aggregate(period.value, LOCAL_FRAME)
    } else {
      // Foreign sovereign frame → relay to THAT frame's own registry via the
      // same-origin Multi-Frame peer-proxy, using its session admin token. The
      // sibling registry resolves the requested frame as ITS OWN local frame and
      // returns the real treasury balance + supply (sovereign-correct — no shared
      // TEG keys, no cross-frame EventStore env reliance, which is what previously
      // mislabelled/blanked the balance when switching A/B/C). Requires the
      // operator to have connected that frame in Settings → Multi-Frame Console.
      const tok = mf.adminTokenFor(opt.key)
      if (!tok) {
        data.value = null
        dataKey.value = null
        error.value =
          `${opt.label} is a foreign sovereign frame. Connect its admin in ` +
          `Settings → Multi-Frame Console to view its treasury here.`
        return
      }
      result = await peerGet<TreasuryAggregate>(
        opt.key,
        'admin/treasury/aggregate',
        tok,
        { period: period.value, frame: opt.frameParam },
      )
    }
    data.value = result
    dataKey.value = asked
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Failed to load treasury data'
    error.value = msg
    uiStore.showError?.('Treasury', msg)
  } finally {
    loading.value = false
  }
}

function setPeriod(p: TreasuryPeriod) {
  if (period.value === p) return
  period.value = p
  hoverBucket.value = null
  // also refresh fee data so the period change is consistent across tabs
  if (activeTab.value === 'fee-collector') void refreshFees()
}

function setFrame(f: string) {
  if (frame.value === f) return
  frame.value = f
  // Cross-view frame memory (events view etc.), by frame key (§FEFRAME W2).
  uiStore.setActiveFrame(f)
  hoverBucket.value = null
  if (activeTab.value === 'fee-collector') void refreshFees()
}

function setTab(t: TreasuryTab) {
  if (activeTab.value === t) return
  activeTab.value = t
  // Lazy-load tab data the first time each is opened
  if (t === 'fee-collector' && !feeCurrent.value) void refreshFees()
  if (t === 'reward-policy' && !policyData.value) void refreshPolicy()
}

// ── Fee collector data fetch ──
async function refreshFees() {
  // §2026-06-03: the fee collector is sovereign-local (one per frame's TEG). Show
  // it for THIS registry's local frame directly; for a foreign frame relay to that
  // frame's own registry via the Multi-Frame peer-proxy (same pattern as the
  // overview treasury), so A/B/C each surface their real fee collector. A foreign
  // frame that isn't connected in the Multi-Frame Console shows a connect prompt.
  if (foreignNotConnected.value) {
    feeData.value = null
    feeKey.value = null
    feeError.value =
      `${selectedOption.value.label} is a foreign sovereign frame. Connect its ` +
      `admin in Settings → Multi-Frame Console to view its fee collector here.`
    return
  }
  const asked = selectionKey.value
  feeLoading.value = true
  feeError.value = null
  try {
    if (isLocalFrameSel.value) {
      feeData.value = await feeCollectorAdminService.info(period.value)
    } else {
      const tok = mf.adminTokenFor(selectedOption.value.key)!
      feeData.value = await peerGet<FeeCollectorInfo>(
        selectedOption.value.key, 'admin/fee-collector/info', tok, { period: period.value },
      )
    }
    feeKey.value = asked
  } catch (e: any) {
    feeError.value = e?.response?.data?.detail || e?.message || 'Failed to load fee_collector info'
    uiStore.showError?.('Fee Collector', feeError.value!)
  } finally {
    feeLoading.value = false
  }
}

// Sparkline max for fee inflow (separate from mint sparkline)
const feeMaxBucket = computed(() => {
  if (!feeData.value || !feeData.value.sparkline.length) return 0
  let max = 0
  for (const p of feeData.value.sparkline) {
    const v = parseFloat(p.amount) || 0
    if (v > max) max = v
  }
  return max
})

// Compact AVT formatter for the tab badge
function formatAvtCompact(v: string | null | undefined): string {
  if (!v) return '0'
  const n = parseFloat(v)
  if (Number.isNaN(n) || n === 0) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  if (n >= 1) return n.toFixed(0)
  return n.toFixed(2)
}

// ── Mint modal ──
const canSubmitMint = computed(() => {
  if (!mintForm.value.targetDid || !mintForm.value.amount) return false
  const n = parseFloat(mintForm.value.amount)
  return !Number.isNaN(n) && n > 0
})
const canSubmitDistribute = computed(() => {
  if (!distributeForm.value.targetDid || !distributeForm.value.amount) return false
  const n = parseFloat(distributeForm.value.amount)
  if (Number.isNaN(n) || n <= 0) return false
  if (feeData.value?.balance && n > parseFloat(feeData.value.balance)) return false
  return true
})
// ── §FEPARITY-R3: return funds to treasury ───────────────────────────────────
const showReceiveModal = ref(false)
const receiveBusy = ref(false)
const receiveError = ref<string | null>(null)
const receiveForm = ref({ sourceDid: '', amount: '', reason: 'dispute_slash', referenceId: '' })
const canSubmitReceive = computed(() => {
  const a = parseFloat(receiveForm.value.amount)
  return !!receiveForm.value.sourceDid && !Number.isNaN(a) && a > 0
})
function openReceiveModal() {
  receiveForm.value = { sourceDid: '', amount: '', reason: 'dispute_slash', referenceId: '' }
  receiveError.value = null
  showReceiveModal.value = true
}
function closeReceiveModal() {
  if (receiveBusy.value) return
  receiveError.value = null
  showReceiveModal.value = false
}
async function executeReceive() {
  receiveError.value = null
  if (!canSubmitReceive.value) {
    receiveError.value = 'Source DID and a positive amount are required.'
    return
  }
  receiveBusy.value = true
  try {
    const res = await feeCollectorAdminService.receive({
      source_agent_did: receiveForm.value.sourceDid,
      amount: receiveForm.value.amount,
      reason: receiveForm.value.reason,
      ...(receiveForm.value.referenceId ? { reference_id: receiveForm.value.referenceId } : {}),
    })
    uiStore.showSuccess?.(
      'Returned to treasury',
      `${receiveForm.value.amount} ${frameCurrency.value} ← ${shortDid(receiveForm.value.sourceDid)}${res?.transaction_id ? ` · tx ${String(res.transaction_id).slice(0, 8)}` : ''}`,
    )
    showReceiveModal.value = false
    void refresh()
  } catch (e: any) {
    // Same inline-error discipline as mint (§pass71.5): anchored to the action so a
    // failure never invites a spam-click.
    const status = e?.response?.status
    const detail = e?.response?.data?.detail || e?.message || 'Return failed'
    receiveError.value = status === 401
      ? '401 Unauthorized — session may have expired or the JWT lacks admin_treasury. Refresh the page (do NOT retry the same click).'
      : `HTTP ${status || '?'}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
  } finally {
    receiveBusy.value = false
  }
}

function openMintModal() {
  mintForm.value = { targetDid: '', amount: '', reason: 'admin_grant' }
  // §pass71.5 — clear stale error from a prior failed attempt when re-opening
  mintError.value = null
  showMintModal.value = true
}
function closeMintModal() {
  if (mintBusy.value) return
  mintError.value = null
  showMintModal.value = false
}
async function executeMint() {
  // §pass71.5 — clear any prior inline error on retry
  mintError.value = null
  if (!mintForm.value.targetDid || !mintForm.value.amount) {
    mintError.value = 'Target DID and amount are required.'
    return
  }
  const amt = parseFloat(mintForm.value.amount)
  if (Number.isNaN(amt) || amt <= 0) {
    mintError.value = 'Amount must be a positive number.'
    return
  }
  mintBusy.value = true
  try {
    const result = await feeCollectorAdminService.mint({
      target_agent_did: mintForm.value.targetDid,
      amount: mintForm.value.amount,
      reason: mintForm.value.reason,
    })
    uiStore.showSuccess?.(
      'Issuance complete',
      `${mintForm.value.amount} ${frameCurrency.value} → ${shortDid(mintForm.value.targetDid)} · tx ${result.transaction_id}`,
    )
    showMintModal.value = false
    // Refresh aggregate so the fresh mint shows up in Recent Mints
    void refresh()
  } catch (e: any) {
    // §pass71.5 — render error INLINE in the modal (not a fly-away toast that
    // gets buried under the still-open modal). This is the root-cause fix for
    // the §pass71.1 spam-click → CrowdSec self-ban: if the user sees a clear
    // error anchored to the action, they don't fat-finger the button N times.
    // Mirrored toast kept for screen-reader / off-screen accessibility.
    const status = e?.response?.status
    const detail = e?.response?.data?.detail || e?.message || 'Issuance failed'
    let humanized = `HTTP ${status || '?'}: ${detail}`
    if (status === 401) {
      humanized = '401 Unauthorized — your session may have expired or the developer JWT lacks the admin_treasury flag. Try refreshing the page (do NOT retry the same click)'
    } else if (status === 403) {
      humanized = `403 Forbidden — ${detail}`
    } else if (status === 503) {
      humanized = `503 — TEG unavailable: ${detail}`
    }
    mintError.value = humanized
    uiStore.showError?.('Issuance failed', humanized)
  } finally {
    mintBusy.value = false
  }
}

// ── Distribute modal ──
function openDistributeModal() {
  distributeForm.value = { targetDid: '', amount: '', reason: 'manual_payout' }
  showDistributeModal.value = true
}
function closeDistributeModal() {
  if (distributeBusy.value) return
  showDistributeModal.value = false
}
// ── P3 — Funding Policy tab ──
async function refreshPolicy() {
  policyLoading.value = true
  policyError.value = null
  try {
    policyData.value = await feeCollectorAdminService.getPolicy()
  } catch (e: any) {
    policyError.value = e?.response?.data?.detail || e?.message || 'Failed to load the funding policy'
    uiStore.showError?.('Funding Policy', policyError.value!)
  } finally {
    policyLoading.value = false
  }
}

const sortedPolicyReasons = computed<string[]>(() => {
  if (!policyData.value) return []
  // 'default' first, rest alphabetical
  const keys = Object.keys(policyData.value.policy)
  return ['default', ...keys.filter(k => k !== 'default').sort()]
})

const availableSourcesForForm = computed<string[]>(() => {
  const all = policyData.value?.valid_sources || ['fee_collector', 'treasury']
  return all.filter(s => !policyForm.value.sources.includes(s))
})

const canSavePolicy = computed(() => {
  const hasReason = policyForm.value.editingReason || policyForm.value.reason.trim().length > 0
  const hasSources = policyForm.value.sources.length > 0
  return hasReason && hasSources
})

function openEditPolicyModal(reason: string | null) {
  if (reason) {
    policyForm.value = {
      editingReason: reason,
      reason,
      sources: [...(policyData.value?.policy[reason] || [])],
    }
  } else {
    policyForm.value = { editingReason: null, reason: '', sources: [] }
  }
  showPolicyModal.value = true
}
function closePolicyModal() {
  if (policyBusy.value) return
  showPolicyModal.value = false
}
function addSourceToForm(source: string) {
  if (policyForm.value.sources.includes(source)) return
  policyForm.value.sources.push(source)
}
function removeSourceFromForm(idx: number) {
  policyForm.value.sources.splice(idx, 1)
}

async function savePolicy() {
  if (!policyData.value || !canSavePolicy.value) return
  const reasonKey = (policyForm.value.editingReason || policyForm.value.reason).trim()
  if (!reasonKey) return

  // Build the next policy dict (full replacement is what the backend takes).
  const nextPolicy: Record<string, string[]> = { ...policyData.value.policy }
  nextPolicy[reasonKey] = [...policyForm.value.sources]

  policyBusy.value = true
  try {
    const result = await feeCollectorAdminService.updatePolicy({ policy: nextPolicy })
    policyData.value = result
    uiStore.showSuccess?.('Saved', `Policy for "${reasonKey}" updated.`)
    showPolicyModal.value = false
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Failed to save policy'
    uiStore.showError?.('Save failed', msg)
  } finally {
    policyBusy.value = false
  }
}

// Reset-confirm modal state (2026-05-08 polish): reset is destructive in the
// sense that it discards the operator's chosen waterfall override and reverts
// to the default. Uses ConfirmActionModal (warn tone) for parity with the
// rest of the destructive admin surface.
const resetConfirmReason = ref<string | null>(null)
const resetConfirmBusy = ref(false)

function openResetConfirm(reason: string) {
  if (reason === 'default' || !policyData.value) return
  resetConfirmReason.value = reason
}
function closeResetConfirm() {
  if (resetConfirmBusy.value) return
  resetConfirmReason.value = null
}

async function executeReset() {
  const reason = resetConfirmReason.value
  if (!reason || reason === 'default' || !policyData.value) return
  resetConfirmBusy.value = true
  const nextPolicy: Record<string, string[]> = { ...policyData.value.policy }
  delete nextPolicy[reason]
  try {
    const result = await feeCollectorAdminService.updatePolicy({ policy: nextPolicy })
    policyData.value = result
    uiStore.showSuccess?.('Reset', `"${reason}" now uses the default waterfall.`)
    resetConfirmReason.value = null
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Failed to reset'
    uiStore.showError?.('Reset failed', msg)
  } finally {
    resetConfirmBusy.value = false
  }
}

async function executeDistribute() {
  if (!distributeForm.value.targetDid || !distributeForm.value.amount) {
    uiStore.showError?.('Distribute', 'Target DID and amount are required.')
    return
  }
  const amt = parseFloat(distributeForm.value.amount)
  if (Number.isNaN(amt) || amt <= 0) {
    uiStore.showError?.('Distribute', 'Amount must be a positive number.')
    return
  }
  distributeBusy.value = true
  try {
    const result = await feeCollectorAdminService.distribute({
      target_agent_did: distributeForm.value.targetDid,
      amount: distributeForm.value.amount,
      reason: distributeForm.value.reason,
    })
    uiStore.showSuccess?.(
      'Distribute complete',
      `${distributeForm.value.amount} ${frameCurrency.value} → ${shortDid(distributeForm.value.targetDid)} · tx ${result.transaction_id}`,
    )
    showDistributeModal.value = false
    void refreshFees()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Distribute failed'
    uiStore.showError?.('Distribute failed', msg)
  } finally {
    distributeBusy.value = false
  }
}

const periodLabel = computed(() => {
  const found = PERIODS.value.find(p => p.value === period.value)
  return found ? found.label : period.value
})

const invariantValClass = computed(() => {
  const d = data.value?.supply_audit?.delta
  if (d === undefined || d === null) return 'at-stat-val--muted'
  if (Math.abs(d) < 0.001) return 'at-stat-val--green'
  return 'at-stat-val--red'
})
const invariantPillClass = computed(() => {
  const s = (data.value?.supply_audit?.status || '').toUpperCase()
  if (s === 'OK') return 'at-stat-pill--green'
  if (s === 'BREACH') return 'at-stat-pill--red'
  return 'at-stat-pill--muted'
})

// ── Sparkline path computation ─────────────────────────
interface PathPair { line: string; area: string }

const _maxBucketVal = computed(() => {
  if (!data.value || !data.value.sparkline.length) return 1
  let max = 0
  for (const p of data.value.sparkline) {
    const m = parseFloat(p.minted) || 0
    const f = parseFloat(p.fees) || 0
    if (m > max) max = m
    if (f > max) max = f
  }
  return max || 1
})

function buildPath(getValue: (p: { minted: string; fees: string }) => string): PathPair | null {
  if (!data.value || !data.value.sparkline.length) return null
  const pts = data.value.sparkline
  const maxV = _maxBucketVal.value
  const stepX = SPARK_W / Math.max(pts.length - 1, 1)
  const padY = 6
  const usableH = SPARK_H - padY * 2
  const coords = pts.map((p, i) => {
    const v = parseFloat(getValue(p)) || 0
    const x = stepX * i
    const ratio = maxV > 0 ? v / maxV : 0
    const y = SPARK_H - padY - ratio * usableH
    return { x, y }
  })
  const line = coords
    .map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(2)},${c.y.toFixed(2)}`)
    .join(' ')
  const area = line + ` L${SPARK_W},${SPARK_H} L0,${SPARK_H} Z`
  return { line, area }
}

const mintPath = computed(() => buildPath(p => p.minted))
const feePath = computed(() => buildPath(p => p.fees))

const tooltipStyle = computed(() => {
  if (hoverBucket.value === null || !data.value) return {}
  const stepPct = 100 / data.value.sparkline.length
  const leftPct = stepPct * (hoverBucket.value + 0.5)
  // Clamp tooltip position so it doesn't overflow at edges
  const clamped = Math.max(8, Math.min(92, leftPct))
  return {
    left: `${clamped}%`,
    transform: 'translateX(-50%)',
  }
})

// ── Reason rows (computed) ─────────────────────────
const reasonRows = computed(() => {
  if (!data.value) return []
  const total = parseFloat(data.value.totals_in_window.minted) || 1
  return Object.entries(data.value.mints_by_reason)
    .map(([reason, amount]) => ({
      reason,
      amount,
      pct: ((parseFloat(amount) || 0) / total) * 100,
    }))
    .sort((a, b) => parseFloat(b.amount) - parseFloat(a.amount))
})

// ── Helpers ────────────────────────────────────────
function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 30) return s
  return `${s.slice(0, 16)}…${s.slice(-6)}`
}

function formatAvt(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n)) return '—'
  if (n === 0) return '0'
  // Adaptive precision: large values use grouping, small values use 4 decimals
  if (Math.abs(n) >= 1) {
    return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
  }
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 6 })
}

function formatDelta(d: number | undefined | null): string {
  if (d === undefined || d === null) return '—'
  if (Math.abs(d) < 0.001) return '0.0'
  return d.toFixed(4)
}

function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const dt = typeof iso === 'string' ? new Date(iso) : iso
  return dt.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
}

function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatBucketTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  if (period.value === '24h') {
    return new Date(iso).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' })
  }
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
}

function reasonPillClass(reason: string | null | undefined): string {
  const r = (reason || '').toLowerCase()
  if (r.includes('admin')) return 'at-mint-reason-pill--cyan'
  if (r.includes('staking')) return 'at-mint-reason-pill--green'
  if (r.includes('dispute')) return 'at-mint-reason-pill--red'
  if (r.includes('reward')) return 'at-mint-reason-pill--violet'
  return 'at-mint-reason-pill--muted'
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}

function goToEventStoreAggregate(agentDid: string) {
  // Build #6's drilldown — open AdminEvents filtered to this aggregate, on the same frame.
  void router.push({
    path: '/admin/events',
    query: { aggregate_id: agentDid, frame: frame.value },
  })
}
</script>

<style scoped>
.at {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* ── Ambient ───────────────────────────────────── */
.at-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.at-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.at-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.at-glow-1 { width: 460px; height: 460px; background: rgba(var(--cyan-rgb), 0.55); top: -110px; right: -90px; }
.at-glow-2 { width: 360px; height: 360px; background: rgba(168, 85, 247, 0.42); bottom: -70px; left: -110px; }

/* ── Hero ─────────────────────────────────────── */
.at-hero {
  position: relative;
  z-index: 1;
  padding: 36px 32px 18px;
}
.at-hero-inner { max-width: 1280px; margin: 0 auto; }
.at-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.at-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.at-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.at-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.at-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 16px;
  line-height: 1.5;
  max-width: 60rem;
}

/* ── Toolbar ─────────────────────────────────── */
.at-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.at-toolbar-group {
  display: flex; align-items: center; gap: 0.4rem;
}
.at-toolbar-spacer { flex: 1; }
.at-toolbar-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.48);
  text-transform: uppercase;
}
.at-toolbar-val {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--cyan);
}
.at-toolbar-meta {
  margin-left: 0.3rem;
}

/* Period chips */
.at-period-btn {
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
}
.at-period-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.06);
  color: rgba(255, 255, 255, 0.9);
}
.at-period-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
  box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.18);
}
.at-period-btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* Frame switch */
.at-frame-switch {
  display: inline-flex;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}
.at-frame-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: transparent;
  border: none;
  border-radius: 3px;
  padding: 3px 9px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
}
.at-frame-btn:hover:not(:disabled) {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(var(--cyan-rgb), 0.06);
}
.at-frame-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.35);
}
.at-frame-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.at-frame-dot {
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}
/* §FEDEVENTS: dot colors ride inline accentHex now (dynamic frame list). */

/* Toggle */
.at-toggle {
  display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.7);
}
.at-toggle input { display: none; }
.at-toggle-track {
  width: 26px; height: 14px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 7px;
  position: relative;
  transition: background 0.15s;
}
.at-toggle-knob {
  position: absolute; top: 2px; left: 2px;
  width: 10px; height: 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  transition: transform 0.15s, background 0.15s;
}
.at-toggle input:checked ~ .at-toggle-track {
  background: rgba(var(--cyan-rgb), 0.3);
}
.at-toggle input:checked ~ .at-toggle-track .at-toggle-knob {
  transform: translateX(12px);
  background: var(--cyan);
}
.at-toggle-label { font-weight: 600; }

/* ── Body ─────────────────────────────────────── */
.at-body {
  position: relative;
  z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.at-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--mono);
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.at-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.at-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.at-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}

/* ── Center / loading / error ─────────────────── */
.at-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.at-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: at-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes at-spin { to { transform: rotate(360deg); } }
.at-loading-text {
  font-family: var(--mono);
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.at-error-text {
  font-family: var(--mono);
  font-size: 0.85rem;
  color: var(--nc-danger);
}

/* ── Hero stats grid ─────────────────────────── */
.at-stats {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 1fr;
  gap: 1rem;
}
.at-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.at-stat-card--lg { gap: 0.55rem; }
.at-stat-key {
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: var(--cyan);
  text-transform: uppercase;
}
.at-stat-val {
  font-family: var(--mono);
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.05;
}
.at-stat-card--lg .at-stat-val { font-size: 1.85rem; }
.at-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.at-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.at-stat-val--violet { color: #c084fc; text-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
.at-stat-val--red { color: var(--nc-danger, #ff3366); text-shadow: 0 0 14px rgba(255, 51, 102, 0.45); }
.at-stat-val--muted { color: rgba(255, 255, 255, 0.48); }
.at-stat-unit {
  font-size: 0.7rem;
  margin-left: 0.3rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.06em;
}
.at-stat-sub {
  font-family: var(--mono);
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.04em;
}
.at-stat-sub code {
  background: rgba(var(--cyan-rgb), 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.7);
}
.at-stat-warn {
  color: var(--nc-warning, #ff9500);
  font-weight: 600;
}

/* Status pill */
.at-stat-pill {
  display: inline-block;
  font-family: var(--mono);
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.at-stat-pill--green {
  background: rgba(0, 255, 136, 0.1);
  color: var(--nc-success, #00ff88);
  border-color: rgba(0, 255, 136, 0.3);
}
.at-stat-pill--red {
  background: rgba(255, 51, 102, 0.1);
  color: var(--nc-danger, #ff3366);
  border-color: rgba(255, 51, 102, 0.3);
}
.at-stat-pill--muted {
  background: rgba(var(--cyan-rgb), 0.06);
  color: rgba(255, 255, 255, 0.6);
  border-color: rgba(var(--cyan-rgb), 0.18);
}

/* ── Section ─────────────────────────────────── */
.at-section {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.at-section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
}
.at-section-title {
  font-family: var(--mono);
  font-size: 0.65rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: var(--cyan);
  text-transform: uppercase;
}
.at-section-sub {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.48);
  letter-spacing: 0.06em;
}

/* ── Sparkline ───────────────────────────────── */
.at-spark-wrap {
  position: relative;
  width: 100%;
  height: 160px;
}
.at-spark {
  width: 100%;
  height: 100%;
  display: block;
}
.at-spark-grid line {
  stroke: rgba(var(--cyan-rgb), 0.06);
  stroke-width: 1;
  stroke-dasharray: 3 5;
}
.at-spark-line {
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.at-spark-line--green {
  stroke: var(--nc-success, #00ff88);
  filter: drop-shadow(0 0 4px rgba(0, 255, 136, 0.4));
}
.at-spark-line--violet {
  stroke: #c084fc;
  filter: drop-shadow(0 0 4px rgba(168, 85, 247, 0.4));
}
.at-spark-area {
  opacity: 0.12;
}
.at-spark-area--green { fill: var(--nc-success, #00ff88); }
.at-spark-area--violet { fill: #c084fc; }
.at-spark-hover {
  stroke: rgba(255, 255, 255, 0.3);
  stroke-width: 1;
  stroke-dasharray: 4 4;
  pointer-events: none;
}
.at-spark-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-family: var(--mono);
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.4);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.at-spark-tooltip {
  position: absolute;
  top: 4px;
  background: rgba(0, 0, 0, 0.95);
  border: 1px solid rgba(var(--cyan-rgb), 0.4);
  border-radius: 4px;
  padding: 6px 9px;
  font-family: var(--mono);
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.9);
  pointer-events: none;
  white-space: nowrap;
  z-index: 5;
}
.at-tt-time {
  font-weight: 700;
  color: var(--cyan);
  margin-bottom: 3px;
  font-size: 0.6rem;
  letter-spacing: 0.08em;
}
.at-tt-row {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.65rem;
}

/* Legend */
.at-legend {
  display: inline-flex; gap: 0.7rem;
}
.at-legend-item {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-family: var(--mono);
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.at-legend-dot {
  display: inline-block;
  width: 7px; height: 7px;
  border-radius: 50%;
}
.at-legend-dot--green { background: var(--nc-success, #00ff88); box-shadow: 0 0 5px rgba(0, 255, 136, 0.5); }
.at-legend-dot--violet { background: #c084fc; box-shadow: 0 0 5px rgba(168, 85, 247, 0.5); }

/* ── Two-column ──────────────────────────── */
.at-twocol {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}

/* ── Reasons list ──────────────────────────── */
.at-reason-list {
  display: flex; flex-direction: column; gap: 0.4rem;
}
.at-reason-row {
  display: grid;
  grid-template-columns: 130px 1fr auto auto;
  align-items: center;
  gap: 0.6rem;
  font-family: var(--mono);
  font-size: 0.7rem;
}
.at-reason-label {
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.65rem;
}
.at-reason-bar {
  position: relative;
  height: 6px;
  background: rgba(var(--cyan-rgb), 0.1);
  border-radius: 3px;
  overflow: hidden;
}
.at-reason-bar-fill {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.5), var(--cyan));
  border-radius: 3px;
  transition: width 0.3s;
}
.at-reason-val {
  text-align: right;
  color: var(--cyan);
  font-weight: 600;
  font-size: 0.7rem;
}
.at-reason-pct {
  text-align: right;
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.55);
  min-width: 3.2rem;
}

/* ── Top fee payers list ───────────────────── */
.at-payer-list {
  display: flex; flex-direction: column; gap: 0.4rem;
}
.at-payer-row {
  display: grid;
  grid-template-columns: 30px 1fr auto auto auto auto;
  align-items: center;
  gap: 0.5rem;
  padding: 4px 7px;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 0.7rem;
}
.at-payer-rank {
  color: var(--cyan);
  font-weight: 700;
  font-size: 0.65rem;
}
.at-payer-did {
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.65rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.at-payer-tx {
  color: rgba(255, 255, 255, 0.48);  /* §FESUITE: 4.94:1 (0.45 was 4.49:1) */
  font-size: 0.6rem;
}
.at-payer-fee {
  color: #c084fc;
  font-weight: 600;
  font-size: 0.7rem;
  text-align: right;
}

/* ── Recent mints ──────────────────────────── */
.at-mint-list {
  display: flex; flex-direction: column; gap: 0.35rem;
}
.at-mint-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 6px 10px;
  background: rgba(var(--cyan-rgb), 0.03);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 0.7rem;
  flex-wrap: wrap;
}
.at-mint-time {
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.at-mint-date {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.5);
}
.at-mint-reason-pill {
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  text-transform: uppercase;
}
.at-mint-reason-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.at-mint-reason-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.at-mint-reason-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.at-mint-reason-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.at-mint-reason-pill--muted { background: rgba(var(--cyan-rgb), 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--cyan-rgb), 0.18); }
.at-mint-amount {
  color: var(--nc-success, #00ff88);
  font-weight: 700;
  font-size: 0.7rem;
}
.at-mint-amount-unit {
  font-size: 0.55rem;
  color: rgba(255, 255, 255, 0.48);
  font-weight: 600;
  letter-spacing: 0.06em;
}
.at-mint-recipient {
  background: rgba(var(--cyan-rgb), 0.05);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.7);
}
.at-mint-spacer { flex: 1; }

/* ── Icon button ───────────────────────────── */
.at-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  transition: all 0.12s;
}
.at-icon-btn:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}

/* ── Empty mini ──────────────────────────── */
.at-empty-mini {
  text-align: center;
  font-family: var(--mono);
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.4);
  padding: 1.4rem;
  letter-spacing: 0.06em;
}

/* ── Footer ──────────────────────────────── */
.at-footer {
  font-family: var(--mono);
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.at-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── Responsive ──────────────────────────── */
/* ── P1 (2026-05-08): Tab bar, Mint button, Fee Collector tab, modals ── */
.at-tabs {
  display: flex;
  gap: 0.4rem;
  margin-top: 0.85rem;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.at-tab {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  border: 1px solid transparent;
  border-bottom: 2px solid transparent;
  border-radius: 6px 6px 0 0;
  padding: 8px 18px;
  cursor: pointer;
  transition: all 0.18s;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  position: relative;
  margin-bottom: -1px;
}
.at-tab:hover {
  color: rgba(255, 255, 255, 0.9);
  background: rgba(var(--cyan-rgb), 0.04);
}
.at-tab--active {
  color: rgba(var(--cyan-rgb), 1);
  background: linear-gradient(180deg,
    rgba(var(--cyan-rgb), 0.12) 0%,
    rgba(var(--cyan-rgb), 0.04) 100%);
  border-color: rgba(var(--cyan-rgb), 0.25);
  border-bottom-color: var(--cyan);
  box-shadow: 0 -2px 12px rgba(var(--cyan-rgb), 0.18);
}
.at-tab-glyph {
  font-size: 0.85rem;
  opacity: 0.85;
}
.at-tab-badge {
  font-family: var(--mono);
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  background: rgba(168, 85, 247, 0.18);
  border: 1px solid rgba(168, 85, 247, 0.38);
  color: #c084fc;
  border-radius: 8px;
  padding: 1px 6px;
  margin-left: 0.3rem;
}

/* Mint button — distinct from generic primary */
/* §FEPARITY-R3 — return-to-treasury: amber, deliberately NOT the mint green.
   Minting creates supply; this only moves it back. Different act, different colour. */
.at-btn--return {
  background: linear-gradient(90deg,
    rgba(255, 183, 77, 0.16) 0%,
    rgba(255, 183, 77, 0.07) 100%);
  border: 1px solid rgba(255, 183, 77, 0.45);
  color: #ffb74d;
}
.at-btn--return:hover:not(:disabled) {
  background: linear-gradient(90deg,
    rgba(255, 183, 77, 0.28) 0%,
    rgba(255, 183, 77, 0.12) 100%);
  border-color: rgba(255, 183, 77, 0.7);
}

.at-btn--mint {
  background: linear-gradient(90deg,
    rgba(0, 255, 136, 0.18) 0%,
    rgba(0, 255, 136, 0.08) 100%);
  border: 1px solid rgba(0, 255, 136, 0.45);
  color: var(--nc-success, #00ff88);
  box-shadow: 0 0 12px rgba(0, 255, 136, 0.18);
}
.at-btn--mint:hover:not(:disabled) {
  background: linear-gradient(90deg,
    rgba(0, 255, 136, 0.3) 0%,
    rgba(0, 255, 136, 0.14) 100%);
  border-color: rgba(0, 255, 136, 0.7);
  box-shadow: 0 0 18px rgba(0, 255, 136, 0.32);
}

.at-btn--xl {
  padding: 0.6rem 1rem;
  font-size: 0.78rem;
  width: 100%;
  justify-content: center;
}

.at-btn-glyph {
  font-size: 0.95rem;
  font-weight: 700;
  margin-right: 0.05rem;
}

/* Fee tab specific */
.at-stats--3 {
  grid-template-columns: 1.4fr 1fr 1fr;
}

.at-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.7rem;
  padding: 0.85rem 1rem;
  border-radius: 8px;
  font-family: var(--mono);
  font-size: 0.75rem;
  line-height: 1.5;
  margin-bottom: 0.85rem;
}
.at-banner--info {
  background: rgba(var(--cyan-rgb), 0.05);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(255, 255, 255, 0.78);
}
.at-banner-glyph {
  font-size: 1.05rem;
  flex-shrink: 0;
}
.at-banner-text strong {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 700;
}
.at-banner-text code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.85em;
}

.at-spark-bar {
  fill: rgba(var(--cyan-rgb), 0.7);
}

/* Modals (custom inline; z-index 10100 matches ConfirmActionModal) */
.at-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 10100;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.2rem;
  animation: at-modal-fade 0.18s ease;
}
@keyframes at-modal-fade {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.at-modal {
  width: min(520px, 100%);
  background: linear-gradient(180deg,
    rgba(10, 13, 22, 0.97) 0%,
    rgba(6, 8, 16, 0.97) 100%);
  border: 1px solid rgba(var(--cyan-rgb), 0.4);
  border-radius: 10px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.6),
              0 0 24px rgba(var(--cyan-rgb), 0.18);
  overflow: hidden;
  font-family: var(--mono);
  animation: at-modal-pop 0.2s ease;
}
@keyframes at-modal-pop {
  from { transform: scale(0.95) translateY(8px); opacity: 0; }
  to   { transform: scale(1) translateY(0); opacity: 1; }
}
.at-modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.95rem 1.2rem;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.18);
}
.at-modal-title {
  font-size: 0.9rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: rgba(var(--cyan-rgb), 0.98);
  text-shadow: 0 0 12px rgba(var(--cyan-rgb), 0.4);
}
.at-modal-close {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.75);
  border-radius: 4px;
  font-family: monospace;
  font-size: 0.85rem;
  padding: 2px 9px;
  cursor: pointer;
  transition: all 0.15s;
}
.at-modal-close:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  color: rgba(var(--cyan-rgb), 1);
}
.at-modal-body {
  padding: 1rem 1.2rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.at-modal-msg {
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.55;
  margin: 0 0 0.5rem;
}
.at-modal-msg code {
  background: rgba(var(--cyan-rgb), 0.06);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.92em;
}
.at-modal-msg strong {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
}
.at-form-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: rgba(var(--cyan-rgb), 0.85);
  text-transform: uppercase;
  margin-top: 0.3rem;
}
.at-form-input {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(255, 255, 255, 0.95);
  font-family: var(--mono);
  font-size: 0.78rem;
  padding: 8px 11px;
  border-radius: 4px;
  outline: none;
  transition: border-color 0.15s, background 0.15s;
}
.at-form-input:focus {
  border-color: rgba(var(--cyan-rgb), 0.65);
  background: rgba(0, 0, 0, 0.55);
}
.at-form-input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.at-form-warn {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--nc-warning, #ff9500);
  background: rgba(255, 149, 0, 0.05);
  border: 1px solid rgba(255, 149, 0, 0.25);
  border-radius: 4px;
  padding: 6px 9px;
  margin-top: 0.4rem;
}
/* §pass71.5 (2026-05-25) — anchored inline error in mint modal so failed
   POSTs render under the form instead of behind a fly-away toast. */
.at-form-error {
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--nc-danger, #ff5252);
  background: rgba(255, 82, 82, 0.07);
  border: 1px solid rgba(255, 82, 82, 0.35);
  border-radius: 4px;
  padding: 8px 11px;
  margin-top: 0.6rem;
  line-height: 1.35;
}
.at-form-error strong {
  color: var(--nc-danger, #ff5252);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.at-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.85rem 1.2rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.at-btn-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid rgba(0, 0, 0, 0.25);
  border-top-color: rgba(0, 0, 0, 0.85);
  border-radius: 50%;
  animation: at-spin 0.7s linear infinite;
  margin-right: 0.4rem;
  vertical-align: -1px;
}

/* ── P3 (2026-05-08) — Funding Policy tab + edit modal ── */
.at-policy-grid {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.at-policy-row {
  display: grid;
  grid-template-columns: 200px 1fr 160px;
  align-items: center;
  gap: 0.85rem;
  padding: 0.65rem 0.85rem;
  background: rgba(var(--cyan-rgb), 0.03);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 6px;
}
.at-policy-row--head {
  background: transparent;
  border: none;
  padding: 0.3rem 0.85rem;
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.48);
  text-transform: uppercase;
}
.at-policy-row--default {
  background: rgba(var(--cyan-rgb), 0.07);
  border-color: rgba(var(--cyan-rgb), 0.3);
  box-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.12);
}
.at-policy-reason {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  color: rgba(var(--cyan-rgb), 0.95);
  background: transparent;
  padding: 0;
}
.at-policy-row--default .at-policy-reason {
  color: var(--cyan);
  text-shadow: 0 0 10px rgba(var(--cyan-rgb), 0.4);
}
.at-policy-waterfall {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}
.at-policy-source {
  display: inline-block;
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px 9px;
  border-radius: 4px;
  border: 1px solid transparent;
  position: relative;
}
.at-policy-source--fee_collector {
  background: rgba(168, 85, 247, 0.12);
  color: #c084fc;
  border-color: rgba(168, 85, 247, 0.4);
}
.at-policy-source--treasury {
  background: rgba(var(--cyan-rgb), 0.12);
  color: var(--cyan);
  border-color: rgba(var(--cyan-rgb), 0.4);
}
.at-policy-source + .at-policy-source::before {
  content: '→';
  position: absolute;
  left: -0.62rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.7rem;
  font-weight: 400;
}
.at-policy-note {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: rgba(255, 149, 0, 0.7);
  margin-left: 0.4rem;
  font-style: italic;
}
.at-policy-actions {
  display: inline-flex;
  gap: 0.4rem;
  justify-content: flex-end;
}
.at-policy-foot {
  margin-top: 0.85rem;
  display: flex;
  justify-content: flex-end;
}
.at-policy-sources-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.85rem;
}
.at-policy-source-card {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 6px;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.at-policy-source-desc {
  margin: 0;
  font-family: var(--mono);
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.55;
}
.at-policy-source-desc code {
  background: rgba(var(--cyan-rgb), 0.06);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.92em;
}
.at-policy-source-desc strong {
  color: rgba(255, 255, 255, 0.92);
  font-weight: 600;
}

/* Edit policy modal source builder */
.at-policy-source-builder {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.4rem;
  margin-bottom: 0.3rem;
}
.at-policy-source-pill {
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: rgba(255, 255, 255, 0.03);
  color: rgba(255, 255, 255, 0.55);
}
.at-policy-source-pill:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  color: rgba(255, 255, 255, 0.9);
  border-color: rgba(var(--cyan-rgb), 0.3);
}
.at-policy-source-pill--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.at-policy-source-pill--active.at-policy-source--fee_collector {
  background: rgba(168, 85, 247, 0.18);
  color: #c084fc;
  border-color: rgba(168, 85, 247, 0.5);
}
.at-policy-source-pill--active.at-policy-source--treasury {
  background: rgba(var(--cyan-rgb), 0.18);
  color: var(--cyan);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.at-policy-source-x {
  font-size: 0.7rem;
  opacity: 0.65;
}

@media (max-width: 1100px) {
  .at-stats { grid-template-columns: 1fr 1fr; }
  .at-stats--3 { grid-template-columns: 1fr 1fr; }
  .at-twocol { grid-template-columns: 1fr; }
  .at-policy-row { grid-template-columns: 1fr; gap: 0.4rem; }
  .at-policy-row--head { display: none; }
  .at-policy-actions { justify-content: flex-start; }
  .at-policy-sources-list { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .at-hero { padding: 24px 16px 12px; }
  .at-h1 { font-size: 1.5rem; }
  .at-body { padding: 0 16px; }
  .at-toolbar { gap: 0.5rem; }
  .at-stats { grid-template-columns: 1fr; }
  .at-mint-row { flex-wrap: wrap; gap: 0.35rem; }
  .at-payer-row { grid-template-columns: 30px 1fr auto auto; row-gap: 0.2rem; }
  .at-payer-row .at-icon-btn { display: none; }
}
</style>
