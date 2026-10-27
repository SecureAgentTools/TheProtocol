<template>
  <div class="cm-page hm-module">
    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <header class="cm-header" data-tour="compliance-hero">
      <div class="cm-header-left">
        <div>
          <h1 class="cm-title">{{ t('complianceMonitorView.title') }}</h1>
          <div class="cm-subtitle">{{ t('complianceMonitorView.subtitle') }}</div>
        </div>
      </div>

      <div class="cm-header-kpis" v-if="store.overview">
        <div class="cm-kpi">
          <div class="cm-kpi-num">{{ store.overview.peers_total }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.targets') }}</div>
        </div>
        <div class="cm-kpi cm-kpi-ok">
          <div class="cm-kpi-num">{{ store.overview.peers_federated }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.federated') }}</div>
        </div>
        <div class="cm-kpi cm-kpi-warn">
          <div class="cm-kpi-num">{{ store.overview.peers_quarantined }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.quarantined') }}</div>
        </div>
        <div class="cm-kpi cm-kpi-bad">
          <div class="cm-kpi-num">{{ store.overview.peers_blacklisted }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.blacklisted') }}</div>
        </div>
        <div class="cm-kpi" :class="unidentifiedCount > 0 ? 'cm-kpi-bad' : 'cm-kpi-ok'">
          <div class="cm-kpi-num">{{ unidentifiedCount }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.unidentified', 'Unidentified') }}</div>
        </div>
        <div class="cm-kpi" v-if="reach" :class="reachKpiClass">
          <div class="cm-kpi-num">{{ reach.reachable }}/{{ reach.peers_active }}</div>
          <div class="cm-kpi-label">Corridors reachable</div>
        </div>
        <div class="cm-kpi" v-if="avgComplianceScore != null">
          <div class="cm-kpi-num">{{ avgComplianceScore }}</div>
          <div class="cm-kpi-label">{{ t('complianceMonitorView.kpis.avgScore', 'Avg score') }}</div>
        </div>
      </div>

      <div class="cm-header-actions">
        <!-- §FEDCLOCK (2026-09-09), his report: /federation has carried this readout since the
             2026-05 T1 audit and this page never had one — so its counters could be arbitrarily
             old with nothing on screen to say so. Same composable, same strings, same 60s cycle. -->
        <div v-if="live.lastFetchedAt.value" class="cm-refresh-meta" aria-live="polite">
          <span class="cm-refresh-meta-label">Refreshed</span>
          <span class="cm-refresh-meta-value">{{ live.lastRefreshedLabel.value }}</span>
          <template v-if="!live.paused.value">
            <span class="cm-refresh-meta-sep">·</span>
            <span class="cm-refresh-meta-label">Next</span>
            <span class="cm-refresh-meta-value">{{ live.nextRefreshInSeconds.value }}s</span>
          </template>
          <!-- a paused clock that still counted down would be lying about what happens next -->
          <span v-else class="cm-refresh-meta-paused" title="Polling is suspended while this tab is in the background">paused</span>
        </div>
        <button class="cm-btn-ghost" @click="refresh" :disabled="store.loading">
          {{ store.loading ? '…' : 'Refresh' }}
        </button>
        <button class="cm-btn-accent" @click="runSimulator" :disabled="store.loadingPreview">
          {{ store.loadingPreview ? 'Simulating…' : 'Preview' }}
        </button>
      </div>
    </header>

    <!-- ── Error banner ───────────────────────────────────────────────── -->
    <div v-if="store.error" class="cm-error">{{ store.error }}</div>

    <!-- ── Enforcement mode (compact single-row segmented) ────────────── -->
    <CMEnforcementToggle
      :mode-state="store.modeState"
      :busy="modeBusy"
      @change="onModeChange"
    />
    <!-- §MCPTEST30 (V0562): how fresh the rows below are. The overview carried both facts and nothing showed them. -->
    <p v-if="store.overview" class="cm-dim cm-poller-line" data-testid="cm-poller">
      <template v-if="store.overview.poller_enabled">
        {{ tp('complianceMonitorView.poller.on', 'The compliance poller reads every active peer every {hours} h; first sight records a baseline.', { hours: Math.round((store.overview.poll_interval_seconds || 0) / 3600 * 10) / 10 }) }}
      </template>
      <template v-else>
        {{ t('complianceMonitorView.poller.off', 'This registry runs no compliance poller (it is not the central registry): the rows below are not re-read here.') }}
      </template>
    </p>

    <!-- ── Preview simulator result ───────────────────────────────────── -->
    <!-- ── Degradation coverage (2026-07-26) ────────────────────────────
         Δ, /health and the stuck-state SLOs all answer "is it broken". On 2026-07-26 a
         five-hour DNS degradation moved none of them, and all three were RIGHT: money was
         safe, services were up, nothing was stuck. The signal was 80-100 WARNING log lines
         a minute, which nothing measured. This panel asks the other question. -->
    <section class="cm-section cm-degradation" v-if="degradation">
      <div class="cm-section-head">
        <h3>
          <Icon name="mdi:chart-line-variant" class="cm-deg-ico" />
          Degradation signals
          <span class="cm-reach-sub">
            green here is not the same as healthy elsewhere &mdash; these catch
            &ldquo;working, but worse, and retrying&rdquo;
          </span>
        </h3>
      </div>

      <div class="cm-deg-grid">
        <div
          v-for="s in degradationCards"
          :key="s.key"
          class="cm-deg-card"
          :class="{ 'is-breach': s.breaching, 'is-unknown': !s.readable }"
        >
          <div class="cm-deg-val">
            <template v-if="s.readable">{{ s.value }}</template>
            <template v-else>&mdash;</template>
            <span class="cm-deg-unit">{{ s.unit }}</span>
          </div>
          <div class="cm-deg-label">{{ s.label }}</div>
          <div class="cm-deg-meta">
            <!-- §DEGREASON (2026-09-09) — four words could not tell four failures apart. On EU
                 and ASIA every one of these read "metric unreadable" from the day the page
                 existed, because the store's hostname resolves only on Frame A's network — and
                 nothing on screen could say so. The reason is the server's, not ours. -->
            <span v-if="!s.readable" class="cm-deg-warn">
              {{ degReasonLabel(s.reason) }}
            </span>
            <span v-else-if="s.breaching" class="cm-deg-warn">over {{ s.threshold }}</span>
            <span v-else class="cm-deg-ok">under {{ s.threshold }}</span>
            <code class="cm-deg-alert">{{ s.alert }}</code>
          </div>
        </div>
      </div>

      <div class="cm-deg-cats" v-if="degradation.by_category && degradation.by_category.length">
        <span class="cm-dim">WARNING+ per minute by category:</span>
        <span v-for="c in degradation.by_category" :key="c.category" class="cm-deg-chip">
          {{ c.category }} <b>{{ c.per_min }}</b>
        </span>
      </div>
      <p class="cm-dim cm-deg-note" v-if="degradation.any_unreadable">
        <template v-if="degradation.metrics_configured === false">
          No metrics backend is configured for this frame (<code>VICTORIA_METRICS_URL</code>), so
          these signals cannot be read here. That is a posture, not an outage &mdash; and it is not
          the same as zero.
        </template>
        <template v-else>
          At least one signal could not be read from the metrics store<template
            v-if="degradation.unreadable_reason"> (<code>{{ degradation.unreadable_reason }}</code>)</template>.
          Unreadable is shown as &mdash;, never as zero &mdash; an absent metric must not look like
          a healthy one.
        </template>
      </p>
    </section>
    <!-- §FESUITE V0577: a failed read hid the panel as if this page had no such question; it says the read failed -->
    <section v-if="!degradation && degradationFailed" class="cm-section cm-degradation" data-testid="cm-degradation-unread">
      <div class="cm-section-head"><h3><Icon name="mdi:chart-line-variant" class="cm-deg-ico" /> Degradation signals</h3></div>
      <ReadFailedNotice dense :retry="loadDegradation" />
    </section>

    <!-- ── Federation reachability (2026-07-24) ─────────────────────────
         A peer is not healthy because it exists and was never marked bad; it is
         healthy because it ANSWERED RECENTLY. frame-c federated with 6 of 16 peers
         for seven weeks because nothing on any screen asked that question. -->
    <section class="cm-section cm-reach" v-if="reach">
      <div class="cm-section-head">
        <h3>
          Federation corridors
          <span class="cm-reach-sub">{{ reach.reachable }} of {{ reach.peers_active }} answering
            (window {{ reach.window.stale_hours }}h)</span>
        </h3>
        <button class="cm-btn cm-btn-ghost" @click="showAllCorridors = !showAllCorridors">
          {{ showAllCorridors ? 'Show only findings' : 'Show all peers' }}
        </button>
      </div>

      <div class="cm-reach-bar" :title="reach.definition">
        <div class="cm-reach-fill" :style="{ width: ((reach.reachable_ratio ?? 0) * 100) + '%' }"
             :class="reachKpiClass"></div>
      </div>

      <p v-if="!reach.findings.length" class="cm-reach-clean">
        Every active peer answered within the window.
      </p>

      <table v-else class="cm-table cm-reach-table">
        <thead>
          <tr>
            <th>Peer</th><th>State</th><th>Last answered</th>
            <th>Diagnosis</th><th>What to do</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in corridorRows" :key="p.peer" :class="'cm-reach-' + p.severity">
            <td>
              <span class="cm-reach-peer">{{ p.peer }}</span>
              <span v-if="p.trust_domain" class="cm-reach-td">{{ p.trust_domain }}</span>
            </td>
            <td><span class="cm-reach-state" :class="'cm-reach-state-' + p.severity">{{ p.state }}</span></td>
            <td>
              <span v-if="p.last_sync_age_seconds != null">{{ humanAge(p.last_sync_age_seconds) }} ago</span>
              <span v-else class="cm-reach-never">
                never<span v-if="p.age_days_since_registration != null"> · registered {{ p.age_days_since_registration }}d ago</span>
              </span>
            </td>
            <td>
              <span v-if="p.diagnosis" class="cm-reach-diag">{{ p.diagnosis }}</span>
              <span v-else class="cm-reach-muted">—</span>
              <div v-if="p.last_sync_error" class="cm-reach-err" :title="p.last_sync_error">
                {{ p.last_sync_error.slice(0, 90) }}
              </div>
            </td>
            <td class="cm-reach-remedy">{{ p.remedy || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- §TRUSTPOLICY (2026-09-11) — PEER TRUST BELONGS HERE, beside the corridors and the
         quarantine preview, because this page already answers "what do we think of our peers and
         what are we doing about it". It was the one rail with no surface: the endpoint existed and
         nothing read it. -->
    <section v-if="!peerTrust && peerTrustFailed" class="cm-section cm-trust" data-testid="cm-peer-trust-unread">
      <div class="cm-section-head"><h3>Peer trust</h3></div>
      <ReadFailedNotice dense :retry="loadPeerTrust" />
    </section>
    <section class="cm-section cm-trust" v-if="peerTrust" data-testid="cm-peer-trust">
      <div class="cm-section-head">
        <h3>
          Peer trust
          <span class="cm-reach-sub">
            {{ trustActing }} of {{ peerTrust.peers.length }} being acted on ·
            mode {{ peerTrust.posture.mode }}
          </span>
        </h3>
        <button class="cm-btn cm-btn-ghost" @click="showAllTrust = !showAllTrust">
          {{ showAllTrust ? 'Show only findings' : 'Show all peers' }}
        </button>
      </div>

      <!-- The posture, in the same words the card publishes. A reader who sees "restricted"
           without seeing the mode would reasonably conclude the peer had already lost something. -->
      <p class="cm-trust-posture">
        Below <strong>{{ peerTrust.posture.warn_below }}</strong> watch ·
        below <strong>{{ peerTrust.posture.restrict_below }}</strong> restrict ·
        below <strong>{{ peerTrust.posture.suspend_below }}</strong> suspend ·
        never below <strong>{{ peerTrust.posture.min_interactions }}</strong> settled interactions.
        <span v-if="peerTrust.posture.mode !== 'enforce'" class="cm-trust-observe">
          This frame is OBSERVING: every peer is judged and nothing is withheld.
        </span>
        <span v-else class="cm-trust-enforce">This frame is ENFORCING.</span>
      </p>

      <!-- ⚠ A FILTER THAT REMOVES EVERYTHING IS INDISTINGUISHABLE FROM AN OUTAGE. Found by
           reading the screenshot taken for the blog post: on a healthy frame every peer is `ok`
           or `unmeasured`, so "findings only" left a table of headers and no rows, which looks
           exactly like a panel that failed to load. Name the withheld count and carry the switch
           that lifts it, the way the corridors section above says "every active peer answered". -->
      <p v-if="!trustRows.length" class="cm-reach-clean">
        No peer is below any threshold this frame sets.
        <template v-if="trustHidden">
          {{ trustHidden }} peer<template v-if="trustHidden !== 1">s</template> not shown
          ({{ peerTrust.by_state.ok || 0 }} trusted,
          {{ peerTrust.by_state.unmeasured || 0 }} unmeasured) ·
          <button class="cm-link" @click="showAllTrust = true">show them</button>
        </template>
      </p>

      <table v-else class="cm-table cm-reach-table">
        <thead>
          <tr><th>Peer</th><th>State</th><th>Evidence</th><th>Why</th><th>Effect</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in trustRows" :key="p.id">
            <td>
              <span class="cm-reach-peer">{{ p.name }}</span>
              <span class="cm-reach-td">{{ p.peer_type }}</span>
            </td>
            <td>
              <span class="cm-reach-state" :class="'cm-trust-' + p.state">{{ p.state }}</span>
            </td>
            <!-- the COUNT is what separates "unmeasured" from "distrusted"; it is never omitted -->
            <td>
              {{ p.total_interactions }} settled<template v-if="p.disputes_lost_with">,
                {{ p.disputes_lost_with }} disputed</template>
              <div v-if="p.bayesian_discount != null && p.total_interactions" class="cm-reach-td">
                {{ Math.round(p.bayesian_discount * 100) }}%
              </div>
            </td>
            <td class="cm-reach-diag">{{ p.reason }}</td>
            <td class="cm-reach-remedy">
              <span v-if="p.enforced" class="cm-trust-acting">withholding federated cards</span>
              <span v-else-if="p.state === 'unmeasured'" class="cm-reach-muted">nothing — not enough evidence to judge</span>
              <span v-else-if="p.state === 'ok'" class="cm-reach-muted">nothing</span>
              <span v-else class="cm-reach-muted">nothing yet — would withhold under enforce</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="cm-reach-clean">{{ peerTrust.note }}</p>
    </section>

    <section class="cm-section cm-preview" v-if="store.preview">
      <div class="cm-section-head">
        <div>
          <h3>Preview · what would quarantine right now?</h3>
          <p class="cm-dim">
            Generated {{ timeAgo(store.preview.generated_at) }} · mode at check
            <code>{{ store.preview.mode_at_check }}</code>
          </p>
        </div>
        <div class="cm-preview-counts">
          <span class="cm-pc cm-pc-bad">{{ store.preview.would_quarantine_count }} would quarantine</span>
          <span class="cm-pc cm-pc-ok">{{ store.preview.would_noop_count }} no-op</span>
          <span class="cm-pc cm-pc-dim">{{ store.preview.skipped_count }} skipped</span>
        </div>
      </div>
      <table class="cm-table">
        <thead>
          <tr>
            <th>Target</th>
            <th>Frame</th>
            <th>Role</th>
            <th>Reachable</th>
            <th>Hash</th>
            <th>Would action</th>
            <th>Grace</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in store.preview.peers" :key="p.operator_id" :class="previewRowClass(p.would_action)">
            <td>
              <strong>{{ p.display_name }}</strong>
              <div class="cm-dim-inline">{{ p.operator_id }}</div>
            </td>
            <td><span class="cm-frame-pill" :class="`cm-frame-${frameKeyOf(p)}`">{{ frameLabelOf(p) }}</span></td>
            <td class="cm-role-cell">{{ p.role }}</td>
            <td>{{ p.reachable === null ? '—' : (p.reachable ? 'yes' : 'no') }}</td>
            <td>{{ p.hash_match === null ? '—' : (p.hash_match ? 'match' : 'mismatch') }}</td>
            <td><code>{{ p.would_action }}</code></td>
            <td>{{ p.grace_hours != null ? p.grace_hours + 'h' : '—' }}</td>
            <td class="cm-dim-inline">{{ p.detail }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── Quarantine queue ──────────────────────────────────────────── -->
    <section class="cm-section" v-if="store.peersQuarantinedWithGrace.length">
      <h3>Pending quarantines</h3>
      <div class="cm-quarantine-list">
        <div
          v-for="p in store.peersQuarantinedWithGrace"
          :key="p.operator_id"
          class="cm-quarantine-row"
        >
          <div class="cm-qrow-head">
            <strong>{{ p.display_name }}</strong>
            <span class="cm-sev-chip">{{ p.federation_status }}</span>
          </div>
          <div class="cm-dim-inline">Reason: {{ p.quarantine_reason ?? '—' }}</div>
          <div class="cm-dim-inline" v-if="p.grace_expires">Grace expires: {{ p.grace_expires }}</div>
          <div class="cm-quarantine-actions">
            <button class="cm-btn-ghost-sm" @click="openPeer(p)">View</button>
            <button class="cm-btn-good-sm" @click="askLift(p)" :disabled="!p.peer_registry_id || !canEnforce"
                    :title="canEnforce ? undefined : t('complianceMonitorView.needsEnforcement', 'Needs the enforcement admin flag')">Lift</button>
            <button class="cm-btn-danger-sm" @click="askBlacklist(p)" :disabled="!p.peer_registry_id || !canEnforce"
                    :title="canEnforce ? undefined : t('complianceMonitorView.needsEnforcement', 'Needs the enforcement admin flag')">Blacklist…</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Federation targets (frame-grouped roster + WS-G identity surface) ── -->
    <section class="cm-section">
      <div class="cm-section-head">
        <h3>
          Federation targets · {{ filteredPeers.length }}<span v-if="filteredPeers.length !== store.peers.length" class="cm-dim"> / {{ store.peers.length }}</span>
        </h3>
        <span class="cm-dim">Every peer this registry federates with, placed in the frame that shares its trust domain</span>
      </div>

      <!-- Roster toolbar: search + status filter + identity blind-spot toggle -->
      <div class="cm-roster-toolbar">
        <input
          v-model="peerSearch"
          class="cm-search"
          type="text"
          :placeholder="t('complianceMonitorView.roster.search', 'Search peer / operator / trust domain…')"
        />
        <div class="cm-filter-chips">
          <button
            v-for="f in STATUS_FILTERS"
            :key="f"
            class="cm-chip"
            :class="{ 'cm-chip-on': statusFilter === f }"
            @click="statusFilter = f"
          >{{ f }}</button>
        </div>
        <button
          class="cm-chip cm-chip-id"
          :class="{ 'cm-chip-on': identityOnly }"
          @click="identityOnly = !identityOnly"
          title="Show only the peers a cross-frame payment would refuse: no trust domain resolves for them"
        >
          <Icon name="mdi:alert" /> {{ t('complianceMonitorView.roster.unidentifiedOnly', 'Unidentified only') }}
          <span v-if="unidentifiedCount" class="cm-chip-count">{{ unidentifiedCount }}</span>
        </button>
      </div>

      <!-- Frame-grouped tile grids (mainframes first within each frame) -->
      <div v-for="g in peersByFrame" :key="g.key" class="cm-frame-group">
        <div class="cm-frame-group-head">
          <span class="cm-frame-pill" :class="`cm-frame-${g.key.toLowerCase()}`">{{ g.key === '?' ? '·' : g.key }}</span>
          <span class="cm-frame-group-label">{{ g.label }}</span>
          <span class="cm-dim">{{ g.peers.length }}</span>
        </div>
        <div class="cm-grid">
          <button
            v-for="p in g.peers"
            :key="p.operator_id"
            class="cm-tile"
            :class="[tileClass(p), { 'cm-tile-blindspot': identityOf(p) === 'unidentified' }]"
            @click="openPeer(p)"
          >
            <div class="cm-tile-top">
              <div class="cm-tile-name">{{ p.display_name }}</div>
              <span v-if="p.role === 'mainframe'" class="cm-tile-status cm-tile-self">SELF</span>
              <span v-else-if="!p.has_compliance_record" class="cm-tile-status cm-tile-unadmitted">NOT ADMITTED</span>
              <span v-else class="cm-tile-status" :class="`cm-tile-${p.federation_status}`">{{ p.federation_status }}</span>
            </div>
            <div class="cm-tile-meta">
              <span class="cm-frame-pill" :class="`cm-frame-${frameKeyOf(p)}`">{{ frameLabelOf(p) }}</span>
              <span class="cm-tile-role">{{ p.role }}</span>
              <span class="cm-id-badge" :class="identityBadge(p).cls" :title="identityBadge(p).title">{{ identityBadge(p).label }}</span>
            </div>
            <div class="cm-tile-stats">
              <span class="cm-tile-stat"><b>{{ p.compliance_score?.toFixed(0) ?? '—' }}</b> score</span>
              <span class="cm-tile-stat"><b>{{ p.drift_events_count ?? 0 }}</b> drifts</span>
              <span class="cm-tile-stat"><b>{{ p.consecutive_poll_failures ?? 0 }}/3</b> fails</span>
              <span class="cm-tile-stat cm-tile-last">{{ timeAgo(p.last_poll_at) }}</span>
            </div>
          </button>
        </div>
      </div>
      <!-- §FESUITE (2026-10-04): the peers come from the overview; "none" only once it was read (the banner says a failed read) -->
      <div v-if="!filteredPeers.length && store.overview" class="cm-empty">No peers match this filter.</div>
    </section>

    <!-- ── Drift panel (Phase 7.1) ─────────────────────────────────────── -->
    <section class="cm-section">
      <div class="cm-section-head">
        <h3>
          Federation state drift
          · {{ store.drifts.length }}
          <span v-if="totalDriftBuckets > 1" class="cm-dim">across {{ totalDriftBuckets }} drift types</span>
        </h3>
        <div class="cm-drift-actions">
          <span v-if="store.lastDriftScan" class="cm-dim cm-drift-hint">
            Last scan {{ timeAgo(store.lastDriftScan.scanned_at) }}
            · {{ store.lastDriftScan.total_drifts }} drift(s)
          </span>
          <button
            class="cm-btn-ghost"
            @click="store.runFederationSync()"
            :disabled="store.runningFederationSync"
            title="Trigger an immediate federation_sync cycle against all ACTIVE peers, bypassing the 300s background interval. Use after a peer-config change to verify reachability without waiting."
          >
            {{ store.runningFederationSync ? 'Syncing…' : 'Trigger fed sync' }}
          </button>
          <button
            class="cm-btn-ghost"
            @click="store.runDriftScan()"
            :disabled="store.runningDriftScan"
            title="Run an on-demand drift scan. Per-day idempotency means already-emitted drifts won't re-emit today."
          >
            {{ store.runningDriftScan ? 'Scanning…' : 'Run drift scan now' }}
          </button>
          <button
            class="cm-btn-ghost"
            @click="store.loadDrifts()"
            :disabled="store.loadingDrifts"
          >
            {{ store.loadingDrifts ? '…' : 'Refresh' }}
          </button>
        </div>
      </div>
      <div v-if="store.driftsError" class="cm-error" data-testid="cm-drifts-error">{{ store.driftsError }}</div>
      <div v-else-if="!store.drifts.length && !store.loadingDrifts" class="cm-empty">
        No drift events recorded.
        Drift detection runs hourly when <code>IS_CENTRAL_REGISTRY=true</code>;
        otherwise on-demand only.
      </div>
      <div v-if="Object.keys(store.driftCountsByType).length" class="cm-drift-summary">
        <button
          v-for="(count, dtype) in store.driftCountsByType"
          :key="dtype"
          class="cm-drift-pill"
          :class="[`cm-drift-${dtype}`, { 'cm-drift-pill-on': driftTypeFilter === dtype }]"
          @click="toggleDriftType(dtype as string)"
          :title="driftTypeFilter === dtype ? 'Clear filter' : `Filter drift list to ${dtype}`"
        >
          <b>{{ count }}</b> {{ dtype }}
        </button>
        <button v-if="driftTypeFilter" class="cm-drift-pill cm-drift-clear" @click="driftTypeFilter = null">✕ clear</button>
      </div>
      <ul class="cm-drift-list">
        <li
          v-for="(d, i) in visibleDrifts"
          :key="i"
          class="cm-drift"
          :class="`drift-type-${(d.data?.drift_type as string) || 'unknown'}`"
        >
          <div class="cm-drift-line">
            <span class="cm-event-time" :title="d.timestamp">{{ stamp(d.timestamp) }}</span>
            <span
              class="cm-drift-type"
              :class="`drift-type-${(d.data?.drift_type as string) || 'unknown'}`"
            >
              {{ d.data?.drift_type ?? '?' }}
            </span>
            <span class="cm-drift-summary">{{ summarizeDrift(d) }}<span
                v-if="d.peer && d.peer.status !== 'ACTIVE'" class="cm-drift-gone"
                data-testid="cm-drift-gone"> · {{ d.peer.status === 'DELETED' ? 'peer no longer exists' : `peer now ${d.peer.status}` }}</span></span>
            <button class="cm-event-toggle" @click="toggleDrift(i)" :title="expandedDrifts.has(i) ? 'Collapse' : 'Expand raw'">
              {{ expandedDrifts.has(i) ? '▲' : '▼' }}
            </button>
          </div>
          <div v-if="expandedDrifts.has(i)" class="cm-event-raw">
            <code>{{ compactJSON(d.data) }}</code>
          </div>
        </li>
      </ul>
      <button
        v-if="filteredDrifts.length > driftLimit"
        class="cm-btn-ghost cm-drift-more"
        @click="driftLimit += DRIFT_PAGE"
      >Show more · {{ filteredDrifts.length - driftLimit }} hidden</button>
    </section>

    <!-- ── Cross-frame trust bundles (§MCPTEST30 V0561: the federation's own frames, read from this registry's
         bundle; the gateways when this registry can read them) ─────────────────────────────────────────────── -->
    <section class="cm-section" data-testid="cm-trust-matrix">
      <div class="cm-section-head">
        <div>
          <h3>
            Cross-frame trust bundles
            <span v-if="store.trustMatrix && store.trustMatrix.gateways_readable" class="cm-dim">· {{ store.trustMatrix.total }} operator gateways</span>
          </h3>
          <p class="cm-dim" v-if="store.trustMatrix">
            Does this registry, and each of its operators' federation gateways, trust every frame's CA?
            A missing CA means cross-frame mTLS from that frame is refused there.
            Read from <code>{{ store.trustMatrix.source }}</code> · {{ timeAgo(store.trustMatrix.scanned_at) }}
          </p>
        </div>
        <div class="cm-drift-actions">
          <span v-if="store.trustMatrix && store.trustMatrix.gateways_readable" class="cm-preview-counts">
            <span class="cm-pc cm-pc-ok">{{ store.trustMatrix.complete }} complete</span>
            <span class="cm-pc cm-pc-bad" v-if="store.trustMatrix.drift">{{ store.trustMatrix.drift }} missing a CA</span>
            <span class="cm-pc cm-pc-dim" v-if="store.trustMatrix.errors">{{ store.trustMatrix.errors }} unreadable</span>
          </span>
          <button
            class="cm-btn-ghost"
            @click="store.loadTrustMatrix()"
            :disabled="store.loadingTrustMatrix"
            title="Read the trust bundles again. Read-only."
          >
            {{ store.loadingTrustMatrix ? 'Reading…' : 'Refresh' }}
          </button>
        </div>
      </div>

      <div v-if="!store.trustMatrix && store.loadingTrustMatrix" class="cm-empty">Reading trust bundles…</div>
      <template v-else-if="store.trustMatrix">
        <!-- this registry's own bundle: one chip per frame of the federation -->
        <div class="cm-trust-frames" data-testid="cm-trust-frames">
          <span class="cm-dim">This registry trusts:</span>
          <span v-for="f in store.trustMatrix.frames" :key="f.trust_domain" class="cm-pc"
                :class="f.ca_count ? 'cm-pc-ok' : 'cm-pc-bad'" :title="f.trust_domain">
            {{ f.name || f.trust_domain }} · {{ f.ca_count ? `${f.ca_count} CA${f.ca_count === 1 ? '' : 's'}` : 'no CA' }}
          </span>
        </div>
        <div v-if="store.trustMatrix.frame_ca_error" class="cm-error">
          {{ store.trustMatrix.frame_ca_error }}. Cross-frame mTLS from those frames is refused here.
        </div>
        <p v-if="!store.trustMatrix.gateways_readable" class="cm-dim" data-testid="cm-trust-gateways-unreadable">
          Operator gateways: not measured here, {{ store.trustMatrix.gateways_unreadable_reason }}.
        </p>
        <div v-else-if="!store.trustMatrix.ops.length" class="cm-empty">No operator federation gateways found.</div>
        <table v-else class="cm-table">
          <thead>
            <tr>
              <th>Operator</th>
              <th>Frame</th>
              <th v-for="f in store.trustMatrix.frames" :key="f.trust_domain" :title="f.trust_domain">{{ f.name || f.trust_domain }}</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="op in store.trustMatrix.ops"
              :key="op.op"
              :class="{ 'cm-would-quarantine': op.complete === false || !!op.error }"
            >
              <td><strong>{{ op.op }}</strong></td>
              <td>{{ op.frame || '?' }}</td>
              <td v-for="f in store.trustMatrix.frames" :key="f.trust_domain">
                <span class="cm-trust-chip" :class="trustChipClass(op.trusts?.[f.trust_domain] ?? null)">{{ trustChipLabel(op.trusts?.[f.trust_domain] ?? null) }}</span>
              </td>
              <td>
                <span v-if="op.error" class="cm-pc cm-pc-dim" :title="op.error">unreadable</span>
                <span v-else-if="op.complete" class="cm-pc cm-pc-ok">trusts all</span>
                <span v-else-if="op.missing.length" class="cm-pc cm-pc-bad">missing {{ op.missing.map(frameNameOf).join(', ') }}</span>
                <span v-else class="cm-pc cm-pc-dim">not fully measured</span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>

    <!-- ── Events feed ───────────────────────────────────────────────── -->
    <section class="cm-section">
      <div class="cm-section-head">
        <h3>Recent compliance events · {{ store.events.length }}</h3>
        <span class="cm-dim">poll cycles, mode changes, baselines, dry-run drifts, quarantines</span>
      </div>
      <div v-if="store.eventsError" class="cm-error" data-testid="cm-events-error">{{ store.eventsError }}</div>
      <p v-else-if="store.eventsUnreadable.length" class="cm-dim" data-testid="cm-events-unreadable">
        Not shown, the event store did not answer for:
        <template v-for="(u, i) in store.eventsUnreadable" :key="u.event_type"><code>{{ u.event_type }}</code> ({{ u.reason }})<template v-if="i < store.eventsUnreadable.length - 1">, </template></template>.
      </p>
      <div v-if="!store.events.length && !store.loadingEvents && !store.eventsError" class="cm-empty">
        No compliance events on the ledger yet.
      </div>
      <ul class="cm-event-feed">
        <li
          v-for="(ev, i) in visibleEvents"
          :key="i"
          class="cm-event"
          :class="`ev-${ev.event_type}`"
        >
          <div class="cm-event-line">
            <span class="cm-event-time" :title="ev.timestamp">{{ stamp(ev.timestamp) }}</span>
            <span class="cm-event-type">{{ ev.event_type }}</span>
            <span class="cm-event-summary">{{ summarizeEvent(ev) }}</span>
            <button class="cm-event-toggle" @click="toggleEvent(i)" :title="expandedEvents.has(i) ? 'Collapse' : 'Expand raw'">
              {{ expandedEvents.has(i) ? '▲' : '▼' }}
            </button>
          </div>
          <div v-if="expandedEvents.has(i)" class="cm-event-raw">
            <code>{{ compactJSON(ev.data) }}</code>
          </div>
        </li>
      </ul>
      <button
        v-if="store.events.length > eventLimit"
        class="cm-btn-ghost cm-drift-more"
        @click="eventLimit += EVENT_PAGE"
      >Show more · {{ store.events.length - eventLimit }} hidden</button>
    </section>

    <!-- ── Drawer + dialogs ──────────────────────────────────────────── -->
    <CMPeerDrawer
      :open="!!selectedPeer"
      :peer="selectedPeer"
      :detail="selectedPeer ? (store.peerDetails[selectedPeer.operator_id] ?? null) : null"
      :loading-detail="selectedPeer ? !!store.loadingDetail[selectedPeer.operator_id] : false"
      :polling="false"
      :quarantining="false"
      :accepting="!!selectedPeer?.peer_registry_id && store.pendingActions.has(`accept:${selectedPeer.peer_registry_id}`)"
      :can-enforce="canEnforce"
      @close="selectedPeer = null"
      @accept-baseline="(a) => store.acceptBaseline(a.peerId, a.expectedHash, a.reason, selectedPeer?.operator_id)"
      @poll-now="(id) => store.pollPeerNow(id, true, selectedPeer?.operator_id)"
      @manual-quarantine="onManualQuarantine"
      @lift="(id) => askLift(findPeerByRegistryId(id))"
      @blacklist="(id) => askBlacklist(findPeerByRegistryId(id))"
    />

    <CMLiftDialog
      :peer="liftTarget"
      :busy="liftBusy"
      @cancel="liftTarget = null"
      @confirm="onLiftConfirm"
    />

    <CMBlacklistModal
      :peer="blacklistTarget"
      :busy="blacklistBusy"
      @cancel="blacklistTarget = null"
      @confirm="onBlacklistConfirm"
    />

    <!-- CM1 (audit 2026-05-07): themed manual-quarantine confirm. -->
    <ConfirmActionModal
      :show="showManualQuarantineModal"
      title="// MANUAL QUARANTINE"
      :message="manualQuarantineTarget
        ? `Quarantine peer <strong>${manualQuarantineTarget.display_name}</strong> for 48 hours? Federation traffic from this peer will be paused until lifted or auto-expiry.`
        : 'Quarantine this peer for 48 hours?'"
      tone="warn"
      confirm-text="Quarantine"
      busy-text="Quarantining…"
      :busy="manualQuarantineBusy"
      :reason-required="true"
      :reason-min-length="5"
      reason-placeholder="Reason for quarantine (at least 5 characters), kept in the audit log"
      warning="Grace period: 48 hours. Use the lift-quarantine button to release early."
      @close="showManualQuarantineModal = false; manualQuarantinePeerId = null; manualQuarantineTarget = null"
      @confirm="confirmManualQuarantine"
    />

    <!-- ── Toast ─────────────────────────────────────────────────────── -->
    <transition name="cm-toast">
      <div v-if="store.lastActionResult" class="cm-toast" @click="store.lastActionResult = null">
        {{ store.lastActionResult }}
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { computed, onMounted, ref, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

import { useConsulStore } from '@/stores/consul'
import { useFrameManifest } from '@/composables/useFrameManifest'
import { consulApi, type PeerTrustOverview } from '@/services/api/consulApi'
import type {
  EnforcementMode,
  PeerComplianceRow,
  ComplianceEvent,
} from '@/services/api/consulApi'

import CMEnforcementToggle from '@/components/consul/CMEnforcementToggle.vue'
import CMBlacklistModal from '@/components/consul/CMBlacklistModal.vue'
import CMLiftDialog from '@/components/consul/CMLiftDialog.vue'
import CMPeerDrawer from '@/components/consul/CMPeerDrawer.vue'
import { useI18n } from '@/composables/useI18n'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { usePermissions } from '@/composables/usePermissions'
import apiClient from '@/services/api/client'

/* §COVERAGE 2026-07-26 — degradation signals. Read from the same VictoriaMetrics the alerts
   evaluate against, so the screen and the alert can never disagree. */
const degradation = ref<any>(null)
/** §FESUITE V0577: the read failed (a 404 is a registry without the route: the panel stays away, as before) */
const degradationFailed = ref(false)
const DEG_META: Record<string, { label: string; unit: string }> = {
  dns_failures_per_min:        { label: 'Name-resolution failures', unit: '/min' },
  settlement_failures_per_min: { label: 'Settlement failures (retrying)', unit: '/min' },
  peer_unresolved_30m:         { label: 'Unresolvable peers (30m)', unit: '' },
  warning_rate_per_min:        { label: 'WARNING+ log rate', unit: '/min' },
}
const degradationCards = computed(() => {
  const sig = degradation.value?.signals || {}
  return Object.keys(DEG_META).map((k) => ({
    key: k,
    label: DEG_META[k].label,
    unit: DEG_META[k].unit,
    value: sig[k]?.value ?? null,
    threshold: sig[k]?.threshold,
    alert: sig[k]?.alert,
    breaching: !!sig[k]?.breaching,
    readable: sig[k]?.readable !== false,
    reason: sig[k]?.reason ?? null,
  }))
})
/** The server's reason, in the operator's words. Unknown reasons pass through verbatim rather
 *  than collapsing to a generic phrase — inventing a cause is worse than showing a raw one. */
function degReasonLabel(reason: string | null): string {
  if (!reason) return 'metric unreadable'
  if (reason === 'not_configured') return 'no metrics backend configured'
  if (reason === 'dns') return 'metrics host does not resolve here'
  if (reason === 'connect') return 'metrics store refused the connection'
  if (reason === 'timeout') return 'metrics store timed out'
  if (reason.startsWith('http_')) return `metrics store answered ${reason.slice(5)}`
  return `metric unreadable (${reason})`
}
async function loadDegradation() {
  try {
    const res = await apiClient.get('/admin/degradation-coverage')
    degradation.value = res.data
    degradationFailed.value = false
  } catch (e: any) {
    degradation.value = null   // no stale or fake numbers; the panel says the read failed instead (404: no route, hidden)
    degradationFailed.value = e?.response?.status !== 404
  }
}

const { t, tp } = useI18n()
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'

const store = useConsulStore()

const selectedPeer = ref<PeerComplianceRow | null>(null)
const liftTarget = ref<PeerComplianceRow | null>(null)
const blacklistTarget = ref<PeerComplianceRow | null>(null)

const modeBusy = ref(false)
const liftBusy = ref(false)
const blacklistBusy = ref(false)

const expandedEvents = ref<Set<number>>(new Set())
const expandedDrifts = ref<Set<number>>(new Set())
const totalDriftBuckets = computed(() => Object.keys(store.driftCountsByType).length)

// ── WS-G identity surface + roster filtering (Phase 1) ──────────────────────
const peerSearch = ref('')
type StatusFilter = 'all' | 'federated' | 'quarantined' | 'blacklisted' | 'unadmitted'
const STATUS_FILTERS: StatusFilter[] = ['all', 'federated', 'quarantined', 'blacklisted', 'unadmitted']
const statusFilter = ref<StatusFilter>('all')
const identityOnly = ref(false)
const driftTypeFilter = ref<string | null>(null)

// Identity (§MCPTEST30 V0561): the server resolves each peer's trust domain the way a cross-frame operation does. A
// registry before V0561 sends no identity at all: that row says "not reported", never a false "unidentified".
type IdentityState = 'resolved' | 'unidentified' | 'pending'
const RESOLVED_BY: Record<string, string> = { column: 'its peer row', card: 'its signed card', bfs: 'the topology cache' }
function identityOf(p: PeerComplianceRow): IdentityState {
  if (p.resolution_state === 'resolved') return 'resolved'
  if (p.resolution_state === 'unidentified') return 'unidentified'
  if (p.trust_domain) return 'resolved'
  return 'pending'
}
function identityBadge(p: PeerComplianceRow): { label: string; cls: string; title: string } {
  const st = identityOf(p)
  if (st === 'resolved')
    return {
      label: p.home_frame || p.trust_domain || 'resolved',
      cls: 'cm-id-resolved',
      title: `Trust domain ${p.trust_domain ?? '?'}${p.resolution_source ? `, resolved by ${RESOLVED_BY[p.resolution_source] || p.resolution_source}` : ''}`
        + (p.home_frame ? `; frame ${p.home_frame}` : '; no frame of this federation shares it')
        + (p.currency_zone ? `, settles in ${p.currency_zone}` : ''),
    }
  if (st === 'unidentified')
    return {
      label: 'unidentified',
      cls: 'cm-id-unidentified',
      title: 'No trust domain resolves for this peer: a cross-frame payment to it would be refused.',
    }
  return {
    label: 'not reported',
    cls: 'cm-id-pending',
    title: 'This registry\'s release does not report peer identity (it arrived in V0561).',
  }
}

// ── Federation reachability ────────────────────────────────────────────────
// Reads the block the compliance overview now carries. `showAllCorridors` defaults to
// findings-only so a red corridor is not buried under a wall of healthy peers — the
// exact way the frame-c gap stayed invisible.
const showAllCorridors = ref(false)
const reach = computed(() => store.overview?.reachability ?? null)

// §TRUSTPOLICY — its own read, so a failure here leaves the rest of CONSUL intact and the
// section is simply absent rather than claiming a posture it could not load.
const peerTrust = ref<PeerTrustOverview | null>(null)
const peerTrustFailed = ref(false)
const showAllTrust = ref(false)
const trustActing = computed(() => (peerTrust.value?.peers || []).filter(p => p.enforced).length)
const trustRows = computed(() => {
  const rows = peerTrust.value?.peers || []
  // "findings" = anything this frame has an opinion about. UNMEASURED is not a finding: it is
  // the absence of one, and listing it as a problem is what turns a prior into an accusation.
  return showAllTrust.value ? rows : rows.filter(p => p.state !== 'ok' && p.state !== 'unmeasured')
})
const trustHidden = computed(() => {
  const rows = peerTrust.value?.peers || []
  return showAllTrust.value ? 0 : rows.filter(p => p.state === 'ok' || p.state === 'unmeasured').length
})
async function loadPeerTrust() {
  try {
    peerTrust.value = await consulApi.getPeerTrust()
    peerTrustFailed.value = false
  } catch (e: any) {
    // §FESUITE V0577: a failed read hid the section; a registry without the route (404) still shows none
    peerTrust.value = null
    peerTrustFailed.value = e?.response?.status !== 404
  }
}
const corridorRows = computed(() => {
  const r = reach.value
  if (!r) return []
  const rows = showAllCorridors.value ? (r.peers ?? r.findings) : r.findings
  return (rows ?? []).filter((p) => (p.status || '').toUpperCase() === 'ACTIVE')
})
const reachKpiClass = computed(() => {
  const r = reach.value
  if (!r || r.peers_active === 0) return ''
  if ((r.counts?.NEVER_SYNCED ?? 0) > 0) return 'cm-kpi-bad'
  if (r.reachable < r.peers_active) return 'cm-kpi-warn'
  return 'cm-kpi-ok'
})
function humanAge(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}

const unidentifiedCount = computed(() => store.peers.filter((p) => identityOf(p) === 'unidentified').length)
const avgComplianceScore = computed<number | null>(() => {
  const scored = store.peers.filter((p) => typeof p.compliance_score === 'number')
  if (!scored.length) return null
  return Math.round(scored.reduce((a, p) => a + (p.compliance_score || 0), 0) / scored.length)
})

const filteredPeers = computed<PeerComplianceRow[]>(() => {
  const q = peerSearch.value.trim().toLowerCase()
  return store.peers.filter((p) => {
    if (identityOnly.value && identityOf(p) !== 'unidentified') return false
    const fs = p.federation_status
    if (statusFilter.value === 'unadmitted' && p.has_compliance_record) return false
    if (statusFilter.value === 'federated' && fs !== 'federated') return false
    if (statusFilter.value === 'quarantined' && fs !== 'quarantined' && fs !== 'soft_quarantined') return false
    if (statusFilter.value === 'blacklisted' && fs !== 'blacklisted') return false
    if (q && !`${p.display_name} ${p.operator_id} ${p.trust_domain ?? ''}`.toLowerCase().includes(q)) return false
    return true
  })
})

// Group the filtered roster by frame for a clearer topology read (mainframes first).
// §CONSULFIX (2026-07-27): Frame C was missing here too, so its four cloud-ops fell into
// "Unmapped" even once the backend resolved them correctly. Kept as one list so adding a
// frame means adding ONE row — the previous shape encoded the known frames twice (the group
// and the negated Unmapped match), which is exactly how C got lost.
// §FEFRAME W3 (V0504): the groups are the FRAME MANIFEST's frames, a peer placed by its trust domain (a frame and its
// operators share one), never a retired letter: on EU and ASIA every peer used to fall into "Unmapped".
// §MCPTEST30 (V0562): quarantine, lift, blacklist and accept-baseline need admin_enforcement on the server; the page
// (admin_platform) let an admin without it press them into a 403. The buttons say so instead.
const perms = usePermissions()
const canEnforce = computed(() => perms.can('enforcement'))

const fm = useFrameManifest()
function frameKeyOf(p: any): string {
  const td = String(p?.trust_domain || '').toLowerCase()
  const e = td ? fm.frames.value.find((f) => (f.trust_domain || '') === td) : null
  return e ? e.key : '?'
}
function frameLabelOf(p: any): string {
  const k = frameKeyOf(p)
  return k === '?' ? 'unmapped' : (fm.byKey(k)?.display_name || k)
}
const peersByFrame = computed(() => {
  const groups = [
    ...fm.frames.value.map((f) => ({ key: f.key, label: f.display_name || f.key })),
    { key: '?', label: 'Unmapped (no frame of this federation shares its trust domain)' },
  ]
  return groups.map((g) => ({
    key: g.key,
    label: g.label,
    peers: filteredPeers.value
      .filter((p) => frameKeyOf(p) === g.key)
      .sort((a, b) => (a.role === 'mainframe' ? 0 : 1) - (b.role === 'mainframe' ? 0 : 1)),
  })).filter((g) => g.peers.length)
})

const filteredDrifts = computed(() =>
  driftTypeFilter.value
    ? store.drifts.filter((d) => (d.data?.drift_type as string) === driftTypeFilter.value)
    : store.drifts,
)
// Cap the drift list so it stops dominating the page; "show more" reveals the rest.
const DRIFT_PAGE = 15
const driftLimit = ref(DRIFT_PAGE)
const visibleDrifts = computed(() => filteredDrifts.value.slice(0, driftLimit.value))
const EVENT_PAGE = 12
const eventLimit = ref(EVENT_PAGE)
const visibleEvents = computed(() => store.events.slice(0, eventLimit.value))
function toggleDriftType(dtype: string) {
  driftTypeFilter.value = driftTypeFilter.value === dtype ? null : dtype
}
watch(driftTypeFilter, () => { expandedDrifts.value = new Set(); driftLimit.value = DRIFT_PAGE })

// Deliberately NOT serialised. `store.refreshAll()` fans out across every peer and
// takes 15-45s; awaiting it first left the degradation panel, the header KPIs and the
// corridors blank for that whole window (Playwright: absent at 15s, present at 45s).
// `loadDegradation()` owns its try/catch and sets `degradation=null` on failure, so it
// is safe to fire unguarded and in parallel — neither call reads the other's state.
onMounted(async () => {
  await Promise.all([loadDegradation(), loadPeerTrust(), store.refreshAll()])
  live.markFetched()
})

async function refresh() {
  // ⚠ `loadDegradation()` used to be reachable ONLY from onMounted, so the four degradation cards
  // were frozen at page-load values and the Refresh button silently did not touch them. They live
  // in a local ref outside the store, which is why `store.refreshAll()` never covered them.
  // §TRUSTPOLICY — loadPeerTrust() goes in BOTH places for the same reason the comment above
  // exists: a loader reachable only from onMounted is a panel frozen at page load while the
  // Refresh button silently does not touch it.
  await Promise.all([store.refreshAll(), loadDegradation(), loadPeerTrust()])
  live.markFetched()
}

/** §FEDCLOCK — the same clock /federation uses, including its pause-on-hidden guard. */
const live = useLiveRefresh(() => { void refresh() }, { intervalMs: 60_000 })
async function runSimulator() { await store.loadPreview() }

async function onModeChange({ mode, reason }: { mode: EnforcementMode; reason: string }) {
  modeBusy.value = true
  try {
    await store.setMode(mode, reason)
    await store.loadOverview()
    await store.loadEvents(50)
  } finally { modeBusy.value = false }
}

function openPeer(peer: PeerComplianceRow) {
  selectedPeer.value = peer
  store.loadPeerDetailByOperator(peer.operator_id).catch(() => {})
}

function findPeerByRegistryId(peerId: number): PeerComplianceRow | null {
  return store.peers.find(p => p.peer_registry_id === peerId) ?? null
}

function askLift(peer: PeerComplianceRow | null) {
  if (!peer) return
  if (!peer.peer_registry_id) {
    store.lastActionResult = `${peer.display_name} has no peer row on this registry: there is no quarantine to lift`
    return
  }
  liftTarget.value = peer
}
async function onLiftConfirm(newHash: string) {
  if (!liftTarget.value || !liftTarget.value.peer_registry_id) return
  liftBusy.value = true
  try {
    const ok = await store.liftQuarantine(liftTarget.value.peer_registry_id, newHash, liftTarget.value.operator_id)
    if (ok) liftTarget.value = null
  } finally { liftBusy.value = false }
}

function askBlacklist(peer: PeerComplianceRow | null) {
  if (!peer) return
  if (!peer.peer_registry_id) {
    store.lastActionResult = `${peer.display_name} has no peer row on this registry: there is nothing to blacklist`
    return
  }
  blacklistTarget.value = peer
}
async function onBlacklistConfirm(reason: string) {
  if (!blacklistTarget.value || !blacklistTarget.value.peer_registry_id) return
  blacklistBusy.value = true
  try {
    const ok = await store.blacklist(blacklistTarget.value.peer_registry_id, reason, blacklistTarget.value.operator_id)
    if (ok) blacklistTarget.value = null
  } finally { blacklistBusy.value = false }
}

// CM1 (audit 2026-05-07): replaced native prompt() with themed
// ConfirmActionModal. Backend manualQuarantine accepts a reason; the prior
// prompt() lost the reason on dismiss + bypassed every theme rule.
const showManualQuarantineModal = ref(false)
const manualQuarantineTarget = ref<PeerComplianceRow | null>(null)
const manualQuarantineBusy = ref(false)
const manualQuarantinePeerId = ref<number | null>(null)

function onManualQuarantine(peerId: number) {
  manualQuarantinePeerId.value = peerId
  manualQuarantineTarget.value = findPeerByRegistryId(peerId)
  showManualQuarantineModal.value = true
}
async function confirmManualQuarantine(reason: string) {
  const peerId = manualQuarantinePeerId.value
  if (peerId == null) return
  manualQuarantineBusy.value = true
  try {
    await store.manualQuarantine(
      peerId,
      { reason, grace_hours: 48 },
      manualQuarantineTarget.value?.operator_id,
    )
    showManualQuarantineModal.value = false
    manualQuarantinePeerId.value = null
    manualQuarantineTarget.value = null
  } finally {
    manualQuarantineBusy.value = false
  }
}

function timeAgo(ts: string | null) { return ts ? dayjs(ts).fromNow() : '—' }
// §MCPTEST30 (V0561): the date as well as the time; the drift list spans weeks, and a bare 02:39:27 named no day
function stamp(ts: string | null) { return ts ? dayjs(ts).format('YYYY-MM-DD HH:mm') : '—' }

function compactJSON(obj: unknown): string {
  try { return JSON.stringify(obj, null, 2) } catch { return String(obj) }
}

function previewRowClass(action: string): string {
  if (action === 'none' || action === 'skipped') return ''
  return 'cm-would-quarantine'
}

// Cross-frame trust-bundle chips: true → ✓ (trusts CA), false → ✗ (missing),
// null → — (unknown, e.g. row carries an error).
function trustChipClass(trusts: boolean | null): string {
  if (trusts === true) return 'cm-trust-yes'
  if (trusts === false) return 'cm-trust-no'
  return 'cm-trust-unknown'
}
function frameNameOf(td: string): string {
  return store.trustMatrix?.frames.find((f) => f.trust_domain === td)?.name || td
}
function trustChipLabel(trusts: boolean | null): string {
  if (trusts === true) return '✓'
  if (trusts === false) return '✗'
  return '—'
}

function tileClass(p: PeerComplianceRow): string {
  if (p.role === 'mainframe') return 'cm-tile-mainframe'
  if (p.federation_status === 'blacklisted') return 'cm-tile-bl'
  if (p.federation_status === 'quarantined' || p.federation_status === 'soft_quarantined') return 'cm-tile-q'
  if (p.federation_status === 'federated') return 'cm-tile-fed'
  return 'cm-tile-neutral'
}

function toggleEvent(i: number) {
  const next = new Set(expandedEvents.value)
  if (next.has(i)) next.delete(i); else next.add(i)
  expandedEvents.value = next
}

function toggleDrift(i: number) {
  const next = new Set(expandedDrifts.value)
  if (next.has(i)) next.delete(i); else next.add(i)
  expandedDrifts.value = next
}

function summarizeDrift(d: { data?: Record<string, unknown>; peer?: { id: number; name: string | null } | null }): string {
  const data = d.data || {}
  const dt = String(data.drift_type ?? 'unknown')
  const peer = data.peer_name ?? d.peer?.name ?? (data.peer_id != null ? `#${data.peer_id}` : '?')
  const license = data.license_id ?? '—'
  const operator = data.operator_application_id ?? data.operator_name ?? '—'
  switch (dt) {
    case 'frame_bundle_stale':
      return `peer=${peer} trust_domain=${data.trust_domain ?? '?'}`
    case 'license_revoked_operator_active':
      return `license=${license} operator=${operator} (license revoked but operator still ACTIVE)`
    case 'operator_revoked_license_active':
      return `license=${license} operator=${operator} (operator revoked but license still ACTIVE)`
    case 'peer_inactive_license_active':
      return `peer=${peer} license=${license} (peer INACTIVE but license still ACTIVE)`
    case 'peer_url_misconfigured':
      return `peer=${peer} (ACTIVE but federation_sync can't reach — URL/port drift)`
    case 'operator_network_topology': {
      const missing = (data.missing_networks as string[]) || []
      const aliasIssues = (data.alias_issues as Array<Record<string, unknown>>) || []
      const op = data.operator_name ?? '?'
      const parts: string[] = []
      if (missing.length) parts.push(`missing networks: ${missing.join(', ')}`)
      if (aliasIssues.length) {
        const expl = aliasIssues.map(a => `${a.network}→${a.expected}`).join('; ')
        parts.push(`wrong/missing aliases: ${expl}`)
      }
      return `op=${op} ${parts.join(' · ') || 'topology drift'}`
    }
    default:
      return `peer=${peer} license=${license} operator=${operator}`
  }
}

// Per-event-type summary extractor — replaces raw JSON dump
function summarizeEvent(ev: ComplianceEvent): string {
  const d = (ev.data || {}) as Record<string, unknown>
  const s = (k: string) => (d[k] != null ? String(d[k]) : '')
  switch (ev.event_type) {
    case 'ComplianceEnforcementModeChanged':
      return `${s('previous_mode')} → ${s('new_mode')}${s('changed_by') ? ` · by ${s('changed_by')}` : ''}`
    case 'CompliancePollCycleCompleted': {
      const parts = [
        `mode=${s('mode')}`,
        `${s('peers_polled')} peers`,
        `${s('drifts_detected')} drifts`,
        `${s('would_quarantine_count')} would-q`,
        `${s('poll_failures')} failures`,
      ]
      if (d['skipped_reason']) parts.push(`skipped: ${s('skipped_reason')}`)
      return parts.join(' · ')
    }
    case 'ComplianceDryRunDrift': {
      const base = `${s('peer_name') || 'peer ' + s('peer_registry_id')} · ${s('severity')} · ${s('what_would_happen')}`
      // §MCPTEST30 (V0561): the same version and source on both sides with a new hash is a release changing a default
      if (d['fetched_version'] == null) return base
      const same = s('stored_version') === s('fetched_version') && s('stored_source') === s('fetched_source')
      return `${base} · version ${s('stored_version')} → ${s('fetched_version')}${same ? ' (same version: a release default changed?)' : ''}`
    }
    case 'ComplianceBaselineRecorded':
      return `${s('peer_name') || 'peer ' + s('peer_registry_id')} · baseline recorded at first sight · version ${s('policy_version')}`
    case 'ComplianceBaselineAccepted':
      return `${s('peer_name') || 'peer ' + s('peer_registry_id')} · baseline accepted by ${s('accepted_by')} · ${s('reason')}`
    case 'RegistryQuarantined':
      return `${s('peer_name') || 'peer ' + s('peer_registry_id')} · ${s('severity')} · ${s('grace_hours')}h grace`
    case 'RegistryQuarantineLifted':
      return `${s('peer_name') || 'peer ' + s('peer_registry_id')} · lifted by ${s('lifted_by')}`
    case 'RegistryBlacklisted':
      return `${s('peer_name') || 'peer ' + s('peer_registry_id')} · by ${s('blacklisted_by')}`
    default:
      // Fallback: first 120 chars of compact JSON
      try {
        const j = JSON.stringify(d)
        return j.length > 120 ? j.slice(0, 117) + '…' : j
      } catch { return '' }
  }
}

watch(() => store.lastActionResult, (val) => {
  if (!val) return
  setTimeout(() => { if (store.lastActionResult === val) store.lastActionResult = null }, 5000)
})
</script>

<style scoped>
/* ── Federation corridors ──────────────────────────────────────────────── */
.cm-reach-sub { font-weight: 400; opacity: 0.7; margin-left: 0.5rem; font-size: 0.85em; }
.cm-reach-bar {
  height: 6px; border-radius: 3px; background: var(--nc-elevated, rgba(255,255,255,0.08));
  overflow: hidden; margin: 0.5rem 0 1rem;
}
.cm-reach-fill { height: 100%; transition: width 0.4s ease; background: var(--nc-success, #3fb950); }
.cm-reach-fill.cm-kpi-warn { background: var(--nc-warning, #d29922); }
.cm-reach-fill.cm-kpi-bad { background: var(--nc-danger, #f85149); }
.cm-reach-clean { opacity: 0.75; font-size: 0.9rem; }
.cm-reach-table td { vertical-align: top; }
.cm-reach-peer { font-weight: 600; }
.cm-reach-td { display: block; font-size: 0.75rem; opacity: 0.6; }
.cm-reach-state {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
  padding: 0.15rem 0.45rem; border-radius: 4px; white-space: nowrap;
}
.cm-reach-state-ok { background: rgba(63,185,80,0.15); color: var(--nc-success, #3fb950); }
.cm-reach-state-info { background: rgba(139,148,158,0.15); color: #8b949e; }
.cm-reach-state-warning { background: rgba(210,153,34,0.15); color: var(--nc-warning, #d29922); }
.cm-reach-state-critical { background: rgba(248,81,73,0.15); color: var(--nc-danger, #f85149); }
.cm-reach-never { color: var(--nc-danger, #f85149); font-weight: 600; }
.cm-reach-diag { font-family: var(--font-mono, monospace); font-size: 0.8rem; }
.cm-reach-err { font-size: 0.7rem; opacity: 0.55; margin-top: 0.2rem; word-break: break-word; }
.cm-reach-remedy { font-size: 0.8rem; opacity: 0.85; max-width: 34ch; }
.cm-reach-muted { opacity: 0.4; }
.cm-poller-line { margin: -6px 0 0; font-size: 12px; }
.cm-trust-frames { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
/* §MCPTEST30 (V0561): a drift about a peer that is no longer active reads as history, not as a live problem */
.cm-drift-gone { color: var(--nc-text-muted); font-style: italic; }
@media (max-width: 780px) {
  .cm-reach-table th:nth-child(5), .cm-reach-table td:nth-child(5) { display: none; }
}

.cm-page {
  padding: 20px 24px 56px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  color: var(--nc-text-primary);
  background: transparent;
  min-height: 100vh;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}
.cm-page.hm-module { background: transparent; }

/* ── Header (mirrors Command Center header bar) ─────────────────── */
/* a row that wraps (it was a grid of auto 1fr auto): beside the sidebar at 1440 px the three did not fit, the title's
   column shrank under the KPIs ("COMPLIANCE" covered, the subtitle on six lines) and the KPI boxes were squeezed past
   their labels (the camera, 2026-10-13). Now the actions take a line of their own first, then the KPIs. */
.cm-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 18px;
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 10px;
  padding: 14px 18px;
}
.cm-header-left { display: flex; align-items: center; gap: 14px; min-width: 0; flex: 1 1 280px; }
.cm-icon-box {
  width: 40px; height: 40px; display: grid; place-items: center;
  background: var(--nc-primary-subtle);
  border: 1px solid var(--nc-primary-subtle);
  border-radius: 8px;
  color: var(--nc-primary);
  font-size: 20px;
}
.cm-title {
  margin: 0;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--nc-primary);
  text-transform: uppercase;
}
.cm-subtitle {
  font-size: 11px;
  color: var(--nc-text-muted);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 0.04em;
  margin-top: 2px;
}
.cm-header-kpis {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-start;
}
.cm-kpi {
  background: var(--nc-deep);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 8px 14px;
  min-width: 80px;
  flex-shrink: 0;   /* a box wraps to the next line rather than shrink past its label */
  text-align: center;
  position: relative;
}
.cm-kpi-num { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 20px; color: var(--nc-text-primary); }
.cm-kpi-label { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 9px; color: var(--nc-text-muted); letter-spacing: 0.12em; margin-top: 2px; }
.cm-kpi-ok   { border-top: 2px solid var(--nc-success); }
.cm-kpi-ok   .cm-kpi-num { color: var(--nc-success); }
.cm-kpi-warn { border-top: 2px solid var(--nc-warning); }
.cm-kpi-warn .cm-kpi-num { color: var(--nc-warning); }
.cm-kpi-bad  { border-top: 2px solid var(--nc-danger); }
.cm-kpi-bad  .cm-kpi-num { color: var(--nc-danger); }

.cm-header-actions { display: flex; gap: 8px; margin-left: auto; }
.cm-btn-ghost {
  background: transparent; color: var(--nc-text-primary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 12px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.04em;
}
.cm-btn-ghost:hover:not(:disabled) { border-color: var(--nc-border-strong); }
.cm-btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.cm-btn-accent {
  background: var(--nc-primary-subtle); color: var(--nc-primary);
  border: 1px solid var(--nc-primary-subtle);
  border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 12px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.04em;
}
.cm-btn-accent:hover:not(:disabled) { box-shadow: 0 0 0 1px var(--nc-primary); }
.cm-btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }

.cm-error {
  background: var(--nc-danger-subtle);
  border: 1px solid var(--nc-danger-subtle);
  color: var(--nc-danger); padding: 8px 14px; border-radius: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px;
}

/* ── Sections ───────────────────────────────────────────────────── */
.cm-section { display: flex; flex-direction: column; gap: 10px; }
.cm-section-head { display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.cm-section > h3,
.cm-section-head h3 {
  margin: 0; font-size: 11px; letter-spacing: 0.12em;
  color: var(--nc-text-primary); text-transform: uppercase;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-weight: 600;
}
.cm-dim { color: var(--nc-text-muted); font-size: 10px; letter-spacing: 0.08em; font-family: 'JetBrains Mono', ui-monospace, monospace; }
.cm-dim-inline { color: var(--nc-text-muted); font-size: 10px; font-family: 'JetBrains Mono', ui-monospace, monospace; }

/* ── Preview card ────────────────────────────────────────────── */
.cm-preview {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-left: 3px solid var(--nc-primary);
  border-radius: 8px;
  padding: 14px 16px;
}
.cm-preview-counts { display: flex; gap: 8px; }
.cm-pc { padding: 3px 10px; border-radius: 10px; font-size: 10px; font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.08em; }
.cm-pc-bad { background: var(--nc-danger-subtle);  color: var(--nc-danger); }
.cm-pc-ok  { background: var(--nc-success-subtle); color: var(--nc-success); }
.cm-pc-dim { background: var(--nc-border);         color: #9a9ea4; }  /* §FESUITE: 4.95:1 on the border fill (the muted text was 4.3:1) */

/* ── Quarantine queue ────────────────────────────────────────── */
.cm-quarantine-list { display: flex; flex-direction: column; gap: 8px; }
.cm-quarantine-row {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-left: 3px solid var(--nc-warning);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.cm-qrow-head { display: flex; gap: 10px; align-items: center; }
.cm-sev-chip {
  background: var(--nc-warning-subtle); color: var(--nc-warning);
  padding: 1px 8px; border-radius: 8px;
  font-size: 9px; letter-spacing: 0.1em; font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cm-quarantine-actions { display: flex; gap: 6px; margin-top: 4px; }
.cm-btn-ghost-sm, .cm-btn-good-sm, .cm-btn-danger-sm {
  border-radius: 5px; padding: 5px 10px; cursor: pointer;
  font-size: 10px; font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 0.06em;
}
.cm-btn-ghost-sm  { background: transparent; color: var(--nc-text-primary); border: 1px solid var(--nc-border); }
.cm-btn-good-sm   { background: var(--nc-success-subtle); color: var(--nc-success); border: 1px solid var(--nc-success-subtle); }
.cm-btn-danger-sm { background: var(--nc-danger-subtle); color: var(--nc-danger); border: 1px solid var(--nc-danger-subtle); }
.cm-btn-good-sm:disabled, .cm-btn-danger-sm:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── Target tiles ────────────────────────────────────────────── */
.cm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 10px;
}
.cm-tile {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 12px 14px;
  text-align: left;
  cursor: pointer;
  display: flex; flex-direction: column; gap: 6px;
  color: var(--nc-text-primary);
  transition: border-color var(--nc-duration-fast), background var(--nc-duration-fast);
  font-family: 'Inter', system-ui, sans-serif;
}
.cm-tile:hover { border-color: var(--nc-border-strong); background: var(--nc-elevated); }
.cm-tile-mainframe { border-left: 3px solid var(--nc-primary); }
.cm-tile-fed       { border-left: 3px solid var(--nc-success); }
.cm-tile-q         { border-left: 3px solid var(--nc-warning); }
.cm-tile-bl        { border-left: 3px solid var(--nc-danger); }
.cm-tile-neutral   { border-left: 3px solid var(--nc-border-strong); }
.cm-tile-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.cm-tile-name { font-size: 13px; font-weight: 600; letter-spacing: 0.02em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.cm-tile-status {
  padding: 1px 7px; border-radius: 8px; font-size: 9px;
  letter-spacing: 0.1em; font-family: 'JetBrains Mono', ui-monospace, monospace;
  white-space: nowrap;
}
.cm-tile-self        { background: var(--nc-primary-subtle); color: var(--nc-primary); }
.cm-tile-unadmitted  { background: var(--nc-border); color: var(--nc-text-muted); }
.cm-tile-federated   { background: var(--nc-success-subtle); color: var(--nc-success); }
.cm-tile-quarantined { background: var(--nc-warning-subtle); color: var(--nc-warning); }
.cm-tile-soft_quarantined { background: var(--nc-warning-subtle); color: var(--nc-chart-3); }
.cm-tile-blacklisted { background: var(--nc-danger-subtle);  color: var(--nc-danger); }

.cm-tile-meta { display: flex; gap: 8px; align-items: center; }
.cm-tile-role { font-size: 9px; color: var(--nc-text-muted); text-transform: uppercase; letter-spacing: 0.1em; font-family: 'JetBrains Mono', ui-monospace, monospace; }

.cm-tile-stats { display: flex; gap: 12px; flex-wrap: wrap; }
.cm-tile-stat { font-size: 10px; color: var(--nc-text-muted); font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.04em; }
.cm-tile-stat b { color: var(--nc-text-primary); font-weight: 400; }
.cm-tile-last { margin-left: auto; }

/* Frame letter pill */
.cm-frame-pill {
  padding: 1px 6px; border-radius: 8px; font-size: 9px;
  letter-spacing: 0.12em; font-family: 'JetBrains Mono', ui-monospace, monospace;
  border: 1px solid;
}
.cm-frame-a { color: var(--nc-primary); border-color: var(--nc-primary-subtle); background: var(--nc-primary-subtle); }
.cm-frame-b { color: var(--nc-chart-5); border-color: rgba(153,102,255,0.3); background: rgba(153,102,255,0.08); }
.cm-frame-\? { color: var(--nc-text-muted); border-color: var(--nc-border); background: transparent; }

/* ── Table (preview only) ─────────────────────────────────── */
.cm-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.cm-table th {
  text-align: left; padding: 7px 10px;
  color: var(--nc-text-muted); font-weight: 400;
  text-transform: uppercase; font-size: 9px; letter-spacing: 0.12em;
  border-bottom: 1px solid var(--nc-border);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cm-table td { padding: 8px 10px; border-bottom: 1px solid var(--nc-border-subtle); vertical-align: top; }
.cm-would-quarantine { background: var(--nc-warning-subtle); }
.cm-role-cell { font-size: 10px; color: var(--nc-text-muted); text-transform: uppercase; font-family: 'JetBrains Mono', ui-monospace, monospace; }

/* ── Cross-frame trust-bundle chips ──────────────────────────── */
.cm-trust-chip {
  display: inline-block; min-width: 22px; text-align: center;
  padding: 1px 8px; border-radius: 8px; font-size: 11px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  border: 1px solid transparent;
}
.cm-trust-yes     { background: var(--nc-success-subtle); color: var(--nc-success); border-color: rgba(0,255,136,0.25); }
.cm-trust-no      { background: var(--nc-danger-subtle);  color: var(--nc-danger);  border-color: rgba(255,51,102,0.35); }
.cm-trust-unknown { background: var(--nc-border);         color: var(--nc-text-muted); }

/* ── Events feed ─────────────────────────────────────────── */
.cm-empty { color: var(--nc-text-muted); font-size: 11px; font-family: 'JetBrains Mono', ui-monospace, monospace; padding: 8px 2px; }
.cm-event-feed { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.cm-event {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  padding: 7px 10px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
}
.cm-event.ev-ComplianceEnforcementModeChanged { border-left: 3px solid var(--nc-primary); }
.cm-event.ev-CompliancePollCycleCompleted     { border-left: 3px solid var(--nc-text-muted); }
.cm-event.ev-ComplianceDryRunDrift            { border-left: 3px solid var(--nc-warning); }
.cm-event.ev-RegistryQuarantined              { border-left: 3px solid var(--nc-warning); }
.cm-event.ev-RegistryQuarantineLifted         { border-left: 3px solid var(--nc-success); }
.cm-event.ev-RegistryBlacklisted              { border-left: 3px solid var(--nc-danger); }

.cm-event-line { display: grid; grid-template-columns: 80px 280px 1fr 32px; gap: 10px; align-items: baseline; }
.cm-event-time { color: var(--nc-text-muted); font-size: 10px; }
.cm-event-type { color: var(--nc-primary); font-size: 10px; letter-spacing: 0.06em; }
.cm-event-summary { color: var(--nc-text-secondary); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cm-event-toggle {
  background: transparent; border: none; color: var(--nc-text-muted);
  cursor: pointer; font-size: 10px; text-align: right;
}
.cm-event-raw {
  margin-top: 6px; padding: 8px; background: var(--nc-deep);
  border: 1px solid var(--nc-border-subtle); border-radius: 4px;
  color: var(--nc-text-secondary); font-size: 10px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-all;
}
.cm-event-raw code { font-family: inherit; color: inherit; background: transparent; padding: 0; }

/* ── Drift panel (Phase 7.1) ────────────────────────────── */
.cm-drift-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.cm-drift-hint { font-size: 10px; }
.cm-drift-summary {
  display: flex; gap: 8px; flex-wrap: wrap;
  margin-bottom: 8px;
}
.cm-drift-pill {
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10px;
  padding: 3px 9px; border-radius: 99px;
  background: var(--nc-deep); border: 1px solid var(--nc-border-subtle);
  color: var(--nc-text-secondary);
}
.cm-drift-pill b { color: var(--nc-text-primary); margin-right: 5px; }
.cm-drift-pill.cm-drift-frame_bundle_stale { border-color: rgba(255,149,0,0.35); color: var(--nc-warning); }
.cm-drift-pill.cm-drift-license_revoked_operator_active { border-color: rgba(255,51,102,0.35); color: var(--nc-danger); }
.cm-drift-pill.cm-drift-operator_revoked_license_active { border-color: rgba(255,51,102,0.35); color: var(--nc-danger); }
.cm-drift-pill.cm-drift-peer_inactive_license_active { border-color: rgba(255,149,0,0.35); color: var(--nc-warning); }
.cm-drift-pill.cm-drift-peer_url_misconfigured { border-color: rgba(255,149,0,0.35); color: var(--nc-warning); }
.cm-drift-pill.cm-drift-operator_network_topology { border-color: rgba(255,149,0,0.35); color: var(--nc-warning); }

.cm-drift-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.cm-drift {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border-subtle);
  border-left-width: 3px;
  border-radius: 6px;
  padding: 7px 10px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
}
.cm-drift.drift-type-frame_bundle_stale { border-left-color: var(--nc-warning); }
.cm-drift.drift-type-license_revoked_operator_active { border-left-color: var(--nc-danger); }
.cm-drift.drift-type-operator_revoked_license_active { border-left-color: var(--nc-danger); }
.cm-drift.drift-type-peer_inactive_license_active { border-left-color: var(--nc-warning); }
.cm-drift.drift-type-peer_url_misconfigured { border-left-color: var(--nc-warning); }
.cm-drift.drift-type-operator_network_topology { border-left-color: var(--nc-warning); }
.cm-drift.drift-type-unknown { border-left-color: var(--nc-text-muted); }

.cm-drift-line { display: grid; grid-template-columns: 80px 280px 1fr 32px; gap: 10px; align-items: baseline; }
.cm-drift-type { color: var(--nc-warning); font-size: 10px; letter-spacing: 0.06em; }
.cm-drift-type.drift-type-license_revoked_operator_active,
.cm-drift-type.drift-type-operator_revoked_license_active { color: var(--nc-danger); }
.cm-drift-summary { color: var(--nc-text-secondary); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Toast ─────────────────────────────────────────────── */
.cm-toast {
  position: fixed; bottom: 22px; right: 22px;
  background: var(--nc-elevated); color: var(--nc-text-primary);
  border: 1px solid var(--nc-primary-subtle);
  padding: 10px 16px; border-radius: 6px;
  font-size: 12px; cursor: pointer;
  box-shadow: var(--nc-shadow-lg);
  z-index: 4000;
}
.cm-toast-enter-active, .cm-toast-leave-active { transition: transform 0.2s, opacity 0.2s; }
.cm-toast-enter-from, .cm-toast-leave-to { transform: translateY(20px); opacity: 0; }

code { font-family: 'JetBrains Mono', ui-monospace, monospace; color: var(--nc-text-primary); background: var(--nc-deep); padding: 1px 5px; border-radius: 3px; font-size: 10px; }

/* Responsive: stack header on narrow viewports */
@media (max-width: 1200px) {
  .cm-header-kpis { justify-content: flex-start; }
  .cm-header-actions { justify-content: flex-end; }
}

/* Mobile pass follow-up (2026-05-08): KPI strip + action buttons were
   overflowing the right edge on phones. Wrap KPIs into a 2-up grid,
   shrink the title, and let the action buttons wrap to a second row. */
@media (max-width: 767.98px) {
  .cm-header { padding: 12px 12px; gap: 10px; }
  .cm-header-left { gap: 10px; }
  .cm-icon-box { width: 34px; height: 34px; font-size: 16px; }
  .cm-title { font-size: 15px; letter-spacing: 0.08em; }
  .cm-subtitle { font-size: 10px; line-height: 1.35; }

  .cm-header-kpis {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    width: 100%;
  }
  .cm-kpi {
    min-width: 0;
    padding: 6px 4px;
  }
  .cm-kpi-num   { font-size: 16px; }
  .cm-kpi-label { font-size: 8px; letter-spacing: 0.08em; }

  .cm-header-actions {
    flex-wrap: wrap;
    justify-content: stretch;
    width: 100%;
  }
  .cm-header-actions > * {
    flex: 1 1 auto;
    min-width: 0;
  }
  .cm-btn-ghost { padding: 8px 10px; font-size: 11px; min-height: 40px; }
}
@media (max-width: 479.98px) {
  /* On the smallest phones the 4-up grid still cramps. Drop to 2x2 so
     each KPI breathes and the BLACKLISTED label fits without ellipsis. */
  .cm-header-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* ── WS-G identity surface + roster toolbar (Phase 1) ─────────────────── */
.cm-kpi-id { border-top: 2px solid var(--nc-chart-5); }
.cm-kpi-id .cm-kpi-num { color: var(--nc-chart-5); }
.cm-kpi-id.cm-kpi-bad { border-top-color: var(--nc-danger); }
.cm-kpi-id.cm-kpi-bad .cm-kpi-num { color: var(--nc-danger); }

.cm-roster-toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cm-search {
  flex: 1 1 240px; min-width: 180px;
  background: var(--nc-deep);
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  padding: 7px 12px;
  color: var(--nc-text-primary);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px; outline: none;
  transition: border-color var(--nc-duration-fast);
}
.cm-search:focus { border-color: var(--nc-primary); }
.cm-search::placeholder { color: var(--nc-text-muted); }

.cm-filter-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.cm-chip {
  background: var(--nc-deep);
  border: 1px solid var(--nc-border);
  color: var(--nc-text-muted);
  border-radius: 99px;
  padding: 5px 12px; cursor: pointer;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
  transition: border-color var(--nc-duration-fast), color var(--nc-duration-fast), background var(--nc-duration-fast);
}
.cm-chip:hover { border-color: var(--nc-border-strong); color: var(--nc-text-primary); }
.cm-chip-on { background: var(--nc-primary-subtle); border-color: var(--nc-primary); color: var(--nc-primary); }
.cm-chip-id { margin-left: auto; }
.cm-chip-id.cm-chip-on { background: var(--nc-danger-subtle); border-color: var(--nc-danger); color: var(--nc-danger); }
.cm-chip-count {
  display: inline-block; margin-left: 5px; padding: 0 6px;
  background: var(--nc-danger); color: #fff; border-radius: 99px; font-size: 9px;
}

/* Frame groups */
.cm-frame-group { display: flex; flex-direction: column; gap: 8px; }
.cm-frame-group + .cm-frame-group { margin-top: 14px; }
.cm-frame-group-head { display: flex; align-items: center; gap: 8px; }
.cm-frame-group-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--nc-text-secondary);
}

/* Identity badge on tiles */
.cm-id-badge {
  margin-left: auto;
  padding: 1px 7px; border-radius: 8px; font-size: 9px;
  letter-spacing: 0.08em; font-family: 'JetBrains Mono', ui-monospace, monospace;
  border: 1px solid transparent; white-space: nowrap; max-width: 150px;
  overflow: hidden; text-overflow: ellipsis;
}
.cm-id-resolved     { background: var(--nc-success-subtle); color: var(--nc-success); border-color: rgba(0,255,136,0.25); }
.cm-id-unidentified { background: var(--nc-danger-subtle);  color: var(--nc-danger);  border-color: rgba(255,51,102,0.35); }
.cm-id-pending      { background: var(--nc-border);         color: var(--nc-text-secondary); }  /* §FESUITE: 5.0:1 on its fill (the muted text was 4.3:1) */
/* Unidentified peers get a subtle red ring so blind-spots pop in the roster. */
.cm-tile-blindspot { box-shadow: 0 0 0 1px rgba(255, 51, 102, 0.4); }
.cm-tile-blindspot:hover { box-shadow: 0 0 0 1px rgba(255, 51, 102, 0.6); }

/* Clickable drift-type pills */
.cm-drift-pill { cursor: pointer; }
.cm-drift-pill:hover { border-color: var(--nc-border-strong); }
.cm-drift-pill-on { box-shadow: inset 0 0 0 1px currentColor; background: var(--nc-elevated); }
.cm-drift-clear { color: var(--nc-text-muted); }
.cm-drift-more { align-self: flex-start; margin-top: 4px; }

/* §COVERAGE 2026-07-26 — degradation signals */
.cm-degradation .cm-deg-ico { margin-right: .4rem; vertical-align: -2px; }
.cm-deg-grid {
  display: grid; gap: .75rem; margin-top: .75rem;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}
.cm-deg-card {
  border: 1px solid var(--nc-border, rgba(255,255,255,.12));
  border-radius: 10px; padding: .75rem .85rem;
  background: var(--nc-surface, rgba(255,255,255,.03));
}
.cm-deg-card.is-breach { border-color: var(--nc-danger, #e0575b); }
.cm-deg-card.is-unknown { border-style: dashed; opacity: .75; }
.cm-deg-val { font-size: 1.5rem; font-weight: 650; line-height: 1.1; }
.cm-deg-unit { font-size: .8rem; font-weight: 400; opacity: .6; margin-left: .15rem; }
.cm-deg-label { font-size: .82rem; opacity: .85; margin-top: .15rem; }
.cm-deg-meta { display: flex; gap: .5rem; align-items: center; margin-top: .4rem; flex-wrap: wrap; }
.cm-deg-ok   { font-size: .72rem; opacity: .6; }
.cm-deg-warn { font-size: .72rem; color: var(--nc-danger, #e0575b); font-weight: 600; }
.cm-deg-alert { font-size: .68rem; opacity: .55; }
.cm-deg-cats { margin-top: .75rem; display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
.cm-deg-chip {
  font-size: .72rem; padding: .12rem .45rem; border-radius: 999px;
  border: 1px solid var(--nc-border, rgba(255,255,255,.12));
}
.cm-deg-note { margin-top: .5rem; font-size: .75rem; }
/* §FEDCLOCK (2026-09-09) — the live-refresh readout, matching /federation's. */
.cm-refresh-meta {
  display: inline-flex; align-items: center; gap: 5px; margin-right: 10px;
  font-size: 0.7rem; opacity: 0.66; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.cm-refresh-meta-label { text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.8; }  /* 4.9:1 (0.75 under the row's 0.66 was 4.47:1) */
.cm-refresh-meta-value { font-weight: 600; opacity: 0.95; }
.cm-refresh-meta-sep { opacity: 0.4; }
.cm-refresh-meta-paused {
  padding: 1px 7px; border-radius: 99px; font-size: 0.62rem; letter-spacing: 0.05em;
  border: 1px solid rgba(148, 163, 184, 0.32); color: rgba(148, 163, 184, 0.9);
}
.cm-trust-posture { font-size: 12.5px; color: var(--nc-text-secondary, #9ab); margin: 0 0 10px; line-height: 1.6; }
.cm-trust-observe { color: #f0c95c; }
.cm-trust-enforce { color: #ff8a8a; }
.cm-trust-acting { color: #ff8a8a; }
.cm-trust-unmeasured { color: var(--nc-text-secondary, #9ab); font-style: italic; }
.cm-trust-ok { color: #7ce8b8; }
.cm-trust-warn { color: #f0c95c; }
.cm-trust-restricted, .cm-trust-suspended { color: #ff8a8a; }
.cm-link { background: none; border: 0; padding: 0; color: var(--nc-primary, #7fe9c8); cursor: pointer; font: inherit; text-decoration: underline; }
</style>
