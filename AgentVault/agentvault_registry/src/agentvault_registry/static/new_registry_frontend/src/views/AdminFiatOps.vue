<template>
  <div class="afo">
    <!-- Ambient background (fixed grid + cyan/violet glows) -->
    <div class="afo-ambient" aria-hidden="true">
      <div class="afo-grid"></div>
      <div class="afo-glow afo-glow-1"></div>
      <div class="afo-glow afo-glow-2"></div>
    </div>

    <!-- Hero — peer-aligned (AdminTreasury / AdminCanaries pattern) -->
    <section class="afo-hero">
      <div class="afo-hero-inner">
        <div class="afo-chip">
          <span class="afo-chip-dot"></span>
          {{ t('adminFiatOpsView.hero.chip') }}
        </div>
        <h1 class="afo-h1">{{ tp('adminFiatOpsView.hero.h1a', 'EUR → {unit} ', { unit }) }}<span class="afo-accent">{{ t('adminFiatOpsView.hero.h1Accent') }}</span>{{ tp('adminFiatOpsView.hero.h1b', ' Console', { unit }) }}</h1>
        <p class="afo-lead">{{ t('adminFiatOpsView.hero.lead') }}</p>
      </div>
    </section>

    <!-- D6-836 (agentvault2-d6, 2026-10-25, his word through agentvault2-69: "make fiat operations inaccessible if
         deactivated. or best just greyed out so you cant use it"): the sidebar greys this page out while the on-ramp
         is off (requiresFiat). Reached by its address it says so; its tools stay, because each serves a purchase paid
         while the switch was on (a refund, a replay; fiat_credit_retry pays an owed credit while it is off too), the
         flares, or a price list prepared before the switch goes on. Every buyer's route refuses while it is off. -->
    <div v-if="fiatOffRead" class="afo-off" role="status" data-testid="afo-fiat-off">
      <Icon name="mdi:currency-eur-off" class="afo-off-icon" />
      <span>The euro on-ramp is off on this registry (FIAT_ONRAMP_ENABLED), so it sells nothing. This page keeps the
        purchases paid while it was on and what serves them (refund, replay, the magic-link mail), the flares, and a
        price list you can prepare before the switch goes on.</span>
    </div>

    <!-- Tab nav -->
    <!-- §FESUITE: the tablist holds only its tabs (the refresh button inside it broke the role: axe
         aria-required-children); each tab names the panel it shows -->
    <nav class="afo-tabs" aria-label="Fiat operations">
      <div class="afo-tablist" role="tablist">
        <button
          v-for="tab in tabs"
          :id="'afo-tab-' + tab.key"
          :key="tab.key"
          class="afo-tab"
          :class="{ 'afo-tab-active': activeTab === tab.key }"
          role="tab"
          :aria-selected="activeTab === tab.key"
          :aria-controls="'afo-panel-' + tab.key"
          @click="activeTab = tab.key"
        >
          <Icon :name="tab.icon" class="afo-tab-icon" />
          <span>{{ tab.label }}</span>
          <span v-if="tab.badge" class="afo-tab-badge">{{ tab.badge }}</span>
        </button>
      </div>
      <div class="afo-tab-spacer"></div>
      <button class="afo-icon-btn" @click="refreshAll" :disabled="loadingAny" title="Refresh all data">
        <Icon name="mdi:refresh" :class="{ 'afo-spin': loadingAny }" />
      </button>
    </nav>

    <!-- ╔════════════════════ OVERVIEW TAB ════════════════════╗ -->
    <section v-show="activeTab === 'overview'" id="afo-panel-overview" class="afo-tab-panel" role="tabpanel" aria-labelledby="afo-tab-overview">
      <ReadFailedNotice v-if="statsFailed && !stats && !statsLoading" text="The purchase statistics could not be read just now." :retry="loadStats" />
      <div v-else-if="!stats && !statsLoading" class="afo-empty">No data yet — fund a purchase to see the dashboard come alive.</div>
      <div v-else-if="statsLoading && !stats" class="afo-loading">Loading stats…</div>
      <template v-else-if="stats">
        <!-- Window picker -->
        <div class="afo-window-row">
          <span class="afo-window-label">Window</span>
          <button
            v-for="w in [1, 7, 30, 90, 365]"
            :key="w"
            class="afo-window-btn"
            :class="{ 'afo-window-btn-active': statsWindow === w }"
            @click="statsWindow = w; loadStats()"
          >{{ w }}d</button>
          <span class="afo-window-meta">{{ stats.window_days }}d of data</span>
        </div>

        <!-- §FESUITE (V0578): the figures below answer the window selected above, or are not drawn: a failed (or late)
             read for another window left the earlier window's KPIs under the new window's button -->
        <ReadFailedNotice v-if="!statsCurrent && statsFailed" dense data-testid="afo-stats-window-unread"
          :text="`The ${statsWindow}-day statistics could not be read just now.`" :retry="loadStats" />
        <div v-else-if="!statsCurrent" class="afo-loading" data-testid="afo-stats-window-loading">Loading stats…</div>
        <template v-else>
        <ReadFailedNotice v-if="statsFailed" dense data-testid="afo-stats-stale" :retry="loadStats"
          text="The statistics could not be read just now. What follows is from the last read that answered." />

        <!-- KPI grid -->
        <div class="afo-kpi-grid">
          <div class="afo-kpi afo-kpi-emphasis">
            <span class="afo-kpi-label">Sales (settled)</span>
            <span class="afo-kpi-value">€{{ formatBigNum(stats.total_eur, 2) }}</span>
            <span class="afo-kpi-meta">avg €{{ formatBigNum(stats.avg_purchase_eur, 2) }}/purchase</span>
          </div>
          <div class="afo-kpi">
            <span class="afo-kpi-label">{{ unit }} distributed</span>
            <span class="afo-kpi-value">{{ formatBigNum(stats.total_avt, 0) }}</span>
            <span class="afo-kpi-meta">treasury draw</span>
          </div>
          <div class="afo-kpi">
            <span class="afo-kpi-label">Success rate</span>
            <span class="afo-kpi-value">{{ stats.success_rate_pct }}%</span>
            <span class="afo-kpi-meta">{{ stats.completed_count }}/{{ stats.completed_count + stats.pending_count + stats.failed_count + stats.refunded_count }}</span>
          </div>
          <div class="afo-kpi">
            <span class="afo-kpi-label">New devs (anon)</span>
            <span class="afo-kpi-value">{{ stats.anonymous_devs_created }}</span>
            <span class="afo-kpi-meta">via Stripe-flow auto-onboard</span>
          </div>
          <div class="afo-kpi">
            <span class="afo-kpi-label">Pending</span>
            <span class="afo-kpi-value afo-kpi-pending">{{ stats.pending_count }}</span>
            <span class="afo-kpi-meta">awaiting webhook</span>
          </div>
          <div class="afo-kpi">
            <span class="afo-kpi-label">Failed / refunded</span>
            <span class="afo-kpi-value afo-kpi-warn">{{ stats.failed_count }}<span class="afo-kpi-sep">/</span>{{ stats.refunded_count }}</span>
            <span class="afo-kpi-meta">action review</span>
          </div>
        </div>

        <!-- Daily revenue sparkline -->
        <div class="afo-card">
          <div class="afo-card-head">
            <h2>{{ t('adminFiatOpsView.panels.dailyRevenue', { days: stats.window_days }) }}</h2>
            <span class="afo-meta">{{ stats.daily_revenue.length }} day{{ stats.daily_revenue.length === 1 ? '' : 's' }} with activity</span>
          </div>
          <div v-if="!stats.daily_revenue.length" class="afo-spark-empty">
            <Icon name="mdi:chart-line-variant" class="afo-spark-empty-icon" />
            <p>No completed purchases in this {{ stats.window_days }}-day window.</p>
            <p class="afo-spark-empty-sub">First fiat purchase will populate the trend line.</p>
          </div>
          <div v-else-if="stats.daily_revenue.length === 1" class="afo-spark-single">
            <div class="afo-spark-single-meta">
              <Icon name="mdi:circle-medium" class="afo-spark-single-pulse" />
              Single day with activity — sparkline appears once 2+ days have completed purchases.
            </div>
            <div class="afo-spark-single-row">
              <div class="afo-spark-single-col">
                <span class="afo-spark-single-label">Day</span>
                <span class="afo-spark-single-val">{{ stats.daily_revenue[0].day }}</span>
              </div>
              <div class="afo-spark-single-col">
                <span class="afo-spark-single-label">EUR</span>
                <span class="afo-spark-single-val afo-spark-single-emph">€{{ stats.daily_revenue[0].eur }}</span>
              </div>
              <div class="afo-spark-single-col">
                <span class="afo-spark-single-label">{{ unit }}</span>
                <span class="afo-spark-single-val">{{ formatBigNum(stats.daily_revenue[0].avt, 0) }}</span>
              </div>
              <div class="afo-spark-single-col">
                <span class="afo-spark-single-label">Purchases</span>
                <span class="afo-spark-single-val">{{ stats.daily_revenue[0].purchases }}</span>
              </div>
            </div>
          </div>
          <div v-else class="afo-spark-wrap">
            <svg :viewBox="`0 0 ${sparkW} ${sparkH}`" class="afo-spark-svg" preserveAspectRatio="none">
              <defs>
                <linearGradient id="afo-spark-grad" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stop-color="var(--nc-primary, #00d2d2)" stop-opacity="0.45" />
                  <stop offset="100%" stop-color="var(--nc-primary, #00d2d2)" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <!-- y-axis grid lines -->
              <line v-for="i in 4" :key="`g${i}`" :x1="0" :x2="sparkW" :y1="(sparkH * i) / 4" :y2="(sparkH * i) / 4" stroke="rgba(255,255,255,0.04)" stroke-width="1" />
              <!-- area fill -->
              <path :d="sparkAreaPath" fill="url(#afo-spark-grad)" />
              <!-- line -->
              <path :d="sparkLinePath" fill="none" stroke="var(--nc-primary, #00d2d2)" stroke-width="1.5" stroke-linejoin="round" />
              <!-- dots -->
              <circle
                v-for="(d, i) in sparkPoints"
                :key="`pt-${i}`"
                :cx="d.x"
                :cy="d.y"
                r="2.5"
                fill="var(--nc-primary, #00d2d2)"
              >
                <title>{{ d.day }} · €{{ d.eur }} · {{ d.purchases }} purchase{{ d.purchases === 1 ? '' : 's' }}</title>
              </circle>
            </svg>
            <div class="afo-spark-foot">
              <span>{{ stats.daily_revenue[0]?.day }}</span>
              <span class="afo-spark-peak" v-if="sparkPeakLabel">peak {{ sparkPeakLabel }}</span>
              <span>{{ stats.daily_revenue[stats.daily_revenue.length - 1]?.day }}</span>
            </div>
          </div>
        </div>

        <!-- Tier share table -->
        <div class="afo-card">
          <div class="afo-card-head"><h2>{{ t('adminFiatOpsView.panels.tierShare') }}</h2></div>
          <div v-if="!stats.tier_share.length" class="afo-empty afo-empty-inline">No settled purchases yet.</div>
          <table v-else class="afo-table">
            <thead><tr><th>Tier</th><th>Count</th><th>Total EUR</th><th>Total {{ unit }}</th><th>Share</th></tr></thead>
            <tbody>
              <tr v-for="row in stats.tier_share" :key="row.tier_label">
                <td>{{ row.tier_label }}</td>
                <td class="afo-mono">{{ row.count }}</td>
                <td class="afo-mono">€{{ formatBigNum(row.total_eur, 2) }}</td>
                <td class="afo-mono">{{ formatBigNum(row.total_avt, 0) }}</td>
                <td>
                  <div class="afo-bar-bg">
                    <div class="afo-bar-fg" :style="{ width: tierSharePct(row) + '%' }"></div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Recent 10 purchases (derived from explorer.rows — single source of truth) -->
        <div class="afo-card">
          <div class="afo-card-head">
            <h2>{{ t('adminFiatOpsView.panels.recentPurchases') }}</h2>
            <button class="afo-btn afo-btn-ghost" @click="activeTab = 'explorer'">View all in Explorer →</button>
          </div>
          <div v-if="!recentPurchases.length" class="afo-empty afo-empty-inline">
            <Icon name="mdi:cart-outline" class="afo-empty-icon" />
            <span>Nothing yet — first fiat purchase will appear here.</span>
          </div>
          <table v-else class="afo-table afo-table-recent afo-table-clickable">
            <thead><tr><th>When</th><th>Status</th><th>EUR</th><th>{{ unit }}</th><th>Tier</th><th>Customer / Agent</th></tr></thead>
            <tbody>
              <tr v-for="p in recentPurchases" :key="p.id" @click="openInExplorer(p.id)" :title="`Open ${p.id.slice(0,8)}… in Explorer`">
                <td>{{ formatRelative(p.created_at) }}</td>
                <td><span class="afo-pill" :class="`afo-pill-status-${p.status}`">{{ p.status }}</span></td>
                <td class="afo-mono">€{{ p.amount_eur }}</td>
                <td class="afo-mono">{{ formatBigNum(p.amount_avt, 0) }}</td>
                <td>{{ p.tier_label }}</td>
                <td class="afo-truncate">{{ p.customer_email || (p.agent_did ? truncMid(p.agent_did, 12, 6) : '—') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        </template>
      </template>
    </section>

    <!-- ╔════════════════════ PRICING TAB ════════════════════╗ -->
    <section v-show="activeTab === 'pricing'" id="afo-panel-pricing" class="afo-tab-panel" role="tabpanel" aria-labelledby="afo-tab-pricing">
      <div v-if="pricingLoading" class="afo-loading">Loading config…</div>
      <div v-else-if="!pricingLoaded" class="afo-error">Failed to load pricing. Check API + admin_treasury flag.</div>

      <template v-else>
        <!-- Active config -->
        <section class="afo-card">
          <div class="afo-card-head">
            <h2>{{ t('adminFiatOpsView.panels.activeConfig') }} <span class="afo-pill afo-pill-version">v{{ active?.version || '?' }}</span></h2>
            <span class="afo-meta" v-if="active?.created_at">
              installed {{ formatDate(active.created_at) }}
              <span v-if="active.created_by_developer_id"> by dev #{{ active.created_by_developer_id }}</span>
            </span>
          </div>
          <p v-if="fallbackInUse" class="afo-warn"><Icon name="mdi:alert" /> DB row not found — falling back to compiled defaults. Save a config to fix.</p>
          <div class="afo-active-grid" v-if="active">
            <div class="afo-active-meta">
              <div><span>Currency</span><strong>{{ active.config.currency }}</strong></div>
              <div><span>Min purchase</span><strong>{{ active.config.currency === 'EUR' ? '€' : '' }}{{ active.config.min_eur }}</strong></div>
              <div><span>Max purchase</span><strong>{{ active.config.currency === 'EUR' ? '€' : '' }}{{ active.config.max_eur }}</strong></div>
            </div>
            <table class="afo-table">
              <thead><tr><th>Floor</th><th>{{ unit }}/€</th><th>Tier</th><th>Bonus</th></tr></thead>
              <tbody>
                <tr v-for="tier in active.config.tiers" :key="tier.tier_label">
                  <td>{{ active.config.currency === 'EUR' ? '€' : '' }}{{ tier.floor_eur }}+</td>
                  <td class="afo-mono">{{ tier.avt_per_eur }}</td>
                  <td>{{ tier.tier_label }}</td>
                  <td class="afo-bonus">{{ tier.bonus_label || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="active?.note" class="afo-note">Note: <em>{{ active.note }}</em></p>
        </section>

        <!-- Edit panel -->
        <section class="afo-card">
          <div class="afo-card-head">
            <h2>{{ t('adminFiatOpsView.panels.editProposal') }}</h2>
            <button class="afo-btn afo-btn-ghost" @click="resetDraftFromActive">↻ Reset to active</button>
          </div>

          <div class="afo-edit-grid">
            <label>
              <span>Currency</span>
              <select v-model="draft.currency" class="nc-input"><option>EUR</option></select>
            </label>
            <label>
              <span>Min EUR</span>
              <input v-model="draft.min_eur" type="text" class="nc-input afo-mono" />
            </label>
            <label>
              <span>Max EUR</span>
              <input v-model="draft.max_eur" type="text" class="nc-input afo-mono" />
            </label>
          </div>

          <div class="afo-tier-edit">
            <div class="afo-tier-head">
              <span>Floor (€)</span><span>{{ unit }}/€</span><span>Label</span><span>Bonus</span><span></span>
            </div>
            <div v-for="(tier, idx) in draft.tiers" :key="idx" class="afo-tier-row">
              <input v-model="tier.floor_eur" type="text" class="nc-input afo-mono" placeholder="1.00" />
              <input v-model="tier.avt_per_eur" type="text" class="nc-input afo-mono" placeholder="2000" />
              <input v-model="tier.tier_label" type="text" class="nc-input" placeholder="tier_1_base" />
              <input v-model="tier.bonus_label" type="text" class="nc-input" placeholder="" />
              <button class="afo-btn afo-btn-icon" @click="removeTier(idx)" :disabled="draft.tiers.length <= 1" title="Remove tier">−</button>
            </div>
            <button class="afo-btn afo-btn-ghost afo-add-tier" @click="addTier">+ Add tier</button>
          </div>

          <label class="afo-note-input">
            <span>Audit note (required, ≥4 chars)</span>
            <textarea v-model="note" class="nc-input" rows="2" :placeholder="`e.g. raised tier_3 to 3500 ${unit}/EUR after demand simulation showed 30-day treasury survival > 60d`"></textarea>
          </label>

          <div v-if="validationErrors.length" class="afo-errors">
            <div class="afo-errors-head"><Icon name="mdi:alert" /> Config errors:</div>
            <ul><li v-for="e in validationErrors" :key="e">{{ e }}</li></ul>
          </div>

          <div class="afo-edit-actions">
            <button class="afo-btn" @click="runValidate" :disabled="validating">
              <span v-if="validating">⟳ Validating…</span>
              <span v-else>✓ Validate</span>
            </button>
            <button class="afo-btn afo-btn-primary" @click="confirmSave" :disabled="!canSave || saving">
              <span v-if="saving">⟳ Saving…</span>
              <span v-else>SAVE NEW VERSION</span>
            </button>
          </div>
        </section>

        <!-- Simulator -->
        <section class="afo-card">
          <div class="afo-card-head"><h2>{{ t('adminFiatOpsView.panels.whatIf') }}</h2></div>
          <p class="afo-sub">Pure-math. No DB writes. Run the proposal against any demand scenario.</p>

          <div class="afo-sim-inputs">
            <label>
              <span>Starting treasury {{ unit }}</span>
              <input v-model="sim.startingTreasury" type="text" class="nc-input afo-mono" placeholder="17700130" />
            </label>
            <label>
              <span>Starting fee_collector {{ unit }}</span>
              <input v-model="sim.startingFeeCollector" type="text" class="nc-input afo-mono" placeholder="2920000" />
            </label>
            <label class="afo-sim-waterfall">
              <span>Waterfall order</span>
              <select v-model="sim.waterfall" class="nc-input">
                <option value="fee_collector,treasury">fee_collector → treasury (default)</option>
                <option value="treasury,fee_collector">treasury → fee_collector (treasury-first)</option>
                <option value="treasury">treasury only</option>
                <option value="fee_collector">fee_collector only</option>
              </select>
            </label>
          </div>

          <div class="afo-sim-scenario">
            <label>
              <span>Scenario template</span>
              <select v-model="sim.scenarioTemplate" @change="applyScenarioTemplate" class="nc-input">
                <option value="custom">Custom (paste/edit list below)</option>
                <option value="even_5_eur">100 buyers × €5</option>
                <option value="even_20_eur">100 buyers × €20</option>
                <option value="even_100_eur">100 buyers × €100</option>
                <option value="mixed_realistic">Mixed: 70% €5, 25% €20, 5% €100 (1000 buyers)</option>
                <option value="whales_only">10 whales × €500</option>
                <option value="exhaustion_test">10000 × €100 (treasury exhaustion test)</option>
              </select>
            </label>
            <label class="afo-sim-purchases">
              <span>Purchases (one EUR amount per line)</span>
              <textarea v-model="sim.purchasesText" class="nc-input afo-mono" rows="4"></textarea>
            </label>
          </div>

          <button class="afo-btn afo-btn-primary" @click="runSimulate" :disabled="simulating">
            <span v-if="simulating">⟳ Simulating…</span>
            <span v-else>▶ RUN SIMULATION</span>
          </button>

          <div v-if="simResult" class="afo-sim-results">
            <div class="afo-sim-summary-grid">
              <div><span>Total EUR collected</span><strong>€{{ simResult.summary.total_eur }}</strong></div>
              <div><span>Total {{ unit }} distributed</span><strong>{{ formatBigNum(simResult.summary.total_avt_distributed, 0) }}</strong></div>
              <div><span>Treasury after</span><strong>{{ formatBigNum(simResult.summary.treasury_remaining, 0) }}</strong></div>
              <div><span>fee_collector after</span><strong>{{ formatBigNum(simResult.summary.fee_collector_remaining, 0) }}</strong></div>
              <div><span>Settled / Partial</span><strong>{{ simResult.summary.purchases_settled }} / {{ simResult.summary.purchases_partial_or_failed }}</strong></div>
              <div v-if="simResult.summary.exhaustion_at_purchase !== null"><span>Exhaustion at</span><strong class="afo-warn-strong">purchase #{{ simResult.summary.exhaustion_at_purchase + 1 }}</strong></div>
            </div>

            <h3>Per-tier breakdown</h3>
            <table class="afo-table">
              <thead><tr><th>Tier</th><th>Count</th><th>Total EUR</th><th>Total {{ unit }}</th></tr></thead>
              <tbody>
                <tr v-for="row in simResult.tier_breakdown" :key="row.tier_label">
                  <td>{{ row.tier_label }}</td>
                  <td class="afo-mono">{{ row.count }}</td>
                  <td class="afo-mono">€{{ row.total_eur }}</td>
                  <td class="afo-mono">{{ formatBigNum(row.total_avt, 0) }}</td>
                </tr>
              </tbody>
            </table>

            <details v-if="simResult.warnings.length" class="afo-warnings">
              <summary>{{ simResult.warnings.length }} warning{{ simResult.warnings.length === 1 ? '' : 's' }}</summary>
              <ul><li v-for="w in simResult.warnings" :key="w">{{ w }}</li></ul>
            </details>
          </div>
        </section>

        <!-- History -->
        <section class="afo-card">
          <div class="afo-card-head">
            <h2>{{ t('adminFiatOpsView.panels.versionHistory') }}</h2>
            <span class="afo-meta">{{ history.length }} version{{ history.length === 1 ? '' : 's' }}</span>
          </div>
          <table class="afo-table">
            <thead><tr><th>v</th><th>Status</th><th>Created</th><th>By</th><th>Note</th></tr></thead>
            <tbody>
              <tr v-for="h in history" :key="h.id" :class="{ 'afo-row-active': h.is_active }">
                <td class="afo-mono">v{{ h.version }}</td>
                <td><span class="afo-pill" :class="h.is_active ? 'afo-pill-active' : 'afo-pill-archived'">{{ h.is_active ? 'ACTIVE' : 'archived' }}</span></td>
                <td>{{ formatDate(h.created_at) }}</td>
                <td>{{ h.created_by_developer_id ? `dev #${h.created_by_developer_id}` : '—' }}</td>
                <td class="afo-note-cell">{{ h.note || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </section>

    <!-- ╔════════════════════ EXPLORER TAB ════════════════════╗ -->
    <section v-show="activeTab === 'explorer'" id="afo-panel-explorer" class="afo-tab-panel" role="tabpanel" aria-labelledby="afo-tab-explorer">
      <!-- Filters -->
      <section class="afo-card">
        <div class="afo-card-head">
          <h2>{{ t('adminFiatOpsView.panels.purchaseExplorer') }}</h2>
          <span class="afo-meta">{{ explorerFailed ? '—' : explorer.total }} match{{ explorer.total === 1 ? '' : 'es' }}</span>
        </div>

        <div class="afo-filter-row">
          <span class="afo-filter-label">Status</span>
          <button
            v-for="s in ['all', 'pending', 'completed', 'failed', 'refunded']"
            :key="s"
            class="afo-filter-pill"
            :class="{
              'afo-filter-pill-active': explorerFilters.statusSet.includes(s),
              [`afo-filter-pill-${s}`]: true,
            }"
            @click="toggleExplorerStatus(s)"
          >{{ s }}</button>
        </div>

        <div class="afo-filter-row">
          <span class="afo-filter-label">Window</span>
          <button
            v-for="w in [1, 7, 30, 90, 365]"
            :key="w"
            class="afo-filter-pill"
            :class="{ 'afo-filter-pill-active': explorerFilters.days === w }"
            @click="explorerFilters.days = w; loadExplorer(0)"
          >{{ w }}d</button>
        </div>

        <div class="afo-filter-search">
          <input v-model="explorerFilters.email" type="text" class="nc-input" placeholder="customer_email contains…" @keyup.enter="loadExplorer(0)" />
          <input v-model="explorerFilters.agent_did" type="text" class="nc-input" placeholder="agent_did exact…" @keyup.enter="loadExplorer(0)" />
          <input v-model="explorerFilters.session_id" type="text" class="nc-input" placeholder="stripe_session_id exact…" @keyup.enter="loadExplorer(0)" />
          <button class="afo-btn afo-btn-primary" @click="loadExplorer(0)" :disabled="explorerLoading">
            <span v-if="explorerLoading">⟳</span>
            <span v-else>SEARCH</span>
          </button>
          <button class="afo-btn afo-btn-ghost" @click="clearExplorerFilters">Clear</button>
        </div>
      </section>

      <!-- Table + drill-down -->
      <section class="afo-card afo-card-table">
        <div v-if="explorerLoading && !explorer.rows.length" class="afo-loading">Loading purchases…</div>
        <ReadFailedNotice v-else-if="explorerFailed" text="The purchases could not be read just now." :retry="() => loadExplorer(explorer.offset)" data-testid="afo-explorer-unread" />
        <div v-else-if="!explorer.rows.length" class="afo-empty afo-empty-inline">No purchases match the current filters.</div>
        <template v-else>
          <table class="afo-table afo-table-explorer">
            <thead>
              <tr>
                <th></th>
                <th>Created</th>
                <th>Status</th>
                <th>EUR</th>
                <th>{{ unit }}</th>
                <th>Tier</th>
                <th>Customer / Agent</th>
                <th>Flow</th>
                <th>Settled</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="p in explorer.rows" :key="p.id">
                <tr class="afo-explorer-row" :class="{ 'afo-explorer-row-open': expandedId === p.id }" @click="toggleExpand(p.id)">
                  <td class="afo-expand-cell">
                    <Icon :name="expandedId === p.id ? 'mdi:chevron-down' : 'mdi:chevron-right'" />
                  </td>
                  <td><time>{{ formatDate(p.created_at) }}</time></td>
                  <td><span class="afo-pill" :class="`afo-pill-status-${p.status}`">{{ p.status }}</span></td>
                  <td class="afo-mono">€{{ p.amount_eur }}</td>
                  <td class="afo-mono">{{ formatBigNum(p.amount_avt, 0) }}</td>
                  <td>{{ p.tier_label }}</td>
                  <td class="afo-truncate" :title="p.customer_email || p.agent_did || ''">
                    {{ p.customer_email || (p.agent_did ? truncMid(p.agent_did, 14, 6) : '—') }}
                  </td>
                  <td>
                    <span v-if="p.anonymous_flow" class="afo-pill afo-pill-anon">anon</span>
                    <span v-else class="afo-pill afo-pill-loggedin">logged-in</span>
                  </td>
                  <td>{{ p.completed_at ? formatRelative(p.completed_at) : '—' }}</td>
                </tr>
                <tr v-if="expandedId === p.id" class="afo-detail-row">
                  <td :colspan="9">
                    <div v-if="detailLoading && !detail" class="afo-loading">Loading detail…</div>
                    <div v-else-if="detail && detail.purchase.id === p.id" class="afo-detail">
                      <!-- Quick-actions strip -->
                      <div class="afo-detail-actions">
                        <button
                          class="afo-btn"
                          :disabled="!canReplay(p) || actionsBusy"
                          @click="doReplay(p)"
                          :title="canReplay(p) ? 'Re-run webhook handler' : 'Only available for pending/failed purchases'"
                        >
                          <Icon name="mdi:replay" /> Replay
                        </button>
                        <button
                          class="afo-btn"
                          :disabled="!canResendMagicLink(p) || actionsBusy"
                          @click="doResendMagicLink(p)"
                          :title="canResendMagicLink(p) ? 'Re-issue & email password-set link' : 'Anon-flow + completed purchases only'"
                        >
                          <Icon name="mdi:email-fast" /> Resend magic-link
                        </button>
                        <button
                          class="afo-btn afo-btn-danger"
                          :disabled="!canRefund(p) || actionsBusy"
                          @click="confirmRefund(p)"
                          :title="canRefund(p) ? 'Issue Stripe refund + flag row (does NOT claw back what it credited)' : 'Completed purchases only'"
                        >
                          <Icon name="mdi:cash-refund" /> Refund
                        </button>
                        <span v-if="actionResult" class="afo-action-result" :class="`afo-action-${actionResult.kind}`">
                          {{ actionResult.text }}
                        </span>
                      </div>

                      <!-- Detail grid -->
                      <div class="afo-detail-grid">
                        <!-- Purchase facts -->
                        <div class="afo-detail-card">
                          <h4><Icon name="mdi:cart-outline" /> Purchase</h4>
                          <dl class="afo-dl">
                            <dt>ID</dt><dd class="afo-mono">{{ detail.purchase.id }}</dd>
                            <dt>Status</dt><dd><span class="afo-pill" :class="`afo-pill-status-${detail.purchase.status}`">{{ detail.purchase.status }}</span></dd>
                            <dt>Tier</dt><dd>{{ detail.purchase.tier_label }} <span class="afo-meta">({{ detail.purchase.avt_per_eur_rate }} {{ unit }}/€)</span></dd>
                            <dt>Amount</dt><dd class="afo-mono">€{{ detail.purchase.amount_eur }} → {{ formatBigNum(detail.purchase.amount_avt, 0) }} {{ unit }}</dd>
                            <dt>Stripe session</dt><dd class="afo-mono afo-truncate">{{ detail.purchase.stripe_session_id }}</dd>
                            <dt v-if="detail.purchase.stripe_event_id">Event id</dt><dd v-if="detail.purchase.stripe_event_id" class="afo-mono">{{ detail.purchase.stripe_event_id }}</dd>
                            <dt v-if="detail.purchase.stripe_payment_intent_id">Payment intent</dt><dd v-if="detail.purchase.stripe_payment_intent_id" class="afo-mono">{{ detail.purchase.stripe_payment_intent_id }}</dd>
                            <dt v-if="detail.purchase.avt_transfer_tx_id">TEG tx</dt><dd v-if="detail.purchase.avt_transfer_tx_id" class="afo-mono">{{ detail.purchase.avt_transfer_tx_id }}</dd>
                            <dt>Created</dt><dd>{{ formatDate(detail.purchase.created_at) }}</dd>
                            <dt v-if="detail.purchase.completed_at">Completed</dt><dd v-if="detail.purchase.completed_at">{{ formatDate(detail.purchase.completed_at) }}</dd>
                            <dt v-if="detail.purchase.refunded_at">Refunded</dt><dd v-if="detail.purchase.refunded_at">{{ formatDate(detail.purchase.refunded_at) }}</dd>
                            <dt v-if="detail.purchase.failure_reason">Failure</dt><dd v-if="detail.purchase.failure_reason" class="afo-failure-text">{{ detail.purchase.failure_reason }}</dd>
                          </dl>
                        </div>

                        <!-- Developer -->
                        <div class="afo-detail-card">
                          <h4><Icon name="mdi:account-circle" /> Developer</h4>
                          <dl v-if="detail.developer" class="afo-dl">
                            <dt>ID</dt><dd>#{{ detail.developer.id }}</dd>
                            <dt>Email</dt><dd>{{ detail.developer.email }}</dd>
                            <dt>Name</dt><dd>{{ detail.developer.name }}</dd>
                            <dt>Verified</dt><dd>{{ detail.developer.is_verified ? '✓ yes' : '✗ no' }}</dd>
                            <dt>Must change pw</dt><dd>{{ detail.developer.must_change_password ? '⚠ yes' : '✓ no' }}</dd>
                            <dt>Magic-link active</dt><dd>{{ detail.developer.has_password_reset_token ? '✓ yes (3-day TTL)' : '✗ no' }}</dd>
                            <dt>Created</dt><dd>{{ formatDate(detail.developer.created_at) }}</dd>
                          </dl>
                          <p v-else class="afo-empty-inline">No developer linked yet.</p>
                        </div>

                        <!-- Agent -->
                        <div class="afo-detail-card">
                          <h4><Icon name="mdi:robot-outline" /> Agent</h4>
                          <dl v-if="detail.agent" class="afo-dl">
                            <dt>DID</dt><dd class="afo-mono afo-truncate">{{ detail.agent.did }}</dd>
                            <dt>Status</dt><dd>{{ detail.agent.status }}</dd>
                            <dt>Liquid {{ unit }}</dt><dd class="afo-mono">{{ formatBigNum(detail.agent.liquid_balance, 6) }}</dd>
                            <dt>Locked {{ unit }}</dt><dd class="afo-mono">{{ formatBigNum(detail.agent.staked_balance, 6) }}</dd>
                            <dt>Owner dev</dt><dd>#{{ detail.agent.creator_developer_id }}</dd>
                            <dt>Created</dt><dd>{{ formatDate(detail.agent.created_at) }}</dd>
                          </dl>
                          <p v-else class="afo-empty-inline">No agent linked yet.</p>
                        </div>

                        <!-- Stripe session -->
                        <div class="afo-detail-card">
                          <h4><Icon name="mdi:credit-card-outline" /> Stripe</h4>
                          <dl v-if="detail.stripe_session" class="afo-dl">
                            <dt>Status</dt><dd>{{ detail.stripe_session.status || '—' }}</dd>
                            <dt>Payment</dt><dd>{{ detail.stripe_session.payment_status || '—' }}</dd>
                            <dt>Amount</dt><dd class="afo-mono">{{ ((detail.stripe_session.amount_total ?? 0) / 100).toFixed(2) }} {{ (detail.stripe_session.currency || '').toUpperCase() }}</dd>
                            <dt>Session</dt><dd class="afo-mono afo-truncate">{{ detail.stripe_session.id }}</dd>
                            <dt v-if="detail.stripe_session.payment_intent">PI</dt><dd v-if="detail.stripe_session.payment_intent" class="afo-mono">{{ detail.stripe_session.payment_intent }}</dd>
                          </dl>
                          <p v-else class="afo-empty-inline">Stripe lookup unavailable (offline / not yet sent / pending session).</p>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Pagination -->
          <div class="afo-pager">
            <button class="afo-btn afo-btn-ghost" :disabled="explorer.offset === 0 || explorerLoading" @click="loadExplorer(Math.max(0, explorer.offset - explorer.limit))">
              ← Prev
            </button>
            <span class="afo-meta">{{ explorer.offset + 1 }}–{{ Math.min(explorer.offset + explorer.rows.length, explorer.total) }} of {{ explorer.total }}</span>
            <button class="afo-btn afo-btn-ghost" :disabled="(explorer.offset + explorer.limit) >= explorer.total || explorerLoading" @click="loadExplorer(explorer.offset + explorer.limit)">
              Next →
            </button>
          </div>
        </template>
      </section>
    </section>

    <!-- ────────── Flare Ops tab ────────── -->
    <section v-show="activeTab === 'flares'" id="afo-panel-flares" class="afo-tab-panel" role="tabpanel" aria-labelledby="afo-tab-flares">
      <header class="afo-section-head">
        <div>
          <h2 class="afo-h2">{{ t('adminFiatOpsView.panels.flareOperations') }}</h2>
          <p class="afo-sub">
            Grant or revoke backer flares. Payment tiers (Sentinel, Architect, Founder) are normally
            obtained via fiat; Operator and Commander tiers are admin-grant only.
          </p>
        </div>
        <button class="afo-btn afo-btn-primary" @click="openGrantPanel(null)">
          <Icon name="mdi:plus" /> Grant flare
        </button>
      </header>

      <!-- Grant panel (collapsible) -->
      <section v-if="grantOpen" class="afo-card afo-flare-grant">
        <div class="afo-card-head">
          <Icon name="mdi:shield-star" />
          <h3>{{ grantForm.developer_id ? `Grant to dev #${grantForm.developer_id}` : 'Grant flare to developer' }}</h3>
          <button class="afo-btn afo-btn-ghost afo-btn-sm" @click="grantOpen = false">Close</button>
        </div>

        <!-- Tier picker — visual chips (one per tier) -->
        <div class="afo-flare-tier-row">
          <button
            v-for="tier in ALL_FLARE_TIERS"
            :key="tier"
            type="button"
            class="afo-flare-tier-chip"
            :class="{ 'afo-flare-tier-chip-active': grantForm.tier === tier }"
            @click="grantForm.tier = tier"
          >
            <FlareBadge :tier="tier" size="sm" :show-label="true" />
            <span class="afo-flare-rank">rank {{ FLARE_RANK[tier] }}</span>
          </button>
        </div>

        <div class="afo-flare-grant-grid">
          <div class="afo-form-group">
            <label class="afo-label">Developer ID</label>
            <input v-model.number="grantForm.developer_id" type="number" class="nc-input" placeholder="e.g. 137" />
          </div>
          <div class="afo-form-group">
            <label class="afo-label">Force override <span class="afo-label-sub">(bypass higher-rank-wins)</span></label>
            <label class="afo-toggle-row">
              <input v-model="grantForm.force" type="checkbox" />
              <span>{{ grantForm.force ? 'Force on — overwrites existing tier' : 'Force off — respects rank order' }}</span>
            </label>
          </div>
          <div class="afo-form-group afo-form-full">
            <label class="afo-label">Display name <span class="afo-label-sub">optional, max 80</span></label>
            <input v-model="grantForm.display_name" type="text" :maxlength="80" class="nc-input" placeholder="Acme Studios" />
          </div>
          <div class="afo-form-group afo-form-full">
            <label class="afo-label">Tagline <span class="afo-label-sub">optional, max 160</span></label>
            <input v-model="grantForm.tagline" type="text" :maxlength="160" class="nc-input" placeholder="Funding open AI agents from genesis." />
          </div>
          <div class="afo-form-group">
            <label class="afo-label">Cause <span class="afo-label-sub">optional, max 80</span></label>
            <input v-model="grantForm.cause" type="text" :maxlength="80" class="nc-input" placeholder="Open-source AI" />
          </div>
          <div class="afo-form-group">
            <label class="afo-label">Accent color <span class="afo-label-sub">hex, optional</span></label>
            <div class="afo-color-row">
              <input v-model="grantForm.accent_color" type="text" :maxlength="9" class="nc-input afo-color-input" placeholder="#FCD34D" />
              <input v-model="accentPicker" type="color" class="afo-color-picker" />
              <FlareBadge :tier="grantForm.tier" size="md" :show-label="false" :accent-color="grantForm.accent_color || null" />
            </div>
          </div>
          <div class="afo-form-group">
            <label class="afo-label">Logo URL <span class="afo-label-sub">https://, optional</span></label>
            <input v-model="grantForm.logo_url" type="url" :maxlength="500" class="nc-input" placeholder="https://your.site/logo.png" />
          </div>
          <div class="afo-form-group">
            <label class="afo-label">Link URL <span class="afo-label-sub">https://, optional</span></label>
            <input v-model="grantForm.link_url" type="url" :maxlength="500" class="nc-input" placeholder="https://your.site" />
          </div>
          <div class="afo-form-group afo-form-full">
            <label class="afo-label">Stamp on agent DID <span class="afo-label-sub">optional</span></label>
            <input v-model="grantForm.agent_did" type="text" :maxlength="200" class="nc-input" placeholder="did:theprotocol:… (must belong to developer)" />
          </div>
        </div>
        <div class="afo-flare-actions">
          <button class="afo-btn afo-btn-primary" :disabled="!grantForm.developer_id || flareSaving" @click="submitGrant">
            <Icon v-if="flareSaving" name="mdi:loading" class="afo-spin" />
            <Icon v-else name="mdi:shield-star" />
            {{ flareSaving ? 'Granting…' : `Grant ${grantForm.tier}` }}
          </button>
          <button class="afo-btn afo-btn-ghost" @click="resetGrantForm">
            <Icon name="mdi:undo" /> Reset
          </button>
        </div>
        <p v-if="flareError" class="afo-error">{{ flareError }}</p>
        <p v-if="flareSuccess" class="afo-success">
          <Icon name="mdi:shield-check" /> {{ flareSuccess }}
        </p>
      </section>

      <!-- Existing flare-bearing developers -->
      <section class="afo-card">
        <div class="afo-card-head">
          <Icon name="mdi:account-star" />
          <h3>Flare-bearing developers <span class="afo-counter">{{ flaresFailed && !flareList.length ? '—' : flareList.length }}</span></h3>
          <button class="afo-btn afo-btn-ghost afo-btn-sm" :disabled="flareLoading" @click="loadFlareList">
            <Icon name="mdi:refresh" /> Refresh
          </button>
        </div>
        <p v-if="flareLoading" class="afo-empty">
          <Icon name="mdi:loading" class="afo-spin" /> Loading flares…
        </p>
        <ReadFailedNotice v-else-if="flaresFailed && !flareList.length" text="The flare holders could not be read just now." :retry="loadFlareList" data-testid="afo-flares-unread" />
        <p v-else-if="flareList.length === 0" class="afo-empty">
          No flares granted yet. Click <strong>Grant flare</strong> above to start.
        </p>
        <table v-else class="afo-table afo-table-flares">
          <thead>
            <tr>
              <th>Tier</th>
              <th>Dev</th>
              <th>Display name</th>
              <th>Tagline / cause</th>
              <th>Granted</th>
              <th class="afo-th-actions"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in flareList" :key="row.developer_id">
              <td>
                <FlareBadge
                  :tier="row.flare_tier"
                  :display-name="row.flare_display_name"
                  :tagline="row.flare_tagline"
                  :cause="row.flare_cause"
                  :accent-color="row.flare_accent_color"
                  :flare-id="row.flare_id"
                  size="sm"
                  :show-label="true"
                />
              </td>
              <td class="afo-mono">#{{ row.developer_id }}<br><small>{{ row.email }}</small></td>
              <td>{{ row.flare_display_name || '—' }}</td>
              <td class="afo-tagline-cell">
                <p v-if="row.flare_tagline">{{ row.flare_tagline }}</p>
                <p v-if="row.flare_cause" class="afo-cause-pill">{{ row.flare_cause }}</p>
              </td>
              <td class="afo-mono"><small>{{ formatDate(row.flare_granted_at) }}</small></td>
              <td class="afo-td-actions">
                <button class="afo-btn afo-btn-sm afo-btn-ghost" @click="openGrantPanel(row)" title="Edit / re-grant">
                  <Icon name="mdi:cog" /> Edit
                </button>
                <button class="afo-btn afo-btn-sm afo-btn-danger" @click="confirmRevoke(row)" title="Revoke">
                  <Icon name="mdi:trash-2" /> Revoke
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </section>

    <!-- Revoke confirm modal -->
    <div v-if="revokingRow" class="afo-modal-backdrop" @click.self="revokingRow = null">
      <div class="afo-modal">
        <h3>Revoke flare</h3>
        <p>
          This wipes the flare from developer <strong>#{{ revokingRow.developer_id }}</strong>
          ({{ revokingRow.email }}) and from <strong>every agent they own</strong>.
          <br><br>
          The <code>flare_id</code> {{ (revokingRow.flare_id || '').slice(0, 8) }}… will be released —
          a future re-grant gets a fresh UUID.
        </p>
        <p class="afo-confirm-prompt">Type <code>REVOKE</code> to confirm:</p>
        <input v-model="revokeConfirmText" type="text" class="nc-input" autofocus />
        <div class="afo-modal-actions">
          <button class="afo-btn" @click="revokingRow = null">Cancel</button>
          <button class="afo-btn afo-btn-danger" :disabled="revokeConfirmText !== 'REVOKE' || flareSaving" @click="submitRevoke">
            <Icon v-if="flareSaving" name="mdi:loading" class="afo-spin" />
            <Icon v-else name="mdi:trash-2" />
            Revoke
          </button>
        </div>
      </div>
    </div>

    <!-- Save-config confirm modal (pricing tab) -->
    <div v-if="confirmingSave" class="afo-modal-backdrop" @click.self="confirmingSave = false">
      <div class="afo-modal">
        <h3>Confirm pricing change</h3>
        <p>This will install a new version and become the live pricing for every fiat purchase. Cannot be undone (only superseded by another version).</p>
        <div class="afo-modal-summary">
          <div><span>New version</span><strong>v{{ (history[0]?.version || 0) + 1 }}</strong></div>
          <div><span>Tiers</span><strong>{{ draft.tiers.length }}</strong></div>
          <div><span>Range</span><strong>{{ draft.currency === 'EUR' ? '€' : '' }}{{ draft.min_eur }}–{{ draft.currency === 'EUR' ? '€' : '' }}{{ draft.max_eur }}</strong></div>
        </div>
        <p class="afo-confirm-prompt">Type <code>I UNDERSTAND</code> to confirm:</p>
        <input v-model="confirmText" type="text" class="nc-input" autofocus />
        <div class="afo-modal-actions">
          <button class="afo-btn" @click="confirmingSave = false">Cancel</button>
          <button class="afo-btn afo-btn-primary" :disabled="confirmText.trim() !== 'I UNDERSTAND' || saving" @click="doSave">
            CONFIRM SAVE
          </button>
        </div>
      </div>
    </div>

    <!-- Refund confirm modal -->
    <div v-if="refundTarget" class="afo-modal-backdrop" @click.self="refundTarget = null">
      <div class="afo-modal afo-modal-danger">
        <h3>Issue Stripe refund?</h3>
        <p>This refunds €{{ refundTarget.amount_eur }} to the card on the original Stripe charge. What it credited is <strong>NOT</strong> clawed back from the agent — review enforcement separately.</p>
        <div class="afo-modal-summary">
          <div><span>Purchase</span><strong class="afo-mono">{{ refundTarget.id.slice(0, 8) }}…</strong></div>
          <div><span>Amount</span><strong>€{{ refundTarget.amount_eur }}</strong></div>
          <div><span>{{ unit }} credited</span><strong>{{ formatBigNum(refundTarget.amount_avt, 0) }}</strong></div>
        </div>
        <p class="afo-confirm-prompt">Type <code>REFUND</code> to confirm:</p>
        <input v-model="refundConfirmText" type="text" class="nc-input" autofocus />
        <div class="afo-modal-actions">
          <button class="afo-btn" @click="refundTarget = null">Cancel</button>
          <button class="afo-btn afo-btn-danger" :disabled="refundConfirmText.trim() !== 'REFUND' || actionsBusy" @click="doRefund">
            CONFIRM REFUND
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, reactive, onMounted, onUnmounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import FlareBadge from '@/components/common/FlareBadge.vue'
import { useI18n } from '@/composables/useI18n'
import {
  fiatPricingAdminService,
  fiatOpsAdminService,
  type PricingConfigRow,
  type SimulationResponse,
  type AdminPurchaseRow,
  type AdminPurchaseDetail,
  type FiatStatsResponse,
} from '@/services/api/fiatOnramp'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'

const { t, tp } = useI18n()

// D6-835 (agentvault2-d6, 2026-10-25): the page named AVT on every frame; a purchase credits the fiat genesis
// registry's own unit (AVT on Frame A, SBXA on sbx-alpha), and a frame without the on-ramp shows its own (ECU on EU).
// A neutral word while the config is unread: never a wrong unit.
// D6-836: the switch as this registry says it; the notice shows only on the registry's own answer.
const { config: regCfg, readOk: regReadOk, localCurrency } = useRegistryConfig()
const unit = computed(() => localCurrency.value || 'units')
const fiatOffRead = computed(() => regReadOk.value && regCfg.value.fiat_onramp_enabled !== true)

// ── Tab state ──
type TabKey = 'overview' | 'pricing' | 'explorer' | 'flares'
const activeTab = ref<TabKey>('overview')
const tabs = computed(() => [
  { key: 'overview' as TabKey, label: t('adminFiatOpsView.tabs.overview'), icon: 'mdi:view-dashboard-outline', badge: '' },
  { key: 'pricing' as TabKey, label: t('adminFiatOpsView.tabs.pricing'), icon: 'mdi:tune-vertical', badge: active.value ? `v${active.value.version}` : '' },
  { key: 'explorer' as TabKey, label: t('adminFiatOpsView.tabs.explorer'), icon: 'mdi:database-search-outline', badge: explorer.total ? String(explorer.total) : '' },
  { key: 'flares' as TabKey, label: t('adminFiatOpsView.tabs.flares'), icon: 'mdi:shield-star', badge: flareList.length ? String(flareList.length) : '' },
])

// ── Stats / Overview ──
const stats = ref<FiatStatsResponse | null>(null)
const statsLoading = ref(false)
// §FESUITE (the failing-reads census, V0569 at sbx-beta, 2026-10-04): with every read failed the overview said "No data
// yet — fund a purchase to see the dashboard come alive." while the frame had purchases. Nothing read is not "no data".
const statsFailed = ref(false)
const statsWindow = ref(30)
// §FESUITE (V0578): the window the stats on screen answer. A failed (or slower) read for another window left the earlier
// window's KPIs under the new window's button; the window buttons stay live during a read, so an earlier window's answer
// landing after a later one replaced it too.
const statsFor = ref<number | null>(null)
let statsSeq = 0
const statsCurrent = computed(() => !!stats.value && statsFor.value === statsWindow.value)
// Recent purchases derive from the Explorer's loaded rows (single source of truth).
// Avoids a second listPurchases round-trip + a state-divergence class of bugs.
// `explorer.rows` populates on mount via loadExplorer(0).

async function loadStats() {
  const seq = ++statsSeq
  const asked = statsWindow.value
  statsLoading.value = true
  try {
    // Stats + recent-10 in parallel; both feed the Overview tab.
    const [s, r] = await Promise.all([
      fiatOpsAdminService.getStats(asked),
      fiatOpsAdminService.listPurchases({ days: asked, limit: 10, offset: 0 }),
    ])
    if (seq !== statsSeq) return   // an earlier window's answer landing after a later one never replaces it
    stats.value = s
    statsFor.value = asked
    recentPurchases.value = (r && Array.isArray(r.rows)) ? r.rows : []
    statsFailed.value = false
  } catch (e) {
    if (seq !== statsSeq) return
    console.error('[admin-fiat-ops] loadStats failed', e)
    statsFailed.value = true
  } finally {
    if (seq === statsSeq) statsLoading.value = false
  }
}

// ── Sparkline math (inline SVG, dynamic dimensions) ──
const sparkW = 760
const sparkH = 120

interface SparkPoint { x: number; y: number; day: string; eur: string; purchases: number }

const sparkPoints = computed<SparkPoint[]>(() => {
  if (!stats.value || !stats.value.daily_revenue.length) return []
  const days = stats.value.daily_revenue
  const max = Math.max(...days.map(d => Number(d.eur))) || 1
  const padX = 6
  const innerW = sparkW - padX * 2
  const padTop = 10
  const padBot = 10
  const innerH = sparkH - padTop - padBot
  const stepX = days.length === 1 ? 0 : innerW / (days.length - 1)
  return days.map((d, i) => ({
    x: padX + (days.length === 1 ? innerW / 2 : stepX * i),
    y: padTop + innerH - (Number(d.eur) / max) * innerH,
    day: d.day,
    eur: d.eur,
    purchases: d.purchases,
  }))
})

const sparkLinePath = computed(() => {
  const pts = sparkPoints.value
  if (!pts.length) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
})

const sparkAreaPath = computed(() => {
  const pts = sparkPoints.value
  if (!pts.length) return ''
  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  const first = pts[0]
  return `${line} L${last.x.toFixed(1)},${sparkH - 6} L${first.x.toFixed(1)},${sparkH - 6} Z`
})

const sparkPeakLabel = computed(() => {
  if (!stats.value || !stats.value.daily_revenue.length) return ''
  const peak = stats.value.daily_revenue.reduce((max, d) => (Number(d.eur) > Number(max.eur) ? d : max))
  return `€${peak.eur} on ${peak.day}`
})

function tierSharePct(row: { count: number }): number {
  if (!stats.value) return 0
  const total = stats.value.tier_share.reduce((s, r) => s + r.count, 0)
  return total ? Math.round((row.count / total) * 100) : 0
}

// Recent purchases — explicit ref so reactivity is unambiguous.
// Loaded by loadStats() so they're refreshed when the window changes.
const recentPurchases = ref<AdminPurchaseRow[]>([])

// ── Pricing tab state (existing logic, ported) ──
const pricingLoading = ref(true)
const pricingLoaded = ref(false)
const fallbackInUse = ref(false)
const active = ref<PricingConfigRow | null>(null)
const history = ref<PricingConfigRow[]>([])

interface Tier { floor_eur: string; avt_per_eur: string; tier_label: string; bonus_label: string }
const draft = reactive<{ tiers: Tier[]; min_eur: string; max_eur: string; currency: string }>({
  tiers: [], min_eur: '1.00', max_eur: '500.00', currency: 'EUR',
})
const note = ref('')
const validationErrors = ref<string[]>([])
const validating = ref(false)
const saving = ref(false)
const confirmingSave = ref(false)
const confirmText = ref('')

const sim = reactive({
  startingTreasury: '17700130',
  startingFeeCollector: '2920000',
  waterfall: 'fee_collector,treasury',
  scenarioTemplate: 'mixed_realistic',
  purchasesText: '',
})
const simulating = ref(false)
const simResult = ref<SimulationResponse | null>(null)

const canSave = computed(() => {
  if (!note.value.trim() || note.value.trim().length < 4) return false
  if (validationErrors.value.length) return false
  if (!draft.tiers.length) return false
  return true
})

async function loadPricing() {
  pricingLoading.value = true
  try {
    const r = await fiatPricingAdminService.getPricing()
    active.value = r.active
    history.value = r.history || []
    fallbackInUse.value = !!r.fallback_in_use
    if (active.value) resetDraftFromActive()
    pricingLoaded.value = true
  } catch (e) {
    console.error('[admin-fiat-ops] loadPricing failed', e)
    pricingLoaded.value = false
  } finally {
    pricingLoading.value = false
  }
}

function resetDraftFromActive() {
  if (!active.value) return
  draft.currency = active.value.config.currency
  draft.min_eur = active.value.config.min_eur
  draft.max_eur = active.value.config.max_eur
  draft.tiers = active.value.config.tiers.map(t => ({
    floor_eur: t.floor_eur,
    avt_per_eur: t.avt_per_eur,
    tier_label: t.tier_label,
    bonus_label: t.bonus_label || '',
  }))
  validationErrors.value = []
}

function addTier() {
  draft.tiers.push({ floor_eur: '0', avt_per_eur: '0', tier_label: `tier_${draft.tiers.length + 1}`, bonus_label: '' })
}
function removeTier(idx: number) {
  if (draft.tiers.length > 1) draft.tiers.splice(idx, 1)
}

watch(
  () => [draft.tiers, draft.min_eur, draft.max_eur, draft.currency],
  () => { validationErrors.value = [] },
  { deep: true },
)

function buildConfig() {
  return {
    tiers: draft.tiers.map(t => ({
      floor_eur: t.floor_eur,
      avt_per_eur: t.avt_per_eur,
      tier_label: t.tier_label,
      bonus_label: t.bonus_label || '',
    })),
    min_eur: draft.min_eur,
    max_eur: draft.max_eur,
    currency: draft.currency,
  }
}

async function runValidate() {
  validating.value = true
  validationErrors.value = []
  try {
    const r = await fiatPricingAdminService.validatePricing(buildConfig(), note.value || 'validation-only')
    if (!r.valid) validationErrors.value = r.errors
  } catch (e: any) {
    validationErrors.value = [e?.response?.data?.detail || String(e)]
  } finally {
    validating.value = false
  }
}

function confirmSave() {
  confirmText.value = ''
  confirmingSave.value = true
}

async function doSave() {
  if (confirmText.value.trim() !== 'I UNDERSTAND') return
  saving.value = true
  try {
    await fiatPricingAdminService.putPricing(buildConfig(), note.value.trim())
    confirmingSave.value = false
    await loadPricing()
    note.value = ''
  } catch (e: any) {
    validationErrors.value = [e?.response?.data?.detail || String(e)]
    confirmingSave.value = false
  } finally {
    saving.value = false
  }
}

const SCENARIOS: Record<string, () => string[]> = {
  custom: () => sim.purchasesText.split('\n').map(s => s.trim()).filter(Boolean),
  even_5_eur: () => Array(100).fill('5'),
  even_20_eur: () => Array(100).fill('20'),
  even_100_eur: () => Array(100).fill('100'),
  whales_only: () => Array(10).fill('500'),
  mixed_realistic: () => {
    const out: string[] = []
    for (let i = 0; i < 700; i++) out.push('5')
    for (let i = 0; i < 250; i++) out.push('20')
    for (let i = 0; i < 50; i++) out.push('100')
    return out
  },
  exhaustion_test: () => Array(10000).fill('100'),
}

function applyScenarioTemplate() {
  if (sim.scenarioTemplate === 'custom') return
  const arr = SCENARIOS[sim.scenarioTemplate]?.() || []
  sim.purchasesText = arr.length > 30
    ? `${arr.slice(0, 10).join('\n')}\n... (${arr.length} total entries — generated)\n`
    : arr.join('\n')
}

async function runSimulate() {
  simulating.value = true
  simResult.value = null
  try {
    const purchases =
      sim.scenarioTemplate === 'custom'
        ? sim.purchasesText.split('\n').map(s => s.trim()).filter(Boolean)
        : SCENARIOS[sim.scenarioTemplate]()
    const wf = sim.waterfall.split(',').map(s => s.trim()).filter(Boolean)
    simResult.value = await fiatPricingAdminService.simulate({
      config: buildConfig(),
      purchases_eur: purchases,
      starting_treasury_avt: sim.startingTreasury,
      starting_fee_collector_avt: sim.startingFeeCollector,
      waterfall: wf,
    })
  } catch (e: any) {
    alert(`Simulation failed: ${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    simulating.value = false
  }
}

// ── Explorer tab state ──
interface ExplorerFilters { statusSet: string[]; days: number; email: string; agent_did: string; session_id: string }
const explorerFilters = reactive<ExplorerFilters>({
  statusSet: ['all'],
  days: 30,
  email: '',
  agent_did: '',
  session_id: '',
})
const explorer = reactive({
  rows: [] as AdminPurchaseRow[],
  total: 0,
  limit: 25,
  offset: 0,
})
const explorerLoading = ref(false)
/** §FESUITE V0577: a failed search said "No purchases match the current filters." (and left the previous filters' rows
 *  and total in place for the next search); only the newest search lands */
const explorerFailed = ref(false)
let explorerSeq = 0
const expandedId = ref<string | null>(null)
const detail = ref<AdminPurchaseDetail | null>(null)
const detailLoading = ref(false)
const actionsBusy = ref(false)
const actionResult = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const refundTarget = ref<AdminPurchaseRow | null>(null)
const refundConfirmText = ref('')

function toggleExplorerStatus(s: string) {
  if (s === 'all') {
    explorerFilters.statusSet = ['all']
  } else {
    const current = explorerFilters.statusSet.filter(x => x !== 'all')
    if (current.includes(s)) {
      const next = current.filter(x => x !== s)
      explorerFilters.statusSet = next.length ? next : ['all']
    } else {
      explorerFilters.statusSet = [...current, s]
    }
  }
  loadExplorer(0)
}

function clearExplorerFilters() {
  explorerFilters.statusSet = ['all']
  explorerFilters.days = 30
  explorerFilters.email = ''
  explorerFilters.agent_did = ''
  explorerFilters.session_id = ''
  loadExplorer(0)
}

async function loadExplorer(offset: number) {
  const mine = ++explorerSeq
  explorerLoading.value = true
  try {
    const status = explorerFilters.statusSet.includes('all')
      ? undefined
      : explorerFilters.statusSet.join(',')
    const r = await fiatOpsAdminService.listPurchases({
      status,
      email: explorerFilters.email.trim() || undefined,
      agent_did: explorerFilters.agent_did.trim() || undefined,
      session_id: explorerFilters.session_id.trim() || undefined,
      days: explorerFilters.days,
      limit: explorer.limit,
      offset,
    })
    if (mine !== explorerSeq) return
    explorerFailed.value = false
    explorer.rows = r.rows
    explorer.total = r.total
    explorer.offset = r.offset
    if (expandedId.value && !r.rows.find(x => x.id === expandedId.value)) {
      expandedId.value = null
      detail.value = null
    }
  } catch (e) {
    if (mine !== explorerSeq) return
    explorerFailed.value = true
    console.error('[admin-fiat-ops] loadExplorer failed', e)
  } finally {
    if (mine === explorerSeq) explorerLoading.value = false
  }
}

async function toggleExpand(id: string) {
  if (expandedId.value === id) {
    expandedId.value = null
    detail.value = null
    actionResult.value = null
    return
  }
  expandedId.value = id
  detail.value = null
  actionResult.value = null
  detailLoading.value = true
  try {
    detail.value = await fiatOpsAdminService.getPurchase(id)
  } catch (e: any) {
    actionResult.value = { kind: 'err', text: `Detail load failed: ${e?.response?.data?.detail || e?.message}` }
  } finally {
    detailLoading.value = false
  }
}

function canReplay(p: AdminPurchaseRow): boolean {
  return p.status === 'pending' || p.status === 'failed'
}
function canResendMagicLink(p: AdminPurchaseRow): boolean {
  return p.anonymous_flow && p.status === 'completed'
}
function canRefund(p: AdminPurchaseRow): boolean {
  return p.status === 'completed'
}

async function doReplay(p: AdminPurchaseRow) {
  actionsBusy.value = true
  actionResult.value = null
  try {
    const r = await fiatOpsAdminService.replayPurchase(p.id)
    actionResult.value = { kind: r.status === 'completed' ? 'ok' : 'err', text: `Replay → ${r.status}: ${r.detail || ''}` }
    await loadExplorer(explorer.offset)
    detail.value = await fiatOpsAdminService.getPurchase(p.id)
  } catch (e: any) {
    actionResult.value = { kind: 'err', text: e?.response?.data?.detail || String(e) }
  } finally {
    actionsBusy.value = false
  }
}

async function doResendMagicLink(p: AdminPurchaseRow) {
  actionsBusy.value = true
  actionResult.value = null
  try {
    const r = await fiatOpsAdminService.resendMagicLink(p.id)
    actionResult.value = { kind: 'ok', text: r.detail || 'Magic-link sent' }
    detail.value = await fiatOpsAdminService.getPurchase(p.id)
  } catch (e: any) {
    actionResult.value = { kind: 'err', text: e?.response?.data?.detail || String(e) }
  } finally {
    actionsBusy.value = false
  }
}

function confirmRefund(p: AdminPurchaseRow) {
  refundConfirmText.value = ''
  refundTarget.value = p
}

async function doRefund() {
  if (!refundTarget.value) return
  if (refundConfirmText.value.trim() !== 'REFUND') return
  actionsBusy.value = true
  actionResult.value = null
  const target = refundTarget.value
  try {
    const r = await fiatOpsAdminService.refund(target.id)
    actionResult.value = { kind: 'ok', text: r.detail || 'Refunded' }
    refundTarget.value = null
    await loadExplorer(explorer.offset)
    detail.value = await fiatOpsAdminService.getPurchase(target.id)
  } catch (e: any) {
    actionResult.value = { kind: 'err', text: e?.response?.data?.detail || String(e) }
    refundTarget.value = null
  } finally {
    actionsBusy.value = false
  }
}

// ── Lifecycle ──
const loadingAny = computed(() => statsLoading.value || pricingLoading.value || explorerLoading.value)

async function refreshAll() {
  await Promise.all([loadStats(), loadPricing(), loadExplorer(explorer.offset)])
}

function openInExplorer(purchaseId: string) {
  activeTab.value = 'explorer'
  // After tab switch, expand the selected row so the user lands on its drill-down.
  setTimeout(() => { toggleExpand(purchaseId) }, 80)
}

onMounted(async () => {
  await Promise.all([loadStats(), loadPricing(), loadExplorer(0), loadFlareList()])
  applyScenarioTemplate()
})

// ────────────────────────────────────────────────────────────
// PB-1 Flare Ops (Phase O, 2026-05-09)
// Admin UI for grant/revoke endpoints already shipped in Phase L:
//   POST /api/v1/admin/fiat/flare/grant
//   POST /api/v1/admin/fiat/flare/revoke/{developer_id}
// Listing endpoint is GET /api/v1/admin/fiat/flares (added in this phase).
// ────────────────────────────────────────────────────────────

interface FlareListRow {
  developer_id: number
  email: string
  name: string
  flare_id: string | null
  flare_tier: 'sentinel' | 'architect' | 'founder' | 'operator' | 'commander'
  flare_granted_at: string | null
  flare_display_name: string | null
  flare_tagline: string | null
  flare_logo_url: string | null
  flare_link_url: string | null
  flare_cause: string | null
  flare_accent_color: string | null
}

const ALL_FLARE_TIERS: Array<FlareListRow['flare_tier']> =
  ['sentinel', 'architect', 'founder', 'operator', 'commander']
const FLARE_RANK: Record<FlareListRow['flare_tier'], number> = {
  sentinel: 1, architect: 2, founder: 3, operator: 50, commander: 99,
}

const flareList = ref<FlareListRow[]>([])
const flareLoading = ref(false)
/** §FESUITE V0577: a failed read said "No flares granted yet. Click Grant flare above to start." under a 0 count */
const flaresFailed = ref(false)
const flareSaving = ref(false)
const flareError = ref('')
const flareSuccess = ref('')

const grantOpen = ref(false)
const grantForm = reactive({
  developer_id: 0,
  tier: 'sentinel' as FlareListRow['flare_tier'],
  agent_did: '',
  display_name: '',
  tagline: '',
  logo_url: '',
  link_url: '',
  cause: '',
  accent_color: '',
  force: false,
})
// the colour picker shows the default accent while none is set; v-model alongside :value was a template compile error
// under the test compiler, which kept this view out of every component test (§FESUITE V0577)
const accentPicker = computed({
  get: () => grantForm.accent_color || '#00D2D2',
  set: (v: string) => { grantForm.accent_color = v },
})

const revokingRow = ref<FlareListRow | null>(null)
const revokeConfirmText = ref('')

async function loadFlareList() {
  flareLoading.value = true
  try {
    const r = await apiClient.get<FlareListRow[]>('/admin/fiat/flares')
    flareList.value = r.data || []
    flaresFailed.value = false
  } catch (e: any) {
    // a registry without the route (404) has no list to show; any other failure says so
    flaresFailed.value = e?.response?.status !== 404
  } finally {
    flareLoading.value = false
  }
}

function openGrantPanel(row: FlareListRow | null) {
  flareError.value = ''
  flareSuccess.value = ''
  if (row) {
    // Edit existing — pre-fill from the row
    grantForm.developer_id = row.developer_id
    grantForm.tier = row.flare_tier
    grantForm.display_name = row.flare_display_name || ''
    grantForm.tagline = row.flare_tagline || ''
    grantForm.cause = row.flare_cause || ''
    grantForm.logo_url = row.flare_logo_url || ''
    grantForm.link_url = row.flare_link_url || ''
    grantForm.accent_color = row.flare_accent_color || ''
    grantForm.agent_did = ''
    grantForm.force = true   // editing implies override
  } else {
    resetGrantForm()
  }
  grantOpen.value = true
}

function resetGrantForm() {
  grantForm.developer_id = 0
  grantForm.tier = 'sentinel'
  grantForm.agent_did = ''
  grantForm.display_name = ''
  grantForm.tagline = ''
  grantForm.logo_url = ''
  grantForm.link_url = ''
  grantForm.cause = ''
  grantForm.accent_color = ''
  grantForm.force = false
  flareError.value = ''
  flareSuccess.value = ''
}

async function submitGrant() {
  flareError.value = ''
  flareSuccess.value = ''
  if (!grantForm.developer_id || grantForm.developer_id <= 0) {
    flareError.value = 'Developer ID required.'
    return
  }
  flareSaving.value = true
  try {
    // Strip empty strings — backend treats null/missing as "leave alone".
    const payload: Record<string, unknown> = {
      developer_id: grantForm.developer_id,
      tier: grantForm.tier,
      force: grantForm.force,
    }
    if (grantForm.agent_did.trim())     payload.agent_did     = grantForm.agent_did.trim()
    if (grantForm.display_name.trim())  payload.display_name  = grantForm.display_name.trim()
    if (grantForm.tagline.trim())       payload.tagline       = grantForm.tagline.trim()
    if (grantForm.logo_url.trim())      payload.logo_url      = grantForm.logo_url.trim()
    if (grantForm.link_url.trim())      payload.link_url      = grantForm.link_url.trim()
    if (grantForm.cause.trim())         payload.cause         = grantForm.cause.trim()
    if (grantForm.accent_color.trim())  payload.accent_color  = grantForm.accent_color.trim()

    await apiClient.post('/admin/fiat/flare/grant', payload)
    flareSuccess.value = `${grantForm.tier} flare granted to dev #${grantForm.developer_id}.`
    await loadFlareList()
  } catch (e: any) {
    flareError.value = e?.response?.data?.detail || e?.message || 'Grant failed.'
  } finally {
    flareSaving.value = false
  }
}

function confirmRevoke(row: FlareListRow) {
  revokingRow.value = row
  revokeConfirmText.value = ''
}

async function submitRevoke() {
  if (!revokingRow.value) return
  if (revokeConfirmText.value !== 'REVOKE') return
  flareSaving.value = true
  try {
    await apiClient.post(`/admin/fiat/flare/revoke/${revokingRow.value.developer_id}`)
    flareSuccess.value = `Flare revoked from dev #${revokingRow.value.developer_id}.`
    revokingRow.value = null
    revokeConfirmText.value = ''
    await loadFlareList()
  } catch (e: any) {
    flareError.value = e?.response?.data?.detail || e?.message || 'Revoke failed.'
  } finally {
    flareSaving.value = false
  }
}

// ── Formatters ──
function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(appLocale(), { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}
function formatRelative(iso: string): string {
  try {
    const d = new Date(iso)
    const now = Date.now()
    const diff = (now - d.getTime()) / 1000
    if (diff < 60) return `${Math.floor(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`
    return formatDate(iso)
  } catch { return iso }
}
function formatBigNum(s: string | number, decimals = 2): string {
  try {
    const n = typeof s === 'number' ? s : Number(s)
    if (isNaN(n)) return String(s)
    return n.toLocaleString(appLocale(), { maximumFractionDigits: decimals, minimumFractionDigits: decimals === 0 ? 0 : Math.min(decimals, 2) })
  } catch { return String(s) }
}
function truncMid(s: string, head = 12, tail = 8): string {
  if (!s || s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}
</script>

<style scoped>
/* ──────────────────────────────────────────────────────────────
 * Base layout + hero
 * ────────────────────────────────────────────────────────────── */
.afo-root { max-width: 1200px; margin: 0 auto; padding: 24px 20px 80px; position: relative; z-index: 1; }
.afo-hero { text-align: center; margin-bottom: 24px; padding-top: 4px; }
.afo-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 10px;
  background: rgba(0, 210, 210, 0.08);
  border: 1px solid rgba(0, 210, 210, 0.22);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--nc-primary, #00d2d2);
  margin-bottom: 14px;
}
.afo-chip-dot {
  width: 6px; height: 6px;
  background: var(--nc-primary, #00d2d2);
  border-radius: 50%;
  box-shadow: 0 0 0 0 var(--nc-primary, #00d2d2);
  animation: afo-pulse 2.4s ease-in-out infinite;
}
@keyframes afo-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0, 210, 210, 0.55); }
  50%      { box-shadow: 0 0 0 6px rgba(0, 210, 210, 0); }
}
.afo-h1 {
  font-size: 30px;
  font-weight: 600;
  margin: 0 0 10px;
  letter-spacing: -0.025em;
  line-height: 1.15;
}
.afo-h1-accent {
  background: linear-gradient(135deg, var(--nc-primary, #00d2d2) 0%, rgba(0, 210, 210, 0.6) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  font-style: italic;
  font-weight: 500;
}
.afo-lead { opacity: 0.78; max-width: 700px; margin: 0 auto; line-height: 1.6; font-size: 13px; }
.afo-lead strong { font-weight: 600; color: rgba(255,255,255,0.92); }

/* ──────────────────────────────────────────────────────────────
 * Tab nav
 * ────────────────────────────────────────────────────────────── */
.afo-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10));
  border-radius: 12px;
  margin-bottom: 18px;
  overflow-x: auto;
}
.afo-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  background: transparent;
  border: none;
  color: inherit;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  cursor: pointer;
  transition: all 150ms ease;
  white-space: nowrap;
  position: relative;
  opacity: 0.65;
}
.afo-tab:hover { opacity: 1; background: rgba(255,255,255,0.03); }
.afo-tab-active {
  opacity: 1;
  background: rgba(0, 210, 210, 0.08);
  color: var(--nc-primary, #00d2d2);
  box-shadow: inset 0 -2px 0 var(--nc-primary, #00d2d2);
}
.afo-tab-icon { font-size: 16px; }
.afo-tab-badge {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  padding: 1px 7px;
  background: rgba(255,255,255,0.06);
  border-radius: 99px;
  color: inherit;
  opacity: 0.85;
}
.afo-tab-active .afo-tab-badge { background: rgba(0, 210, 210, 0.18); }
.afo-tablist { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; }
.afo-tab-spacer { flex: 1; }
.afo-icon-btn {
  width: 36px; height: 36px;
  background: transparent; border: 1px solid transparent;
  border-radius: 8px; cursor: pointer; color: inherit;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
}
.afo-icon-btn:hover { border-color: var(--nc-primary, #00d2d2); }
.afo-icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.afo-spin { animation: afo-spin 1s linear infinite; }
@keyframes afo-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.afo-tab-panel {
  animation: afo-fadein 200ms ease;
}
@keyframes afo-fadein { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

/* ──────────────────────────────────────────────────────────────
 * Cards (shared)
 * ────────────────────────────────────────────────────────────── */
.afo-card {
  background: var(--nc-surface, rgba(0, 0, 0, 0.45));
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  border-radius: 12px;
  padding: 22px 24px;
  margin-bottom: 18px;
}
.afo-card-table { padding: 22px 0 16px; }
.afo-card-table > * { padding-left: 24px; padding-right: 24px; }
.afo-card-table .afo-table { padding: 0; }
.afo-card-head {
  display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
  margin-bottom: 16px; flex-wrap: wrap;
}
.afo-card-head h2 { margin: 0; font-size: 17px; font-weight: 600; }
.afo-meta { font-size: 12px; opacity: 0.6; }

.afo-loading, .afo-error, .afo-empty { text-align: center; padding: 40px; opacity: 0.65; }
.afo-empty-inline {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 28px 16px; opacity: 0.55; font-size: 13px;
}
.afo-empty-icon { font-size: 32px; opacity: 0.50; color: var(--nc-primary, #00d2d2); }
.afo-error { color: rgb(239, 68, 68); }

.afo-table-clickable tbody tr { cursor: pointer; }
.afo-table-clickable tbody tr:hover { background: rgba(0, 210, 210, 0.04); }

.afo-warn { color: rgb(245, 158, 11); font-size: 13px; margin: 0 0 12px; }
.afo-warn-strong { color: rgb(239, 68, 68); }

.afo-mono { font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.afo-truncate { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ──────────────────────────────────────────────────────────────
 * Overview KPI grid
 * ────────────────────────────────────────────────────────────── */
.afo-window-row { display: flex; align-items: center; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
.afo-window-label { font-size: 11px; letter-spacing: 0.10em; text-transform: uppercase; opacity: 0.55; margin-right: 6px; }
.afo-window-btn {
  padding: 5px 11px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  color: inherit;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  cursor: pointer;
  transition: all 150ms ease;
}
.afo-window-btn:hover { border-color: var(--nc-primary, #00d2d2); }
.afo-window-btn-active {
  background: rgba(0, 210, 210, 0.12);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
.afo-window-meta { font-size: 11px; opacity: 0.45; margin-left: 8px; }

.afo-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}
.afo-kpi {
  background: var(--nc-surface, rgba(0, 0, 0, 0.40));
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10));
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  position: relative;
  transition: transform 200ms cubic-bezier(.2,.7,.2,1), border-color 200ms ease, box-shadow 200ms ease;
  overflow: hidden;
}
.afo-kpi::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(180px 80px at 100% 0%, rgba(0, 210, 210, 0.10), transparent 70%);
  opacity: 0;
  transition: opacity 250ms ease;
  pointer-events: none;
}
.afo-kpi:hover {
  transform: translateY(-1px);
  border-color: rgba(0, 210, 210, 0.28);
  box-shadow: 0 8px 24px -12px rgba(0, 210, 210, 0.30);
}
.afo-kpi:hover::before { opacity: 1; }
.afo-kpi-emphasis {
  border-color: rgba(0, 210, 210, 0.30);
  background: linear-gradient(135deg, rgba(0, 210, 210, 0.06) 0%, rgba(0, 0, 0, 0.40) 100%);
}
.afo-kpi-label {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  opacity: 0.55;
}
.afo-kpi-value {
  font-size: 22px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.afo-kpi-emphasis .afo-kpi-value { color: var(--nc-primary, #00d2d2); }
.afo-kpi-meta { font-size: 11px; opacity: 0.5; }
.afo-kpi-pending { color: rgb(245, 158, 11); }
.afo-kpi-warn { color: rgb(239, 68, 68); }
.afo-kpi-sep { opacity: 0.35; margin: 0 4px; font-weight: 400; }

/* ──────────────────────────────────────────────────────────────
 * Sparkline
 * ────────────────────────────────────────────────────────────── */
.afo-spark-empty {
  text-align: center;
  padding: 30px 20px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.afo-spark-empty-icon {
  font-size: 44px;
  opacity: 0.30;
  color: var(--nc-primary, #00d2d2);
  margin-bottom: 4px;
}
.afo-spark-empty p { margin: 0; font-size: 14px; opacity: 0.75; }
.afo-spark-empty-sub { font-size: 12px !important; opacity: 0.5 !important; }

.afo-spark-single {
  padding: 6px 0 0;
}
.afo-spark-single-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  letter-spacing: 0.04em;
  opacity: 0.55;
  margin-bottom: 14px;
}
.afo-spark-single-pulse {
  font-size: 14px;
  color: var(--nc-primary, #00d2d2);
  animation: afo-pulse-text 1.8s ease-in-out infinite;
}
@keyframes afo-pulse-text { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.afo-spark-single-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(0, 210, 210, 0.12);
  border-radius: 10px;
  padding: 18px 22px;
}
.afo-spark-single-col { display: flex; flex-direction: column; gap: 4px; }
.afo-spark-single-label {
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
}
.afo-spark-single-val {
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.afo-spark-single-emph { color: var(--nc-primary, #00d2d2); font-size: 18px; }

.afo-spark-wrap { padding: 6px 0 4px; }
.afo-spark-svg {
  width: 100%;
  height: 120px;
  display: block;
}
.afo-spark-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  opacity: 0.55;
  margin-top: 6px;
  padding: 0 6px;
}
.afo-spark-peak { color: var(--nc-primary, #00d2d2); opacity: 0.85; }

/* ──────────────────────────────────────────────────────────────
 * Tables (shared)
 * ────────────────────────────────────────────────────────────── */
.afo-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.afo-table th, .afo-table td {
  text-align: left; padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,0.05);
}
.afo-table th { font-size: 10px; letter-spacing: 0.10em; text-transform: uppercase; opacity: 0.55; font-weight: 500; }
.afo-table tbody tr:hover { background: rgba(255,255,255,0.02); }
.afo-table-recent td { padding: 7px 10px; font-size: 12.5px; }

.afo-bonus { color: rgb(16, 185, 129); font-weight: 600; }
.afo-bar-bg { width: 100%; height: 4px; background: rgba(255,255,255,0.05); border-radius: 99px; overflow: hidden; }
.afo-bar-fg { height: 100%; background: linear-gradient(90deg, var(--nc-primary, #00d2d2) 0%, rgba(0, 210, 210, 0.5) 100%); transition: width 300ms ease; }

/* ──────────────────────────────────────────────────────────────
 * Pills (status)
 * ────────────────────────────────────────────────────────────── */
.afo-pill {
  font-size: 10px; letter-spacing: 0.05em; padding: 2px 8px;
  border-radius: 99px; text-transform: uppercase;
  background: rgba(255,255,255,0.06);
  display: inline-block;
}
.afo-pill-version { background: rgba(0, 210, 210, 0.15); color: var(--nc-primary, #00d2d2); }
.afo-pill-active { background: rgba(16, 185, 129, 0.15); color: rgb(16, 185, 129); }
.afo-pill-archived { background: rgba(255,255,255,0.04); opacity: 0.7; }

.afo-pill-status-pending { background: rgba(245, 158, 11, 0.15); color: rgb(245, 158, 11); }
.afo-pill-status-completed { background: rgba(16, 185, 129, 0.15); color: rgb(16, 185, 129); }
.afo-pill-status-failed { background: rgba(239, 68, 68, 0.15); color: rgb(239, 68, 68); }
.afo-pill-status-refunded { background: rgba(168, 85, 247, 0.15); color: rgb(168, 85, 247); }

.afo-pill-anon { background: rgba(56, 189, 248, 0.15); color: rgb(56, 189, 248); }
.afo-pill-loggedin { background: rgba(255,255,255,0.06); opacity: 0.75; }

/* ──────────────────────────────────────────────────────────────
 * Pricing tab — active grid + edit panel
 * ────────────────────────────────────────────────────────────── */
.afo-active-grid { display: grid; grid-template-columns: 200px 1fr; gap: 18px; align-items: start; }
.afo-active-meta div { padding: 8px 0; border-bottom: 1px dashed rgba(255,255,255,0.06); display: flex; justify-content: space-between; font-size: 13px; }
.afo-active-meta span { opacity: 0.6; }
.afo-note { font-size: 12px; opacity: 0.7; margin: 14px 0 0; padding-top: 10px; border-top: 1px dashed rgba(255,255,255,0.06); }

.afo-edit-grid {
  display: grid;
  grid-template-columns: 200px 1fr 1fr;
  gap: 12px;
  margin-bottom: 18px;
}
.afo-edit-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; opacity: 0.7; }

.afo-tier-edit { margin-bottom: 16px; }
.afo-tier-head, .afo-tier-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1.4fr 0.8fr 32px;
  gap: 8px; align-items: center;
}
.afo-tier-head {
  font-size: 10px; letter-spacing: 0.10em; text-transform: uppercase;
  opacity: 0.55; padding: 0 2px 6px;
}
.afo-tier-row { padding: 4px 0; }
.afo-add-tier { margin-top: 8px; font-size: 12px; }

.afo-note-input { display: block; margin-bottom: 14px; }
.afo-note-input span { display: block; font-size: 11px; opacity: 0.7; margin-bottom: 4px; }

.afo-off {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 1200px;
  margin: 0 auto 18px;
  padding: 10px 14px;
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.45;
}
.afo-off-icon { flex: 0 0 auto; width: 18px; height: 18px; color: rgb(245, 158, 11); margin-top: 1px; }

.afo-errors {
  background: rgba(239, 68, 68, 0.07);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
  font-size: 12px;
}
.afo-errors-head { font-weight: 600; margin-bottom: 4px; color: rgb(239, 68, 68); }
.afo-errors ul { margin: 0; padding-left: 18px; }

.afo-edit-actions { display: flex; gap: 8px; justify-content: flex-end; }

.afo-row-active { background: rgba(0, 210, 210, 0.04); }
.afo-note-cell { max-width: 360px; }

.afo-sim-inputs { display: grid; grid-template-columns: 1fr 1fr 1.5fr; gap: 12px; margin-bottom: 14px; }
.afo-sim-inputs label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; opacity: 0.7; }
.afo-sim-scenario { display: grid; grid-template-columns: 280px 1fr; gap: 12px; margin-bottom: 14px; }
.afo-sim-scenario label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; opacity: 0.7; }
.afo-sim-purchases textarea { min-height: 88px; font-family: ui-monospace, monospace; }

.afo-sim-results { margin-top: 18px; padding-top: 18px; border-top: 1px dashed rgba(255,255,255,0.08); }
.afo-sim-summary-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 18px;
}
.afo-sim-summary-grid div {
  background: rgba(0, 0, 0, 0.30); border-radius: 6px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px; font-size: 12px;
}
.afo-sim-summary-grid span { opacity: 0.6; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
.afo-sim-summary-grid strong { font-size: 15px; font-variant-numeric: tabular-nums; }
.afo-sim-results h3 { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.7; margin: 14px 0 6px; }

.afo-warnings { margin-top: 14px; font-size: 12px; opacity: 0.85; }
.afo-warnings summary { cursor: pointer; padding: 6px 0; }
.afo-warnings ul { margin: 4px 0 0; padding-left: 18px; max-height: 200px; overflow-y: auto; }

/* ──────────────────────────────────────────────────────────────
 * Buttons
 * ────────────────────────────────────────────────────────────── */
.afo-btn {
  padding: 8px 14px;
  background: transparent;
  border: 1px solid var(--nc-border, rgba(255,255,255,0.10));
  border-radius: 6px;
  color: inherit;
  font-size: 12px;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all 150ms ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.afo-btn:hover:not(:disabled) { border-color: var(--nc-primary, #00d2d2); }
.afo-btn-primary { background: var(--nc-primary, #00d2d2); color: #000; border-color: var(--nc-primary, #00d2d2); font-weight: 600; }
.afo-btn-primary:hover:not(:disabled) { filter: brightness(1.1); }
.afo-btn-ghost { font-size: 11px; opacity: 0.8; }
.afo-btn-icon { width: 32px; padding: 0; font-size: 16px; line-height: 30px; text-align: center; }
.afo-btn-danger {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.4);
  color: rgb(239, 68, 68);
}
.afo-btn-danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.2); border-color: rgb(239, 68, 68); }
.afo-btn:disabled { opacity: 0.35; cursor: not-allowed; }

/* ──────────────────────────────────────────────────────────────
 * Explorer — filters + table + drill-down
 * ────────────────────────────────────────────────────────────── */
.afo-filter-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.afo-filter-label { font-size: 11px; letter-spacing: 0.10em; text-transform: uppercase; opacity: 0.55; margin-right: 8px; }
.afo-filter-pill {
  padding: 5px 11px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 99px;
  color: inherit;
  font-size: 11px;
  letter-spacing: 0.04em;
  cursor: pointer;
  text-transform: uppercase;
  transition: all 150ms ease;
}
.afo-filter-pill:hover { border-color: var(--nc-primary, #00d2d2); }
.afo-filter-pill-active {
  background: rgba(0, 210, 210, 0.12);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
/* Status-tinted active pills */
.afo-filter-pill-pending.afo-filter-pill-active { background: rgba(245, 158, 11, 0.18); border-color: rgb(245, 158, 11); color: rgb(245, 158, 11); }
.afo-filter-pill-completed.afo-filter-pill-active { background: rgba(16, 185, 129, 0.18); border-color: rgb(16, 185, 129); color: rgb(16, 185, 129); }
.afo-filter-pill-failed.afo-filter-pill-active { background: rgba(239, 68, 68, 0.18); border-color: rgb(239, 68, 68); color: rgb(239, 68, 68); }
.afo-filter-pill-refunded.afo-filter-pill-active { background: rgba(168, 85, 247, 0.18); border-color: rgb(168, 85, 247); color: rgb(168, 85, 247); }

.afo-filter-search { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.afo-filter-search .nc-input { flex: 1; min-width: 180px; }

.afo-table-explorer th:first-child, .afo-table-explorer td:first-child { width: 28px; padding-left: 18px; }
.afo-explorer-row { cursor: pointer; transition: background 150ms ease; }
.afo-explorer-row:hover { background: rgba(0, 210, 210, 0.03); }
.afo-explorer-row-open {
  background: rgba(0, 210, 210, 0.06);
}
.afo-expand-cell { color: var(--nc-primary, #00d2d2); }

.afo-detail-row td { background: rgba(0, 0, 0, 0.20); padding: 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.afo-detail { padding: 18px 24px 22px; }

.afo-detail-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
.afo-action-result {
  font-size: 12px; padding: 6px 12px; border-radius: 6px; max-width: 600px;
}
.afo-action-ok { background: rgba(16, 185, 129, 0.10); color: rgb(16, 185, 129); border: 1px solid rgba(16, 185, 129, 0.25); }
.afo-action-err { background: rgba(239, 68, 68, 0.10); color: rgb(239, 68, 68); border: 1px solid rgba(239, 68, 68, 0.25); }

.afo-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.afo-detail-card {
  background: var(--nc-surface, rgba(0, 0, 0, 0.30));
  border: 1px solid var(--nc-border, rgba(255,255,255,0.06));
  border-radius: 8px;
  padding: 14px 16px;
}
.afo-detail-card h4 {
  font-size: 11px; letter-spacing: 0.10em; text-transform: uppercase;
  opacity: 0.65; margin: 0 0 10px;
  display: flex; align-items: center; gap: 6px;
}
.afo-dl { margin: 0; display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; font-size: 12px; }
.afo-dl dt { opacity: 0.55; }
.afo-dl dd { margin: 0; word-break: break-word; }
.afo-failure-text { color: rgb(239, 68, 68); font-size: 11px; }

.afo-pager { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; padding: 0 18px; }

/* ──────────────────────────────────────────────────────────────
 * Modals
 * ────────────────────────────────────────────────────────────── */
.afo-modal-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.7);
  display: flex; align-items: center; justify-content: center;
  z-index: 10100;
}
.afo-modal {
  background: var(--nc-surface, rgba(20, 20, 20, 0.96));
  border: 1px solid rgba(0, 210, 210, 0.40);
  border-radius: 10px; padding: 24px; max-width: 480px; width: 90%;
}
.afo-modal-danger { border-color: rgba(239, 68, 68, 0.40); }
.afo-modal h3 { margin: 0 0 8px; font-size: 17px; }
.afo-modal-summary { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 14px 0; }
.afo-modal-summary div { background: rgba(0,0,0,0.30); padding: 8px; border-radius: 6px; font-size: 12px; display: flex; flex-direction: column; gap: 2px; }
.afo-modal-summary span { opacity: 0.6; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
.afo-confirm-prompt { font-size: 13px; }
.afo-confirm-prompt code { background: rgba(0,0,0,0.35); padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, monospace; }
.afo-modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }

/* ──────────────────────────────────────────────────────────────
 * Mobile
 * ────────────────────────────────────────────────────────────── */
@media (max-width: 1023.98px) {
  .afo-active-grid { grid-template-columns: 1fr; }
  .afo-edit-grid { grid-template-columns: 1fr 1fr; }
  .afo-sim-inputs { grid-template-columns: 1fr 1fr; }
  .afo-sim-scenario { grid-template-columns: 1fr; }
  .afo-sim-summary-grid { grid-template-columns: 1fr 1fr; }
  .afo-modal-summary { grid-template-columns: 1fr; }
}
@media (max-width: 767.98px) {
  .afo-edit-grid { grid-template-columns: 1fr; }
  .afo-sim-inputs { grid-template-columns: 1fr; }
  .afo-sim-summary-grid { grid-template-columns: 1fr; }
  .afo-tier-head, .afo-tier-row { grid-template-columns: repeat(2, 1fr) 28px; row-gap: 4px; }
  .afo-card { padding: 16px; }
  .afo-card-table > * { padding-left: 16px; padding-right: 16px; }
  .afo-headline { font-size: 24px; }
  .afo-table-explorer th:nth-child(8), .afo-table-explorer td:nth-child(8),
  .afo-table-explorer th:nth-child(7), .afo-table-explorer td:nth-child(7) { display: none; }
}

/* ── Flare Ops tab (Phase O, 2026-05-09) ─────────────────────── */

.afo-flare-grant {
  border-color: rgba(245, 158, 11, 0.30);
  background:
    linear-gradient(180deg,
      rgba(245, 158, 11, 0.04) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.40)) 60%);
}
.afo-flare-grant .afo-card-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.afo-flare-tier-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 0 24px 16px;
}
.afo-flare-tier-chip {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  cursor: pointer;
  transition: all 200ms ease;
  min-width: 110px;
}
.afo-flare-tier-chip:hover {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.40);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
}
.afo-flare-tier-chip-active {
  border-color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12);
  box-shadow: 0 0 0 1px var(--nc-primary, #00d2d2),
              0 8px 20px -10px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.45);
}
.afo-flare-rank {
  font-family: ui-monospace, monospace;
  font-size: 9.5px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
}

.afo-flare-grant-grid {
  padding: 0 24px 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.afo-form-full { grid-column: 1 / -1; }
.afo-form-group { display: flex; flex-direction: column; gap: 4px; }
.afo-label {
  font-size: 11px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.65;
}
.afo-label-sub {
  margin-left: 6px;
  text-transform: none;
  letter-spacing: normal;
  opacity: 0.50;
  font-family: ui-monospace, monospace;
}
.afo-toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.20);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  cursor: pointer;
}
.afo-toggle-row input { cursor: pointer; }

.afo-color-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.afo-color-input { flex: 1; min-width: 100px; max-width: 200px; }
.afo-color-picker {
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}

.afo-flare-actions {
  padding: 0 24px 18px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.afo-btn-sm { padding: 5px 10px; font-size: 11px; }

.afo-counter {
  margin-left: 8px;
  padding: 2px 8px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--nc-primary, #00d2d2);
}

.afo-table-flares {
  width: 100%;
}
.afo-table-flares th, .afo-table-flares td {
  padding: 10px 14px;
  text-align: left;
  vertical-align: middle;
  font-size: 12.5px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.afo-table-flares th {
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
  font-weight: 500;
}
.afo-th-actions, .afo-td-actions { text-align: right; white-space: nowrap; }
.afo-td-actions .afo-btn { margin-left: 4px; }
.afo-tagline-cell p { margin: 0 0 3px; line-height: 1.4; opacity: 0.85; }
.afo-cause-pill {
  display: inline-block;
  margin-top: 2px;
  padding: 1px 8px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--nc-primary, #00d2d2);
}
.afo-btn-danger {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.40);
  color: rgb(252, 165, 165);
}
.afo-btn-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.22);
  border-color: rgb(239, 68, 68);
}
.afo-confirm-prompt code {
  background: rgba(239, 68, 68, 0.15);
  color: rgb(252, 165, 165);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, monospace;
}

.afo-error {
  margin: 8px 24px 12px;
  font-size: 12px;
  color: rgb(239, 68, 68);
}
.afo-success {
  margin: 8px 24px 12px;
  font-size: 13px;
  color: rgb(16, 185, 129);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.afo-spin { animation: afo-spin 1s linear infinite; }
@keyframes afo-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .afo-flare-grant-grid { grid-template-columns: 1fr; padding: 0 16px 14px; }
  .afo-flare-tier-row { padding: 0 16px 16px; }
  .afo-flare-tier-chip { min-width: 90px; }
}
</style>
