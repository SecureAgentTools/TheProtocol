<template>
  <div :class="['auditor-root', 'alarm-' + alarmLevel]">
    <!-- Critical-breach veil: the whole observatory flushes red -->
    <div v-if="alarmLevel === 'critical'" class="au-alarm-veil" aria-hidden="true"></div>

    <!-- HEADER -->
    <header class="au-header">
      <div class="au-header-left">
        <ProtocolMark :size="30" glow :alive="alarmLevel === 'critical'" :tone="alarmLevel === 'critical' ? 'red' : 'green'" class="au-brandmark" />
        <h1 class="au-title">THE AUDITOR</h1>
        <span class="au-subtitle">Supply Invariant Guardian</span>
        <div class="au-mode-toggle" role="group" aria-label="Audit tier" v-if="availableModes.length > 1">
          <button
            v-for="m in availableModes"
            :key="m"
            type="button"
            :class="['au-mode-btn', m, { active: mode === m }]"
            :aria-pressed="mode === m"
            @click="auditorStore.setMode(m)"
          >{{ modeLabel(m) }}</button>
        </div>
      </div>
      <div class="au-header-right">
        <TpsaBadge />
        <span class="au-header-sep"></span>
        <span class="au-clock au-mono">{{ clock }}<span class="au-clock-z"> UTC</span></span>
        <span class="au-header-sep"></span>
        <span :class="['au-live-dot', wsConnected ? 'live' : 'offline']"></span>
        <span :class="['au-live-label', wsConnected ? 'live' : 'offline']">{{ wsConnected ? 'LIVE' : 'OFFLINE' }}</span>
        <span class="au-header-sep"></span>
        <span class="au-header-meta" v-if="stats">{{ stats.total_audits.toLocaleString() }} audits</span>
        <span class="au-header-sep"></span>
        <span class="au-header-meta">{{ frames.length }} frame{{ frames.length !== 1 ? 's' : '' }}</span>
        <span class="au-header-sep"></span>
        <span class="au-header-meta" v-if="stats">{{ stats.uptime_pct == null ? 'uptime not measured' : stats.uptime_pct + '% uptime' }}</span>
      </div>
    </header>
    <div class="au-header-line"></div>

    <!-- BREACH ALARM BAR (klaxon) -->
    <div v-if="alarmLevel !== 'none'" :class="['au-alarm-bar', alarmLevel]" role="alert" aria-live="assertive" data-testid="invariant-klaxon">
      <span class="au-alarm-klaxon">&#9888;</span>
      <span class="au-alarm-title">{{ alarmLevel === 'critical' ? 'INVARIANT BREACH DETECTED' : 'INVARIANT BREACH &middot; CONTAINED' }}</span>
      <span class="au-alarm-frames">
        <span v-for="f in breachingFrames" :key="f.id" class="au-alarm-frame">
          {{ f.name }} <span class="au-alarm-delta au-mono">&#x0394; {{ breachDeltaDisplay(f.id) }} {{ f.currency || 'AVT' }}</span>
        </span>
      </span>
      <span class="au-alarm-spacer"></span>
      <span class="au-alarm-status">{{ alarmLevel === 'critical' ? 'ACTION REQUIRED' : 'EXPECTED &mdash; MAINTENANCE' }}</span>
    </div>

    <!-- §GLOBALSTD 4.2 — STALENESS is a first-class state, not a quietly old
         timestamp. Fires when the newest completed cycle in this view is older
         than 5 minutes (cadence is 60s); mirrors the AuditorCycleStall alert. -->
    <div v-if="staleAgeSec !== null && staleAgeSec > 300" class="au-stale-banner" role="alert">
      <span class="au-stale-glyph">&#9203;</span>
      <span class="au-stale-title">AUDIT DATA STALE</span>
      <span class="au-stale-copy">last completed cycle was
        <b class="au-mono">{{ Math.round(staleAgeSec / 60) }} min</b> ago (cadence 60s) &mdash;
        the invariant is <b>unwatched</b> while this persists</span>
    </div>

    <!-- MAINTENANCE BANNER (reusable; live-togglable) -->
    <div v-if="maintenance && maintenance.active" class="au-maint-banner" role="status">
      <div class="au-maint-stripe"></div>
      <div class="au-maint-icon">&#9888;</div>
      <div class="au-maint-body">
        <div class="au-maint-top">
          <span class="au-maint-pill">MAINTENANCE</span>
          <span class="au-maint-title">{{ maintenance.title || 'Maintenance in progress' }}</span>
          <span class="au-maint-ref" v-if="maintenance.patch_ref">{{ maintenance.patch_ref }}</span>
        </div>
        <div class="au-maint-msg">{{ maintenance.message }}</div>
        <div class="au-maint-meta">
          <span v-if="maintenance.since">since {{ formatDateTime(maintenance.since) }}</span>
          <span class="au-maint-dot" v-if="maintenance.since && patchNotes.length">&middot;</span>
          <a v-if="patchNotes.length" class="au-maint-link" @click.stop="openIncidentLog()">view patch notes &#x2193;</a>
        </div>
      </div>
    </div>

    <!-- ═══ THE VERDICT ═══
         One row per frame answering the single question this whole page exists to answer.
         Everything below is the evidence behind it. Added 2026-08-01 because the page was
         eighteen co-equal cards and no answer. -->
    <!-- §MTLSHOPS (a) (2026-09-15): a public-only frame's persistent public BREACH is its own notice, never the invariant klaxon -->
    <div v-if="publicBreachFrames.length" class="au-alarm-bar au-public-breach-bar" role="status" data-testid="public-breach-bar">
      <span class="au-alarm-klaxon">&#9888;</span>
      <span class="au-alarm-title">PUBLIC SUPPLY AUDIT BREACH</span>
      <span class="au-alarm-frames">
        <span v-for="f in publicBreachFrames" :key="f.id" class="au-alarm-frame">
          {{ f.name }} <span class="au-alarm-delta au-mono">read BREACH {{ latestOf(f.id)?.public_breach_streak }} times in a row</span>
        </span>
      </span>
      <span class="au-alarm-spacer"></span>
      <span class="au-alarm-status">THE EXACT CHECK BELONGS TO THE FRAME'S OWN AUDITOR</span>
    </div>
    <FrameVerdictBand :latest-by-frame="latestByFrame" :frames="frames" />
    <AttestationSeal />

    <!-- MAIN GRID -->
    <div class="au-main-grid">

      <!-- LEFT: Hero cards -->
      <div class="au-hero-col">
        <!-- System conservation crest -->
        <div class="au-conserve-crest" :class="['alarm-' + alarmLevel, { live: allConserved }]" role="status" aria-live="polite" data-testid="conserve-crest">
          <span class="au-crest-glyph" aria-hidden="true">&#x25C8;</span>
          <span class="au-crest-text">{{ crestText }}</span>
          <span class="au-crest-sep"></span>
          <span class="au-crest-meta">{{ truthFrames.length }} FRAME{{ truthFrames.length !== 1 ? 'S' : '' }} &middot; &#x0394; {{ systemAtomicDisplay }}<template v-if="frameConfigs.length > truthFrames.length"> &middot; {{ frameConfigs.length - truthFrames.length }} PUBLIC-ONLY</template></span>
        </div>
        <div class="au-hero-row">
          <div
            v-for="frame in frameConfigs"
            :key="frame.id"
            :class="['au-hero-card', frameCardClass(frame.id)]"
          >
            <div class="au-hero-scanline"></div>
            <div class="au-hero-seal" :class="deltaClass(frame.id)"></div>
            <div class="au-hero-ring ring-1" :class="deltaClass(frame.id)"></div>
            <div class="au-hero-ring ring-2" :class="deltaClass(frame.id)"></div>
            <div class="au-hero-ring ring-3" :class="deltaClass(frame.id)"></div>
            <div class="au-hero-content">
              <div :class="['au-frame-label', frameLabelClass(frame.id)]">{{ frame.name.toUpperCase() }}</div>
              <div class="au-hero-label au-label">{{ atomicAvailable(frame.id) ? 'ATOMIC INVARIANT Δ' : isPublicOnly(frame.id) ? 'PUBLIC SUPPLY Δ' : 'SUPPLY Δ (LIVE)' }}</div>
              <div :class="['au-hero-value', deltaClass(frame.id)]">
                <AnimatedNumber v-if="latestByFrame[frame.id]" :value="headlineNum(frame.id)" :decimals="1" />
                <span v-else>---</span>
              </div>
              <div class="au-hero-status" v-if="latestByFrame[frame.id]">
                <span :class="['au-hero-check', deltaClass(frame.id)]">{{ truthIcon(frame.id) }}</span>
                <span :class="['au-hero-badge', deltaClass(frame.id)]" :data-testid="'hero-badge-' + frame.id">{{ statusLabel(frame.id) }}</span>
              </div>
              <!-- New delta feature: live-read Δ shown additionally to the atomic truth -->
              <div class="au-hero-sub" v-if="atomicAvailable(frame.id)">
                <span class="au-hero-sub-label">LIVE-READ &#x0394;</span>
                <span :class="['au-hero-sub-val', isDivergent(frame.id) ? 'diverge' : 'match']">{{ liveDisplay(frame.id) }}</span>
                <span class="au-hero-sub-tag" v-if="isDivergent(frame.id)" title="HTTP /supply-audit differs from the atomic invariant — transient outbox lag or a legacy read-model counter; the atomic Δ is the truth">&#8800; atomic</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Invariant Formula -->
        <div class="au-formula-card">
          <div class="au-formula-head">
            <span class="au-formula-label au-label">INVARIANT &mdash; VERIFIED ATOMICALLY</span>
            <span :class="['au-formula-stamp', 'alarm-' + alarmLevel]" data-testid="formula-stamp">{{ formulaStamp }}</span>
          </div>
          <div class="au-formula-block">
            <span class="au-formula-term">tokens_issued &minus; tokens_destroyed</span>
            <span :class="['au-formula-eq', combinedDeltaClass]">══════════════</span>
            <span class="au-formula-term">&Sigma; (liquid + locked)</span>
          </div>
          <div class="au-formula-footer">
            <span :class="['au-formula-dot', wsConnected ? 'live' : 'offline']"></span>
            <span class="au-formula-note">Single-statement snapshot per frame &middot; every {{ auditInterval }}s &middot; HTTP read-skew shown separately as live-read &#x0394;</span>
          </div>
        </div>
      </div>

      <!-- RIGHT: Chart + Supply Detail -->
      <div class="au-right-col">
        <!-- Delta Trend Chart -->
        <div class="au-chart-card card" :data-series="chartConfig.datasets.map((d) => d.label).join('|')" :data-chart-mode="chartMode" data-testid="delta-trend">
          <div class="au-chart-header">
            <span class="au-label">{{ chartMode === 'atomic' ? 'ATOMIC Δ TREND' : 'LIVE-READ Δ TREND' }}</span>
            <span :class="['au-chart-live', wsConnected ? 'on' : 'off']"><span class="au-chart-live-dot"></span>{{ wsConnected ? 'LIVE' : 'OFFLINE' }}</span>
            <div class="au-chart-toggle" role="tablist" aria-label="Delta source">
              <button
                :class="['au-toggle-btn', { active: chartMode === 'atomic' }]"
                @click="chartMode = 'atomic'"
                role="tab" :aria-selected="chartMode === 'atomic'"
              >ATOMIC</button>
              <button
                :class="['au-toggle-btn', { active: chartMode === 'live' }]"
                @click="chartMode = 'live'"
                role="tab" :aria-selected="chartMode === 'live'"
              >LIVE</button>
            </div>
            <div class="au-chart-legend" v-if="frameConfigs.length > 1">
              <span class="au-legend-item" v-for="f in frameConfigs" :key="f.id">
                <span class="au-legend-dot" :style="{ background: frameHue(f.id), boxShadow: '0 0 6px ' + frameHue(f.id) }"></span> {{ f.name }}
              </span>
            </div>
            <span class="au-chart-count">Last {{ chartLabels.length }} cycles</span>
          </div>
          <div class="au-chart-wrap">
            <Line v-if="chartReady" :data="chartConfig" :options="chartOptions" :plugins="chartPlugins" />
            <div v-else class="au-chart-empty au-shimmer">Acquiring audit telemetry&#8230;</div>
          </div>
        </div>

        <!-- Supply Detail -->
        <div class="au-supply-card card">
          <div class="au-label" style="margin-bottom: 14px;">SUPPLY DETAIL</div>
          <div v-for="frame in frameConfigs" :key="frame.id">
            <div :class="['au-supply-frame-label', frameLabelClass(frame.id)]" v-if="frames.length > 1">{{ frame.name }}</div>
            <div class="au-supply-grid" v-if="latestByFrame[frame.id]">
              <div class="au-supply-row">
                <span class="au-supply-key">Units Issued <span class="au-supply-aux">ledger</span></span>
                <span class="au-supply-val au-mono"><AnimatedNumber :value="latestByFrame[frame.id]!.tokens_issued" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span></span>
              </div>
              <div class="au-supply-row" v-if="tokensDestroyed(frame.id) !== null">
                <span class="au-supply-key">Units Destroyed <span class="au-supply-aux">ledger</span></span>
                <span class="au-supply-val au-mono dim"><AnimatedNumber :value="tokensDestroyed(frame.id)!" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span></span>
              </div>
              <div class="au-supply-row" v-if="trueMinted(frame.id) !== null">
                <span class="au-supply-key">Real Issued <span class="au-supply-truth">since baseline</span></span>
                <span class="au-supply-val au-mono"><AnimatedNumber :value="trueMinted(frame.id)!" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span></span>
              </div>
              <div class="au-supply-row" v-if="trueBurned(frame.id) !== null">
                <span class="au-supply-key">Real Burned <span class="au-supply-truth">since baseline</span></span>
                <span class="au-supply-val au-mono dim"><AnimatedNumber :value="trueBurned(frame.id)!" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span></span>
              </div>
              <div class="au-supply-row" v-if="netPosition(frame.id) !== null && Math.abs(netPosition(frame.id)!) >= 0.01">
                <span class="au-supply-key">+ net escrow &amp; settlement <span class="au-supply-aux">in-transit &middot; &Delta;=0</span></span>
                <span class="au-supply-val au-mono dim">{{ netPosition(frame.id)! >= 0 ? '+' : '' }}<AnimatedNumber :value="netPosition(frame.id)!" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span></span>
              </div>
              <div class="au-supply-row">
                <span class="au-supply-key">&Sigma; Circulating</span>
                <span :class="['au-supply-val', 'au-mono', isBalanced(frame.id) ? 'matched' : 'unmatched']"><AnimatedNumber :value="latestByFrame[frame.id]!.total_circulating" :decimals="2" comma /> <span class="au-unit" :class="{ 'au-unit-alt': (frame.currency || 'AVT') !== 'AVT' }">{{ frame.currency || 'AVT' }}</span><button class="au-supply-info" type="button" @click="explainCirculating(frame.id)" aria-label="Why is circulating different from issued? Open the reconciliation detail" title="Why ≠ issued? — jump to the escrow &amp; settlement reconciliation that explains this number">i</button></span>
              </div>
              <div class="au-supply-row" v-if="agentCount(frame.id) !== null">
                <span class="au-supply-key">Agents</span>
                <span class="au-supply-val au-mono dim">{{ agentCount(frame.id) }}</span>
              </div>
              <div class="au-supply-divider"></div>
              <div class="au-supply-row">
                <span class="au-supply-key">Atomic &#x0394; <span class="au-supply-truth">truth</span></span>
                <span :class="['au-supply-val', 'au-mono', 'au-supply-delta', deltaClass(frame.id)]">{{ atomicDisplay(frame.id) }}</span>
              </div>
              <div class="au-supply-row">
                <span class="au-supply-key">Live-read &#x0394; <span class="au-supply-aux">HTTP</span></span>
                <span :class="['au-supply-val', 'au-mono', isDivergent(frame.id) ? 'unmatched' : 'dim']">{{ liveDeltaFixed(frame.id) }}</span>
              </div>
              <div class="au-supply-row au-supply-spark-row">
                <span class="au-supply-key">&#x0394; trend <span class="au-supply-aux">{{ Math.min(48, (historyByFrame[frame.id] || []).length) }} cyc</span></span>
                <span class="au-supply-spark" v-html="sparkline(frame.id)" :data-testid="'spark-' + frame.id"></span>
              </div>
              <div class="au-supply-row">
                <span class="au-supply-key">Last Check</span>
                <span class="au-supply-val au-mono dim">{{ formatTimeAgo(latestByFrame[frame.id]!.timestamp) }} ({{ latestByFrame[frame.id]!.response_ms }}ms)</span>
              </div>
            </div>
            <div v-else class="au-supply-empty au-shimmer">Awaiting first audit&#8230;</div>
            <div class="au-supply-frame-divider" v-if="frames.length > 1 && frame.id !== frames[frames.length - 1].id"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- FX RESERVE SOLVENCY (I2 — independent reserve-floor + cross-frame pool) -->
    <SolvencyPanel />

    <!-- PER-USER CONSERVATION (I3 — every account's liquid & locked ≥ 0) -->
    <PerUserPanel />

    <!-- SUPPLY COMPOSITION (V4 — where the supply sits + why issued ≠ circulating) -->
    <CompositionPanel />

    <!-- NATIVE SUPPLY (V6 — per-currency conservation on the currency-blind ledger) -->
    <NativeSupplyPanel />

    <!-- HOLDER REGISTER (V5 — AGORA's points; who holds them) -->
    <SharesPanel />

    <!-- STATS ROW -->
    <div class="au-stats-row" v-if="stats">
      <div class="au-stat-card">
        <span class="au-stat-ic" v-html="statIcon('audits')"></span>
        <div class="au-stat-number"><AnimatedNumber :value="stats.total_audits" comma /></div>
        <div class="au-stat-label au-label">TOTAL AUDITS</div>
      </div>
      <div class="au-stat-card accent">
        <span class="au-stat-ic" v-html="statIcon('streak')"></span>
        <div class="au-stat-number ok"><AnimatedNumber :value="stats.consecutive_ok" comma /></div>
        <div class="au-stat-label au-label">CONSECUTIVE OK</div>
      </div>
      <div class="au-stat-card">
        <span class="au-stat-ic" v-html="statIcon('uptime')"></span>
        <div class="au-stat-number">{{ stats.uptime_pct == null ? '—' : stats.uptime_pct + '%' }}</div>
        <div class="au-stat-label au-label">UPTIME</div>
      </div>
      <div class="au-stat-card">
        <span class="au-stat-ic" v-html="statIcon('atomic')"></span>
        <div class="au-stat-number au-mono ok">{{ (stats.max_atomic_delta ?? 0).toFixed(6) }}</div>
        <div class="au-stat-label au-label">MAX ATOMIC &#x0394;</div>
      </div>
      <div class="au-stat-card au-stat-card-info">
        <span class="au-stat-ic" v-html="statIcon('live')"></span>
        <button
          v-if="peakBetaIncident"
          class="au-info-btn"
          @click.stop="showMaxDeltaInfo = !showMaxDeltaInfo"
          :aria-label="'Show historical peak live-read delta details'"
          :aria-expanded="showMaxDeltaInfo"
        >i</button>
        <div class="au-stat-number au-mono">{{ stats.max_delta.toFixed(2) }}</div>
        <div class="au-stat-label au-label">MAX LIVE &#x0394;</div>
        <div v-if="showMaxDeltaInfo && peakBetaIncident" class="au-info-popover" @click.stop>
          <div class="au-info-popover-header">
            <span class="au-info-popover-title">MAX LIVE-READ &#x0394;</span>
            <button class="au-info-popover-close" @click.stop="showMaxDeltaInfo = false" aria-label="Close">✕</button>
          </div>
          <div class="au-info-popover-body">
            <div class="au-info-note">
              <strong class="au-mono">{{ stats.max_delta.toFixed(2) }} AVT</strong> is the all-time peak of the
              <em>live-read</em> &#x0394; — the HTTP supply endpoint reads supply &amp; balances in two separate
              queries, so under cross-frame load it transiently diverges. It is <strong>not</strong> a real
              supply change; the atomic invariant (one DB snapshot) is the source of truth and holds &#x0394;=0.
              The worst <em>real</em> (atomic) breach to date:
            </div>
            <div class="au-info-row">
              <span class="au-info-key">Delta</span>
              <span class="au-info-val au-mono danger">+{{ peakBetaIncident.delta!.toFixed(6) }} AVT</span>
            </div>
            <div class="au-info-row">
              <span class="au-info-key">Date</span>
              <span class="au-info-val au-mono">{{ peakBetaIncident.date }}</span>
            </div>
            <div class="au-info-row">
              <span class="au-info-key">Frame</span>
              <span class="au-info-val">{{ frameName(peakBetaIncident.frame) }}</span>
            </div>
            <div class="au-info-row">
              <span class="au-info-key">Cause</span>
              <span class="au-info-val">{{ peakBetaIncident.cause }}</span>
            </div>
            <div class="au-info-row">
              <span class="au-info-key">Status</span>
              <span class="au-info-val ok">&#x2713; {{ peakBetaIncident.status }} ({{ peakBetaIncident.patch_ref }})</span>
            </div>
            <div class="au-info-popover-footer">
              <a class="au-info-link" @click.stop="openIncidentLog()">View full patch notes &#x2193;</a>
            </div>
          </div>
        </div>
      </div>
      <div class="au-stat-card">
        <span class="au-stat-ic" v-html="statIcon('since')"></span>
        <div class="au-stat-number dim">{{ stats.oldest_audit ? formatDateShort(stats.oldest_audit) : '---' }}</div>
        <div class="au-stat-label au-label">MONITORING SINCE</div>
      </div>
    </div>

    <!-- AUDIT LOG -->
    <div class="au-log-section">
      <div class="au-log-header">
        <span class="au-label">AUDIT LOG</span>
        <span class="au-log-count" v-if="history.length">{{ history.length }} records</span>
      </div>
      <div class="au-log-table-wrap">
        <table class="au-log-table">
          <thead>
            <tr>
              <th>TIME</th>
              <th class="c" v-if="frames.length > 1">FRAME</th>
              <th class="r">ATOMIC &#x0394;</th>
              <th class="r">LIVE-READ &#x0394;</th>
              <th class="c">ST</th>
              <th class="r">MS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in history" :key="row.id + '-' + row.frame" :data-frame="row.frame" :class="['au-log-row', { 'breach-row': rowTruthBreach(row), 'maint-row': row.maintenance, 'alt': idx % 2 === 1, 'au-log-fresh': idx === 0 }]">
              <td class="au-mono dim">{{ formatTime(row.timestamp) }}</td>
              <td class="c" v-if="frames.length > 1">
                <span class="au-frame-badge" :style="{ color: frameHue(row.frame), borderColor: hexToRgba(frameHue(row.frame), 0.4) }">{{ frameLetter(row.frame) }}</span>
              </td>
              <td :class="['au-mono', 'r', rowAtomicClass(row)]">{{ rowAtomicDisplay(row) }}</td>
              <td :class="['au-mono', 'r', 'dim']">{{ row.delta.toFixed(6) }}</td>
              <td class="c">
                <span v-if="rowTruth(row) === 'OK'" class="au-icon-ok">&#x2713;</span>
                <span v-else-if="row.maintenance" class="au-icon-maint" title="Breach during maintenance window (safe / mitigated)">&#9888;</span>
                <span v-else-if="rowTruth(row) === 'BREACH'" class="au-icon-breach">&#x2717;</span>
                <span v-else class="au-icon-warn">!</span>
              </td>
              <td :class="['au-mono', 'r', latencyClass(row.response_ms)]">{{ row.response_ms }}</td>
            </tr>
            <tr v-if="!history.length">
              <td :colspan="frames.length > 1 ? 6 : 5" class="au-log-empty">Waiting for first audit...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- PATCH NOTES & INCIDENT LOG (collapsible) -->
    <div class="au-incidents-section" v-if="patchNotes.length > 0">
      <button
        class="au-incidents-toggle"
        @click="showIncidentLog = !showIncidentLog"
        :aria-expanded="showIncidentLog"
      >
        <span class="au-incidents-chevron">{{ showIncidentLog ? '&#x25BE;' : '&#x25B8;' }}</span>
        <span class="au-label">PATCH NOTES &amp; INCIDENT LOG</span>
        <span class="au-incidents-count">{{ patchNotes.length }} {{ patchNotes.length === 1 ? 'entry' : 'entries' }}</span>
        <span class="au-incidents-note">resolved breaches &amp; auditor changelog</span>
      </button>
      <div v-if="showIncidentLog" class="au-incidents-body">
        <div
          v-for="note in patchNotes"
          :key="note.id"
          :class="['au-incident-card', 'kind-' + note.kind]"
        >
          <div class="au-incident-meta">
            <span class="au-incident-date au-mono">{{ note.date }}</span>
            <span :class="['au-frame-badge', frameBadgeClass(note.frame)]">{{ frameBadgeLabel(note.frame) }}</span>
            <span v-if="note.delta !== null" class="au-incident-delta au-mono danger">+{{ note.delta!.toFixed(6) }} AVT</span>
            <span :class="['au-incident-status', 'au-mono', statusToneClass(note)]">{{ statusGlyph(note) }} {{ note.status }}</span>
            <span class="au-incident-ref au-mono dim">{{ note.patch_ref }}</span>
          </div>
          <div class="au-incident-title">{{ note.title }}</div>
          <div class="au-incident-cause">
            <span class="au-incident-cause-key">{{ note.kind === 'upgrade' ? 'Change:' : 'Cause:' }}</span> {{ note.cause }}
          </div>
          <div class="au-incident-desc">{{ note.description }}</div>
        </div>
      </div>
    </div>

    <!-- FOOTER -->
    <footer class="au-footer">
      <span class="au-footer-glyph">&#x25C8;</span>
      <span>The Auditor v{{ auditorVersion }}</span>
      <span class="au-footer-sep"></span>
      <span>Atomic Invariant Verification</span>
      <span class="au-footer-sep"></span>
      <span>Zero Tolerance</span>
      <span class="au-footer-sep"></span>
      <span>{{ frames.length }} Sovereign Frame{{ frames.length !== 1 ? 's' : '' }}</span>
      <span class="au-footer-sep"></span>
      <span v-if="lastVerified">Verified {{ formatTimeAgo(lastVerified) }}</span>
      <span v-else>Polling every {{ auditInterval }}s</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
  Legend,
} from 'chart.js'
import { useAuditorStore } from '@/stores/auditorStore'
import { useWsStore } from '@/stores/wsStore'
import { storeToRefs } from 'pinia'
import type { AuditResult } from '@/types/auditor'
import AnimatedNumber from '@/components/AnimatedNumber.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'
import FrameVerdictBand from '@/components/FrameVerdictBand.vue'
import AttestationSeal from '@/components/AttestationSeal.vue'
import TpsaBadge from '@/components/TpsaBadge.vue'
import SolvencyPanel from '@/components/SolvencyPanel.vue'
import PerUserPanel from '@/components/PerUserPanel.vue'
import CompositionPanel from '@/components/CompositionPanel.vue'
import NativeSupplyPanel from '@/components/NativeSupplyPanel.vue'
import SharesPanel from '@/components/SharesPanel.vue'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler, Legend)

