<template>
  <div class="mcp">
    <!-- Ambient (auto-suppressed by neural-command.css §25 when DashboardLayout
         renders <ViewAmbient>; kept so the standalone preview still has tone) -->
    <div class="mcp-ambient">
      <div class="mcp-grid"></div>
      <div class="mcp-scan"></div>
      <div class="mcp-glow mcp-glow-1"></div>
      <div class="mcp-glow mcp-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="mcp-hero">
      <div class="mcp-hero-inner">
        <div class="mcp-chip">
          <span class="mcp-chip-dot"></span>
          {{ tr('mcpTester.head.badge', 'MCP REGRESSION SWEEP') }} · {{ heroBadge }}
        </div>
        <h1 class="mcp-h1">
          MCP <span class="mcp-accent">Tester</span>
        </h1>
        <!-- §MCPTEST30 (V0535): the lead said "public 421 + admin 317 = 738 tools" and "86 lifecycles (77 + 9)" long after
             both moved; it says what the tester does, and the run's own numbers follow it -->
        <p class="mcp-lead">
          {{ tr('mcpTester.hero.lead', 'Every MCP tool on both bridges is called and held to its contract: status, shape, value types, the side effect it promises, the event it emits, the audit row it writes, the tier that may call it. Probe families then ask what a contract cannot: who else can read an object, whether a filter is applied, whether two pages partition a feed, whether one payment pays once, whether the ledgers agree. A skipped row is a coverage hole, never a pass.') }}
          <template v-if="heroLead"> {{ heroLead }}</template>
          <template v-else> {{ tr('mcpTester.hero.sandboxOnly', 'It runs only against the sandbox, never against production.') }}</template>
        </p>
        <!-- §MCPTEST30 (V0545): the line names the run it counts. The picker above shows the flow the NEXT press starts,
             so a cloud-op δ run on screen sat under "MCP Tester — sandbox-A" with nothing saying which run it was -->
        <p v-if="summary" class="mcp-lead mcp-lead--numbers" data-testid="mcp-hero-numbers"
           :data-suite="summary?.flow_name || loadedFlowName || ''">
          {{ tp('mcpTester.hero.rowsOf', 'This run ({suite}, started {started}): {rows} rows ({parts}).', {
            suite: loadedSuiteLabel, started: fmtStarted(loadedStartedAt), rows: rowKindsNow.rows, parts: rowParts.join(', '),
          }) }}
          <template v-if="contractsCounted">
            {{ tp('mcpTester.hero.contracts', '{explicit} of them are held to an explicit contract, {derived} to one derived from the tool\'s schema.', {
              explicit: summary.explicit_contracts ?? 0, derived: summary.default_contracts ?? 0,
            }) }}
          </template>
        </p>
        <div class="mcp-meta-row">
          <span class="mcp-meta">
            <span class="mcp-meta-key">{{ tr('mcpTester.head.origin', 'ORIGIN') }}</span>
            <span class="mcp-meta-val">{{ originHostname }}</span>
          </span>
          <span v-if="sandboxRole !== 'parent'" class="mcp-meta">
            <span class="mcp-meta-key">{{ tr('mcpTester.head.target', 'TARGET') }}</span>
            <span class="mcp-meta-val">{{ targetUrl || (sandboxRole === 'sandbox' ? tr('mcpTester.sandbox.targetSelf', 'this frame') : '—') }}</span>
          </span>
          <span v-if="sandboxRole !== 'parent'" class="mcp-meta">
            <span class="mcp-meta-key">{{ tr('mcpTester.head.mode', 'MODE') }}</span>
            <span class="mcp-meta-val" :class="isSandboxEffective ? 'mcp-mode-sandbox' : 'mcp-mode-proxy'">
              {{ modeLabel }}
            </span>
          </span>
          <!-- §MCPTEST30 (V0555): the console suite's runs have their own page and history (his word 2026-10-03) -->
          <router-link to="/admin/console-suite" class="mcp-meta mcp-meta-link" data-testid="mcp-to-console-suite">
            <Icon name="mdi:monitor-cellphone" class="mcp-meta-link-icon" aria-hidden="true" />{{ tr('mcpTester.head.toConsoleSuite', 'Console suite runs') }}
          </router-link>
        </div>
        <!-- §MCPTEST30 (2026-10-01): the cross-target switcher linked :8002/:8003/:30000/:30100, the retired sandbox
             tier; from a console that does not know its sandbox role (EU's) all four led nowhere. The target this
             console sweeps is the backend's API_TEST_TARGET_URL, shown in the meta row above. -->
      </div>
    </section>

    <!-- §TESTBED: this frame's sandbox, provisioned from here through the frame runner (renders nothing without one) -->
    <McpSandboxPanel @role="sandboxRole = $event" />

    <!-- §TESTBED: a production frame that provisions its sandbox here runs no sweep itself (its registry refuses, by
         posture); the controls, the target chips and this frame's own ledger feed give way to where runs happen -->
    <section v-if="sandboxRole === 'parent'" class="mcp-section" data-testid="mcp-parent-note">
      <p class="mcp-parent-note">
        {{ tr('mcpTester.sandbox.parentNote', 'This frame is production, so the MCP tester does not run here. Stand its sandbox up above, then run the sweep in the sandbox’s own MCP tester.') }}
      </p>
    </section>

    <!-- Sandbox refusal banner -->
    <section v-if="targetUrl && !isSandboxEffective" class="mcp-section">
      <div class="mcp-warning-banner">
        <span class="mcp-warning-icon"><Icon name="mdi:alert" /></span>
        <div>
          <strong>{{ tr('mcpTester.banner.refusalTitle', 'Refusing to run.') }}</strong>
          {{ tr('mcpTester.banner.refusalBody', 'The backend reports a target that is not a sandbox endpoint, and the MCP Tester runs only against a sandbox frame: point API_TEST_TARGET_URL on the backend at the sandbox registry.') }}
          <code>API_TEST_TARGET_URL = {{ targetUrl }}</code>
        </div>
      </div>
    </section>

    <!-- §MCPTEST30 (V0535): a sweep that stopped reporting (its registry restarted, its worker died) is said, not counted -->
    <section v-if="runSilentSince !== null" class="mcp-section" data-testid="mcp-run-silent">
      <div class="mcp-warning-banner">
        <span class="mcp-warning-icon"><Icon name="mdi:alert" /></span>
        <div>
          {{ tp('mcpTester.silent.body', 'This sweep stopped reporting at {time}: no heartbeat since, so its registry restarted or its worker died. Its record still reads running; a new sweep can start.', { time: fmtTime(runSilentSince) }) }}
        </div>
      </div>
    </section>

    <!-- Phase E.3 — persistent BUG-FIND banner: surface real wrapper / endpoint
         bugs caught by the harness immediately, regardless of which tab is active. -->
    <section v-if="bugFinds.length > 0" class="mcp-section">
      <div class="mcp-bugfind-banner" @click="activeTab = 'bugfind'">
        <span class="mcp-bugfind-icon">◉</span>
        <div class="mcp-bugfind-text">
          <strong>{{ bugFinds.length === 1 ? tr('mcpTester.banner.bugFindOne', '1 BUG-FIND assertion flagged this run.') : tp('mcpTester.banner.bugFindMany', '{n} BUG-FIND assertions flagged this run.', { n: bugFinds.length }) }}</strong>
          {{ tp('mcpTester.banner.bugFindCaught', 'What the strict-mode harness caught: {what}.', { what: bugFindTaxonomy }) }}
          {{ tr('mcpTester.banner.clickToInspect', 'Click to inspect.') }}
        </div>
        <span class="mcp-bugfind-arrow">→</span>
      </div>
    </section>

    <!-- Stats row + run controls -->
    <section v-if="sandboxRole !== 'parent'" class="mcp-section">
      <div class="mcp-controls">
        <!-- §pass73.3.19 — pick which suite to run (MCP tester / federation /
             cloud-op sweeps). Each gets the same live-log + run history. -->
        <select
          class="mcp-flow-select"
          v-model="selectedFlow"
          :disabled="isRunning"
          data-testid="mcp-flow-select"
          :title="tr('mcpTester.controls.suiteTip', 'Which suite to run')"
          :aria-label="tr('mcpTester.controls.suiteTip', 'Which suite to run')"
        >
          <option v-for="f in availableFlows" :key="f.flow_name" :value="f.flow_name">
            {{ f.label }}
          </option>
        </select>
        <button
          class="mcp-btn mcp-btn-primary"
          :disabled="!canRun"
          @click="startRun"
          data-testid="mcp-start-run"
        >
          <span class="mcp-btn-icon">{{ isRunning && runSilentSince === null ? '◐' : '▶' }}</span>
          {{ isRunning && runSilentSince === null ? tr('mcpTester.controls.inProgress', 'Sweep in progress…') : tp('mcpTester.controls.runFlow', 'Run: {label}', { label: selectedFlowLabel }) }}
        </button>
        <button
          class="mcp-btn mcp-btn-ghost"
          :disabled="isRunning"
          @click="loadLatest"
        >
          <span class="mcp-btn-icon">↻</span>
          {{ tr('mcpTester.controls.reloadLatest', 'Reload latest') }}
        </button>
        <button
          v-if="summary"
          class="mcp-btn mcp-btn-ghost"
          @click="downloadJson"
        >
          <span class="mcp-btn-icon">↓</span>
          {{ tr('mcpTester.controls.downloadJson', 'Download JSON') }}
        </button>
        <!-- Pass 10 (2026-05-28) — CSV export for spreadsheet eval -->
        <button
          v-if="summary && results.length > 0"
          class="mcp-btn mcp-btn-ghost"
          @click="downloadCsv"
          :title="tr('mcpTester.controls.csvTip', 'Export the per-tool table as CSV (Excel and spreadsheets read it)')"
        >
          <span class="mcp-btn-icon">▦</span>
          {{ tr('mcpTester.controls.downloadCsv', 'Download CSV') }}
        </button>
        <!-- §MCPTEST30 (V0535): a run that stopped reporting no longer counts up -->
        <span v-if="runSilentSince !== null" class="mcp-elapsed" data-testid="mcp-run-silent-since">
          {{ tp('mcpTester.controls.silentSince', 'silent since {time}', { time: fmtTime(runSilentSince) }) }}
        </span>
        <span v-else-if="elapsedDisplay" class="mcp-elapsed">
          <span class="mcp-elapsed-dot"></span> {{ elapsedDisplay }}
        </span>
      </div>

      <!-- Stat cards -->
      <div v-if="summary" class="mcp-stats-row">
        <div class="mcp-stat">
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.rows', 'Rows') }}</div>
          <div class="mcp-stat-value">{{ rowKindsNow.rows }}</div>
          <div class="mcp-stat-sub" data-testid="mcp-row-kinds">{{ rowParts.join(' · ') }}</div>
        </div>
        <div
          class="mcp-stat mcp-stat--success"
          :title="passRateTooltip"
        >
          <div class="mcp-stat-label">
            {{ tr('mcpTester.tiles.passRate', 'Pass rate') }}
            <span class="mcp-stat-tip">ⓘ</span>
          </div>
          <div class="mcp-stat-value" data-testid="mcp-pass-rate">{{ passReading.pct.toFixed(2) }}%</div>
          <!-- §MCPTEST30 (V0539): the four classes of a run's rows, which add up to them; the rule's refusals were
               counted as passes here and as skips in the category list -->
          <div class="mcp-stat-sub mcp-stat-breakdown" data-testid="mcp-pass-breakdown">
            <!-- §MCPTEST30 (V0552): their own class (they shared .mcp-chip with the banner and the filter buttons, so the
                 banner's margin and gap broke the row and every count showed a button's cursor), and the rule's mark is a
                 gavel: "20⊘" read as "200" in the chip font, whose zero is slashed -->
            <span class="mcp-count mcp-count--ok" data-count="passed" :title="tr('mcpTester.pass.chipPassed', 'called and passed')">{{ passReading.measured }}✓</span>
            <span v-if="passReading.byRule > 0" class="mcp-count mcp-count--rule" data-count="by-rule"
                  :title="tr('mcpTester.pass.chipByRule', 'refused by a standing rule, never called')">{{ passReading.byRule }}<Icon name="mdi:gavel" class="mcp-count-icon" aria-hidden="true" /></span>
            <span class="mcp-count mcp-count--bad" data-count="failed" :title="tr('mcpTester.pass.chipFailed', 'called and failed')">{{ summary.failed }}✗</span>
            <span class="mcp-count mcp-count--muted" data-count="skipped" :title="tr('mcpTester.pass.chipSkipped', 'not measured: a coverage hole')">{{ summary.skipped }}—</span>
          </div>
          <!-- §MCPTEST30 (V0549): the rate counts four kinds of pass alike; folded, a bar and one line say how many were
               checked against a written contract, open (a tap on a phone) the four kinds and what each means -->
          <details v-if="passDepth" class="mcp-depth" data-testid="mcp-pass-depth">
            <summary class="mcp-depth-summary">
              <span class="mcp-depth-bar" aria-hidden="true">
                <span v-for="p in passDepth.parts" :key="p.key" class="mcp-depth-seg" :class="`mcp-depth-seg--${p.key}`" :style="{ flexGrow: p.n }"></span>
              </span>
              <span class="mcp-depth-line">{{ tp('mcpTester.depth.summary', '{contract} of {total} passes checked against a written contract', { contract: passDepth.contract, total: passDepth.total }) }}</span>
            </summary>
            <ul class="mcp-depth-list">
              <li v-for="p in passDepth.parts" :key="p.key" :data-depth="p.key">
                <span class="mcp-depth-seg mcp-depth-dot" :class="`mcp-depth-seg--${p.key}`" aria-hidden="true"></span>
                <span class="mcp-depth-n">{{ p.n }}</span>
                <span class="mcp-depth-what">{{ tr(PASS_DEPTH_TEXT[p.key].key, PASS_DEPTH_TEXT[p.key].fallback) }}</span>
              </li>
            </ul>
          </details>
          <!-- §MCPTEST30 (V0550): what the target switched off. A switched-off tool passes on the refusal its switch
               documents (a 403 staking_disabled there is right, a 2xx a finding); folded, one line, open the switches and
               the rows they held -->
          <details v-if="targetSwitches" class="mcp-depth mcp-switches" data-testid="mcp-target-switches">
            <summary class="mcp-depth-summary">
              <span class="mcp-depth-line">{{
                !targetSwitches.read
                  ? tr('mcpTester.switches.unread', 'This target could not say what it switched off: its rows were judged as on any registry')
                  : targetSwitches.rows.length === 1
                    ? tr('mcpTester.switches.summaryOne', '1 row held to a switch this target turned off')
                    : targetSwitches.rows.length
                      ? tp('mcpTester.switches.summaryMany', '{n} rows held to a switch this target turned off', { n: targetSwitches.rows.length })
                      : tr('mcpTester.switches.summaryNone', 'This target switched surfaces off; no row met them')
              }}</span>
            </summary>
            <div v-if="targetSwitches.read" class="mcp-switches-body">
              <p class="mcp-switches-what">{{ tr('mcpTester.switches.what', 'A switched-off tool passes on the refusal its switch documents; a 2xx there is a finding.') }}</p>
              <div v-if="targetSwitches.off.length" class="mcp-switches-list" data-testid="mcp-target-switches-off">
                <span class="mcp-switches-label">{{ tr('mcpTester.switches.offLabel', 'Switched here') }}</span>
                <code v-for="o in targetSwitches.off" :key="o" class="mcp-code mcp-phasef-chip">{{ o }}</code>
              </div>
              <div v-if="targetSwitches.rows.length" class="mcp-switches-list" data-testid="mcp-target-switches-rows">
                <span class="mcp-switches-label">{{ tr('mcpTester.switches.rowsLabel', 'Held to its refusal') }}</span>
                <code v-for="t in targetSwitches.rows" :key="t" class="mcp-code mcp-phasef-chip">{{ t }}</code>
              </div>
            </div>
          </details>
        </div>
        <div class="mcp-stat mcp-stat--muted" :title="tr('mcpTester.tiles.skippedTip', 'Skips count AGAINST the pass rate, per doctrine: genuine limits of the sandbox environment, each covered by its skip_reason.')">
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.skipped', 'Skipped') }}</div>
          <div class="mcp-stat-value">{{ summary.skipped }}</div>
          <div class="mcp-stat-sub">{{ tr('mcpTester.tiles.skippedSub', 'coverage hole') }}</div>
        </div>
        <!--
          §MCPTEST-MCP10 — refused-by-standing-order, NOT a coverage hole.
          Rendered only when the run actually recorded the split; pre-MCP10
          runs conflated it with `skipped` and showing a fabricated 0 would
          claim a fact that run never established.
        -->
        <div
          v-if="summary.policy_denied !== undefined && summary.policy_denied !== null"
          class="mcp-stat mcp-stat--muted"
          :title="tr('mcpTester.pass.policyDeniedTip', 'Refused by a standing operating rule (provisioning, teardown, self-provision, simulation start and stop, canary fleet pause, moving value): declined on purpose, not a gap in coverage. Never called, so never a pass: they count against the pass rate.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.policyDenied', 'Policy-denied') }}</div>
          <div class="mcp-stat-value">{{ summary.policy_denied }}</div>
          <div class="mcp-stat-sub">{{ tr('mcpTester.tiles.policyDeniedSub', 'refused by rule') }}</div>
        </div>
        <div class="mcp-stat" :class="summary.failed > 0 ? 'mcp-stat--danger' : 'mcp-stat--muted'" :title="tr('mcpTester.tiles.hardFailsTip', 'Hard fails = HTTP / shape / side-effect / event-emit / audit-row contract violations.')">
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.hardFails', 'Hard fails') }}</div>
          <div class="mcp-stat-value">{{ summary.failed }}</div>
          <div class="mcp-stat-sub">{{ tr('mcpTester.tiles.hardFailsSub', 'contract violations') }}</div>
        </div>
        <div class="mcp-stat" :class="summary.bug_finds > 0 ? 'mcp-stat--danger' : 'mcp-stat--muted'" :title="tr('mcpTester.tiles.bugFindTip', 'BUG-FIND = a real wrapper or endpoint bug surfaced by a read-after-write or expect_events assertion (a 2xx that lied).')">
          <div class="mcp-stat-label">BUG-FIND</div>
          <div class="mcp-stat-value">{{ summary.bug_finds }}</div>
          <div class="mcp-stat-sub">{{ tr('mcpTester.tiles.bugFindSub', 'defects a check named') }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.contractGap.measured && (summary.contract_gap || 0) > 0 ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :data-measured="tiles.contractGap.measured ? '1' : '0'"
          :title="tr('mcpTester.tiles.contractGapsTip', 'contract_gap = a test-side bug (over-claim, missing fixture, stale contract). NOT a production bug: the §pass70/Phase D taxonomy keeps it apart from a hard fail.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.contractGaps', 'Contract gaps') }}</div>
          <div class="mcp-stat-value">{{ tiles.contractGap.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.contractGap.measured ? tr('mcpTester.tiles.contractGapsSub', 'test-side drift') : tileNotMeasured }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.tierDrift.measured && (summary.tier_drift || 0) > 0 ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :data-measured="tiles.tierDrift.measured ? '1' : '0'"
          :title="tr('mcpTester.tiles.tierDriftTip', 'tier_drift = a tool missing from the _TIER_1/2/3_TOOLS sets in audit.py. It shows as tier=unknown in audit rows. Add it to the matching set, or surface it as a strict failure.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.tierDrift', 'Tier drift') }}</div>
          <div class="mcp-stat-value">{{ tiles.tierDrift.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.tierDrift.measured ? tr('mcpTester.tiles.tierDriftSub', 'audit-set lag') : tileNotMeasured }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.authMatrix.measured && (summary.auth_matrix_violations || 0) > 0 ? 'mcp-stat--danger' : 'mcp-stat--muted'"
          :data-measured="tiles.authMatrix.measured ? '1' : '0'"
          :title="tr('mcpTester.tiles.wrongTierTip', 'F.1 wrong-tier auth matrix: for every tool, a credential of the wrong tier is sent (no JWT, an agent JWT to a developer tool, a developer JWT to an agent tool) and a 401/403 rejection is expected. A count above zero is a privilege-escalation regression. The per-tool list is on the Drift & integrity tab.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.wrongTier', 'Wrong-tier accepts') }}</div>
          <div class="mcp-stat-value">{{ tiles.authMatrix.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.authMatrix.measured ? tp('mcpTester.tiles.wrongTierSub', 'of {n} probes', { n: summary.auth_matrix_total || 0 }) : tileNotMeasured }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.crossFrame.measured && (summary.cross_frame_drift || 0) > 0 ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :data-measured="tiles.crossFrame.measured ? '1' : '0'"
          :title="tr('mcpTester.tiles.crossFrameTip', 'F.4 cross-frame parity: 25 public read-only tools are called on both the target frame and its peer frame (the sandbox pair) in parallel, and their response shape signatures compared. Values may differ (agent counts, fixtures); SHAPES must match. The diff is on the Drift & integrity tab.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.crossFrame', 'A↔B shape diff') }}</div>
          <div class="mcp-stat-value">{{ tiles.crossFrame.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.crossFrame.measured ? tp('mcpTester.tiles.crossFrameSub', 'of {n} compared', { n: summary.cross_frame_compared ?? 25 }) : tileNotMeasured }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.latency.measured && (summary.latency_regressions || 0) > 0 ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :data-measured="tiles.latency.measured ? '1' : '0'"
          :title="tr('mcpTester.tiles.latencyTip', 'F.2 latency baseline: Redis keeps the last 10 healthy elapsed_ms per tool. When the current run is over 2.0× the median of the prior 3, the row is flagged on the All tools tab. Advisory only: it does not change pass_pct. The detector needs at least 3 prior healthy samples.')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.latency', 'Latency regressions') }}</div>
          <div class="mcp-stat-value">{{ tiles.latency.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.latency.measured ? latencyTileSub : tileNotMeasured }}</div>
        </div>
        <div
          class="mcp-stat"
          :class="tiles.wrapper.measured && (summary.wrapper_drift || 0) > 0 ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :data-measured="tiles.wrapper.measured ? '1' : '0'"
          :title="wrapperReason ? tp('mcpTester.tiles.wrapperNotMeasuredTip', 'F.3 not measured: {reason}', { reason: wrapperReason }) : tr('mcpTester.tiles.wrapperTip', 'F.3 wrapper↔route: before the sweep, the request survey runs sealed on the target (no connection, no process, nothing from the environment of the node): every MCP tool is called offline and the request it sends goes through the path, query and body validation of its own route. A count is a tool whose route refuses what it sends (the rule of the build gate; its named exceptions are listed apart, not counted).')"
        >
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.wrapper', 'Wrapper↔route drift') }}</div>
          <div class="mcp-stat-value">{{ tiles.wrapper.text }}</div>
          <div class="mcp-stat-sub">{{ tiles.wrapper.measured ? wrapperTileSub : tileNotMeasured }}</div>
        </div>
        <!-- emission_integrity HONESTY flag (2026-06-26) — sidecar verdict from
             REAL ES polls + an mTLS handshake the strict pass-rate is BLIND to.
             Yellow whenever not clean: the suite can read 98%+/0-fail while
             cross-frame settlement is dead. Open "Drift & integrity" for per-check. -->
        <div
          class="mcp-stat"
          :class="(emissionIntegrityStatus === 'warn' || emissionIntegrityStatus === 'degraded') ? 'mcp-stat--warning' : 'mcp-stat--muted'"
          :title="emissionIntegrityTooltip"
        >
          <div class="mcp-stat-label">
            {{ tr('mcpTester.tiles.integrity', 'Emission integrity') }}
            <span class="mcp-stat-tip">ⓘ</span>
          </div>
          <div class="mcp-stat-value mcp-stat-value--word">{{ emissionIntegrityStatus ? emissionIntegrityStatus.toUpperCase() : '—' }}</div>
          <div class="mcp-stat-sub">{{ tp('mcpTester.tiles.integritySub', '{degraded} degraded · {warn} warn', { degraded: emissionIntegrityDegradedCount, warn: emissionIntegrityWarnCount }) }}</div>
        </div>
        <div class="mcp-stat">
          <div class="mcp-stat-label">{{ tr('mcpTester.tiles.wall', 'Wall') }}</div>
          <div class="mcp-stat-value">{{ fmtDuration(loadedWallSeconds) }}</div>
          <div class="mcp-stat-sub">{{ tr('mcpTester.tiles.wallSub', 'start to finish') }}</div>
        </div>
      </div>

      <!-- Coverage gauge -->
      <div v-if="summary" class="mcp-gauge">
        <div class="mcp-gauge-track">
          <div class="mcp-gauge-fill" :style="{ width: coveragePct.toFixed(2) + '%' }"></div>
          <div v-if="passReading.total > 0 && passReading.measured === passReading.total" class="mcp-gauge-sparkle">✦</div>
        </div>
        <div class="mcp-gauge-label">
          {{ tr('mcpTester.tiles.coverage', 'Coverage') }} <strong>{{ coveragePct.toFixed(2) }}%</strong>
          ({{ passReading.measured }}/{{ passReading.total }})
        </div>
      </div>
    </section>

    <!-- Tabs -->
    <div v-if="summary || logLines.length > 0" class="mcp-tabbar-wrap">
      <div class="mcp-tabbar" role="tablist" :aria-label="tr('mcpTester.tabs.listName', 'MCP tester views')">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          class="mcp-tabbar-btn"
          :class="{ 'mcp-tabbar-btn--active': activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          :aria-label="tab.count !== undefined ? `${tab.label} (${tab.count})` : tab.label"
          :title="tab.label"
          :data-testid="`mcp-tab-${tab.id}`"
          @click="activeTab = tab.id"
        >
          <span class="mcp-tabbar-icon" aria-hidden="true"><Icon :name="tab.icon" /></span>
          <span class="mcp-tabbar-label">{{ tab.label }}</span>
          <span v-if="tab.count !== undefined" class="mcp-tabbar-count">{{ tab.count }}</span>
        </button>
      </div>
    </div>

    <!-- TAB: Live log (left) + Live EventStore stream (right) -->
    <section v-if="activeTab === 'log' && sandboxRole !== 'parent'" class="mcp-section">
      <div class="mcp-live-grid">
        <div class="mcp-card">
          <div class="mcp-card-header">
            <span class="mcp-card-icon">▤</span>
            {{ tr('mcpTester.log.title', 'Live log') }}
            <span v-if="isRunning" class="mcp-spinner-inline"></span>
            <span class="mcp-card-meta">{{ tp('mcpTester.log.lines', '{n} lines', { n: shownLogLines.length }) }}</span>
          </div>
          <!-- §MCPTEST30 (V0539): a region that scrolls is reachable by keyboard (axe at 393 px: scrollable-region-focusable);
               the empty line names the button the page has (there is no "Run full sweep") -->
          <div ref="logScroll" class="mcp-log" tabindex="0" role="region" :aria-label="tr('mcpTester.log.region', 'Live log')">
            <!-- §FESUITE (the loading sweep): "no log entries yet" only after the last run was read -->
            <div v-if="logLines.length === 0 && !lastRunRead" class="mcp-log-empty" role="status">
              {{ tr('mcpTester.log.loading', 'Reading the last run…') }}
            </div>
            <ReadFailedNotice v-else-if="logLines.length === 0 && historyFailed" dense :retry="loadLatest" />
            <div v-else-if="logLines.length === 0" class="mcp-log-empty">
              {{ tr('mcpTester.log.empty', 'No log entries yet. Press Run to start a sweep.') }}
            </div>
            <div v-for="(l, i) in shownLogLines" :key="i" class="mcp-log-line" :class="{ 'mcp-log-line--beat': l.folded > 0 }">
              <span class="mcp-log-time">{{ fmtTime(l.ts) }}</span>
              <span class="mcp-log-msg">{{ l.msg }}</span>
              <span v-if="l.folded > 1" class="mcp-log-folded" :title="tp('mcpTester.log.foldedTip', '{n} heartbeat lines, one every 6 s', { n: l.folded })">×{{ l.folded }}</span>
            </div>
          </div>
        </div>

        <div class="mcp-card mcp-events-card">
          <div class="mcp-card-header">
            <span class="mcp-card-icon">⌬</span>
            <!-- §MCPTEST30 (V0541): the panel names the store it shows (on EU's console it streamed EU's own production
                 store under the heading "Sandbox EventStore" while the sweep's events landed in sbx-alpha's) -->
            {{ tr('mcpTester.events.title', 'EventStore — live') }}
            <span v-for="src in evtSources" :key="src.frame" class="mcp-event-source" data-testid="mcp-event-source"
                  :title="src.why === 'target'
                    ? tr('mcpTester.events.sourceTarget', 'The target\'s store: where the sweep\'s events land.')
                    : src.why === 'peer'
                      ? tr('mcpTester.events.sourcePeer', 'The peer frame\'s store: where a cross-frame transfer lands.')
                      : tr('mcpTester.events.sourceOwn', 'This node\'s own store: no target store is named for this console.')">
              {{ evtSources.length > 1 ? src.frame + ' · ' : '' }}{{ src.host }}
            </span>
            <span
              class="mcp-event-status"
              :class="evtWsConnected ? 'mcp-event-status--ok' : 'mcp-event-status--idle'"
              :title="evtWsConnected
                ? tr('mcpTester.events.connectedTip', 'Read through this console (/admin/mcp-tester/event-stream): the store answered and the subscription is open.')
                : tr('mcpTester.events.connectingTip', 'Waiting for the store to answer.')"
            >
              <span class="mcp-event-status-dot"></span>
              {{ evtWsConnected ? tr('mcpTester.events.connected', 'CONNECTED') : tr('mcpTester.events.connecting', 'CONNECTING…') }}
            </span>
            <span class="mcp-card-meta">{{ tp('mcpTester.events.feedMeta', '{shown} / {total} · cap {cap}', { shown: evtFeedFiltered.length, total: evtFeed.length, cap: EVT_MAX_FEED }) }}</span>
            <button
              class="mcp-card-action"
              :class="{ 'mcp-card-action--active': evtPaused }"
              @click="evtPaused = !evtPaused"
              :title="evtPaused ? tr('mcpTester.events.resumeTip', 'Resume stream') : tr('mcpTester.events.pauseTip', 'Pause stream')"
            >{{ evtPaused ? '▶ ' + tr('mcpTester.events.resume', 'Resume') : '⏸ ' + tr('mcpTester.events.pause', 'Pause') }}</button>
            <button
              class="mcp-card-action"
              :title="tr('mcpTester.events.clearTip', 'Clear feed')"
              @click="evtFeed = []; evtExpandedId = null"
            >⨯ {{ tr('mcpTester.events.clear', 'Clear') }}</button>
          </div>

          <!-- Toolbar: search + noise toggle + pin clear -->
          <div class="mcp-events-toolbar">
            <input
              v-model="evtFilterText"
              type="text"
              :placeholder="tr('mcpTester.events.searchPlaceholder', 'Filter by type, aggregate, source…')"
              class="mcp-events-search"
              :aria-label="tr('mcpTester.events.searchAria', 'Filter event feed')"
            />
            <button
              class="mcp-events-toggle"
              :class="{ 'mcp-events-toggle--on': evtHideNoise }"
              :title="evtHideNoise ? tr('mcpTester.events.noiseOnTip', 'Showing test events. Click to show background workers too.') : tr('mcpTester.events.noiseOffTip', 'Showing all events. Click to hide background-noise types.')"
              @click="evtHideNoise = !evtHideNoise"
            >
              {{ evtHideNoise ? '◉ ' + tr('mcpTester.events.hideNoise', 'Hide noise') : '○ ' + tr('mcpTester.events.showAll', 'Show all') }}
            </button>
            <!-- Pass 7 (2026-05-28) — multi-frame toggle + frame chip filter -->
            <button
              class="mcp-events-toggle mcp-events-toggle--frame-b"
              :class="{ 'mcp-events-toggle--on': evtIncludeB }"
              :title="evtIncludeB ? tr('mcpTester.events.peerOnTip', 'Subscribed to the sandbox-A and sandbox-B EventStores. Click to drop B.') : tr('mcpTester.events.peerOffTip', 'Add the sandbox-B EventStore subscription (see cross-frame propagation live)')"
              @click="evtIncludeB = !evtIncludeB"
            >
              {{ evtIncludeB ? '◉ A+B' : '○ ' + tr('mcpTester.events.aOnly', 'A only') }}
            </button>
            <div v-if="evtIncludeB" class="mcp-frame-chip-group">
              <button
                v-for="opt in (['all','A','B','cross'] as const)"
                :key="opt"
                class="mcp-frame-chip"
                :class="[
                  `mcp-frame-chip--${opt}`,
                  { 'mcp-frame-chip--active': evtFrameFilter === opt },
                ]"
                :title="opt === 'all' ? tr('mcpTester.events.frameAllTip', 'Show events from any frame') : opt === 'cross' ? tr('mcpTester.events.frameCrossTip', 'Show only cross-frame events') : tp('mcpTester.events.frameOneTip', 'Show only frame {frame} events', { frame: opt })"
                @click="evtFrameFilter = opt"
              >{{ opt === 'all' ? tr('mcpTester.events.frameAll', 'All') : opt === 'cross' ? '⇋ ' + tr('mcpTester.events.frameCross', 'cross') : opt }}</button>
            </div>
            <span v-if="evtHiddenNoiseCount" class="mcp-events-hidden-hint">
              {{ evtHiddenNoiseCount === 1 ? tr('mcpTester.events.hiddenOne', '(1 background event hidden)') : tp('mcpTester.events.hiddenMany', '({n} background events hidden)', { n: evtHiddenNoiseCount }) }}
            </span>
            <button
              v-if="evtPinnedType"
              class="mcp-events-pin-clear"
              :title="tp('mcpTester.events.pinnedTip', 'Showing only {type}. Click to clear.', { type: evtPinnedType })"
              @click="evtPinnedType = ''"
            >× {{ evtPinnedType }}</button>
          </div>

          <!-- Type facet chips: click to pin -->
          <div v-if="evtTypeFacets.length > 0" class="mcp-events-facets">
            <button
              v-for="[type, count] in evtTypeFacets"
              :key="type"
              class="mcp-events-facet"
              :class="{ 'mcp-events-facet--pinned': evtPinnedType === type }"
              :style="{ '--facet-color': evtTypeColor(type) }"
              :title="tp('mcpTester.events.facetTip', 'Pin the filter to {type} ({n})', { type, n: count })"
              @click="evtPinnedType = (evtPinnedType === type ? '' : type)"
            >
              <span class="mcp-events-facet-name">{{ type }}</span>
              <span class="mcp-events-facet-count">{{ count }}</span>
            </button>
          </div>

          <div class="mcp-events">
            <!-- §FESUITE (the loading sweep): "no events yet" only once the store answers; before that the feed is waiting -->
            <div v-if="evtFeed.length === 0 && !evtWsConnected" class="mcp-log-empty" role="status">
              {{ tr('mcpTester.events.connectingTip', 'Waiting for the store to answer.') }}
            </div>
            <div v-else-if="evtFeed.length === 0" class="mcp-log-empty">
              {{ tr('mcpTester.events.emptyFeed', 'No events yet. The page is subscribed to system.events, and events appear as the registry emits them.') }}
            </div>
            <div v-else-if="evtFeedFiltered.length === 0" class="mcp-log-empty">
              {{ tr('mcpTester.events.emptyFilter', 'No events match the current filter') }}
              <button class="mcp-log-empty-reset" @click="evtFilterText = ''; evtPinnedType = ''; evtHideNoise = false">{{ tr('mcpTester.events.clearFilters', 'Clear all filters') }}</button>
            </div>
            <template v-for="evt in evtFeedFiltered" :key="evt.id">
              <div
                class="mcp-event-row"
                :class="[
                  evt.fresh ? 'mcp-event-row--fresh' : '',
                  evtExpandedId === evt.id ? 'mcp-event-row--expanded' : '',
                  `mcp-event-row--frame-${evt.frame}`,
                ]"
                role="button"
                tabindex="0"
                :aria-expanded="evtExpandedId === evt.id"
                :aria-controls="`evt-panel-${evt.id}`"
                @click="evtToggleExpand(evt.id)"
                @keydown.enter.prevent="evtToggleExpand(evt.id)"
                @keydown.space.prevent="evtToggleExpand(evt.id)"
              >
                <span class="mcp-event-caret">{{ evtExpandedId === evt.id ? '▾' : '▸' }}</span>
                <span class="mcp-event-time">{{ evt.time }}</span>
                <!-- Pass 7 — frame tag (only when multi-frame on, otherwise redundant) -->
                <span
                  v-if="evtIncludeB || evt.frame === 'cross'"
                  class="mcp-event-frame"
                  :class="`mcp-event-frame--${evt.frame}`"
                  :title="tp('mcpTester.events.originTip', 'Origin frame: {frame}', { frame: evt.frame })"
                >{{ evt.frame === 'cross' ? '⇋' : evt.frame }}</span>
                <span
                  class="mcp-event-type"
                  :style="{ color: evtTypeColor(evt.event_type) }"
                >{{ evt.event_type }}</span>
                <span class="mcp-event-target" :title="evt.aggregate_id">{{ evt.targetShort }}</span>
                <span class="mcp-event-source" :title="`Source: ${evtSourceLabel(evt)}`">{{ evtSourceLabel(evt) }}</span>
              </div>

              <!-- Inline expand panel (Mission Control / AdminEvents pattern) -->
              <div
                v-if="evtExpandedId === evt.id"
                :id="`evt-panel-${evt.id}`"
                class="mcp-event-panel"
                @click.stop
              >
                <div class="mcp-event-panel-meta">
                  <div class="mcp-event-panel-cell">
                    <span class="mcp-event-panel-label">{{ tr('mcpTester.events.eventType', 'Event type') }}</span>
                    <span class="mcp-event-panel-value">
                      <code class="mcp-code">{{ evt.event_type }}</code>
                      <button class="mcp-mini-copy" :title="tr('mcpTester.events.copyType', 'Copy type')" @click.stop="evtCopyType(evt.event_type)">⎘</button>
                    </span>
                  </div>
                  <div class="mcp-event-panel-cell">
                    <span class="mcp-event-panel-label">{{ tr('mcpTester.events.aggregate', 'Aggregate') }}</span>
                    <span class="mcp-event-panel-value">
                      <code class="mcp-code">{{ evt.aggregate_id || '—' }}</code>
                      <button v-if="evt.aggregate_id" class="mcp-mini-copy" :title="tr('mcpTester.events.copyAggregate', 'Copy aggregate')" @click.stop="evtCopyType(evt.aggregate_id)">⎘</button>
                    </span>
                  </div>
                  <div class="mcp-event-panel-cell">
                    <span class="mcp-event-panel-label">{{ tr('mcpTester.events.source', 'Source') }}</span>
                    <span class="mcp-event-panel-value">
                      <code class="mcp-code">{{ evtSourceLabel(evt) }}</code>
                    </span>
                  </div>
                  <div v-if="evt.source_frame || evt.target_frame" class="mcp-event-panel-cell">
                    <span class="mcp-event-panel-label">{{ tr('mcpTester.events.frameRouting', 'Frame routing') }}</span>
                    <span class="mcp-event-panel-value">
                      <code class="mcp-code">{{ _frameShort(evt.source_frame || '?') }} → {{ _frameShort(evt.target_frame || '?') }}</code>
                      <span class="mcp-event-frame" :class="`mcp-event-frame--${evt.frame}`" style="margin-left:6px">{{ evt.frame === 'cross' ? '⇋ ' + tr('mcpTester.events.frameCross', 'cross') : evt.frame }}</span>
                    </span>
                  </div>
                  <div class="mcp-event-panel-cell">
                    <span class="mcp-event-panel-label">{{ tr('mcpTester.events.timestamp', 'Timestamp') }}</span>
                    <span class="mcp-event-panel-value">
                      <code class="mcp-code">{{ evt.rawTimestamp }}</code>
                    </span>
                  </div>
                </div>
                <JsonViewer :data="evt.payload || {}" :label="tr('mcpTester.events.payload', 'Event payload (raw broadcast)')" bordered />
                <JsonViewer
                  v-if="evt.metadata && Object.keys(evt.metadata).length"
                  :data="evt.metadata"
                  :label="tr('mcpTester.cards.metadata', 'Metadata')"
                  bordered
                />
              </div>
            </template>
          </div>
        </div>
      </div>
    </section>

    <!-- §MCPTEST30 (V0541): a result tab with no run loaded (a sweep in flight, or none run yet) printed a clean verdict
         over zero rows ("No wrapper bugs surfaced", "Nothing was left out", "All Phase F detectors clean"). It says what
         it waits for (runReading.awaitsRun), and while a sweep runs it offers the last finished one. -->
    <section v-if="awaitingRun" class="mcp-section" data-testid="mcp-awaiting-run">
      <div class="mcp-card">
        <div class="mcp-empty mcp-empty--rich">
          <span class="mcp-empty-icon" aria-hidden="true">◯</span>
          <div class="mcp-empty-body">
            <div class="mcp-empty-title">
              {{ isRunning ? tr('mcpTester.awaiting.inFlight', 'A sweep is in flight') : tr('mcpTester.awaiting.title', 'No sweep results yet') }}
            </div>
            <div class="mcp-empty-detail">
              {{ isRunning
                ? tr('mcpTester.awaiting.inFlightNote', 'Its rows arrive when it finishes; the live log shows its steps meanwhile.')
                : tr('mcpTester.awaiting.note', 'Run a sweep, or open a finished one from History: this tab reads its rows.') }}
              <button
                v-if="isRunning && lastFinishedRun"
                type="button"
                class="mcp-empty-reset"
                data-testid="mcp-show-last-finished"
                @click="viewRun(lastFinishedRun.run_id)"
              >{{ tp('mcpTester.awaiting.showLast', 'Show the last finished run ({suite} · {started})',
                     { suite: flowShortLabel(lastFinishedRun.flow_name), started: fmtStarted(lastFinishedRun.started_at) }) }}</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- TAB: BUG-FIND failures -->
    <section v-if="activeTab === 'bugfind' && !awaitingRun" class="mcp-section">
      <div class="mcp-card" :class="bugFinds.length > 0 ? 'mcp-card--danger' : ''">
        <div class="mcp-card-header">
          <span class="mcp-card-icon" :class="bugFinds.length > 0 ? 'text-danger' : ''">◉</span>
          {{ tr('mcpTester.cards.bugFindTitle', 'BUG-FIND assertions') }}
          <span class="mcp-card-meta">{{ tp('mcpTester.cards.found', '{n} found', { n: bugFinds.length }) }}</span>
        </div>
        <div v-if="bugFinds.length === 0" class="mcp-empty">
          <span class="mcp-empty-icon">✓</span>
          {{ tr('mcpTester.cards.bugFindEmpty', 'No wrapper bugs surfaced. The framework caught no silent NO-OPs, field drift or shape drift this run.') }}
        </div>
        <table v-else class="mcp-table mcp-table--stack">
          <thead>
            <tr>
              <th style="width: 35%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
              <th>{{ tr('mcpTester.cols.failureDiff', 'Failure diff') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(bf, i) in bugFinds" :key="i">
              <td><code class="mcp-code">{{ bf.tool }}</code></td>
              <td class="mcp-cell-error">{{ bf.error }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- TAB: Hard failures -->
    <section v-if="activeTab === 'fails' && !awaitingRun" class="mcp-section">
      <div class="mcp-card" :class="hardFails.length > 0 ? 'mcp-card--danger' : ''">
        <div class="mcp-card-header">
          <span class="mcp-card-icon" :class="hardFails.length > 0 ? 'text-danger' : ''">✕</span>
          {{ tr('mcpTester.cards.hardFailTitle', 'Hard failures') }}
          <span class="mcp-card-meta">{{ tp('mcpTester.cards.found', '{n} found', { n: hardFails.length }) }}</span>
        </div>
        <div v-if="hardFails.length === 0" class="mcp-empty">
          <span class="mcp-empty-icon">✓</span>
          {{ tr('mcpTester.cards.hardFailEmpty', 'No hard failures. Every reachable tool returned a healthy outcome or an expected skip.') }}
        </div>
        <table v-else class="mcp-table mcp-table--stack">
          <thead>
            <tr>
              <th style="width: 35%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
              <th>{{ tr('mcpTester.cols.error', 'Error') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(hf, i) in hardFails" :key="i">
              <td><code class="mcp-code">{{ hf.tool }}</code></td>
              <td class="mcp-cell-error">{{ hf.error }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- TAB: All tools (results table) -->
    <section v-if="activeTab === 'results' && !awaitingRun" class="mcp-section">
      <!-- Phase E.3 — sweep timing analytics: median + p95 + slowest 10 -->
      <div v-if="results.length > 0" class="mcp-card mcp-card--timing">
        <div class="mcp-card-header">
          <span class="mcp-card-icon">⌬</span>
          {{ tr('mcpTester.cards.timingTitle', 'Sweep timing') }}
          <span class="mcp-card-meta">
            {{ tp('mcpTester.cards.timingMeta', 'median {median}ms · p95 {p95}ms · max {max}ms', { median: latencyMedian, p95: latencyP95, max: latencyMax }) }}
          </span>
        </div>
        <div class="mcp-timing-row">
          <div
            v-for="row in slowestTen"
            :key="row.tool"
            class="mcp-timing-cell"
            :class="row.healthy ? '' : 'mcp-timing-cell--bad'"
            :title="row.error || row.skip_reason || 'OK'"
          >
            <code class="mcp-code">{{ row.tool.replace('theprotocol_', '') }}</code>
            <span class="mcp-timing-ms">{{ row.elapsed }}ms</span>
          </div>
        </div>
      </div>
      <!-- §pass73.3.18 — auto-derived category groupings + per-row expand
           panel. Settings: auto-categorize by tool-name prefix · sync await ·
           persist expansion in localStorage · categories + rows collapsed by
           default. Inspired by the api-tester's endpoint-card pattern but
           tailored to MCP strict-mode semantics (12-axis assertions, latency
           baseline, tier-set, error/skip envelopes). -->
      <div class="mcp-card mcp-card--categories">
        <!-- Sticky toolbar (Pass 2 2026-05-28) — header + pills + filters in
             one bar that stays glued to the top while scrolling categories.
             Counts visible at all times. Fail-only / slow-only filter chips. -->
        <div class="mcp-card-header mcp-card-header--sticky">
          <span class="mcp-card-icon">⎘</span>
          {{ tr('mcpTester.cards.byCategoryTitle', 'Tools by category') }}
          <div class="mcp-pill-group">
            <span class="mcp-pill mcp-pill--ok" :title="tp('mcpTester.cards.okPillTip', '{n} tools healthy', { n: totalPassCount })">{{ tp('mcpTester.cards.okPill', '{n} OK', { n: totalPassCount }) }}</span>
            <span v-if="totalFailCount > 0" class="mcp-pill mcp-pill--fail" :title="tp('mcpTester.cards.failPillTip', '{n} tools failed', { n: totalFailCount })">{{ tp('mcpTester.cards.failPill', '{n} fail', { n: totalFailCount }) }}</span>
            <span v-if="totalByRuleCount > 0" class="mcp-pill mcp-pill--rule"
                  :title="tr('mcpTester.pass.chipByRule', 'refused by a standing rule, never called')">{{ tp('mcpTester.pass.byRuleChip', '{n} by rule', { n: totalByRuleCount }) }}</span>
            <span v-if="totalSkipCount > 0" class="mcp-pill mcp-pill--skip" :title="tp('mcpTester.cards.skipPillTip', '{n} tools skipped', { n: totalSkipCount })">{{ tp('mcpTester.cards.skipPill', '{n} skip', { n: totalSkipCount }) }}</span>
            <span class="mcp-pill mcp-pill--meta">{{ filteredResults.length }} / {{ results.length }}</span>
          </div>
          <input
            v-model="filterText"
            class="mcp-input"
            :placeholder="tr('mcpTester.filter.placeholder', 'Filter tool name…')"
            data-testid="mcp-filter-input"
          />
          <select v-model="filterTier" class="mcp-input" :aria-label="tr('mcpTester.filter.tierAria', 'Filter by tier')">
            <option value="">{{ tr('mcpTester.filter.allTiers', 'All tiers') }}</option>
            <option value="none">none</option>
            <option value="agent">agent</option>
            <option value="developer">developer</option>
            <option value="admin">admin</option>
            <option value="admin-bridge">admin-bridge</option>
          </select>
          <select v-model="filterCategory" class="mcp-input" :aria-label="tr('mcpTester.filter.categoryAria', 'Filter by category')">
            <option value="">{{ tr('mcpTester.filter.allCategories', 'All categories') }}</option>
            <option
              v-for="cat in availableCategories"
              :key="cat"
              :value="cat"
            >{{ cat }}</option>
          </select>
          <button
            class="mcp-chip"
            :class="{ 'mcp-chip--on': onlyFailures }"
            :title="onlyFailures ? tr('mcpTester.filter.failsOnlyOnTip', 'Showing failed tools only. Click to show all.') : tr('mcpTester.filter.failsOnlyOffTip', 'Show only failing tools')"
            @click="onlyFailures = !onlyFailures"
          >{{ onlyFailures ? '◉' : '○' }} {{ tr('mcpTester.filter.failsOnly', 'fails only') }}</button>
          <button
            class="mcp-chip"
            :class="{ 'mcp-chip--on': onlySlow }"
            :title="onlySlow ? tp('mcpTester.filter.slowOnlyOnTip', 'Showing tools over {ms}ms. Click to show all.', { ms: SLOW_THRESHOLD_MS }) : tp('mcpTester.filter.slowOnlyOffTip', 'Show tools slower than {ms}ms', { ms: SLOW_THRESHOLD_MS })"
            @click="onlySlow = !onlySlow"
          >{{ onlySlow ? '◉' : '○' }} {{ tr('mcpTester.filter.slowOnly', 'slow only') }}</button>
          <!-- Pass 8 (2026-05-28) — strict pass mode: requires status==2xx.
               Surfaces tools that the predicate accepted as healthy with 4xx. -->
          <button
            class="mcp-chip"
            :class="{ 'mcp-chip--on': strictPass }"
            :title="strictPass ? tp('mcpTester.filter.strictOnTip', 'Strict mode ON: the {n} lenient passes (healthy, but no 2xx status) are hidden. Click to show them again.', { n: totalLenientPassCount }) : tp('mcpTester.filter.strictOffTip', 'Strict pass mode: hide the passes the predicate accepted without a 2xx (a 4xx taken as proof that the endpoint exists, or no status at all). {n} tools fall in that bucket.', { n: totalLenientPassCount })"
            @click="strictPass = !strictPass"
          >{{ strictPass ? '◉' : '○' }} {{ tr('mcpTester.filter.strictPass', 'strict pass') }}<span v-if="totalLenientPassCount > 0" class="mcp-chip-num">{{ totalLenientPassCount }}</span></button>
          <!-- Status-code bucket chips -->
          <div class="mcp-status-chips" role="radiogroup" :aria-label="tr('mcpTester.filter.statusAria', 'Filter by HTTP status')">
            <button
              v-for="b in (['', '2xx', '4xx', '401', '403', '404', '5xx'] as const)"
              :key="b || 'all'"
              class="mcp-status-chip"
              :class="[`mcp-status-chip--${b || 'all'}`, { 'mcp-status-chip--active': statusBucket === b }]"
              :title="b ? tp('mcpTester.filter.statusOnlyTip', 'Show only {b} responses ({n} tools)', { b, n: statusDistribution[b] || 0 }) : tr('mcpTester.filter.statusAllTip', 'Show all status codes')"
              @click="statusBucket = b"
            >
              <span class="mcp-status-chip-label">{{ b || tr('mcpTester.filter.statusAll', 'all') }}</span>
              <span v-if="b && statusDistribution[b]" class="mcp-status-chip-count">{{ statusDistribution[b] }}</span>
            </button>
          </div>
          <button
            class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
            :title="allCategoriesExpanded ? tr('mcpTester.filter.collapseAllTip', 'Collapse all categories') : tr('mcpTester.filter.expandAllTip', 'Expand all categories')"
            @click="toggleAllCategories"
            data-testid="mcp-toggle-all-categories"
          >{{ allCategoriesExpanded ? '⊟ ' + tr('mcpTester.filter.collapseAll', 'collapse all') : '⊞ ' + tr('mcpTester.filter.expandAll', 'expand all') }}</button>
        </div>
        <!-- §MCPTEST-MCP11 — the "Skipped this run" and "Refused by standing
             order" cards used to sit HERE, between the filter bar and the
             category list. With 21 policy-denied rows they pushed every
             category below the fold and made the All-tools view unreadable.
             They now live on their own "Not run" tab; see that section. -->

        <div class="mcp-results-scroll">
          <!-- Per-category sections -->
          <div
            v-for="cat in categorizedFilteredResults"
            :key="cat.name"
            class="mcp-cat-section"
            :class="{ 'mcp-cat-section--expanded': expandedCategories.has(cat.name) }"
          >
            <!-- Category header — click to toggle -->
            <button
              class="mcp-cat-header"
              :class="{
                'mcp-cat-header--all-pass': cat.fail_count === 0 && cat.skip_count === 0,
                'mcp-cat-header--has-fails': cat.fail_count > 0,
              }"
              @click="toggleCategory(cat.name)"
              :data-testid="`mcp-cat-${cat.name}`"
            >
              <span class="mcp-cat-chevron">{{ expandedCategories.has(cat.name) ? '▾' : '▸' }}</span>
              <span class="mcp-cat-name">{{ cat.name }}</span>
              <span class="mcp-cat-stats">
                <span class="mcp-cat-stat mcp-cat-stat--ok">{{ tp('mcpTester.cards.okPill', '{n} OK', { n: cat.pass_count }) }}</span>
                <span
                  v-if="cat.fail_count > 0"
                  class="mcp-cat-stat mcp-cat-stat--fail"
                >{{ tp('mcpTester.cards.failPill', '{n} fail', { n: cat.fail_count }) }}</span>
                <span
                  v-if="cat.by_rule_count > 0"
                  class="mcp-cat-stat mcp-cat-stat--rule"
                >{{ tp('mcpTester.pass.byRuleChip', '{n} by rule', { n: cat.by_rule_count }) }}</span>
                <span
                  v-if="cat.skip_count > 0"
                  class="mcp-cat-stat mcp-cat-stat--skip"
                >{{ tp('mcpTester.cards.skipPill', '{n} skip', { n: cat.skip_count }) }}</span>
                <span class="mcp-cat-stat mcp-cat-stat--meta">
                  · {{ tp('mcpTester.list.median', 'median {ms}ms', { ms: cat.median_ms }) }}
                </span>
                <span class="mcp-cat-stat mcp-cat-stat--meta">
                  · {{ categoryCount(cat.name, cat.total) }}
                </span>
              </span>
              <!-- §MCPTEST30 (V0535): three segments; one bar coloured by pass rate painted a category with skips and no
                   failures red -->
              <span class="mcp-cat-bar" :title="tp('mcpTester.pass.catBar', '{pass} passed · {rule} refused by rule · {skip} not measured · {fail} failed', { pass: cat.pass_count, rule: cat.by_rule_count, skip: cat.skip_count, fail: cat.fail_count })">
                <span class="mcp-cat-bar-fill mcp-cat-bar-fill--green" :style="{ width: cat.bar.pass + '%' }"></span>
                <span class="mcp-cat-bar-fill mcp-cat-bar-fill--rule" :style="{ width: cat.bar.byRule + '%' }"></span>
                <span class="mcp-cat-bar-fill mcp-cat-bar-fill--skip" :style="{ width: cat.bar.skip + '%' }"></span>
                <span class="mcp-cat-bar-fill mcp-cat-bar-fill--red" :style="{ width: cat.bar.fail + '%' }"></span>
              </span>
            </button>

            <!-- Tool rows for this category — only rendered when expanded -->
            <transition name="mcp-cat-slide">
              <table
                v-if="expandedCategories.has(cat.name)"
                class="mcp-table mcp-table--results mcp-table--in-cat mcp-table--stack"
              >
                <thead>
                  <tr>
                    <th style="width: 24px"><span class="mcp-sr-only">{{ tr('mcpTester.cols.expand', 'Expand') }}</span></th>
                    <th>{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                    <th style="width: 110px">{{ tr('mcpTester.cols.tier', 'Tier') }}</th>
                    <th style="width: 88px">{{ tr('mcpTester.cols.status', 'Status') }}</th>
                    <th style="width: 70px">HTTP</th>
                    <th style="width: 80px">{{ tr('mcpTester.cols.elapsed', 'Elapsed') }}</th>
                    <th>{{ tr('mcpTester.cols.errorOrSkip', 'Error / Skip reason') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in cat.tools" :key="row.tool">
                    <tr
                      :class="[rowClass(row), 'mcp-row-clickable', { 'mcp-row--expanded': expandedRows.has(row.tool) }]"
                      @click="toggleRow(row.tool)"
                      :data-testid="`mcp-row-${row.tool}`"
                      tabindex="0"
                      role="button"
                      :aria-expanded="expandedRows.has(row.tool)"
                      :aria-controls="`mcp-detail-${row.tool}`"
                      @keydown="onRowKeydown($event, row.tool)"
                    >
                      <td class="mcp-row-chevron-cell">
                        <span class="mcp-row-chevron">
                          {{ expandedRows.has(row.tool) ? '▾' : '▸' }}
                        </span>
                      </td>
                      <td><code class="mcp-code" :title="row.tool">{{ rowLabel(row.tool) }}</code></td>
                      <td class="mcp-cell-inline" :data-label="tr('mcpTester.cols.tier', 'Tier')">{{ row.tier || '—' }}</td>
                      <td class="mcp-cell-inline" :data-label="tr('mcpTester.cols.status', 'Status')">
                        <span class="mcp-badge" :class="badgeOf(row).cls" :data-outcome="outcomeOf(row)" :data-refusal-only="isRefusalOnly(row) ? '1' : undefined"
                              :title="isRefusalOnly(row) ? tr('mcpTester.outcome.refusalOnlyTip', 'passed on a refusal alone: nothing in this run reached its success path, so it counts as not measured') : outcomeOf(row) === 'by_rule' ? tr('mcpTester.pass.chipByRule', 'refused by a standing rule, never called') : undefined">{{ tr(badgeOf(row).key, badgeOf(row).fallback) }}</span>
                      </td>
                      <td class="mcp-cell-mono mcp-cell-inline" data-label="HTTP">{{ row.status || '—' }}</td>
                      <td class="mcp-cell-mono mcp-cell-inline" :data-label="tr('mcpTester.cols.elapsed', 'Elapsed')">
                        {{ row.elapsed }}ms
                        <span
                          v-if="row.latency_regression"
                          class="mcp-latency-flag"
                          :title="tp('mcpTester.list.latencyTip', 'Latency regression: now {ms}ms, {factor}× the median of the prior 3 ({baseline}ms). Threshold 2.0×. Advisory only: it does not change pass_pct.', { ms: row.elapsed, factor: row.latency_baseline_ms ? (row.elapsed / row.latency_baseline_ms).toFixed(1) : '?', baseline: row.latency_baseline_ms || 0 })"
                        ><Icon name="mdi:alert" /> {{ tp('mcpTester.list.timesBaseline', '{factor}× baseline', { factor: row.latency_baseline_ms ? (row.elapsed / row.latency_baseline_ms).toFixed(1) : '?' }) }}</span>
                      </td>
                      <td class="mcp-cell-error"
                          :data-label="row.error || row.skip_reason ? tr('mcpTester.cols.errorOrSkip', 'Error / Skip reason') : undefined">
                        <span v-if="row.error">{{ row.error }}</span>
                        <span v-else-if="row.skip_reason" class="mcp-cell-muted">{{ row.skip_reason }}</span>
                      </td>
                    </tr>

                    <!-- Expanded detail row — Phase 1 unlock: surface every
                         field the strict-mode harness has captured for this
                         tool. As backend ships more axes (request args,
                         response data, per-axis assertion breakdown), this
                         panel grows to render them; today it shows everything
                         currently in the row schema. -->
                    <tr
                      v-if="expandedRows.has(row.tool)"
                      class="mcp-detail-row"
                      :key="`${row.tool}--detail`"
                    >
                      <td colspan="7" :id="`mcp-detail-${row.tool}`">
                        <div class="mcp-detail-panel" @click.stop>
                          <!-- 3-column quick-facts grid -->
                          <div class="mcp-detail-grid">
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.cols.tool', 'Tool') }}</div>
                              <div class="mcp-detail-val">
                                <code class="mcp-code">{{ row.tool }}</code>
                                <button
                                  class="mcp-detail-copy"
                                  :title="tr('mcpTester.detail.copyTool', 'Copy tool name')"
                                  @click="copyToClipboard(row.tool)"
                                >⎘</button>
                              </div>
                            </div>
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.cols.tier', 'Tier') }}</div>
                              <div class="mcp-detail-val">{{ row.tier || '—' }}</div>
                            </div>
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.cols.status', 'Status') }}</div>
                              <div class="mcp-detail-val">
                                <span class="mcp-badge" :class="badgeOf(row).cls">{{ tr(badgeOf(row).key, badgeOf(row).fallback) }}</span>
                              </div>
                            </div>
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.detail.httpStatus', 'HTTP status') }}</div>
                              <div class="mcp-detail-val">{{ row.status || '—' }}</div>
                            </div>
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.cols.elapsed', 'Elapsed') }}</div>
                              <div class="mcp-detail-val">
                                {{ row.elapsed }}ms
                                <span
                                  v-if="row.latency_regression"
                                  class="mcp-detail-warn"
                                >
                                  <Icon name="mdi:alert" /> {{ tp('mcpTester.detail.timesBaselineMs', '{factor}× baseline ({baseline}ms)', { factor: row.latency_baseline_ms ? (row.elapsed / row.latency_baseline_ms).toFixed(1) : '?', baseline: row.latency_baseline_ms }) }}
                                </span>
                              </div>
                            </div>
                            <div class="mcp-detail-cell">
                              <div class="mcp-detail-key">{{ tr('mcpTester.detail.category', 'Category') }}</div>
                              <div class="mcp-detail-val">{{ cat.name }}</div>
                            </div>
                          </div>

                          <!-- Error / skip rationale (expanded if present) -->
                          <div v-if="row.error" class="mcp-detail-block">
                            <div class="mcp-detail-block-header">
                              <span class="mcp-detail-block-icon">⊗</span>
                              {{ tr('mcpTester.detail.failureDetail', 'Failure detail') }}
                              <button
                                class="mcp-detail-copy"
                                @click="copyToClipboard(row.error || '')"
                                :title="tr('mcpTester.detail.copyError', 'Copy error')"
                              >⎘ {{ tr('mcpTester.detail.copy', 'copy') }}</button>
                            </div>
                            <pre class="mcp-detail-pre mcp-detail-pre--err">{{ row.error }}</pre>
                          </div>
                          <div v-else-if="row.skip_reason" class="mcp-detail-block">
                            <div class="mcp-detail-block-header">
                              <span class="mcp-detail-block-icon">◯</span>
                              {{ tr('mcpTester.detail.skipRationale', 'Skip rationale') }}
                              <button
                                class="mcp-detail-copy"
                                @click="copyToClipboard(row.skip_reason || '')"
                                :title="tr('mcpTester.detail.copyReason', 'Copy reason')"
                              >⎘ {{ tr('mcpTester.detail.copy', 'copy') }}</button>
                            </div>
                            <pre class="mcp-detail-pre mcp-detail-pre--skip">{{ row.skip_reason }}</pre>
                          </div>

                          <!-- 12-axis strict-mode assertion summary
                               (assertions field will populate as backend
                               sends it; for now we render what we KNOW
                               from existing schema) -->
                          <!-- pass73.3.19 Pass 6 (2026-05-28) — Real response
                               payload. Critical for evaluating non-200 codes:
                               see the error envelope from a 4xx, the actual
                               shape from a 2xx, or the re-fire response. -->
                          <div v-if="rowResponsePayload(row)" class="mcp-detail-block">
                            <JsonViewer
                              :data="rowResponsePayload(row)"
                              :label="rowResponseLabel(row)"
                              bordered
                            />
                          </div>

                          <div class="mcp-detail-block">
                            <div class="mcp-detail-block-header">
                              <span class="mcp-detail-block-icon">◇</span>
                              {{ tr('mcpTester.detail.assertions', 'Strict-mode assertions') }}
                              <span class="mcp-detail-block-meta">{{ tp('mcpTester.detail.assertionsPassed', '{pass} / {total} passed', { pass: assertionsForRow(row).pass_count, total: assertionsForRow(row).total }) }}</span>
                            </div>
                            <ul class="mcp-assertion-list">
                              <li
                                v-for="ax in assertionsForRow(row).axes"
                                :key="ax.name"
                                class="mcp-assertion"
                                :class="{
                                  'mcp-assertion--pass': ax.state === 'pass',
                                  'mcp-assertion--fail': ax.state === 'fail',
                                  'mcp-assertion--skip': ax.state === 'skip',
                                  'mcp-assertion--unknown': ax.state === 'unknown',
                                }"
                              >
                                <span class="mcp-assertion-icon">{{ ax.state === 'pass' ? '✔' : ax.state === 'fail' ? '✗' : ax.state === 'skip' ? '○' : '·' }}</span>
                                <span class="mcp-assertion-name">{{ ax.name }}</span>
                                <span v-if="ax.detail" class="mcp-assertion-detail">{{ ax.detail }}</span>
                              </li>
                            </ul>
                          </div>

                          <!-- pass73.3.19 (2026-05-28) — Re-fire wired to
                               POST /admin/mcp-tester/refire-single. Splices
                               result back into results[] for instant feedback. -->
                          <div class="mcp-detail-actions">
                            <button
                              class="mcp-btn mcp-btn-tiny"
                              :class="refiring.has(row.tool) ? 'mcp-btn-loading' : 'mcp-btn-cyan'"
                              :disabled="refiring.has(row.tool)"
                              @click="refireOneTool(row.tool, row.tier)"
                              :title="tp('mcpTester.detail.refireTip', 'Re-fire {tool} now', { tool: row.tool })"
                            >{{ refiring.has(row.tool) ? '⟳ ' + tr('mcpTester.detail.firing', 'firing…') : '▶ ' + tr('mcpTester.cols.refire', 'Re-fire') }}</button>
                            <button
                              class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
                              @click="copyToClipboard(JSON.stringify(row, null, 2))"
                              :title="tr('mcpTester.detail.copyRowTip', 'Copy the entire row as JSON')"
                            >⎘ {{ tr('mcpTester.detail.copyRow', 'Copy row JSON') }}</button>
                            <!-- Pass 10 (2026-05-28) — Share permalink to this tool's row -->
                            <button
                              class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
                              @click="shareDeepLink(row.tool)"
                              :title="tr('mcpTester.detail.shareTip', 'Copy a permalink to this tool (it opens with the row expanded)')"
                            ><Icon name="mdi:source-branch" /> {{ tr('mcpTester.detail.share', 'Share') }}</button>
                            <!-- Flake badge if seen recently -->
                            <span v-if="flakeScoreFor(row.tool).failed > 0" class="mcp-flake-badge" :title="flakeScoreFor(row.tool).failed === 1 ? tr('mcpTester.detail.flakeTipOne', 'Failed once in recent runs: possibly flaky') : tp('mcpTester.detail.flakeTipMany', 'Failed {n} times in recent runs: possibly flaky', { n: flakeScoreFor(row.tool).failed })">
                              <Icon name="mdi:alert" /> {{ tp('mcpTester.detail.flake', 'flake {n}', { n: flakeScoreFor(row.tool).failed }) }}
                            </span>
                            <button
                              class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
                              @click="expandedRows.delete(row.tool); persistRowExpansion()"
                              :title="tr('mcpTester.detail.closeTip', 'Close detail')"
                            >✕ {{ tr('mcpTester.detail.close', 'Close') }}</button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </transition>
          </div>

          <!-- Empty states (Pass 4 2026-05-28); with no run loaded the tab waits above it (§MCPTEST30, V0541) -->
          <div
            v-if="categorizedFilteredResults.length === 0"
            class="mcp-empty mcp-empty--rich"
          >
            <span class="mcp-empty-icon">⌗</span>
            <div class="mcp-empty-body">
              <div class="mcp-empty-title">{{ tr('mcpTester.list.noMatch', 'No tools match your filters') }}</div>
              <div class="mcp-empty-detail">
                {{ results.length === 1 ? tr('mcpTester.list.filteredOne', '1 tool is loaded but filtered out.') : tp('mcpTester.list.filteredMany', '{n} tools are loaded but filtered out.', { n: results.length }) }}
                <button
                  class="mcp-empty-reset"
                  @click="filterText = ''; filterTier = ''; filterCategory = ''; onlyFailures = false; onlySlow = false"
                >{{ tr('mcpTester.list.clearFilters', 'Clear all filters') }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- TAB: Probes (§MCPTEST30, V0535) — the probe families of the loaded run: what each one's pass means, and how its
         rows came out. They lived in "Admin · Other" until this tab; a family opens in All tools filtered to it. -->
    <section v-if="activeTab === 'probes' && !awaitingRun" class="mcp-section" data-testid="mcp-probes">
      <div class="mcp-card">
        <div class="mcp-card-header">
          <span class="mcp-card-icon" aria-hidden="true"><Icon name="mdi:test-tube" /></span>
          {{ tr('mcpTester.probes.title', 'Probe families') }}
          <span class="mcp-card-meta">
            {{ probeMetaPhrases(probeTallies.length, probeRowCount, probeBugFinds).map((p) => tp(p.key, p.fallback, p.params)).join(' · ') }}
          </span>
        </div>
        <div v-if="probeTallies.length === 0" class="mcp-empty">
          <span class="mcp-empty-icon">—</span>
          {{ tr('mcpTester.probes.none', 'This run carries no probe checks: the federation and cloud-operator suites test tools and flows, the strict MCP sweep runs the probes.') }}
        </div>
        <div v-else class="mcp-probe-grid">
          <button
            v-for="f in probeTallies"
            :key="f.family.id"
            type="button"
            class="mcp-probe"
            :class="{ 'mcp-probe--bug': f.bugFinds > 0, 'mcp-probe--fail': f.failed > 0 }"
            :data-testid="`mcp-probe-${f.family.id}`"
            @click="openProbeFamily(f.family.label.fallback)"
          >
            <span class="mcp-probe-head">
              <span class="mcp-probe-name">{{ tr(f.family.label.key, f.family.label.fallback) }}</span>
              <span class="mcp-probe-count">{{ f.passed }}/{{ f.total }}</span>
            </span>
            <span class="mcp-probe-proves">{{ tr(f.family.proves.key, f.family.proves.fallback) }}</span>
            <span class="mcp-probe-tally">
              <span v-if="f.bugFinds > 0" class="mcp-cat-stat mcp-cat-stat--fail">{{ tp('mcpTester.probes.tallyBugFind', '{n} BUG-FIND', { n: f.bugFinds }) }}</span>
              <span v-if="f.failed > 0" class="mcp-cat-stat mcp-cat-stat--fail">{{ tp('mcpTester.probes.tallyFailed', '{n} failed', { n: f.failed }) }}</span>
              <span v-if="f.notMeasured > 0" class="mcp-cat-stat mcp-cat-stat--skip">{{ tp('mcpTester.probes.tallyNotMeasured', '{n} not measured', { n: f.notMeasured }) }}</span>
              <span v-if="f.bugFinds === 0 && f.failed === 0 && f.notMeasured === 0" class="mcp-cat-stat mcp-cat-stat--ok">{{ tr('mcpTester.probes.tallyHeld', 'all held') }}</span>
            </span>
          </button>
        </div>
      </div>
    </section>

    <!-- TAB: Not run — the two populations that are NOT passes and NOT failures.
         A coverage hole and a refusal look identical in a single number, so they
         stay reported apart, by name, with the reason attached to each. Moved off
         the All-tools tab (§MCPTEST-MCP11) because 21 denied rows buried the
         categories under a wall of text. -->
    <section v-if="activeTab === 'notrun' && !awaitingRun" class="mcp-section">
      <div v-if="skipped.length === 0 && policyDenied.length === 0" class="mcp-card">
        <div class="mcp-card-header">
          <span class="mcp-card-icon">◯</span>
          {{ tr('mcpTester.notRun.emptyTitle', 'Nothing was left out') }}
          <span class="mcp-card-meta">{{ tr('mcpTester.notRun.emptyMeta', 'every tool in the catalogue was invoked and graded') }}</span>
        </div>
      </div>

      <!-- Pass 11 (2026-05-28) — Skipped tools rationale card.
           Surfaces the typically-skipped endpoints with the per-tool reason
           so operators can opt-in via the teardown bucket. -->
      <div v-if="skipped.length > 0" class="mcp-card mcp-card--skip-rationale">
        <div class="mcp-card-header">
          <span class="mcp-card-icon">◯</span>
          {{ tr('mcpTester.notRun.skippedTitle', 'Skipped this run') }}
          <span class="mcp-card-meta">{{ skipped.length === 1 ? tr('mcpTester.notRun.skippedMetaOne', '1 row not measured, by why') : tp('mcpTester.notRun.skippedMetaMany', '{n} rows not measured, by why', { n: skipped.length }) }}</span>
        </div>
        <!-- §MCPTEST30 (V0535): grouped by why: a coverage hole someone can close, nothing to decide, left out on purpose -->
        <div v-for="g in skippedGroups" :key="g.kind" class="mcp-skip-group" :data-testid="`mcp-notrun-${g.kind}`">
          <div class="mcp-skip-group-head">
            <span class="mcp-skip-group-title">{{ tr(NOT_RUN_HEADINGS[g.kind].key, NOT_RUN_HEADINGS[g.kind].fallback) }}</span>
            <span class="mcp-skip-group-count">{{ g.rows.length }}</span>
            <span class="mcp-skip-group-note">{{ tr(NOT_RUN_HEADINGS[g.kind].noteKey, NOT_RUN_HEADINGS[g.kind].note) }}</span>
          </div>
          <ul class="mcp-skip-rationale-list">
            <li v-for="(s, i) in g.rows" :key="i">
              <code class="mcp-code" :title="s.tool">{{ s.tool.replace(/^theprotocol[._]/i, '') }}</code>
              <span class="mcp-skip-reason">{{ s.reason || s.skip_reason || tr('mcpTester.notRun.noRationale', 'no rationale given') }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- §MCPTEST-MCP10 — the other half of the old conflated list. These
           tools were never a coverage question: a standing operating rule
           forbids the harness from invoking them. -->
      <div v-if="policyDenied.length > 0" class="mcp-card mcp-card--skip-rationale">
        <div class="mcp-card-header">
          <span class="mcp-card-icon"><Icon name="mdi:gavel" aria-hidden="true" /></span>
          {{ tr('mcpTester.notRun.refusedTitle', 'Refused by standing order') }}
          <span class="mcp-card-meta">{{ policyDenied.length === 1 ? tr('mcpTester.notRun.refusedMetaOne', '1 tool never invoked, by rule') : tp('mcpTester.notRun.refusedMetaMany', '{n} tools never invoked, by rule', { n: policyDenied.length }) }}</span>
        </div>
        <ul class="mcp-skip-rationale-list">
          <li v-for="(s, i) in policyDenied" :key="i">
            <code class="mcp-code" :title="s.tool">{{ s.tool.replace(/^theprotocol[._]/i, '') }}</code>
            <span class="mcp-skip-reason">{{ s.reason || tr('mcpTester.notRun.refusedDefault', 'refused by operating rule') }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- TAB: Drift & integrity (was "Phase F drift") — wrapper / cross-frame / auth matrix detail surface -->
    <section v-if="activeTab === 'phasef' && !awaitingRun" class="mcp-section">
      <div class="mcp-card">
        <div class="mcp-card-header">
          <span class="mcp-card-icon">◇</span>
          {{ tr('mcpTester.tabs.phasef', 'Drift & integrity') }}
          <!-- §MCPTEST30 (V0541): a detector the run did not measure reads "not measured", never 0 -->
          <span class="mcp-card-meta" data-testid="mcp-drift-meta">
            <template v-for="(k, i) in DETECTOR_KEYS" :key="k">
              <span v-if="i > 0" aria-hidden="true"> · </span>
              <span :data-detector="k" :data-measured="detectorsRun[k] ? '1' : '0'">{{ tr(DETECTOR_TEXT[k].name.key, DETECTOR_TEXT[k].name.fallback) }}:
                <strong v-if="detectorsRun[k]">{{ detectorReading(k) }}</strong>
                <span v-else class="mcp-cell-muted">{{ tr('mcpTester.drift.notMeasured', 'not measured') }}</span></span>
            </template>
          </span>
        </div>
        <!-- §MCPTEST30 (V0547): the strict sweep says why its wrapper↔route check did not measure -->
        <p v-if="wrapperReason" class="mcp-cell-muted" data-testid="mcp-wrapper-reason" style="margin: 0 0 12px">
          {{ tr('mcpTester.drift.wrapperRoute', 'wrapper↔route') }}: {{ tr('mcpTester.drift.notMeasured', 'not measured') }} ({{ wrapperReason }})
        </p>

        <!-- emission_integrity HONESTY flag (2026-06-26) — ALWAYS rendered, even
             when the 4 Phase F detectors are clean: the whole point is that the
             strict pass-rate can stay green while cross-frame settlement /
             emission is broken. Real ES polls + mTLS handshake → per-check verdict. -->
        <div
          v-if="emissionIntegrity"
          class="mcp-card"
          :class="emissionIntegrityStatus === 'degraded' ? 'mcp-card--danger' : (emissionIntegrityStatus === 'warn' ? 'mcp-card--warning' : '')"
          style="margin-bottom: 14px"
        >
          <div class="mcp-card-header">
            <span class="mcp-card-icon">⊶</span> {{ tr('mcpTester.drift.integrityTitle', 'Emission & cross-frame integrity') }}
            <span
              class="mcp-badge"
              :class="emissionIntegrityStatus === 'degraded' ? 'mcp-badge--danger' : (emissionIntegrityStatus === 'warn' ? 'mcp-badge--warning' : 'mcp-badge--success')"
            >{{ emissionIntegrityStatus === 'degraded' ? tr('mcpTester.drift.statusDegraded', 'DEGRADED') : emissionIntegrityStatus === 'warn' ? tr('mcpTester.drift.statusWarn', 'WARN') : (emissionIntegrityStatus && emissionIntegrityStatus !== 'ok') ? emissionIntegrityStatus.toUpperCase() : tr('mcpTester.drift.statusOk', 'OK') }}</span>
            <span class="mcp-card-meta">{{ emissionIntegrity.summary }}</span>
          </div>
          <table class="mcp-table mcp-table--stack">
            <thead>
              <tr>
                <th style="width: 22%">{{ tr('mcpTester.cols.check', 'Check') }}</th>
                <th style="width: 12%">{{ tr('mcpTester.cols.status', 'Status') }}</th>
                <th>{{ tr('mcpTester.cols.detail', 'Detail') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in emissionIntegrityChecks" :key="c.name">
                <td><code class="mcp-code">{{ c.name }}</code></td>
                <td>
                  <span
                    class="mcp-badge"
                    :class="c.status === 'degraded' ? 'mcp-badge--danger' : (c.status === 'warn' ? 'mcp-badge--warning' : (c.status === 'ok' ? 'mcp-badge--success' : 'mcp-badge--muted'))"
                  >{{ (c.status || 'unknown').toUpperCase() }}</span>
                </td>
                <td class="mcp-cell-muted">{{ c.detail }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="phaseFTotalIssues === 0" class="mcp-empty mcp-empty--rich" data-testid="mcp-drift-clean">
          <span class="mcp-empty-icon" aria-hidden="true">{{ detectorsMeasured.length ? '✓' : '◯' }}</span>
          <div class="mcp-empty-body">
            <div class="mcp-empty-title">
              <template v-if="detectorsMeasured.length">
                {{ tr('mcpTester.drift.clean', 'Clean') }}: {{ detectorsMeasured.map((k) => tr(DETECTOR_TEXT[k].clean.key, DETECTOR_TEXT[k].clean.fallback)).join(' · ') }}.
              </template>
              <template v-else>{{ tr('mcpTester.drift.noneRun', 'This run measured no drift detector: the strict MCP sweep runs all three.') }}</template>
            </div>
            <div v-if="detectorsMeasured.length && detectorsUnmeasured.length" class="mcp-empty-detail">
              {{ tr('mcpTester.drift.notRunBy', 'Not measured by this suite') }}:
              {{ detectorsUnmeasured.map((k) => tr(DETECTOR_TEXT[k].name.key, DETECTOR_TEXT[k].name.fallback)).join(', ') }}.
            </div>
          </div>
        </div>
        <div v-else class="mcp-phasef-grid">
          <!-- F.3 wrapper↔route: §MCPTEST30 (V0547) the request survey's rows (tool, surface, the gated classes, what the
               route refused); a run before V0547 carries the static check's shape (method, path, wrapper_only, openapi_only) -->
          <div v-if="phaseFDetails.wrapper_drift_details?.length" class="mcp-card mcp-card--warning" data-testid="mcp-wrapper-drift">
            <div class="mcp-card-header">
              <span class="mcp-card-icon">⌧</span> F.3 · {{ tr('mcpTester.drift.wrapperCardTitle', 'Requests their own route refuses') }}
              <span class="mcp-card-meta">{{ phaseFDetails.wrapper_drift_details.length === 1 ? tr('mcpTester.drift.wrapperCardMetaOne', '1 tool') : tp('mcpTester.drift.wrapperCardMetaMany', '{n} tools', { n: phaseFDetails.wrapper_drift_details.length }) }}</span>
            </div>
            <table class="mcp-table mcp-table--stack">
              <thead>
                <tr>
                  <th style="width: 30%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                  <th style="width: 24%">{{ tr('mcpTester.drift.wrapperCardCheck', 'Check') }}</th>
                  <th>{{ tr('mcpTester.drift.wrapperCardRefused', 'What the route refused') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(d, i) in phaseFDetails.wrapper_drift_details" :key="i">
                  <td><code class="mcp-code">{{ d.tool }}</code></td>
                  <td v-if="Array.isArray(d.classes)" class="mcp-cell-mono" :data-label="tr('mcpTester.drift.wrapperCardCheck', 'Check')">{{ d.classes.join(' · ') }} <span class="mcp-cell-muted">{{ d.surface }}</span></td>
                  <td v-else class="mcp-cell-mono" :data-label="tr('mcpTester.drift.wrapperCardCheck', 'Check')">{{ d.method }} <span class="mcp-cell-muted">{{ d.path }}</span></td>
                  <td v-if="Array.isArray(d.classes)" class="mcp-cell-error" :data-label="tr('mcpTester.drift.wrapperCardRefused', 'What the route refused')">{{ d.detail }}</td>
                  <td v-else class="mcp-cell-error" :data-label="tr('mcpTester.drift.wrapperCardRefused', 'What the route refused')">
                    <span v-if="d.wrapper_only?.length">{{ tr('mcpTester.drift.wrapperOnly', 'documented by the wrapper, unknown to the route:') }} <code>{{ d.wrapper_only.join(', ') }}</code></span>
                    <br v-if="d.wrapper_only?.length && d.openapi_only?.length" />
                    <span v-if="d.openapi_only?.length">{{ tr('mcpTester.drift.routeOnly', 'accepted by the route, undocumented in the wrapper:') }} <code>{{ d.openapi_only.join(', ') }}</code></span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <!-- F.4 cross-frame parity -->
          <div v-if="phaseFDetails.cross_frame_drift_details?.length" class="mcp-card mcp-card--warning">
            <div class="mcp-card-header">
              <span class="mcp-card-icon">⇋</span> {{ tr('mcpTester.drift.f4Title', 'F.4 · target vs peer frame shape divergence') }}
              <span class="mcp-card-meta">{{ detectorReading('cross_frame') }}</span>
            </div>
            <table class="mcp-table mcp-table--stack">
              <thead>
                <tr>
                  <th style="width: 35%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                  <th>{{ tr('mcpTester.cols.keysOnlyTarget', 'Keys only on the target') }}</th>
                  <th>{{ tr('mcpTester.cols.keysOnlyPeer', 'Keys only on the peer') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(d, i) in phaseFDetails.cross_frame_drift_details" :key="i">
                  <td><code class="mcp-code">{{ d.tool }}</code></td>
                  <td class="mcp-cell-error" :data-label="tr('mcpTester.cols.onlyTarget', 'only on the target')">{{ (d.only_in_a || []).join(', ') || '—' }}</td>
                  <td class="mcp-cell-error" :data-label="tr('mcpTester.cols.onlyPeer', 'only on the peer')">{{ (d.only_in_b || []).join(', ') || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <!-- F.1 auth-matrix violations -->
          <div v-if="phaseFDetails.auth_matrix_failed_tools?.length" class="mcp-card mcp-card--danger">
            <div class="mcp-card-header">
              <span class="mcp-card-icon"><Icon name="mdi:alert" /></span> {{ tr('mcpTester.drift.f1Title', 'F.1 · Tools that accepted a wrong-tier credential (privilege escalation)') }}
              <span class="mcp-card-meta">{{ phaseFDetails.auth_matrix_failed_tools.length === 1 ? tr('mcpTester.drift.f1MetaOne', '1 violation') : tp('mcpTester.drift.f1MetaMany', '{n} violations', { n: phaseFDetails.auth_matrix_failed_tools.length }) }}</span>
            </div>
            <div class="mcp-phasef-list">
              <code v-for="(t, i) in phaseFDetails.auth_matrix_failed_tools" :key="i" class="mcp-code mcp-phasef-chip" :title="tr('mcpTester.drift.f1ChipTip', 'tool (wrong-tier credential → HTTP status)')">{{ t }}</code>
            </div>
          </div>
          <!-- §MCPTEST30 (V0545): a mutation whose read-after-write answered 2xx without any key its check reads judged
               nothing (the mTLS toggle read `enabled` for months from a route that answers `enrolled`) -->
          <div v-if="unjudgedReadBacks.length" class="mcp-card mcp-card--warning" data-testid="mcp-unjudged-read-backs">
            <div class="mcp-card-header">
              <span class="mcp-card-icon"><Icon name="mdi:alert" /></span>
              {{ tr('mcpTester.drift.unjudgedTitle', 'Read-after-write checks that judged nothing') }}
              <span class="mcp-card-meta">{{ unjudgedReadBacks.length === 1 ? tr('mcpTester.drift.unjudgedMetaOne', '1 mutation: the read answered without any key its check reads') : tp('mcpTester.drift.unjudgedMetaMany', '{n} mutations: the read answered without any key its check reads', { n: unjudgedReadBacks.length }) }}</span>
            </div>
            <div class="mcp-phasef-list">
              <code v-for="t in unjudgedReadBacks" :key="t" class="mcp-code mcp-phasef-chip">{{ t.replace('theprotocol_', '') }}</code>
            </div>
          </div>
          <!-- pass73.3.19 (2026-05-28) — F.2 latency regressions detail
               (was just a count before; now backend ships the full per-tool
               list with baseline + factor). -->
          <div v-if="phaseFDetails.latency_regressions_details?.length" class="mcp-card mcp-card--warning">
            <div class="mcp-card-header">
              <span class="mcp-card-icon"><Icon name="mdi:timer-sand" /></span> {{ tr('mcpTester.drift.f2Title', 'F.2 · Latency regressions') }}
              <!-- §MCPTEST30 (V0544): a tool is flagged beyond twice the WHOLE run's slowdown (the box, not a tool) -->
              <span class="mcp-card-meta" data-testid="mcp-latency-meta">{{ phaseFDetails.latency_regressions_details.length === 1 ? tr('mcpTester.drift.f2MetaOne', '1 tool > 2× baseline') : tp('mcpTester.drift.f2MetaMany', '{n} tools > 2× baseline', { n: phaseFDetails.latency_regressions_details.length }) }}<template
                v-if="typeof summary?.latency_run_factor === 'number' && summary.latency_run_factor > 1.05"> · {{
                  tp('mcpTester.drift.runFactor', 'the whole run ran {f}× its baseline: flagged beyond twice that', { f: summary.latency_run_factor })
                }}</template></span>
            </div>
            <table class="mcp-table mcp-table--stack">
              <thead>
                <tr>
                  <th style="width: 50%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                  <th style="width: 12%; text-align:right">{{ tr('mcpTester.cols.now', 'Now') }}</th>
                  <th style="width: 12%; text-align:right">{{ tr('mcpTester.cols.baseline', 'Baseline') }}</th>
                  <th style="width: 12%; text-align:right">{{ tr('mcpTester.cols.factor', 'Factor') }}</th>
                  <th style="width: 14%"><span class="mcp-sr-only">{{ tr('mcpTester.cols.refire', 'Re-fire') }}</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(d, i) in latencyRegressionsSorted" :key="i">
                  <td><code class="mcp-code">{{ d.tool }}</code></td>
                  <td style="text-align:right" class="mcp-cell-mono" :data-label="tr('mcpTester.cols.now', 'Now')">{{ d.elapsed }}ms</td>
                  <td style="text-align:right" class="mcp-cell-muted" :data-label="tr('mcpTester.cols.baseline', 'Baseline')">{{ d.baseline_ms }}ms</td>
                  <td style="text-align:right" :data-label="tr('mcpTester.cols.factor', 'Factor')">
                    <span class="mcp-badge" :class="d.factor >= 5 ? 'mcp-badge--danger' : d.factor >= 3 ? 'mcp-badge--warning' : 'mcp-badge--muted'">
                      {{ d.factor }}×
                    </span>
                  </td>
                  <td>
                    <button
                      class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
                      :disabled="refiring.has(d.tool)"
                      :title="`Re-fire ${d.tool}`"
                      @click="refireOneTool(d.tool)"
                    >{{ refiring.has(d.tool) ? '⟳ firing…' : '▶ Re-fire' }}</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <!-- §MCPTEST30 (V0547): the build gate's named exceptions: refused requests the gate names with a reason, not counted -->
        <div v-if="detectorsRun.wrapper_route && wrapperKnown.length" class="mcp-card" data-testid="mcp-wrapper-known" style="margin-top: 14px">
          <div class="mcp-card-header">
            <span class="mcp-card-icon">⌧</span> F.3 · {{ tr('mcpTester.drift.knownTitle', 'Named exceptions of the build gate') }}
            <span class="mcp-card-meta">{{ tr('mcpTester.drift.knownMeta', 'not counted: the gate names each with its reason') }}</span>
          </div>
          <table class="mcp-table mcp-table--stack">
            <thead>
              <tr>
                <th style="width: 30%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                <th>{{ tr('mcpTester.drift.knownWhy', 'Why the gate names it') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="k in wrapperKnown" :key="k.tool">
                <td><code class="mcp-code">{{ k.tool }}</code></td>
                <td class="mcp-cell-muted" :data-label="tr('mcpTester.drift.knownWhy', 'Why the gate names it')">{{ k.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <!-- §MCPTEST30 (V0547): tools whose route authenticates only a federation peer (the survey's PEER_ROUTE): no MCP
             caller can succeed with them. Reported, not counted -->
        <div v-if="detectorsRun.wrapper_route && wrapperPeerOnly.length" class="mcp-card mcp-card--warning" data-testid="mcp-wrapper-peer" style="margin-top: 14px">
          <div class="mcp-card-header">
            <span class="mcp-card-icon">⌧</span> F.3 · {{ tr('mcpTester.drift.peerTitle', 'Tools no MCP caller can succeed with') }}
            <span class="mcp-card-meta">{{ wrapperPeerOnly.length === 1 ? tr('mcpTester.drift.peerMetaOne', '1 tool: the route serves only a federation peer · reported, not counted') : tp('mcpTester.drift.peerMetaMany', '{n} tools: the route serves only a federation peer · reported, not counted', { n: wrapperPeerOnly.length }) }}</span>
          </div>
          <details class="mcp-fold" :open="wrapperPeerOnly.length <= 5" data-testid="mcp-wrapper-peer-list">
            <summary>{{ wrapperPeerOnly.length === 1 ? tr('mcpTester.drift.peerListOne', 'The tool and the route it calls') : tp('mcpTester.drift.peerListMany', 'The {n} tools and the route each calls', { n: wrapperPeerOnly.length }) }}</summary>
          <table class="mcp-table mcp-table--stack">
            <thead>
              <tr>
                <th style="width: 30%">{{ tr('mcpTester.cols.tool', 'Tool') }}</th>
                <th style="width: 10%">{{ tr('mcpTester.drift.peerSurface', 'Surface') }}</th>
                <th>{{ tr('mcpTester.drift.peerRoute', 'The route it calls') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="k in wrapperPeerOnly" :key="k.tool">
                <td><code class="mcp-code">{{ k.tool }}</code></td>
                <td class="mcp-cell-muted" :data-label="tr('mcpTester.drift.peerSurface', 'Surface')">{{ k.surface }}</td>
                <td class="mcp-cell-muted" :data-label="tr('mcpTester.drift.peerRoute', 'The route it calls')">{{ k.detail }}</td>
              </tr>
            </tbody>
          </table>
          </details>
        </div>
      </div>
    </section>

    <!-- TAB: Recent runs history -->
    <section v-if="activeTab === 'history'" class="mcp-section">
      <div class="mcp-card">
        <div class="mcp-card-header">
          <span class="mcp-card-icon"><Icon name="mdi:timer-sand" /></span>
          {{ tr('mcpTester.history.title', 'Recent runs') }}
          <span class="mcp-card-meta">{{ tp('mcpTester.history.countMeta', '{n} in history', { n: runHistory.length }) }}</span>
          <!-- §FESUITE: the console suite's runs are not in this history; they have their own page -->
          <router-link to="/admin/console-suite" class="mcp-meta-link mcp-history-xlink" data-testid="mcp-history-to-console-suite">
            <Icon name="mdi:monitor-cellphone" class="mcp-meta-link-icon" aria-hidden="true" />{{ tr('mcpTester.head.toConsoleSuite', 'Console suite runs') }}
          </router-link>
        </div>
        <div v-if="runHistory.length === 0" class="mcp-empty">
          <span class="mcp-empty-icon">—</span>
          {{ tr('mcpTester.history.empty', 'No runs yet on this registry.') }}
        </div>
        <!-- Phase E.3 — trajectory sparkline: pass-rate evolution -->
        <div v-if="trajectoryPoints.length >= 2" class="mcp-trajectory">
          <div class="mcp-trajectory-label">
            {{ tp('mcpTester.history.trajectory', 'Pass-rate trajectory · {flow}', { flow: trajectoryFlow === 'flow_playwright_console_lifecycles' && trajectoryTarget
              ? `${flowShortLabel(trajectoryFlow)} · ${trajectoryTarget}` : flowShortLabel(trajectoryFlow) }) }}
            <span class="mcp-cell-muted">
              ({{ trajectoryPoints[0].pct.toFixed(2) }}% → {{ trajectoryPoints[trajectoryPoints.length - 1].pct.toFixed(2) }}%)
            </span>
          </div>
          <svg class="mcp-trajectory-svg" :viewBox="`0 0 ${trajectorySvgW} ${trajectorySvgH}`" preserveAspectRatio="none">
            <polyline
              :points="trajectoryPolyline"
              fill="none"
              stroke="var(--nc-primary, var(--cyan, #22d3ee))"
              stroke-width="1.5"
            />
            <circle
              v-for="(p, idx) in trajectoryPoints"
              :key="idx"
              :cx="p.x"
              :cy="p.y"
              r="2.5"
              fill="var(--nc-primary, var(--cyan, #22d3ee))"
            />
          </svg>
        </div>
        <!-- §MCPTEST30 (V0539): on a phone each run is a small card (the table cut off at Status, the pass rate unseen) -->
        <table v-if="runHistory.length > 0" class="mcp-table mcp-history-table">
          <thead>
            <tr>
              <th style="width: 36px">⇋</th>
              <th>{{ tr('mcpTester.cols.runId', 'Run ID') }}</th>
              <th style="width: 96px">{{ tr('mcpTester.cols.suite', 'Suite') }}</th>
              <th style="width: 100px">{{ tr('mcpTester.cols.status', 'Status') }}</th>
              <th style="width: 156px">{{ tr('mcpTester.cols.started', 'Started') }}</th>
              <th style="width: 80px">{{ tr('mcpTester.cols.wall', 'Wall') }}</th>
              <th style="width: 180px"
                  :title="tr('mcpTester.history.passRateTip', 'Every suite keeps its own figure: the MCP, federation and cloud-operator flows divide by every row (a row not run counts against them), the console suite by the steps it measured. The bar under it is what the figure divides: passed, refused by rule, not measured, failed. Red is a failed row or a bug-find; amber, a fall from the previous run of the same suite on the same target.')">
                {{ tr('mcpTester.cols.passRate', 'Pass rate') }}</th>
              <th style="width: 80px">BUG-FIND</th>
              <th style="width: 150px"><span class="mcp-sr-only">{{ tr('mcpTester.cols.actions', 'Actions') }}</span></th>
            </tr>
          </thead>
          <tbody>
            <!-- §SUITES1018: one reading per row (historyRows) -->
            <tr v-for="{ run, cell, delta, why, cls } in historyRows" :key="run.run_id">
              <!-- pass73.3.19 — checkbox-select 2 runs to diff -->
              <td class="h-cmp">
                <input
                  type="checkbox"
                  :checked="diffSelection.includes(run.run_id)"
                  :disabled="!diffSelection.includes(run.run_id) && diffSelection.length >= 2"
                  @change="toggleDiffSelection(run.run_id)"
                  :title="tr('mcpTester.history.compareTip', 'Select up to 2 runs to compare')"
                  :aria-label="tp('mcpTester.history.compareAria', 'Compare run {id}', { id: run.run_id })"
                />
              </td>
              <td class="h-id"><code class="mcp-code">{{ run.run_id }}</code></td>
              <td class="h-suite">
                <span class="mcp-badge mcp-badge--info mcp-badge--suite"
                      :title="run.flow_label || run.flow_name || 'flow_mcp_lifecycle_complete'">
                  {{ flowShortLabel(run.flow_name) }}
                </span>
                <span v-if="consoleTarget(run)" class="mcp-hist-target">{{ consoleTarget(run) }}</span>
              </td>
              <td class="h-status">
                <!-- §MCPTEST30 (V0539): a record that still says 'running' hours after its start never recorded its finish -->
                <span class="mcp-badge" :class="'mcp-badge--' + statusBadge(historyStatus(run.status, run.started_at, nowTick / 1000))"
                      :title="historyStatus(run.status, run.started_at, nowTick / 1000) === 'unfinished'
                        ? tp('mcpTester.history.unfinishedTip', 'Started {started}; no finish was recorded, and no suite runs this long.', { started: fmtStarted(run.started_at) })
                        : undefined"
                      :data-testid="`mcp-history-status-${run.run_id}`">
                  {{ historyStatus(run.status, run.started_at, nowTick / 1000) === 'unfinished'
                    ? tr('mcpTester.history.unfinished', 'unfinished') : run.status }}
                </span>
              </td>
              <td class="mcp-cell-mono h-started">
                {{ fmtStarted(run.started_at) }}
              </td>
              <td class="mcp-cell-mono h-wall">
                {{ fmtDuration(runWallSeconds(run)) }}
              </td>
              <td class="mcp-cell-mono h-pass">
                <template v-if="run.summary && cell">
                  <span :class="cls" :title="historyPassTitle(run, cell)" :data-testid="`mcp-history-pass-${run.run_id}`">{{ cell.reading.pct.toFixed(2) }}%</span>
                  <span v-if="cell.fraction" class="mcp-cell-muted" style="font-size: 10px;">
                    ({{ cell.fraction.num }}/{{ cell.fraction.den }})
                  </span>
                  <span v-if="delta" class="mcp-delta" :class="`mcp-delta--${deltaKind(delta.delta)}`"
                        :title="tp('mcpTester.history.deltaTip', 'Against the previous run of this suite, {prev}', { prev: delta.prevId })"
                        :data-testid="`mcp-history-delta-${run.run_id}`">{{ fmtDelta(delta.delta) }}</span>
                  <!-- §SUITES1018: what the figure divides, in the category bar's parts (the green part is the figure) -->
                  <span class="mcp-hist-bar" aria-hidden="true" :data-testid="`mcp-history-bar-${run.run_id}`">
                    <span class="mcp-cat-bar-fill mcp-cat-bar-fill--green" :style="{ width: cell.bar.pass + '%' }"></span>
                    <span class="mcp-cat-bar-fill mcp-cat-bar-fill--rule" :style="{ width: cell.bar.byRule + '%' }"></span>
                    <span class="mcp-cat-bar-fill mcp-cat-bar-fill--skip" :style="{ width: cell.bar.skip + '%' }"></span>
                    <span class="mcp-cat-bar-fill mcp-cat-bar-fill--red" :style="{ width: cell.bar.fail + '%' }"></span>
                  </span>
                  <span v-if="why.length" class="mcp-hist-why" :data-testid="`mcp-history-why-${run.run_id}`">
                    <template v-for="(w, i) in why" :key="w.kind">{{ i > 0 ? ' · ' : '' }}<span
                      :class="w.kind === 'failed' ? 'mcp-hist-why--bad' : undefined">{{ w.text }}</span></template>
                  </span>
                </template>
                <span v-else>—</span>
              </td>
              <td class="mcp-cell-mono h-bug" data-label="BUG-FIND">
                <span v-if="run.summary && run.summary.bug_finds > 0" class="text-danger">
                  {{ run.summary.bug_finds }}
                </span>
                <span v-else class="mcp-cell-muted">0</span>
              </td>
              <td class="h-act">
                <button class="mcp-link" @click="viewRun(run.run_id)">{{ tr('mcpTester.history.view', 'View') }} →</button>
                <button
                  v-if="!diffSelection.includes(run.run_id)"
                  class="mcp-link"
                  style="margin-left: 8px"
                  :title="tp('mcpTester.history.diffTip', 'Diff this run with the current view ({current})', { current: latestRunId || '—' })"
                  @click="diffWithCurrent(run.run_id)"
                  :disabled="!latestRunId || latestRunId === run.run_id"
                >Δ {{ tr('mcpTester.history.vsCurrent', 'vs current') }}</button>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- pass73.3.19 — Diff panel -->
        <div v-if="diffSelection.length === 2 || diffResult" class="mcp-card mcp-card--diff">
          <div class="mcp-card-header">
            <span class="mcp-card-icon">Δ</span>
            {{ tr('mcpTester.history.diffTitle', 'Run diff') }}
            <span class="mcp-card-meta">
              <code class="mcp-code">{{ diffSelection[0] || '?' }}</code>
              →
              <code class="mcp-code">{{ diffSelection[1] || '?' }}</code>
            </span>
            <button
              class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
              style="margin-left:auto"
              :disabled="diffLoading"
              @click="runDiff()"
            >⟳ {{ diffLoading ? tr('mcpTester.history.computing', 'computing…') : tr('mcpTester.history.compute', 'Compute diff') }}</button>
            <button
              class="mcp-btn mcp-btn-ghost mcp-btn-tiny"
              @click="diffSelection = []; diffResult = null"
            >✕ {{ tr('mcpTester.events.clear', 'Clear') }}</button>
          </div>
          <div v-if="diffResult" class="mcp-diff-grid">
            <div class="mcp-diff-cell mcp-diff-cell--fail">
              <div class="mcp-diff-cell-title">{{ tr('mcpTester.history.newlyFailing', 'Newly failing') }}</div>
              <div class="mcp-diff-cell-count">{{ diffResult.newly_failing.length }}</div>
              <div class="mcp-diff-cell-list">
                <code v-for="(d, i) in diffResult.newly_failing.slice(0, 12)" :key="i" class="mcp-code">{{ d.tool }}</code>
                <span v-if="diffResult.newly_failing.length > 12" class="mcp-cell-muted">{{ tp('mcpTester.history.more', '… +{n} more', { n: diffResult.newly_failing.length - 12 }) }}</span>
              </div>
            </div>
            <div class="mcp-diff-cell mcp-diff-cell--pass">
              <div class="mcp-diff-cell-title">{{ tr('mcpTester.history.newlyPassing', 'Newly passing') }}</div>
              <div class="mcp-diff-cell-count">{{ diffResult.newly_passing.length }}</div>
              <div class="mcp-diff-cell-list">
                <code v-for="(d, i) in diffResult.newly_passing.slice(0, 12)" :key="i" class="mcp-code">{{ d.tool }}</code>
                <span v-if="diffResult.newly_passing.length > 12" class="mcp-cell-muted">{{ tp('mcpTester.history.more', '… +{n} more', { n: diffResult.newly_passing.length - 12 }) }}</span>
              </div>
            </div>
            <div class="mcp-diff-cell mcp-diff-cell--warn">
              <div class="mcp-diff-cell-title">{{ tr('mcpTester.history.latencyRegressed', 'Latency regressed (>1.5×)') }}</div>
              <div class="mcp-diff-cell-count">{{ diffResult.latency_regressed.length }}</div>
              <div class="mcp-diff-cell-list">
                <div v-for="(d, i) in diffResult.latency_regressed.slice(0, 8)" :key="i" class="mcp-diff-row">
                  <code class="mcp-code">{{ d.tool }}</code>
                  <span class="mcp-cell-mono">{{ d.a_ms }}ms → {{ d.b_ms }}ms ({{ d.factor }}×)</span>
                </div>
              </div>
            </div>
            <div class="mcp-diff-cell mcp-diff-cell--info">
              <div class="mcp-diff-cell-title">{{ tr('mcpTester.history.latencyImproved', 'Latency improved') }}</div>
              <div class="mcp-diff-cell-count">{{ diffResult.latency_improved.length }}</div>
              <div class="mcp-diff-cell-list">
                <div v-for="(d, i) in diffResult.latency_improved.slice(0, 8)" :key="i" class="mcp-diff-row">
                  <code class="mcp-code">{{ d.tool }}</code>
                  <span class="mcp-cell-mono">{{ d.a_ms }}ms → {{ d.b_ms }}ms ({{ d.factor }}×)</span>
                </div>
              </div>
            </div>
            <div class="mcp-diff-cell mcp-diff-cell--muted">
              <div class="mcp-diff-cell-title">{{ tr('mcpTester.history.unchanged', 'Unchanged') }}</div>
              <div class="mcp-diff-cell-count">{{ diffResult.unchanged_count }}</div>
              <div class="mcp-diff-cell-list">
                <span class="mcp-cell-muted">{{ tr('mcpTester.history.unchangedNote', 'tools with the same status and a similar latency') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer-style architecture note -->
    <section class="mcp-section mcp-footer-note">
      <div class="mcp-footer-grid">
        <div>
          <div class="mcp-footer-key">{{ tr('mcpTester.footer.architecture', 'ARCHITECTURE') }}</div>
          <div class="mcp-footer-val">
            {{ summary && contractsCounted ? tp('mcpTester.footer.archLifecyclesCounted', 'Lifecycles chain real mutations over explicit contracts ({n} in this run).', { n: summary.explicit_contracts }) : tr('mcpTester.footer.archLifecycles', 'Lifecycles chain real mutations over explicit contracts.') }}
            {{ tr('mcpTester.footer.archCatch', 'Read-after-write verifiers catch silent NO-OPs; a tier-set static analyser catches dispatch drift; an empty-args fallback reaches every remaining tool.') }}
            {{ tr('mcpTester.footer.archHealthy', 'A 4xx on a healthy tool is an intentional coverage probe: judge by the healthy field, not by the raw status code.') }}
          </div>
        </div>
        <div v-if="sandboxRole === 'sandbox'">
          <div class="mcp-footer-key">{{ tr('mcpTester.head.target', 'TARGET') }}</div>
          <div class="mcp-footer-val">
            {{ tr('mcpTester.sandbox.footerTarget', 'This frame is the sandbox its frame stood up. The sweep runs against this frame itself, so every write a test makes lands here and never on the frame that made it.') }}
          </div>
        </div>
        <div v-if="showsTargetChips(sandboxRole)">
          <div class="mcp-footer-key">{{ tr('mcpTester.footer.proxy', 'PROXY') }}</div>
          <div class="mcp-footer-val">
            {{ tp('mcpTester.footer.proxyOrigin', 'This view runs from {origin}.', { origin: originHostname }) }}
            {{ tp('mcpTester.footer.proxyBody', 'The backend’s API_TEST_TARGET_URL ({target}) is always a sandbox. It is hard-coded inside the runner: even if every other layer were bypassed, the sweep would still hit sandbox containers.', { target: targetUrl || '?' }) }}
          </div>
        </div>
        <div>
          <div class="mcp-footer-key">{{ tr('mcpTester.footer.docs', 'DOCS') }}</div>
          <div class="mcp-footer-val">
            {{ sandboxRole === 'none' ? tr('mcpTester.footer.docsNone', 'The architecture, the source-tree layout and the rebuild cycle are described in:') : tr('mcpTester.footer.docsKit', 'The loop this sweep belongs to (a sandbox stood up from your own frame, a baseline on the release, your build on top of it, and the comparison that has to show no new red) is described in:') }}
            <code>{{ docsPath }}</code>
          </div>
        </div>
      </div>
    </section>

    <!-- Pass 9 (2026-05-28) — Re-fire toast STACK (queue) -->
    <div class="mcp-toast-stack">
      <transition-group name="mcp-toast" tag="div">
        <div
          v-for="t in refireToasts"
          :key="t.id"
          class="mcp-toast"
          :class="t.healthy ? 'mcp-toast--ok' : 'mcp-toast--bad'"
          @click="dismissToast(t.id)"
        >
          <span class="mcp-toast-icon"><Icon v-if="t.kind === 'share'" name="mdi:link-variant" /><template v-else>{{ t.healthy ? '✓' : '✗' }}</template></span>
          <span class="mcp-toast-msg">
            <template v-if="t.kind === 'share'">
              {{ tr('mcpTester.toast.linkCopied', 'Link copied:') }} <code>{{ t.tool }}</code>
            </template>
            <template v-else>
              {{ tr('mcpTester.toast.refired', 'Re-fired:') }} <code>{{ t.tool }}</code>
              <strong>{{ t.healthy ? 'OK' : tr('mcpTester.toast.fail', 'FAIL') }}</strong>
              <span v-if="t.status" class="mcp-toast-status">[{{ t.status }}]</span>
              ({{ t.elapsed }}ms)
            </template>
          </span>
          <span class="mcp-toast-dismiss">×</span>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<script setup lang="ts">
import McpSandboxPanel from '@/components/admin/McpSandboxPanel.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { openSse, type SseHandle } from '@/services/sse'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAlive } from '@/composables/useAlive'
import {
  mcpTesterApi,
  type McpTesterRun,
  type McpTesterRunMeta,
  type McpTesterToolRow,
  type McpTesterSummary,
} from '@/services/api/mcpTester'
import { useAuthStore } from '@/stores/auth'
import { useLogger } from '@/composables/useLogger'
import JsonViewer from '@/components/common/JsonViewer.vue'

import { ROLE_BADGE, ROLE_LEAD, docsPathFor, showsTargetChips } from '@/services/mcpTester/role'
// §MCPTEST30 (V0535): the probe families, the categories of rows that are not tools, and how a run is read
import { tallyFamilies } from '@/services/mcpTester/probeFamilies'
import { rowLabel, rowKinds, rowKindPhrases, probeMetaPhrases } from '@/services/mcpTester/categories'
import {
  foldHeartbeats, runWallSeconds, fmtDuration, suiteTrend, groupNotRun, barSegments, DEFAULT_FLOW,
  acceptStreamedLine, silentSince,
  readPassRate, passFraction, rowOutcome, tallyOutcomes, suiteDelta, historyStatus, namedEntries,
  readDetectors, DETECTOR_KEYS, awaitsRun, historyCell, targetOf,
  type NotRunKind, type RowOutcome, type TrendRun, type DetectorKey, tileReading, latencyMeasured,
  type HistoryCell, type RunCounts, readRefusalOnly, isRefusalOnly, type RefusalOnlyReading,
} from '@/services/mcpTester/runReading'
// §MCPTEST30 (V0549): how deep the passes were checked (summary.pass_depth)
import { readPassDepth, PASS_DEPTH_TEXT } from '@/services/mcpTester/passDepth'
// §MCPTEST30 (V0550): what the target switched off (summary.target_switches, switched_off_rows)
import { readTargetSwitches } from '@/services/mcpTester/targetSwitches'
import { assertionsForRow as readAxes, bugFindTaxonomy as readBugFindTaxonomy, type Say } from '@/services/mcpTester/assertions'
import { categorizeTool } from '@/services/mcpTester/toolCategory'
import { liveOld } from '@/services/ledgerNames'
import {
  filterRows, isLenientPass, latencyStats, statusDistribution as readStatusDistribution, SLOW_THRESHOLD_MS,
  type StatusBucket,
} from '@/services/mcpTester/listReading'

const log = useLogger('AdminMcpTester')
const auth = useAuthStore()

// ─── Origin awareness ────────────────────────────────────────────────────

const originHostname = computed(() =>
  typeof window !== 'undefined' ? window.location.host : 'unknown'
)

const isProdHost = computed(() => {
  const h = originHostname.value.toLowerCase()
  // Production hosts: every *.theprotocol.cloud console and the operators' subdomains
  return (
    h.includes('theprotocol.cloud') ||
    h.includes('agentvault.com')
  )
})

const isSandboxHost = computed(() => {
  const h = originHostname.value.toLowerCase()
  return (
    h.includes('localhost:8002') ||
    h.includes('localhost:8003') ||
    h.includes('sandbox') ||
    h === 'localhost'
  )
})

// True iff (1) backend confirmed the sweep target is sandbox, AND (2) we either
// hosted from sandbox directly OR ran from prod where backend will proxy.
const isSandboxEffective = computed(() => {
  // If we haven't gotten backend confirmation yet, trust origin signals
  if (targetUrl.value === '') return true
  return isSandboxBackend.value
})

const modeLabel = computed(() => {
  if (sandboxRole.value === 'sandbox') return isSandboxBackend.value ? tr('mcpTester.head.modeDirectSelf', 'DIRECT → this frame') : tr('mcpTester.head.modeRefused', 'REFUSED: not a sandbox')
  if (!targetUrl.value) return tr('mcpTester.head.modeDetecting', 'detecting…')
  if (isProdHost.value && isSandboxBackend.value) return tr('mcpTester.head.modeProxied', 'PROXIED → sandbox')
  if (isSandboxHost.value && isSandboxBackend.value) return tr('mcpTester.head.modeDirect', 'DIRECT → sandbox')
  if (!isSandboxBackend.value) return tr('mcpTester.head.modeRefused', 'REFUSED: not a sandbox')
  return 'OK'
})

const originBadge = computed(() => {
  if (isProdHost.value) return tr('mcpTester.head.originProd', 'PRODUCTION ORIGIN · PROXIED')
  if (isSandboxHost.value) return tr('mcpTester.head.originSandbox', 'SANDBOX ORIGIN · DIRECT')
  return tr('mcpTester.head.originUnknown', 'UNKNOWN ORIGIN')
})

// ─── Run state ───────────────────────────────────────────────────────────

const isRunning      = ref(false)
const latestRunId    = ref<string | null>(null)
// §pass73.3.19 — which suite to run (MCP tester / federation / cloud-op sweeps).
const selectedFlow   = ref<string>('flow_mcp_lifecycle_complete')
const availableFlows = ref<{ flow_name: string; label: string }[]>([
  { flow_name: 'flow_mcp_lifecycle_complete', label: 'MCP Tester — sandbox-A' },
])
const selectedFlowLabel = computed(() =>
  availableFlows.value.find(f => f.flow_name === selectedFlow.value)?.label || tr('mcpTester.controls.fullSweep', 'full sweep'))
const targetUrl      = ref<string>('')
// §TESTBED: what the sandbox panel says this frame is (a `t` loop variable lives in this template: translate is `tr`)
const { t: tr, tp } = useI18n()
const sandboxRole = ref<'parent' | 'sandbox' | 'none'>('none')
const isSandboxBackend = ref<boolean>(true)
// §MCPTEST30 (V0541): true once the console itself said its target and posture (GET /flows)
const postureFromBackend = ref(false)

// §TESTBED: a frame that knows its own role says so; only a frame that does not (the development
// host, where this page was born) falls back to reading its hostname.
const heroBadge = computed(() => {
  const phrase = sandboxRole.value === 'none' ? null : ROLE_BADGE[sandboxRole.value]
  return phrase ? tr(phrase.key, phrase.fallback) : originBadge.value
})
const heroLead = computed(() => {
  const phrase = sandboxRole.value === 'none' ? null : ROLE_LEAD[sandboxRole.value]
  return phrase ? tr(phrase.key, phrase.fallback) : ''
})
const docsPath = computed(() => docsPathFor(sandboxRole.value))

// pass73.3.19 (2026-05-28) — Cross-target switcher.
// Each entry has a `url` that points at THAT instance's MCP tester. Chips
// open in new tab (except the active one). Hard-coded to known sandbox
// + cloud-op ports; could become dynamic if backend exposes a list.
const summary        = ref<McpTesterSummary | null>(null)
const logLines       = ref<{ ts: number; msg: string }[]>([])
const bugFinds       = ref<{ tool: string; error: string }[]>([])
const hardFails      = ref<{ tool: string; error: string }[]>([])
const skipped        = ref<{ tool: string; reason: string }[]>([])
// §MCPTEST-MCP10 — refused-by-standing-order, deliberately a SEPARATE list
// from `skipped`: a coverage hole is work owed, a policy denial is work declined.
const policyDenied   = ref<{ tool: string; reason: string }[]>([])
const results        = ref<McpTesterToolRow[]>([])
const runHistory     = ref<McpTesterRunMeta[]>([])
const filterText     = ref('')
const filterTier     = ref('')
const startedAt      = ref<number | null>(null)
// §MCPTEST30 (V0535): the loaded run's finish; with startedAt, its wall time (a federation summary's wall_s is a sum)
const finishedAt     = ref<number | null>(null)
const nowTick        = ref(Date.now())

const logScroll = ref<HTMLElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
let eventSource: SseHandle | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null

// ─── Sandbox EventStore live stream ──────────────────────────────────────
// 2026-05-28 (Pass 1 revisited) — verified empirically: /api/v1/ws/events
// is the registry process's `system.events` broadcast (event_emitter.py:480)
// which catches ONLY events emitted FROM the registry process. TEG-layer
// events (TokensTransferred from canary transfers, fees, etc.) emit through
// TEG's own event_emitter directly to ES via mTLS — they NEVER hit the
// registry's broadcast manager. So a direct browser → /ws/events sees no
// TEG/financial flow events.
//
// The SSE proxy at /admin/mcp-tester/event-stream IS the mTLS-WS pipe to ES:
// the backend opens a mTLS-authenticated ws_connect to event-store-test:8200
// (same code path reactors use) and forwards every event to the SSE pipe.
// This is "subscribe like the reactors do" — server-side mTLS, browser-side
// SSE (browsers can't speak mTLS+SPIFFE).
//
// Net: SSE proxy is the correct path. The browser doesn't care if it's
// SSE or WS — both feed evtPush() with the same data. Keeping SSE.

interface EvtFeedRow {
  id: string
  time: string
  event_type: string
  targetShort: string
  rawTimestamp: string
  fresh: boolean
  // Pass 1 (2026-05-28) — keep raw payload + extracted metadata for
  // inline expand + JsonViewer inspection (Mission Control pattern).
  payload: any
  metadata: any
  aggregate_id: string
  source_service?: string
  // Pass 7 (2026-05-28) — frame origin so the FE can color-code rows.
  // Set by the multi-frame SSE proxy (`event: event\nid: A|B`); inferred
  // from event data.source_frame for single-frame proxy.
  frame: 'A' | 'B' | 'cross'
  // Pass 12 (2026-05-28) — richer source attribution. source_service is
  // almost always "registry" (or absent), so we derive a distinguishable
  // source from frame + TEG routing.
  source_frame?: string
  target_frame?: string
  source_teg?: string
  target_teg?: string
}

// Pass 12 (2026-05-28) — derive a meaningful, ALWAYS-present source label.
// Problem: source_service is "registry" on every event (or missing), so the
// feed was indistinguishable. We synthesize from the richest available signal:
//   cross-frame transfer → "teg-layer-a → teg-layer-test-b"
//   else frame-qualified → "registry · sandbox-A"
//   else bare frame       → "sandbox-A"
const FRAME_LABEL: Record<string, string> = { A: 'sandbox-A', B: 'sandbox-B', cross: 'cross-frame' }
function _frameShort(f: string): string {
  if (/sandbox-a|sandbox_a/i.test(f) || f === 'A') return 'A'
  if (/sandbox-b|sandbox_b/i.test(f) || f === 'B') return 'B'
  if (/agentvault\.com|frame-a/i.test(f)) return 'prod-A'
  if (/frame-b/i.test(f)) return 'frame-B'
  return f
}
function evtSourceLabel(evt: EvtFeedRow): string {
  // 1. Cross-frame transfer with TEG routing → most informative
  if (evt.source_teg && evt.target_teg && evt.source_teg !== evt.target_teg) {
    return `${evt.source_teg} → ${evt.target_teg}`
  }
  // 2. Cross-frame by frame fields
  if (evt.source_frame && evt.target_frame && evt.source_frame !== evt.target_frame) {
    return `${_frameShort(evt.source_frame)} → ${_frameShort(evt.target_frame)}`
  }
  // 3. service + frame qualifier
  const svc = evt.source_service || 'registry'
  return `${svc} · ${FRAME_LABEL[evt.frame] || evt.frame}`
}

const EVT_MAX_FEED = 250
// Background noise: high-volume background workers that drown out test
// sweep events. Toggle off with the "Show all" button. ~95% of recent
// events on a healthy sandbox come from these 3 workers.
const EVT_NOISE_TYPES = new Set<string>([
  'TokensIssued',          // staking_distributor mints
  'RewardsDistributed',    // reward fanout
  'RewardsAutoCompounded', // staking auto-compound
  // §MCPTEST30 (V0541): measured on sbx-alpha's store, 2026-10-01 23:xxZ: 5,089 of 8,714 events in an hour were
  // LedgerBalanceChanged (the TEG's per-balance mirror of transfers the feed already shows by their own types); agents'
  // heartbeats are the other steady trickle. The rewards above have been switched off since the BaFin configuration.
  'LedgerBalanceChanged',
  'AgentHeartbeat',
])
const evtWsConnected = ref(false)
/** §FESUITE (the loading sweep): the log says "no entries yet" only after the last run was read (onMounted) */
const lastRunRead = ref(false)
// §FESUITE (the failing-reads census, 2026-10-04): the runs' read failed, nothing read (the log says so; it said "No log
// entries yet. Press Run to start a sweep." with every read failed)
const historyFailed = ref(false)
const evtFeed       = ref<EvtFeedRow[]>([])
const evtPaused     = ref(false)
const evtExpandedId = ref<string | null>(null)
const evtFilterText = ref('')
const evtAutoScroll = ref(true)
const evtHideNoise  = ref(true) // default: hide chatty background workers
const evtPinnedType = ref<string>('')
// §MCPTEST30 (V0541): the store(s) the stream reads, from the proxy's `source` events ("A <host:port> target|own|peer")
const evtSources = ref<{ frame: string; host: string; why: string }[]>([])
// Pass 7 (2026-05-28) — multi-frame subscription + frame filter
const evtIncludeB   = ref<boolean>(false)
const evtFrameFilter = ref<'all' | 'A' | 'B' | 'cross'>('all')

function evtToggleExpand(id: string) {
  evtExpandedId.value = evtExpandedId.value === id ? null : id
}

function evtCopyType(t: string) {
  try { navigator.clipboard?.writeText(t) } catch { /* */ }
}

const evtFeedFiltered = computed(() => {
  const q = evtFilterText.value.trim().toLowerCase()
  const pin = evtPinnedType.value
  const fr  = evtFrameFilter.value
  return evtFeed.value.filter(r => {
    if (fr !== 'all' && r.frame !== fr) return false
    if (pin && r.event_type !== pin) return false
    if (evtHideNoise.value && !pin && EVT_NOISE_TYPES.has(liveOld(r.event_type))) return false
    if (q) {
      const hay = (r.event_type + ' ' + r.aggregate_id + ' ' + (r.source_service || '')).toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const evtTypeFacets = computed(() => {
  const m = new Map<string, number>()
  evtFeed.value.forEach(r => m.set(r.event_type, (m.get(r.event_type) || 0) + 1))
  return Array.from(m.entries()).sort((a,b) => b[1]-a[1]).slice(0, 10)
})

// Stats line: total observed + per-class breakdown (hidden noise count)
const evtHiddenNoiseCount = computed(() => {
  if (!evtHideNoise.value || evtPinnedType.value) return 0
  return evtFeed.value.filter(r => EVT_NOISE_TYPES.has(liveOld(r.event_type))).length
})
let evtSource: SseHandle | null = null
let evtReconnectTimer: ReturnType<typeof setTimeout> | null = null
let evtReconnectDelay = 500

// SSE proxy works from anywhere — no origin gate needed.
const evtCanConnect = computed(() => true)

function evtTruncate(s: string): string {
  if (!s) return ''
  if (s.length <= 24) return s
  return s.slice(0, 10) + '…' + s.slice(-6)
}

function evtDeepFind(obj: any, key: string): any {
  if (!obj || typeof obj !== 'object') return null
  if (key in obj) return (obj as any)[key]
  for (const k of Object.keys(obj)) {
    const v = evtDeepFind((obj as any)[k], key)
    if (v !== null && v !== undefined) return v
  }
  return null
}

// Color per event type — gives the user a quick read on flows
const _evtTypeColors: Record<string, string> = {
  TokensTransferred:         '#00d2d2',
  TokensIssued:              '#00ff88',
  TokensStaked:              '#a78bfa',
  TokensUnstaked:            '#fbbf24',
  TransactionFeeCollected:   '#fb923c',
  AgentCardRegistered:       '#34d399',
  AgentCardUpdated:          '#60a5fa',
  RewardsDistributed:        '#86efac',
  EigenTrustComputed:        '#c084fc',
  CrossRegistryTransferInitiated: '#22d3ee',
  CrossRegistryTransferCompleted: '#22d3ee',
  A2APaymentAuthorized:      '#f472b6',
  A2APaymentSettled:         '#f472b6',
}
function evtTypeColor(t: string): string {
  return _evtTypeColors[liveOld(t)] || 'rgba(var(--cyan-rgb), 0.85)'
}

function evtPush(raw: any, frameHint?: 'A' | 'B') {
  if (evtPaused.value) return
  let payload = raw
  if (typeof payload?.data === 'string') {
    try { payload = { ...payload, data: JSON.parse(payload.data) } } catch { /* leave */ }
  }
  const event_type = evtDeepFind(payload, 'event_type')
  if (!event_type) return
  const aggregate_id = evtDeepFind(payload, 'aggregate_id') || ''
  const timestamp    = evtDeepFind(payload, 'timestamp') || new Date().toISOString()
  const evtId        = evtDeepFind(payload, 'id') || evtDeepFind(payload, 'event_id')

  // Pass 1 (2026-05-28) — extract metadata + source_service + keep full
  // payload for inline expand panel (JsonViewer-driven inspection).
  const metadata       = evtDeepFind(payload, 'metadata') || {}
  const source_service = evtDeepFind(payload, 'source_service') || ''
  // Pass 12 (2026-05-28) — TEG routing for richer source attribution
  const source_teg = evtDeepFind(payload, 'source_teg') || ''
  const target_teg = evtDeepFind(payload, 'target_teg') || ''

  // Pass 7 (2026-05-28, fix) — derive frame from multiple signals:
  //  1. source_frame != target_frame → 'cross' (true cross-frame transfer)
  //  2. Multi-SSE proxy frameHint (SSE id: A|B) → which ES it came from
  //  3. source_frame trust-domain name → A or B
  //  4. Default 'A' (single-SSE proxy runs against sandbox-A)
  // Cross-frame ALWAYS wins (most informative for the propagation view).
  const sourceFrame = String(evtDeepFind(payload, 'source_frame') || '')
  const targetFrame = String(evtDeepFind(payload, 'target_frame') || '')
  let frame: 'A' | 'B' | 'cross'
  if (sourceFrame && targetFrame && sourceFrame !== targetFrame) {
    frame = 'cross'
  } else if (frameHint) {
    frame = frameHint
  } else if (/sandbox-b|frame-b/i.test(sourceFrame)) {
    frame = 'B'
  } else {
    frame = 'A'
  }

  const row: EvtFeedRow = {
    id:            evtId ? String(evtId) : `mc-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    time:          (() => {
      try { return new Date(String(timestamp)).toLocaleTimeString(appLocale(), { hour12: false }) }
      catch { return new Date().toLocaleTimeString(appLocale(), { hour12: false }) }
    })(),
    rawTimestamp:  String(timestamp),
    event_type:    String(event_type),
    targetShort:   evtTruncate(String(aggregate_id)),
    aggregate_id:  String(aggregate_id || ''),
    source_service: String(source_service || ''),
    payload:       payload,
    metadata:      metadata,
    fresh:         true,
    frame:         frame,
    source_frame:  sourceFrame || undefined,
    target_frame:  targetFrame || undefined,
    source_teg:    source_teg || undefined,
    target_teg:    target_teg || undefined,
  }
  if (evtFeed.value.some(e => e.id === row.id)) return
  evtFeed.value.unshift(row)
  if (evtFeed.value.length > EVT_MAX_FEED) evtFeed.value.length = EVT_MAX_FEED
  setTimeout(() => { row.fresh = false }, 1500)
}

function evtConnect() {
  evtClose()
  const token = auth.token || ''
  if (!token) {
    // No JWT yet — caller (onMounted) will retry once auth resolves.
    return
  }
  // Pass 7 (2026-05-28) — pick endpoint based on multi-frame toggle.
  //  - Default: /event-stream (sandbox-A only)
  //  - With B toggle: /event-stream-multi?frames=a,b
  // §RELEASEHARDEN D2 (2026-09-14) — the JWT rides the Authorization header of a fetch-based reader
  // (services/sse.ts). The `?access_token=` form before it wrote the admin JWT into the container
  // log on every open, and the server refuses it now. A fetch stream does not reconnect by itself,
  // so the end of the stream schedules the same reconnect the EventSource error used to.
  const base = '/api/v1'
  const url = evtIncludeB.value
    ? `${base}/admin/mcp-tester/event-stream-multi?frames=a,b`
    : `${base}/admin/mcp-tester/event-stream`
  try {
    evtSource = openSse(url, {
      headers: { Authorization: `Bearer ${token}` },
      onEvent: (ev) => {
        // §MCPTEST30 (V0541): CONNECTED once the STORE answers (upstream-open); `connected` is only the proxy, which
        // answers before the store does, so the panel said CONNECTED while the store refused
        if (ev.event === 'upstream-open') {
          evtWsConnected.value = true
          evtReconnectDelay = 500
        } else if (ev.event === 'connected') {
          evtSources.value = []
        } else if (ev.event === 'source') {
          const [frame, host, why] = String(ev.data || '').split(' ')
          if (frame && host) evtSources.value = [...evtSources.value.filter((x) => x.frame !== frame), { frame, host, why: why || '' }]
        } else if (ev.event === 'event') {
          try {
            const data = JSON.parse(ev.data)
            // Multi-SSE labels the frame through the SSE `id:` field (server-side `id: A` / `id: B`).
            const frameHint = ev.id === 'B' ? 'B' : ev.id === 'A' ? 'A' : undefined
            evtPush(data, frameHint)
          } catch { /* ignore */ }
        } else if (ev.event === 'upstream-close' || ev.event === 'upstream-error') {
          evtWsConnected.value = false
        }
      },
      onError: () => { evtWsConnected.value = false; evtScheduleReconnect() },
      onClose: () => { evtWsConnected.value = false; evtScheduleReconnect() },
    })
  } catch {
    evtWsConnected.value = false
    evtScheduleReconnect()
  }
}

// Pass 7 — reconnect when user toggles multi-frame
watch(evtIncludeB, () => {
  // brief delay so toggle CSS animation completes before re-establishing
  setTimeout(() => evtConnect(), 100)
})

function evtScheduleReconnect() {
  if (evtReconnectTimer) clearTimeout(evtReconnectTimer)
  evtReconnectTimer = setTimeout(() => {
    evtReconnectDelay = Math.min(evtReconnectDelay * 1.5, 8000)
    evtConnect()
  }, evtReconnectDelay)
}

function evtClose() {
  if (evtSource) { try { evtSource.close() } catch { /* */ } evtSource = null }
  if (evtReconnectTimer) { clearTimeout(evtReconnectTimer); evtReconnectTimer = null }
}

// ─── Tabs ────────────────────────────────────────────────────────────────

type TabId = 'log' | 'bugfind' | 'fails' | 'results' | 'probes' | 'notrun' | 'phasef' | 'history'
const activeTab = ref<TabId>('log')
// §FESUITE (09's ask, 2026-10-03: he looked for the console suite's runs in this page's history): a link may name the
// tab (`?tab=history`, the console-suite page's link back). It wins over the remembered tab at mount, and vue-router
// keeps this page on a query-only change, so a later arrival is read by the watcher (PART 1: the second arrival).
const TAB_IDS: readonly TabId[] = ['log', 'bugfind', 'fails', 'results', 'probes', 'notrun', 'phasef', 'history']
const route = useRoute()
function tabFromQuery(q: unknown): TabId | null {
  return typeof q === 'string' && (TAB_IDS as readonly string[]).includes(q) ? (q as TabId) : null
}
watch(() => route.query.tab, (q) => { const asked = tabFromQuery(q); if (asked) activeTab.value = asked })

const tabs = computed(() => [
  // §MCPTEST30 (V0535): Icon names, not glyphs (the hourglass drew as a colour emoji); the live log counts the lines it
  // shows (heartbeats folded); a Probes tab; "Phase F drift" says what it holds
  { id: 'log' as const,    label: tr('mcpTester.tabs.log', 'Live log'), icon: 'mdi:format-list-bulleted', count: shownLogLines.value.length || undefined },
  { id: 'bugfind' as const,label: tr('mcpTester.tabs.bugfind', 'BUG-FIND'), icon: 'mdi:bug-check-outline',    count: bugFinds.value.length || undefined },
  { id: 'fails' as const,  label: tr('mcpTester.tabs.fails', 'Hard fails'), icon: 'mdi:close-circle',         count: hardFails.value.length || undefined },
  { id: 'results' as const,label: tr('mcpTester.tabs.results', 'All tools'), icon: 'mdi:view-grid',            count: results.value.length || undefined },
  { id: 'probes' as const, label: tr('mcpTester.tabs.probes', 'Probes'), icon: 'mdi:test-tube',            count: probeTallies.value.length || undefined },
  // §MCPTEST-MCP11 — skips and policy-denials share a tab: both are "not run",
  // and neither is a pass or a failure. Count is the sum so the badge answers
  // "how many were left out" in one number, with the split visible inside.
  { id: 'notrun' as const, label: tr('mcpTester.tabs.notrun', 'Not run'), icon: 'mdi:cancel',               count: (skipped.value.length + policyDenied.value.length) || undefined },
  { id: 'phasef' as const, label: tr('mcpTester.tabs.phasef', 'Drift & integrity'), icon: 'mdi:shield-check',    count: phaseFTabCount.value || undefined },
  { id: 'history' as const,label: tr('mcpTester.tabs.history', 'History'), icon: 'mdi:history',              count: runHistory.value.length || undefined },
])

// §MCPTEST30 (V0535): what the page reads off a run
const shownLogLines = computed(() => foldHeartbeats(logLines.value))
const probeTallies = computed(() => tallyFamilies(results.value))
const probeRowCount = computed(() => probeTallies.value.reduce((n, f) => n + f.total, 0))
const probeBugFinds = computed(() => probeTallies.value.reduce((n, f) => n + f.bugFinds, 0))
// §MCPTEST30 (V0536): what the run's rows are, in their own words (a federation run's rows are its tests, not tools)
const rowKindsNow = computed(() => rowKinds(results.value.map((r) => r.tool), summary.value?.tool_count ?? results.value.length))
const rowParts = computed(() => rowKindPhrases(rowKindsNow.value).map((p) => tp(p.key, p.fallback, p.params)))
// the federation and cloud-operator suites count no contracts (both counts 0): saying "0 explicit contracts" of them
// reads as a deficiency they do not have
const contractsCounted = computed(() =>
  ((summary.value?.explicit_contracts ?? 0) + (summary.value?.default_contracts ?? 0)) > 0)
const skippedGroups = computed(() => groupNotRun(skipped.value as { tool: string; reason?: string | null; skip_reason?: string | null }[]))
const NOT_RUN_HEADINGS: Record<NotRunKind, { key: string; fallback: string; note: string; noteKey: string }> = {
  unmeasured: { key: 'mcpTester.notRun.unmeasured', fallback: 'Answered, success path not measured',
                noteKey: 'mcpTester.notRun.unmeasuredNote', note: 'The tool answered (often a 401 or 403) and the step accepted any answer, so its contract\'s success was never reached: a coverage hole someone can close.' },
  lost:       { key: 'mcpTester.notRun.lost', fallback: 'Answer lost in transit',
                noteKey: 'mcpTester.notRun.lostNote', note: 'No HTTP status came back to the tester (the server may have answered): its own transport, not the tool. A read is asked once more first; a write never is.' },
  fixture:    { key: 'mcpTester.notRun.fixture', fallback: 'No subject this run',
                noteKey: 'mcpTester.notRun.fixtureNote', note: 'The run made nothing for it to act on (an operator\'s sweep makes no proposals, payment authorizations or contracts), so it was not called: a hole in the run\'s setup.' },
  role:       { key: 'mcpTester.notRun.role', fallback: 'Needs another account',
                noteKey: 'mcpTester.notRun.roleNote', note: 'The run\'s account cannot open it (an operator\'s or an admin\'s view, locked to a member), so it was not walked.' },
  nothing:    { key: 'mcpTester.notRun.nothing', fallback: 'Nothing to decide this run',
                noteKey: 'mcpTester.notRun.nothingNote', note: 'The probe ran and had nothing to judge: an empty list, one page where two were needed, an object anyone may read.' },
  switched_off: { key: 'mcpTester.notRun.switchedOff', fallback: 'Switched off on this node',
                noteKey: 'mcpTester.notRun.switchedOffNote', note: 'The feature is disabled where the run went (the registry says so in its own words), so there was nothing to measure there.' },
  by_design:  { key: 'mcpTester.notRun.byDesign', fallback: 'Left out on purpose',
                noteKey: 'mcpTester.notRun.byDesignNote', note: 'Not called by decision: a tool that would loop, provision, or move value no run should move.' },
  other:      { key: 'mcpTester.notRun.other', fallback: 'Other reasons',
                noteKey: 'mcpTester.notRun.otherNote', note: 'Each row says why in its own words.' },
}
/** the loaded run's wall time from its own start and finish (a summary's wall_s can be a sum of test times) */
const loadedWallSeconds = computed(() =>
  runWallSeconds({ started_at: startedAt.value, finished_at: finishedAt.value, summary: summary.value }))
/** the finished run History would load while a new sweep is in flight, if any (the results tabs show it on request) */
const lastFinishedRun = computed(() =>
  runHistory.value.find((r) => r.status === 'completed' && r.run_id !== latestRunId.value && !!r.summary) || null)
/** §MCPTEST30 (V0541): a result tab with no run loaded waits for one instead of reporting clean over zero rows */
const awaitingRun = computed(() => awaitsRun(activeTab.value, {
  rows: results.value.length,
  bugFinds: bugFinds.value.length,
  hardFails: hardFails.value.length,
  notRun: skipped.value.length + policyDenied.value.length,
  hasSummary: !!summary.value,
}))
/** the loaded run's suite (a console run names it on the run, not in its summary) */
const loadedFlowName = ref<string | null>(null)
/** §MCPTEST30 (V0545): the loaded run's own start. `startedAt` is the LIVE run's while a finished one is viewed mid-sweep */
const loadedStartedAt = ref<number | null>(null)
/** the loaded run's suite as the picker names it, else the History column's tag */
const loadedSuiteLabel = computed(() => {
  const f = summary.value?.flow_name || loadedFlowName.value
  return availableFlows.value.find((x) => x.flow_name === f)?.label || flowShortLabel(f)
})
/** §MCPTEST30 (V0541): which drift detectors the loaded run measured; a count is a reading only where its own is true */
const detectorsRun = computed(() =>
  readDetectors(summary.value as unknown as Record<string, unknown> | null, results.value,
                summary.value?.flow_name || loadedFlowName.value))
const detectorsMeasured = computed(() => DETECTOR_KEYS.filter((k) => detectorsRun.value[k]))
/** §MCPTEST30 (V0547): each stat tile reads its count only where its own check ran (tileReading); a dash otherwise */
const tiles = computed(() => {
  const s = (summary.value || {}) as Record<string, unknown>
  const contracts = contractsCounted.value
  return {
    contractGap: tileReading(s.contract_gap, contracts),
    tierDrift: tileReading(s.tier_drift, contracts),
    authMatrix: tileReading(s.auth_matrix_violations, detectorsRun.value.auth_matrix),
    crossFrame: tileReading(s.cross_frame_drift, detectorsRun.value.cross_frame),
    // §MCPTEST30 (V0548): a run with no tool baselined (a new suite, the first three runs) compared nothing; a run before
    // V0544 names no count and keeps its old reading
    latency: tileReading(s.latency_regressions, latencyMeasured(s.latency_baselined_tools)),
    wrapper: tileReading(s.wrapper_drift, detectorsRun.value.wrapper_route),
  }
})
const tileNotMeasured = computed(() => tr('mcpTester.tiles.notMeasured', 'not measured this run'))
const latencyTileSub = computed(() => {
  const n = summary.value?.latency_baselined_tools
  return typeof n === 'number' ? tp('mcpTester.tiles.latencyBaselined', 'of {n} with a baseline', { n }) : tr('mcpTester.tiles.latencyVsPrior', 'vs prior-3 median')
})
/** §MCPTEST30 (V0547): the request survey's account of F.3 (a run before V0547 names none of it) */
const wrapperKnown = computed<Array<{ tool: string; reason: string }>>(() => {
  const v = summary.value?.wrapper_drift_known
  return Array.isArray(v) ? v.filter((k) => k && typeof k.tool === 'string') : []
})
const wrapperPeerOnly = computed<Array<{ tool: string; surface: string; detail: string }>>(() => {
  const v = summary.value?.wrapper_peer_route
  return Array.isArray(v) ? v.filter((k) => k && typeof k.tool === 'string') : []
})
const wrapperReason = computed(() => {
  const r = summary.value?.wrapper_drift_reason
  return !detectorsRun.value.wrapper_route && typeof r === 'string' && r ? r : ''
})
const wrapperTileSub = computed(() => {
  const n = summary.value?.wrapper_drift_surveyed
  if (typeof n !== 'number') return tr('mcpTester.tiles.wrapperNotRecorded', 'tool count not recorded for this run')
  const k = wrapperKnown.value.length
  return k ? tp('mcpTester.tiles.wrapperSurveyedKnown', 'of {n} tools surveyed · {k} named', { n, k })
           : tp('mcpTester.tiles.wrapperSurveyed', 'of {n} tools surveyed', { n })
})
const detectorsUnmeasured = computed(() => DETECTOR_KEYS.filter((k) => !detectorsRun.value[k]))
const DETECTOR_TEXT: Record<DetectorKey, { name: { key: string; fallback: string }; clean: { key: string; fallback: string } }> = {
  wrapper_route: { name: { key: 'mcpTester.drift.wrapperRoute', fallback: 'wrapper↔route' },
                   clean: { key: 'mcpTester.drift.cleanWrapper', fallback: "every tool's request passes its route" } },
  cross_frame:   { name: { key: 'mcpTester.drift.crossFrame', fallback: 'A↔B' },
                   clean: { key: 'mcpTester.drift.cleanCross', fallback: 'the target and its peer frame agree on shape' } },
  auth_matrix:   { name: { key: 'mcpTester.drift.authMatrix', fallback: 'wrong-tier accepts' },
                   clean: { key: 'mcpTester.drift.cleanMatrix', fallback: 'every probed tool rejects the wrong tier' } },
}
function detectorReading(k: DetectorKey): string {
  const s = summary.value
  if (!s) return ''
  if (k === 'wrapper_route') return String(s.wrapper_drift || 0)
  if (k === 'cross_frame') {
    const of = s.cross_frame_compared
    return typeof of === 'number'
      ? tp('mcpTester.drift.ofCompared', '{n} of {of} compared', { n: s.cross_frame_drift || 0, of })
      : String(s.cross_frame_drift || 0)
  }
  return tp('mcpTester.drift.ofProbes', '{n} of {of}', { n: s.auth_matrix_violations || 0, of: s.auth_matrix_total || 0 })
}
function categoryCount(name: string, n: number): string {
  const checks = /^(Probe|Federation|Console) · /.test(name)
  if (checks) return n === 1 ? tr('mcpTester.list.checkOne', '1 check') : tp('mcpTester.list.checkMany', '{n} checks', { n })
  return n === 1 ? tr('mcpTester.list.toolOne', '1 tool') : tp('mcpTester.list.toolMany', '{n} tools', { n })
}

// Phase F drift tab count — sum of all 4 new outcome categories.
// §MCPTEST30 (V0545): mutations whose read-after-write judged nothing (a run before V0545 carries no list: empty)
const unjudgedReadBacks = computed<string[]>(() => {
  const v = summary.value?.unjudged_read_backs
  return Array.isArray(v) ? v.filter((t): t is string => typeof t === 'string') : []
})
const phaseFTotalIssues = computed(() => {
  if (!summary.value) return 0
  return (summary.value.auth_matrix_violations || 0)
       + (summary.value.cross_frame_drift || 0)
       + (summary.value.latency_regressions || 0)
       + (summary.value.wrapper_drift || 0)
       + unjudgedReadBacks.value.length
})

// ── emission_integrity HONESTY flag (2026-06-26) ──────────────────────────
// Sidecar verdict (real ES polls + mTLS handshake) the strict pass-rate is
// blind to. `null` for runs that predate the flag — the stat card shows '—'.
const emissionIntegrity = computed<{
  status: string
  checks: Record<string, { status: string; detail: string }>
  summary: string
} | null>(() => (summary.value as any)?.emission_integrity || null)

const emissionIntegrityStatus = computed<string>(() => emissionIntegrity.value?.status || '')

const emissionIntegrityChecks = computed(() =>
  Object.entries(emissionIntegrity.value?.checks || {}).map(([name, v]: [string, any]) => ({
    name,
    status: (v && v.status) || 'unknown',
    detail: (v && v.detail) || '',
  }))
)
const emissionIntegrityDegradedCount = computed(() =>
  emissionIntegrityChecks.value.filter((c) => c.status === 'degraded').length)
const emissionIntegrityWarnCount = computed(() =>
  emissionIntegrityChecks.value.filter((c) => c.status === 'warn').length)
const emissionIntegrityTooltip = computed(() => {
  if (!emissionIntegrity.value)
    return tr('mcpTester.payload.integrityNotComputed', 'emission_integrity was not computed for this run (an older sweep): re-run to populate it.')
  return emissionIntegrity.value.summary
    || tr('mcpTester.payload.integrityDefault', 'Real ES polls and an mTLS handshake give the verdict (cross-frame settlement, receiver credit, emission, supply transit). The Drift & integrity tab has the per-check detail.')
})

// Phase F drift tab badge — the 4 detectors PLUS the emission_integrity
// non-ok checks, since that detail panel now lives in this tab.
const phaseFTabCount = computed(() =>
  phaseFTotalIssues.value + emissionIntegrityDegradedCount.value + emissionIntegrityWarnCount.value)

// pass73.3.19 — sort regressions by factor (worst first)
const latencyRegressionsSorted = computed(() =>
  [...(phaseFDetails.value.latency_regressions_details || [])]
    .sort((a, b) => (Number(b.factor) || 0) - (Number(a.factor) || 0))
)

// Pull drift details from latest run for display in Phase F tab. Backend
// persists these into the `summary` field but we also keep them on a
// dedicated `phaseFDetails` ref in case the FE wants to refresh just the
// drift sections without reloading full results.
const phaseFDetails = ref<{
  wrapper_drift_details: any[]
  cross_frame_drift_details: any[]
  auth_matrix_failed_tools: string[]
  latency_regressions_details: any[]
}>({
  wrapper_drift_details: [],
  cross_frame_drift_details: [],
  auth_matrix_failed_tools: [],
  latency_regressions_details: [],
})

// ─── Derived ─────────────────────────────────────────────────────────────

// §MCPTEST30 (V0535): a run whose heartbeat stopped is not in flight (the backend's single-flight guard already lets a
// new sweep start past a run older than its container's boot); the page says so and lets Run be pressed
const runSilentSince = computed(() => isRunning.value ? silentSince(logLines.value, nowTick.value / 1000) : null)
const canRun = computed(() => (!isRunning.value || runSilentSince.value !== null) && isSandboxEffective.value)

// §MCPTEST30 (V0539): how the page reads a run's pass count (runReading.readPassRate): a pass is a row that was called
// and held, and the rows a standing rule kept from being called are a class of their own
const passReading = computed(() => readPassRate(summary.value ?? { tool_count: 0, passed: 0, skipped: 0, failed: 0 }))
// §MCPTEST30 (V0549): null for a run before V0549 (no pass_depth) or one with no passing tool rows: the tile shows nothing
const passDepth = computed(() => readPassDepth(summary.value?.pass_depth))
// §MCPTEST30 (V0550): null for a run before V0550 or a target with nothing switched off: the note shows nothing
const targetSwitches = computed(() => readTargetSwitches(summary.value?.target_switches, summary.value?.target_switches_read, summary.value?.switched_off_rows))
const byRuleTools = computed(() => new Set(policyDenied.value.map((p) => p.tool)))
const outcomeOf = (row: McpTesterToolRow): RowOutcome => rowOutcome(row, byRuleTools.value)
const OUTCOME_BADGE: Record<RowOutcome, { cls: string; key: string; fallback: string }> = {
  pass:    { cls: 'mcp-badge--success', key: 'mcpTester.outcome.pass',   fallback: 'OK' },
  by_rule: { cls: 'mcp-badge--rule',    key: 'mcpTester.outcome.byRule', fallback: 'BY RULE' },
  skip:    { cls: 'mcp-badge--muted',   key: 'mcpTester.outcome.skip',   fallback: 'SKIP' },
  fail:    { cls: 'mcp-badge--danger',  key: 'mcpTester.outcome.fail',   fallback: 'FAIL' },
}
// §MCPTEST30 (V0636): a row whose only pass was a refusal is a skip (not measured), and its badge says which kind
const REFUSAL_ONLY_BADGE = { cls: 'mcp-badge--muted', key: 'mcpTester.outcome.refusalOnly', fallback: 'REFUSAL ONLY' }
const badgeOf = (row: McpTesterToolRow) => (isRefusalOnly(row) ? REFUSAL_ONLY_BADGE : OUTCOME_BADGE[outcomeOf(row)])
function refusalOnlyLine(ro: RefusalOnlyReading): string {
  return ro.targetPct === null
    ? tp('mcpTester.pass.tipRefusalOnly', '{n} of the not measured passed on a refusal alone: a refusal shows the route refuses, never that the tool does its job.', { n: ro.n })
    : tp('mcpTester.pass.tipRefusalOnlyPct', '{n} of the not measured passed on a refusal alone: a refusal shows the route refuses, never that the tool does its job. The target counted {pct}%.',
        { n: ro.n, pct: ro.targetPct.toFixed(2) })
}

const coveragePct = computed(() => {
  const r = passReading.value
  return r.total ? (r.measured / r.total) * 100 : 0
})

const wallMinutes = computed(() => {
  if (!summary.value) return ''
  return (summary.value.wall_s / 60).toFixed(1)
})

const elapsedDisplay = computed(() => {
  if (!isRunning.value || !startedAt.value) return ''
  const elapsed = Math.floor((nowTick.value - startedAt.value * 1000) / 1000)
  const m = Math.floor(elapsed / 60)
  const s = elapsed % 60
  return `${m}m ${s.toString().padStart(2, '0')}s elapsed`
})

const filterCategory = ref('')
// Pass 2 (2026-05-28) — fail-only filter chip + persistence
const onlyFailures   = ref(false)
const onlySlow       = ref(false)
// Pass 8 (2026-05-28) — HTTP status code filter + strict-pass mode
const statusBucket = ref<StatusBucket>('')
const strictPass   = ref(false)  // requires status==2xx (not just healthy)

// pass73.3.19 — per-tool re-fire state. Set of tools currently in-flight.
const refiring       = ref<Set<string>>(new Set())
// Pass 9 (2026-05-28) — toast QUEUE (multiple refires can be in flight)
// pass73.3.19 (2026-05-28): `kind` distinguishes a re-fire result toast from a
// share/copy confirmation — sharing was wrongly rendering as "Re-fired … OK (0ms)".
interface RefireToast { id: string; tool: string; healthy: boolean; elapsed: number; status: number; kind?: 'refire' | 'share' }
const refireToasts   = ref<RefireToast[]>([])
function dismissToast(id: string) {
  refireToasts.value = refireToasts.value.filter(t => t.id !== id)
}

// pass73.3.19 — run-to-run diff state
const diffSelection  = ref<string[]>([])
const diffResult     = ref<ReturnType<typeof mcpTesterApi.diffRuns> | null>(null)
const diffLoading    = ref(false)

function toggleDiffSelection(runId: string) {
  const i = diffSelection.value.indexOf(runId)
  if (i >= 0) diffSelection.value.splice(i, 1)
  else if (diffSelection.value.length < 2) diffSelection.value.push(runId)
  // auto-compute when 2 selected
  if (diffSelection.value.length === 2) runDiff()
}

function diffWithCurrent(otherRunId: string) {
  if (!latestRunId.value) return
  diffSelection.value = [otherRunId, latestRunId.value]
  runDiff()
}

async function runDiff() {
  if (diffSelection.value.length !== 2) return
  diffLoading.value = true
  diffResult.value = null
  try {
    const [a, b] = await Promise.all([
      mcpTesterApi.getRun(diffSelection.value[0], true),
      mcpTesterApi.getRun(diffSelection.value[1], true),
    ])
    diffResult.value = mcpTesterApi.diffRuns(a, b)
  } catch (err) {
    log.error('runDiff failed', err)
  } finally {
    diffLoading.value = false
  }
}

// Pass 6 (2026-05-28) — pick a payload to render in the detail panel.
// Prefers the freshest re-fire response, falls back to sweep excerpt.
function rowResponsePayload(row: any): any {
  if (row && row.response_data) return row.response_data
  if (row && row.response_excerpt) return row.response_excerpt
  return null
}
function rowResponseLabel(row: any): string {
  if (row && row.response_data) return tp('mcpTester.payload.refired', 'Response payload (re-fired at {time})', { time: new Date(row.refired_at || Date.now()).toLocaleTimeString(appLocale()) })
  if (row && row.response_excerpt) return tr('mcpTester.payload.captured', 'Response payload (captured by the sweep)')
  return tr('mcpTester.payload.plain', 'Response payload')
}

async function refireOneTool(tool: string, tier?: string) {
  if (refiring.value.has(tool)) return
  refiring.value = new Set([...refiring.value, tool])
  try {
    const r = await mcpTesterApi.refireSingle(tool, {}, tier || '')
    // Splice the freshly-fired row into results[] so the table updates in place
    const idx = results.value.findIndex((x: any) => x.tool === tool)
    const merged = {
      tool:    r.tool,
      tier:    r.tier || (results.value[idx]?.tier ?? ''),
      healthy: !!r.healthy,
      skipped: !!r.skipped,
      status:  r.status,
      elapsed: r.elapsed,
      error:   r.error || null,
      skip_reason: results.value[idx]?.skip_reason ?? null,
      // Keep prior latency baseline marker if present — re-fire doesn't update baseline
      latency_regression:  results.value[idx]?.latency_regression ?? false,
      latency_baseline_ms: results.value[idx]?.latency_baseline_ms ?? 0,
      // New field: response payload from the re-fire (used by detail panel)
      response_data: r.response_data,
      refired_at: Date.now(),
    }
    if (idx >= 0) results.value.splice(idx, 1, merged as any)
    else results.value.push(merged as any)
    // Pass 9 — push to queue (don't overwrite; multiple refires visible)
    const tid = `${tool}-${Date.now()}`
    refireToasts.value.push({ id: tid, tool, healthy: !!r.healthy, elapsed: r.elapsed, status: r.status })
    setTimeout(() => dismissToast(tid), 4500)
    log.info(`[mcp-tester] re-fired ${tool} healthy=${r.healthy} status=${r.status} elapsed=${r.elapsed}ms`)
  } catch (err: any) {
    log.error('refireOneTool failed', err)
    const tid = `${tool}-${Date.now()}-err`
    refireToasts.value.push({ id: tid, tool, healthy: false, elapsed: 0, status: 0 })
    setTimeout(() => dismissToast(tid), 5000)
  } finally {
    const next = new Set(refiring.value)
    next.delete(tool)
    refiring.value = next
  }
}


// §MCPTEST30: the toolbar's filters (services/mcpTester/listReading.ts, unit-tested)
const filteredResults = computed(() => filterRows(results.value, {
  text: filterText.value, tier: filterTier.value, category: filterCategory.value, onlyFailures: onlyFailures.value,
  onlySlow: onlySlow.value, statusBucket: statusBucket.value, strictPass: strictPass.value,
}, categorizeTool))

// Aggregate counts for the toolbar pills.
// Bug fix (2026-05-28 — pass73.3.19) — earlier version read `r.status`
// (HTTP status code as a string). The actual schema uses booleans:
// `r.healthy` for pass, `r.skipped` for skip, !healthy && !skipped for fail.
// §MCPTEST30 (V0539): the list's pills count the four classes the pass-rate card counts (the rule's refusals read SKIP)
const outcomeTally = computed(() => tallyOutcomes(results.value, byRuleTools.value))
const totalPassCount = computed(() => outcomeTally.value.pass)
const totalFailCount = computed(() => outcomeTally.value.fail)
const totalSkipCount = computed(() => outcomeTally.value.skip)
const totalByRuleCount = computed(() => outcomeTally.value.by_rule)
// §MCPTEST30: the strict chip counts the rows the strict filter hides, by the same predicate (a healthy 1xx/3xx row was
// hidden and not counted)
const totalLenientPassCount = computed(() => results.value.filter(isLenientPass).length)
// Status-code distribution for chips
const statusDistribution = computed(() => readStatusDistribution(results.value))

// ═══════════════════════════════════════════════════════════════════════════
// §pass73.3.18 — auto-derived categorization + expandable rows + persistence
// ═══════════════════════════════════════════════════════════════════════════
// Design decisions (locked with commander 2026-05-28):
//   - Auto-derived categories from tool name prefix (NOT backend field) →
//     zero backend change, doctrine-defining derivation lives in FE.
//   - Expansion state persists via localStorage → debugging sessions survive
//     page reloads.
//   - Categories + rows COLLAPSED BY DEFAULT → 12-axis assertion lists are
//     long; show the shape first, drill down on demand.
// ───────────────────────────────────────────────────────────────────────────

const LS_CAT_KEY = 'mcp-tester-expanded-categories'
const LS_ROW_KEY = 'mcp-tester-expanded-rows'

function _loadSet(key: string): Set<string> {
  try {
    const raw = typeof window !== 'undefined' ? window.localStorage.getItem(key) : null
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? new Set(arr.filter(s => typeof s === 'string')) : new Set()
  } catch { return new Set() }
}

function _saveSet(key: string, s: Set<string>) {
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(key, JSON.stringify(Array.from(s)))
    }
  } catch { /* quota / privacy mode — silent skip */ }
}

const expandedCategories = ref<Set<string>>(_loadSet(LS_CAT_KEY))
const expandedRows = ref<Set<string>>(_loadSet(LS_ROW_KEY))

function persistCategoryExpansion() { _saveSet(LS_CAT_KEY, expandedCategories.value) }
function persistRowExpansion() { _saveSet(LS_ROW_KEY, expandedRows.value) }

/** §MCPTEST30 (V0535): a probe family's card opens All tools filtered to that family, its rows expanded */
function openProbeFamily(label: string) {
  const name = 'Probe · ' + label
  filterCategory.value = name
  expandedCategories.value.add(name)
  persistCategoryExpansion()
  activeTab.value = 'results'
}

function toggleCategory(name: string) {
  if (expandedCategories.value.has(name)) {
    expandedCategories.value.delete(name)
  } else {
    expandedCategories.value.add(name)
  }
  // Force reactivity (Set mutation isn't deep-tracked)
  expandedCategories.value = new Set(expandedCategories.value)
  persistCategoryExpansion()
}

function toggleRow(toolName: string) {
  if (expandedRows.value.has(toolName)) {
    expandedRows.value.delete(toolName)
  } else {
    expandedRows.value.add(toolName)
  }
  expandedRows.value = new Set(expandedRows.value)
  persistRowExpansion()
}

const allCategoriesExpanded = computed(() => {
  const all = categorizedFilteredResults.value
  return all.length > 0 && all.every(c => expandedCategories.value.has(c.name))
})

function toggleAllCategories() {
  if (allCategoriesExpanded.value) {
    expandedCategories.value = new Set()
  } else {
    expandedCategories.value = new Set(categorizedFilteredResults.value.map(c => c.name))
  }
  persistCategoryExpansion()
}

// Pass 3 (2026-05-28) — keyboard navigation across visible tool rows.
// Esc: collapse the focused row's expand panel.
// Enter/Space: toggle row expand.
// j / ↓: move focus to next visible row.
// k / ↑: move focus to previous visible row.
function flatVisibleTools(): string[] {
  const out: string[] = []
  for (const cat of categorizedFilteredResults.value) {
    if (!expandedCategories.value.has(cat.name)) continue
    for (const r of cat.tools) out.push(r.tool)
  }
  return out
}
function onRowKeydown(e: KeyboardEvent, toolName: string) {
  const flat = flatVisibleTools()
  const idx = flat.indexOf(toolName)
  if (e.key === 'Escape') {
    if (expandedRows.value.has(toolName)) {
      expandedRows.value.delete(toolName)
      expandedRows.value = new Set(expandedRows.value)
      persistRowExpansion()
      e.preventDefault()
    }
  } else if (e.key === 'Enter' || e.key === ' ') {
    toggleRow(toolName)
    e.preventDefault()
  } else if (e.key === 'j' || e.key === 'ArrowDown') {
    if (idx >= 0 && idx + 1 < flat.length) {
      focusToolRow(flat[idx + 1])
      e.preventDefault()
    }
  } else if (e.key === 'k' || e.key === 'ArrowUp') {
    if (idx > 0) {
      focusToolRow(flat[idx - 1])
      e.preventDefault()
    }
  }
}
function focusToolRow(toolName: string) {
  nextTick(() => {
    const el = document.querySelector(`[data-testid="mcp-row-${toolName}"]`) as HTMLElement | null
    if (el) el.focus()
  })
}

// §MCPTEST30: a row's category is services/mcpTester/toolCategory.ts (unit-tested)

/**
 * Group filteredResults by auto-derived category. Returns an array sorted
 * by category name with per-category aggregate stats.
 */
const categorizedFilteredResults = computed(() => {
  const groups = new Map<string, McpTesterToolRow[]>()
  for (const r of filteredResults.value) {
    const cat = categorizeTool(r.tool, r.tier)
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat)!.push(r)
  }
  const out = Array.from(groups.entries()).map(([name, tools]) => {
    const tally = tallyOutcomes(tools, byRuleTools.value)
    const pass = tally.pass
    const fail = tally.fail
    const skip = tally.skip
    const byRule = tally.by_rule
    const elapsed = tools
      .map(t => t.elapsed || 0)
      .filter(n => n > 0)
      .sort((a, b) => a - b)
    const median = elapsed.length === 0 ? 0
      : elapsed.length % 2 === 0
        ? Math.round(((elapsed[elapsed.length / 2 - 1] || 0) + (elapsed[elapsed.length / 2] || 0)) / 2)
        : (elapsed[Math.floor(elapsed.length / 2)] || 0)
    const total = tools.length
    return {
      name,
      tools: tools.slice().sort((a, b) => a.tool.localeCompare(b.tool)),
      pass_count: pass,
      fail_count: fail,
      skip_count: skip,
      by_rule_count: byRule,
      bar: barSegments(pass, skip, fail, byRule),
      total,
      pass_pct: total === 0 ? 0 : Math.round((pass / total) * 100),
      median_ms: median,
    }
  })
  // Sort: categories with fails first (highest priority), then alphabetic
  return out.sort((a, b) => {
    if (a.fail_count !== b.fail_count) return b.fail_count - a.fail_count
    return a.name.localeCompare(b.name)
  })
})

const availableCategories = computed(() => {
  const cats = new Set<string>()
  for (const r of results.value) cats.add(categorizeTool(r.tool, r.tier))
  return Array.from(cats).sort()
})

// §MCPTEST30: a row's strict-mode axes and the BUG-FIND taxonomy live in services/mcpTester/assertions.ts (unit-tested);
// the page passes its own words
const say: Say = { t: (key, fallback) => tr(key, fallback), tp }
function assertionsForRow(row: McpTesterToolRow) { return readAxes(row, detectorsRun.value, say) }

async function copyToClipboard(text: string) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // Fallback: textarea trick
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
  } catch {
    log.warn?.('copy failed; clipboard unavailable')
  }
}

// ─── Phase E.3 — bug-find taxonomy + timing analytics + trajectory ───────

const bugFindTaxonomy = computed(() => readBugFindTaxonomy(bugFinds.value, say))

const passRateTooltip = computed(() => {
  if (!summary.value) return ''
  const r = passReading.value
  // the MCP and federation flows divide by every row, the console suite by the steps it measured: the tooltip states
  // the fraction that reproduces the rate, and quotes a rate it cannot reproduce (runReading.passFraction)
  const f = passFraction(r)
  const lines = [
    f?.over === 'rows'
      ? tp('mcpTester.pass.tipRate', 'Pass rate {pct}%: {passed} of {rows} rows were called and passed.',
          { pct: r.pct.toFixed(2), passed: r.measured, rows: r.total })
      : f?.over === 'measured'
        ? tp('mcpTester.pass.tipRateMeasured', 'Pass rate {pct}%: {passed} of the {den} rows this suite measured passed; it leaves the rows it did not measure out of the rate.',
            { pct: r.pct.toFixed(2), passed: r.measured, den: f.den })
        : tp('mcpTester.pass.tipRateSuite', 'Pass rate {pct}% as this suite records it; {passed} of {rows} rows were called and passed.',
            { pct: r.pct.toFixed(2), passed: r.measured, rows: r.total }),
  ]
  lines.push(tp('mcpTester.pass.tipClasses', '{passed} passed · {failed} failed · {skipped} not measured · {rule} refused by rule = {rows}',
    { passed: r.measured, failed: r.failed, skipped: r.skipped, rule: r.byRule, rows: r.measured + r.failed + r.skipped + r.byRule }))
  const ro = readRefusalOnly(summary.value)
  if (ro) lines.push(refusalOnlyLine(ro))
  if (f?.over === 'rows') {
    lines.push(tr('mcpTester.pass.tipDoctrine', 'A row not measured counts against the pass rate: a skip is a coverage hole, never a pass.'))
  }
  if (r.overlap > 0 && r.recordedPct !== null) {
    lines.push(tp('mcpTester.pass.tipRecorded', 'This run recorded {recorded}%: it counted {n} rows it never called as passes (the flows count four separate classes since V0539).',
      { recorded: r.recordedPct.toFixed(2), n: r.overlap }))
  }
  return lines.join('\n')
})


// §MCPTEST30: the sweep's timing (listReading.latencyStats: the p95 is the nearest-rank one; it read the maximum up to 20 rows)
const latency = computed(() => latencyStats(results.value))
const latencyMedian = computed(() => latency.value.median)
const latencyP95 = computed(() => latency.value.p95)
const latencyMax = computed(() => latency.value.max)
const slowestTen = computed(() => latency.value.slowest)

const trajectorySvgW = 320
const trajectorySvgH = 56

// §MCPTEST30 (V0535): the suite whose trend History draws: the loaded run's (suites sit on different floors, so a line
// through all of them drew the suites taking turns)
const trajectoryFlow = computed(() => summary.value?.flow_name || selectedFlow.value || DEFAULT_FLOW)
// §SUITES1018: and the loaded run's target (sameSuite): the console suite's two passes are two lines, not one
const trajectoryTarget = computed(() => {
  const t = (summary.value as { target?: unknown } | null)?.target
  return typeof t === 'string' ? t.trim() : ''
})
const trajectoryPoints = computed(() => {
  // Up to 12 most-recent finished runs OF ONE SUITE with a pass_pct value,
  // oldest-to-newest order. Coords scaled into the SVG viewBox.
  const pts = suiteTrend(runHistory.value, trajectoryFlow.value, 12, trajectoryTarget.value)
    .map(r => ({ id: r.id, pct: r.pct, x: 0, y: 0 }))
  if (pts.length < 2) return []
  const w = trajectorySvgW
  const h = trajectorySvgH
  const stepX = w / (pts.length - 1)
  const lo = Math.min(...pts.map(p => p.pct))
  const hi = Math.max(...pts.map(p => p.pct))
  const span = Math.max(0.01, hi - lo)
  pts.forEach((p, i) => {
    p.x = i * stepX
    p.y = h - 6 - ((p.pct - lo) / span) * (h - 12)
  })
  return pts
})

const trajectoryPolyline = computed(() =>
  trajectoryPoints.value.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
)

function rowClass(row: McpTesterToolRow): string {
  if (row.error && row.error.includes('BUG-FIND')) return 'mcp-row--bug'
  if (!row.healthy && !row.skipped) return 'mcp-row--fail'
  if (row.skipped) return 'mcp-row--skip'
  return ''
}

function statusBadge(status: string): string {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running' || status === 'queued') return 'info'
  if (status === 'unfinished') return 'warn'
  return 'muted'
}

/** §pass73.3.19 — short suite tag for the History "Suite" column.
 *  Legacy runs (pre-flow_name) default to MCP (that was the only suite). */
function flowShortLabel(flowName?: string | null): string {
  // Legacy runs (pre-flow_name) have null/undefined/'' — that was the only
  // suite then, so → MCP. Guard FIRST so the default branch never .replace(null).
  if (!flowName) return 'MCP'
  switch (flowName) {
    case 'flow_federation_suite_complete': return 'Federation'
    case 'flow_mcp_lifecycle_cloudop_sandboxalpha_complete': return 'Cloud-op α'
    // §MCPTEST30 (V0637): the key keeps a retired operator's name; the operator under Sandbox Beta answers it
    case 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete': return 'Cloud-op β'
    case 'flow_playwright_console_lifecycles': return 'Console'  // §FESUITE: the console lifecycle suite (Playwright)
    case 'flow_mcp_lifecycle_complete':
      return 'MCP'
    default:
      return flowName.replace('flow_', '').replace('_complete', '').slice(0, 12)
  }
}

/** Phase E.3 — colour-code pass_pct for the History tab cell. */
// §MCPTEST30 (V0539): a History pass rate is read against its own suite. Fixed floors (99.5 green, 95 amber) painted
// every cloud operator run red with nothing failed (an operator's sweep makes no fixtures; it sits near 85 %). Red is a
// run that failed or found a bug, amber one that fell from its suite's previous run, green the rest.
function historyDelta(run: McpTesterRunMeta): { delta: number; prevId: string } | null {
  return suiteDelta(runHistory.value as unknown as TrendRun[], run as unknown as TrendRun)
}
// §SUITES1018 (2026-10-19, his report on EU's History): an operator run read a green 87.34% with nothing failed and no word
// of the 97 rows it did not run. The bar and the words under the figure say what it is made of; a failed row (his word on
// V0627: "1 failed as red is fine", a row red by design included) or a bug-find turns the row red.
function historyPassClass(c: HistoryCell | null, d: { delta: number } | null): string {
  if (c && c.bad) return 'mcp-passrate--bad'
  if (d && d.delta < 0) return 'mcp-passrate--warn'
  return 'mcp-passrate--ok'
}
type HistoryWhy = { kind: 'failed' | 'notMeasured' | 'byRule'; text: string }
function historyWhy(c: HistoryCell): HistoryWhy[] {
  const w: HistoryWhy[] = []
  if (c.failed > 0) w.push({ kind: 'failed', text: tp('mcpTester.history.whyFailed', '{n} failed', { n: c.failed }) })
  if (c.notMeasured > 0) w.push({ kind: 'notMeasured', text: tp('mcpTester.history.whyNotMeasured', '{n} not measured', { n: c.notMeasured }) })
  if (c.byRule > 0) w.push({ kind: 'byRule', text: tp('mcpTester.history.whyByRule', '{n} refused by rule', { n: c.byRule }) })
  return w
}
// one reading per History row, kept while the history is unchanged (the row read it five times per render)
const historyRows = computed(() => runHistory.value.map((run) => {
  const cell = run.summary ? historyCell(run.summary as unknown as RunCounts & { bug_finds?: number | null }) : null
  const delta = historyDelta(run)
  return { run, cell, delta, why: cell ? historyWhy(cell) : [], cls: historyPassClass(cell, delta) }
}))
// §SUITES1018: the console suite's two passes (all of it on sbx-beta, the everything-on pass on sbx-alpha) by their target
function consoleTarget(run: McpTesterRunMeta): string {
  return run.flow_name === 'flow_playwright_console_lifecycles' ? targetOf(run as unknown as TrendRun) : ''
}
function historyPassTitle(run: McpTesterRunMeta, c: HistoryCell | null): string {
  if (!run.summary || !c) return ''
  const r = c.reading
  const parts = [tp('mcpTester.pass.tipClasses', '{passed} passed · {failed} failed · {skipped} not measured · {rule} refused by rule = {rows}',
    { passed: r.measured, failed: r.failed, skipped: r.skipped, rule: r.byRule, rows: r.measured + r.failed + r.skipped + r.byRule })]
  const ro = readRefusalOnly(run.summary as { refusal_only?: unknown; target_counts?: unknown })
  if (ro) parts.push(refusalOnlyLine(ro))
  if (c.fraction?.over === 'measured' && r.skipped + r.byRule > 0) {
    parts.push(tp('mcpTester.history.tipOverMeasured', 'This suite divides by the {den} steps it measured: its {n} not measured are left out of the figure.',
      { den: c.fraction.den, n: r.skipped + r.byRule }))
  } else if (c.fraction?.over === 'rows' && r.skipped + r.byRule > 0) {
    parts.push(tp('mcpTester.history.tipOverRows', 'This suite divides by every row: its {n} rows not run count against the figure; they are not failures.',
      { n: r.skipped + r.byRule }))
  }
  if (r.overlap > 0 && r.recordedPct !== null) {
    parts.push(tp('mcpTester.pass.tipRecorded', 'This run recorded {recorded}%: it counted {n} rows it never called as passes (the flows count four separate classes since V0539).',
      { recorded: r.recordedPct.toFixed(2), n: r.overlap }))
  }
  return parts.join('\n')
}
function deltaKind(d: number): 'up' | 'down' | 'flat' {
  return d > 0 ? 'up' : d < 0 ? 'down' : 'flat'
}
function fmtDelta(d: number): string {
  return d > 0 ? `▲${d.toFixed(2)}` : d < 0 ? `▼${Math.abs(d).toFixed(2)}` : '='
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(appLocale(), { hour12: false })
}

// pass73.3.19 (2026-05-28) — History "Started" cell showed time only, so you
// couldn't tell WHICH DAY a run was. Show compact date + time.
function fmtStarted(ts: number | null | undefined): string {
  // §MCPTEST30 (V0539): a record's start can be null (the type said number, three callers passed number | null)
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString(appLocale(), {
    month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

// ─── API actions ─────────────────────────────────────────────────────────

async function startRun() {
  if (isRunning.value && runSilentSince.value === null) return
  try {
    logLines.value = []
    summary.value = null
    loadedFlowName.value = selectedFlow.value
    bugFinds.value = []
    hardFails.value = []
    skipped.value = []
    policyDenied.value = []
    results.value = []
    activeTab.value = 'log'

    const resp = await mcpTesterApi.startRun(selectedFlow.value)
    latestRunId.value = resp.run_id
    targetUrl.value = resp.target
    isSandboxBackend.value = resp.is_sandbox
    isRunning.value = true
    startedAt.value = resp.started_at
    loadedStartedAt.value = resp.started_at ?? null

    log.info(`[mcp-tester] started run ${resp.run_id} (flow=${selectedFlow.value})`)
    openStream(resp.run_id)
    startElapsedTimer()
    await loadRunHistory()
  } catch (err: any) {
    log.error('startRun failed', err)
    const msg = err?.response?.data?.detail || err?.message || 'Unknown error'
    logLines.value.push({ ts: Date.now() / 1000, msg: `ERROR: ${msg}` })
    isRunning.value = false
    if (msg.toLowerCase().includes('sandbox')) {
      isSandboxBackend.value = false
    }
  }
}

function openStream(runId: string) {
  closeStream()
  // §RELEASEHARDEN D2 (2026-09-14) — the run log streams over fetch with the JWT in the Authorization
  // header (services/sse.ts). The EventSource before it could only send `?access_token=`, which this
  // route never read (so every run fell back to polling after one refused open) and which wrote the
  // token into the access log on that open. Polling stays the fallback when the stream cannot open.
  let sseUsable = true
  const token = auth.token || ''
  if (!token) {
    pollTimer = setInterval(() => pollRun(runId), 2000)
    return
  }
  const fallBackToPolling = () => {
    if (sseUsable) {
      sseUsable = false
      log.warn('SSE unavailable — polling fallback')
    }
    closeStream()
    pollTimer = setInterval(() => pollRun(runId), 2000)
  }
  // §MCPTEST30 (V0535): the stream replays the run's log from its first line; the n-th streamed line is the run's n-th
  let streamed = 0
  try {
    const url = mcpTesterApi.streamUrl(runId)
    eventSource = openSse(url, {
      headers: { Authorization: `Bearer ${token}` },
      onEvent: (ev) => {
        if (ev.event === 'log') {
          if (acceptStreamedLine(logLines.value, streamed, ev.data, Date.now() / 1000)) autoScrollLog()
          streamed += 1
        } else if (ev.event === 'status') {
          if (ev.data === 'completed' || ev.data === 'failed') {
            isRunning.value = false
          }
        } else if (ev.event === 'summary') {
          // §MCPTEST30 (V0541): the live sweep writes the page only while it is the run on screen; a run opened from
          // History mid-sweep had its summary replaced by the sweep's, and its tabs by the sweep's rows when it ended
          if (latestRunId.value === runId) {
            try { summary.value = JSON.parse(ev.data) } catch { /* */ }
          }
        } else if (ev.event === 'done') {
          isRunning.value = false
          stopElapsedTimer()
          closeStream()
          if (latestRunId.value === runId) loadRun(runId)
          loadRunHistory()
        }
      },
      onError: fallBackToPolling,
      // the server ends the stream after `done`; a stream that ends while the run is still going is
      // the old EventSource error case, and polling picks the run up
      onClose: () => { if (isRunning.value) fallBackToPolling() },
    })
  } catch {
    pollTimer = setInterval(() => pollRun(runId), 2000)
  }
}

function closeStream() {
  if (eventSource) { eventSource.close(); eventSource = null }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function pollRun(runId: string) {
  try {
    const run = await mcpTesterApi.getRun(runId, false)
    // §MCPTEST30 (V0541): the sweep's summary and rows reach the page only while it is the run on screen (see openStream)
    if (run.summary && latestRunId.value === runId) summary.value = run.summary
    logLines.value = run.log_lines.map((l) => ({ ts: l.ts, msg: l.msg }))
    autoScrollLog()
    if (run.status === 'completed' || run.status === 'failed') {
      isRunning.value = false
      stopElapsedTimer()
      closeStream()
      if (latestRunId.value === runId) await loadRun(runId)
      await loadRunHistory()
    }
  } catch (err) {
    log.error('pollRun failed', err)
  }
}

async function loadRun(runId: string) {
  try {
    const run = await mcpTesterApi.getRun(runId, true)
    summary.value      = run.summary
    loadedFlowName.value = run.flow_name || run.summary?.flow_name || null
    loadedStartedAt.value = run.started_at ?? null
    // §MCPTEST30 (V0539): objects from the flows, "name: text" strings from a console suite run (runReading.namedEntries)
    bugFinds.value     = namedEntries(run.bug_finds)
    hardFails.value    = namedEntries(run.hard_fails)
    skipped.value      = namedEntries(run.skipped)
    policyDenied.value = namedEntries(run.policy_denied)
    results.value      = run.results || []
    latestRunId.value  = runId
    startedAt.value    = run.started_at
    finishedAt.value   = run.finished_at
    isRunning.value    = run.status === 'running' || run.status === 'queued'
    logLines.value     = run.log_lines.map((l) => ({ ts: l.ts, msg: l.msg }))
    // Phase F drift detail surfaces — backend persists these on summary.
    const s = (run.summary || {}) as any
    phaseFDetails.value = {
      wrapper_drift_details:    Array.isArray(s.wrapper_drift_details) ? s.wrapper_drift_details : [],
      cross_frame_drift_details: Array.isArray(s.cross_frame_drift_details) ? s.cross_frame_drift_details : [],
      auth_matrix_failed_tools:  Array.isArray(s.auth_matrix_failed_tools) ? s.auth_matrix_failed_tools : [],
      // pass73.3.19 — latency_regressions_details added by backend (mcp_tester.py)
      latency_regressions_details: Array.isArray(s.latency_regressions_details) ? s.latency_regressions_details : [],
    }
    if (isRunning.value) startElapsedTimer()
    await nextTick()
    autoScrollLog()
  } catch (err) {
    log.error('loadRun failed', err)
  }
}

/** §MCPTEST30 (V0535): open a finished run without losing the sweep in flight. loadRun takes the loaded run's status as
 *  the page's, so viewing an old run mid-sweep re-armed "Run" and stopped the elapsed clock while the sweep ran on. */
async function viewRun(runId: string) {
  const live = isRunning.value && runSilentSince.value === null   // a run that stopped reporting is not kept as live
  const liveLog = logLines.value
  const liveStarted = startedAt.value
  await loadRun(runId)
  if (live) {
    isRunning.value = true
    logLines.value = liveLog
    startedAt.value = liveStarted
    startElapsedTimer()
  }
}

async function loadLatest() {
  try {
    const { run } = await mcpTesterApi.latest()
    if (run) await loadRun(run.run_id)
    await loadRunHistory()
  } catch (err) {
    log.error('loadLatest failed', err)
  }
}

async function loadRunHistory() {
  try {
    const { runs } = await mcpTesterApi.listRuns()
    runHistory.value = runs
    historyFailed.value = false
    // A backend before V0541 does not state its posture: read it from the newest run whose summary this console's
    // mapper wrote (it sets a boolean is_sandbox). §MCPTEST30 (V0541): a console suite run carries neither (its target
    // is a label, "Sandbox Alpha"), and taking it made the page refuse over a sweep running against the sandbox.
    const last = postureFromBackend.value ? undefined : runs.find((r) => typeof r.summary?.is_sandbox === 'boolean')
    if (last?.summary) {
      targetUrl.value = last.summary.target || ''
      isSandboxBackend.value = !!last.summary.is_sandbox
    }
  } catch (err) {
    historyFailed.value = !runHistory.value.length
    log.error('loadRunHistory failed', err)
  }
}

function downloadJson() {
  if (!latestRunId.value || !summary.value) return
  const payload = {
    run_id:     latestRunId.value,
    summary:    summary.value,
    bug_finds:  bugFinds.value,
    hard_fails: hardFails.value,
    skipped:    skipped.value,
    policy_denied: policyDenied.value,
    results:    results.value,
    log_lines:  logLines.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `mcp-tester-${latestRunId.value}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// Pass 10 (2026-05-28) — CSV export for the per-tool results table.
// One row per tool; columns chosen to be Excel/sheets friendly.
function downloadCsv() {
  if (!latestRunId.value || results.value.length === 0) return
  const header = [
    'tool', 'tier', 'healthy', 'skipped', 'status', 'elapsed_ms',
    'latency_regression', 'latency_baseline_ms', 'error', 'skip_reason',
    'flake_score', 'category', 'outcome',
  ].join(',')
  const escape = (s: any) => {
    if (s === null || s === undefined) return ''
    const str = String(s).replace(/"/g, '""')
    return /[,"\n]/.test(str) ? `"${str}"` : str
  }
  const lines = [header]
  for (const r of results.value) {
    lines.push([
      escape(r.tool),
      escape(r.tier || ''),
      escape(r.healthy ? 'true' : 'false'),
      escape(r.skipped ? 'true' : 'false'),
      escape(r.status || ''),
      escape(r.elapsed || 0),
      escape(r.latency_regression ? 'true' : 'false'),
      escape(r.latency_baseline_ms || 0),
      escape(r.error || ''),
      escape(r.skip_reason || ''),
      escape(flakeScoreFor(r.tool).failed),
      escape(categorizeTool(r.tool, r.tier)),
      escape(outcomeOf(r)),
    ].join(','))
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `mcp-tester-${latestRunId.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// Pass 10 (2026-05-28) — Flake detection: walk runHistory backward and
// count how many of the last N runs failed for each tool. Caches per-call
// since runHistory[] is small.
const FLAKE_WINDOW = 5
const _flakeCache = new Map<string, { failed: number; total: number }>()
function flakeScoreFor(tool: string): { failed: number; total: number } {
  if (_flakeCache.has(tool)) return _flakeCache.get(tool)!
  let failed = 0
  let total  = 0
  // Walk runHistory (newest first) — each entry's summary may not have results
  // so we treat absence as "no signal". Best-effort.
  for (const run of runHistory.value.slice(0, FLAKE_WINDOW)) {
    const s: any = run.summary
    if (!s || !Array.isArray(s.auth_matrix_failed_tools)) continue
    // Limited signal: auth_matrix_failed_tools encodes flakes for that axis
    total++
    if (s.auth_matrix_failed_tools.some((t: string) => t.startsWith(tool + '('))) failed++
  }
  // Also count current run + bug-finds
  if (bugFinds.value.some((b: any) => b.tool === tool)) failed++
  if (hardFails.value.some((h: any) => h.tool === tool)) failed++
  const out = { failed, total }
  _flakeCache.set(tool, out)
  return out
}
// Reset cache when results change (different run loaded)
watch(latestRunId, () => _flakeCache.clear())

// Pass 10 (2026-05-28) — Deep-link to failure via URL hash (?focus=tool_X).
// On mount, if hash carries focus param, scroll to + expand that row.
function applyDeepLinkFromHash() {
  const hash = window.location.hash || ''
  const m = hash.match(/[?&]focus=([^&]+)/)
  if (!m) return
  const tool = decodeURIComponent(m[1])
  // Auto-expand row + parent category
  for (const cat of categorizedFilteredResults.value) {
    if (cat.tools.some((r: any) => r.tool === tool)) {
      expandedCategories.value.add(cat.name)
      expandedRows.value.add(tool)
      expandedCategories.value = new Set(expandedCategories.value)
      expandedRows.value      = new Set(expandedRows.value)
      persistCategoryExpansion(); persistRowExpansion()
      nextTick(() => {
        const el = document.querySelector(`[data-testid="mcp-row-${tool}"]`) as HTMLElement | null
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          el.focus()
        }
      })
      break
    }
  }
}
function shareDeepLink(tool: string) {
  const base = window.location.href.split('?')[0].split('&')[0]
  const link = `${base}?focus=${encodeURIComponent(tool)}`
  navigator.clipboard?.writeText(link).then(() => {
    const tid = `dl-${tool}-${Date.now()}`
    refireToasts.value.push({
      id: tid, tool, healthy: true, elapsed: 0, status: 0, kind: 'share',
    })
    setTimeout(() => dismissToast(tid), 3200)
  })
}

function autoScrollLog() {
  nextTick(() => {
    if (logScroll.value) {
      logScroll.value.scrollTop = logScroll.value.scrollHeight
    }
  })
}

function startElapsedTimer() {
  stopElapsedTimer()
  nowTick.value = Date.now()
  elapsedTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
}

function stopElapsedTimer() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
}

// ─── Lifecycle ───────────────────────────────────────────────────────────

// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a page left during its first reads opens no stream and starts no timer when they land
const alive = useAlive()
onMounted(async () => {
  // §pass73.3.19 — populate the suite selector (federation + cloud-op sweeps
  // now run from this view too). Falls back to the hardcoded default on error.
  try {
    const fr = await mcpTesterApi.listFlows()
    if (fr?.flows?.length) {
      availableFlows.value = fr.flows
      if (!availableFlows.value.some(f => f.flow_name === selectedFlow.value)) {
        selectedFlow.value = fr.default || availableFlows.value[0].flow_name
      }
    }
    // §MCPTEST30 (V0541): this console's own posture, from this console (a backend before V0541 does not say it)
    if (typeof fr?.target === 'string' && typeof fr?.is_sandbox === 'boolean') {
      targetUrl.value = fr.target
      isSandboxBackend.value = fr.is_sandbox
      postureFromBackend.value = true
    }
  } catch { /* keep hardcoded default */ }
  await loadRunHistory()
  if (!alive()) return
  if (runHistory.value.length > 0) {
    const latest = runHistory.value[0]
    if (latest) {
      await loadRun(latest.run_id)
      if (!alive()) return
      if (latest.status === 'queued' || latest.status === 'running') {
        isRunning.value = true
        openStream(latest.run_id)
        startElapsedTimer()
      }
    }
  }
  lastRunRead.value = true
  // Pass 2 (2026-05-28) — when results already exist on mount, default
  // to the All-tools tab so categorized rows are visible immediately.
  // Otherwise keep Live log default (which shows the EventStore feed).
  // Honors a localStorage override if the user manually selected a tab.
  try {
    const stickyTab = localStorage.getItem('mcp_tester_active_tab') as TabId | null
    if (stickyTab && tabs.value.some(t => t.id === stickyTab)) {
      activeTab.value = stickyTab
    } else if (results.value.length > 0) {
      activeTab.value = 'results'
    }
  } catch { /* localStorage may be unavailable */ }
  const askedTab = tabFromQuery(route.query.tab)
  if (askedTab) activeTab.value = askedTab
  // Subscribe to ES via SSE proxy (mTLS pipe to event-store-test:8200).
  evtConnect()
  // Pass 10 (2026-05-28) — auto-open deep-linked tool if focus=X in URL
  setTimeout(applyDeepLinkFromHash, 800)
})

// Persist tab selection so the user lands where they were last
watch(activeTab, (newTab) => {
  try { localStorage.setItem('mcp_tester_active_tab', newTab) } catch { /* */ }
})

onUnmounted(() => {
  closeStream()
  stopElapsedTimer()
  evtClose()
})

// Auto-switch tab when BUG-FIND or hard-fail counts move
watch(
  () => [bugFinds.value.length, hardFails.value.length],
  ([newBugs, newFails], [oldBugs, oldFails]) => {
    if (newBugs > (oldBugs || 0)) activeTab.value = 'bugfind'
    else if (newFails > (oldFails || 0)) activeTab.value = 'fails'
  }
)
</script>

<style scoped>
.mcp {
  position: relative;
  min-height: 100vh;
  padding: 0 0 40px;
  /* Don't paint an opaque background — let DashboardLayout <ViewAmbient>
     show through (global rule §25 auto-suppresses the local .mcp-ambient
     when ambient layer is active). Mirrors AdminReactors / AdminCanaries. */
  color: var(--text-primary, #e8eaed);
  /* Theme-aware tokens (audit 2026-05-07 pattern):
     - var(--cyan) aliases the global brand-theme primary (neural=cyan, sovereign=red)
     - var(--cyan-rgb) is the comma-separated RGB triple for rgba() usage */
  --cyan:      var(--nc-primary, #00d2d2);
  --cyan-rgb:  var(--nc-primary-rgb, 0, 210, 210);
  --red:       #ff3366;
  --green:     #00ff88;
  --amber:     #ffb84d;
  --muted:     #788593;  /* §FESUITE: 5.15:1 (#6b7785 was 4.25:1) */
  --border:    rgba(var(--cyan-rgb), 0.18);
  --surface:   #0a0d16;
  --surface-2: rgba(10, 13, 22, 0.85);
  --mono:      'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;
}

/* ── Ambient (auto-suppressed by neural-command.css §25) ─────────── */
.mcp-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.mcp-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.mcp-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg, transparent 0, transparent 3px,
    rgba(var(--cyan-rgb), 0.025) 3px, rgba(var(--cyan-rgb), 0.025) 4px
  );
}
.mcp-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.mcp-glow-1 { width: 480px; height: 480px; background: rgba(var(--cyan-rgb), 0.6); top: -100px; right: -100px; }
.mcp-glow-2 { width: 360px; height: 360px; background: rgba(255, 51, 102, 0.4); bottom: -80px; left: -80px; }

/* ── Hero ──────────────────────────────────────────────────────────── */
.mcp-hero {
  position: relative; z-index: 1; padding: 48px 32px 24px;
}
.mcp-hero-inner { max-width: 1280px; margin: 0 auto; }
.mcp-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px; border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
}
.mcp-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
  animation: mcpPulse 1.6s ease-in-out infinite;
}
@keyframes mcpPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.mcp-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 36px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--text-bright); line-height: 1.15;
}
.mcp-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.mcp-lead { color: var(--muted); font-size: 14px; max-width: 720px; line-height: 1.7; margin: 0; }
.mcp-lead strong { color: rgba(255, 255, 255, 0.85); font-weight: 600; }

.mcp-meta-row {
  display: flex; flex-wrap: wrap; gap: 18px; margin-top: 20px;
}
.mcp-meta {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 11px;
}
.mcp-meta-key {
  font-size: 9px; font-weight: 700; letter-spacing: 0.16em;
  color: rgba(var(--cyan-rgb), 0.7); text-transform: uppercase;
}
.mcp-meta-val { color: var(--text-bright); }
.mcp-meta-link {
  color: var(--cyan); text-decoration: none; border: 1px solid var(--border); border-radius: 5px; padding: 4px 10px;
}
.mcp-meta-link:hover { background: rgba(var(--cyan-rgb), 0.08); }
.mcp-meta-link-icon { width: 14px; height: 14px; }
.mcp-history-xlink { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; font-weight: 400; letter-spacing: 0.08em; padding: 3px 8px; }
.mcp-mode-sandbox { color: var(--green); }
.mcp-mode-proxy { color: var(--amber); }

/* ── Section wrapper ───────────────────────────────────────────────── */
.mcp-section {
  position: relative; z-index: 1;
  max-width: 1280px; margin: 24px auto 0; padding: 0 32px;
}
.mcp-parent-note {
  margin: 0; max-width: 72ch; font-size: 13px; line-height: 1.55; color: var(--muted);
  border-left: 2px solid rgba(var(--cyan-rgb), 0.45); padding: 4px 0 4px 12px;
}

/* ── Warning banner ────────────────────────────────────────────────── */
.mcp-warning-banner {
  display: flex; align-items: flex-start; gap: 12px;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.4);
  border-radius: 6px; padding: 14px 18px;
  color: #ffb3c1;
  font-size: 13px; line-height: 1.5;
}
.mcp-warning-icon { font-size: 18px; color: #ff3366; line-height: 1; flex-shrink: 0; }
.mcp-warning-banner strong { color: #ff5577; }
.mcp-warning-banner code {
  background: rgba(0, 0, 0, 0.3); padding: 1px 6px; border-radius: 3px;
  font-family: var(--mono); font-size: 11.5px; color: var(--cyan);
}

/* ── Controls row ──────────────────────────────────────────────────── */
.mcp-controls {
  display: flex; gap: 10px; align-items: center; margin-bottom: 20px; flex-wrap: wrap;
}
/* §FESUITE (V0638): the run-type select sizes to its longest option, and the cloud-operator flows' labels (47 characters
   since V0637) made it, and the column of buttons a phone stacks under it, wider than a 393 px screen. Capped at its row and
   allowed to shrink below its longest option (the browser cuts the shown label; the full one is in the list). */
.mcp-flow-select { max-width: 100%; min-width: 0; }
.mcp-btn {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 12px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  border-radius: 5px; padding: 9px 18px; cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s;
}
.mcp-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.mcp-btn-icon { font-size: 11px; line-height: 1; }
.mcp-btn-primary {
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.95), rgba(var(--cyan-rgb), 0.75));
  color: #001518;
  border-color: rgba(var(--cyan-rgb), 0.6);
  box-shadow: 0 4px 14px rgba(var(--cyan-rgb), 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}
.mcp-btn-primary:not(:disabled):hover { filter: brightness(1.1); transform: translateY(-1px); }
.mcp-btn-ghost {
  background: transparent; color: var(--text-bright);
  border-color: rgba(var(--cyan-rgb), 0.25);
}
.mcp-btn-ghost:not(:disabled):hover {
  border-color: var(--cyan); background: rgba(var(--cyan-rgb), 0.06);
}
.mcp-elapsed {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
  margin-left: auto;
}
.mcp-elapsed-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
  animation: mcpPulse 1.6s ease-in-out infinite;
}

/* ── Stats row ─────────────────────────────────────────────────────── */
.mcp-stats-row {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px; margin-bottom: 18px;
}
.mcp-stat {
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid var(--border);
  border-top-color: rgba(var(--cyan-rgb), 0.32);
  border-radius: 5px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(var(--cyan-rgb), 0.05);
}
.mcp-stat--success { border-top-color: var(--green); }
.mcp-stat--danger  { border-top-color: var(--red); }
.mcp-stat--warning { border-top-color: #fbbf24; }
.mcp-stat--muted   { border-top-color: rgba(107, 119, 133, 0.4); }
.mcp-stat-label {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  letter-spacing: 0.18em; color: rgba(var(--cyan-rgb), 0.85);
  text-transform: uppercase;
  display: inline-flex; align-items: baseline; gap: 4px;
}
.mcp-stat-tip {
  font-size: 9px; opacity: 0.55; cursor: help; font-weight: 400;
}
.mcp-stat-value {
  font-family: 'Orbitron', var(--mono); font-size: 30px; font-weight: 700;
  color: var(--text-bright); line-height: 1;
}
.mcp-stat--success .mcp-stat-value { color: var(--green); text-shadow: 0 0 12px rgba(0, 255, 136, 0.35); }
.mcp-stat--danger .mcp-stat-value  { color: var(--red);   text-shadow: 0 0 12px rgba(255, 51, 102, 0.35); }
.mcp-stat--warning .mcp-stat-value { color: #fbbf24;     text-shadow: 0 0 12px rgba(251, 191, 36, 0.35); }
.mcp-stat--muted .mcp-stat-value   { color: var(--muted); }
/* emission_integrity word value (OK / WARN / DEGRADED) — smaller than the
   30px numeric so an 8-char status word fits the 160px stat card. */
.mcp-stat-value--word { font-size: 18px; letter-spacing: 0.04em; }
.mcp-stat-sub {
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.mcp-stat-breakdown {
  /* §MCPTEST30 (V0539): four chips share the card's row (a fourth class, the rule's refusals); a narrow card wraps whole chips */
  display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 2px;
}
.mcp-chip {
  font-family: var(--mono); font-size: 9.5px; font-weight: 700;
  padding: 1px 6px; border-radius: 3px; letter-spacing: 0.04em;
  border: 1px solid currentColor;
}
/* §MCPTEST30 (V0552): the pass-rate counts, a class of their own (not buttons, not the banner) */
.mcp-count {
  display: inline-flex; align-items: center; gap: 2px;
  font-family: var(--mono); font-size: 9.5px; font-weight: 700; font-variant-numeric: tabular-nums;
  padding: 1px 5px; border-radius: 3px; letter-spacing: 0.04em; line-height: 1.5; white-space: nowrap;
  border: 1px solid currentColor; cursor: default;
}
.mcp-count-icon { font-size: 10px; width: 1em; height: 1em; flex: none; }
.mcp-count--ok    { color: var(--green); background: rgba(0, 255, 136, 0.06); }
.mcp-count--bad   { color: var(--red);   background: rgba(255, 51, 102, 0.06); }
.mcp-count--muted { color: var(--muted); background: rgba(107, 119, 133, 0.06); }
/* §MCPTEST30 (V0539): refused by a standing rule, never called: neither a pass nor a hole (#a5b4fc is 9:1 on the card) */
.mcp-count--rule  { color: #a5b4fc; background: rgba(165, 180, 252, 0.08); }
/* §MCPTEST30 (V0549): the depth of the passes, folded under the rate (a details element: a tap opens it, no hover) */
.mcp-depth { margin-top: 6px; font-size: 11px; color: var(--muted); }
.mcp-depth-summary { display: flex; flex-direction: column; gap: 4px; cursor: pointer; list-style: none; }
.mcp-depth-summary::-webkit-details-marker { display: none; }
.mcp-depth-summary:focus-visible { outline: 1px solid rgba(var(--cyan-rgb), 0.6); outline-offset: 2px; border-radius: 3px; }
.mcp-depth-bar { display: flex; height: 5px; border-radius: 3px; overflow: hidden; background: rgba(107, 119, 133, 0.18); }
.mcp-depth-seg { display: block; min-width: 0; }
.mcp-depth-seg--success_contract { background: var(--green); }
.mcp-depth-seg--success_default { background: rgba(0, 255, 136, 0.38); }
.mcp-depth-seg--refusal_contract { background: #a5b4fc; }
.mcp-depth-seg--refusal_default { background: rgba(107, 119, 133, 0.75); }
.mcp-depth-line { line-height: 1.35; text-decoration: underline dotted rgba(107, 119, 133, 0.6); text-underline-offset: 2px; }
.mcp-depth[open] .mcp-depth-line { text-decoration: none; color: var(--text-bright); }
.mcp-depth-list { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.mcp-depth-list li { display: grid; grid-template-columns: 8px auto 1fr; gap: 6px; align-items: baseline; line-height: 1.35; }
.mcp-depth-dot { width: 8px; height: 8px; border-radius: 2px; align-self: start; margin-top: 4px; }  /* on the first line of a wrapped meaning */
.mcp-depth-n { font-family: var(--mono); font-variant-numeric: tabular-nums; color: var(--text-bright); }
/* §MCPTEST30 (V0550): the target's switches, folded under the pass rate like the depth */
.mcp-switches-body { margin-top: 6px; display: flex; flex-direction: column; gap: 6px; }
.mcp-switches-what { margin: 0; line-height: 1.35; }
.mcp-switches-list { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.mcp-switches-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
/* Pass 2 (2026-05-28) — toggle chip variant (filter buttons in toolbar) */
.mcp-chip[class*="mcp-chip"] { cursor: pointer; transition: all 0.15s; }
.mcp-chip[class*="mcp-chip"]:hover { transform: translateY(-1px); }
.mcp-chip--on {
  color: var(--amber, #fbbf24) !important;
  background: rgba(251, 191, 36, 0.18) !important;
  box-shadow: 0 0 8px rgba(251, 191, 36, 0.35);
}

/* ── Phase E.3 — BUG-FIND persistent banner ──────────────────────────── */
.mcp-bugfind-banner {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(90deg, rgba(255, 51, 102, 0.18), rgba(255, 51, 102, 0.06));
  border: 1px solid rgba(255, 51, 102, 0.45);
  border-left: 4px solid var(--red);
  border-radius: 5px;
  cursor: pointer;
  transition: background 120ms ease;
}
.mcp-bugfind-banner:hover { background: linear-gradient(90deg, rgba(255, 51, 102, 0.28), rgba(255, 51, 102, 0.10)); }
.mcp-bugfind-icon  { font-size: 22px; color: var(--red); text-shadow: 0 0 8px rgba(255, 51, 102, 0.5); }
.mcp-bugfind-text  { flex: 1; font-size: 13px; color: var(--text-bright); line-height: 1.5; }
.mcp-bugfind-text strong { color: var(--red); font-family: 'Orbitron', var(--mono); }
.mcp-bugfind-arrow { font-size: 18px; color: var(--red); opacity: 0.7; }

/* ── Phase E.3 — Sweep timing analytics card ─────────────────────────── */
.mcp-card--timing { margin-bottom: 14px; }
.mcp-timing-row {
  /* Bug fix (2026-05-28 pass73.3.19): minmax(220px) caused overlap on
     mid-widths when tool names exceeded 14 chars. Widen to 280px and
     allow content to ellipse. */
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 6px; padding: 10px 14px;
}
.mcp-timing-cell {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 8px; border-radius: 3px;
  background: rgba(10, 13, 22, 0.55);
  border-left: 2px solid rgba(var(--cyan-rgb), 0.25);
  font-size: 11px;
  min-width: 0;       /* allow inner code to shrink */
  gap: 8px;           /* breathing room between tool name + ms */
  overflow: hidden;
}
.mcp-timing-cell > code {
  flex: 1 1 auto; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mcp-timing-cell--bad {
  border-left-color: var(--red);
  background: rgba(255, 51, 102, 0.06);
}
.mcp-timing-ms {
  font-family: var(--mono); font-weight: 700;
  color: rgba(var(--cyan-rgb), 0.9);
}
.mcp-timing-cell--bad .mcp-timing-ms { color: #ffb3c1; }

/* ── Phase E.3 — Trajectory sparkline ────────────────────────────────── */
.mcp-trajectory {
  padding: 12px 14px; margin-bottom: 14px;
  background: rgba(10, 13, 22, 0.5); border: 1px solid var(--border);
  border-radius: 5px;
}
.mcp-trajectory-label {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.12em;
  color: rgba(var(--cyan-rgb), 0.85); text-transform: uppercase;
  margin-bottom: 8px;
  display: flex; gap: 8px; align-items: baseline;
}
.mcp-trajectory-svg {
  display: block; width: 100%; height: 56px;
  filter: drop-shadow(0 0 4px rgba(var(--cyan-rgb), 0.25));
}

/* ── Phase E.3 — pass-rate cell colour-coding (history) ──────────────── */
.mcp-passrate--ok   { color: var(--green); font-weight: 700; }
.mcp-passrate--warn { color: #fbbf24;     font-weight: 700; }
.mcp-passrate--bad  { color: var(--red);   font-weight: 700; }
/* §SUITES1018: what a History figure divides (the category bar's parts and colours, kept on a phone too), and the words
   that name what is missing from it */
.mcp-hist-bar {
  display: flex;
  height: 3px;
  width: 100%;
  max-width: 168px;
  margin-top: 4px;
  background: rgba(var(--cyan-rgb), 0.08);
  border-radius: 2px;
  overflow: hidden;
}
.mcp-hist-why { display: block; margin-top: 3px; font-size: 10px; line-height: 1.35; color: var(--muted); white-space: normal; }
.mcp-hist-why--bad { color: var(--red); }
.mcp-hist-target { display: block; margin-top: 3px; font-size: 10px; color: var(--muted); }
/* §MCPTEST30 (V0539): the change from the suite's previous run */
.mcp-delta { margin-left: 6px; font-size: 10px; font-weight: 700; white-space: nowrap; }
.mcp-delta--up   { color: var(--green); }
.mcp-delta--down { color: #fbbf24; }
.mcp-delta--flat { color: var(--muted); }

/* ── Phase F.2 — latency-regression marker on All-tools row ──────────── */
.mcp-latency-flag {
  display: inline-block; margin-left: 6px;
  padding: 1px 5px; font-size: 9.5px;
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.5);
  border-radius: 3px; color: #fbbf24;
  font-family: var(--mono); cursor: help;
}

/* ── Phase F detail tab ─────────────────────────────────────────────── */
.mcp-phasef-grid {
  display: flex; flex-direction: column; gap: 14px; padding: 14px;
}
.mcp-card--warning { border-top-color: #fbbf24; }
.mcp-badge--warning { background: rgba(251, 191, 36, 0.12); color: #fbbf24; }
.mcp-phasef-list { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 14px; }
.mcp-phasef-chip {
  padding: 3px 8px; font-size: 11px;
  background: rgba(255, 51, 102, 0.10);
  border: 1px solid rgba(255, 51, 102, 0.45);
  border-radius: 3px; color: #ffb3c1;
  /* §MCPTEST30 (V0549): a tool name with its credential and status is one long word (it ran 55 px past a phone) */
  max-width: 100%; overflow-wrap: anywhere;
}
/* §MCPTEST30 (V0549): a long reported list folds (open up to five rows); a tap or a key opens it */
.mcp-fold > summary { cursor: pointer; padding: 8px 14px; font-size: 11px; color: var(--muted); letter-spacing: 0.04em; list-style: none; }
.mcp-fold > summary::-webkit-details-marker { display: none; }
.mcp-fold > summary::before { content: '▸ '; }
.mcp-fold[open] > summary::before { content: '▾ '; }
.mcp-fold > summary:focus-visible { outline: 1px solid rgba(var(--cyan-rgb), 0.6); outline-offset: -2px; }
/* §MCPTEST30 (V0549): a detector the run did not measure recedes beside the measured tiles; its dash and its line say why */
.mcp-stat[data-measured="0"] { border-style: dashed; box-shadow: none; }
.mcp-stat[data-measured="0"] .mcp-stat-value { color: var(--muted); opacity: 0.55; }

/* ── Coverage gauge ────────────────────────────────────────────────── */
.mcp-gauge {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 18px;
  background: rgba(10, 13, 22, 0.6); border: 1px solid var(--border);
  border-radius: 5px;
}
.mcp-gauge-track {
  flex: 1; position: relative; height: 10px;
  background: rgba(0, 0, 0, 0.5); border-radius: 5px;
  overflow: hidden;
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.mcp-gauge-fill {
  height: 100%; transition: width 0.6s ease;
  background: linear-gradient(90deg, var(--cyan), var(--green));
  box-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45);
}
.mcp-gauge-sparkle {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  font-size: 10px; color: var(--green);
  text-shadow: 0 0 8px rgba(0, 255, 136, 0.8);
  animation: mcpPulse 1.6s ease-in-out infinite;
}
.mcp-gauge-label {
  font-family: var(--mono); font-size: 12px; color: var(--muted);
  white-space: nowrap;
}
.mcp-gauge-label strong { color: var(--text-bright); font-weight: 700; font-size: 13px; }

/* ── Tabbar ────────────────────────────────────────────────────────── */
.mcp-tabbar-wrap {
  position: relative; z-index: 1;
  padding: 4px 32px 0;
  max-width: 1280px; margin: 24px auto 0;
}
.mcp-tabbar {
  /* §MCPTEST30 (V0535): eight tabs wrap as whole tabs, never inside a label */
  display: inline-flex; flex-wrap: wrap; gap: 4px; max-width: 100%;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px; padding: 4px;
}
.mcp-tabbar-btn {
  /* §MCPTEST30 (V0539): 8 px sides and 0.05em let all eight tabs share one row at 1440 (History wrapped alone) */
  display: inline-flex; align-items: center; gap: 0.45rem;
  background: transparent; border: none; border-radius: 5px;
  padding: 8px 8px; cursor: pointer; white-space: nowrap;
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55); transition: all 0.15s;
}
.mcp-tabbar-btn:hover {
  color: rgba(255, 255, 255, 0.95); background: rgba(var(--cyan-rgb), 0.06);
}
.mcp-tabbar-btn--active {
  background: rgba(var(--cyan-rgb), 0.18); color: var(--cyan);
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.35);
}
.mcp-tabbar-icon { font-size: 0.95rem; color: rgba(var(--cyan-rgb), 0.85); display: inline-flex; align-items: center; }
.mcp-tabbar-btn--active .mcp-tabbar-icon { color: var(--cyan); }
.mcp-tabbar-count {
  background: rgba(var(--cyan-rgb), 0.2); color: var(--cyan);
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  padding: 1px 7px; border-radius: 8px;
  font-size: 0.6rem; font-weight: 700;
}

/* ── Cards ─────────────────────────────────────────────────────────── */
.mcp-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.92), rgba(6, 8, 16, 0.92));
  border: 1px solid var(--border);
  border-top-color: rgba(var(--cyan-rgb), 0.32);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(var(--cyan-rgb), 0.05);
}
.mcp-card--danger { border-top-color: var(--red); }
.mcp-card-header {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08);
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--text-bright);
}
.mcp-card-icon { color: var(--cyan); font-size: 14px; }
.mcp-card-meta {
  margin-left: auto; font-weight: 400; color: var(--muted);
  font-size: 10px; letter-spacing: 0.08em;
}

/* Pass 8 (2026-05-28) — status-code bucket chips */
.mcp-status-chips {
  display: inline-flex; gap: 4px;
  padding: 2px; background: rgba(0, 0, 0, 0.35);
  border-radius: 4px; border: 1px solid rgba(var(--cyan-rgb), 0.1);
}
.mcp-status-chip {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: none;
  color: rgba(255,255,255,0.6);
  font-family: var(--mono); font-size: 9.5px; font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px 9px; border-radius: 3px;
  cursor: pointer; transition: all 0.15s;
}
.mcp-status-chip:hover { color: var(--cyan); background: rgba(var(--cyan-rgb), 0.05); }
.mcp-status-chip-count {
  background: rgba(0,0,0,0.45); border-radius: 8px;
  font-size: 9px; padding: 0 5px;
}
.mcp-status-chip--active.mcp-status-chip--2xx { background: rgba(0, 255, 136, 0.20); color: var(--green); }
.mcp-status-chip--active.mcp-status-chip--4xx { background: rgba(251, 191, 36, 0.18); color: var(--amber, #fbbf24); }
.mcp-status-chip--active.mcp-status-chip--401,
.mcp-status-chip--active.mcp-status-chip--403,
.mcp-status-chip--active.mcp-status-chip--404 { background: rgba(251, 191, 36, 0.18); color: var(--amber, #fbbf24); }
.mcp-status-chip--active.mcp-status-chip--5xx { background: rgba(255, 51, 102, 0.18); color: var(--red); }
.mcp-status-chip--active.mcp-status-chip--all { background: rgba(255,255,255,0.10); color: #fff; }

.mcp-chip-num {
  margin-left: 4px; padding: 1px 5px;
  border-radius: 8px; background: rgba(0,0,0,0.4);
  font-size: 9px;
}

/* Pass 2 (2026-05-28) — sticky filter bar + pills */
.mcp-card-header--sticky {
  position: sticky; top: 0; z-index: 30;
  background: linear-gradient(180deg, rgba(8, 14, 22, 0.97) 0%, rgba(8, 14, 22, 0.92) 100%);
  backdrop-filter: blur(8px);
  flex-wrap: wrap; gap: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
}
.mcp-card--categories { overflow: visible; }
.mcp-pill-group {
  display: inline-flex; gap: 6px; align-items: center;
  margin-right: 8px;
}
.mcp-pill {
  display: inline-block;
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.04em; padding: 2px 9px; border-radius: 10px;
  border: 1px solid currentColor;
  background: rgba(0, 0, 0, 0.35);
}
.mcp-pill--ok   { color: var(--green); }
.mcp-pill--fail { color: var(--red); }
.mcp-pill--skip { color: var(--amber, #fbbf24); }
.mcp-pill--rule { color: #a5b4fc; }
.mcp-pill--meta { color: var(--muted); border-color: rgba(var(--cyan-rgb), 0.2); }

/* ── Log ───────────────────────────────────────────────────────────── */
.mcp-log {
  padding: 14px 18px;
  font-family: var(--mono); font-size: 11.5px; line-height: 1.55;
  flex: 1 1 auto; min-height: 0;          /* fill the flex card; scroll inside */
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.5);
}
.mcp-log::-webkit-scrollbar { width: 8px; background: rgba(0, 0, 0, 0.3); }
.mcp-log::-webkit-scrollbar-thumb { background: rgba(var(--cyan-rgb), 0.25); border-radius: 4px; }
.mcp-log-empty {
  color: var(--muted); text-align: center; padding: 36px 0;
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px;
}
.mcp-log-empty kbd {
  background: rgba(var(--cyan-rgb), 0.1); border: 1px solid rgba(var(--cyan-rgb), 0.25);
  padding: 2px 6px; border-radius: 3px; font-family: var(--mono); font-size: 10.5px;
  color: var(--cyan);
}
.mcp-log-line {
  display: flex; gap: 12px;
  padding: 1px 0;
  color: rgba(255, 255, 255, 0.7);
}
.mcp-log-line:last-child { color: var(--text-bright); }
.mcp-log-time { color: rgba(var(--cyan-rgb), 0.55); flex-shrink: 0; }
.mcp-log-msg { word-break: break-word; }

/* ── Live grid (log left + events right) ───────────────────────────── */
.mcp-live-grid {
  display: grid; gap: 14px;
  /* pass73.3.19 Pass-4 (2026-05-28) — EventStore pane (right) is the wider one:
     its rows carry long event-type names (CrossFrameTransferInitiated, …) that
     were being clipped. Log (left) is plain text, tolerates the narrower column. */
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.45fr);
  align-items: stretch;            /* both cards share the tallest height */
}
/* pass73.3.19 Pass-1 (2026-05-28) — frame-fill fix. The grid stretches the
   shorter (log) card to match the taller events card; make the cards flex
   columns and let their scroll panes grow so the log fills the frame instead
   of leaving dead space below a hard 420px cap. */
.mcp-live-grid > .mcp-card {
  display: flex; flex-direction: column;
  min-height: 480px; max-height: 78vh;
  overflow: hidden;                /* clip to rounded corners; panes scroll */
}
@media (max-width: 1100px) {
  .mcp-live-grid { grid-template-columns: 1fr; }
  .mcp-live-grid > .mcp-card { max-height: 70vh; }
}

/* Pass 11 (2026-05-28) — Mobile responsive */
@media (max-width: 900px) {
  .mcp-card-header--sticky { flex-direction: column; align-items: stretch; }
  .mcp-pill-group { order: -1; }
  .mcp-controls { flex-wrap: wrap; }
  .mcp-target-chips { flex-direction: column; align-items: stretch; }
  .mcp-target-chip { justify-content: center; }
  .mcp-events-toolbar { flex-wrap: wrap; }
  .mcp-events-search { min-width: 100%; }
  .mcp-frame-chip-group, .mcp-status-chips { flex-wrap: wrap; }
}
@media (max-width: 600px) {
  .mcp-event-row {
    grid-template-columns: 16px 56px min-content 1fr;
    font-size: 10px;
    padding: 6px 10px;
    gap: 6px;
  }
  .mcp-event-target, .mcp-event-source { display: none; }
  .mcp-stats-grid { grid-template-columns: 1fr 1fr !important; }
  .mcp-tabbar { overflow-x: auto; }
  .mcp-tabbar-count { display: none; }
  .mcp-detail-grid { grid-template-columns: 1fr; }
  .mcp-toast-stack { right: 8px; left: 8px; max-width: none; }
  /* §MCPTEST30 (V0542): the meta line wraps under the title instead of vanishing (the Drift tab's "not measured"
     readings, the Not run and BUG-FIND counts lived only there) */
  .mcp-card-header { flex-wrap: wrap; row-gap: 4px; }
  .mcp-card-meta { flex-basis: 100%; margin-left: 0; white-space: normal; }
  .mcp-diff-grid { grid-template-columns: 1fr; }
  /* a result table stacks a row's cells (the emission check's detail ran off the screen, cut mid-word) */
  .mcp-table--stack thead { display: none; }
  .mcp-table--stack, .mcp-table--stack tbody, .mcp-table--stack tr, .mcp-table--stack td {
    display: block; width: 100%; box-sizing: border-box;
  }
  .mcp-table--stack tr { padding: 8px 0; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08); }
  .mcp-table--stack td { border: 0 !important; padding: 2px 14px !important; text-align: left !important; }
  /* §MCPTEST30 (V0549): a route path or a handler name is one long word: in a stacked row it wraps inside its cell (it was
     clipped at the card edge); only here, so a desktop table never squeezes a tool name mid-word */
  .mcp-table--stack td, .mcp-table--stack .mcp-code { overflow-wrap: anywhere; }
  .mcp-table--stack td[data-label]::before {
    content: attr(data-label) " "; color: var(--muted); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
  }
  /* §MCPTEST30 (V0553): the All tools rows stack too (agentvault2-45's 393 px reading: 913 px of sideways scroll inside
     .mcp-results-scroll). The chevron sits beside the tool name, the four short cells share one line, the reason takes
     its own, and a passing row shows no empty reason line */
  .mcp-table--stack td.mcp-row-chevron-cell { float: left; width: auto; padding-right: 0 !important; }
  .mcp-table--stack td.mcp-cell-inline { display: inline-block; width: auto; }
  .mcp-table--stack td.mcp-cell-error:empty { display: none; }
}

/* ── EventStore live stream card ───────────────────────────────────── */
.mcp-events-card { border-top-color: rgba(var(--cyan-rgb), 0.4); }
.mcp-events {
  padding: 6px 4px 6px 0;
  font-family: var(--mono); font-size: 11px; line-height: 1.45;
  flex: 1 1 auto; min-height: 0;          /* fill the flex card; scroll inside */
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.5);
}
.mcp-events::-webkit-scrollbar { width: 8px; background: rgba(0, 0, 0, 0.3); }
.mcp-events::-webkit-scrollbar-thumb { background: rgba(var(--cyan-rgb), 0.25); border-radius: 4px; }
.mcp-event-row {
  /* Pass 7 (2026-05-28): grid was caret/time/type/target/source; added
     frame tag column between time and type. min-content keeps the chip
     compact. */
  display: grid;
  /* Pass 12 (2026-05-28): widened source col 110→180 for derived labels
     like "teg-layer-a → teg-layer-test-b"; trimmed target to 100.
     Pass-4 (2026-05-28): trimmed target 100→90 + source 180→150 to give the
     1fr type column more room (event names were clipping); pairs with the
     wider EventStore pane (live-grid 1fr→1.45fr). */
  grid-template-columns: 18px 72px min-content minmax(0, 1.6fr) 90px 150px;
  gap: 10px;
  padding: 5px 14px;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.04);
  transition: background-color 0.6s ease, border-left-color 0.15s;
  align-items: center;
  cursor: pointer;
  border-left: 2px solid transparent;
  outline: none;
}
.mcp-event-row:hover {
  background-color: rgba(var(--cyan-rgb), 0.08);
  border-left-color: rgba(var(--cyan-rgb), 0.5);
}
.mcp-event-row:focus-visible {
  background-color: rgba(var(--cyan-rgb), 0.12);
  border-left-color: var(--cyan);
}
.mcp-event-row--fresh {
  background-color: rgba(var(--cyan-rgb), 0.18);
  box-shadow: inset 2px 0 0 var(--cyan);
}
.mcp-event-row--expanded {
  background-color: rgba(var(--cyan-rgb), 0.10);
  border-left-color: var(--cyan);
  border-bottom-color: rgba(var(--cyan-rgb), 0.2);
}
.mcp-event-caret {
  color: rgba(var(--cyan-rgb), 0.6); font-size: 10px;
  transition: transform 0.15s, color 0.15s;
  text-align: center;
}
.mcp-event-row--expanded .mcp-event-caret { color: var(--cyan); }
.mcp-event-time { color: rgba(var(--cyan-rgb), 0.55); font-size: 10.5px; }
.mcp-event-type {
  font-weight: 600; font-size: 11px;
  letter-spacing: 0.02em;
  text-shadow: 0 0 6px currentColor;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mcp-event-target {
  color: var(--muted); font-size: 10.5px; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mcp-event-source {
  color: rgba(var(--cyan-rgb), 0.4); font-size: 9.5px;
  font-style: italic; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* Pass 7 (2026-05-28) — frame origin chip + row tinting */
.mcp-event-frame {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 22px; height: 16px; padding: 0 6px;
  border-radius: 8px;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.04em;
  border: 1px solid currentColor;
  text-shadow: 0 0 4px currentColor;
}
.mcp-event-frame--A     { color: var(--cyan); }
.mcp-event-frame--B     { color: #f472b6; }  /* magenta */
.mcp-event-frame--cross { color: var(--amber, #fbbf24); font-size: 11px; }
.mcp-event-row--frame-A { background-color: rgba(var(--cyan-rgb), 0.02); }
.mcp-event-row--frame-B { background-color: rgba(244, 114, 182, 0.04); }
.mcp-event-row--frame-cross {
  background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.04), rgba(244, 114, 182, 0.04));
}
.mcp-event-row--frame-A.mcp-event-row--fresh    { background-color: rgba(var(--cyan-rgb), 0.18); }
.mcp-event-row--frame-B.mcp-event-row--fresh    { background-color: rgba(244, 114, 182, 0.20); box-shadow: inset 2px 0 0 #f472b6; }
.mcp-event-row--frame-cross.mcp-event-row--fresh {
  background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.18), rgba(244, 114, 182, 0.20));
  box-shadow: inset 2px 0 0 var(--amber, #fbbf24);
}

/* Frame chip filter (toolbar) */
.mcp-frame-chip-group {
  display: inline-flex; gap: 4px;
  padding: 2px; background: rgba(0, 0, 0, 0.35);
  border-radius: 14px; border: 1px solid rgba(var(--cyan-rgb), 0.1);
}
.mcp-frame-chip {
  background: transparent;
  border: none;
  color: rgba(255,255,255,0.55);
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.04em;
  padding: 3px 9px; border-radius: 12px;
  cursor: pointer; transition: all 0.15s;
}
.mcp-frame-chip:hover { color: var(--cyan); }
.mcp-frame-chip--active.mcp-frame-chip--A     { background: var(--cyan); color: #000; }
.mcp-frame-chip--active.mcp-frame-chip--B     { background: #f472b6; color: #000; }
.mcp-frame-chip--active.mcp-frame-chip--cross { background: var(--amber, #fbbf24); color: #000; }
.mcp-frame-chip--active.mcp-frame-chip--all   { background: rgba(255,255,255,0.15); color: #fff; }

/* A+B toggle special highlight */
.mcp-events-toggle--frame-b.mcp-events-toggle--on {
  color: #f472b6; border-color: #f472b6;
  box-shadow: 0 0 8px rgba(244, 114, 182, 0.4);
}

/* §MCPTEST30 (V0541): the store the live panel reads */
.mcp-event-source {
  margin-left: 8px; padding: 1px 7px; border-radius: 3px; font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.02em; text-transform: none; color: #c3ccd6; background: rgba(120, 133, 147, 0.18);
}
/* ── EventStore toolbar (search + noise toggle) ────────────────────── */
.mcp-events-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 14px;
  background: rgba(0, 0, 0, 0.35);
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.mcp-events-search {
  flex: 1; min-width: 0;
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  color: var(--cyan); font-family: var(--mono); font-size: 11px;
  padding: 4px 9px; border-radius: 3px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.mcp-events-search:focus {
  outline: none; border-color: var(--cyan);
  box-shadow: 0 0 0 2px rgba(var(--cyan-rgb), 0.15);
}
.mcp-events-search::placeholder { color: rgba(var(--cyan-rgb), 0.35); }
.mcp-events-toggle {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(255, 255, 255, 0.7);
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  padding: 3px 9px; border-radius: 4px; cursor: pointer;
  letter-spacing: 0.06em; transition: all 0.15s;
  white-space: nowrap;
}
.mcp-events-toggle:hover { border-color: var(--cyan); color: var(--cyan); }
.mcp-events-toggle--on   { color: var(--green); border-color: var(--green); }
.mcp-events-hidden-hint {
  color: rgba(var(--cyan-rgb), 0.5);
  font-family: var(--mono); font-size: 10px;
  font-style: italic;
}
.mcp-events-pin-clear {
  background: rgba(var(--amber-rgb, 251, 191, 36), 0.15);
  border: 1px solid var(--amber);
  color: var(--amber);
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  padding: 3px 9px; border-radius: 4px; cursor: pointer;
  letter-spacing: 0.04em;
}
.mcp-events-pin-clear:hover { background: rgba(var(--amber-rgb, 251, 191, 36), 0.25); }

/* ── Type facet chips ──────────────────────────────────────────────── */
.mcp-events-facets {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 8px 14px;
  background: rgba(0, 0, 0, 0.25);
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.mcp-events-facet {
  --facet-color: rgba(var(--cyan-rgb), 0.7);
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid color-mix(in srgb, var(--facet-color) 30%, transparent);
  color: var(--facet-color);
  font-family: var(--mono); font-size: 9.5px; font-weight: 600;
  padding: 3px 7px 3px 9px; border-radius: 10px; cursor: pointer;
  letter-spacing: 0.03em;
  transition: all 0.15s;
}
.mcp-events-facet:hover {
  border-color: var(--facet-color);
  box-shadow: 0 0 8px color-mix(in srgb, var(--facet-color) 40%, transparent);
}
.mcp-events-facet--pinned {
  background: color-mix(in srgb, var(--facet-color) 22%, transparent);
  border-color: var(--facet-color);
  box-shadow: 0 0 10px color-mix(in srgb, var(--facet-color) 50%, transparent);
}
.mcp-events-facet-name { color: inherit; }
.mcp-events-facet-count {
  background: rgba(0, 0, 0, 0.4);
  padding: 1px 6px; border-radius: 10px;
  color: rgba(255, 255, 255, 0.9);
  min-width: 18px; text-align: center;
}

/* ── Inline expand panel (Mission Control / AdminEvents pattern) ──── */
.mcp-event-panel {
  padding: 14px 16px 16px 32px;
  background: rgba(0, 0, 0, 0.55);
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-left: 2px solid var(--cyan);
  animation: mcpEvtPanelOpen 0.18s ease-out;
}
@keyframes mcpEvtPanelOpen {
  from { opacity: 0; transform: translateY(-3px); }
  to   { opacity: 1; transform: translateY(0); }
}
.mcp-event-panel-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 8px 14px;
  margin-bottom: 10px;
}
.mcp-event-panel-cell {
  display: flex; flex-direction: column; gap: 2px;
}
.mcp-event-panel-label {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: rgba(var(--cyan-rgb), 0.55);
}
.mcp-event-panel-value {
  display: inline-flex; align-items: center; gap: 4px;
  color: rgba(255, 255, 255, 0.92);
  font-family: var(--mono); font-size: 10.5px;
  word-break: break-all;
}
.mcp-mini-copy {
  background: transparent; border: none; cursor: pointer;
  color: rgba(var(--cyan-rgb), 0.5);
  font-size: 11px; padding: 0 4px;
  transition: color 0.15s;
}
.mcp-mini-copy:hover { color: var(--cyan); }

/* Empty-state reset button */
.mcp-log-empty-reset {
  display: inline-block; margin-left: 10px;
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  color: var(--cyan); cursor: pointer;
  font-family: var(--mono); font-size: 10px;
  padding: 2px 8px; border-radius: 3px;
}
.mcp-log-empty-reset:hover { border-color: var(--cyan); background: rgba(var(--cyan-rgb), 0.1); }
.mcp-event-status {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.14em; padding: 2px 8px; border-radius: 3px;
  border: 1px solid currentColor;
  margin-left: 10px;
}
.mcp-event-status-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor; box-shadow: 0 0 6px currentColor;
}
.mcp-event-status--ok   { color: var(--green); }
.mcp-event-status--idle { color: var(--muted); }
.mcp-card-action {
  margin-left: 10px; border: 1px solid rgba(var(--cyan-rgb), 0.25);
  background: transparent; color: rgba(255, 255, 255, 0.7);
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  padding: 3px 9px; border-radius: 4px; cursor: pointer;
  letter-spacing: 0.06em; transition: all 0.15s;
}
.mcp-card-action:hover { border-color: var(--cyan); color: var(--cyan); }
.mcp-card-action--active { color: var(--amber); border-color: var(--amber); }

/* ── Tables ────────────────────────────────────────────────────────── */
.mcp-table { width: 100%; border-collapse: collapse; }
.mcp-table th, .mcp-table td {
  padding: 9px 14px; text-align: left;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.06);
  font-size: 12px; vertical-align: top;
}
.mcp-table th {
  background: rgba(0, 0, 0, 0.4);
  color: rgba(var(--cyan-rgb), 0.85);
  font-family: var(--mono); font-weight: 600;
  font-size: 9.5px; letter-spacing: 0.18em; text-transform: uppercase;
  position: sticky; top: 0; z-index: 2;
}
.mcp-table tbody tr:hover { background: rgba(var(--cyan-rgb), 0.04); }
.mcp-row--bug  { background: rgba(255, 51, 102, 0.08); }
.mcp-row--fail { background: rgba(255, 51, 102, 0.04); }
.mcp-row--skip { opacity: 0.55; }
.mcp-code {
  font-family: var(--mono); font-size: 11.5px; color: var(--cyan);
  background: rgba(var(--cyan-rgb), 0.05); padding: 1px 6px; border-radius: 3px;
}
.mcp-cell-error { color: #ffb3c1; font-size: 11.5px; line-height: 1.5; }
.mcp-cell-mono { font-family: var(--mono); font-size: 11px; color: var(--text-bright); }
.mcp-cell-muted { color: var(--muted); }

.mcp-results-scroll { max-height: 600px; overflow-y: auto; }
.mcp-results-scroll::-webkit-scrollbar { width: 8px; background: rgba(0, 0, 0, 0.3); }
.mcp-results-scroll::-webkit-scrollbar-thumb { background: rgba(var(--cyan-rgb), 0.25); border-radius: 4px; }

/* ── Empty state ───────────────────────────────────────────────────── */
.mcp-empty {
  padding: 36px 18px; text-align: center;
  font-family: var(--mono); font-size: 12px; color: var(--muted);
}
.mcp-empty-icon {
  display: inline-block; font-size: 18px; color: var(--green);
  margin-right: 6px;
  text-shadow: 0 0 8px rgba(0, 255, 136, 0.4);
}

/* Pass 11 (2026-05-28) — Skip rationale card */
.mcp-card--skip-rationale {
  border-top-color: var(--amber, #fbbf24);
  margin: 8px 0;
}
.mcp-skip-rationale-list {
  list-style: none; margin: 0; padding: 8px 14px 14px;
  display: grid; gap: 6px;
}
.mcp-skip-rationale-list li {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 6px 10px;
  background: rgba(251, 191, 36, 0.04);
  border-left: 2px solid var(--amber, #fbbf24);
  border-radius: 3px;
  font-family: var(--mono); font-size: 11px;
}
.mcp-skip-rationale-list code {
  flex-shrink: 0; font-size: 11px; color: var(--text-bright);
  background: rgba(0,0,0,0.4); padding: 2px 6px; border-radius: 2px;
}
.mcp-skip-reason {
  color: var(--muted); line-height: 1.4;
  flex: 1; min-width: 0;
}

/* Pass 10 (2026-05-28) — Flake badge */
.mcp-flake-badge {
  display: inline-flex; align-items: center;
  background: rgba(251, 191, 36, 0.18);
  border: 1px solid var(--amber, #fbbf24);
  color: var(--amber, #fbbf24);
  font-family: var(--mono); font-size: 9.5px; font-weight: 700;
  padding: 3px 8px; border-radius: 10px;
  letter-spacing: 0.04em;
}

/* Pass 9 (2026-05-28) — Toast stack (multiple re-fires) */
.mcp-toast-stack {
  position: fixed; right: 20px; bottom: 20px; z-index: 100;
  display: flex; flex-direction: column-reverse; gap: 8px;
  max-width: 480px;
  pointer-events: none;
}
.mcp-toast-stack > div { display: contents; }
.mcp-toast {
  display: flex; align-items: center; gap: 12px;
  background: rgba(8, 14, 22, 0.96);
  border: 1px solid var(--cyan);
  border-left-width: 4px;
  padding: 12px 16px; border-radius: 5px;
  font-family: var(--mono); font-size: 12px;
  color: var(--text-bright);
  max-width: 480px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  cursor: pointer;
  pointer-events: auto;
}
.mcp-toast-status {
  color: rgba(var(--cyan-rgb), 0.65);
  font-weight: 600; font-size: 10.5px;
  margin: 0 4px;
}
.mcp-toast--ok  { border-color: var(--green); }
.mcp-toast--ok .mcp-toast-icon  { color: var(--green); }
.mcp-toast--bad { border-color: var(--red); }
.mcp-toast--bad .mcp-toast-icon { color: var(--red); }
.mcp-toast-icon { font-size: 20px; font-weight: 700; }
.mcp-toast-msg  { flex: 1; }
.mcp-toast-msg code { background: rgba(0,0,0,0.5); padding: 1px 5px; border-radius: 2px; }
.mcp-toast-dismiss { color: var(--muted); font-size: 18px; }
.mcp-toast-enter-active, .mcp-toast-leave-active { transition: all 0.3s ease; }
.mcp-toast-enter-from { transform: translateX(20px); opacity: 0; }
.mcp-toast-leave-to   { transform: translateY(8px);  opacity: 0; }

/* pass73.3.19 (2026-05-28) — Cross-target switcher chips */
.mcp-target-chips {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-top: 10px; padding-top: 10px;
  border-top: 1px dashed rgba(var(--cyan-rgb), 0.12);
}
.mcp-target-chips-label {
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.18em;
  color: var(--muted); margin-right: 4px;
}
.mcp-target-chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  color: rgba(255,255,255,0.7);
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 12px;
  text-decoration: none;
  transition: all 0.15s;
}
.mcp-target-chip:hover {
  border-color: var(--cyan); color: var(--cyan);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(var(--cyan-rgb), 0.2);
}
.mcp-target-chip--active {
  background: rgba(var(--cyan-rgb), 0.22);
  border-color: var(--cyan); color: var(--cyan);
  box-shadow: 0 0 12px rgba(var(--cyan-rgb), 0.35);
  cursor: default;
}
.mcp-target-chip-dot {
  width: 8px; height: 8px; border-radius: 50%;
  box-shadow: 0 0 6px currentColor;
}
.mcp-target-chip-dot--cyan    { background: var(--cyan); color: var(--cyan); }
.mcp-target-chip-dot--magenta { background: #f472b6; color: #f472b6; }
.mcp-target-chip-dot--green   { background: var(--green); color: var(--green); }
.mcp-target-chip-dot--amber   { background: var(--amber, #fbbf24); color: var(--amber, #fbbf24); }
.mcp-target-chip-pin { font-size: 8px; opacity: 0.6; }

/* pass73.3.19 (2026-05-28) — Run diff grid */
.mcp-card--diff {
  margin-top: 14px;
  border-top-color: rgba(var(--cyan-rgb), 0.5);
}
.mcp-diff-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px; padding: 12px 14px;
}
.mcp-diff-cell {
  background: rgba(10, 13, 22, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-left-width: 3px;
  border-radius: 4px;
  padding: 10px 12px;
  min-width: 0;
}
.mcp-diff-cell--fail { border-left-color: var(--red); }
.mcp-diff-cell--pass { border-left-color: var(--green); }
.mcp-diff-cell--warn { border-left-color: var(--amber, #fbbf24); }
.mcp-diff-cell--info { border-left-color: var(--cyan); }
.mcp-diff-cell--muted { border-left-color: rgba(107, 119, 133, 0.5); }
.mcp-diff-cell-title {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em;
  color: var(--muted); text-transform: uppercase;
  margin-bottom: 4px;
}
.mcp-diff-cell-count {
  font-family: 'Orbitron', var(--mono);
  font-size: 22px; font-weight: 700;
  color: var(--text-bright);
  margin-bottom: 8px;
}
.mcp-diff-cell-list {
  display: flex; flex-direction: column; gap: 3px;
  max-height: 240px; overflow-y: auto;
  font-size: 10.5px;
}
.mcp-diff-cell-list code {
  display: inline-block; margin-right: 4px;
  background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 100%;
}
.mcp-diff-row {
  display: flex; justify-content: space-between; gap: 8px;
  align-items: center;
}
.mcp-diff-row code { flex: 1 1 auto; min-width: 0; }
.mcp-diff-row .mcp-cell-mono { flex-shrink: 0; color: rgba(255,255,255,0.85); }

/* pass73.3.19 — Re-fire button cyan variant + loading state */
.mcp-btn-cyan {
  background: rgba(var(--cyan-rgb), 0.18);
  border: 1px solid var(--cyan);
  color: var(--cyan);
}
.mcp-btn-cyan:hover {
  background: rgba(var(--cyan-rgb), 0.30);
  box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.4);
}
.mcp-btn-loading {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.5);
  cursor: wait;
}
.mcp-btn-loading::before {
  display: inline-block;
  animation: mcp-spin 0.8s linear infinite;
}
@keyframes mcp-spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }

/* Pass 4 (2026-05-28) — Rich empty states */
.mcp-empty--rich {
  display: flex; align-items: flex-start; justify-content: center;
  gap: 18px; max-width: 600px; margin: 30px auto; text-align: left;
}
.mcp-empty--rich .mcp-empty-icon {
  font-size: 36px; color: rgba(var(--cyan-rgb), 0.65);
  text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4);
  margin-right: 0; line-height: 1;
}
.mcp-empty-body { flex: 1; min-width: 0; }
.mcp-empty-title {
  font-family: var(--mono); font-size: 13px; font-weight: 700;
  color: var(--text-bright); letter-spacing: 0.04em;
  margin-bottom: 6px;
}
.mcp-empty-detail {
  font-family: var(--mono); font-size: 11px; color: var(--muted);
  line-height: 1.55;
}
.mcp-empty-reset {
  display: inline-block; margin-left: 6px;
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  color: var(--cyan); cursor: pointer;
  font-family: var(--mono); font-size: 10.5px;
  padding: 3px 9px; border-radius: 3px;
  transition: all 0.15s;
}
.mcp-empty-reset:hover {
  border-color: var(--cyan);
  background: rgba(var(--cyan-rgb), 0.1);
  transform: translateY(-1px);
}

/* ── Inputs ────────────────────────────────────────────────────────── */
.mcp-input {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 5px 10px;
  font-family: var(--mono); font-size: 11px; color: var(--text-bright);
  margin-left: 8px;
  transition: border-color 0.15s;
}
.mcp-input:focus { outline: none; border-color: var(--cyan); }
select.mcp-input { cursor: pointer; }

/* ── Badges ────────────────────────────────────────────────────────── */
.mcp-badge {
  display: inline-block; padding: 2px 8px; border-radius: 3px;
  font-family: var(--mono); font-size: 9.5px; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase;
  border: 1px solid transparent;
}
.mcp-badge--success { background: rgba(0, 255, 136, 0.1); color: var(--green); border-color: rgba(0, 255, 136, 0.25); }
.mcp-badge--danger  { background: rgba(255, 51, 102, 0.1); color: var(--red);  border-color: rgba(255, 51, 102, 0.3); }
.mcp-badge--info    { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.mcp-badge--muted   { background: rgba(107, 119, 133, 0.12); color: var(--muted); border-color: rgba(107, 119, 133, 0.25); }
.mcp-badge--rule    { background: rgba(165, 180, 252, 0.1); color: #a5b4fc; border-color: rgba(165, 180, 252, 0.3); }
.mcp-badge--warn    { background: rgba(251, 191, 36, 0.1); color: #fbbf24; border-color: rgba(251, 191, 36, 0.3); }
.mcp-badge--suite   { text-transform: none; letter-spacing: 0.04em; }

/* ── Link button ───────────────────────────────────────────────────── */
.mcp-link {
  background: none; border: none; cursor: pointer;
  color: var(--cyan); font-family: var(--mono); font-size: 11px;
  padding: 0;
}
.mcp-link:hover { text-decoration: underline; text-shadow: 0 0 6px rgba(var(--cyan-rgb), 0.4); }

/* ── Footer note ───────────────────────────────────────────────────── */
.mcp-footer-note { margin-top: 32px; }
.mcp-footer-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px;
  padding: 18px 22px;
  background: rgba(10, 13, 22, 0.5); border: 1px solid var(--border);
  border-radius: 5px;
}
.mcp-footer-key {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.2em; color: var(--cyan);
  text-transform: uppercase; margin-bottom: 8px;
}
.mcp-footer-val {
  font-size: 12px; line-height: 1.6; color: var(--muted);
}
.mcp-footer-val strong { color: var(--text-bright); font-weight: 600; }
.mcp-footer-val code {
  background: rgba(var(--cyan-rgb), 0.06); padding: 1px 5px; border-radius: 3px;
  font-family: var(--mono); font-size: 11px; color: var(--cyan);
}

/* ── Spinner ───────────────────────────────────────────────────────── */
.mcp-spinner-inline {
  display: inline-block; width: 10px; height: 10px;
  border: 2px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: var(--cyan); border-radius: 50%;
  animation: mcpSpin 0.8s linear infinite;
}
@keyframes mcpSpin { to { transform: rotate(360deg); } }

/* ── Utility text ──────────────────────────────────────────────────── */
.text-danger { color: var(--red); }

/* ── Responsive ────────────────────────────────────────────────────── */
@media (max-width: 768px) {
  .mcp-hero { padding: 32px 18px 20px; }
  .mcp-h1 { font-size: 26px; }
  .mcp-section { padding: 0 18px; }
  .mcp-tabbar-wrap { padding: 4px 18px 0; }
  .mcp-tabbar-btn { padding: 8px 10px; font-size: 10px; }
  .mcp-tabbar-label { display: none; }
  .mcp-controls { flex-direction: column; align-items: stretch; }
  .mcp-elapsed { margin-left: 0; }
  .mcp-meta-row { gap: 10px; }
  .mcp-meta { font-size: 10px; }
}

/* ═══════════════════════════════════════════════════════════════════════════
 * §pass73.3.18 — Per-tool detail panel + auto-derived category groupings.
 * Visual DNA matches the existing .mcp- family (glass / cyan accent /
 * subtle borders). Slightly elevated padding + animated expand for the
 * detail panel since it carries the most information per click.
 * ═════════════════════════════════════════════════════════════════════════ */

.mcp-btn-tiny {
  padding: 4px 10px;
  font-size: 10.5px;
  letter-spacing: 0.04em;
}

.mcp-cat-section {
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08);
  background: transparent;
}
.mcp-cat-section:last-child { border-bottom: none; }
.mcp-cat-section--expanded {
  background: rgba(var(--cyan-rgb), 0.018);
}

.mcp-cat-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: transparent;
  border: none;
  border-left: 3px solid transparent;
  color: var(--text-bright);
  font-family: var(--font-display, var(--mono, monospace));
  font-size: 12.5px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease, border-left-color 0.15s ease;
}
.mcp-cat-header:hover {
  background: rgba(var(--cyan-rgb), 0.05);
  border-left-color: rgba(var(--cyan-rgb), 0.5);
}
.mcp-cat-header--all-pass {
  border-left-color: rgba(0, 255, 136, 0.35);
}
.mcp-cat-header--has-fails {
  border-left-color: rgba(255, 51, 102, 0.55);
  background: rgba(255, 51, 102, 0.03);
}
.mcp-cat-chevron {
  display: inline-block;
  width: 14px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-size: 12px;
  user-select: none;
}
.mcp-cat-name {
  font-weight: 600;
  letter-spacing: 0.02em;
  min-width: 200px;
  color: var(--text-bright);
}
.mcp-cat-stats {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--muted);
}
.mcp-cat-stat--ok { color: var(--green); font-weight: 600; }
.mcp-cat-stat--fail { color: var(--red); font-weight: 600; }
.mcp-cat-stat--skip { color: var(--muted); }
.mcp-cat-stat--rule { color: #a5b4fc; }
.mcp-cat-stat--meta { color: rgba(var(--cyan-rgb), 0.55); }
.mcp-cat-bar {
  margin-left: auto;
  height: 4px;
  width: 120px;
  background: rgba(var(--cyan-rgb), 0.08);
  border-radius: 2px;
  overflow: hidden;
  display: inline-flex;
}
.mcp-cat-bar-fill {
  display: block;
  flex: 0 0 auto;
  height: 100%;
  transition: width 0.4s ease, background 0.2s ease;
}
/* §MCPTEST30 (V0535): not measured is grey, never red */
.mcp-cat-bar-fill--skip { background: rgba(120, 133, 147, 0.6); }
.mcp-cat-bar-fill--rule { background: rgba(165, 180, 252, 0.55); }
.mcp-cat-bar-fill--green { background: linear-gradient(90deg, #00ff88, #00d2d2); }
.mcp-cat-bar-fill--amber { background: linear-gradient(90deg, #fbbf24, #fb923c); }
.mcp-cat-bar-fill--red { background: linear-gradient(90deg, #ff3366, #fb1854); }

.mcp-table--in-cat {
  margin: 0;
  width: 100%;
}
.mcp-table--in-cat thead tr {
  background: rgba(var(--cyan-rgb), 0.04);
}

.mcp-row-clickable {
  cursor: pointer;
  transition: background 0.12s ease;
}
.mcp-row-clickable:hover {
  background: rgba(var(--cyan-rgb), 0.06) !important;
}
.mcp-row-chevron-cell {
  text-align: center;
  width: 24px;
  user-select: none;
}
.mcp-row-chevron {
  display: inline-block;
  color: rgba(var(--cyan-rgb), 0.55);
  font-size: 11px;
  transition: transform 0.18s ease, color 0.18s ease;
}
.mcp-row--expanded .mcp-row-chevron {
  color: var(--cyan);
}

.mcp-detail-row {
  background: rgba(var(--cyan-rgb), 0.025);
}
.mcp-detail-row > td {
  padding: 0 !important;
}
.mcp-detail-panel {
  padding: 14px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-left: 3px solid rgba(var(--cyan-rgb), 0.4);
  background:
    linear-gradient(180deg, rgba(var(--cyan-rgb), 0.04), transparent 70%),
    rgba(0, 0, 0, 0.15);
}

.mcp-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px 18px;
}
.mcp-detail-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.mcp-detail-key {
  font-size: 9.5px;
  letter-spacing: 0.08em;
  color: rgba(var(--cyan-rgb), 0.65);
  text-transform: uppercase;
}
.mcp-detail-val {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--mono, monospace);
  font-size: 12px;
  color: var(--text-bright);
  word-break: break-all;
}
.mcp-detail-warn {
  display: inline-block;
  margin-left: 4px;
  padding: 1px 6px;
  background: rgba(251, 146, 60, 0.15);
  color: #fb923c;
  border: 1px solid rgba(251, 146, 60, 0.3);
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
}
.mcp-detail-copy {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 0.7);
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.mcp-detail-copy:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: var(--cyan);
  border-color: rgba(var(--cyan-rgb), 0.4);
}

.mcp-detail-block {
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.22);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 4px;
}
.mcp-detail-block-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(var(--cyan-rgb), 0.85);
  margin-bottom: 8px;
}
.mcp-detail-block-icon {
  font-size: 13px;
  color: var(--cyan);
}
.mcp-detail-block-meta {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  font-weight: 400;
}
.mcp-detail-pre {
  margin: 0;
  font-family: var(--mono, monospace);
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-bright);
  max-height: 240px;
  overflow: auto;
}
.mcp-detail-pre--err { color: #ffb3c1; }
.mcp-detail-pre--skip { color: var(--muted); }

.mcp-assertion-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mcp-assertion {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 3px;
  font-size: 11.5px;
  background: rgba(0, 0, 0, 0.18);
}
.mcp-assertion--pass { color: var(--text-bright); border-left: 2px solid var(--green); }
.mcp-assertion--fail { color: #ffb3c1; border-left: 2px solid var(--red); background: rgba(255, 51, 102, 0.06); }
.mcp-assertion--skip { color: var(--muted); border-left: 2px solid rgba(107, 119, 133, 0.4); }
.mcp-assertion--unknown { color: rgba(255, 255, 255, 0.4); border-left: 2px solid rgba(107, 119, 133, 0.2); font-style: italic; }
.mcp-assertion-icon { font-weight: 700; font-size: 12px; min-width: 14px; }
.mcp-assertion-name { font-weight: 500; min-width: 200px; }
.mcp-assertion-detail {
  color: var(--muted);
  font-size: 11px;
  font-family: var(--mono, monospace);
}
.mcp-assertion--pass .mcp-assertion-icon { color: var(--green); }
.mcp-assertion--fail .mcp-assertion-icon { color: var(--red); }
.mcp-assertion--skip .mcp-assertion-icon { color: var(--muted); }

.mcp-detail-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.mcp-detail-actions button[disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}

.mcp-empty {
  padding: 30px 20px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  font-style: italic;
}

/* Slide animation for category expansion */
.mcp-cat-slide-enter-active,
.mcp-cat-slide-leave-active {
  transition: opacity 0.18s ease;
}
.mcp-cat-slide-enter-from,
.mcp-cat-slide-leave-to {
  opacity: 0;
}

@media (max-width: 600px) {
  .mcp-history-table, .mcp-history-table tbody { display: block; }
  .mcp-history-table thead { display: none; }
  .mcp-history-table tr {
    display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; column-gap: 10px; row-gap: 5px;
    grid-template-areas: "cmp id status" ". suite pass" ". started wall" ". act bug";
    padding: 10px 12px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.08);
  }
  .mcp-history-table td { display: block; padding: 0; border: 0; min-width: 0; }
  .mcp-history-table .h-cmp { grid-area: cmp; }
  .mcp-history-table .h-id { grid-area: id; }
  .mcp-history-table .h-id code { word-break: break-all; }
  .mcp-history-table .h-status { grid-area: status; justify-self: end; }
  .mcp-history-table .h-suite { grid-area: suite; }
  .mcp-history-table .h-pass { grid-area: pass; justify-self: end; text-align: right; }
  .mcp-history-table .h-pass .mcp-hist-bar { margin-left: auto; }
  .mcp-history-table .h-started { grid-area: started; }
  .mcp-history-table .h-wall { grid-area: wall; justify-self: end; }
  .mcp-history-table .h-act { grid-area: act; }
  .mcp-history-table .h-bug { grid-area: bug; justify-self: end; }
  .mcp-history-table .h-bug::before { content: attr(data-label) ' '; color: var(--muted); font-size: 10px; }
  /* a console step's name is wider than a phone: its reason went under it, not off the screen */
  .mcp-skip-rationale-list li { flex-direction: column; gap: 4px; }
  .mcp-skip-rationale-list code { flex-shrink: 1; max-width: 100%; overflow-wrap: anywhere; }
}
@media (max-width: 760px) {
  .mcp-cat-name { min-width: auto; }
  .mcp-cat-bar { display: none; }
  .mcp-detail-grid { grid-template-columns: 1fr; }
  .mcp-assertion-name { min-width: auto; }
}

/* ── §MCPTEST30 (V0535): the run's numbers, the folded log, the probe families, not run by why ───────────────── */
.mcp-lead--numbers { margin-top: 10px; color: #c3ccd6; font-size: 0.9rem; }
.mcp-log-line--beat .mcp-log-msg { color: var(--muted); }
.mcp-log-folded {
  margin-left: 8px; padding: 0 6px; border-radius: 3px; font-size: 10px;
  color: #c3ccd6; background: rgba(120, 133, 147, 0.18);
}
.mcp-probe-grid {
  display: grid; gap: 10px; padding: 14px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.mcp-probe {
  display: flex; flex-direction: column; gap: 6px; text-align: left; cursor: pointer;
  padding: 12px 14px; border-radius: 6px; font: inherit; color: inherit;
  background: rgba(var(--cyan-rgb), 0.04); border: 1px solid rgba(var(--cyan-rgb), 0.16);
  transition: border-color 0.15s ease, background 0.15s ease;
}
.mcp-probe:hover, .mcp-probe:focus-visible { border-color: rgba(var(--cyan-rgb), 0.5); background: rgba(var(--cyan-rgb), 0.08); }
.mcp-probe:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
.mcp-probe--bug, .mcp-probe--fail { border-color: rgba(255, 51, 102, 0.45); }
.mcp-probe-head { display: flex; align-items: baseline; gap: 8px; }
.mcp-probe-name { font-weight: 700; color: #e6edf3; }
.mcp-probe-count { margin-left: auto; font-family: var(--mono); font-size: 12px; color: var(--cyan); }
.mcp-probe-proves { font-size: 12.5px; line-height: 1.45; color: #a7b2bf; }
.mcp-probe-tally { display: flex; flex-wrap: wrap; gap: 8px; font-size: 11px; }
.mcp-skip-group + .mcp-skip-group { border-top: 1px solid rgba(var(--cyan-rgb), 0.1); }
.mcp-skip-group-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; padding: 12px 16px 4px; }
.mcp-skip-group-title { font-weight: 700; color: #e6edf3; }
.mcp-skip-group-count {
  font-family: var(--mono); font-size: 11px; padding: 0 6px; border-radius: 3px;
  color: #c3ccd6; background: rgba(120, 133, 147, 0.18);
}
.mcp-skip-group-note { flex-basis: 100%; font-size: 12px; color: #a7b2bf; }
.mcp-sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
</style>
