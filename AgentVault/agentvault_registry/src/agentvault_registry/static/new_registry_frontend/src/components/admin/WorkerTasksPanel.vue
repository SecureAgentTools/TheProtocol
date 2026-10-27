<template>
  <!-- Build #4 (2026-05-07): Background Workers Status panel.
       Mounted inside AdminReactors.vue as the 2nd tab.
       Strategy doc §4 Build #4. Backend: GET /admin/workers/status. -->
  <div class="wt-panel">

    <!-- Loading -->
    <div v-if="loading && !data" class="wt-center">
      <div class="wt-spinner"></div>
      <p class="wt-loading-text">Querying background workers…</p>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="wt-center">
      <p class="wt-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
      <button class="wt-btn wt-btn--ghost" @click="fetchStatus">Retry</button>
    </div>

    <!-- Dashboard -->
    <div v-else-if="data" class="wt-section">
      <!-- Stats -->
      <div class="wt-stats-row">
        <div class="wt-stat wt-stat--cyan">
          <span class="wt-stat-label">Worker Tasks</span>
          <span class="wt-stat-value">{{ data.summary.total }}</span>
        </div>
        <div class="wt-stat wt-stat--ok">
          <span class="wt-stat-label">With Leader</span>
          <span class="wt-stat-value">{{ data.summary.with_leader }}</span>
          <span class="wt-stat-sub">running cluster-wide</span>
        </div>
        <div class="wt-stat" :class="data.summary.no_leader > 0 ? 'wt-stat--warn' : 'wt-stat--muted'">
          <span class="wt-stat-label">No Leader</span>
          <span class="wt-stat-value">{{ data.summary.no_leader }}</span>
          <span v-if="data.summary.no_leader > 0" class="wt-stat-sub">paused or disabled</span>
        </div>
        <div class="wt-stat wt-stat--cyan">
          <span class="wt-stat-label">Categories</span>
          <span class="wt-stat-value">{{ uniqueCategories.length }}</span>
        </div>
      </div>

      <!-- Toolbar -->
      <div class="wt-toolbar">
        <div class="wt-toolbar-left">
          <span class="wt-toolbar-label">FILTER</span>
          <button
            v-for="c in CATEGORIES"
            :key="c.id || 'all'"
            class="wt-chip"
            :class="{ 'wt-chip--active': activeCategory === c.id }"
            @click="activeCategory = c.id"
          >
            {{ c.label }}
          </button>
          <button
            class="wt-chip"
            :class="{ 'wt-chip--active': showOnlyNoLeader }"
            @click="showOnlyNoLeader = !showOnlyNoLeader"
            title="Show only tasks with no active leader"
          ><Icon name="mdi:alert" /> No Leader</button>
        </div>
        <div class="wt-toolbar-right">
          <span class="wt-mono-label">{{ t('common.lastRefresh') }}</span>
          <span class="wt-mono-val">{{ lastRefreshAt || '—' }}</span>
          <span class="wt-mono-label" style="margin-left:0.6rem">Auto:</span>
          <button class="wt-btn wt-btn--ghost" @click="toggleAutoRefresh">
            <span class="wt-live-dot" :class="{ 'wt-live-dot--on': autoRefresh }"></span>
            {{ autoRefresh ? 'Paused-aware' : 'Off' }}
          </button>
          <button class="wt-btn wt-btn--primary" @click="fetchStatus">↻ Refresh</button>
        </div>
      </div>

      <!-- Reading-the-data note (matches reactor tab) -->
      <div class="wt-note wt-note--info">
        <span class="wt-note-icon">ⓘ</span>
        <div class="wt-note-body">
          <strong class="wt-note-title">Reading the data</strong>
          <span class="wt-note-text">
            <strong>Workers</strong> are singleton background tasks (one per cluster) that run on a leader-elected uvicorn worker. Each row shows the
            current Redis lease state: <code>has_leader=true</code> means a worker is actively running the task; <code>lease_ttl_seconds</code>
            counts down to next renewal (LOCK_TTL=30s, renew=15s; lease shrinks until renewed). If a task shows <code>no_leader</code>, it's
            either disabled by env var or temporarily paused. Reactor framework leases are surfaced separately on the <code>Reactors</code> tab.
          </span>
        </div>
      </div>

      <!-- §pass27 Phase 1 (2026-05-17) — canary_judge card.
           Registry-side worker (registry-a only). Surfaces 24h pass-rate,
           failures, and in-flight counts. Click Details to open the modal. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Canary Judgment
          <span class="wt-cts-section-sub">registry-a · 5s cycle · canary_test_results-backed</span>
        </h3>
        <div
          v-if="judgeDegraded"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>Pass rate degraded.</strong>
            {{ judgeStatus?.summary.pass_rate_24h }}% over 24h
            (below 95% threshold; baseline ≈ 97%) —
            <em>{{ judgeStatus?.summary.failures_24h }} failure(s) of {{ judgeStatus?.summary.cycles_24h }} total</em>.
            Open Inspect → Outcome Breakdown for path-level damage.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openJudgeModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="judgeCardClass"
          @click="openJudgeModal"
          @keydown.enter="openJudgeModal"
          @keydown.space.prevent="openJudgeModal"
          role="button"
          tabindex="0"
          aria-label="Open canary judge details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="judgeDotClass"></span>
            <span class="wt-card-name">canary_judge</span>
            <span class="wt-pill" :class="judgePillClass">{{ judgePillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--cyan">monitoring</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openJudgeModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Leader-elected outcome judge. Sweeps in-flight canary state every 5s,
            rules pass/fail vs SLO + grace, and persists totals to
            <code>canary_test_results</code>. Drives the live canary pass-rate
            dashboard.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Pass rate 24h</span>
              <span class="wt-card-val" :class="(judgeStatus?.summary.pass_rate_24h ?? 100) < 97 ? 'wt-text-warn' : 'wt-text-ok'">
                {{ judgeStatus?.summary.pass_rate_24h !== null && judgeStatus?.summary.pass_rate_24h !== undefined ? judgeStatus.summary.pass_rate_24h + '%' : '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ judgeStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Failures 24h</span>
              <span
                class="wt-card-val"
                :class="(judgeStatus?.summary.failures_24h ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ judgeStatus?.summary.failures_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">In flight</span>
              <span
                class="wt-card-val"
                :class="(judgeStatus?.summary.in_flight_count ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ judgeStatus?.summary.in_flight_count ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Active paths</span>
              <span class="wt-card-val">{{ judgeStatus?.summary.active_paths ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass27 Phase 2 (2026-05-17) — canary_rebalancer card.
           Registry-side worker (registry-a only). Surfaces under-floor agents
           + recent funding activity. Click Details to open the modal. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Canary Rebalancing
          <span class="wt-cts-section-sub">registry-a · 300s cycle · floor-triggered refunds</span>
        </h3>
        <div
          v-if="rebalancerNeedsAttention"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>Canary agent(s) below floor.</strong>
            {{ rebalancerStatus?.summary.agents_under_floor }} of
            {{ rebalancerStatus?.summary.agents_active }} canary agents
            under {{ formatAvt(rebalancerStatus?.config.floor_avt) }} {{ localCurrency }} —
            rebalancer will refund on next eligible cycle.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openRebalancerModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="rebalancerCardClass"
          @click="openRebalancerModal"
          @keydown.enter="openRebalancerModal"
          @keydown.space.prevent="openRebalancerModal"
          role="button"
          tabindex="0"
          aria-label="Open canary rebalancer details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="rebalancerDotClass"></span>
            <span class="wt-card-name">canary_rebalancer</span>
            <span class="wt-pill" :class="rebalancerPillClass">{{ rebalancerPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--green">payments</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openRebalancerModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Auto-rebalancer for canary sender agents. Refunds any agent whose
            home-TEG balance falls below the FLOOR; 1h per-agent cooldown
            prevents runaway funding. Closes the manual-rebalance class
            permanently.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Funded 24h</span>
              <span class="wt-card-val">{{ rebalancerStatus?.summary.funded_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Disbursed 24h</span>
              <span class="wt-card-val">{{ rebalancerStatus ? (formatAvt(rebalancerStatus.summary.avt_disbursed_24h) + ' ' + localCurrency).trim() : '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Under floor</span>
              <span
                class="wt-card-val"
                :class="(rebalancerStatus?.summary.agents_under_floor ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ rebalancerStatus?.summary.agents_under_floor ?? '—' }} / {{ rebalancerStatus?.summary.agents_active ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Errors 24h</span>
              <span
                class="wt-card-val"
                :class="(rebalancerStatus?.summary.errors_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ rebalancerStatus?.summary.errors_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass29 Phase 7 (2026-05-17) — agent_health_checker card.
           Probes agent /health URLs every 5min. Surfaces probe history +
           state-transition matrix + currently-down agents. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Agent Health Probes
          <span class="wt-cts-section-sub">registry-a + frame-b · 5min cycle · /health probe + flap detection</span>
        </h3>
        <div
          v-if="agentHealthHasUnreachable"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>{{ agentHealthStatus?.summary.agents_unreachable }} agent(s) unreachable.</strong>
            Probe could not connect — agents are either down or behind a
            firewall. Click <em>Inspect</em> for the list + last-active times.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openAgentHealthModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="agentHealthCardClass"
          @click="openAgentHealthModal"
          @keydown.enter="openAgentHealthModal"
          @keydown.space.prevent="openAgentHealthModal"
          role="button"
          tabindex="0"
          aria-label="Open agent health checker details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="agentHealthDotClass"></span>
            <span class="wt-card-name">agent_health_checker</span>
            <span class="wt-pill" :class="agentHealthPillClass">{{ agentHealthPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--amber">monitoring</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openAgentHealthModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Periodic <code>/health</code> probe across all active agents.
            Fires <code>agent.health_changed</code> webhook on state
            transitions. Modal surfaces probe history + flap matrix +
            currently-down list — distinct from AdminAgents which shows
            <em>current</em> health, not <em>cycle</em> history.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Healthy</span>
              <span class="wt-card-val wt-text-ok">{{ agentHealthStatus?.db_summary?.healthy ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Unhealthy</span>
              <span class="wt-card-val" :class="(agentHealthStatus?.db_summary?.unhealthy ?? 0) > 0 ? 'wt-text-warn' : ''">
                {{ agentHealthStatus?.db_summary?.unhealthy ?? '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Unreachable</span>
              <span class="wt-card-val" :class="(agentHealthStatus?.db_summary?.unreachable ?? 0) > 0 ? 'wt-text-error' : ''">
                {{ agentHealthStatus?.db_summary?.unreachable ?? '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">State changes 24h</span>
              <span class="wt-card-val">{{ agentHealthStatus?.summary.state_changes_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ agentHealthStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass29 Phase 6 (2026-05-17) — federation_sync card.
           Periodic peer card sync. Surfaces per-peer freshness + cycle
           health. Banner fires only on stale ACTIVE peers (actionable). -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Federation Sync
          <span class="wt-cts-section-sub">registry-a + frame-b · 5min cycle · per-peer freshness + license-gated skip</span>
        </h3>
        <div
          v-if="fedHasStalePeers"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>{{ fedStatus?.summary.stale_active_peers }} ACTIVE peer(s) stale.</strong>
            Federation sync has not refreshed agent cards from these peers within
            the expected window — click <em>Inspect</em> to see which peers and
            their last-sync timestamps.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openFedSyncModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="fedCardClass"
          @click="openFedSyncModal"
          @keydown.enter="openFedSyncModal"
          @keydown.space.prevent="openFedSyncModal"
          role="button"
          tabindex="0"
          aria-label="Open federation sync details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="fedDotClass"></span>
            <span class="wt-card-name">federation_sync</span>
            <span class="wt-pill" :class="fedPillClass">{{ fedPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--indigo">federation</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openFedSyncModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Periodic agent-card pull from federation peers (with license-gate
            check + Bayesian trust decay). Backup path; reactors handle the
            hot push. Modal surfaces per-peer freshness + 24h sync attempts.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Active peers</span>
              <span class="wt-card-val">{{ fedStatus?.summary.active_peers ?? '—' }} / {{ fedStatus?.summary.total_peers ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Stale ACTIVE</span>
              <span class="wt-card-val" :class="(fedStatus?.summary.stale_active_peers ?? 0) > 0 ? 'wt-text-warn' : 'wt-text-ok'">
                {{ fedStatus?.summary.stale_active_peers ?? '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ fedStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Errors 24h</span>
              <span
                class="wt-card-val"
                :class="(fedStatus?.summary.errors_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ fedStatus?.summary.errors_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass28 Phase 5 (2026-05-17) — collusion_worker card.
           24h-cadence enforcement worker. Surfaces ring detections + decay
           pass status. Modal polls at 60s instead of 5s. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Collusion Detection
          <span class="wt-cts-section-sub">registry-a + frame-b · daily cycle · Bayesian decay + SCC ring detection</span>
        </h3>
        <div
          v-if="collusionHasRings"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>New collusion rings detected.</strong>
            {{ collusionStatus?.summary.rings_24h }} ring(s) flagged in last 24h
            (lifetime {{ collusionStatus?.summary.lifetime_rings }}) —
            click <em>Inspect</em> to review members + severity.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openCollusionModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="collusionCardClass"
          @click="openCollusionModal"
          @keydown.enter="openCollusionModal"
          @keydown.space.prevent="openCollusionModal"
          role="button"
          tabindex="0"
          aria-label="Open collusion worker details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="collusionDotClass"></span>
            <span class="wt-card-name">collusion_worker</span>
            <span class="wt-pill" :class="collusionPillClass">{{ collusionPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--green">reputation</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openCollusionModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Daily Bayesian trust-decay + SCC collusion ring detector. Flags
            agent groups that route discounts among themselves to fake
            reputation. Persists findings as <code>CollusionRingDetected</code>
            rows in <code>auditor_flag_logs</code>.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Rings 24h</span>
              <span class="wt-card-val" :class="(collusionStatus?.summary.rings_24h ?? 0) > 0 ? 'wt-text-warn' : 'wt-text-ok'">
                {{ collusionStatus?.summary.rings_24h ?? '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Lifetime rings</span>
              <span class="wt-card-val">{{ collusionStatus?.summary.lifetime_rings ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ collusionStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Errors 24h</span>
              <span
                class="wt-card-val"
                :class="(collusionStatus?.summary.errors_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ collusionStatus?.summary.errors_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass28 Phase 4 (2026-05-17) — supply_auditor card.
           Runs on EVERY registry (60s cycle). Surfaces the supply invariant —
           the single most operator-critical observability on the registry side. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Supply Invariant
          <span class="wt-cts-section-sub">registry-a + frame-b · 60s cycle · zero-tolerance |Δ|</span>
        </h3>
        <div
          v-if="supplyHasBreach"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>SUPPLY INVARIANT BREACH.</strong>
            {{ supplyStatus?.summary.breaches_24h }} breach event(s) in last 24h.
            Live |Δ| = {{ supplyStatus?.summary.live_delta ?? '?' }} {{ localCurrency }} —
            <em>investigate immediately</em>.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openSupplyModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="supplyCardClass"
          @click="openSupplyModal"
          @keydown.enter="openSupplyModal"
          @keydown.space.prevent="openSupplyModal"
          role="button"
          tabindex="0"
          aria-label="Open supply auditor details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="supplyDotClass"></span>
            <span class="wt-card-name">supply_auditor</span>
            <span class="wt-pill" :class="supplyPillClass">{{ supplyPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--green">audit</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openSupplyModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Self-consistent supply invariant auditor (f037 Option 4). Polls
            EventStore <code>/projections/supply-audit</code> every 60s on each
            registry, verifies <code>tokens_issued − tokens_destroyed + transit_net == circulating</code>,
            emits <code>SupplyInvariantBreach</code> on any |Δ|>0.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Status</span>
              <span class="wt-card-val" :class="supplyStatusValClass">{{ supplyStatus?.summary.live_status || '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">|Δ| live</span>
              <span class="wt-card-val" :class="supplyAbsDelta > 0 ? 'wt-text-warn' : 'wt-text-ok'">
                {{ formatAvt(supplyStatus?.summary.live_delta) }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ supplyStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Breaches 24h</span>
              <span
                class="wt-card-val"
                :class="(supplyStatus?.summary.breaches_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ supplyStatus?.summary.breaches_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Registries</span>
              <span class="wt-card-val">{{ supplyStatus?.summary.registries_reporting ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass27 Phase 3 (2026-05-17) — saga_timeout_checker card.
           Runs on BOTH registry-a AND frame-b-registry; status aggregates
           fleet-wide via Prom registry_id label. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Saga Timeouts
          <span class="wt-cts-section-sub">registry-a + frame-b · 60s cross-frame · 5min settlement saga</span>
        </h3>
        <div
          v-if="sagaHasErrors"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>Saga timeouts detected.</strong>
            {{ sagaStatus?.summary.errors_24h }} error(s) /
            {{ sagaStatus?.summary.pending_now }} pending now —
            click <em>Inspect</em>.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openSagaModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="sagaCardClass"
          @click="openSagaModal"
          @keydown.enter="openSagaModal"
          @keydown.space.prevent="openSagaModal"
          role="button"
          tabindex="0"
          aria-label="Open saga timeout checker details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="sagaDotClass"></span>
            <span class="wt-card-name">saga_timeout_checker</span>
            <span class="wt-pill" :class="sagaPillClass">{{ sagaPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--indigo">federation</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openSagaModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Dual-cycle timeout sweeper. Cross-frame sweep every 60s refunds
            locked async transfers past their 5min timeout; settlement saga
            check every 5min times out cross-registry disputes past the 72h
            deadline.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Registries reporting</span>
              <span class="wt-card-val">{{ sagaStatus?.per_registry.length ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cross-frame 24h</span>
              <span class="wt-card-val">{{ sagaStatus?.summary.cross_frame_refunded_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Settlement 24h</span>
              <span class="wt-card-val">{{ sagaStatus?.summary.settlements_timed_out_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Pending now</span>
              <span
                class="wt-card-val"
                :class="(sagaStatus?.summary.pending_now ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ sagaStatus?.summary.pending_now ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Errors 24h</span>
              <span
                class="wt-card-val"
                :class="(sagaStatus?.summary.errors_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ sagaStatus?.summary.errors_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass26 (2026-05-17) — Cross-TEG 2PC sweeper card.
           This is a TEG-side worker (one per TEG container, leader-elected
           per-TEG via Redis). Not surfaced in /admin/workers/status (which
           is registry-side); shown here as a synthetic card so the workers
           tab has one fleet-wide observability surface. Click Details to
           open the per-TEG breakdown modal. Generic modal architecture —
           extensible to canary_judge / canary_rebalancer / saga_timeout_checker
           when their TEG-side counterparts ship. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Cross-frame Coordination
          <span class="wt-cts-section-sub">TEG-side · leader-elected per TEG · 60s cycle</span>
        </h3>
        <div
          v-if="sweeperHasErrors"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>Sweeper errors detected.</strong>
            {{ sweeperStatus?.summary.errors_24h }} error(s) in last 24h across
            {{ sweeperErrorTegCount }} TEG(s) — click <em>Inspect</em> to review.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openSweeperModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="sweeperCardClass"
          @click="openSweeperModal"
          @keydown.enter="openSweeperModal"
          @keydown.space.prevent="openSweeperModal"
          role="button"
          tabindex="0"
          aria-label="Open cross-TEG sweeper details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="sweeperDotClass"></span>
            <span class="wt-card-name">cross_teg_sweeper</span>
            <span class="wt-pill" :class="sweeperPillClass">{{ sweeperPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--cyan">cross-frame</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openSweeperModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Durable 2PC coordination sweeper. Releases expired source-side locks
            via the existing compensation primitive; flags partial-commit cases
            for operator review. Replaces the in-memory cleanup stub.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">TEGs reporting</span>
              <span class="wt-card-val">{{ sweeperStatus?.summary.teg_count ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ sweeperStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Aborted 24h</span>
              <span
                class="wt-card-val"
                :class="(sweeperStatus?.summary.aborted_24h ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ sweeperStatus?.summary.aborted_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Pending now</span>
              <span
                class="wt-card-val"
                :class="(sweeperStatus?.summary.pending_total ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ sweeperStatus?.summary.pending_total ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Errors 24h</span>
              <span
                class="wt-card-val"
                :class="(sweeperStatus?.summary.errors_24h ?? 0) > 0 ? 'wt-text-error' : 'wt-text-ok'"
              >{{ sweeperStatus?.summary.errors_24h ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass36 Option C Phase 3 (2026-05-17) — agent_card_pullsync card.
           Each registry's worker pulls native agents' /.well-known/agent-card.json
           every 6h and reconciles drift against stored card_data. Preserves
           registry-owned federation_metadata + flare. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Agent-Card Pull-Sync
          <span class="wt-cts-section-sub">A2A v1.0 §4.1.2 · per-registry · 6h cycle</span>
        </h3>
        <div
          v-if="pullsyncStatus?.banner?.level === 'warn'"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>Pull-sync warning.</strong>
            {{ pullsyncStatus?.banner?.msg }} — click <em>Inspect</em>.
          </span>
          <button class="wt-btn wt-btn--primary" @click="openPullsyncModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="{
            'wt-card--warn': pullsyncStatus?.banner?.level === 'warn',
            'wt-card--ok': pullsyncStatus && pullsyncStatus.banner === null,
          }"
          @click="openPullsyncModal"
          @keydown.enter="openPullsyncModal"
          @keydown.space.prevent="openPullsyncModal"
          role="button"
          tabindex="0"
          aria-label="Open agent-card pull-sync details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="!pullsyncStatus ? 'wt-card-dot--muted' : pullsyncStatus.banner?.level === 'warn' ? 'wt-card-dot--warn' : 'wt-card-dot--ok'"></span>
            <span class="wt-card-name">agent_card_pullsync</span>
            <span class="wt-pill" :class="!pullsyncStatus ? 'wt-pill--muted' : pullsyncStatus.banner?.level === 'warn' ? 'wt-pill--warn' : 'wt-pill--ok'">
              {{ !pullsyncStatus ? (aggUnread.pullsync ? 'unread' : 'loading') : pullsyncStatus.banner?.level === 'warn' ? 'attention' : 'healthy' }}
            </span>
            <span class="wt-card-cat-pill wt-card-cat-pill--cyan">federation</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openPullsyncModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Per A2A v1.0 §4.1.2, each agent owns its own card at
            <code>/.well-known/agent-card.json</code>. This worker pulls native
            agents' cards on a 6h cycle and reconciles drift — agent owns
            identity/transport; registry preserves flare + federation_metadata.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Native agents</span>
              <span class="wt-card-val">{{ pullsyncStatus?.db_buckets.total_native_active ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ pullsyncStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Pulls (200) 24h</span>
              <span class="wt-card-val">{{ pullsyncStatus?.summary.pulls_200_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Drift 24h</span>
              <span
                class="wt-card-val"
                :class="(pullsyncStatus?.summary.drift_events_24h ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ pullsyncStatus?.summary.drift_events_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Never pulled</span>
              <span
                class="wt-card-val"
                :class="(pullsyncStatus?.db_buckets.never_pulled ?? 0) > 0 ? 'wt-text-warn' : ''"
              >{{ pullsyncStatus?.db_buckets.never_pulled ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- §pass30 (2026-05-17) — canary IRONHAND mTLS card.
           Pattern A: per-canary workload containers each fetching their own
           SVID via SPIRE Workload API. Exercises the full IRONHAND stack
           that real production agents use. -->
      <div class="wt-cts-section">
        <h3 class="wt-cts-section-title">
          Canary IRONHAND mTLS
          <span class="wt-cts-section-sub">per-agent SVID · workload containers · §pass30 Pattern A</span>
        </h3>
        <div
          v-if="ironhandHasFailures"
          class="wt-cts-error-banner"
          role="alert"
        >
          <span class="wt-cts-banner-glyph"><Icon name="mdi:alert" /></span>
          <span class="wt-cts-banner-text">
            <strong>{{ ironhandStatus?.summary.failures_24h }} IRONHAND failure(s) in last 24h.</strong>
            Per-agent mTLS regression on at least one canary path —
            possibly SPIRE Workload API attestation, federated bundle, or
            revocation pipeline. <em>FAIL LOUDLY by design — no bearer fallback.</em>
          </span>
          <button class="wt-btn wt-btn--primary" @click="openIronhandModal">Inspect</button>
        </div>
        <div
          class="wt-card wt-card--cts"
          :class="ironhandCardClass"
          @click="openIronhandModal"
          @keydown.enter="openIronhandModal"
          @keydown.space.prevent="openIronhandModal"
          role="button"
          tabindex="0"
          aria-label="Open canary IRONHAND mTLS details"
        >
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="ironhandDotClass"></span>
            <span class="wt-card-name">canary_ironhand</span>
            <span class="wt-pill" :class="ironhandPillClass">{{ ironhandPillLabel }}</span>
            <span class="wt-card-cat-pill wt-card-cat-pill--cyan">monitoring</span>
            <span style="flex:1"></span>
            <button class="wt-btn wt-btn--ghost wt-cts-details-btn" type="button" @click.stop="openIronhandModal">
              Details →
            </button>
          </div>
          <div class="wt-card-desc">
            Per-canary workload containers fetching their own SVID via SPIRE
            Workload API (Docker-label attestation). Fires real
            <code>/teg/transfer</code> through nginx mTLS edge with per-agent
            client cert. Distinct from the §15 registry-SVID canary — exercises
            agent-mTLS the way user-deployed agents do.
          </div>
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Pass rate 24h</span>
              <span class="wt-card-val" :class="(ironhandStatus?.summary.pass_rate_24h ?? 100) < 97 ? 'wt-text-warn' : 'wt-text-ok'">
                {{ ironhandStatus?.summary.pass_rate_24h !== null && ironhandStatus?.summary.pass_rate_24h !== undefined ? ironhandStatus.summary.pass_rate_24h + '%' : '—' }}
              </span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Active paths</span>
              <span class="wt-card-val">{{ ironhandStatus?.summary.active_paths ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Cycles 24h</span>
              <span class="wt-card-val">{{ ironhandStatus?.summary.cycles_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Failures 24h</span>
              <span
                class="wt-card-val"
                :class="(ironhandStatus?.summary.failures_24h ?? 0) > 0 ? 'wt-text-error' : ''"
              >{{ ironhandStatus?.summary.failures_24h ?? '—' }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Revoc p95</span>
              <span class="wt-card-val">
                <template v-if="ironhandStatus?.summary.revocation_p95_propagation_ms != null">
                  {{ ironhandStatus.summary.revocation_p95_propagation_ms }}ms
                </template>
                <template v-else>—</template>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty / filter empty -->
      <div v-if="filteredWorkers.length === 0" class="wt-empty">
        <div class="wt-empty-glyph"><Icon name="mdi:magnify" /></div>
        <p class="wt-empty-title">No workers match the current filter</p>
        <button class="wt-btn wt-btn--ghost" @click="resetFilters">Clear filters</button>
      </div>

      <!-- Worker grid -->
      <div v-else class="wt-grid">
        <div
          v-for="w in filteredWorkers"
          :key="w.name"
          class="wt-card"
          :class="cardClass(w)"
        >
          <!-- Top row: name + leader pill -->
          <div class="wt-card-head">
            <span class="wt-card-dot" :class="dotClass(w)"></span>
            <span class="wt-card-name">{{ w.name }}</span>
            <span v-if="w.has_leader" class="wt-pill wt-pill--ok">LEADER</span>
            <span v-else class="wt-pill wt-pill--warn">NO LEADER</span>
            <span class="wt-card-cat-pill" :class="catPillClass(w.category)">{{ w.category }}</span>
          </div>

          <!-- Description -->
          <div class="wt-card-desc">{{ w.description }}</div>

          <!-- Body grid -->
          <div class="wt-card-body">
            <div class="wt-card-row">
              <span class="wt-card-key">Schedule</span>
              <span class="wt-card-val">{{ w.schedule_label }}</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Leader worker</span>
              <span v-if="w.leader_worker" class="wt-card-val wt-mono" :title="w.leader_worker">{{ w.leader_worker }}</span>
              <span v-else class="wt-card-val wt-text-muted">—</span>
            </div>
            <div class="wt-card-row">
              <span class="wt-card-key">Lease TTL</span>
              <span v-if="w.lease_ttl_seconds != null" class="wt-card-val">{{ w.lease_ttl_seconds }}s</span>
              <span v-else class="wt-card-val wt-text-muted">—</span>
            </div>
            <!-- P5.2 (2026-05-08): last-run timestamp + status. Backend writes
                 these via background_tasks/leader.py:run_with_leadership. -->
            <div class="wt-card-row">
              <span class="wt-card-key">Last run</span>
              <span
                v-if="w.last_run_at"
                class="wt-card-val"
                :class="w.last_status === 'error' ? 'wt-text-error' : 'wt-text-ok'"
                :title="w.last_run_at"
              >
                {{ formatRelative(w.last_run_at) }}
                <span v-if="w.last_status === 'error'" class="wt-pill wt-pill--bad" style="margin-left:6px">ERROR</span>
              </span>
              <span v-else class="wt-card-val wt-text-muted">—</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="wt-footer">
        <code>/admin/workers/status</code> · Snapshot {{ snapshotTime }}
      </div>
    </div>

    <!-- §pass26 — Generic worker modal. Today only cross_teg_sweeper is
         mapped backend-side; the modal accepts worker_id so future workers
         can reuse the shell. -->
    <CrossTegSweeperModal
      v-if="sweeperModalOpen"
      :worker-id="'cross_teg_sweeper'"
      @close="closeSweeperModal"
    />

    <!-- §pass27 Phase 1 (2026-05-17) — canary_judge dedicated modal -->
    <CanaryJudgeModal
      v-if="judgeModalOpen"
      :worker-id="'canary_judge'"
      @close="closeJudgeModal"
    />

    <!-- §pass27 Phase 2 (2026-05-17) — canary_rebalancer dedicated modal -->
    <CanaryRebalancerModal
      v-if="rebalancerModalOpen"
      :worker-id="'canary_rebalancer'"
      @close="closeRebalancerModal"
    />

    <!-- §pass27 Phase 3 (2026-05-17) — saga_timeout_checker dedicated modal -->
    <SagaTimeoutCheckerModal
      v-if="sagaModalOpen"
      :worker-id="'saga_timeout_checker'"
      @close="closeSagaModal"
    />

    <!-- §pass28 Phase 4 (2026-05-17) — supply_auditor dedicated modal -->
    <SupplyAuditorModal
      v-if="supplyModalOpen"
      :worker-id="'supply_auditor'"
      @close="closeSupplyModal"
    />

    <!-- §pass28 Phase 5 (2026-05-17) — collusion_worker dedicated modal -->
    <CollusionWorkerModal
      v-if="collusionModalOpen"
      :worker-id="'collusion_worker'"
      @close="closeCollusionModal"
    />

    <!-- §pass29 Phase 6 (2026-05-17) — federation_sync dedicated modal -->
    <FederationSyncModal
      v-if="fedSyncModalOpen"
      :worker-id="'federation_sync'"
      @close="closeFedSyncModal"
    />

    <!-- §pass29 Phase 7 (2026-05-17) — agent_health_checker dedicated modal -->
    <AgentHealthModal
      v-if="agentHealthModalOpen"
      :worker-id="'agent_health_checker'"
      @close="closeAgentHealthModal"
    />

    <!-- §pass30 (2026-05-17) — canary IRONHAND mTLS dedicated modal -->
    <CanaryIronhandModal
      v-if="ironhandModalOpen"
      :worker-id="'canary_ironhand'"
      @close="closeIronhandModal"
    />

    <!-- §pass36 Option C Phase 3 (2026-05-17) — agent_card_pullsync dedicated modal -->
    <AgentCardPullSyncModal
      v-if="pullsyncModalOpen"
      @close="closePullsyncModal"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * WorkerTasksPanel — admin observability for the 22 background worker tasks.
 *
 * Build #4 (2026-05-07).
 * Strategy doc §4 Build #4. Backend: GET /admin/workers/status.
 */
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiClient } from '@/services/api/client'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import CrossTegSweeperModal from './CrossTegSweeperModal.vue'
import { getSweeperStatus, type SweeperStatusResponse } from '@/services/api/crossTegSweeper'
import CanaryJudgeModal from './CanaryJudgeModal.vue'
import { getCanaryJudgeStatus, type CanaryJudgeStatusResponse } from '@/services/api/canaryJudge'
import CanaryRebalancerModal from './CanaryRebalancerModal.vue'
import { getRebalancerStatus, type RebalancerStatusResponse } from '@/services/api/canaryRebalancer'
import SagaTimeoutCheckerModal from './SagaTimeoutCheckerModal.vue'
import { getSagaStatus, type SagaStatusResponse } from '@/services/api/sagaTimeout'
import SupplyAuditorModal from './SupplyAuditorModal.vue'
import { getSupplyAuditorStatus, type SupplyStatusResponse } from '@/services/api/supplyAuditor'
import CollusionWorkerModal from './CollusionWorkerModal.vue'
import { getCollusionStatus, type CollusionStatusResponse } from '@/services/api/collusionWorker'
import FederationSyncModal from './FederationSyncModal.vue'
import { getFederationSyncStatus, type FedSyncStatusResponse } from '@/services/api/federationSync'
import AgentHealthModal from './AgentHealthModal.vue'
import { getAgentHealthStatus, type AgentHealthStatusResponse } from '@/services/api/agentHealth'
import CanaryIronhandModal from './CanaryIronhandModal.vue'
import AgentCardPullSyncModal from './AgentCardPullSyncModal.vue'
import { getPullsyncStatus, type PullsyncStatusResponse } from '@/services/api/agentCardPullsync'
import { getCanaryIronhandStatus, type CanaryIronhandStatusResponse } from '@/services/api/canaryIronhand'

const { t } = useI18n()
// D6-835: the canary rebalancer and the supply auditor count in this frame's unit
const { localCurrency } = useCurrency()

// Idempotent — multiple imports register only once.
dayjs.extend(relativeTime)

interface WorkerStatus {
  name: string
  description: string
  schedule_label: string
  category: string
  has_leader: boolean
  leader_worker: string | null
  lease_ttl_seconds: number | null
  // P5.2 (2026-05-08): backend writes these via run_with_leadership in
  // background_tasks/leader.py after each cycle completes. May be null
  // for: workers that haven't fired yet, or older workers using a
  // different leadership pattern.
  last_run_at?: string | null
  last_status?: string | null  // "ok" | "error"
}

interface WorkersResponse {
  summary: {
    total: number
    with_leader: number
    no_leader: number
  }
  workers: WorkerStatus[]
  snapshot_at: string
}

const data = ref<WorkersResponse | null>(null)
const loading = ref(true)
const error = ref('')
const lastRefreshAt = ref('')
const autoRefresh = ref(true)
const activeCategory = ref<string | null>(null)
const showOnlyNoLeader = ref(false)
let refreshInterval: number | null = null

// §pass26 — cross-TEG sweeper observability state.
const sweeperStatus = ref<SweeperStatusResponse | null>(null)
const sweeperModalOpen = ref(false)
// One-shot guard so the error banner doesn't shout on every poll.
const sweeperErrorAnnounced = ref(false)

// §pass27 Phase 1 — canary_judge observability state.
const judgeStatus = ref<CanaryJudgeStatusResponse | null>(null)
const judgeModalOpen = ref(false)

// §pass27 Phase 2 — canary_rebalancer observability state.
const rebalancerStatus = ref<RebalancerStatusResponse | null>(null)
const rebalancerModalOpen = ref(false)

// §pass27 Phase 3 — saga_timeout_checker observability state.
const sagaStatus = ref<SagaStatusResponse | null>(null)
const sagaModalOpen = ref(false)

// §pass28 Phase 4 — supply_auditor observability state.
const supplyStatus = ref<SupplyStatusResponse | null>(null)
const supplyModalOpen = ref(false)

// §pass28 Phase 5 — collusion_worker observability state.
const collusionStatus = ref<CollusionStatusResponse | null>(null)
const collusionModalOpen = ref(false)

// §pass29 Phase 6 — federation_sync observability state.
const fedStatus = ref<FedSyncStatusResponse | null>(null)
const fedSyncModalOpen = ref(false)

// §pass29 Phase 7 — agent_health_checker observability state.
const agentHealthStatus = ref<AgentHealthStatusResponse | null>(null)
const agentHealthModalOpen = ref(false)

// §pass30 — canary IRONHAND mTLS observability state.
const ironhandStatus = ref<CanaryIronhandStatusResponse | null>(null)
const ironhandModalOpen = ref(false)

// §pass36 Option C Phase 3 — agent_card_pullsync observability state.
const pullsyncStatus = ref<PullsyncStatusResponse | null>(null)
// §FESUITE V0577: an aggregate read that failed left its card at LOADING for good (each catch below was silent), on a
// green card with green dashes; the card says UNREAD now and colours nothing it has not read
const aggUnread = reactive<Record<string, boolean>>({})
const pullsyncModalOpen = ref(false)

const CATEGORIES = [
  { id: null,           label: 'All' },
  { id: 'payments',     label: 'Payments' },
  { id: 'governance',   label: 'Governance' },
  { id: 'federation',   label: 'Federation' },
  { id: 'monitoring',   label: 'Monitoring' },
  { id: 'reputation',   label: 'Reputation' },
  { id: 'ledger',       label: 'Ledger' },
  { id: 'audit',        label: 'Audit' },
  { id: 'webhooks',     label: 'Webhooks' },
  { id: 'operations',   label: 'Ops' },
]

async function fetchStatus() {
  try {
    error.value = ''
    const resp = await apiClient.get<WorkersResponse>('/admin/workers/status')
    data.value = resp.data
    lastRefreshAt.value = dayjs().format('HH:mm:ss')
    loading.value = false
  } catch (e: any) {
    const msg = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
    error.value = `Failed to load worker status: ${msg}`
    loading.value = false
  }
}

// §pass26 — fetch sweeper aggregate every refresh tick. Best-effort: errors
// are swallowed so the workers tab stays useful even if the sweeper endpoint
// is unreachable (e.g. Prometheus partition).
async function fetchSweeperStatus() {
  try {
    sweeperStatus.value = await getSweeperStatus()
    aggUnread.sweeper = false
  } catch {
    // Silent — no UI churn for a transient Prom failure.
    aggUnread.sweeper = true
  }
}

// §pass27 Phase 1 — canary_judge aggregate. Same best-effort pattern.
async function fetchJudgeStatus() {
  try {
    judgeStatus.value = await getCanaryJudgeStatus()
    aggUnread.judge = false
  } catch {
    // Silent.
    aggUnread.judge = true
  }
}

// §pass27 Phase 2 — canary_rebalancer aggregate.
async function fetchRebalancerStatus() {
  try {
    rebalancerStatus.value = await getRebalancerStatus()
    aggUnread.rebalancer = false
  } catch {
    // Silent.
    aggUnread.rebalancer = true
  }
}

// §pass27 Phase 3 — saga_timeout_checker aggregate.
async function fetchSagaStatus() {
  try {
    sagaStatus.value = await getSagaStatus()
    aggUnread.saga = false
  } catch {
    // Silent.
    aggUnread.saga = true
  }
}

// §pass28 Phase 4 — supply_auditor aggregate.
async function fetchSupplyStatus() {
  try {
    supplyStatus.value = await getSupplyAuditorStatus()
    aggUnread.supply = false
  } catch {
    // Silent.
    aggUnread.supply = true
  }
}

// §pass28 Phase 5 — collusion_worker aggregate.
async function fetchCollusionStatus() {
  try {
    collusionStatus.value = await getCollusionStatus()
    aggUnread.collusion = false
  } catch {
    // Silent.
    aggUnread.collusion = true
  }
}

// §pass29 Phase 6 — federation_sync aggregate.
async function fetchFedStatus() {
  try {
    fedStatus.value = await getFederationSyncStatus()
    aggUnread.fed = false
  } catch {
    // Silent.
    aggUnread.fed = true
  }
}

// §pass29 Phase 7 — agent_health_checker aggregate.
async function fetchAgentHealthStatus() {
  try {
    agentHealthStatus.value = await getAgentHealthStatus()
    aggUnread.agentHealth = false
  } catch {
    // Silent.
    aggUnread.agentHealth = true
  }
}

// §pass30 — canary IRONHAND mTLS aggregate.
async function fetchIronhandStatus() {
  try {
    ironhandStatus.value = await getCanaryIronhandStatus()
    aggUnread.ironhand = false
  } catch {
    // Silent.
    aggUnread.ironhand = true
  }
}

// §pass36 Option C Phase 3 — agent_card_pullsync aggregate.
async function fetchPullsyncStatus() {
  try {
    pullsyncStatus.value = await getPullsyncStatus()
    aggUnread.pullsync = false
  } catch {
    // Silent.
    aggUnread.pullsync = true
  }
}

function startAutoRefresh() {
  if (refreshInterval !== null) return
  // Build #4: 10s interval, visibility-guarded (matches AdminReactors pattern)
  refreshInterval = window.setInterval(() => {
    if (document.visibilityState !== 'hidden') {
      fetchStatus()
      fetchSweeperStatus()
      fetchJudgeStatus()
      fetchRebalancerStatus()
      fetchSagaStatus()
      fetchSupplyStatus()
      fetchCollusionStatus()
      fetchFedStatus()
      fetchAgentHealthStatus()
      fetchIronhandStatus()
      fetchPullsyncStatus()
    }
  }, 10_000)
}
function stopAutoRefresh() {
  if (refreshInterval !== null) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    fetchStatus()
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

onMounted(() => {
  fetchStatus()
  fetchSweeperStatus()
  fetchJudgeStatus()
  fetchRebalancerStatus()
  fetchSagaStatus()
  fetchSupplyStatus()
  fetchCollusionStatus()
  fetchFedStatus()
  fetchAgentHealthStatus()
  fetchIronhandStatus()
  fetchPullsyncStatus()
  if (autoRefresh.value) startAutoRefresh()
})
onBeforeUnmount(() => { stopAutoRefresh() })

// §pass26 — sweeper modal control.
function openSweeperModal() {
  sweeperModalOpen.value = true
  // Mark as announced so the banner pulse de-escalates after the user has
  // engaged. We re-arm only if the banner is dismissed and the panel
  // remounts — keeps the signal noise-free.
  sweeperErrorAnnounced.value = true
}
function closeSweeperModal() {
  sweeperModalOpen.value = false
}

// §pass27 Phase 1 — judge modal control.
function openJudgeModal() { judgeModalOpen.value = true }
function closeJudgeModal() { judgeModalOpen.value = false }

// §pass27 Phase 2 — rebalancer modal control + formatter.
function openRebalancerModal() { rebalancerModalOpen.value = true }
function closeRebalancerModal() { rebalancerModalOpen.value = false }

// §pass27 Phase 3 — saga modal control.
function openSagaModal() { sagaModalOpen.value = true }
function closeSagaModal() { sagaModalOpen.value = false }

// §pass28 Phase 4 — supply auditor modal control.
function openSupplyModal() { supplyModalOpen.value = true }
function closeSupplyModal() { supplyModalOpen.value = false }

// §pass28 Phase 5 — collusion worker modal control.
function openCollusionModal() { collusionModalOpen.value = true }
function closeCollusionModal() { collusionModalOpen.value = false }

// §pass29 Phase 6 — federation_sync modal control.
function openFedSyncModal() { fedSyncModalOpen.value = true }
function closeFedSyncModal() { fedSyncModalOpen.value = false }

// §pass29 Phase 7 — agent_health_checker modal control.
function openAgentHealthModal() { agentHealthModalOpen.value = true }
function closeAgentHealthModal() { agentHealthModalOpen.value = false }
function openIronhandModal() { ironhandModalOpen.value = true }
function closeIronhandModal() { ironhandModalOpen.value = false }

// §pass36 Option C Phase 3 — agent_card_pullsync modal control.
function openPullsyncModal() { pullsyncModalOpen.value = true }
function closePullsyncModal() { pullsyncModalOpen.value = false }
function formatAvt(v?: string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = parseFloat(v)
  if (!Number.isFinite(n)) return v
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}

const sweeperHasErrors = computed(() => (sweeperStatus.value?.summary.errors_24h ?? 0) > 0)

const sweeperErrorTegCount = computed(() => {
  if (!sweeperStatus.value) return 0
  return sweeperStatus.value.per_op.filter(p => p.errors_24h > 0).length
})

const sweeperPillLabel = computed(() => {
  if (!sweeperStatus.value) return aggUnread.sweeper ? 'UNREAD' : 'LOADING'
  if (sweeperStatus.value.summary.errors_24h > 0) return 'ERRORS'
  if (sweeperStatus.value.summary.pending_total > 0) return 'PENDING'
  return 'HEALTHY'
})

const sweeperPillClass = computed(() => {
  if (!sweeperStatus.value) return 'wt-pill--muted'
  if (sweeperStatus.value.summary.errors_24h > 0) return 'wt-pill--bad'
  if (sweeperStatus.value.summary.pending_total > 0) return 'wt-pill--warn'
  return 'wt-pill--ok'
})

const sweeperDotClass = computed(() => {
  if (!sweeperStatus.value) return 'wt-card-dot--muted'
  if (sweeperStatus.value.summary.errors_24h > 0) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})

const sweeperCardClass = computed(() => ({
  'wt-card--ok':   !!sweeperStatus.value && !sweeperHasErrors.value,
  'wt-card--warn': sweeperHasErrors.value,
}))

// §pass27 Phase 1 — canary judge derived state.
//
// Failure-count vs. degradation:
// `failures_24h > 0` is the BASELINE in healthy operation (97% pass rate
// across 30 paths × ~30 tests/min ≈ 43K tests/day = ~1.3K expected daily
// failures from network blips + cross-frame races, NOT regressions). The
// banner should only fire on an ACTIONABLE condition — pass rate dropping
// below 95% over 24h, which is the same threshold as U6 verification gate
// and the prod canary alert. The CARD still shows raw failure counts for
// observability. Pass-rate is per_path-aware so a regression on a single
// path drags the fleet rate down meaningfully.
const judgeDegraded = computed(() => {
  const rate = judgeStatus.value?.summary.pass_rate_24h
  if (rate === null || rate === undefined) return false
  return rate < 95
})
const judgeHasFailures = judgeDegraded  // legacy alias for the template
const judgePillLabel = computed(() => {
  if (!judgeStatus.value) return aggUnread.judge ? 'UNREAD' : 'LOADING'
  const rate = judgeStatus.value.summary.pass_rate_24h
  if (rate === null) return 'NO DATA'
  if (rate < 90) return 'DEGRADED'
  if (rate < 97) return 'WARN'
  return 'HEALTHY'
})
const judgePillClass = computed(() => {
  if (!judgeStatus.value) return 'wt-pill--muted'
  const rate = judgeStatus.value.summary.pass_rate_24h
  if (rate === null) return 'wt-pill--muted'
  if (rate < 90) return 'wt-pill--bad'
  if (rate < 97) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const judgeDotClass = computed(() => {
  if (!judgeStatus.value) return 'wt-card-dot--muted'
  const rate = judgeStatus.value.summary.pass_rate_24h
  if (rate === null) return 'wt-card-dot--muted'
  if (rate < 90) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const judgeCardClass = computed(() => ({
  'wt-card--ok':   !!judgeStatus.value && !judgeHasFailures.value,
  'wt-card--warn': judgeHasFailures.value,
}))

// §pass27 Phase 2 — canary_rebalancer derived state.
//
// Why the banner gates on `agents_under_floor` instead of `errors_24h`:
// `errors_24h` includes chronic `balance_query_failed` for canary agents
// whose home TEGs are unreachable from this registry (~2 prod agents,
// pre-existing network condition). They emit one error per 5-min cycle
// — ~288/day each — which would keep a raw-error banner permanently
// armed and desensitise the operator. The ACTIONABLE signal is "a
// canary agent's liquid balance has crossed the FLOOR" because that
// means a payment path is about to starve. Errors stay visible in the
// CARD row + modal, but they don't trigger the alarm.
const rebalancerHasErrors = computed(() => (rebalancerStatus.value?.summary.errors_24h ?? 0) > 0)
const rebalancerHasUnderfloor = computed(() => (rebalancerStatus.value?.summary.agents_under_floor ?? 0) > 0)
// The banner-fires-when condition. Tightened from the original ||.
const rebalancerNeedsAttention = rebalancerHasUnderfloor
const rebalancerPillLabel = computed(() => {
  if (!rebalancerStatus.value) return aggUnread.rebalancer ? 'UNREAD' : 'LOADING'
  if (rebalancerHasErrors.value) return 'ERRORS'
  if (rebalancerHasUnderfloor.value) return 'REFUNDING'
  if (!rebalancerStatus.value.config.enabled) return 'DISABLED'
  return 'HEALTHY'
})
const rebalancerPillClass = computed(() => {
  if (!rebalancerStatus.value) return 'wt-pill--muted'
  if (rebalancerHasErrors.value) return 'wt-pill--bad'
  if (rebalancerHasUnderfloor.value) return 'wt-pill--warn'
  if (!rebalancerStatus.value.config.enabled) return 'wt-pill--muted'
  return 'wt-pill--ok'
})
const rebalancerDotClass = computed(() => {
  if (!rebalancerStatus.value) return 'wt-card-dot--muted'
  if (rebalancerHasErrors.value) return 'wt-card-dot--warn'
  if (rebalancerHasUnderfloor.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const rebalancerCardClass = computed(() => ({
  'wt-card--ok':   !!rebalancerStatus.value && !rebalancerHasErrors.value && !rebalancerHasUnderfloor.value,
  'wt-card--warn': rebalancerHasErrors.value || rebalancerHasUnderfloor.value,
}))

// §pass27 Phase 3 — saga_timeout_checker derived state.
const sagaHasErrors = computed(() => (sagaStatus.value?.summary.errors_24h ?? 0) > 0)
const sagaHasPending = computed(() => (sagaStatus.value?.summary.pending_now ?? 0) > 0)
const sagaPillLabel = computed(() => {
  if (!sagaStatus.value) return aggUnread.saga ? 'UNREAD' : 'LOADING'
  if (sagaHasErrors.value) return 'ERRORS'
  if (sagaHasPending.value) return 'PENDING'
  return 'HEALTHY'
})
const sagaPillClass = computed(() => {
  if (!sagaStatus.value) return 'wt-pill--muted'
  if (sagaHasErrors.value) return 'wt-pill--bad'
  if (sagaHasPending.value) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const sagaDotClass = computed(() => {
  if (!sagaStatus.value) return 'wt-card-dot--muted'
  if (sagaHasErrors.value || sagaHasPending.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const sagaCardClass = computed(() => ({
  'wt-card--ok':   !!sagaStatus.value && !sagaHasErrors.value && !sagaHasPending.value,
  'wt-card--warn': sagaHasErrors.value || sagaHasPending.value,
}))

// §pass28 Phase 4 — supply_auditor derived state.
//
// Banner fires ONLY on actual breach. Live-Δ > 0 is shown in the card body
// but is NOT alarm-worthy (could be transient between cycles); a breach
// event is the durable signal that supply conservation has actually failed.
const supplyAbsDelta = computed(() => {
  const v = supplyStatus.value?.summary.live_delta
  if (v === null || v === undefined) return 0
  return Math.abs(parseFloat(String(v)))
})
const supplyHasBreach = computed(() => (supplyStatus.value?.summary.breaches_24h ?? 0) > 0)
const supplyPillLabel = computed(() => {
  if (!supplyStatus.value) return aggUnread.supply ? 'UNREAD' : 'LOADING'
  if (supplyHasBreach.value) return 'BREACH'
  const s = supplyStatus.value.summary.live_status
  if (s === 'BREACH') return 'Δ>0'
  if (s === 'OK') return 'HEALTHY'
  return s || 'UNKNOWN'
})
const supplyPillClass = computed(() => {
  if (!supplyStatus.value) return 'wt-pill--muted'
  if (supplyHasBreach.value) return 'wt-pill--bad'
  if (supplyAbsDelta.value > 0) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const supplyDotClass = computed(() => {
  if (!supplyStatus.value) return 'wt-card-dot--muted'
  if (supplyHasBreach.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const supplyCardClass = computed(() => ({
  'wt-card--ok':   !!supplyStatus.value && !supplyHasBreach.value,
  'wt-card--warn': supplyHasBreach.value,
}))
const supplyStatusValClass = computed(() => {
  const s = supplyStatus.value?.summary.live_status
  if (s === 'BREACH') return 'wt-text-error'
  if (s === 'OK') return 'wt-text-ok'
  return ''
})

// §pass28 Phase 5 — collusion_worker derived state.
//
// Banner fires only when NEW rings are detected within the last 24h —
// lifetime rings count alone isn't actionable (older detections may be
// already triaged). Errors_24h also fires the banner if scan/decay fails.
const collusionHasRings = computed(() => (collusionStatus.value?.summary.rings_24h ?? 0) > 0)
const collusionHasErrors = computed(() => (collusionStatus.value?.summary.errors_24h ?? 0) > 0)
const collusionPillLabel = computed(() => {
  if (!collusionStatus.value) return aggUnread.collusion ? 'UNREAD' : 'LOADING'
  if (collusionHasErrors.value) return 'ERRORS'
  if (collusionHasRings.value) return 'NEW RINGS'
  return 'CLEAN'
})
const collusionPillClass = computed(() => {
  if (!collusionStatus.value) return 'wt-pill--muted'
  if (collusionHasErrors.value) return 'wt-pill--bad'
  if (collusionHasRings.value) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const collusionDotClass = computed(() => {
  if (!collusionStatus.value) return 'wt-card-dot--muted'
  if (collusionHasErrors.value || collusionHasRings.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const collusionCardClass = computed(() => ({
  'wt-card--ok':   !!collusionStatus.value && !collusionHasErrors.value && !collusionHasRings.value,
  'wt-card--warn': collusionHasErrors.value || collusionHasRings.value,
}))

// §pass29 Phase 6 — federation_sync derived state.
//
// Banner gates on stale_active_peers > 0 (actionable: peer X hasn't been
// synced in N cycles, agent cards from that peer are going stale). Raw
// errors_24h alone shows in the card body but isn't a banner trigger
// since transient peer-unreachable errors are baseline.
const fedHasStalePeers = computed(() => (fedStatus.value?.summary.stale_active_peers ?? 0) > 0)
const fedHasErrors = computed(() => (fedStatus.value?.summary.errors_24h ?? 0) > 0)
const fedPillLabel = computed(() => {
  if (!fedStatus.value) return aggUnread.fed ? 'UNREAD' : 'LOADING'
  if (fedHasStalePeers.value) return 'STALE PEERS'
  if (fedHasErrors.value) return 'ERRORS'
  return 'HEALTHY'
})
const fedPillClass = computed(() => {
  if (!fedStatus.value) return 'wt-pill--muted'
  if (fedHasStalePeers.value) return 'wt-pill--warn'
  if (fedHasErrors.value) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const fedDotClass = computed(() => {
  if (!fedStatus.value) return 'wt-card-dot--muted'
  if (fedHasStalePeers.value || fedHasErrors.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const fedCardClass = computed(() => ({
  'wt-card--ok':   !!fedStatus.value && !fedHasStalePeers.value && !fedHasErrors.value,
  'wt-card--warn': fedHasStalePeers.value || fedHasErrors.value,
}))

// §pass29 Phase 7 — agent_health_checker derived state.
//
// Banner gates on agents_unreachable > 0 — that's the actionable signal
// (can't even reach the agent). agents_unhealthy in card body shows
// non-200 probes which can be transient. State changes 24h in card body
// surfaces flapping without being alarm-worthy.
const agentHealthHasUnreachable = computed(() => (agentHealthStatus.value?.summary.agents_unreachable ?? 0) > 0)
const agentHealthHasUnhealthy = computed(() => (agentHealthStatus.value?.summary.agents_unhealthy ?? 0) > 0)
const agentHealthPillLabel = computed(() => {
  if (!agentHealthStatus.value) return aggUnread.agentHealth ? 'UNREAD' : 'LOADING'
  if (agentHealthHasUnreachable.value) return 'UNREACHABLE'
  if (agentHealthHasUnhealthy.value) return 'UNHEALTHY'
  return 'HEALTHY'
})
const agentHealthPillClass = computed(() => {
  if (!agentHealthStatus.value) return 'wt-pill--muted'
  if (agentHealthHasUnreachable.value) return 'wt-pill--bad'
  if (agentHealthHasUnhealthy.value) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const agentHealthDotClass = computed(() => {
  if (!agentHealthStatus.value) return 'wt-card-dot--muted'
  if (agentHealthHasUnreachable.value || agentHealthHasUnhealthy.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const agentHealthCardClass = computed(() => ({
  'wt-card--ok':   !!agentHealthStatus.value && !agentHealthHasUnreachable.value && !agentHealthHasUnhealthy.value,
  'wt-card--warn': agentHealthHasUnreachable.value || agentHealthHasUnhealthy.value,
}))

// §pass30 — canary IRONHAND mTLS derived state.
//
// Banner gates on failures_24h > 0 — FAIL LOUDLY means any failure is actionable.
// The pass_rate threshold is 97 (warn) / 90 (bad) matching judge.
const ironhandHasFailures = computed(() => (ironhandStatus.value?.summary.failures_24h ?? 0) > 0)
const ironhandPassRateLow = computed(() => {
  const r = ironhandStatus.value?.summary.pass_rate_24h
  return r !== null && r !== undefined && r < 97
})
const ironhandPillLabel = computed(() => {
  if (!ironhandStatus.value) return aggUnread.ironhand ? 'UNREAD' : 'LOADING'
  if (ironhandHasFailures.value) return 'FAILING'
  if (ironhandPassRateLow.value) return 'DEGRADED'
  return 'HEALTHY'
})
const ironhandPillClass = computed(() => {
  if (!ironhandStatus.value) return 'wt-pill--muted'
  if (ironhandHasFailures.value) return 'wt-pill--bad'
  if (ironhandPassRateLow.value) return 'wt-pill--warn'
  return 'wt-pill--ok'
})
const ironhandDotClass = computed(() => {
  if (!ironhandStatus.value) return 'wt-card-dot--muted'
  if (ironhandHasFailures.value) return 'wt-card-dot--bad'
  if (ironhandPassRateLow.value) return 'wt-card-dot--warn'
  return 'wt-card-dot--ok-bright'
})
const ironhandCardClass = computed(() => ({
  'wt-card--ok':   !!ironhandStatus.value && !ironhandHasFailures.value && !ironhandPassRateLow.value,
  'wt-card--warn': ironhandPassRateLow.value && !ironhandHasFailures.value,
  'wt-card--bad':  ironhandHasFailures.value,
}))

const uniqueCategories = computed(() => {
  if (!data.value) return []
  return [...new Set(data.value.workers.map(w => w.category))].sort()
})

const filteredWorkers = computed<WorkerStatus[]>(() => {
  if (!data.value) return []
  let list = data.value.workers
  if (activeCategory.value) {
    list = list.filter(w => w.category === activeCategory.value)
  }
  if (showOnlyNoLeader.value) {
    list = list.filter(w => !w.has_leader)
  }
  return list
})

function resetFilters() {
  activeCategory.value = null
  showOnlyNoLeader.value = false
}

const snapshotTime = computed(() => {
  if (!data.value?.snapshot_at) return ''
  return dayjs(data.value.snapshot_at).format('HH:mm:ss')
})

function cardClass(w: WorkerStatus): string[] {
  const out = ['wt-card']
  if (w.has_leader) out.push('wt-card--ok')
  else out.push('wt-card--warn')
  if (w.category === 'unknown') out.push('wt-card--unknown')
  return out
}
function dotClass(w: WorkerStatus): string {
  if (!w.has_leader) return 'wt-card-dot--warn'
  if (w.category === 'audit' || w.category === 'monitoring') return 'wt-card-dot--ok-bright'
  return 'wt-card-dot--ok'
}
function catPillClass(cat: string): string {
  switch (cat) {
    case 'payments':   return 'wt-card-cat-pill--cyan'
    case 'governance': return 'wt-card-cat-pill--violet'
    case 'federation': return 'wt-card-cat-pill--indigo'
    case 'monitoring': return 'wt-card-cat-pill--amber'
    case 'reputation': return 'wt-card-cat-pill--green'
    case 'ledger':     return 'wt-card-cat-pill--cyan'
    case 'audit':      return 'wt-card-cat-pill--green'
    case 'webhooks':   return 'wt-card-cat-pill--orange'
    case 'operations': return 'wt-card-cat-pill--soft'
    default:           return 'wt-card-cat-pill--muted'
  }
}

// P5.2 (2026-05-08): relative time for last-run.
function formatRelative(iso: string): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}
</script>

<style scoped>
.wt-panel {
  position: relative;
  z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
}

/* ── Loading / Error ────────────────────────────────────── */
.wt-center {
  text-align: center;
  padding: 4rem 1rem;
}
.wt-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--nc-primary-rgb), 0.2);
  border-top-color: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 50%;
  animation: wt-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes wt-spin { to { transform: rotate(360deg); } }
.wt-loading-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: var(--nc-text-muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.wt-error-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  color: var(--nc-danger);
}

/* ── Stats row ─────────────────────────────────────────── */
.wt-stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.wt-stat {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.wt-stat--cyan { border-top-color: rgba(var(--nc-primary-rgb), 0.32); }
.wt-stat--ok   { border-top-color: rgba(0, 255, 136, 0.4); }
.wt-stat--warn { border-top-color: rgba(255, 149, 0, 0.4); }
.wt-stat--muted { border-top-color: rgba(255, 255, 255, 0.1); opacity: 0.85; }

.wt-stat-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
  font-weight: 600;
}
.wt-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.1;
  color: rgba(var(--nc-primary-rgb), 1);
}
.wt-stat--ok .wt-stat-value   { color: var(--nc-success); }
.wt-stat--warn .wt-stat-value { color: var(--nc-warning); }
.wt-stat--muted .wt-stat-value { color: rgba(255, 255, 255, 0.55); }
.wt-stat-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--nc-text-muted);
}

/* ── Toolbar ───────────────────────────────────────────── */
.wt-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.85rem;
  padding: 0.6rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  margin-bottom: 0.85rem;
}
.wt-toolbar-left, .wt-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.wt-toolbar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.55);
  font-weight: 600;
  margin-right: 0.25rem;
}
.wt-mono-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.1em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
}
.wt-mono-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb), 1);
}

.wt-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.6);
  background: rgba(var(--nc-primary-rgb), 0.04);
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
}
.wt-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.wt-chip--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  color: rgba(var(--nc-primary-rgb), 1);
}

.wt-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.wt-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.wt-btn--ghost {
  background: transparent;
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.wt-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  color: rgba(var(--nc-primary-rgb), 1);
}
.wt-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
}
.wt-btn--primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.3);
}

.wt-live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--nc-text-muted);
}
.wt-live-dot--on {
  background: var(--nc-success);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.6);
  animation: wt-pulse 2s ease-in-out infinite;
}
@keyframes wt-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(0, 255, 136, 0.6); }
  50% { box-shadow: 0 0 14px rgba(0, 255, 136, 0.9); }
}

/* ── Note ──────────────────────────────────────────────── */
.wt-note {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  background: rgba(var(--nc-primary-rgb), 0.03);
  border-left: 2px solid rgba(var(--nc-primary-rgb), 0.3);
  padding: 0.7rem 0.9rem;
  border-radius: 4px;
  margin-bottom: 1rem;
}
.wt-note-icon {
  color: rgba(var(--nc-primary-rgb), 1);
  font-size: 0.95rem;
  flex-shrink: 0;
  margin-top: 1px;
}
.wt-note-body { display: flex; flex-direction: column; gap: 0.18rem; }
.wt-note-title {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-weight: 600;
  text-transform: uppercase;
}
.wt-note-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.6;
}
.wt-note-text code {
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: rgba(var(--nc-primary-rgb), 1);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.62rem;
}

/* ── Empty ─────────────────────────────────────────────── */
.wt-empty {
  text-align: center;
  padding: 2.4rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.wt-empty-glyph { font-size: 1.8rem; opacity: 0.5; margin-bottom: 0.4rem; }
.wt-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.6rem;
}

/* ── Card grid ─────────────────────────────────────────── */
.wt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 0.85rem;
  margin-bottom: 1rem;
}

.wt-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.92), rgba(6, 8, 16, 0.88));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-top-width: 2px;
  border-radius: 8px;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.wt-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.3);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3), 0 0 24px rgba(var(--nc-primary-rgb), 0.06);
}
.wt-card--ok      { border-top-color: rgba(0, 255, 136, 0.4); }
.wt-card--warn    { border-top-color: rgba(255, 149, 0, 0.4); opacity: 0.8; }
.wt-card--unknown { border-top-color: rgba(255, 51, 102, 0.4); }

.wt-card-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.wt-card-dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0;
}
.wt-card-dot--ok        { background: var(--nc-success); box-shadow: 0 0 6px rgba(0, 255, 136, 0.5); }
.wt-card-dot--ok-bright { background: var(--nc-success); box-shadow: 0 0 10px rgba(0, 255, 136, 0.8); animation: wt-pulse 1.6s infinite; }
.wt-card-dot--warn      { background: var(--nc-warning); }
/* §FESUITE V0577: the computeds named these two and nothing defined them, so the dot of an unread card, and of a
   failing ironhand card, had no colour at all (the base rule sets none) */
.wt-card-dot--muted     { background: rgba(255, 255, 255, 0.25); box-shadow: none; }
.wt-card-dot--bad       { background: #ff6b81; box-shadow: 0 0 6px rgba(255, 51, 102, 0.5); }

.wt-card-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
}

.wt-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 1px 7px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.wt-pill--ok   { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.wt-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }

.wt-card-cat-pill {
  margin-left: auto;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.52rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  text-transform: uppercase;
}
.wt-card-cat-pill--cyan   { background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 1); border-color: rgba(var(--nc-primary-rgb), 0.3); }
.wt-card-cat-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.wt-card-cat-pill--indigo { background: rgba(99, 102, 241, 0.1); color: #a5b4fc; border-color: rgba(99, 102, 241, 0.3); }
.wt-card-cat-pill--amber  { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.wt-card-cat-pill--green  { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.wt-card-cat-pill--orange { background: rgba(255, 149, 0, 0.08); color: rgba(255, 149, 0, 0.85); border-color: rgba(255, 149, 0, 0.25); }
.wt-card-cat-pill--soft   { background: rgba(99, 179, 237, 0.08); color: rgba(99, 179, 237, 0.95); border-color: rgba(99, 179, 237, 0.25); }
.wt-card-cat-pill--muted  { background: rgba(var(--nc-primary-rgb), 0.04); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--nc-primary-rgb), 0.18); }

.wt-card-desc {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.5;
}

.wt-card-body {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.4rem;
  padding-top: 0.4rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.wt-card-row {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}
.wt-card-key {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  letter-spacing: 0.1em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
  font-weight: 600;
}
.wt-card-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}
.wt-mono { font-family: 'IBM Plex Mono', monospace; }
.wt-text-muted { color: var(--nc-text-muted); }
.wt-text-ok    { color: rgba(255, 255, 255, 0.85); }
.wt-text-warn  { color: var(--nc-warning); }
.wt-text-error { color: #ff6b81; }
.wt-pill--bad    { background: rgba(255, 51, 102, 0.18); border-color: rgba(255, 51, 102, 0.45); color: #ff6b81; }
.wt-pill--muted  { background: rgba(255, 255, 255, 0.06); border-color: rgba(255, 255, 255, 0.12); color: rgba(255, 255, 255, 0.55); }

/* ── §pass26: Cross-TEG sweeper card + banner ─────────────── */
.wt-cts-section {
  margin: 1.5rem 0 1.6rem 0;
  padding-bottom: 1rem;
  border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.10);
}
.wt-cts-section-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(var(--nc-primary-rgb), 0.92);
  margin: 0 0 0.75rem 0;
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
}
.wt-cts-section-sub {
  font-size: 0.62rem;
  font-weight: 400;
  letter-spacing: 0.02em;
  color: var(--nc-text-muted);
  text-transform: none;
}
.wt-cts-error-banner {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.7rem 0.9rem;
  margin-bottom: 0.75rem;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.32);
  border-radius: 6px;
  color: #ff8a9c;
  font-size: 0.78rem;
  font-family: 'IBM Plex Mono', monospace;
}
.wt-cts-banner-glyph {
  font-size: 1.1rem;
  flex-shrink: 0;
  color: #ff6b81;
}
.wt-cts-banner-text { flex: 1; line-height: 1.45; }
.wt-cts-banner-text strong { color: #ffb1bc; }
.wt-cts-banner-text em {
  font-style: normal;
  color: rgba(var(--nc-primary-rgb), 0.95);
  border-bottom: 1px dashed currentColor;
}
.wt-card--cts {
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, transform 0.15s;
}
.wt-card--cts:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  transform: translateY(-1px);
}
.wt-card--cts:focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb), 0.65);
  outline-offset: 2px;
}
.wt-cts-details-btn {
  font-size: 0.7rem;
  padding: 3px 10px;
}

/* ── Footer ──────────────────────────────────────────── */
.wt-footer {
  margin-top: 1.4rem;
  padding-top: 0.85rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  text-align: center;
}
.wt-footer code {
  background: rgba(var(--nc-primary-rgb), 0.08);
  padding: 1px 5px;
  border-radius: 3px;
  color: rgba(var(--nc-primary-rgb), 1);
}

/* ── Responsive ────────────────────────────────────── */
@media (max-width: 768px) {
  .wt-panel { padding: 0 16px; }
  .wt-grid { grid-template-columns: 1fr; }
  .wt-toolbar { flex-direction: column; align-items: flex-start; }
}
</style>