const auditorStore = useAuditorStore()
const wsStore = useWsStore()
const { latestByFrame, history, stats, frames, maintenance, mode, availableModes } = storeToRefs(auditorStore)

// Tier button label. A MAP, not a ternary: with three tiers a two-way ternary
// silently labels every unknown tier 'PROD', which is the one mistake that must
// never happen here (a legacy ledger reading as production).
const MODE_LABELS: Record<string, string> = { prod: 'PROD', sandbox: 'SANDBOX', legacy: 'LEGACY' }
function modeLabel(m: string): string {
  return MODE_LABELS[m] || m.toUpperCase()
}
const { connected: wsConnected } = storeToRefs(wsStore)

const auditorVersion = '2.3'
const auditInterval = 60

// "i" on Σ Circulating → jump to that frame's Circulating-Supply card and open its
// reconciliation detail (the escrow & settlement breakdown that explains issued vs circulating).
function explainCirculating(frameId: string) {
  const el = document.getElementById('comp-' + frameId)
  if (el) {
    const det = el.querySelector('details.au-comp-recon') as HTMLDetailsElement | null
    if (det) det.open = true
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el.classList.remove('au-comp-flash')
    void el.offsetWidth // restart the flash animation
    el.classList.add('au-comp-flash')
  } else {
    document.querySelector('.au-comp')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// Live UTC clock (mission-control header)
const clock = ref('--:--:--')
let clockTimer: ReturnType<typeof setInterval> | null = null
function tickClock() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  clock.value = `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
}

// ── Patch notes & incident log ─────────────────────────────────────────────
// Manually curated changelog: resolved breaches during beta + auditor upgrades.
// Newest FIRST. Adding entries surfaces them here + on the MAX-DELTA popover.
interface PatchNote {
  id: string
  date: string
  // §LEGACYTIER 2026-09-09: 'all' plus every live frame id. The union used to name only
  // frame-a/b/c, and both badge helpers fell through, so an EU entry rendered as FLEET.
  frame: 'frame-a' | 'frame-b' | 'frame-c' | 'eu' | 'asia' | 'all'
  delta: number | null
  title: string
  cause: string
  status: string
  kind: 'incident' | 'upgrade' | 'maintenance'
  patch_ref: string
  description: string
}

const patchNotes: PatchNote[] = [
  {
    id: 'euasia-auditor-wiring-2026-09-09',
    date: '2026-09-09',
    frame: 'all',
    delta: null,
    title: 'Two of the five checks on EU and ASIA were answering about nothing, and the holder register could not see five AGORA listings',
    cause: 'The two live production frames reach this auditor through a JSON list that carried only their EventStore address and key. Without a TEG connection the cross-store locked check cannot run, without a registry connection the holder register has nothing to read, and the transit zero-point they inherited belonged to a pair of frames that no longer exists',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'EUASIA-WIRING \u00b7 2026-09-09',
    description: 'Three separate complaints on the production band turned out to be one missing line of configuration. EU and ASIA are wired into this auditor through a list of extra frames, and that list gave them an EventStore address, an EventStore key and a currency. It did not give them a TEG connection, a registry connection, or the identity of their FX router. Everything that depends on those three was therefore either silent or wrong, and had been since the cluster was built.\n\n"Do the two ledgers agree on what is locked?" read "not checked", which was the honest answer. That check is the only assertion on this page that spans two stores: it compares the EventStore projection\'s locked balance against the TEG\'s locked balance, per account, across the union of both sides. It exists precisely because the supply invariant cannot see this class of fault. Delta compares the EventStore against itself, so a locked balance that is deleted from one store and not the other keeps Delta at zero while the books diverge. That is not hypothetical: it is how a reconciliation once removed most of a frame\'s locked units without raising anything. On the live cluster the check had never run once. It runs now on both frames and returns OK, with one caveat stated plainly rather than buried: both totals are currently zero, because nothing is locked on either frame yet. The check is wired and will bite when locked units exist. It is not yet evidence that anything is right.\n\n"Is cross-frame value settling?" read plus 100,000.00 ACU above baseline on ASIA and plus 50,000.00 ECU on EU, described as residue accumulated. Both frames actually hold exactly zero in transit. The drift was entirely in the baseline, which was negative, and which was set automatically on 6 September at 06:26 and 06:28. Those timestamps belong to the rehearsal pair that was torn down and rebuilt from zero on 7 September. The rebuild reused the frame identifiers, so the persisted monitoring zero-point outlived the ledger it described and kept measuring a frame that no longer exists. Both were re-baselined to the current truthful value through the standing admin rail, which never touches the ledger and which writes a signed attestation carrying the old baseline, the old drift and the stated reason into each frame\'s chain. Those are attestations 81186 and 81187. The general lesson is on the record with them: a monitoring baseline keyed on a frame identifier alone survives the frame, and an identifier can be reused.\n\nThe AGORA listings were the same missing line. Five listings exist and trade, three on EU and two on ASIA, and the holder register panel had no connection to the registry database that holds them, so it showed nothing at all. With the connection in place both frames read their cap tables on the first cycle.\n\nOne further defect was found while writing this entry rather than by any instrument. The frame badge on these notes was chosen by a chain of comparisons that ended in a default of FLEET, so an entry about EU or ASIA would have been labelled as fleet-wide, quietly and forever. It is a lookup now, and an identifier it does not know prints itself instead of claiming to be everything.',
  },
  {
    id: 'legacy-tier-2026-09-09',
    date: '2026-09-09',
    frame: 'all',
    delta: null,
    title: 'A third tier: the retiring frames moved out of production, and the signature strip stopped naming the wrong ledgers',
    cause: 'Production meant the EU and ASIA cluster, but the three retiring frames were still filed under it, and the attestation strip was pinned to a list of frames written when those three were production',
    status: 'LIVE',
    kind: 'upgrade',
    patch_ref: 'LEGACYTIER \u00b7 2026-09-09',
    description: 'The environment switch above now offers three tiers rather than two. Production is the live EU and ASIA cluster. Legacy is the retiring stack, reachable and deliberately throttled, with its operators turned off. Sandbox is unchanged. The three retiring frames simply moved out of the production tier; nothing about them was altered.\n\nThe part worth writing down is what nearly went wrong. Attestation signing was gated on the literal word production in four places. Moving the retiring frames to their own tier would have silently ended three signed hash chains that carry real history, with no error and no empty result to notice. Those frames are retiring, not fictional, and their chains are the record of what they held. Signing is now gated on a named set of tiers that includes both production and legacy, so all five attested frames signed in the same cycle after the change, and the strip under the verdict band proves it in the reader\'s browser as it always did.\n\nThat strip had a fault of its own, and a screenshot found it rather than a test. It verified a hardcoded list of three frames, which was correct on the day it was written and stopped being correct when EU and ASIA became production. Under the production toggle it was showing the retiring frames\' chips and sequence numbers: the right cryptography performed against the wrong ledgers. It now derives the frames to verify from whichever tier is on screen, and re-verifies when the tier changes. Its summary had a second, quieter fault: it asked whether every result was good, and every result over an empty list is good, so a run that verified nothing would have reported a green seal. Verifying nothing now reports pending, which is what it is.',
  },
  {
    id: 'transitbase-b-2026-08-22',
    date: '2026-08-22',
    frame: 'frame-b',
    delta: null,
    title: 'The settling check read "+1,655.03 vs baseline" on Frame B: traced to the cent, re-baselined through the rail, and the check learned to speak',
    cause: 'A frozen in-transit residue accumulated against the 14 August baseline, almost all of it in one hot day, and the check reported it as a bare number with no direction, no unit and no meaning',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'TRANSITBASE-B \u00b7 2026-08-22',
    description: 'The verdict band\'s "Is cross-frame value settling?" showed 1,655.03 vs baseline on Frame B and nothing else. That number was read by a person who could not tell from it whether money was in trouble, which is a failure of the sentence before it is anything else: no direction, no currency, no hint of whether anyone is paged. For the record up front: the supply invariant held at zero throughout, because value mid-flight between frames is supply-neutral by construction.\n\nThe trace reconciles to the cent. Grouping every transit-classified ledger leg by day since the baseline was set on 14 August, the day sums add to +1,655.04 against the observed drift of +1,655.03. The residue formed almost entirely on 18 August, the hot day after the host reboot, at +1,689.17, and partially returned afterwards: -377.46 on the 19th, +407.10 on the 20th, -89.01 on the 21st. Every clean day before and after nets to fractions of a cent, locks and mirrors against releases, and the control query for unclassified legs since the baseline returned zero rows. Then the value froze: fourteen straight hours at exactly +1,655.03 while the simulator kept trading through the rail. A frozen, explained, delta-neutral residue is exactly what the baseline mechanism exists for, so the monitoring zero-point was moved to the current truthful value through the standing admin rail, the ledger itself untouched, the same treatment Frame C received on 17 August.\n\nThe rail was made better before it was used. Until today a transit re-baseline was a silent metadata write; it now emits a signed TPSA-1 attestation into the frame\'s chain carrying the old baseline, the old drift and the stated reason, exactly as the native-supply rail already did. This move is attestation #110 on Frame B\'s chain: the zero-point change has a chain of custody, and the number this entry is about sits on the permanent record with a signature over it.\n\nTwo more things surfaced while standing in that corner. The check\'s answer now states direction, currency and meaning: above baseline means residue accumulated and is watched; below baseline past the threshold means escrow locking without releasing, which is the direction that pages. And the by-kind breakdown beneath it had quietly been showing a single catch-all line because its refresh had died on every attempt with an exception whose printed text is empty, a TimeoutError hidden by logging the message instead of the repr: the full-history breakdown measurably takes 56 to 126 seconds per frame against a connection budget of 15. The failure is logged properly now, the query is granted the time it was measured to need on a six-hour cadence, and the breakdown is whole again. The books were never wrong; the sentence, the silence and the timeout were.',
  },
  {
    id: 'tpsa1-signed-attestations-2026-08-22',
    date: '2026-08-22',
    frame: 'all',
    delta: null,
    title: 'TPSA-1: every verdict is now a signed, hash-chained attestation you can verify in your own browser',
    cause: 'Trusting a verdict on this page meant trusting the server that rendered it. A verdict worth the name should survive on its own: portable, signed, and checkable by a stranger with no access to this host',
    status: 'LIVE',
    kind: 'upgrade',
    patch_ref: 'TPSA-1 \u00b7 auditor v2.4.0',
    description: 'Each audit cycle on each production frame now emits an attestation: a canonical JSON document carrying the invariant terms, the verdict, its own coverage limits and the digest of the previous attestation for that frame, signed with Ed25519. The signed bytes are stored verbatim and served at /api/auditor/attestations; the verification key lives at /.well-known/auditor-jwks.json. Checking one needs nothing from this host beyond those two responses: recompute the SHA-256 of the payload, verify the signature over exactly those bytes, and follow prev_hash backwards. Rewriting any stored verdict breaks every link after it, visibly.\n\nEvery attestation is also pinned into the event stream: it carries as_of_event_seq, the highest event sequence number, fetched in the same single SQL statement as the terms themselves, so one database snapshot covers both the numbers and the position in history they were observed at.\n\nThe TPSA-1 strip under the verdict band runs the verification in the reader\'s own browser with WebCrypto: digest, signature, chain link. They are the same checks the reference conformance script performs; the browser is a convenience, not the authority.\n\nThe limits are stated rather than implied. The terms are read from projection state, so a later verifier can verify the document forever and reproduce the method live, but cannot refold history at a past sequence number; per-event folding is the next version of the standard. Baseline changes now travel an admin rail that writes a signed provenance attestation into the same chain, so the write-down baseline this page leans on has a chain of custody rather than just a file. And chain heads are published daily to subscribers, whose devices retain what this host could no longer rewrite after a compromise.\n\nAll of it was proven the day it shipped: the conformance checks pass on all three frames, including an independent recompute of the invariant reading exactly zero, and the chain was demonstrated to link across a container restart rather than break. A restart is a gap in time, never a break in the chain.',
  },
  {
    id: 'sqlite-wal-cycle-lock-2026-08-22',
    date: '2026-08-22',
    frame: 'all',
    delta: null,
    title: 'One audit cycle on all three frames died of a database lock, and the first explanation written down was wrong',
    cause: 'The metrics scan held a shared SQLite lock past the writers\' five-second patience in rollback-journal mode; one full cycle failed with "database is locked" and one public read returned a 500',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'GLOBALSTD-WAL \u00b7 2026-08-22',
    description: 'At 02:15 UTC on 22 August one complete audit cycle failed on frames A, B and C simultaneously with "database is locked", and one public API read caught a 500 from the same lock. The invariant went unwatched for roughly three minutes. The books were never at risk; the watcher blinked.\n\nThe first explanation was wrong, and is corrected here rather than quietly. The 176-second gap between cycles was initially attributed to a container-restart artifact, because the previous restart had shown a similar bump and the pattern matched. Reading the logs instead of the pattern found three gather exceptions, one per frame, at the same second.\n\nThe mechanism was in this auditor\'s own storage. Its history is a 3.27 GB SQLite file, and every thirty seconds the metrics endpoint scans 733 thousand audit rows for totals. In rollback-journal mode a reader holds a shared lock, a writer needs an exclusive one, and the writers give up after five seconds. The scan had always been there; the day\'s new writers, the attestation chain, raised the collision odds until it finally fired.\n\nThe fix is structural rather than a retry: the database now runs in WAL mode, where readers and writers do not block each other, with durability unchanged. Zero lock errors since, verified across a restart. The same day added the alarm this class deserves, because the auditor\'s HTTP server can be perfectly healthy while its audit loop is wedged: a gauge now tracks seconds since the last completed cycle and pages at five minutes. A watchdog nobody watches is not a standard.',
  },
  {
    id: 'native-recon-display-honesty-2026-08-22',
    date: '2026-08-22',
    frame: 'all',
    delta: null,
    title: 'The page contradicted its own backend: invented billion-unit "gaps" on A and B, and "conserved" beside -155.2M on C',
    cause: 'The backend published recon_basis and a rebased gap and marked the raw figure unverifiable; the dashboard rendered the raw figure anyway and never read the fields that explained it',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'GLOBALSTD-P0 \u00b7 2026-08-22',
    description: 'What readers saw: frame A appeared to carry a 1.42 billion AVT issuance gap, frame B 1.15 billion JDAY, and frame C said "conserved" directly beside -155,224,720. All three were display artifacts. The backend had it right the whole time: for A and B it set native_supply_ok to null with recon_basis pre_baseline_genesis, meaning issuance predates the re-derivation window and the raw subtraction is an artifact of an incomplete record, not a finding. For C it published a rebased gap of exactly 0.00 against the documented 12 August write-down baseline. The page read none of those fields and printed the raw number the backend had explicitly marked meaningless.\n\nNow frames A and B state plainly that the total is not re-derivable and why, with no number pretending otherwise; frame C shows the rebased gap beside its baseline date; and every card names the basis its verdict rests on. The part that mattered most is the breach path: it now uses the rebased figure, so a real future un-evented destruction on frame C would announce itself as itself instead of arriving pre-buried inside 155.22 million of explained history.\n\nSame pass, same class, this very panel: three of the entries below were labelled FLEET in frame A colours because the type union behind the frame badge never learned frame C existed, and nothing type-checked the build. The union is fixed and the build now runs the type checker, proven by running it against the old code first and watching it fail in four places. No money was wrong anywhere in this entry. The page was.',
  },
  {
    id: 'audit-interval-1h-2026-08-20',
    date: '2026-08-20',
    frame: 'all',
    delta: null,
    title: 'Audit interval was raised to 1 hour, measured, and put back to 60 seconds the same day',
    cause: 'The host was under sustained memory pressure and the once-a-minute audit was a reasonable suspect; measuring it on both sides of the change showed it was not the cause',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'AUDITINTERVAL \u00b7 2026-08-20',
    description: 'For part of one afternoon this auditor ran once an hour instead of once a minute, and then it was put back. The entry is kept because the measurement is more useful than the change was.\n\nThe host was under sustained memory pressure, with roughly 86 GB in swap and load peaking near 100, and the once-a-minute audit was a reasonable suspect: it re-reads three sovereign ledgers on every pass and the three EventStore databases hold about 36 GB of working set between them. So the interval was raised to 3600 seconds and the cost was measured on both sides of the change rather than argued about.\n\nAcross matched 150-second windows the three EventStore databases moved from 3.02 cores to 2.59. That looks like a saving until you notice the windows were not comparable: the box was already calming down, from load 59 to 39 during the first and 42 to 29 during the second, so an unknown part of that 0.43 belongs to the box rather than to this change. The number that was clean is the auditor’s own: 0.16 cores before, 0.17 after. The audit cycle was cut sixtyfold and the process that runs it did not get cheaper by any measurable amount, because its CPU is spent serving this dashboard and its websocket, not on auditing. Whatever the audit pass costs, it is smaller than the noise floor of a busy host.\n\nThe real load was elsewhere and was never a poller. A census of every container put the weight on the core spine, led by one EventStore database at 1.98 cores, a registry database at 1.44 and a TEG at 1.31, with the top eighteen containers together accounting for roughly 13 of 24 cores and no single dominant consumer. The binding constraint was memory rather than CPU: with that much in swap the kernel’s own paging was inflating the load figure, and no amount of polling less often addresses that.\n\nSo the interval is back to 60 seconds. The cost of leaving it at an hour would have been up to an hour of delay before a supply breach was named here, and the measured saving did not come close to justifying that trade. Recorded rather than quietly reversed, because a hypothesis that was tested and rejected is worth as much as one that was confirmed, and the next person to suspect this auditor should be able to read the numbers instead of repeating the experiment.',
  },
  {
    id: 'transit-drift-stresstest-2026-08-17',
    date: '2026-08-17',
    frame: 'frame-c',
    delta: null,
    title: 'A 1,212.78 BVT transit stranding from one stress-test window, traced leg by leg and re-baselined',
    cause: 'During a deliberately hot simulator run, a handful of cross-TEG mirror legs (the receiver-credit reflections) arrived short or not at all, leaving the paired locks and releases without their exact counterweight',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'TRANSITBASE-C · 2026-08-17',
    description: 'The settling panel on this frame read -1,212.78 against its baseline and crossed into STRANDING, which alerts below -1,000. The trace was short and exact. Grouping every one-sided ledger leg by day showed the cross-TEG triple (escrow lock, receiver mirror, escrow release) netting to precisely 0.0000 on the 14th, 15th and 16th, and to exactly -1,212.78 on the 17th, all of it inside two hours that coincide with a stress test deliberately run at several times the usual concurrency. Within that window the locks and releases still pair perfectly, 537 against 537, release equal to twice the lock to the cent. The shortfall sits entirely in the mirror legs, the reflections of receiver credits on operator ledgers, which sum 1,212.78 short of their locks. The operator ledgers themselves were credited correctly, the account-for-account census reads exact, and the supply invariant held at zero throughout, so no unit is missing anywhere; what went missing was a small number of reflections, not the light. The residue then froze: three hours of quiet and a second, calmer simulator session added nothing to it. A frozen, explained, delta-neutral residue is exactly what the transit baseline mechanism exists for, so the monitoring zero-point was moved to the current truthful value using the standing re-baseline rail, the ledger itself untouched. Drift measurement restarts at zero and the next stranding, should one form, will be visible against a clean line rather than buried under an explained one.',
  },
  {
    id: 'native-supply-rebaseline-2026-08-17',
    date: '2026-08-17',
    frame: 'frame-c',
    delta: null,
    title: 'The flickering -155M issuance gap: the check was double-counting its own federation adjustment. Rebaselined at a verified quiet moment; no unit was ever missing',
    cause: 'The native-supply check added the cloud-op TEGs’ full balance levels on top of a projection that already tracks their deltas, so its verdict moved with every simulator flow between mainframe and operators and crossed the tolerance line at random',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'NATIVEBASE · 2026-08-17',
    description: 'For days this frame’s panel would sometimes ask "was every unit actually issued?" and show a gap of -155,224,720 BVT, and sometimes show nothing. Both readings were wrong in an instructive way, because two separate facts had been entangled into one number. The first fact is real and stands: the raw gap of -155.22M is a frozen constant, unchanged to the cent between every reading taken this week. It is the reconciliation of 12 August, which wrote down phantom projection balances (the leftover rows of purged agents, and the projection levels of operator-homed agents) and booked them as tokens_destroyed. No burn events stand behind that figure because nothing was burned; the units written down either never truly existed or continue to exist on the operator ledgers. That is documented history, not missing money. The second fact is the defect: the check tried to explain the gap by adding the operator TEGs’ full balance levels, published every ten minutes, on top of a projection that already applies operator deltas through the balance outbox. Measured on the night of the diagnosis, 88.2M of operator-agent rows sit in this frame’s projection. Adding levels on top of deltas double-counts every unit moved since the write-down, so the "reconciled" residual silently tracked the simulator’s net operator holdings and wandered back and forth across the tolerance line. That was the flicker. The confirming fingerprint: funding operator agents with 7.0M that evening moved the residual by exactly 6.9M, which is what a double-count does and what missing money does not do. The fix follows the same pattern the transit ledger already uses. The raw gap is now reconciled against a frozen per-frame baseline captured at a verified quiet moment, with the simulator stopped and the daily account-for-account census reading exactly zero at rest. At the moment of capture the rebased gap reads exactly 0.00. The federation figure remains on the payload as a diagnostic but no longer votes on the verdict. From here, any new destruction without an event behind it moves the rebased gap and keeps it moved: a trend rather than a flicker, which is the only alarm shape worth having. Throughout all of it the supply invariant held at zero, live and atomic, and per-user conservation, the locked-units guard and reserve solvency stayed green. This was a check arguing with its own correction term. The books were never wrong.',
  },
  {
    id: 'native-supply-610-2026-08-01',
    date: '2026-08-01',
    frame: 'frame-c',
    delta: null,
    title: 'Frame C native issuance reconciled: the 610 BVT was an accounting offset, not missing money',
    cause: 'A reconciliation on 28 July anchored this frame’s issuance counters on a balance total that was itself understated, by exactly the locked balance that same pass had wrongly removed',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'NATIVEFIX · 2026-08-01',
    description: 'Frame C reported its circulating supply exceeding its re-derived issuance total by 610 BVT. That figure has now been traced to its origin and corrected, and the finding was narrower than it first appeared: no balance was ever wrong and no unit was ever unaccounted for. The 610 was an offset inside two bookkeeping counters, and it was put there by a reconciliation run on 28 July. That pass set this frame’s issuance counter equal to the sum of all balances at that moment, but the same pass had just removed 610 units of locked balance in error, so the counter was anchored to a total that was short by exactly that amount. The reconciliation then read as perfectly balanced, which is why nothing flagged it at the time. When the locked balance was restored on 1 August the balances became correct again, the issuance counter rose with them to keep the supply invariant at zero, and the difference against the issuance history recorded on the immutable log finally became visible as 610. Three independent facts establish that this was never missing money. The locked balance is fully backed: every lock on this frame moves value from liquid to locked within a single account and nets to zero, so a lock creates nothing and requires no issuance behind it. The issuance history is complete: twelve typed issuance events on the log account for the entire native supply of this frame, whose genesis is later than the verification baseline. And the two ledgers agree exactly: the TEG ledger and the projection report the same locked total across the same seven accounts, to the cent. The correction re-anchored the issuance counters on the immutable log rather than on a balance total, in a single atomic statement whose arithmetic keeps the supply invariant at zero by construction rather than by assertion. Issuance is now stated as exactly what the log records was issued, burns as exactly what the log records was burned, and the remainder of what sits on the books is stated as cross-frame value in transit. The supply invariant held at zero before, during and after. Because a number that has been made to read zero is worthless if it can no longer read anything else, the check was then deliberately driven to fail: one account had its projected balance raised by 999 units with no corresponding issuance event, the native check opened to exactly 999 while the supply invariant stayed at zero throughout, and the value was restored and the check returned to zero. That is the whole point of this particular assertion. The supply invariant is structurally blind to a balance appearing without an issuance behind it, and this check is the one that sees it.',
  },
  {
    id: 'teg-es-staked-guard-2026-08-01',
    date: '2026-08-01',
    frame: 'all',
    delta: null,
    title: 'New cross-store guard: the two ledgers are now compared directly, because the supply invariant structurally cannot',
    cause: 'Nothing in the system compared TEG against the EventStore. The supply invariant compares the EventStore against itself, so a projection that disagrees with the ledger it mirrors was invisible to it',
    status: 'LIVE',
    kind: 'upgrade',
    patch_ref: 'AUDITFIX \u00b7 2026-08-01',
    description: 'The locked-balance incident earlier today ran undetected for four days, and the reason is worth stating plainly: there was no check that compared the two stores. \u0394 = 0 verifies that the EventStore is internally consistent, and it does that job perfectly, but supply_summary had been set from the very projection table that was wrong, so the invariant was comparing a number against itself. A projection that disagrees with the ledger it mirrors sat outside every check we had. That gap is now closed. A new assertion runs on every audit cycle and compares TEG locked_balance against the projection staked_balance for every account, across the union of both sides, so a locked balance present on only one side is caught in either direction. It is read-only against both stores. Its tolerance is deliberately loose, the greater of five units or a tenth of a percent, because payouts on locked units compound continuously in TEG while the projection is event-driven and a small live lag is normal and must not cry wolf. Severity scales with how much of the locked balance is in dispute: a few units of lag reports as a mismatch, while a tenth or more of the total reports as a breach. The failure it was built for removed 99.85 percent of all locked units, so it would have been unmissable. When either store is unreachable the check reports as not run rather than as passing, because a check that did not run is not a check that passed. It was verified with a negative control rather than by observing it agree: one account on frame-c had its projected locked balance deliberately moved by 999 units, the guard raised a breach naming that exact account within one cycle, and the value was then restored and the guard returned to OK, with the supply invariant untouched at zero throughout. A guard that has only ever been seen saying OK is indistinguishable from a guard that cannot say anything else, which is precisely the failure being corrected here. This guard also surfaced a second finding on frame-c, a 610 BVT difference between circulating supply and re-derived issuance, which was held visible here rather than papered over. It has since been traced and resolved, and the first reading of it recorded here was wrong: it was not balance without an issuance behind it, it was an offset inside two bookkeeping counters. See the entry above for the full account.',
  },
  {
    id: 'staked-projection-recon-2026-08-01',
    date: '2026-08-01',
    frame: 'all',
    delta: null,
    title: 'Locked balances were deleted from the public projection by our own reconciliation, and restored. No unit moved; payouts were never affected',
    cause: 'The 2026-07-28 reconciliation compared EventStore liquid+locked against the TEG liquid column alone. Locked units live in a separate TEG column, so every account with locked units looked like an excess and was written down',
    status: 'RESOLVED',
    kind: 'incident',
    patch_ref: 'STAKEFIX · 2026-08-01',
    description: 'On 2026-07-28 we reconciled the EventStore projection against the TEG ledger. That reconciliation summed the projection’s liquid and locked columns together and compared the result against a single TEG column, token_balance. TEG holds locked value in a second column, locked_balance, which the comparison never read. Every account with an open lock therefore appeared to hold more in the projection than in the ledger, by exactly the size of its locked units, and the reconciliation resolved that apparent excess by writing the projection down. The locked column was emptied. On frame-a that removed 1,881,514 AVT of locked units from the projection, on frame-b 673 JDAY and on frame-c 610 BVT. The signal that made it findable came from a user, not from us: the network-wide locked figure on the dashboard read 2,822 while a single operator’s own locked figure read over 1.8 million. A subset cannot exceed the whole, so the network figure had to be the wrong one. No unit was created, destroyed or moved. TEG is authoritative for balances and was never written to, and every account’s liquid figure matched TEG to the cent throughout, which is the fingerprint of a wrong-column comparison rather than lost value. Payouts on locked units are computed from a different store again, the registry cache, which also matched TEG exactly, so the nightly distributions were correct: the run on 2026-08-01 paid 603.84 to 11 accounts on their full locked units. Had the payout used the corrupted figure it would have paid 0.90. The invariant did not catch this and structurally could not. The 2026-07-28 operation set supply_summary from the same projection table, so Δ = 0 was comparing the EventStore against itself; a locked column that disagrees with TEG is invisible to that check. There is no cross-store assertion between TEG and the EventStore today, and building one is the first follow-up. The repair re-derived the locked balance from TEG on all three frames using the supported projection resync, which rewrites only the projection and holds no TEG connection. Frame-c was done first as a canary, then frame-b, then frame-a, each verified before the next. All three now read TEG == EventStore with a gap of 0.00, zero negative balances, and Δ = 0. Frame-b additionally carried an impossible negative locked balance of -0.83 on the FX gateway account, which the TEG-driven sweep skipped because TEG held no locked units there to sync toward; it needed an explicit second pass, and a reconciliation driven from one side only ever fixes what that side knows about. One consequence is stated here rather than smoothed over: restoring the locked balance on frame-c has made native issuance fail to reconcile by exactly 610 BVT. Those units exist on the ledger and in TEG, but no typed issuance event stands behind them, consistent with the development-era direct writes described in the 2026-07-28 note. Deleting the locked balance had been hiding that gap. It is now visible on this page and under investigation, which is the correct state for it to be in. Transit baselines on all three frames were re-set at this verified-clean moment.',
  },
  {
    id: 'transit-net-rebaseline-2026-07-28',
    date: '2026-07-28',
    frame: 'all',
    delta: null,
    title: 'Legacy stranded transit_net cleared: held visible for diagnosis, then reconciled to ledger truth and re-baselined to zero',
    cause: 'Escrow-development-era defects (June 2026) wrote one-sided balance legs, which classify as supply-neutral and so accumulated in transit_net instead of issued or destroyed',
    status: 'LIVE',
    kind: 'maintenance',
    patch_ref: 'PRISTINE · 2026-07-28',
    description: 'While the AGORA escrow system was still being built in June 2026, defects in the cross-TEG escrow path emitted one-sided balance legs. Those legs are supply-neutral by classification, so they accumulated in transit_net rather than in issued or destroyed, and the per-frame invariant held at Δ = 0 the entire time. No unit was ever created or lost. What was visible on this dashboard was a large standing transit_net per frame: frame-b at -1,277,510 JDAY, frame-c at +1,167,194 BVT, frame-a at -49,761 AVT. Nearly all of it formed on a single day, 2026-06-17, across roughly 61,000 legs through the FX gateway, and then stopped moving, drifting only about 120 per day afterwards. That signature, large and then frozen, is what identified it as an artifact rather than live economic flow. We deliberately left it in place rather than clearing it. A standing anomaly that no longer changes is the cheapest evidence available, and zeroing it early would have destroyed the trail before the cause was understood. It stayed on this page as a known, bounded, Δ-neutral artifact while the underlying escrow idempotency defects were traced and fixed. Once the cause was closed, we reconciled and re-baselined. The EventStore projection was resynced to TEG truth across 489 accounts (frame-a 239, frame-b 237, frame-c 13), removing 2,385,478 of projection-over-ledger drift with the same development-era origin: round-numbered direct writes that appear in neither the immutable event log nor the TEG balance journal, so they were never transactions. The resync rewrites only the projection and never the TEG, so no spendable balance changed. supply_summary was then re-attributed so tokens_issued equals circulating with tokens_destroyed and transit_net at zero, an operation that is Δ-neutral by construction because it adds to one side of the identity exactly what it removes from the other. The auditor transit baselines were reset to match. All three frames now read issued == circulating, destroyed = 0, transit_net = 0, Δ = 0, confirmed across consecutive independent audit cycles. transit_net will accumulate again from zero as genuine cross-frame trade happens. That is expected and is not a regression. A new baseline-independent check now flags any single-day step above 250,000, which the previous drift-based check structurally could not do, because its baseline had been captured two days after the original event and had absorbed it.',
  },
  {
    id: 'a2-true-mint-burn-2026-05-30',
    date: '2026-05-30',
    frame: 'all',
    delta: null,
    title: 'Real issuance/burn surfaced — "units destroyed" is transfer-leg accounting, not burns',
    cause: 'Post-cutover, supply_summary issued/destroyed accumulate per-transaction net, folding in cross-frame / cross-TEG transfer legs',
    status: 'LIVE',
    kind: 'upgrade',
    patch_ref: 'A2 · 2026-05-30',
    description: 'The supply_summary tokens_issued / tokens_destroyed counters are the positive / negative per-transaction net ACCUMULATORS that keep the projection atomic invariant at Δ = 0 — they are not real issuance or burn. Since the single-writer cutover, a transfer whose debit and credit settle in separate Postgres transactions (cross-frame, cross-TEG, A2A-settle, split lock) arrives as two single-sided LedgerBalanceChanged events: the debit half is booked as "destroyed", the credit half as "issued". So ordinary transfer volume inflates both — which is why "units destroyed" keeps climbing even though nothing is being burned. The atomic invariant (issued − destroyed = Σ circulating) holds at exactly 0 throughout, proving no units are lost or created. The Auditor now also reads the typed supply events on the immutable log (TokensIssued, DisputeCompensationMinted, DisputeSlash, BalanceCorrected) since the balance-integrity baseline and reports the REAL issued / burned — currently real burned = 0 on both frames. A structural projection fix (kind-segregated counters) follows next so the raw counters carry the right labels themselves.',
  },
  {
    id: 'auditor-v2.1-atomic-2026-05-29',
    date: '2026-05-29',
    frame: 'all',
    delta: null,
    title: 'Auditor v2.1 — independent atomic invariant verification',
    cause: 'Non-atomic HTTP read-skew surfaced phantom deltas during CQRS cutover',
    status: 'LIVE',
    kind: 'upgrade',
    patch_ref: 'auditor v2.1',
    description: 'The auditor now verifies the supply invariant by reading each frame\'s EventStore Postgres directly and computing issued − destroyed − Σ(liquid+locked) in ONE SQL statement (a single MVCC snapshot). This is immune to the read-skew in the HTTP /supply-audit endpoint, which reads supply_summary and materialized_balances in two separate steps and therefore reports transient phantom deltas (e.g. +125 on Frame A) while the true invariant holds at 0. The atomic delta is now the source of truth for status, breaches, uptime and the streak; the HTTP value is retained and displayed additionally as the "live-read Δ (in-flight)". Also adds a reusable, runtime-togglable maintenance mode and this patch-notes panel.',
  },
  {
    id: 'cqrs-balance-integrity-2026-05-29',
    date: '2026-05-29',
    frame: 'all',
    delta: 125.0,
    title: 'CQRS transactional-outbox balance integrity (pass73.3.20)',
    cause: 'Stale DisputeCompensationMinted counter double-counted in the read-model audit path after the CQRS re-baseline',
    status: 'RESOLVED',
    kind: 'maintenance',
    patch_ref: 'pass73.3.20',
    description: 'Fleet-wide rollout of a tolerance-free balance-integrity chain: a DB-trigger journal (L1) feeds a transactional outbox emitter (L2) that emits one LedgerBalanceChanged event per txid, making the projection the single balance writer with supply conserved per-txid net. Both frames are cut over to the single-writer projection; the atomic invariant verified directly by this auditor is Δ = 0 on both. Frame A HTTP /supply-audit had shown a +125 AVT live-read Δ: two legacy DisputeCompensationMinted events (125 AVT total) were folded into tokens_issued by the re-baseline via the recipient balances, but the separate tokens_minted_compensation counter was left set — so get_supply_summary() added the 125 a second time. It was a stale read-model counter, NOT a real supply change. RESOLVED Δ-safe by zeroing the redundant counter (no balances touched); HTTP /supply-audit now reads Δ = 0 on both frames, matching the atomic invariant.',
  },
  {
    id: 'f037-autocompound-2026-04-11',
    date: '2026-04-11',
    frame: 'frame-a',
    delta: 37.442107,
    title: 'RewardsAutoCompounded projection double-count',
    cause: 'Auto-compound projection bug (payouts on locked units)',
    status: 'PATCHED',
    kind: 'incident',
    patch_ref: 'Part 15',
    description: 'The midnight distributor of payouts on locked units emitted both TokensIssued and RewardsAutoCompounded for auto-compounded payouts. The projection added both events to the balance (+74.88 AVT total for a 37.44 AVT payout) instead of moving the amount from liquid to locked. Fixed by updating the materialized_balances SQL trigger and the Python projection to subtract from liquid_balance when RewardsAutoCompounded fires. Delta restored to 0.0 via direct materialized_balances row correction. Frame B has the same dormant code path but no auto-compound agents yet, so it has not been affected.',
  },
]

const showIncidentLog = ref(false)
const showMaxDeltaInfo = ref(false)
const chartMode = ref<'atomic' | 'live'>('atomic')

const peakBetaIncident = computed(() => {
  const withDelta = patchNotes.filter((n) => n.kind === 'incident' && typeof n.delta === 'number')
  if (withDelta.length === 0) return null
  return withDelta.reduce((max, i) => (i.delta! > max.delta! ? i : max), withDelta[0])
})

function frameName(f: string): string {
  return f === 'frame-a' ? 'Frame A' : f === 'frame-b' ? 'Frame B' : 'Fleet'
}
// Maps, not ternaries: the old label chain ended in 'FLEET', so any frame it did not
// name was silently reported as fleet-wide. An unknown id now prints ITSELF.
const BADGE_CLASS: Record<string, string> = {
  'frame-a': 'badge-a', 'frame-b': 'badge-b', 'frame-c': 'badge-c',
  eu: 'badge-eu', asia: 'badge-asia', all: 'badge-all',
}
const BADGE_LABEL: Record<string, string> = {
  'frame-a': 'FRAME A', 'frame-b': 'FRAME B', 'frame-c': 'FRAME C',
  eu: 'EU', asia: 'ASIA', all: 'FLEET',
}
function frameBadgeClass(f: string): string {
  return BADGE_CLASS[f] || 'badge-all'
}
function frameBadgeLabel(f: string): string {
  return BADGE_LABEL[f] || f.toUpperCase()
}
function statusToneClass(n: PatchNote): string {
  if (n.kind === 'upgrade') return 'tone-upgrade'
  if (n.status === 'IN PROGRESS' || n.status === 'TEMPORARY') return 'tone-progress'
  return 'ok'
}
function statusGlyph(n: PatchNote): string {
  if (n.kind === 'upgrade') return '✦'
  if (n.status === 'IN PROGRESS' || n.status === 'TEMPORARY') return '◐'
  return '✓'
}

function openIncidentLog() {
  showIncidentLog.value = true
  showMaxDeltaInfo.value = false
  setTimeout(() => {
    document.querySelector('.au-incidents-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 80)
}

// Frame configs (with fallback for single-frame)
const frameConfigs = computed(() => {
  // Defensive mode-scope: even if `frames` leaks a foreign-mode entry (e.g. a WS
  // welcome race), every panel that iterates frameConfigs stays in the viewed env.
  const f = frames.value.filter((fr) => !fr.mode || fr.mode === mode.value)
  if (f.length > 0) return f
  return [{ id: 'frame-a', name: 'Frame A', currency: 'AVT' }]
})
// Per-frame currency ticker (Frame A = AVT, Frame B = JDAY, Frame C = BVT; read live
// from the frame's own card so a re-denomination needs no code change). Falls back to AVT.
function frameCurrency(frameId: string): string {
  return frames.value.find((f) => f.id === frameId)?.currency || 'AVT'
}
// Single-letter frame tag (A/B/C) derived from the display name — mode-agnostic,
// so sbx-frame-c and a future prod frame-c both badge as 'C' (not 'A').
function frameLetter(idOrName: string): string {
  const f = frames.value.find((x) => x.id === idOrName)
  const n = (f?.name || idOrName || '').toUpperCase()
  const m = n.match(/FRAME\s*([A-Z0-9])/) || n.match(/[-_ ]([A-Z0-9])$/)
  return m ? m[1] : (n.replace(/[^A-Z0-9]/g, '').slice(-1) || '?')
}
// Per-frame CSS accent class (mode-agnostic via the letter, so sbx-frame-c and
// frame-c both get the amber Frame-C identity, not just prod ids).
function frameCardClass(idOrName: string): string {
  const L = frameLetter(idOrName)
  return L === 'C' ? 'frame-c-card' : L === 'B' ? 'frame-b-card' : ''
}
// §GLOBALSTD 4.2 (refined 2026-08-22) — staleness is measured CLIENT-monotonically:
// the moment the newest SERVER timestamp last ADVANCED on this client. The first
// cut compared server clocks against the client clock, so a client running a few
// minutes fast would show a FALSE stale banner (skew reads as age). null until
// data first arrives (no data is the 'Acquiring…' state, not staleness).
const nowTick = ref(Date.now())
let _staleTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { _staleTimer = setInterval(() => { nowTick.value = Date.now() }, 5000) })
onUnmounted(() => { if (_staleTimer) clearInterval(_staleTimer) })
const newestServerTs = computed<number>(() => {
  let newest = 0
  for (const f of frames.value || []) {
    const ts = latestByFrame.value?.[f.id]?.timestamp
    if (ts) newest = Math.max(newest, Date.parse(ts))
  }
  return newest
})
const lastAdvanceAt = ref<number | null>(null)
watch(newestServerTs, (v, old) => { if (v && v !== old) lastAdvanceAt.value = Date.now() })
const staleAgeSec = computed<number | null>(() =>
  lastAdvanceAt.value === null ? null : Math.max(0, (nowTick.value - lastAdvanceAt.value) / 1000))

function frameLabelClass(idOrName: string): string {
  const L = frameLetter(idOrName)
  return L === 'C' ? 'frame-c-label' : L === 'B' ? 'frame-b-label' : ''
}

// System-wide conservation state (drives the crest)
// §MTLSHOPS (a) (2026-09-15, agentvault2-85's calls): the crest, the klaxon, the formula and the atomic trend answer from
// the atomic read alone. A public-only frame (its databases take TLS clients with a frame certificate only, so this host
// reads its public supply audit) is never counted among the frames whose invariant this page verifies.
function isPublicOnly(frameId: string): boolean {
  return !!(latestOf(frameId)?.extra_data?.public_only || frames.value.find((f) => f.id === frameId)?.public_only)
}
const truthFrames = computed(() => frameConfigs.value.filter((f) => !isPublicOnly(f.id)))
const publicBreachFrames = computed(() => frameConfigs.value.filter((f) => {
  if (!isPublicOnly(f.id)) return false
  const r = latestOf(f.id)
  return !!r && r.status === 'BREACH' && (r.public_breach_streak ?? 0) >= (r.extra_data?.public_breach_readings ?? 5)
}))
const allConserved = computed(() =>
  truthFrames.value.length > 0 &&
  truthFrames.value.every((f) => truthStatusOf(f.id) === 'OK')
)
const systemAtomicDisplay = computed(() => {
  let worst = 0
  for (const f of frameConfigs.value) {
    const a = atomicVal(f.id)
    if (a !== null && Math.abs(a) > Math.abs(worst)) worst = a
  }
  return worst.toFixed(6)
})
const lastVerified = computed(() => {
  let t = ''
  for (const f of frameConfigs.value) {
    const r = latestByFrame.value[f.id]
    if (r?.timestamp && (!t || r.timestamp > t)) t = r.timestamp
  }
  return t
})

// ── Breach-alarm choreography ───────────────────────────────────────────────
// Intensity gradient: none (calm green) → contained (gold, maintenance window,
// acknowledged) → critical (red klaxon, a real un-contained invariant breach).
const breachingFrames = computed(() =>
  truthFrames.value.filter((f) => truthStatusOf(f.id) === 'BREACH')
)
const alarmLevel = computed<'none' | 'contained' | 'critical'>(() => {
  if (breachingFrames.value.length === 0) return 'none'
  return maintenanceActive() ? 'contained' : 'critical'
})
const crestText = computed(() => {
  if (alarmLevel.value === 'critical') return 'INVARIANT BREACH'
  if (alarmLevel.value === 'contained') return 'BREACH · CONTAINED'
  return allConserved.value ? 'SUPPLY CONSERVED' : 'VERIFYING'
})
const formulaStamp = computed(() => {
  if (alarmLevel.value === 'critical') return '✗ BREACH'
  if (alarmLevel.value === 'contained') return '◐ CONTAINED'
  return '✓ HOLDS'
})
function breachDeltaDisplay(frameId: string): string {
  const a = atomicVal(frameId)
  const v = a !== null ? a : (liveVal(frameId) ?? 0)
  return (v >= 0 ? '+' : '') + v.toFixed(6)
}

// ── Delta accessors ─────────────────────────────────────────────────────────
function latestOf(frameId: string): AuditResult | null {
  return latestByFrame.value[frameId] || null
}
function atomicVal(frameId: string): number | null {
  const r = latestOf(frameId)
  if (!r) return null
  return r.atomic_delta ?? null
}
function liveVal(frameId: string): number | null {
  const r = latestOf(frameId)
  if (!r) return null
  return r.delta ?? null
}
function atomicAvailable(frameId: string): boolean {
  return atomicVal(frameId) !== null
}
function truthStatusOf(frameId: string): string | null {
  const r = latestOf(frameId)
  if (!r || isPublicOnly(frameId)) return null
  return r.atomic_status ?? null
}
function maintenanceActive(): boolean {
  return !!maintenance.value?.active
}
function headlineDisplay(frameId: string): string {
  const a = atomicVal(frameId)
  const v = a !== null ? a : liveVal(frameId)
  return v === null ? '---' : v.toFixed(1)
}
function headlineNum(frameId: string): number {
  const a = atomicVal(frameId)
  if (a !== null) return a
  const l = liveVal(frameId)
  return l !== null ? l : 0
}
function atomicDisplay(frameId: string): string {
  const a = atomicVal(frameId)
  return a === null ? 'n/a' : a.toFixed(6)
}
function liveDisplay(frameId: string): string {
  const v = liveVal(frameId)
  if (v === null) return '---'
  return (v >= 0 ? '+' : '') + v.toFixed(1)
}
function liveDeltaFixed(frameId: string): string {
  const v = liveVal(frameId)
  if (v === null) return '---'
  return (v >= 0 ? '+' : '') + v.toFixed(6)
}

// Inline atomic-Δ sparkline (oldest→newest). A flatline on the baseline = proof
// of conservation over the recent window. Content is fully controlled (no user
// input) so v-html is safe here.
function sparkline(frameId: string): string {
  const rows = (historyByFrame.value[frameId] || []).slice(0, 48)
  // §MTLSHOPS (a): the atomic Δ only; a row without one is not drawn as if it were
  const vals = rows.map((r) => r.atomic_delta).filter((v): v is number => v !== null && v !== undefined).reverse()
  const w = 72, h = 18, mid = h / 2
  if (vals.length < 2) {
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><line x1="0" y1="${mid}" x2="${w}" y2="${mid}" stroke="rgba(143,191,163,0.18)" stroke-width="1"/></svg>`
  }
  const max = Math.max(1e-9, ...vals.map((v) => Math.abs(v)))
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w
    const y = mid - (v / max) * (mid - 1.5)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const color = frameHue(frameId)
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">`
    + `<line x1="0" y1="${mid}" x2="${w}" y2="${mid}" stroke="rgba(143,191,163,0.14)" stroke-width="1" stroke-dasharray="2 3"/>`
    + `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>`
    + `</svg>`
}
function isDivergent(frameId: string): boolean {
  const a = atomicVal(frameId)
  const l = liveVal(frameId)
  if (a === null || l === null) return false
  return Math.abs(l - a) > 0.0000005
}
function deltaClass(frameId: string): string {
  if (isPublicOnly(frameId)) return publicBreachFrames.value.some((f) => f.id === frameId) ? 'warn' : ''
  const t = truthStatusOf(frameId)
  if (!t) return latestOf(frameId) ? 'warn' : ''
  if (t === 'OK') return 'ok'
  if (maintenanceActive()) return 'maint'
  return t === 'BREACH' ? 'danger' : 'warn'
}
function statusLabel(frameId: string): string {
  const r = latestOf(frameId)
  if (r && isPublicOnly(frameId)) return `PUBLIC ${r.status}${r.status === 'BREACH' ? ' ×' + (r.public_breach_streak ?? 0) : ''}`
  if (r && !truthStatusOf(frameId)) return 'NOT MEASURED'
  const t = truthStatusOf(frameId) || ''
  if (t === 'OK') return 'OK'
  if (maintenanceActive() && t === 'BREACH') return 'BREACH · MAINT'
  return t
}
function truthIcon(frameId: string): string {
  if (isPublicOnly(frameId)) return '◌'
  const t = truthStatusOf(frameId)
  return t === 'OK' ? '✓' : t === 'BREACH' ? '✗' : '!'
}
function tokensDestroyed(frameId: string): number | null {
  const r = latestOf(frameId)
  if (!r) return null
  const v = r.tokens_destroyed ?? r.extra_data?.tokens_destroyed
  return (v === null || v === undefined) ? null : v
}
// A2: REAL issuance/burn from typed supply events since the balance-integrity baseline.
// (tokens_issued/tokens_destroyed above are transfer-leg-inflated ledger accumulators.)
function trueMinted(frameId: string): number | null {
  const v = latestOf(frameId)?.extra_data?.true_minted
  return (v === null || v === undefined) ? null : v
}
function trueBurned(frameId: string): number | null {
  const v = latestOf(frameId)?.extra_data?.true_burned
  return (v === null || v === undefined) ? null : v
}
function agentCount(frameId: string): number | null {
  const r = latestOf(frameId)
  const v = r?.extra_data?.agent_count
  return (v === null || v === undefined) ? null : v
}
function isBalanced(frameId: string): boolean {
  const t = truthStatusOf(frameId)
  return t === 'OK'
}
// The escrow + cross-frame settlement position that bridges Issued → Σ Circulating
// (circulating = issued − destroyed + this). Computed from the SAME displayed figures so
// the on-screen identity always sums exactly. It is conserved (Δ=0) cross-frame/in-flight
// value — NOT issued, NOT missing. Non-zero on any FX-active frame.
function netPosition(frameId: string): number | null {
  const r = latestOf(frameId)
  if (!r || r.tokens_issued === undefined || r.total_circulating === undefined) return null
  const destroyed = (r.tokens_destroyed ?? r.extra_data?.tokens_destroyed ?? 0) as number
  return r.total_circulating - r.tokens_issued + destroyed
}

// Per-row helpers (audit log)
function rowTruth(r: AuditResult): string {
  // §MTLSHOPS (a): the log's status column is the atomic verdict; a public reading or a row without one is not a verdict
  if (r.extra_data?.public_only) return 'PUBLIC'
  return r.atomic_status ?? 'NOT MEASURED'
}
function rowTruthBreach(r: AuditResult): boolean {
  return rowTruth(r) === 'BREACH' && !r.maintenance
}
function rowAtomicDisplay(r: AuditResult): string {
  return (r.atomic_delta === null || r.atomic_delta === undefined) ? 'n/a' : r.atomic_delta.toFixed(6)
}
function rowAtomicClass(r: AuditResult): string {
  if (r.atomic_delta === null || r.atomic_delta === undefined) return 'dim'
  return rowTruth(r) === 'OK' ? 'ok' : (r.maintenance ? 'maint' : 'danger')
}

const combinedDeltaClass = computed(() => {
  for (const f of truthFrames.value) {
    const cls = deltaClass(f.id)
    if (cls === 'danger') return 'danger'
    if (cls === 'maint') return 'maint'
    if (cls === 'warn') return 'warn'
  }
  return frameConfigs.value.some((f) => latestByFrame.value[f.id]) ? 'ok' : ''
})

// ── Chart — dual-frame line datasets, atomic/live toggle ────────────────────
const { historyByFrame } = storeToRefs(auditorStore)

function seriesValue(d: AuditResult): number | null {
  if (chartMode.value === 'atomic') {
    // §MTLSHOPS (a): the ATOMIC trend draws atomic Δ only; a row without one is a gap, never its live Δ
    return (d.atomic_delta === null || d.atomic_delta === undefined) ? null : d.atomic_delta
  }
  return d.delta
}

// Per-frame hue — keyed by display name so it's mode-agnostic (prod frame-a and
// sandbox sbx-frame-a both render green). Frame C (BVT) gets amber to read as a
// distinct sovereign/second-currency frame. Drives chart, legend, spark, badges.
function frameHue(idOrName: string): string {
  const f = frames.value.find((x) => x.id === idOrName)
  const n = (f?.name || idOrName || '').toUpperCase()
  if (n.includes('FRAME C') || n.endsWith(' C') || n.includes('-C')) return '#ffb300' // BVT amber
  if (n.includes('FRAME B') || n.endsWith(' B') || n.includes('-B')) return '#00b0ff' // blue
  return '#00c853' // Frame A / default green
}
function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const chartLabels = computed(() => {
  // Longest history series across the *current mode's* frames (sandbox ids are
  // sbx-frame-*, prod ids are frame-*) — never hardcode prod ids or the chart
  // is empty in sandbox.
  let longest: AuditResult[] = []
  for (const f of frameConfigs.value) {
    const h = historyByFrame.value[f.id] || []
    if (h.length > longest.length) longest = h
  }
  return [...longest].reverse().slice(-200).map((d) => {
    const t = new Date(d.timestamp)
    return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  })
})

const chartReady = computed(() => chartLabels.value.length > 1)

// Emphasized zero baseline — the "flatline of conservation" (Δ = 0 is the proof).
const zeroLinePlugin = {
  id: 'auZeroLine',
  beforeDatasetsDraw(chart: any) {
    const area = chart.chartArea
    const y = chart.scales?.y
    if (!area || !y) return
    const y0 = y.getPixelForValue(0)
    if (y0 < area.top || y0 > area.bottom) return
    const ctx = chart.ctx
    ctx.save()
    ctx.beginPath()
    ctx.moveTo(area.left, y0)
    ctx.lineTo(area.right, y0)
    ctx.lineWidth = 1
    ctx.setLineDash([3, 5])
    ctx.strokeStyle = 'rgba(0, 200, 83, 0.30)'
    ctx.shadowColor = 'rgba(0, 200, 83, 0.45)'
    ctx.shadowBlur = 6
    ctx.stroke()
    ctx.restore()
  },
}
const chartPlugins = [zeroLinePlugin]

const chartConfig = computed(() => {
  // One dataset per current-mode frame (was hardcoded to frame-a/frame-b, so the
  // sandbox chart — ids sbx-frame-* — rendered empty and Frame C never plotted).
  const datasets: any[] = frameConfigs.value
    .map((f) => {
      const data = [...(historyByFrame.value[f.id] || [])].reverse().slice(-200)
      if (data.length === 0) return null
      if (chartMode.value === 'atomic' && (isPublicOnly(f.id) || data.every((d) => d.atomic_delta === null || d.atomic_delta === undefined))) return null
      const color = frameHue(f.id)
      return {
        label: f.name,
        data: data.map(seriesValue),
        borderColor: color,
        backgroundColor: (ctx: any) => {
          if (!ctx.chart?.ctx) return hexToRgba(color, 0.06)
          const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 180)
          gradient.addColorStop(0, hexToRgba(color, 0.12))
          gradient.addColorStop(1, hexToRgba(color, 0.0))
          return gradient
        },
        borderWidth: 2,
        pointRadius: (c: any) => (c.dataIndex === (c.dataset.data.length - 1) ? 3.6 : 0),
        pointBackgroundColor: color,
        pointBorderColor: hexToRgba(color, 0.35),
        pointBorderWidth: 4,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: color,
        pointHoverBorderColor: color,
        fill: true,
        tension: 0.35,
      }
    })
    .filter(Boolean)

  return { labels: chartLabels.value, datasets }
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  interaction: { mode: 'index' as const, intersect: false },
  plugins: {
    legend: {
      display: frames.value.length > 1,
      position: 'top' as const,
      align: 'end' as const,
      labels: {
        color: '#4a7a5e',
        font: { family: "'IBM Plex Mono', monospace", size: 9 },
        boxWidth: 10,
        boxHeight: 2,
        padding: 12,
      },
    },
    tooltip: {
      backgroundColor: 'rgba(4, 26, 14, 0.95)',
      borderColor: 'rgba(0, 200, 100, 0.25)',
      borderWidth: 1,
      titleColor: '#8fbfa3',
      bodyColor: '#e0f2e9',
      titleFont: { family: "'IBM Plex Mono', monospace", size: 10, weight: 400 as const },
      bodyFont: { family: "'IBM Plex Mono', monospace", size: 11, weight: 600 as const },
      padding: { top: 8, bottom: 8, left: 12, right: 12 },
      cornerRadius: 4,
      callbacks: {
        label: (ctx: any) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(6)}`,
      },
    },
  },
  scales: {
    x: {
      grid: { color: 'rgba(0, 200, 100, 0.04)', drawBorder: false },
      border: { display: false },
      ticks: {
        color: '#4a7a5e',
        font: { family: "'IBM Plex Mono', monospace", size: 9 },
        maxTicksLimit: 8,
        padding: 8,
      },
    },
    y: {
      grid: { color: 'rgba(0, 200, 100, 0.04)', drawBorder: false },
      border: { display: false },
      ticks: {
        color: '#4a7a5e',
        font: { family: "'IBM Plex Mono', monospace", size: 9 },
        padding: 8,
      },
      suggestedMin: -0.001,
      suggestedMax: 0.001,
    },
  },
}))

// ── Formatters ──────────────────────────────────────────────────────────────
function formatNumber(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(ts: string): string {
  const d = new Date(ts)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }
  return d.toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatDateShort(ts: string): string {
  return new Date(ts).toLocaleDateString([], { month: '2-digit', day: '2-digit' })
}

function formatDateTime(ts: string): string {
  return new Date(ts).toLocaleString([], {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function formatTimeAgo(ts: string): string {
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function latencyClass(ms: number): string {
  if (ms < 100) return 'latency-ok'
  if (ms < 500) return 'latency-warn'
  return 'latency-bad'
}

// Compact inline stat-card icons (controlled SVG, safe v-html).
function statIcon(name: string): string {
  const paths: Record<string, string> = {
    audits: '<path d="M3 12h3l2-7 4 14 2-7h3"/>',
    streak: '<circle cx="12" cy="12" r="9"/><path d="M8.4 12l2.6 2.6 4.6-5.2"/>',
    uptime: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    atomic: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    live: '<path d="M3 12h3.5l2 5.5 3-13 2.4 9 1.6-3H21"/>',
    since: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 3.5v3M16 3.5v3"/>',
  }
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ''}</svg>`
}

// Lifecycle
onMounted(async () => {
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  await auditorStore.fetchAll()
  wsStore.connect()
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  wsStore.disconnect()
})
</script>

<style scoped>
/* ROOT */
.auditor-root {
  max-width: 1400px;
  margin: 0 auto;
  padding: 28px 36px 20px;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

/* HEADER */
.au-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
}

.au-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.au-icon {
  color: var(--au-accent);
  font-size: 18px;
  opacity: 0.9;
  text-shadow: 0 0 12px rgba(0, 200, 83, 0.5);
  animation: iconBeat 4s ease-in-out infinite;
}

@keyframes iconBeat {
  0%, 100% { opacity: 0.7; text-shadow: 0 0 10px rgba(0, 200, 83, 0.35); }
  50% { opacity: 1; text-shadow: 0 0 16px rgba(0, 200, 83, 0.6); }
}

.au-title {
  font-family: var(--au-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.34em;
  color: var(--au-text);
  margin: 0;
  text-transform: uppercase;
  text-shadow: 0 0 20px rgba(0, 200, 83, 0.16);
}

.au-subtitle {
  font-size: 11px;
  color: var(--au-text-dim);
  letter-spacing: 0.04em;
  padding-left: 10px;
  border-left: 1px solid var(--au-border);
}

/* ── Tier toggle (prod | sandbox | legacy) — sets which tier is audited ── */
.au-mode-toggle {
  display: inline-flex;
  align-items: center;
  margin-left: 12px;
  padding: 2px;
  gap: 2px;
  border: 1px solid var(--au-border);
  border-radius: 7px;
  background: rgba(0, 0, 0, 0.25);
}
.au-mode-btn {
  font-family: 'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.1em;
  color: var(--au-text-dim);
  background: transparent;
  border: 0;
  border-radius: 5px;
  padding: 5px 11px;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.au-mode-btn:hover { color: var(--au-text); }
.au-mode-btn.active.prod {
  color: #04130b;
  background: linear-gradient(180deg, rgba(0, 200, 83, 0.95), rgba(0, 176, 80, 0.85));
  box-shadow: 0 0 12px rgba(0, 200, 83, 0.35);
}
.au-mode-btn.active.sandbox {
  color: #0a1014;
  background: linear-gradient(180deg, rgba(255, 193, 7, 0.95), rgba(255, 171, 0, 0.85));
  box-shadow: 0 0 12px rgba(255, 193, 7, 0.3);
}
/* Legacy = the retiring stack: a muted slate, deliberately quieter than the two
   live tiers so the eye reads it as an archive rather than something to watch. */
.au-mode-btn.active.legacy {
  color: #e8edf2;
  background: linear-gradient(180deg, rgba(120, 134, 156, 0.92), rgba(96, 110, 132, 0.85));
  box-shadow: 0 0 12px rgba(120, 134, 156, 0.28);
}

.au-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
}

.au-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.au-live-dot.live {
  background: var(--au-accent);
  box-shadow: 0 0 6px var(--au-accent), 0 0 12px rgba(0, 200, 83, 0.3);
  animation: pulseDot 2s ease-in-out infinite;
}

.au-live-dot.offline {
  background: var(--au-danger);
  box-shadow: 0 0 6px var(--au-danger);
}

.au-live-label {
  font-weight: 700;
  font-size: 10px;
  letter-spacing: 0.12em;
}

.au-live-label.live { color: var(--au-accent); }
.au-live-label.offline { color: var(--au-danger); }

.au-header-sep {
  width: 1px;
  height: 12px;
  background: var(--au-border);
}

.au-header-meta {
  color: var(--au-text-dim);
  font-size: 11px;
  letter-spacing: 0.02em;
}

.au-clock {
  font-size: 11px;
  color: var(--au-text-secondary);
  letter-spacing: 0.08em;
  font-variant-numeric: tabular-nums;
}
.au-clock-z {
  color: var(--au-text-ghost);
  font-size: 9px;
  letter-spacing: 0.12em;
}

.au-header-line {
  height: 1px;
  background: linear-gradient(90deg, var(--au-accent) 0%, rgba(0, 200, 83, 0.15) 30%, rgba(0, 200, 83, 0.03) 100%);
  margin-bottom: 24px;
}

/* ──────────────────────────────────────────────────────────── */
/* MAINTENANCE BANNER                                           */
/* ──────────────────────────────────────────────────────────── */
.au-maint-banner {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 18px 14px 20px;
  margin-bottom: 24px;
  background: linear-gradient(135deg, rgba(255, 215, 0, 0.07) 0%, rgba(255, 145, 0, 0.04) 100%);
  border: 1px solid rgba(255, 196, 0, 0.30);
  border-radius: var(--au-radius-lg);
  box-shadow: 0 0 24px rgba(255, 180, 0, 0.06), var(--au-shadow);
  overflow: hidden;
}

.au-maint-stripe {
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--au-gold), var(--au-warning));
  box-shadow: 0 0 12px rgba(255, 196, 0, 0.5);
  animation: maintPulse 2.4s ease-in-out infinite;
}

.au-maint-icon {
  color: var(--au-gold);
  font-size: 18px;
  line-height: 1.3;
  flex-shrink: 0;
  text-shadow: 0 0 10px rgba(255, 196, 0, 0.4);
}

.au-maint-body { flex: 1; min-width: 0; }

.au-maint-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}

.au-maint-pill {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: #1a1200;
  background: linear-gradient(135deg, var(--au-gold), var(--au-warning));
  padding: 2px 8px;
  border-radius: 3px;
  text-transform: uppercase;
}

.au-maint-title {
  font-size: 13px;
  font-weight: 600;
  color: #ffe89e;
  letter-spacing: 0.01em;
}

.au-maint-ref {
  font-size: 10px;
  color: var(--au-warning);
  font-family: var(--au-font);
  border: 1px solid rgba(255, 196, 0, 0.25);
  border-radius: 3px;
  padding: 1px 6px;
}

.au-maint-msg {
  font-size: 11.5px;
  color: var(--au-text-secondary);
  line-height: 1.6;
}

.au-maint-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 7px;
  font-size: 10px;
  color: var(--au-text-dim);
  letter-spacing: 0.02em;
}

.au-maint-link {
  color: var(--au-gold);
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px dashed rgba(255, 196, 0, 0.4);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.au-maint-link:hover { color: #fff0bf; }

@keyframes maintPulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

/* MAIN GRID */
.au-main-grid {
  display: grid;
  grid-template-columns: minmax(300px, 420px) 1fr;
  gap: 24px;
  margin-bottom: 24px;
}

/* Hero Column */
.au-hero-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.au-hero-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.au-hero-card {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 232px;
  background: var(--au-gradient);
  border: 1px solid var(--au-border);
  border-radius: var(--au-radius-lg);
  box-shadow: var(--au-shadow-lg);
  overflow: hidden;
  animation: breathe 4s ease-in-out infinite;
}

.au-hero-card.frame-b-card {
  border-color: rgba(0, 176, 255, 0.12);
}

.au-hero-scanline {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, rgba(0, 200, 83, 0.08) 50%, transparent 100%);
  animation: scanline 8s linear infinite;
  pointer-events: none;
  z-index: 2;
}

.frame-b-card .au-hero-scanline {
  background: linear-gradient(90deg, transparent 0%, rgba(0, 176, 255, 0.08) 50%, transparent 100%);
}

/* Ring pulses */
.au-hero-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  border: 1px solid transparent;
  pointer-events: none;
  opacity: 0;
}

.au-hero-ring.ring-1 { width: 90px; height: 90px; }
.au-hero-ring.ring-2 { width: 130px; height: 130px; }
.au-hero-ring.ring-3 { width: 170px; height: 170px; }

.au-hero-ring.ok.ring-1 {
  border-color: rgba(0, 200, 83, 0.15);
  animation: ringPulse 3s ease-out infinite 0s;
}
.au-hero-ring.ok.ring-2 {
  border-color: rgba(0, 200, 83, 0.10);
  animation: ringPulse 3s ease-out infinite 0.5s;
}
.au-hero-ring.ok.ring-3 {
  border-color: rgba(0, 200, 83, 0.06);
  animation: ringPulse 3s ease-out infinite 1s;
}

.frame-b-card .au-hero-ring.ok.ring-1 {
  border-color: rgba(0, 176, 255, 0.15);
}
.frame-b-card .au-hero-ring.ok.ring-2 {
  border-color: rgba(0, 176, 255, 0.10);
}
.frame-b-card .au-hero-ring.ok.ring-3 {
  border-color: rgba(0, 176, 255, 0.06);
}

.au-hero-ring.danger.ring-1 {
  border-color: rgba(255, 23, 68, 0.20);
  animation: ringPulse 1.5s ease-out infinite 0s;
}
.au-hero-ring.danger.ring-2 {
  border-color: rgba(255, 23, 68, 0.14);
  animation: ringPulse 1.5s ease-out infinite 0.3s;
}
.au-hero-ring.danger.ring-3 {
  border-color: rgba(255, 23, 68, 0.08);
  animation: ringPulse 1.5s ease-out infinite 0.6s;
}

.au-hero-ring.maint.ring-1 {
  border-color: rgba(255, 196, 0, 0.18);
  animation: ringPulse 2.2s ease-out infinite 0s;
}
.au-hero-ring.maint.ring-2 {
  border-color: rgba(255, 196, 0, 0.12);
  animation: ringPulse 2.2s ease-out infinite 0.4s;
}
.au-hero-ring.maint.ring-3 {
  border-color: rgba(255, 196, 0, 0.07);
  animation: ringPulse 2.2s ease-out infinite 0.8s;
}

.au-hero-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.au-frame-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--au-accent);
  opacity: 0.7;
  margin-bottom: 2px;
}

.au-frame-label.frame-b-label {
  color: var(--au-accent-b);
}

.au-hero-label {
  margin-bottom: 2px;
}

.au-hero-value {
  font-size: 60px;
  font-weight: 200;
  line-height: 1;
  letter-spacing: -0.03em;
  transition: color var(--au-transition-slow), text-shadow var(--au-transition-slow);
  font-variant-numeric: tabular-nums;
}

.au-hero-value.ok {
  color: var(--au-accent);
  text-shadow: var(--au-glow-accent);
}

.frame-b-card .au-hero-value.ok {
  color: var(--au-accent-b);
  text-shadow: var(--au-glow-accent-b);
}

.au-hero-value.danger {
  color: var(--au-danger);
  text-shadow: 0 0 60px rgba(255, 23, 68, 0.40), 0 0 120px rgba(255, 23, 68, 0.15);
}

.au-hero-value.warn {
  color: var(--au-warning);
  text-shadow: 0 0 60px rgba(255, 145, 0, 0.35);
}

.au-hero-value.maint {
  color: var(--au-gold);
  text-shadow: 0 0 50px rgba(255, 196, 0, 0.35);
}

.au-hero-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.au-hero-check {
  font-size: 12px;
  font-weight: 700;
}

.au-hero-check.ok { color: var(--au-accent); }
.frame-b-card .au-hero-check.ok { color: var(--au-accent-b); }
.au-hero-check.danger { color: var(--au-danger); }
.au-hero-check.warn { color: var(--au-warning); }
.au-hero-check.maint { color: var(--au-gold); }

.au-hero-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  padding: 2px 8px;
  border-radius: 2px;
}

.au-hero-badge.ok {
  color: var(--au-accent);
  background: rgba(0, 200, 83, 0.10);
  border: 1px solid rgba(0, 200, 83, 0.18);
}

.frame-b-card .au-hero-badge.ok {
  color: var(--au-accent-b);
  background: rgba(0, 176, 255, 0.10);
  border: 1px solid rgba(0, 176, 255, 0.18);
}

/* Frame C (BVT) — amber sovereign identity, mirroring frame-b's blue accent so
   the second-currency frame reads as visually distinct (matches the chart /
   legend / badge hue #ffb300). */
.au-hero-card.frame-c-card { border-color: rgba(255, 179, 0, 0.14); }
.frame-c-card .au-hero-scanline {
  background: linear-gradient(90deg, transparent 0%, rgba(255, 179, 0, 0.09) 50%, transparent 100%);
}
.frame-c-card .au-hero-ring.ok.ring-1,
.frame-c-card .au-hero-ring.ok.ring-2,
.frame-c-card .au-hero-ring.ok.ring-3 { border-color: rgba(255, 179, 0, 0.5); }
.au-frame-label.frame-c-label,
.frame-c-card .au-frame-label { color: #ffb300; }
.frame-c-card .au-hero-value.ok { color: #ffb300; text-shadow: 0 0 50px rgba(255, 179, 0, 0.35); }
.frame-c-card .au-hero-check.ok { color: #ffb300; }
.frame-c-card .au-hero-badge.ok {
  color: #ffb300;
  background: rgba(255, 179, 0, 0.10);
  border: 1px solid rgba(255, 179, 0, 0.20);
}
.au-supply-frame-label.frame-c-label { color: #ffb300; }
/* Second-currency (BVT) unit ticker — amber so the denomination reads distinct
   from AVT at a glance, without recolouring the value itself. */
.au-unit.au-unit-alt { color: #ffb300; opacity: 0.9; }

.au-hero-badge.danger {
  color: var(--au-danger);
  background: rgba(255, 23, 68, 0.10);
  border: 1px solid rgba(255, 23, 68, 0.18);
}

.au-hero-badge.warn {
  color: var(--au-warning);
  background: rgba(255, 145, 0, 0.10);
  border: 1px solid rgba(255, 145, 0, 0.18);
}

.au-hero-badge.maint {
  color: var(--au-gold);
  background: rgba(255, 196, 0, 0.10);
  border: 1px solid rgba(255, 196, 0, 0.20);
}

/* Hero sub — live-read Δ shown additionally to the atomic truth */
.au-hero-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--au-border-subtle);
  font-size: 10px;
}

.au-hero-sub-label {
  color: var(--au-text-dim);
  letter-spacing: 0.1em;
  font-weight: 700;
  font-size: 8.5px;
}

.au-hero-sub-val {
  font-family: var(--au-font);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.au-hero-sub-val.match { color: var(--au-text-secondary); }
.au-hero-sub-val.diverge { color: var(--au-warning); }

.au-hero-sub-tag {
  font-size: 8px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--au-warning);
  background: rgba(255, 145, 0, 0.08);
  border: 1px solid rgba(255, 145, 0, 0.18);
  border-radius: 2px;
  padding: 1px 5px;
}

/* Formula Card */
.au-formula-card {
  background: var(--au-gradient);
  border: 1px solid var(--au-border);
  border-radius: var(--au-radius-lg);
  padding: 18px 20px;
  box-shadow: var(--au-shadow);
}

.au-formula-label { margin-bottom: 14px; }

.au-formula-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 12px 0;
}

.au-formula-term {
  font-size: 12px;
  color: var(--au-text-secondary);
  letter-spacing: 0.04em;
}

.au-formula-eq {
  font-size: 11px;
  letter-spacing: 0;
  transition: color var(--au-transition-slow), text-shadow var(--au-transition-slow);
  line-height: 1.2;
}

.au-formula-eq.ok {
  background: linear-gradient(90deg, rgba(0, 200, 83, 0.22) 0%, var(--au-accent) 50%, rgba(0, 200, 83, 0.22) 100%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  filter: drop-shadow(0 0 8px rgba(0, 200, 83, 0.35));
  animation: eqFlow 3.2s linear infinite;
}
@keyframes eqFlow { to { background-position: -220% 0; } }
.au-formula-eq.danger {
  color: var(--au-danger);
  text-shadow: 0 0 20px rgba(255, 23, 68, 0.3);
}
.au-formula-eq.warn { color: var(--au-warning); }
.au-formula-eq.maint { color: var(--au-gold); text-shadow: 0 0 20px rgba(255, 196, 0, 0.3); }

.au-formula-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--au-border-subtle);
}

.au-formula-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}

.au-formula-dot.live {
  background: var(--au-accent);
  animation: pulseDot 2s ease-in-out infinite;
}
.au-formula-dot.offline { background: var(--au-text-dim); }

.au-formula-note {
  font-size: 10px;
  color: var(--au-text-dim);
  letter-spacing: 0.02em;
}

/* Right Column */
.au-right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Chart */
.au-chart-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.au-chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  gap: 12px;
}

.au-chart-toggle {
  display: inline-flex;
  border: 1px solid var(--au-border);
  border-radius: 4px;
  overflow: hidden;
}

.au-toggle-btn {
  background: transparent;
  border: none;
  color: var(--au-text-dim);
  font-family: var(--au-font);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 4px 10px;
  cursor: pointer;
  transition: all var(--au-transition);
}

.au-toggle-btn:hover { color: var(--au-text-secondary); }

.au-toggle-btn.active {
  background: rgba(0, 200, 83, 0.12);
  color: var(--au-accent);
}

.au-chart-legend {
  display: flex;
  gap: 14px;
  align-items: center;
  margin-left: auto;
}

.au-legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--au-text-dim);
  letter-spacing: 0.02em;
}

.au-legend-dot {
  width: 8px;
  height: 3px;
  border-radius: 1px;
}

.au-legend-dot.frame-a { background: #00c853; }
.au-legend-dot.frame-b { background: #00b0ff; }

.au-chart-count {
  font-size: 10px;
  color: var(--au-text-ghost);
}

.au-chart-wrap {
  flex: 1;
  min-height: 160px;
  position: relative;
}

.au-chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--au-text-dim);
  font-size: 11px;
  letter-spacing: 0.04em;
}

/* Supply Detail */
.au-supply-card { padding: 18px 22px; }

.au-supply-frame-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--au-accent);
  margin-bottom: 10px;
}

.au-supply-frame-label.frame-b-label {
  color: var(--au-accent-b);
}

.au-supply-frame-divider {
  height: 1px;
  background: var(--au-border);
  margin: 14px 0;
}

.au-supply-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.au-supply-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.au-supply-key {
  font-size: 11px;
  color: var(--au-text-dim);
  letter-spacing: 0.02em;
}

.au-supply-truth {
  font-size: 8px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--au-accent);
  background: rgba(0, 200, 83, 0.08);
  border-radius: 2px;
  padding: 1px 4px;
  margin-left: 4px;
}

.au-supply-aux {
  font-size: 8px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--au-text-dim);
  margin-left: 4px;
}

.au-supply-val {
  font-size: 13px;
  color: var(--au-text);
  font-weight: 500;
  letter-spacing: 0.01em;
}

.au-supply-val.matched { color: var(--au-text); }
.au-supply-val.unmatched { color: var(--au-warning); }

/* "i" on Σ Circulating → jumps to the reconciliation detail that explains issued vs circulating */
.au-supply-info {
  margin-left: 7px; width: 14px; height: 14px; flex: none; vertical-align: middle;
  border-radius: 50%; border: 1px solid rgba(0, 200, 83, 0.42); background: rgba(0, 200, 83, 0.08);
  color: var(--au-accent); font-family: Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 700;
  font-size: 10px; line-height: 1; cursor: pointer; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
}
.au-supply-info:hover { background: rgba(0, 200, 83, 0.20); border-color: var(--au-accent); }
.au-supply-info:active { transform: scale(0.9); }
.au-supply-info:focus-visible { outline: 2px solid var(--au-accent); outline-offset: 2px; }
.au-supply-val.dim {
  color: var(--au-text-dim);
  font-size: 11px;
  font-weight: 400;
}

.au-supply-delta.ok { color: var(--au-accent); font-weight: 700; }
.au-supply-delta.danger { color: var(--au-danger); font-weight: 700; }
.au-supply-delta.maint { color: var(--au-gold); font-weight: 700; }

.au-supply-divider {
  height: 1px;
  background: var(--au-border-subtle);
  margin: 4px 0;
}

.au-unit {
  font-size: 9px;
  color: var(--au-text-dim);
  font-weight: 400;
  letter-spacing: 0.08em;
}

.au-supply-empty {
  color: var(--au-text-dim);
  font-size: 11px;
  text-align: center;
  padding: 16px;
}

/* STATS ROW */
.au-stats-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 28px;
  /* §pass75.x: lift the stats-row into its own stacking context ABOVE the log
     section (later in DOM). The MAX LIVE Δ info popover opens downward over the
     log; without this the stat card's :hover transform traps the popover's
     z-index inside the card's context and the log paints over it, leaving the
     popover glitched/peeking below the log. */
  position: relative;
  z-index: 30;
}

.au-stat-card {
  background: var(--au-gradient);
  border: 1px solid var(--au-border);
  border-top: 2px solid var(--au-border);
  border-radius: var(--au-radius);
  padding: 16px 14px 14px;
  text-align: center;
  transition: border-color var(--au-transition), box-shadow var(--au-transition);
}

.au-stat-card:hover {
  border-top-color: var(--au-border-bright);
  box-shadow: var(--au-shadow);
}

.au-stat-card.accent {
  border-top-color: rgba(0, 200, 83, 0.35);
}

.au-stat-number {
  font-size: 22px;
  font-weight: 600;
  color: var(--au-text);
  line-height: 1.2;
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}

.au-stat-number.ok { color: var(--au-accent); }
.au-stat-number.dim {
  color: var(--au-text-secondary);
  font-size: 16px;
}

.au-stat-label { margin-top: 2px; }

/* AUDIT LOG */
.au-log-section { margin-bottom: 24px; }

.au-log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.au-log-count {
  font-size: 10px;
  color: var(--au-text-ghost);
}

.au-log-table-wrap {
  background: var(--au-gradient);
  border: 1px solid var(--au-border);
  border-radius: var(--au-radius-lg);
  max-height: 380px;
  overflow-y: auto;
}

.au-log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.au-log-table thead {
  position: sticky;
  top: 0;
  z-index: 2;
}

.au-log-table th {
  background: var(--au-surface-elevated);
  color: var(--au-text-dim);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  padding: 10px 16px;
  text-align: left;
  border-bottom: 1px solid var(--au-border);
}

.au-log-table th.r { text-align: right; }
.au-log-table th.c { text-align: center; }

.au-log-table td {
  padding: 7px 16px;
  border-bottom: 1px solid rgba(0, 200, 100, 0.03);
  transition: background var(--au-transition);
  font-size: 12px;
}

.au-log-table td.r { text-align: right; }
.au-log-table td.c { text-align: center; }

.au-log-row.alt td { background: rgba(0, 200, 83, 0.012); }
.au-log-row:hover td { background: rgba(0, 200, 83, 0.04); }
.au-log-row.breach-row td { background: rgba(255, 23, 68, 0.03); }
.au-log-row.breach-row:hover td { background: rgba(255, 23, 68, 0.06); }
.au-log-row.maint-row td { background: rgba(255, 196, 0, 0.03); }
.au-log-row.maint-row:hover td { background: rgba(255, 196, 0, 0.06); }

/* Frame badges in log */
.au-frame-badge {
  display: inline-block;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 1px 6px;
  border-radius: 2px;
  min-width: 18px;
  text-align: center;
}

.au-frame-badge.badge-a {
  color: var(--au-accent);
  background: rgba(0, 200, 83, 0.10);
  border: 1px solid rgba(0, 200, 83, 0.15);
}

.au-frame-badge.badge-b {
  color: var(--au-accent-b);
  background: rgba(0, 176, 255, 0.10);
  border: 1px solid rgba(0, 176, 255, 0.15);
}

.au-stale-banner { display: flex; align-items: center; gap: 10px; margin: 0 0 14px; padding: 9px 14px; border: 1px solid rgba(255,207,107,0.45); border-radius: 10px; background: rgba(255,179,0,0.08); color: #ffcf6b; font-size: 12px; }
.au-stale-glyph { font-size: 14px; }
.au-stale-title { font-family: var(--au-mono, monospace); font-weight: 800; letter-spacing: 0.12em; font-size: 11px; }
.au-stale-copy { color: #d9c08a; }
.au-stale-copy b { color: #ffcf6b; }

.au-frame-badge.badge-c {
  color: #ffb300;
  background: rgba(255, 179, 0, 0.10);
  border: 1px solid rgba(255, 179, 0, 0.15);
}

.au-frame-badge.badge-eu {
  color: #7fe9c8;
  background: rgba(127, 233, 200, 0.10);
  border: 1px solid rgba(127, 233, 200, 0.18);
}

.au-frame-badge.badge-asia {
  color: #f87171;
  background: rgba(248, 113, 113, 0.10);
  border: 1px solid rgba(248, 113, 113, 0.18);
}

.au-frame-badge.badge-all {
  color: var(--au-text-secondary);
  background: rgba(143, 191, 163, 0.08);
  border: 1px solid rgba(143, 191, 163, 0.18);
}

/* Status icons */
.au-icon-ok { color: var(--au-accent); font-weight: 700; font-size: 13px; }
.au-icon-breach { color: var(--au-danger); font-weight: 700; font-size: 13px; }
.au-icon-warn { color: var(--au-warning); font-weight: 700; font-size: 13px; }
.au-icon-maint { color: var(--au-gold); font-weight: 700; font-size: 12px; }

/* Latency */
.latency-ok { color: var(--au-text-dim); }
.latency-warn { color: var(--au-warning); }
.latency-bad { color: var(--au-danger); }

.au-log-empty {
  text-align: center;
  color: var(--au-text-dim);
  padding: 32px !important;
  font-size: 11px;
  letter-spacing: 0.04em;
}

/* UTILITY */
.au-mono {
  font-family: var(--au-font);
  font-variant-numeric: tabular-nums;
}

.au-label {
  font-family: var(--au-display);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--au-text-dim);
  line-height: 1;
}

.r { text-align: right; }
.c { text-align: center; }
.dim { color: var(--au-text-dim); }
.ok { color: var(--au-accent); }
.danger { color: var(--au-danger); }
.maint { color: var(--au-gold); }

/* FOOTER */
.au-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 10px;
  color: var(--au-text-dim);
  opacity: 0.35;
  padding-top: 16px;
  border-top: 1px solid var(--au-border-subtle);
  letter-spacing: 0.04em;
}

.au-footer-sep {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--au-text-dim);
  opacity: 0.4;
}

/* ANIMATIONS */
@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.008); }
}

@keyframes ringPulse {
  0% {
    opacity: 0.6;
    transform: translate(-50%, -50%) scale(0.85);
  }
  100% {
    opacity: 0;
    transform: translate(-50%, -50%) scale(1.2);
  }
}

@keyframes scanline {
  0% { top: -1px; }
  100% { top: 100%; }
}

@keyframes pulseDot {
  0%, 100% {
    box-shadow: 0 0 4px var(--au-accent), 0 0 8px rgba(0, 200, 83, 0.2);
  }
  50% {
    box-shadow: 0 0 8px var(--au-accent), 0 0 16px rgba(0, 200, 83, 0.4);
  }
}

/* RESPONSIVE */
@media (max-width: 1100px) {
  .au-main-grid {
    grid-template-columns: 1fr;
  }
  .au-hero-card {
    min-height: 210px;
  }
  .au-stats-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .auditor-root {
    padding: 16px;
  }
  .au-header {
    flex-direction: column;
    gap: 10px;
    align-items: flex-start;
  }
  .au-hero-row {
    grid-template-columns: 1fr;
  }
  .au-hero-value {
    font-size: 44px;
  }
  .au-stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .au-log-table-wrap {
    max-height: 300px;
  }
}

@media (max-width: 480px) {
  .au-stats-row {
    grid-template-columns: 1fr;
  }
}

/* ──────────────────────────────────────────────────────────── */
/* INFO (i) BUTTON ON MAX DELTA + POPOVER                      */
/* ──────────────────────────────────────────────────────────── */
.au-stat-card-info {
  position: relative;
}

.au-info-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid var(--au-border-bright);
  background: rgba(0, 200, 83, 0.06);
  color: var(--au-accent);
  font-family: var(--au-font);
  font-size: 10px;
  font-weight: 700;
  font-style: italic;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--au-transition);
  z-index: 2;
}

.au-info-btn:hover {
  background: rgba(0, 200, 83, 0.14);
  border-color: var(--au-accent-dim);
  box-shadow: 0 0 6px rgba(0, 200, 83, 0.25);
  transform: scale(1.08);
}

.au-info-btn:focus-visible {
  outline: 1px solid var(--au-accent);
  outline-offset: 1px;
}

.au-info-popover {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  min-width: 320px;
  max-width: 400px;
  background: var(--au-surface-elevated);
  border: 1px solid var(--au-border-bright);
  border-radius: var(--au-radius-lg);
  box-shadow: var(--au-shadow-lg), 0 0 24px rgba(0, 200, 83, 0.08);
  padding: 0;
  z-index: 100;
  text-align: left;
  animation: popoverIn 160ms ease-out;
}

.au-info-popover::before {
  content: '';
  position: absolute;
  top: -5px;
  right: 14px;
  width: 8px;
  height: 8px;
  background: var(--au-surface-elevated);
  border-top: 1px solid var(--au-border-bright);
  border-left: 1px solid var(--au-border-bright);
  transform: rotate(45deg);
}

.au-info-popover-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--au-border);
  background: linear-gradient(90deg, rgba(0, 200, 83, 0.06) 0%, transparent 100%);
}

.au-info-popover-title {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--au-accent);
  text-transform: uppercase;
  font-weight: 700;
}

.au-info-popover-close {
  background: none;
  border: none;
  color: var(--au-text-dim);
  font-family: var(--au-font);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 2px;
  transition: all var(--au-transition);
}

.au-info-popover-close:hover {
  color: var(--au-text);
  background: rgba(0, 200, 83, 0.08);
}

.au-info-popover-body {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

/* §pass75.x: read-skew explainer at the top of the MAX LIVE Δ popover — clarifies
   the headline live-read peak (read-skew) vs the worst real (atomic) breach below. */
.au-info-note {
  font-size: 11px;
  line-height: 1.5;
  color: var(--au-text-dim);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--au-border);
}
.au-info-note em { font-style: normal; color: var(--au-accent); }

.au-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 11px;
}

.au-info-key {
  color: var(--au-text-dim);
  letter-spacing: 0.02em;
  flex-shrink: 0;
  text-transform: uppercase;
  font-size: 10px;
}

.au-info-val {
  color: var(--au-text);
  text-align: right;
  font-size: 11px;
}

.au-info-val.danger { color: var(--au-danger); }
.au-info-val.ok { color: var(--au-accent); }

.au-info-popover-footer {
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid var(--au-border);
}

.au-info-link {
  display: inline-block;
  color: var(--au-accent);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px dashed rgba(0, 200, 83, 0.4);
  padding-bottom: 1px;
  transition: all var(--au-transition);
}

.au-info-link:hover {
  color: #6dffa0;
  border-bottom-color: var(--au-accent);
}

@keyframes popoverIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ──────────────────────────────────────────────────────────── */
/* PATCH NOTES & INCIDENT LOG (collapsible section)            */
/* ──────────────────────────────────────────────────────────── */
.au-incidents-section {
  margin-top: 20px;
  margin-bottom: 24px;
  border: 1px solid var(--au-border);
  border-radius: var(--au-radius-lg);
  background: var(--au-gradient);
  overflow: hidden;
}

.au-incidents-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: transparent;
  border: none;
  color: var(--au-text);
  font-family: var(--au-font);
  cursor: pointer;
  text-align: left;
  transition: background var(--au-transition);
}

.au-incidents-toggle:hover {
  background: rgba(0, 200, 83, 0.04);
}

.au-incidents-toggle:focus-visible {
  outline: 1px solid var(--au-accent);
  outline-offset: -1px;
}

.au-incidents-chevron {
  color: var(--au-accent);
  font-size: 11px;
  width: 12px;
  display: inline-block;
  transition: transform var(--au-transition);
}

.au-incidents-toggle .au-label {
  font-size: 11px;
  color: var(--au-text);
  letter-spacing: 0.14em;
}

.au-incidents-count {
  font-size: 10px;
  color: var(--au-accent-dim);
  padding: 2px 8px;
  border: 1px solid var(--au-border-bright);
  border-radius: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.au-incidents-note {
  margin-left: auto;
  font-size: 10px;
  color: var(--au-text-dim);
  letter-spacing: 0.04em;
  font-style: italic;
}

.au-incidents-body {
  border-top: 1px solid var(--au-border);
  padding: 14px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  animation: incidentsIn 220ms ease-out;
}

@keyframes incidentsIn {
  from {
    opacity: 0;
    max-height: 0;
  }
  to {
    opacity: 1;
    max-height: 2000px;
  }
}

.au-incident-card {
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-left: 2px solid var(--au-accent);
  border-radius: var(--au-radius);
  padding: 12px 14px;
  position: relative;
  transition: all var(--au-transition);
}

.au-incident-card:hover {
  border-color: var(--au-border-bright);
  border-left-color: var(--au-accent);
  background: var(--au-card-hover);
}

.au-incident-card.kind-upgrade { border-left-color: var(--au-accent-b); }
.au-incident-card.kind-maintenance { border-left-color: var(--au-gold); }

.au-incident-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-size: 10px;
}

.au-incident-date {
  color: var(--au-text-dim);
  letter-spacing: 0.04em;
}

.au-incident-delta {
  color: var(--au-danger);
  font-weight: 600;
  padding: 2px 6px;
  background: rgba(255, 23, 68, 0.06);
  border: 1px solid rgba(255, 23, 68, 0.15);
  border-radius: 2px;
}

.au-incident-status {
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 2px;
  letter-spacing: 0.04em;
}

.au-incident-status.ok {
  color: var(--au-accent);
  background: rgba(0, 200, 83, 0.06);
  border: 1px solid rgba(0, 200, 83, 0.15);
}

.au-incident-status.tone-upgrade {
  color: var(--au-accent-b);
  background: rgba(0, 176, 255, 0.06);
  border: 1px solid rgba(0, 176, 255, 0.15);
}

.au-incident-status.tone-progress {
  color: var(--au-gold);
  background: rgba(255, 196, 0, 0.06);
  border: 1px solid rgba(255, 196, 0, 0.18);
}

.au-incident-ref {
  margin-left: auto;
  font-size: 9px;
  letter-spacing: 0.04em;
}

.au-incident-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--au-text);
  margin-bottom: 6px;
  letter-spacing: 0.01em;
}

.au-incident-cause {
  font-size: 11px;
  color: var(--au-text-secondary);
  margin-bottom: 8px;
}

.au-incident-cause-key {
  color: var(--au-text-dim);
  text-transform: uppercase;
  font-size: 9px;
  letter-spacing: 0.08em;
  margin-right: 4px;
}

.au-incident-desc {
  font-size: 11px;
  color: var(--au-text-secondary);
  line-height: 1.6;
  padding-top: 8px;
  border-top: 1px dashed var(--au-border);
}

@media (max-width: 768px) {
  .au-info-popover {
    min-width: 260px;
    max-width: calc(100vw - 40px);
    right: -8px;
  }
  .au-incidents-note {
    display: none;
  }
  .au-incident-meta {
    font-size: 9px;
  }
  .au-chart-legend { display: none; }
}

/* ──────────────────────────────────────────────────────────── */
/* PASS D — stat icons + chart telemetry pill                   */
/* ──────────────────────────────────────────────────────────── */
.au-stat-ic {
  position: absolute;
  top: 11px;
  left: 12px;
  width: 14px;
  height: 14px;
  color: var(--au-text-dim);
  opacity: 0.5;
  transition: color var(--au-transition), opacity var(--au-transition);
}
.au-stat-ic :deep(svg) { width: 14px; height: 14px; display: block; }
.au-stat-card.accent .au-stat-ic { color: var(--au-accent); opacity: 0.72; }
.au-stat-card:hover .au-stat-ic { color: var(--au-accent); opacity: 0.95; }

.au-chart-live {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--au-display);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.14em;
  padding: 2px 7px;
  border-radius: 999px;
  border: 1px solid var(--au-border);
  color: var(--au-text-dim);
}
.au-chart-live-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--au-text-dim); flex-shrink: 0; }
.au-chart-live.on { color: var(--au-accent); border-color: rgba(0, 200, 83, 0.25); }
.au-chart-live.on .au-chart-live-dot { background: var(--au-accent); box-shadow: 0 0 6px var(--au-accent); animation: pulseDot 2s ease-in-out infinite; }
.au-chart-live.off { color: var(--au-danger); border-color: rgba(255, 23, 68, 0.25); }
.au-chart-live.off .au-chart-live-dot { background: var(--au-danger); }

/* ──────────────────────────────────────────────────────────── */
/* PASS C — materiality (bezel, chips, glass, proof stamp)      */
/* ──────────────────────────────────────────────────────────── */
/* Glass sheen — a faint top highlight gives the panels material depth */
.au-hero-card, .au-formula-card, .au-chart-card, .au-supply-card {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.020), transparent 42%),
    var(--au-gradient);
}

/* Precision tick bezel just inside the seal ring */
.au-hero-seal::after {
  content: '';
  position: absolute;
  inset: 2px;
  border-radius: 50%;
  background: repeating-conic-gradient(from 0deg, rgba(0, 200, 83, 0.20) 0deg 0.7deg, transparent 0.7deg 12deg);
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 4px), #000 calc(100% - 4px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 4px), #000 calc(100% - 4px));
  pointer-events: none;
}
.frame-b-card .au-hero-seal::after { background: repeating-conic-gradient(from 0deg, rgba(0, 176, 255, 0.20) 0deg 0.7deg, transparent 0.7deg 12deg); }
.au-hero-seal.danger::after { background: repeating-conic-gradient(from 0deg, rgba(255, 23, 68, 0.24) 0deg 0.7deg, transparent 0.7deg 12deg); }
.au-hero-seal.maint::after { background: repeating-conic-gradient(from 0deg, rgba(255, 196, 0, 0.22) 0deg 0.7deg, transparent 0.7deg 12deg); }

/* Frame label → channel chip */
.au-frame-label {
  display: inline-block;
  padding: 2px 10px;
  margin-bottom: 9px;
  border: 1px solid rgba(0, 200, 83, 0.18);
  border-radius: 999px;
  background: rgba(0, 200, 83, 0.05);
  font-family: var(--au-display);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.22em;
  opacity: 0.9;
}
.frame-b-card .au-frame-label,
.au-frame-label.frame-b-label {
  border-color: rgba(0, 176, 255, 0.18);
  background: rgba(0, 176, 255, 0.05);
}

/* Formula → proof panel */
.au-formula-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.au-formula-head .au-formula-label { margin-bottom: 0; }
.au-formula-stamp {
  font-family: var(--au-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 2px 9px;
  border-radius: 3px;
  white-space: nowrap;
  color: var(--au-accent);
  background: rgba(0, 200, 83, 0.08);
  border: 1px solid rgba(0, 200, 83, 0.20);
  transition: all var(--au-transition-slow);
}
.au-formula-stamp.alarm-contained { color: var(--au-gold); background: rgba(255, 196, 0, 0.08); border-color: rgba(255, 196, 0, 0.24); }
.au-formula-stamp.alarm-critical { color: var(--au-danger); background: rgba(255, 23, 68, 0.08); border-color: rgba(255, 23, 68, 0.30); }

/* ──────────────────────────────────────────────────────────── */
/* BREACH ALARM CHOREOGRAPHY (none → contained → critical)      */
/* ──────────────────────────────────────────────────────────── */
.au-brandmark { display: inline-flex; flex-shrink: 0; }

/* Critical veil — the whole observatory flushes red at the edges */
.au-alarm-veil {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 3;
  background: radial-gradient(130% 110% at 50% 42%, transparent 50%, rgba(255, 23, 68, 0.17) 100%);
  mix-blend-mode: screen;
  animation: alarmVeil 1.5s ease-in-out infinite;
}
@keyframes alarmVeil { 0%, 100% { opacity: 0.38; } 50% { opacity: 1; } }

.au-alarm-bar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 11px 18px;
  margin-bottom: 18px;
  border-radius: var(--au-radius-lg);
  overflow: hidden;
  font-family: var(--au-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.au-alarm-bar.au-public-breach-bar {
  background: rgba(255, 196, 0, 0.07);
  border-color: rgba(255, 196, 0, 0.35);
  color: var(--au-gold, #ffc400);
}
.au-alarm-bar.critical {
  color: #ffd9df;
  background: linear-gradient(90deg, rgba(255, 23, 68, 0.16), rgba(255, 23, 68, 0.05));
  border: 1px solid rgba(255, 23, 68, 0.40);
  animation: alarmBarPulse 1.3s ease-in-out infinite;
}
.au-alarm-bar.contained {
  color: #ffe89e;
  background: linear-gradient(90deg, rgba(255, 196, 0, 0.12), rgba(255, 196, 0, 0.04));
  border: 1px solid rgba(255, 196, 0, 0.32);
  box-shadow: 0 0 20px rgba(255, 196, 0, 0.08);
}
@keyframes alarmBarPulse {
  0%, 100% { box-shadow: 0 0 22px rgba(255, 23, 68, 0.14), inset 0 0 14px rgba(255, 23, 68, 0.05); border-color: rgba(255, 23, 68, 0.34); }
  50% { box-shadow: 0 0 42px rgba(255, 23, 68, 0.34), inset 0 0 24px rgba(255, 23, 68, 0.10); border-color: rgba(255, 23, 68, 0.62); }
}
.au-alarm-bar.critical::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 80, 110, 0.18), transparent);
  transform: translateX(-100%);
  animation: alarmSweep 2.2s linear infinite;
  pointer-events: none;
}
@keyframes alarmSweep { to { transform: translateX(100%); } }

.au-alarm-klaxon { font-size: 16px; animation: klaxonFlash 0.85s steps(1, end) infinite; }
.au-alarm-bar.contained .au-alarm-klaxon { animation: none; opacity: 0.9; }
@keyframes klaxonFlash { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0.32; } }

.au-alarm-title { white-space: nowrap; }
.au-alarm-frames { display: flex; gap: 14px; flex-wrap: wrap; }
.au-alarm-frame { font-weight: 600; letter-spacing: 0.04em; opacity: 0.95; }
.au-alarm-delta { font-family: var(--au-font); font-weight: 700; }
.au-alarm-spacer { flex: 1; }
.au-alarm-status {
  font-size: 9px;
  letter-spacing: 0.16em;
  opacity: 0.82;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid currentColor;
  white-space: nowrap;
}

/* Crest alarm states */
.au-conserve-crest.alarm-critical {
  border-color: rgba(255, 23, 68, 0.40);
  color: var(--au-danger);
  box-shadow: 0 0 24px rgba(255, 23, 68, 0.12);
  animation: alarmBarPulse 1.3s ease-in-out infinite;
}
.au-conserve-crest.alarm-critical .au-crest-glyph { color: var(--au-danger); animation: klaxonFlash 0.85s steps(1, end) infinite; }
.au-conserve-crest.alarm-contained { border-color: rgba(255, 196, 0, 0.30); color: var(--au-gold); }
.au-conserve-crest.alarm-contained .au-crest-glyph { color: var(--au-gold); }

/* Critical hero figure: danger flicker + micro-jitter */
.alarm-critical .au-hero-value.danger { animation: dangerFlicker 1.4s ease-in-out infinite; }
@keyframes dangerFlicker {
  0%, 100% { opacity: 1; text-shadow: var(--au-glow-danger); }
  49% { opacity: 0.95; }
  50% { opacity: 0.68; text-shadow: 0 0 70px rgba(255, 23, 68, 0.6), 0 0 6px rgba(255, 255, 255, 0.5); transform: translateX(0.6px); }
  52% { opacity: 0.96; transform: translateX(-0.6px); }
}

@media (prefers-reduced-motion: reduce) {
  .au-alarm-veil, .au-alarm-bar.critical, .au-alarm-bar.critical::after, .au-alarm-klaxon,
  .au-conserve-crest.alarm-critical, .au-conserve-crest.alarm-critical .au-crest-glyph,
  .alarm-critical .au-hero-value.danger { animation: none !important; }
}

/* ──────────────────────────────────────────────────────────── */
/* PASS 5 — cohesion, signature, responsive polish              */
/* ──────────────────────────────────────────────────────────── */
.au-footer-glyph { color: var(--au-accent); opacity: 0.55; font-size: 9px; }
.au-footer { opacity: 0.42; }

@media (max-width: 768px) {
  .au-title { letter-spacing: 0.18em; font-size: 13px; }
  .au-header-right { flex-wrap: wrap; row-gap: 6px; justify-content: flex-start; }
  .au-conserve-crest { flex-wrap: wrap; gap: 6px 10px; }
}

/* ──────────────────────────────────────────────────────────── */
/* PASS 4 — instrument details (sparkline, stat cards, log)     */
/* ──────────────────────────────────────────────────────────── */
.au-supply-spark-row { align-items: center; }
.au-supply-spark { display: inline-flex; align-items: center; opacity: 0.92; }
.au-supply-spark :deep(svg) { display: block; }

.au-stat-card {
  position: relative;
  transition: transform var(--au-transition), border-color var(--au-transition), box-shadow var(--au-transition);
}
.au-stat-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(0, 200, 83, 0.5), transparent);
  opacity: 0;
  transition: opacity var(--au-transition);
  pointer-events: none;
}
.au-stat-card:hover { transform: translateY(-2px); }
.au-stat-card:hover::after { opacity: 1; }
.au-stat-card.accent::after { opacity: 0.55; }

/* Newest audit-log row — live left-accent + one-shot reveal */
.au-log-row.au-log-fresh td:first-child { box-shadow: inset 2px 0 0 var(--au-accent); }
.au-log-row.au-log-fresh td { animation: freshRow 1.2s ease-out; }
@keyframes freshRow {
  0% { background: rgba(0, 200, 83, 0.10); }
  100% { background: transparent; }
}

@media (prefers-reduced-motion: reduce) {
  .au-stat-card:hover { transform: none; }
  .au-log-row.au-log-fresh td { animation: none !important; }
}

/* ──────────────────────────────────────────────────────────── */
/* PASS 2 — conservation crest + invariant radar seal           */
/* ──────────────────────────────────────────────────────────── */
.au-conserve-crest {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 7px 16px;
  border: 1px solid var(--au-border);
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(0, 200, 83, 0.04), transparent);
  font-family: var(--au-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--au-text-dim);
  transition: color var(--au-transition-slow), border-color var(--au-transition-slow), box-shadow var(--au-transition-slow);
}
.au-conserve-crest.live {
  border-color: rgba(0, 200, 83, 0.22);
  color: var(--au-accent);
  box-shadow: 0 0 26px rgba(0, 200, 83, 0.07), inset 0 0 18px rgba(0, 200, 83, 0.03);
}
.au-crest-glyph { color: var(--au-text-dim); font-size: 11px; transition: color var(--au-transition-slow); }
.au-conserve-crest.live .au-crest-glyph { color: var(--au-accent); animation: iconBeat 3.5s ease-in-out infinite; }
.au-crest-sep { width: 1px; height: 11px; background: var(--au-border); }
.au-crest-meta { color: var(--au-text-ghost); font-size: 9px; letter-spacing: 0.12em; font-family: var(--au-font); }

/* Radar-sweep conservation seal behind the invariant figure */
.au-hero-seal {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 176px;
  height: 176px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  border: 1px solid rgba(0, 200, 83, 0.10);
  box-shadow: inset 0 0 28px rgba(0, 200, 83, 0.045);
}
.au-hero-seal::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 0 72%, rgba(0, 200, 83, 0.5) 90%, transparent 100%);
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 2px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 2px));
  animation: sealSweep 6s linear infinite;
}
@keyframes sealSweep { to { transform: rotate(360deg); } }

.frame-b-card .au-hero-seal {
  border-color: rgba(0, 176, 255, 0.10);
  box-shadow: inset 0 0 28px rgba(0, 176, 255, 0.045);
}
.frame-b-card .au-hero-seal::before {
  background: conic-gradient(from 0deg, transparent 0 72%, rgba(0, 176, 255, 0.5) 90%, transparent 100%);
}
.au-hero-seal.danger { border-color: rgba(255, 23, 68, 0.18); }
.au-hero-seal.danger::before {
  background: conic-gradient(from 0deg, transparent 0 62%, rgba(255, 23, 68, 0.6) 86%, transparent 100%);
  animation-duration: 2.4s;
}
.au-hero-seal.maint { border-color: rgba(255, 196, 0, 0.16); }
.au-hero-seal.maint::before {
  background: conic-gradient(from 0deg, transparent 0 72%, rgba(255, 196, 0, 0.5) 90%, transparent 100%);
}

@media (prefers-reduced-motion: reduce) {
  .au-hero-seal::before, .au-formula-eq.ok, .au-conserve-crest.live .au-crest-glyph { animation: none !important; }
}

/* ──────────────────────────────────────────────────────────── */
/* PASS 1 — staggered entrance + motion accessibility           */
/* ──────────────────────────────────────────────────────────── */
@keyframes auRise {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: none; }
}

.au-header              { animation: auRise 0.5s ease both; }
.au-maint-banner        { animation: auRise 0.5s ease both 0.05s; }
.au-main-grid           { animation: auRise 0.6s cubic-bezier(0.2, 0.7, 0.2, 1) both 0.10s; }
.au-stats-row           { animation: auRise 0.6s cubic-bezier(0.2, 0.7, 0.2, 1) both 0.18s; }
.au-log-section         { animation: auRise 0.6s cubic-bezier(0.2, 0.7, 0.2, 1) both 0.26s; }
.au-incidents-section   { animation: auRise 0.6s cubic-bezier(0.2, 0.7, 0.2, 1) both 0.32s; }
.au-footer              { animation: auRise 0.6s ease both 0.40s; }

@media (prefers-reduced-motion: reduce) {
  .au-header, .au-maint-banner, .au-main-grid, .au-stats-row,
  .au-log-section, .au-incidents-section, .au-footer { animation: none !important; }
  .au-hero-card, .au-hero-scanline, .au-hero-ring, .au-maint-stripe,
  .au-icon, .au-live-dot, .au-formula-dot { animation: none !important; }
}
</style>
