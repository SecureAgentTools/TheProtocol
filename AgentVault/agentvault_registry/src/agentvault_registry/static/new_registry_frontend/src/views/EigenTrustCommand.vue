<template>
  <div class="et-module">
    <!-- §FEFRAME W3: on a registry where the simulation console is switched off (every node but the simulation's own),
         say so instead of offering controls the server refuses with 503 -->
    <!-- §FESUITE (2026-10-09): until the registry config has answered, the page does not know whether the console is on
         here, and starts nothing (an unread config read as "on", and its pollers asked rails that answer 503) -->
    <ReadFailedNotice v-if="cfgReadFailed" dense data-testid="et-config-unread" :retry="() => loadRegistryConfig(true)"
      text="Whether the simulation console is on here could not be read just now; nothing is started until it is." />
    <div v-else-if="!simulationEnabled" class="et-nosim" data-testid="et-nosim">
      <strong>No simulation runs on this registry.</strong>
      The simulation console is switched off here (ADMIN_SIMULATION_ENABLED), so there is nothing to start, stop or fund.
      Reputation itself is computed on every registry; the public leaderboard shows it.
    </div>

    <!-- Ambient Background -->
    <div class="et-ambient">
      <div class="et-grid"></div>
      <div class="et-scan"></div>
      <div class="et-glow et-glow-1"></div>
      <div class="et-glow et-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="et-hero">
      <div class="et-hero-inner">
        <div class="et-chip">
          <span class="et-chip-dot" :class="!statusKnown ? '' : status.running ? 'dot-green' : 'dot-red'"></span>
          {{ !statusKnown ? '—' : status.running ? t('eigenTrustView.hero.chipActive') : t('eigenTrustView.hero.chipIdle') }}
        </div>
        <h1 class="et-h1">{{ t('eigenTrustView.hero.h1a') }}<span class="et-accent">{{ t('eigenTrustView.hero.h1Accent') }}</span></h1>
        <p class="et-lead">{{ t('eigenTrustView.hero.leadTemplate', { agents: totalAgents, registries: registryCount }) }}</p>
        <div class="et-hero-stats">
          <div class="et-hero-stat">
            <span class="et-hero-stat-val" :class="statusKnown && status.running ? 'green' : ''">{{ !statusKnown ? '—' : status.running ? status.instances + ' instance' + (status.instances > 1 ? 's' : '') : 'Stopped' }}</span>
            <span class="et-hero-stat-label">Simulation</span>
          </div>
          <div class="et-hero-stat">
            <span class="et-hero-stat-val">{{ registries.length ? totalAgents : '—' }}</span>
            <span class="et-hero-stat-label">Agents</span>
          </div>
          <div class="et-hero-stat">
            <span class="et-hero-stat-val" data-testid="et-total-split">{{ registries.length ? totalBalanceCompact : '—' }}</span>
            <span class="et-hero-stat-label">Total</span>
          </div>
          <div class="et-hero-stat">
            <span class="et-hero-stat-val" :class="supplyOk ? 'green' : 'red'">{{ supplyDeltaLabel }}</span>
            <span class="et-hero-stat-label">Supply Delta</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab Bar -->
    <div class="et-tabs">
      <button v-for="tab in tabs" :key="tab.id" class="et-tab" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab Content -->
    <div class="et-content">

      <!-- CONTROL -->
      <div v-if="activeTab === 'control'" class="et-section">

        <!-- Stat Cards -->
        <div class="et-stat-row">
          <div class="et-stat-card">
            <div class="et-stat-label">Simulation</div>
            <div class="et-stat-value" :class="statusKnown && status.running ? 'green' : 'dim'">
              <span class="et-dot" :class="!statusKnown ? '' : status.running ? 'dot-green' : 'dot-red'"></span>
              {{ !statusKnown ? '—' : status.running ? 'ACTIVE' : 'STOPPED' }}
            </div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Total Agents</div>
            <div class="et-stat-value">{{ registries.length ? totalAgents : '—' }}</div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Funded</div>
            <div class="et-stat-value">{{ registries.length ? totalBalanceCompact : '—' }}</div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Supply Delta</div>
            <div class="et-stat-value" :class="supplyOk ? 'green' : 'red'">{{ supplyDeltaLabel }}</div>
          </div>
        </div>

        <!-- Presets -->
        <div class="et-card">
          <div class="et-card-header">
            <span class="et-card-title">Presets</span>
          </div>
          <div class="et-card-body" style="display:flex;gap:10px;flex-wrap:wrap;">
            <button v-for="p in presets" :key="p.label" class="et-preset-btn"
                    :class="{ 'et-preset-stress': p.tone === 'stress' }" @click="applyPreset(p)">
              <span class="et-preset-name">{{ p.label }}</span>
              <span class="et-preset-desc">{{ p.instances }}× · {{ p.pairs }}p · {{ p.interval }}s</span>
            </button>
          </div>
        </div>

        <!-- Config -->
        <div class="et-card">
          <div class="et-card-header">
            <span class="et-card-title">Configuration</span>
          </div>
          <div class="et-card-body">
            <div class="et-config-grid">
              <!-- Path mode (real enum — replaces the dead modern/legacy radio) -->
              <div class="et-config-item">
                <label for="eigentrustcommand-sel-109" class="et-label">Path Mode</label>
                <select id="eigentrustcommand-sel-109" v-model="config.mode" class="et-select">
                  <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
                </select>
                <span class="et-hint">{{ MODE_OPTIONS.find(m => m.value === config.mode)?.hint }}</span>
              </div>
              <!-- Cross backend -->
              <div class="et-config-item">
                <label for="eigentrustcommand-sel-117" class="et-label">Cross Backend</label>
                <select id="eigentrustcommand-sel-117" v-model="config.backend_mode" class="et-select">
                  <option v-for="b in BACKEND_OPTIONS" :key="b.value" :value="b.value">{{ b.label }}</option>
                </select>
                <span class="et-hint">2PC sync · Async SF-4 · Intra forces local</span>
              </div>
              <!-- Pairs — §SIMPAIRS (2026-08-27, his report: "its locked in the frontend").
                   TWO different locks were on this control and only ONE of them was wrong.

                   (1) `max="50"` was arbitrary: the rail accepts `pairs` up to 500
                       (`admin_simulation.py:159`, `Field(15, ge=1, le=500)`). Raised to 500.

                   (2) `:disabled="config.dynamic"` is CORRECT and stays. Under `--dynamic`
                       the sim does `_cycle_pairs = _dyn_n if _dyn else args.pairs`
                       (`sim_eigentrust.py:1920`) — the AIMD controller REPLACES the pair
                       count with its own regulated concurrency, so `pairs` is not merely
                       ignored, it never reaches the loop. Enabling the slider there would
                       hand back a control that changes nothing, which is worse than a
                       disabled one.

                   What was actually missing is that the greyed-out control said only
                   "auto" and never said what to reach for instead. Under dynamic the pair
                   count IS the concurrency range, and those two sliders are right below
                   and are not disabled. -->
              <div class="et-config-item" :class="{ 'et-dim': config.dynamic }">
                <label class="et-label" for="et-cfg-pairs">Pairs / cycle
                  <span class="et-label-val">{{ config.dynamic ? 'auto' : config.pairs }}</span></label>
                <input id="et-cfg-pairs" type="range" v-model.number="config.pairs" min="1" max="500" class="et-slider" :disabled="config.dynamic">
                <span v-if="config.dynamic" class="et-hint" data-testid="et-pairs-dyn-hint">
                  Dynamic regulates this: pairs per cycle = the AIMD concurrency, inside
                  [{{ config.min_concurrency }}..{{ config.max_concurrency }}]. Set the range below,
                  or turn Dynamic off to fix a pair count here.
                </span>
                <span v-else class="et-hint">Fixed workload — {{ config.pairs }} pair(s) every {{ config.cycle_interval }}s. Watch load.</span>
              </div>
              <!-- Concurrency -->
              <div class="et-config-item" :class="{ 'et-dim': config.dynamic }">
                <label class="et-label" for="et-cfg-concurrency">Concurrency <span class="et-label-val">{{ config.dynamic ? 'auto' : config.concurrency }}</span></label>
                <input id="et-cfg-concurrency" type="range" v-model.number="config.concurrency" min="1" max="200" step="1" class="et-slider" :disabled="config.dynamic">
              </div>
              <!-- Interval -->
              <div class="et-config-item">
                <label class="et-label" for="et-cfg-cycle-interval">Interval <span class="et-label-val">{{ config.cycle_interval }}s</span></label>
                <input id="et-cfg-cycle-interval" type="range" v-model.number="config.cycle_interval" min="0" max="60" class="et-slider">
              </div>
              <!-- Cycles -->
              <div class="et-config-item">
                <label class="et-label" for="et-cfg-cycles">Cycles <span class="et-label-val">{{ config.cycles === 0 ? 'Infinite' : config.cycles }}</span></label>
                <input id="et-cfg-cycles" type="range" v-model.number="config.cycles" min="0" max="500" step="10" class="et-slider">
              </div>
              <!-- Instances -->
              <div class="et-config-item">
                <label class="et-label">Instances <span class="et-label-val">{{ config.instances }}</span></label>
                <div class="et-instance-btns">
                  <button v-for="n in [1, 2, 4, 8, 16]" :key="n" class="et-instance-btn"
                          :class="{ active: config.instances === n }" @click="config.instances = n">{{ n }}</button>
                </div>
              </div>
              <!-- Rate cap -->
              <div class="et-config-item" :class="{ 'et-dim': config.dynamic }">
                <label class="et-label" for="et-cfg-rate-tps">Rate cap
                  <span class="et-label-val">{{ config.dynamic ? 'auto' : (config.rate_tps ? config.rate_tps + ' tx/s' : 'off') }}</span>
                </label>
                <input id="et-cfg-rate-tps" type="number" v-model.number="config.rate_tps" placeholder="off" min="0" step="0.5" class="et-input-sm et-input-full" :disabled="config.dynamic">
              </div>
              <!-- Raw mode -->
              <div class="et-config-item et-config-wide">
                <label class="et-checkbox"><input type="checkbox" v-model="config.raw"> Raw mode (skip EigenTrust weighting)</label>
              </div>
              <!-- §2026-07-19 IRONKEY sub-agent frontier -->
              <div class="et-config-item et-config-wide" v-if="config.mode === 'market' || config.mode === 'delegation'">
                <label class="et-checkbox et-checkbox-accent">
                  <input type="checkbox" v-model="config.spawn_subagents" :disabled="config.mode === 'delegation'">
                  <Icon name="mdi:robot" /> Spawn sub-agent clerks &mdash; frame-c parents delegate order execution to birth-token sub-agents (every spawn audit-verified &amp; revocable)
                </label>
              </div>
              <div class="et-config-item et-config-wide" v-if="config.mode === 'delegation' || config.spawn_subagents">
                <span class="et-hint"><Icon name="mdi:shield-key" /> IRONKEY {{ config.mode === 'delegation' ? '— each cycle runs the full authority lifecycle (issue → consume → attenuate → caveat/reuse deny → revoke → periodic breaker) then asserts every action left its security-audit row' : '— a delegation + audit self-check tick folds in every 12 cycles alongside clerk-executed trades' }} &middot; frame-c enforce.</span>
                <label class="et-checkbox" style="margin-top:8px">
                  <input type="checkbox" v-model="config.xreg_delegation">
                  Include cross-registry delegation leg (frame-c → doha) &mdash; optional, off by default
                </label>
              </div>
              <!-- §XREGMODE 2026-08-12 — 100% foreign-federated overlay -->
              <div class="et-config-item et-config-wide" v-if="config.mode === 'market'">
                <label class="et-checkbox et-checkbox-accent">
                  <input type="checkbox" v-model="config.xreg_only">
                  <Icon name="mdi:earth" /> 100% foreign-federated, every clerk order becomes a cross-registry passport buy on a FOREIGN market (market &ne; home; auto-enables sub-agent clerks)
                </label>
              </div>
              <template v-if="config.mode === 'market' && config.xreg_only">
                <div class="et-config-item">
                  <label for="eigentrustcommand-sel-209" class="et-label">Spawn frames</label>
                  <select id="eigentrustcommand-sel-209" v-model="config.spawn_frames" class="et-select">
                    <option value="A,B,C">All 3 mainframes (A+B+C)</option>
                    <option value="C">Frame-C only</option>
                    <option value="A,B">Frame-A + Frame-B</option>
                  </select>
                </div>
                <div class="et-config-item et-config-wide">
                  <span class="et-hint"><Icon name="mdi:earth" /> Clerks on the selected mainframe(s) place 100% of their orders as cross-registry passport buys onto OTHER frames' markets, a saturation test of the federated delegation/spawn path. Buy-only (foreign sells need fill-tracking); &Delta;=0 by construction. A settle-backlog cap is auto-applied so it can't outrun cross-frame event replication.</span>
                </div>
              </template>
              <!-- Dynamic auto-regulation (AIMD) -->
              <div class="et-config-item et-config-wide">
                <label class="et-checkbox et-checkbox-accent">
                  <input type="checkbox" v-model="config.dynamic">
                  <Icon name="mdi:cog" /> Auto-regulate &mdash; hold a settle-time SLO (adjusts concurrency automatically for sustained error-free runs)
                </label>
              </div>
              <template v-if="config.dynamic">
                <div class="et-config-item">
                  <label class="et-label" for="et-cfg-target-settle-ms">Target settle <span class="et-label-val">{{ config.target_settle_ms }}ms</span></label>
                  <input id="et-cfg-target-settle-ms" type="range" v-model.number="config.target_settle_ms" min="500" max="20000" step="500" class="et-slider">
                </div>
                <div class="et-config-item">
                  <label for="eigentrustcommand-sel-233" class="et-label">Target metric</label>
                  <select id="eigentrustcommand-sel-233" v-model="config.target_metric" class="et-select">
                    <option value="p50">p50 (median)</option>
                    <option value="p95">p95</option>
                    <option value="avg">average</option>
                  </select>
                </div>
                <div class="et-config-item">
                  <label class="et-label" for="et-cfg-min-concurrency">Min concurrency <span class="et-label-val">{{ config.min_concurrency }}</span></label>
                  <input id="et-cfg-min-concurrency" type="range" v-model.number="config.min_concurrency" min="1" max="32" class="et-slider">
                </div>
                <div class="et-config-item">
                  <label class="et-label" for="et-cfg-max-concurrency">Max concurrency <span class="et-label-val">{{ config.max_concurrency }}</span></label>
                  <input id="et-cfg-max-concurrency" type="range" v-model.number="config.max_concurrency" min="4" max="200" step="2" class="et-slider">
                </div>
                <div class="et-config-item">
                  <label class="et-label" for="et-cfg-max-backlog">Max settle backlog <span class="et-label-val">{{ config.max_backlog > 0 ? config.max_backlog.toLocaleString(appLocale()) : 'off' }}</span></label>
                  <input id="et-cfg-max-backlog" type="number" v-model.number="config.max_backlog" min="0" step="500" placeholder="0 = unbounded" class="et-input-sm et-input-full">
                </div>
                <div class="et-config-item et-config-wide">
                  <span class="et-hint"><Icon name="mdi:cog" /> Starts gentle, probes concurrency up while settle &lt; target, backs off fast on breach/errors. Pairs / Concurrency / Rate above are auto-managed; Instances &amp; Interval still apply.</span>
                </div>
                <div class="et-config-item et-config-wide" v-if="config.mode === 'market' && config.max_backlog > 0">
                  <span class="et-hint"><Icon name="mdi:tray-full" /> Backlog cap: holds new orders while any market's unsettled-trade backlog exceeds {{ config.max_backlog.toLocaleString(appLocale()) }} (resumes under {{ Math.floor(config.max_backlog * 0.8).toLocaleString(appLocale()) }}) so the sim can't outrun the settlement worker. Market mode.</span>
                </div>
              </template>
              <template v-if="config.mode === 'market'">
                <div class="et-config-item">
                  <label for="eigentrustcommand-sel-261" class="et-label">Currency balance</label>
                  <select id="eigentrustcommand-sel-261" v-model="config.venue_balance" class="et-select">
                    <option value="currency">By currency (A+B = C)</option>
                    <option value="venue">By market (uniform)</option>
                  </select>
                </div>
                <div class="et-config-item">
                  <label class="et-label" for="et-cfg-passport-share">Passport share <span class="et-label-val">{{ Math.round(config.passport_share * 100) }}%</span></label>
                  <input id="et-cfg-passport-share" type="range" v-model.number="config.passport_share" min="0" max="0.95" step="0.01" class="et-slider">
                </div>
                <div class="et-config-item et-config-wide">
                  <span class="et-hint"><Icon name="mdi:cog" /> A/B are AVT markets, C is BVT, an asymmetric 2-vs-1 set. <strong>By currency</strong> gives the single BVT market (C) as much flow as both AVT markets (A+B) combined, so the sim trades ~50/50 by currency instead of skewing AVT. Passport share = fraction of market fires that are cross-frame relays onto C (folded into the balance).</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- ── Demand Director (market mode) — live DB flag, OFF by default ── -->
        <div class="et-card" v-if="config.mode === 'market'">
          <div class="et-card-header">
            <span class="et-card-title"><Icon name="mdi:chart-line" /> Demand Director</span>
            <span class="et-card-sub">per-listing price bias the market-sim reads · live · OFF = neutral</span>
            <button type="button" class="dd-master" :class="{ on: dd.enabled }" role="switch" :aria-checked="dd.enabled"
                    @click="ddToggle()" :title="dd.enabled ? 'Director ON — click for a neutral market' : 'Director OFF — click to enable'">
              <span class="dd-master-dot"></span>{{ dd.enabled ? 'ON' : 'OFF' }}
            </button>
          </div>
          <div class="et-card-body">
            <div class="dd-note">
              <Icon name="mdi:information-outline" />
              <span v-if="!dd.enabled"><b>OFF</b> — the running market-sim trades a neutral two-sided book and ignores these settings.</span>
              <span v-else><b>ON</b> — the running market-sim pushes the tickers below toward their direction (live; next sim cycle, no restart).</span>
            </div>
            <div v-if="dd.loading" class="et-hint">discovering markets…</div>
            <table class="dd-table" v-else-if="dd.symbols.length">
              <thead><tr><th>Ticker</th><th>Market</th><th>Direction</th><th>Strength&nbsp;(0–1)</th></tr></thead>
              <tbody>
                <tr v-for="row in dd.symbols" :key="row.symbol">
                  <td class="dd-sym">${{ row.symbol }}</td>
                  <td class="dd-venue">{{ row.venue }}</td>
                  <td>
                    <div class="dd-dir" role="group" :aria-label="`Direction for ${row.symbol}`">
                      <button type="button" class="dd-seg up" :class="{ active: (dd.cfg[row.symbol]?.dir ?? 0) > 0 }"
                        :aria-pressed="(dd.cfg[row.symbol]?.dir ?? 0) > 0" @click="ddSetDir(row.symbol, 1)"><Icon name="mdi:trending-up" /> Up</button>
                      <button type="button" class="dd-seg flat" :class="{ active: (dd.cfg[row.symbol]?.dir ?? 0) === 0 }"
                        :aria-pressed="(dd.cfg[row.symbol]?.dir ?? 0) === 0" @click="ddSetDir(row.symbol, 0)"><Icon name="mdi:swap-horizontal" /> Flat</button>
                      <button type="button" class="dd-seg down" :class="{ active: (dd.cfg[row.symbol]?.dir ?? 0) < 0 }"
                        :aria-pressed="(dd.cfg[row.symbol]?.dir ?? 0) < 0" @click="ddSetDir(row.symbol, -1)"><Icon name="mdi:chevron-down" /> Down</button>
                    </div>
                  </td>
                  <td>
                    <input class="dd-strength" type="number" step="0.05" min="0" max="1"
                      :aria-label="`Strength for ${row.symbol}`"
                      :value="dd.cfg[row.symbol]?.strength ?? 0.85"
                      @input="ddSetStrength(row.symbol, ($event.target as HTMLInputElement).value)" />
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="et-hint">no markets discovered yet, list/approve a ticker first.</div>
            <div class="dd-actions">
              <button class="et-btn dd-save" :disabled="dd.saving || !dd.symbols.length" @click="ddSave()">
                <Icon name="mdi:check" /> {{ dd.saving ? 'saving…' : 'SAVE / APPLY' }}
              </button>
              <button class="et-btn dd-off" :disabled="dd.saving || !dd.enabled" @click="ddOff()" title="Turn the director OFF (neutral market)">
                <Icon name="mdi:flash-off" /> OFF
              </button>
              <span v-if="dd.savedMsg" class="dd-saved"><Icon name="mdi:check-circle" /> {{ dd.savedMsg }}</span>
            </div>
          </div>
        </div>

        <!-- ── Campaign Engine (market mode) — scripted, timed demand-director scenarios ── -->
        <div class="et-card" v-if="config.mode === 'market'">
          <div class="et-card-header">
            <span class="et-card-title"><Icon name="mdi:chart-candlestick" /> Campaign Engine</span>
            <span class="et-card-sub">scripted, timed market scenarios · drives the demand-director · Δ-safe</span>
            <span class="camp-badge" :class="{ live: camp.status?.active }">
              <span class="camp-badge-dot"></span>{{ camp.status?.active ? 'RUNNING' : 'IDLE' }}
            </span>
          </div>
          <div class="et-card-body">
            <div class="dd-note">
              <Icon name="mdi:information" />
              <span>A campaign steps the demand-director through a built-in scenario's timed phases (e.g. <b>bull run</b>, <b>flash crash</b>). It biases the running market-sim's order flow only — moves no money (Δ-safe).</span>
            </div>

            <!-- Live status (when a campaign is active) -->
            <div v-if="camp.status?.active" class="camp-status">
              <div class="camp-status-head">
                <span class="camp-name"><Icon name="mdi:rocket-launch" /> {{ camp.status.name }}</span>
                <span class="camp-phase">phase {{ (camp.status.phase_idx ?? 0) + 1 }} · <b>{{ camp.status.phase }}</b></span>
              </div>
              <div class="camp-progress" role="progressbar" :aria-valuenow="campPct" aria-valuemin="0" aria-valuemax="100">
                <div class="camp-progress-fill" :style="{ width: campPct + '%' }"></div>
              </div>
              <div class="camp-meta">
                <span><Icon name="mdi:clock-outline" /> {{ fmtUptime(camp.status.elapsed_sec || 0) }} / {{ fmtUptime(camp.status.total_sec || 0) }}</span>
                <span class="camp-dir" :class="campDirClass">
                  <Icon :name="campDirIcon" /> {{ campDirLabel }}<template v-if="camp.status.current_strength != null"> · str {{ Number(camp.status.current_strength).toFixed(2) }}</template>
                </span>
              </div>
            </div>
            <div v-else class="et-hint camp-idle">No campaign running — pick a scenario below and press START.</div>

            <!-- Preset picker + actions -->
            <div class="camp-controls">
              <div class="camp-field">
                <label class="camp-label" for="camp-preset">Scenario</label>
                <select id="camp-preset" class="camp-select" v-model="camp.selected" :disabled="camp.loading || camp.busy">
                  <option v-if="!camp.presets.length" value="">loading…</option>
                  <option v-for="p in camp.presets" :key="p.key" :value="p.key">{{ p.name }}</option>
                </select>
              </div>
              <p v-if="campSelectedPreset" class="camp-preset-desc">
                {{ campSelectedPreset.description }}
                <span class="camp-preset-meta">{{ campSelectedPreset.phases }} phase{{ campSelectedPreset.phases === 1 ? '' : 's' }} · {{ fmtUptime(campSelectedPreset.duration_sec) }}</span>
              </p>
              <label class="et-checkbox camp-restore"><input type="checkbox" v-model="camp.restoreSoftpeg"> Restore soft-peg director on stop</label>
              <div class="dd-actions">
                <button class="et-btn camp-start" :disabled="camp.busy || !camp.selected || camp.status?.active" @click="campStart()">
                  <Icon name="mdi:rocket-launch" /> {{ camp.busy ? 'working…' : 'START CAMPAIGN' }}
                </button>
                <button class="et-btn camp-stop" :disabled="camp.busy || !camp.status?.active" @click="campStop()">
                  <Icon name="mdi:close-circle" /> STOP
                </button>
                <button class="et-btn camp-refresh" :disabled="camp.busy" @click="campRefreshStatus()" title="Refresh status now">
                  <Icon name="mdi:refresh" />
                </button>
                <span v-if="camp.savedMsg" class="dd-saved"><Icon name="mdi:check-circle" /> {{ camp.savedMsg }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="et-action-row">
          <button class="et-btn et-btn-green" @click="startSim" :disabled="!simulationEnabled || !statusKnown || status.running || loading">
            {{ loading ? 'Starting...' : 'START' }}
          </button>
          <button class="et-btn et-btn-red" @click="stopSim" :disabled="!simulationEnabled || !status.running || loading">
            {{ loading ? 'Stopping...' : 'STOP' }}
          </button>
          <div class="et-fund-inline">
            <label class="et-label" for="et-fund-target">Top up to</label>
            <input id="et-fund-target" type="number" v-model.number="fundTarget" class="et-input-sm" min="100" step="1000" />
            <span class="et-label">{{ localCurrency }}</span>
            <button class="et-btn et-btn-gold" @click="fundAll(fundTarget, false)" :disabled="!simulationEnabled || fundLoading">
              {{ fundLoading ? 'Funding...' : 'FUND' }}
            </button>
          </div>
        </div>

        <ReadFailedNotice v-if="simulationEnabled && statusRead === 'unread'" dense :retry="fetchStatus" data-testid="et-status-unread" />
        <!-- Start/stop feedback banner + running hint (AAA+ 2026-06-06) -->
        <div v-if="notice" class="et-notice" :class="notice.type === 'ok' ? 'et-notice-ok' : 'et-notice-err'">
          {{ notice.msg }}
        </div>
        <div v-if="status.running && !notice" class="et-hint et-run-hint">A simulation is already running — press STOP to start a new one.</div>

        <!-- Status Line -->
        <div v-if="status.running" class="et-status-line">
          {{ status.instances }} instance{{ status.instances > 1 ? 's' : '' }} &middot; uptime {{ fmtUptime(status.uptime_seconds) }}
          <span v-if="status.params?.pairs"> &middot; {{ status.params.pairs }} pairs / {{ status.params.cycle_interval }}s</span>
        </div>

        <!-- Live Log -->
        <div v-if="status.running || logLines.length > 0" class="et-log-panel">
          <div class="et-log-header">
            <span class="et-log-title">LIVE LOG</span>
            <div v-if="logInstances.length > 1" class="et-log-legend">
              <span class="et-log-legend-label">{{ logInstances.length }} instances</span>
              <span v-for="n in logInstances" :key="n" class="et-log-legend-chip"
                    :style="{ color: instColor(n), borderColor: instColor(n) }">sim {{ n }}</span>
            </div>
          </div>
          <div class="et-log-body" ref="logBodyRef">
            <div v-for="(entry, idx) in logLines" :key="idx"
                 class="et-log-line" :class="logLineClass(entry.line)">
              <span v-if="logInstances.length > 1" class="et-log-inst"
                    :style="{ color: instColor(entry.instance), borderColor: instColor(entry.instance) }">{{ entry.instance }}</span>
              {{ entry.line }}
            </div>
            <div v-if="logLines.length === 0" class="et-log-empty">Waiting for log output...</div>
          </div>
        </div>
      </div>

      <!-- TELEMETRY -->
      <div v-if="activeTab === 'telemetry'" class="et-section">

        <!-- Headline throughput -->
        <div class="et-stat-row">
          <div class="et-stat-card">
            <div class="et-stat-label">Throughput</div>
            <div class="et-stat-value green">{{ (metrics?.throughput_tps ?? 0).toFixed(1) }}<span class="et-unit">tx/s</span></div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Success Rate</div>
            <div class="et-stat-value" :class="(metrics?.fail_pct ?? 0) > 1 ? 'red' : 'green'">{{ (100 - (metrics?.fail_pct ?? 0)).toFixed(1) }}<span class="et-unit">%</span></div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Active Instances</div>
            <div class="et-stat-value">{{ metrics?.instances ?? 0 }}</div>
          </div>
          <div class="et-stat-card">
            <div class="et-stat-label">Supply Delta</div>
            <div class="et-stat-value" :class="supplyOk ? 'green' : 'red'">{{ supplyDeltaLabel }}</div>
          </div>
          <div v-if="metrics?.dynamic?.enabled" class="et-stat-card">
            <div class="et-stat-label">Auto Concurrency <Icon name="mdi:cog" /></div>
            <div class="et-stat-value cyan">{{ metrics?.dynamic?.concurrency ?? '--' }}</div>
          </div>
          <div v-if="metrics?.dynamic?.enabled" class="et-stat-card">
            <div class="et-stat-label">Settle / Target</div>
            <div class="et-stat-value" :class="(metrics?.dynamic?.settle_ms ?? 0) > (metrics?.dynamic?.target_settle_ms ?? 1) ? 'red' : 'green'">
              {{ metrics?.dynamic?.settle_ms ?? 0 }}<span class="et-unit">/ {{ metrics?.dynamic?.target_settle_ms ?? 0 }}ms</span>
            </div>
          </div>
        </div>

        <div class="et-tele-grid">
          <!-- Per-path latency -->
          <div class="et-card">
            <div class="et-card-header">
              <span class="et-card-title">Latency by Path</span>
              <span class="et-card-sub">p50 · p95 · p99 ms</span>
            </div>
            <div class="et-card-body">
              <div v-for="p in PATHS" :key="p.key" class="et-lat-row">
                <span class="et-lat-label">{{ p.label }}</span>
                <span class="et-lat-count">{{ metrics?.paths?.[p.key] ?? 0 }} tx</span>
                <template v-if="metrics?.latency?.[p.key]">
                  <span class="et-lat-val">{{ metrics.latency[p.key].p50 }}</span>
                  <span class="et-lat-val dim">{{ metrics.latency[p.key].p95 }}</span>
                  <span class="et-lat-val dim">{{ metrics.latency[p.key].p99 }}</span>
                </template>
                <span v-else class="et-lat-val dim et-lat-empty">—</span>
              </div>
              <div v-if="!metrics?.running" class="et-log-empty">No active run — start a simulation to see live latency.</div>
            </div>
          </div>

          <!-- Deadman safety -->
          <div class="et-card">
            <div class="et-card-header">
              <span class="et-card-title">Deadman Safety</span>
              <span class="et-badge" :class="deadman?.armed ? 'badge-green' : 'badge-dim'">{{ deadman?.armed ? 'ARMED' : 'DISARMED' }}</span>
            </div>
            <div class="et-card-body">
              <div v-for="g in deadmanGauges" :key="g.label" class="et-gauge">
                <div class="et-gauge-top">
                  <span class="et-gauge-label">{{ g.label }}</span>
                  <span class="et-gauge-val" :class="{ red: g.danger, warn: g.warn && !g.danger }">{{ g.value }}{{ g.unit }} <span class="et-gauge-max">/ {{ g.max }}{{ g.unit }}{{ g.floor ? ' floor' : '' }}</span></span>
                </div>
                <div class="et-gauge-track"><div class="et-gauge-fill" :class="{ red: g.danger, warn: g.warn && !g.danger }" :style="{ width: g.pct + '%' }"></div></div>
              </div>
              <div v-if="deadman?.last_stop" class="et-laststop" :class="{ 'et-laststop-warn': deadman.last_stop.reason !== 'manual_stop' }">
                <span class="et-laststop-icon">{{ deadman.last_stop.reason === 'manual_stop' ? '■' : '⚠' }}</span>
                <span>Last stop: <strong>{{ deadman.last_stop.reason }}</strong><template v-if="deadman.last_stop.details"> — {{ Array.isArray(deadman.last_stop.details) ? deadman.last_stop.details.join(', ') : deadman.last_stop.details }}</template></span>
                <span class="et-laststop-ago">{{ fmtAgo(deadman.last_stop.ts) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Per-instance grid -->
        <div class="et-card" v-if="metrics?.per_instance?.length">
          <div class="et-card-header"><span class="et-card-title">Per-Instance</span></div>
          <div class="et-card-body">
            <div class="et-inst-grid">
              <div v-for="inst in metrics.per_instance" :key="inst.instance" class="et-inst-card">
                <div class="et-inst-head">#{{ inst.instance }} <span class="et-inst-cyc">cyc {{ inst.cycle }}</span></div>
                <div class="et-inst-tps">{{ inst.tps.toFixed(1) }} <span class="et-unit">tx/s</span></div>
                <div class="et-inst-okfail"><span class="green">{{ inst.ok }} ok</span> · <span :class="inst.fail ? 'red' : 'dim'">{{ inst.fail }} fail</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- AGENTS -->
      <div v-if="activeTab === 'agents'" class="et-section">

        <!-- Action Bar -->
        <div class="et-action-bar">
          <div class="et-fund-inline">
            <label class="et-label" for="et-fund-target-2">Top up to</label>
            <input id="et-fund-target-2" type="number" v-model.number="fundTarget" class="et-input-sm" min="100" step="1000" />
            <span class="et-label">{{ localCurrency }}</span>
          </div>
          <button class="et-btn et-btn-gold" @click="fundAll(fundTarget, false)" :disabled="!simulationEnabled || fundLoading">
            {{ fundLoading ? 'Funding...' : 'Top Up All' }}
          </button>
          <button class="et-btn et-btn-ghost" @click="fundAll(fundTarget, true)" :disabled="!simulationEnabled || fundLoading">Depleted Only</button>
          <button class="et-btn et-btn-cyan" @click="previewFunding(fundTarget)" :disabled="!simulationEnabled || previewLoading">
            {{ previewLoading ? 'Calculating...' : 'Preview' }}
          </button>
          <button class="et-btn et-btn-ghost" @click="fetchAgents" :disabled="agentsLoading">
            <span v-if="agentsLoading" class="et-spin">&#x21BB;</span>
            <span v-else>&#x21BB;</span> Refresh
          </button>
          <div v-if="fundResult" class="et-fund-result">{{ fundResult }}</div>
        </div>

        <!-- Mint + Preview Panel -->
        <div v-if="previewData || mintResult" class="et-preview-panel">
          <div v-if="previewData" class="et-preview-grid">
            <div class="et-preview-item">
              <span class="et-preview-label">Agents to fund</span>
              <span class="et-preview-value">{{ previewData.agents_to_fund }}</span>
            </div>
            <div class="et-preview-item">
              <span class="et-preview-label">Frame A needed</span>
              <span class="et-preview-value">{{ fmtNum(previewData.total_needed_a) }} AVT</span>
            </div>
            <div class="et-preview-item">
              <span class="et-preview-label">Frame A treasury</span>
              <span class="et-preview-value" :class="previewData.deficit_a > 0 ? 'et-deficit' : 'et-surplus'">{{ fmtNum(previewData.treasury_a) }} AVT</span>
            </div>
            <div class="et-preview-item" v-if="previewData.deficit_a > 0">
              <span class="et-preview-label">Frame A deficit</span>
              <span class="et-preview-value et-deficit">{{ fmtNum(previewData.deficit_a) }} AVT — ISSUANCE REQUIRED</span>
            </div>
            <div class="et-preview-item">
              <span class="et-preview-label">Frame B needed</span>
              <span class="et-preview-value">{{ fmtNum(previewData.total_needed_b) }} AVT</span>
            </div>
            <div class="et-preview-item">
              <span class="et-preview-label">Frame B treasury</span>
              <span class="et-preview-value" :class="previewData.deficit_b > 0 ? 'et-deficit' : 'et-surplus'">{{ fmtNum(previewData.treasury_b) }} AVT</span>
            </div>
            <div class="et-preview-item" v-if="previewData.deficit_b > 0">
              <span class="et-preview-label">Frame B deficit</span>
              <span class="et-preview-value et-deficit">{{ fmtNum(previewData.deficit_b) }} AVT — ISSUANCE REQUIRED</span>
            </div>
          </div>
          <div class="et-mint-bar">
            <input type="number" v-model.number="mintAmount" class="et-input-sm" min="1000" step="100000" placeholder="Amount" />
            <button class="et-btn et-btn-mint" @click="doMint('A')" :disabled="mintLoading">
              {{ mintLoading ? 'Issuing...' : 'Issue on Frame A' }}
            </button>
            <button class="et-btn et-btn-mint-b" @click="doMint('B')" :disabled="!simulationEnabled || mintLoading">
              {{ mintLoading ? 'Issuing...' : 'Issue on Frame B' }}
            </button>
            <span v-if="mintResult" class="et-mint-result">{{ mintResult }}</span>
          </div>
        </div>

        <!-- Funding Progress Log -->
        <div v-if="fundLoading || fundLogLines.length > 0" class="et-fund-log">
          <div class="et-fund-log-header">
            <span>Funding Progress</span>
            <span v-if="fundLoading" class="et-spin">&#x21BB;</span>
          </div>
          <div class="et-fund-log-body" ref="fundLogRef">
            <div v-for="(line, i) in fundLogLines" :key="i" class="et-fund-log-line" :class="'et-log-' + line.type">
              {{ line.message }}
            </div>
          </div>
        </div>

        <!-- Summary -->
        <div class="et-summary">
          {{ totalAgents }} agents &middot; {{ registryCount }} registries &middot; {{ totalBalanceLine }} total
        </div>

        <!-- Registry Groups -->
        <div v-if="agentsLoading && registries.length === 0" class="et-empty">Loading agents...</div>
        <div v-else-if="registries.length === 0" class="et-empty">No agent data. Click Refresh.</div>
        <div v-else class="et-registry-list">
          <div v-for="reg in sortedRegistries" :key="reg.name" class="et-card et-registry-card">
            <div class="et-card-header et-registry-header" @click="toggleRegistry(reg.name)">
              <div class="et-registry-info">
                <span class="et-collapse-icon">{{ expandedRegistries.has(reg.name) ? '&#9660;' : '&#9654;' }}</span>
                <span class="et-registry-name">{{ reg.name }}</span>
                <span class="et-registry-frame">(Frame {{ reg.frame }})</span>
                <span class="et-registry-meta">&mdash; {{ reg.agents.length }} agents &mdash; {{ fmtNum(reg.total_balance) }} {{ currencyForItem(reg) }}</span>
              </div>
              <span class="et-funded-badge">{{ reg.funded_count }}/{{ reg.agents.length }} funded</span>
            </div>
            <div v-if="expandedRegistries.has(reg.name)" class="et-card-body et-agent-list">
              <div v-for="agent in reg.agents" :key="agent.did" class="et-agent-row">
                <span class="et-agent-name" :title="agent.did">{{ agent.name || truncDid(agent.did) }}</span>
                <div class="et-balance-track">
                  <div class="et-balance-bar" :class="balanceColor(agent.balance)" :style="{ width: barWidth(agent.balance, reg) + '%' }"></div>
                </div>
                <span class="et-agent-balance" :class="balanceColor(agent.balance)">{{ fmtNum(agent.balance) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- TOPOLOGY -->
      <div v-if="activeTab === 'topology'" class="et-section">
        <div v-if="topoLoading" class="et-empty">Loading topology...</div>
        <EigenTrustTopology v-else :registries="topoRegistries" :edges="topoEdges" />
      </div>

    </div>

    <!-- ETC2 (audit 2026-05-07): mint AVT confirm. Highest-blast-radius op. -->
    <ConfirmActionModal
      :show="showMintConfirm"
      title="// ISSUE AVT UNITS"
      :message="`Issue <strong>${fmtNum(mintAmount)} AVT</strong> on Frame ${mintConfirmFrame}? This is a real treasury issuance — supply invariant audit will reflect the new total.`"
      tone="danger"
      warning="Once issued, units enter circulation. There is no reverse issuance. Verify amount + frame before confirming."
      warning-title="⚠ Unit issuance"
      confirm-text="Issue Units"
      busy-text="Issuing…"
      :busy="mintLoading"
      @close="showMintConfirm = false; mintConfirmFrame = ''"
      @confirm="executeMint"
    />

    <!-- ETC2 (audit 2026-05-07): bulk-fund confirm. -->
    <ConfirmActionModal
      :show="showFundConfirm"
      title="// BULK FUND AGENTS"
      :message="`Fund ${fundConfirmOnlyDepleted ? '<strong>depleted</strong> agents only' : '<strong>all</strong> agents'} to <strong>${fmtNum(fundConfirmTarget)} AVT</strong> from treasury? This will fire one /teg/treasury/fund-agent call per under-target agent.`"
      tone="warn"
      confirm-text="Fund Now"
      busy-text="Funding…"
      :busy="fundLoading"
      @close="showFundConfirm = false"
      @confirm="executeFundAll"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { simulationApi } from '@/services/api/simulation'
import type { SimStatus, RegistryGroup, SimAgent, SimMode, SimBackendMode, SimMetrics, SimDeadmanStatus, SimTargetMetric } from '@/services/api/simulation'
import { apiClient } from '@/services/api/client'
import { useRegistryConfig, loadRegistryConfig, onRegistryConfigRead, type RegistryConfig } from '@/composables/useRegistryConfig'
import { formatPerCurrency } from '@/services/currencySum'
import EigenTrustTopology from '@/components/EigenTrustTopology.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { exchangeAdminService, type DemandDirectorConfig, type CampaignPreset, type CampaignStatus } from '@/services/api/exchangeAdminService'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

// §FEFRAME W3: the same switch routers/admin_simulation.py enforces
const { simulationEnabled, readOk: cfgReadOk, readFailed: cfgReadFailed } = useRegistryConfig()
const { t } = useI18n()
const { localCurrency, currencyForItem } = useCurrency()

// ── Tabs ──────────────────────────────────────────────────────────────────────
const tabs = computed(() => [
  { id: 'control', label: t('eigenTrustView.tabs.control') },
  { id: 'telemetry', label: 'Telemetry' },
  { id: 'agents',  label: t('eigenTrustView.tabs.agents') },
  { id: 'topology', label: t('eigenTrustView.tabs.topology') },
])
const activeTab = ref('control')

// ── State ─────────────────────────────────────────────────────────────────────
const status = reactive<SimStatus>({ running: false, instances: 0, container_ids: [], uptime_seconds: 0, params: {} })
/** §FESUITE V0577: what the status read did. It was swallowed and `running` defaults to false, so a failed read (and a
 *  running simulation that overloads the registry is exactly when one fails) said STOPPED with START pressable, and the
 *  5 s poll, which runs only while a simulation runs, never asked again. Where the console is off, the configuration
 *  answers instead (nothing runs). */
const statusRead = ref<'reading' | 'read' | 'unread'>('reading')
const statusKnown = computed(() => statusRead.value === 'read' || !simulationEnabled.value)
const registries = ref<RegistryGroup[]>([])
const supplyAudit = ref<Record<string, any>>({})
const loading = ref(false)
// Inline start/stop feedback banner (AAA+ 2026-06-06: the Start button used to
// swallow errors / silent 200s → "nothing happens". Now every start reports.)
const notice = ref<{ type: 'ok' | 'err'; msg: string } | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null
function setNotice(type: 'ok' | 'err', msg: string) {
  notice.value = { type, msg }
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = null }, 8000)
}
const fundLoading = ref(false)
const agentsLoading = ref(false)
const fundResult = ref('')
const fundTarget = ref(10000)
const expandedRegistries = ref(new Set<string>())
const previewLoading = ref(false)
const previewData = ref<any>(null)
const mintAmount = ref(10000000)
const mintLoading = ref(false)
const mintResult = ref('')
const fundLogLines = ref<{ type: string, message: string }[]>([])
const fundLogRef = ref<HTMLElement | null>(null)
let fundLogTimer: ReturnType<typeof setInterval> | null = null
const topoRegistries = ref<any[]>([])
const topoEdges = ref<any[]>([])
const topoLoading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Config ────────────────────────────────────────────────────────────────────
const config = reactive<{
  mode: SimMode; pairs: number; cycle_interval: number; cycles: number; raw: boolean
  instances: number; backend_mode: SimBackendMode; concurrency: number; rate_tps: number | null
  dynamic: boolean; target_settle_ms: number; target_metric: SimTargetMetric
  min_concurrency: number; max_concurrency: number; max_backlog: number
  venue_balance: 'currency' | 'venue'; passport_share: number
  spawn_subagents: boolean; xreg_delegation: boolean
  spawn_frames: string; xreg_only: boolean; clerk_anchored: boolean
}>({ mode: 'mixed', pairs: 10, cycle_interval: 5, cycles: 0, raw: false, instances: 4, backend_mode: 'mixed', concurrency: 40, rate_tps: null,
     dynamic: false, target_settle_ms: 5000, target_metric: 'p50', min_concurrency: 2, max_concurrency: 64, max_backlog: 0,
     venue_balance: 'currency', passport_share: 0.18, spawn_subagents: false, xreg_delegation: false,
     spawn_frames: 'A,B,C', xreg_only: false, clerk_anchored: false })

// ── Demand Director (market mode) — single source of truth = the registry DB flag,
//    controlled here in the sim panel; the running market-sim polls it live each cycle
//    (OFF by default → neutral two-sided book; takes effect with no restart). Tickers are
//    discovered network-wide via /exchange/network-listings (every venue, incl. cloud-ops).
interface DdRow { dir: number; strength: number }
const dd = reactive<{
  enabled: boolean; loading: boolean; saving: boolean; savedMsg: string
  symbols: { symbol: string; venue: string }[]; cfg: Record<string, DdRow>
}>({ enabled: false, loading: false, saving: false, savedMsg: '', symbols: [], cfg: {} })
let ddSavedTimer: ReturnType<typeof setTimeout> | null = null

function ddNormDir(d: number): number { return d > 0 ? 1 : d < 0 ? -1 : 0 }
function ddEnsure(sym: string): DdRow { if (!dd.cfg[sym]) dd.cfg[sym] = { dir: 0, strength: 0.85 }; return dd.cfg[sym] }
function ddSetDir(sym: string, d: number) { ddEnsure(sym).dir = ddNormDir(d) }
function ddSetStrength(sym: string, raw: string) { let v = parseFloat(raw); if (!isFinite(v)) v = 0; ddEnsure(sym).strength = Math.min(1, Math.max(0, v)) }
function ddToggle() { dd.enabled = !dd.enabled }

async function ddLoad() {
  dd.loading = true
  try {
    // discover every venue's tickers network-wide (local ∪ federated stock cards)
    const { data } = await apiClient.get('/agora/network-listings')
    const items: any[] = Array.isArray(data) ? data : (data?.listings || [])
    const seen = new Set<string>(); const syms: { symbol: string; venue: string }[] = []
    for (const it of items) {
      const sym = String(it.symbol || '').toUpperCase()
      if (!sym || seen.has(sym)) continue
      seen.add(sym)
      syms.push({ symbol: sym, venue: String(it.origin || it.venue || (it.is_local ? 'local' : 'network')) })
    }
    syms.sort((a, b) => a.symbol.localeCompare(b.symbol))
    dd.symbols = syms
    const cfg = await exchangeAdminService.getDemandDirector()
    dd.enabled = !!cfg.enabled
    for (const [sym, tk] of Object.entries(cfg.tickers || {})) {
      dd.cfg[sym.toUpperCase()] = { dir: ddNormDir((tk as any).dir), strength: Math.min(1, Math.max(0, (tk as any).strength)) }
    }
  } catch { /* not admin / venue absent — leave neutral defaults */ }
  finally { dd.loading = false }
}

async function ddSave() {
  for (const r of dd.symbols) ddEnsure(r.symbol)
  const tickers: Record<string, DdRow> = {}
  for (const [sym, row] of Object.entries(dd.cfg)) tickers[sym] = { dir: ddNormDir(row.dir), strength: row.strength }
  const payload: DemandDirectorConfig = { enabled: dd.enabled, tickers }
  dd.saving = true; dd.savedMsg = ''
  try {
    await exchangeAdminService.setDemandDirector(payload)
    dd.savedMsg = dd.enabled ? 'saved — ON (live next sim cycle)' : 'saved — OFF (neutral market)'
    setNotice('ok', dd.enabled
      ? 'Demand Director ON — the market-sim will push these tickers (live, no restart)'
      : 'Demand Director OFF — neutral two-sided market')
    if (ddSavedTimer) clearTimeout(ddSavedTimer)
    ddSavedTimer = setTimeout(() => { dd.savedMsg = '' }, 4000)
  } catch (e: any) {
    setNotice('err', 'Director save failed: ' + (e?.response?.data?.detail || e?.message || 'error'))
  } finally { dd.saving = false }
}

async function ddOff() { dd.enabled = false; await ddSave() }

// ── §V0132 Campaign Engine (market mode) — scripted, timed demand-director
//    scenarios. Presets + live status are PUBLIC reads; start/stop are admin.
//    The settlement worker steps the active campaign each cycle and writes the
//    same demand_director flag the sim polls — Δ-irrelevant (biases sim only).
const camp = reactive<{
  presets: CampaignPreset[]; selected: string; status: CampaignStatus | null
  loading: boolean; busy: boolean; restoreSoftpeg: boolean; savedMsg: string
}>({ presets: [], selected: '', status: null, loading: false, busy: false, restoreSoftpeg: true, savedMsg: '' })
let campTimer: ReturnType<typeof setInterval> | null = null
let campSavedTimer: ReturnType<typeof setTimeout> | null = null

const campSelectedPreset = computed<CampaignPreset | null>(
  () => camp.presets.find(p => p.key === camp.selected) || null)
const campPct = computed(() => {
  const s = camp.status
  if (!s?.active || !s.total_sec) return 0
  return Math.min(100, Math.max(0, Math.round((Number(s.elapsed_sec || 0) / Number(s.total_sec)) * 100)))
})
const campDir = computed(() => {
  const d = camp.status?.current_dir
  return d == null ? 0 : (d > 0 ? 1 : d < 0 ? -1 : 0)
})
const campDirClass = computed(() => campDir.value > 0 ? 'up' : campDir.value < 0 ? 'down' : 'flat')
const campDirIcon = computed(() => campDir.value > 0 ? 'mdi:trending-up' : campDir.value < 0 ? 'mdi:chevron-down' : 'mdi:swap-horizontal')
const campDirLabel = computed(() => campDir.value > 0 ? 'pushing up' : campDir.value < 0 ? 'pushing down' : 'holding')

async function campLoadPresets() {
  camp.loading = true
  try {
    const { presets } = await exchangeAdminService.getCampaignPresets()
    camp.presets = Array.isArray(presets) ? presets : []
    if (!camp.selected && camp.presets.length) {
      // default to the gentlest scenario when present (least disruptive)
      camp.selected = (camp.presets.find(p => p.key === 'soft_peg') || camp.presets[0]).key
    }
  } catch { /* venue absent / not admin — leave empty */ }
  finally { camp.loading = false }
}

async function campRefreshStatus() {
  try { camp.status = await exchangeAdminService.getCampaignStatus() }
  catch { camp.status = null }
}

function campArmSavedClear() {
  if (campSavedTimer) clearTimeout(campSavedTimer)
  campSavedTimer = setTimeout(() => { camp.savedMsg = '' }, 5000)
}

async function campStart() {
  if (!camp.selected) return
  camp.busy = true; camp.savedMsg = ''
  try {
    const res = await exchangeAdminService.startCampaign(camp.selected)
    camp.savedMsg = `started — ${res.name} (${res.phases} phases)`
    setNotice('ok', `Campaign "${res.name}" started — the market-sim follows its phases live (Δ-safe).`)
    await campRefreshStatus()
    campArmSavedClear()
  } catch (e: any) {
    setNotice('err', 'Campaign start failed: ' + (e?.response?.data?.detail || e?.message || 'error'))
  } finally { camp.busy = false }
}

async function campStop() {
  camp.busy = true; camp.savedMsg = ''
  try {
    const res = await exchangeAdminService.stopCampaign(camp.restoreSoftpeg)
    camp.savedMsg = res.restored_softpeg ? 'stopped — soft-peg restored' : 'stopped'
    setNotice('ok', 'Campaign stopped' + (res.restored_softpeg ? ' — uniform soft-peg director restored.' : '.'))
    await campRefreshStatus()
    campArmSavedClear()
  } catch (e: any) {
    setNotice('err', 'Campaign stop failed: ' + (e?.response?.data?.detail || e?.message || 'error'))
  } finally { camp.busy = false }
}

function campStartPolling() { void campRefreshStatus(); if (campTimer) return; campTimer = setInterval(() => { void campRefreshStatus() }, 3000) }
function campStopPolling() { if (campTimer) { clearInterval(campTimer); campTimer = null } }

// Human labels for the real path/backend enums (replaces the dead modern/legacy radio)
const MODE_OPTIONS: { value: SimMode; label: string; hint: string }[] = [
  { value: 'mixed', label: 'Mixed', hint: '60/25/15 local · cross-reg · cross-frame' },
  { value: 'local-only', label: 'Local', hint: 'same-registry transfers only' },
  { value: 'cross-only', label: 'Cross-Reg', hint: 'cross-registry, same frame' },
  { value: 'cross-frame-only', label: 'Cross-Frame', hint: 'A↔B sovereign transfers' },
  { value: 'fx', label: 'FX (cross-currency)', hint: 'op↔op cross-currency FX legs between two frames' },
  { value: 'market', label: 'AGORA Market', hint: 'market order-flow · passport relays A↔C only · Frame-B local-only (no FX)' },
  { value: 'delegation', label: 'IRONKEY Delegation ✦', hint: 'sub-agent authority lifecycle + audit self-check · frame-c enforce' },
]
const BACKEND_OPTIONS: { value: SimBackendMode; label: string }[] = [
  { value: 'mixed', label: 'Mixed' },
  { value: 'async', label: 'Async (SF-4)' },
  { value: '2pc', label: '2PC' },
  { value: 'intra', label: 'Intra' },
]
const logLines = ref<{ instance: number, line: string }[]>([])
const logInstances = ref<number[]>([])
const logBodyRef = ref<HTMLElement | null>(null)

// Per-instance categorical colors so a multi-instance run is readable at a glance.
// Instance 1 = the theme primary (stays theme-reactive); the rest are a fixed
// distinguishing palette (categorical, not the primary accent — design-language safe).
const INST_PALETTE = ['#a78bfa', '#f59e0b', '#34d399', '#38bdf8', '#f472b6', '#facc15', '#fb7185']
function instColor(n: number): string {
  if (n <= 1) return 'var(--et-cyan)'
  return INST_PALETTE[(n - 2) % INST_PALETTE.length]
}
let logTimer: ReturnType<typeof setInterval> | null = null

interface SimPreset {
  label: string; mode: SimMode; pairs: number; interval: number; cycles: number
  instances: number; concurrency: number; backend_mode: SimBackendMode; tone?: string
  dynamic?: boolean; target_settle_ms?: number; max_concurrency?: number; max_backlog?: number
  venue_balance?: 'currency' | 'venue'; passport_share?: number
  spawn_subagents?: boolean; xreg_delegation?: boolean
}
const presets: SimPreset[] = [
  { label: 'Warm Up',      mode: 'mixed',      pairs: 5,  interval: 10, cycles: 50, instances: 1,  concurrency: 20,  backend_mode: 'mixed' },
  { label: 'Steady',       mode: 'mixed',      pairs: 20, interval: 3,  cycles: 0,  instances: 4,  concurrency: 40,  backend_mode: 'mixed' },
  { label: 'Endurance',    mode: 'mixed',      pairs: 15, interval: 3,  cycles: 0,  instances: 4,  concurrency: 40,  backend_mode: 'mixed' },
  { label: 'Full Blast',   mode: 'mixed',      pairs: 50, interval: 0,  cycles: 0,  instances: 16, concurrency: 100, backend_mode: 'mixed', tone: 'stress' },
  { label: 'Local Stress', mode: 'local-only', pairs: 50, interval: 0,  cycles: 0,  instances: 16, concurrency: 100, backend_mode: 'intra', tone: 'stress' },
  { label: 'FX Slow',      mode: 'fx',         pairs: 5,  interval: 10, cycles: 60, instances: 1,  concurrency: 4,   backend_mode: 'async' },
  { label: 'Auto ≤5s ⚙',   mode: 'fx',         pairs: 8,  interval: 1,  cycles: 0,  instances: 1,  concurrency: 8,   backend_mode: 'async', dynamic: true, target_settle_ms: 5000, tone: 'auto' },
  // §V0064 AGORA — dynamic venue order-flow at GENTLE concurrency so trade
  // creation can't outpace settlement (the escrow row serialises every money
  // leg). 2750ms settle target per sim doctrine (5000 = the crash peg). Frame-B
  // trades local-only; passport relays ride the A↔C FX rail.
  { label: 'AGORA Market ⚙', mode: 'market', pairs: 10, interval: 4, cycles: 0, instances: 1, concurrency: 8, backend_mode: 'mixed', dynamic: true, target_settle_ms: 2750, max_concurrency: 10, max_backlog: 2000, venue_balance: 'currency', passport_share: 0.18, tone: 'auto' },
  // §2026-07-19 IRONKEY ✦ — the sub-agent frontier. "Desk": a live AGORA market where frame-c
  // parents spawn execution-clerk sub-agents that trade under capability tokens, punctuated by a
  // full delegation lifecycle + audit self-check every N cycles. "Delegation": the pure conformance
  // battery. Both run gently (frame-c enforce is worker-sensitive); xreg leg stays OFF by default.
  { label: 'AGORA + Sub-Agents ✦', mode: 'market', pairs: 10, interval: 5, cycles: 0, instances: 1, concurrency: 10, backend_mode: 'mixed', dynamic: true, target_settle_ms: 2750, max_concurrency: 12, max_backlog: 2000, venue_balance: 'currency', passport_share: 0.18, spawn_subagents: true, tone: 'auto' },
  { label: 'IRONKEY Delegation ✦', mode: 'delegation', pairs: 1, interval: 5, cycles: 0, instances: 1, concurrency: 4, backend_mode: 'mixed', tone: 'auto' },
]

function applyPreset(p: SimPreset) {
  config.mode = p.mode
  config.pairs = p.pairs
  config.cycle_interval = p.interval
  config.cycles = p.cycles
  config.instances = p.instances
  config.concurrency = p.concurrency
  config.backend_mode = p.backend_mode
  config.dynamic = p.dynamic ?? false
  if (p.target_settle_ms) config.target_settle_ms = p.target_settle_ms
  // gentle ceiling for the venue (settlement-capacity bound); presets that
  // don't set it leave the user's current max untouched.
  if (p.max_concurrency) config.max_concurrency = p.max_concurrency
  // settlement-backlog cap (0=off): presets that don't set it leave the user's value
  if (p.max_backlog !== undefined) config.max_backlog = p.max_backlog
  if (p.venue_balance) config.venue_balance = p.venue_balance
  if (p.passport_share !== undefined) config.passport_share = p.passport_share
  // IRONKEY: a preset that doesn't opt in explicitly turns the sub-agent options OFF (so switching
  // from a ✦ preset back to a plain one clears them). xreg stays a deliberate, separate opt-in.
  config.spawn_subagents = p.spawn_subagents ?? false
  config.xreg_delegation = p.xreg_delegation ?? false
}

// ── Computed ──────────────────────────────────────────────────────────────────
const totalAgents = computed(() => registries.value.reduce((s, r) => s + r.agents.length, 0))
// §SUMSPLIT (§ORGMARKET W) — §17.3 refused to add AVT + BVT into one number by
// FILTERING to the local currency, which was honest about the unit and silent
// about the rest: foreign-currency registries simply vanished from "Total".
// The split says everything: per-currency lines, local frame first, ONE shared
// formatter (services/currencySum.ts). A single-currency fleet renders exactly
// the single line it always had.
const perCurrencyEntries = computed(() =>
  registries.value.map(r => ({ amount: r.total_balance, currency: currencyForItem(r) })))
const totalBalanceLine = computed(() =>
  formatPerCurrency(perCurrencyEntries.value, { localCurrency: localCurrency.value, fmt: fmtNum }))
const totalBalanceCompact = computed(() =>
  formatPerCurrency(perCurrencyEntries.value, { localCurrency: localCurrency.value, fmt: fmtCompact }))
const registryCount = computed(() => registries.value.length)

const sortedRegistries = computed(() =>
  [...registries.value].sort((a, b) => b.total_balance - a.total_balance)
)

const supplyOk = computed(() => {
  const a = supplyAudit.value
  if (!a || (!a.A && !a.B)) return true
  return (a.A?.status === 'OK' || !a.A) && (a.B?.status === 'OK' || !a.B)
})

const supplyDeltaLabel = computed(() => {
  const a = supplyAudit.value
  if (!a || (!a.A && !a.B)) return '--'
  const dA = a.A?.delta ?? 0
  const dB = a.B?.delta ?? 0
  const total = Math.abs(dA) + Math.abs(dB)
  return total === 0 ? '0.0' : total.toFixed(2)
})

// ── Fetch ─────────────────────────────────────────────────────────────────────
async function fetchStatus() {
  try {
    const s = await simulationApi.getStatus()
    Object.assign(status, s)
    statusRead.value = 'read'
  } catch {
    // a failed refresh keeps what was shown; a failed first read says so, and START waits for an answer
    if (statusRead.value !== 'read') statusRead.value = 'unread'
  }
}

async function fetchAgents() {
  agentsLoading.value = true
  try {
    const data = await simulationApi.getAgents()
    registries.value = data.registries || []
  } catch { /* agents unavailable */ }
  finally { agentsLoading.value = false }
}

async function fetchLogs() {
  if (!status.running) return
  try {
    const data = await simulationApi.getLogs(50)
    // Filter out Docker-API plumbing noise (not sim output)
    logLines.value = (data.lines || []).filter(l => !l.line.includes('No such container'))
    // Track which instances are present so the log clearly shows ALL of them, not one
    // (the backend now interleaves every running instance chronologically).
    logInstances.value = data.instances && data.instances.length
      ? data.instances
      : [...new Set(logLines.value.map(l => l.instance))].sort((a, b) => a - b)
    nextTick(() => {
      if (logBodyRef.value) logBodyRef.value.scrollTop = logBodyRef.value.scrollHeight
    })
  } catch { /* logs unavailable */ }
}

function logLineClass(line: string): string {
  if (line.includes('CYCLE')) return 'log-cycle'
  if (line.includes('FAIL')) return 'log-fail'
  return 'log-tx'
}

function startLogPolling() {
  stopLogPolling()
  fetchLogs()
  // ETC3 (audit 2026-05-07): visibility guard. logTimer fires every 2s — without
  // the guard, hidden tabs hammer /admin/simulation/logs at 30 rps/min for nothing.
  logTimer = setInterval(() => {
    if (document.visibilityState !== 'hidden') fetchLogs()
  }, 2000)
}

function stopLogPolling() {
  if (logTimer) { clearInterval(logTimer); logTimer = null }
}

async function fetchSupplyAudit() {
  try {
    supplyAudit.value = await simulationApi.getSupplyAudit()
  } catch { /* audit unavailable */ }
}

async function fetchTopology() {
  topoLoading.value = true
  try {
    const data = await simulationApi.getTopology()
    topoRegistries.value = data.registries || []
    topoEdges.value = data.edges || []
  } catch { /* topology unavailable */ }
  finally { topoLoading.value = false }
}

// ── Telemetry (2026-05-31) ──────────────────────────────────────────────────
const metrics = ref<SimMetrics | null>(null)
const deadman = ref<SimDeadmanStatus | null>(null)
let telemetryTimer: ReturnType<typeof setInterval> | null = null

async function fetchTelemetry() {
  const [m, d] = await Promise.all([
    simulationApi.getMetrics().catch(() => null),
    simulationApi.getDeadmanStatus().catch(() => null),
  ])
  if (m) metrics.value = m
  if (d) deadman.value = d
}

function startTelemetryPolling() {
  stopTelemetryPolling()
  fetchTelemetry()
  fetchSupplyAudit()
  // 3s cadence, visibility-guarded like the other pollers.
  telemetryTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    fetchTelemetry()
    fetchSupplyAudit()
  }, 3000)
}

function stopTelemetryPolling() {
  if (telemetryTimer) { clearInterval(telemetryTimer); telemetryTimer = null }
}

const PATHS = [
  { key: 'local', label: 'Local' },
  { key: 'cross_reg', label: 'Cross-Reg' },
  { key: 'cross_frame', label: 'Cross-Frame' },
] as const

// Deadman safety gauges. Load/Swap are ceilings (bar fills toward red as they
// rise); Mem Avail is a floor (bar drains toward red as headroom shrinks).
const deadmanGauges = computed(() => {
  const d = deadman.value
  if (!d) return [] as { label: string; value: number; max: number; unit: string; pct: number; danger: boolean; warn: boolean; floor: boolean }[]
  const s = d.last_snapshot || {}
  const th = d.thresholds
  const clamp = (n: number) => Math.max(2, Math.min(100, n))
  const load = +(s.load1m ?? 0).toFixed(1)
  const swap = +(s.swap_used_gb ?? 0).toFixed(1)
  const avail = +(s.available_gb ?? 99).toFixed(1)
  const fl = th.mem_available_gb_min
  return [
    { label: 'Load 1m', value: load, max: th.load1m_max, unit: '', pct: clamp(load / th.load1m_max * 100), danger: load > th.load1m_max, warn: load > th.load1m_max * 0.75, floor: false },
    { label: 'Swap Used', value: swap, max: th.swap_used_gb_max, unit: 'GB', pct: clamp(swap / th.swap_used_gb_max * 100), danger: swap > th.swap_used_gb_max, warn: swap > th.swap_used_gb_max * 0.75, floor: false },
    { label: 'Mem Avail', value: avail, max: fl, unit: 'GB', pct: clamp(avail / (fl * 3) * 100), danger: avail < fl, warn: avail < fl * 1.5, floor: true },
  ]
})

function fmtAgo(ts?: string): string {
  if (!ts) return '--'
  const d = (Date.now() - new Date(ts).getTime()) / 1000
  if (d < 60) return Math.floor(d) + 's ago'
  if (d < 3600) return Math.floor(d / 60) + 'm ago'
  return Math.floor(d / 3600) + 'h ago'
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function startSim() {
  loading.value = true
  notice.value = null
  try {
    const res = await simulationApi.start({
      mode: config.mode,
      pairs: config.pairs,
      cycle_interval: config.cycle_interval,
      cycles: config.cycles,
      raw: config.raw,
      instances: config.instances,
      concurrency: config.concurrency,
      backend_mode: config.backend_mode,
      rate_tps: config.rate_tps,
      dynamic: config.dynamic,
      target_settle_ms: config.target_settle_ms,
      target_metric: config.target_metric,
      min_concurrency: config.min_concurrency,
      max_concurrency: config.max_concurrency,
      max_backlog: config.max_backlog,
      venue_balance: config.venue_balance,
      passport_share: config.passport_share,
      spawn_subagents: config.spawn_subagents || (config.mode === 'market' && config.xreg_only),
      xreg_delegation: config.xreg_delegation,
      // §XREGMODE — 100% foreign-federated overlay (only applied in market mode; the server also
      // forces mode=market + spawn_subagents and a settle-backlog default when xreg_only is set).
      spawn_frames: config.spawn_frames,
      xreg_only: config.mode === 'market' && config.xreg_only,
      clerk_anchored: config.clerk_anchored,
    })
    const n = Number(res?.instances ?? 0)
    if (n > 0) {
      const dyn = config.dynamic ? ` · dynamic ≤ ${config.target_settle_ms}ms` : ''
      setNotice('ok', `Started ${n} instance${n > 1 ? 's' : ''} · ${config.mode}${dyn}`)
    } else {
      // Backend now 500s on 0 instances, but guard the legacy fake-200 too.
      setNotice('err', 'Start launched 0 instances — nothing started. Check the Live Log / Docker.')
    }
    await fetchStatus()
    startLogPolling()
    startTelemetryPolling()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'request failed'
    setNotice('err', `Start failed: ${msg}`)
  } finally { loading.value = false }
}

async function stopSim() {
  loading.value = true
  try {
    await simulationApi.stop()
    setNotice('ok', 'Simulation stopped.')
    await fetchStatus()
    stopLogPolling()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'request failed'
    setNotice('err', `Stop failed: ${msg}`)
  } finally { loading.value = false }
}

async function previewFunding(target: number) {
  previewLoading.value = true
  previewData.value = null
  try {
    const res = await simulationApi.fundingPreview({ target_balance: target, only_depleted: false, depleted_threshold: 100 })
    previewData.value = res
  } catch { previewData.value = { message: 'Preview failed' } }
  finally { previewLoading.value = false }
}

// ETC1+ETC2 (audit 2026-05-07): mint flow rebuilt.
//
// Original bugs:
//   (1) Frame B branch used raw fetch() with localStorage.getItem('token') —
//       wrong key. Canonical is 'sovereign_auth_token' (config/index.ts).
//       Result: Authorization: 'Bearer ' (empty), 401, "Mint failed" with no
//       diagnostic. Frame B mint was effectively broken from this UI.
//   (2) No confirm guard. Minting is the highest-blast-radius operation in
//       the entire app — supply invariant breach if accidental.
//
// Fix:
//   - Replace raw fetch with apiClient.post — it auto-injects the canonical
//     token via the request interceptor.
//   - Gate the click via ConfirmActionModal danger-tone with the amount inline.
const showMintConfirm = ref(false)
const mintConfirmFrame = ref<string>('')

function doMint(frame: string) {
  if (mintLoading.value) return
  mintConfirmFrame.value = frame
  showMintConfirm.value = true
}

async function executeMint() {
  const frame = mintConfirmFrame.value
  if (!frame) return
  mintLoading.value = true
  mintResult.value = ''
  showMintConfirm.value = false
  try {
    if (frame === 'B') {
      // apiClient adds /api/v1 prefix + Authorization: Bearer <sovereign_auth_token>
      const res = await apiClient.post('/admin/simulation/mint-frame-b', {
        amount: String(mintAmount.value),
      })
      mintResult.value = `Issued ${fmtNum(mintAmount.value)} AVT on Frame B`
    } else {
      await simulationApi.mintTokens(String(mintAmount.value))
      mintResult.value = `Issued ${fmtNum(mintAmount.value)} AVT on Frame A`
    }
    await previewFunding(fundTarget.value)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    mintResult.value = err?.response?.data?.detail || 'Issuance failed'
  } finally {
    mintLoading.value = false
    mintConfirmFrame.value = ''
    setTimeout(() => { mintResult.value = '' }, 8000)
  }
}

function startFundLogPolling() {
  fundLogLines.value = []
  // ETC3: fundLogTimer fires every 2s during a funding run — pause on hidden tab.
  fundLogTimer = setInterval(async () => {
    if (document.visibilityState === 'hidden') return
    try {
      const res = await simulationApi.getFundStatus()
      if (res.lines && res.lines.length > fundLogLines.value.length) {
        fundLogLines.value = res.lines
        nextTick(() => { if (fundLogRef.value) fundLogRef.value.scrollTop = fundLogRef.value.scrollHeight })
      }
    } catch {}
  }, 2000)
}

function stopFundLogPolling() {
  if (fundLogTimer) { clearInterval(fundLogTimer); fundLogTimer = null }
}

// ETC2 (audit 2026-05-07): confirm guard on bulk funding.
// fundAll moves AVT from treasury to every sim agent — high-blast-radius.
// Previously a single click on "Fund All" or "Fund Depleted" fired immediately.
const showFundConfirm = ref(false)
const fundConfirmTarget = ref(0)
const fundConfirmOnlyDepleted = ref(false)

function fundAll(target: number, onlyDepleted: boolean) {
  if (fundLoading.value) return
  fundConfirmTarget.value = target
  fundConfirmOnlyDepleted.value = onlyDepleted
  showFundConfirm.value = true
}

async function executeFundAll() {
  const target = fundConfirmTarget.value
  const onlyDepleted = fundConfirmOnlyDepleted.value
  fundLoading.value = true
  fundResult.value = ''
  fundLogLines.value = []
  showFundConfirm.value = false
  startFundLogPolling()
  try {
    const res = await simulationApi.fundAgents({
      target_balance: target,
      only_depleted: onlyDepleted,
      depleted_threshold: 100,
    })
    fundResult.value = res.message || `Funded ${res.funded_count ?? '?'} agents`
    await fetchAgents()
  } catch {
    fundResult.value = 'Funding failed — check progress log for details'
  } finally {
    fundLoading.value = false
    stopFundLogPolling()
    try { const res = await simulationApi.getFundStatus(); fundLogLines.value = res.lines } catch {}
    setTimeout(() => { fundResult.value = '' }, 10000)
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtNum(n: number): string {
  if (n == null) return '0'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
}

function fmtCompact(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return fmtNum(n)
}

function fmtUptime(s: number): string {
  if (!s) return '0s'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

function truncDid(did: string): string {
  if (!did) return '?'
  return did.length > 28 ? did.slice(0, 20) + '...' + did.slice(-6) : did
}

function balanceColor(bal: number): string {
  if (bal >= 1000) return 'bar-green'
  if (bal >= 100) return 'bar-yellow'
  return 'bar-red'
}

function barWidth(bal: number, reg: RegistryGroup): string {
  const max = Math.max(...reg.agents.map(a => a.balance), 1)
  return Math.max((bal / max) * 100, 1).toFixed(1)
}

function toggleRegistry(name: string) {
  const s = new Set(expandedRegistries.value)
  if (s.has(name)) s.delete(name)
  else s.add(name)
  expandedRegistries.value = s
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling() {
  stopPolling()
  // ETC3: pollTimer fires every 5s — pause on hidden tab.
  pollTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    if (status.running) fetchStatus()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(() => status.running, (running) => {
  if (running) { startPolling(); startLogPolling() }
  else { stopLogPolling() }
})

// ── Lifecycle ─────────────────────────────────────────────────────────────────
// §MCPTEST30 V0562 (agentvault2-45): onMounted awaits before it starts its pollers, and a page left during an await has
// already run onUnmounted, so a poller started afterwards (the 3 s campaign read, the telemetry, the status poll) was
// never cleared. Nothing that starts a timer runs once the page is gone.
let alive = true
let started = false
let offConfigRead: (() => void) | null = null
onMounted(async () => {
  // §MCPTEST30 V0562 (45's first admin sweep of sbx-beta): where the simulation console is off, every
  // /admin/simulation read answers 503, and the 3-second telemetry poll raised a "Server Error" toast for each one.
  // Ask the registry first; the banner above says why the panels stay empty. The AGORA reads are not the console's.
  const cfg = await loadRegistryConfig()
  if (!alive) return
  // §FESUITE (2026-10-09): a config that did not answer is not "on". It read as on (only an explicit false is off),
  // and a page opened while the registry could not answer polled /admin/simulation rails that answer 503 where the
  // console is off (sweeps/recovery on V0587). Start once a read answers; useRegistryConfig reads again on its own.
  if (!cfgReadOk.value) {
    offConfigRead = onRegistryConfigRead((c) => { offConfigRead?.(); offConfigRead = null; void startConsole(c) })
    return
  }
  await startConsole(cfg)
})

async function startConsole(cfg: RegistryConfig): Promise<void> {
  if (started || !alive) return
  started = true
  if (cfg.simulation_enabled === false) {
    void ddLoad(); void campLoadPresets(); campStartPolling()
    return
  }
  // Telemetry/safety must NOT wait on the (sometimes slow) agents host-script +
  // federation topology fetches — start it immediately so the Telemetry tab
  // paints live data on first render.
  startTelemetryPolling()
  await fetchStatus()
  if (!alive) return
  if (status.running) startPolling()
  // heavier fetches fire without blocking
  fetchAgents(); fetchTopology()
  void ddLoad()                 // §2026-06-18 demand-director panel — discover venues + current cfg
  void campLoadPresets()        // §V0132 campaign engine — scenario library
  campStartPolling()            // §V0132 campaign engine — live status (3s public read)
}

onUnmounted(() => { alive = false; offConfigRead?.(); offConfigRead = null; stopPolling(); stopLogPolling(); stopTelemetryPolling(); campStopPolling(); stopFundLogPolling(); if (ddSavedTimer) clearTimeout(ddSavedTimer); if (campSavedTimer) clearTimeout(campSavedTimer) })
</script>

<style scoped>
.et-nosim { margin: 12px 0; padding: 12px 14px; border: 1px dashed rgba(var(--nc-primary-rgb), .3); border-radius: 10px; font-size: .82rem; color: rgba(230, 249, 255, .75); line-height: 1.5; }
/* ── Design Tokens ─────────────────────────────────────────────────────────── */
.et-module {
  --et-bg: #060b14;
  --et-surface: rgba(0, 20, 20, 0.6);
  --et-surface-2: rgba(0, 28, 28, 0.5);
  --et-border: rgba(var(--nc-primary-rgb), 0.15);
  --et-border-hover: rgba(var(--nc-primary-rgb), 0.3);
  --et-cyan: var(--nc-primary);
  /* Neutral house text (design language: bright #e8eaed, muted slate) — de-greened
     from the old matrix tint so the cyan/red theme accent carries the colour. */
  --et-text: #e8eaed;
  --et-text-dim: #8a97a6;
  --et-text-muted: #5c6775;
  /* Semantic colors are FIXED per the design language (do NOT theme):
     success #10b981 · warning/amber #f59e0b · danger/red #ef4444. */
  --et-green: #10b981;
  --et-red: #ef4444;
  --et-yellow: #f59e0b;
  --et-gold: #d4a017;
  --et-mono: 'IBM Plex Mono', 'Courier New', monospace;
  --et-radius: 6px;
  --et-radius-lg: 10px;

  min-height: 100vh;
  color: var(--et-text);
  position: relative;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ── Ambient ───────────────────────────────────────────────────────────────── */
.et-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.et-grid {
  position: absolute; inset: 0;
  background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}
.et-scan {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 0%, rgba(var(--nc-primary-rgb),0.015) 50%, transparent 100%);
  background-size: 100% 200%;
  animation: etScan 10s linear infinite;
}
@keyframes etScan { 0% { background-position: 0 -100%; } 100% { background-position: 0 100%; } }
.et-glow { position: absolute; border-radius: 50%; filter: blur(160px); opacity: 0.06; }
.et-glow-1 { width: 500px; height: 500px; background: var(--nc-primary); top: -100px; right: -80px; }
.et-glow-2 { width: 400px; height: 400px; background: var(--nc-primary); bottom: -60px; left: -60px; }

/* ── Hero ──────────────────────────────────────────────────────────────────── */
.et-hero { position: relative; z-index: 1; padding: 28px 0 16px; }
.et-hero-inner { max-width: 100%; }
.et-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--et-mono); font-size: 10px; letter-spacing: 0.15em;
  color: var(--et-cyan); background: rgba(var(--nc-primary-rgb),0.06); border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 20px; padding: 3px 14px;
}
.et-chip-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.et-h1 {
  font-family: var(--et-mono); font-size: 28px; font-weight: 700;
  letter-spacing: 0.04em; margin: 10px 0 6px; color: var(--et-text);
}
.et-accent { color: var(--et-cyan); }
.et-lead { font-family: var(--et-mono); font-size: 12px; color: var(--et-text-dim); letter-spacing: 0.03em; }
.et-hero-stats { display: flex; gap: 32px; margin-top: 18px; }
.et-hero-stat { display: flex; flex-direction: column; }
.et-hero-stat-val { font-family: var(--et-mono); font-size: 20px; font-weight: 600; color: var(--et-text); }
.et-hero-stat-label { font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.12em; color: var(--et-text-dim); text-transform: uppercase; margin-top: 2px; }

/* ── Old header removed, replaced by hero ── */
.et-header {
  background: var(--et-surface);
  border-bottom: 1px solid var(--et-border);
  padding: 18px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.et-header-left { display: flex; align-items: center; gap: 14px; }
.et-header-icon {
  width: 40px; height: 40px;
  border-radius: var(--et-radius);
  background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  display: flex; align-items: center; justify-content: center;
  color: var(--et-cyan); flex-shrink: 0;
}
.et-header-title {
  font-family: var(--et-mono); font-size: 14px; font-weight: 700;
  color: var(--et-cyan); letter-spacing: 0.06em; text-transform: uppercase;
}
.et-header-sub { font-size: 11px; color: var(--et-text-dim); margin-top: 2px; }
.et-header-right { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }

/* ── Quick Stats ───────────────────────────────────────────────────────────── */
.et-quickstat { text-align: center; }
.et-quickstat-label {
  font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--et-text-muted); display: block;
}
.et-quickstat-value {
  font-family: var(--et-mono); font-size: 18px; font-weight: 700;
  color: var(--et-cyan); line-height: 1.2; display: flex;
  align-items: center; justify-content: center; gap: 6px;
}
.et-quickstat-value.green { color: var(--et-green); }
.et-quickstat-value.red   { color: var(--et-red); }
.et-quickstat-value.dim   { color: var(--et-text-dim); }

/* ── Dot Indicator ─────────────────────────────────────────────────────────── */
.et-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
}
.dot-green { background: var(--et-green); box-shadow: 0 0 6px rgba(16, 185, 129, 0.6); }
.dot-red   { background: var(--et-red); box-shadow: 0 0 6px rgba(239, 68, 68, 0.4); }

/* ── Tab Bar ───────────────────────────────────────────────────────────────── */
.et-tabs { position: relative; z-index: 1;
  display: flex; gap: 2px;
  border-bottom: 1px solid var(--et-border);
  padding: 0 28px; background: var(--et-surface); overflow-x: auto;
}
.et-tab {
  padding: 10px 16px;
  font-family: var(--et-mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--et-text-dim); cursor: pointer;
  border: none; border-bottom: 2px solid transparent;
  transition: all 0.15s; margin-bottom: -1px; white-space: nowrap;
  background: none;
}
.et-tab:hover { color: var(--et-text); }
.et-tab.active { color: var(--et-cyan); border-bottom-color: var(--et-cyan); }

/* ── Content ───────────────────────────────────────────────────────────────── */
.et-content { padding: 24px 28px; position: relative; z-index: 1; }
.et-section { display: flex; flex-direction: column; gap: 20px; }

/* ── Stat Cards ────────────────────────────────────────────────────────────── */
.et-stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }
.et-stat-card {
  background: rgba(var(--nc-primary-rgb), 0.03); border: 1px solid var(--et-border);
  border-radius: var(--et-radius-lg); padding: 16px 20px;
  transition: border-color 0.2s, background 0.2s;
}
.et-stat-card:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.et-stat-card:hover { border-color: var(--et-border-hover); }
.et-stat-label {
  font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--et-text-dim); margin-bottom: 6px;
}
.et-stat-value {
  font-family: var(--et-mono); font-size: 22px; font-weight: 700;
  color: var(--et-cyan); display: flex; align-items: center; gap: 8px;
}
.et-stat-value.green { color: var(--et-green); }
.et-stat-value.red   { color: var(--et-red); }
.et-stat-value.dim   { color: var(--et-text-dim); }
.et-stat-value.cyan  { color: var(--et-cyan); }

/* ── Dynamic auto-regulation UI (2026-06-06) ──────────────────────────────── */
.et-dim { opacity: 0.45; transition: opacity 0.2s; }
.et-checkbox-accent { color: var(--et-cyan); font-weight: 600; }
.et-run-hint { margin-top: 8px; }
.et-notice {
  margin-top: 10px; padding: 8px 12px; border-radius: 6px;
  font-family: var(--et-mono); font-size: 11px; letter-spacing: 0.02em;
}
.et-notice-ok  { background: rgba(16, 185, 129, 0.10); border: 1px solid var(--et-green); color: var(--et-green); }
.et-notice-err { background: rgba(239, 68, 68, 0.10); border: 1px solid var(--et-red); color: var(--et-red); }

/* ── Cards ─────────────────────────────────────────────────────────────────── */
.et-card {
  /* Canonical house card: quiet primary-tint fill + faint top sheen + light blur + soft shadow. */
  background:
    linear-gradient(168deg, rgba(255,255,255,0.025), rgba(255,255,255,0) 60%),
    rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: var(--et-radius-lg);
  backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 12px 32px -22px rgba(0,0,0,0.8);
  transition: border-color 0.2s;
}
.et-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); }
.et-card-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px 12px; border-bottom: 1px solid var(--et-border);
  gap: 12px; flex-wrap: wrap;
}
.et-card-title {
  font-family: var(--et-mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--et-cyan);
}
.et-card-body { padding: 16px 20px; }

/* ── Presets ────────────────────────────────────────────────────────────────── */
.et-preset-btn {
  background: var(--et-surface-2); border: 1px solid var(--et-border);
  border-radius: var(--et-radius); padding: 12px 20px;
  cursor: pointer; transition: all 0.15s; text-align: left;
  display: flex; flex-direction: column; gap: 4px; min-width: 140px;
}
.et-preset-btn:hover {
  border-color: var(--et-cyan);
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.15);
}
.et-preset-name {
  font-family: var(--et-mono); font-size: 12px; font-weight: 700;
  color: var(--et-cyan); letter-spacing: 0.04em;
}
.et-preset-desc {
  font-family: var(--et-mono); font-size: 10px; color: var(--et-text-dim);
}

/* ── Config ────────────────────────────────────────────────────────────────── */
.et-config-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
.et-config-item { display: flex; flex-direction: column; gap: 6px; }
.et-label {
  font-family: var(--et-mono); font-size: 10px; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--et-text-dim);
}
.et-label-val {
  color: var(--et-cyan); font-weight: 700;
}
.et-radio-group { display: flex; gap: 16px; }
.et-radio, .et-checkbox {
  font-family: var(--et-mono); font-size: 11px; color: var(--et-text);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.et-radio input, .et-checkbox input { accent-color: var(--et-cyan); cursor: pointer; }
.et-slider {
  -webkit-appearance: none; appearance: none; width: 100%; height: 4px;
  background: rgba(var(--nc-primary-rgb), 0.12); border-radius: 2px; outline: none;
}
.et-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%;
  background: var(--et-cyan); cursor: pointer; border: 2px solid var(--et-bg);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.4);
}
.et-slider::-moz-range-thumb {
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--et-cyan); cursor: pointer; border: 2px solid var(--et-bg);
}

/* ── Buttons ───────────────────────────────────────────────────────────────── */
.et-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px; border-radius: var(--et-radius);
  font-family: var(--et-mono); font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  cursor: pointer; transition: all 0.15s; border: 1px solid transparent;
  white-space: nowrap;
}
.et-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.et-btn-green {
  background: rgba(16, 185, 129, 0.12); color: var(--et-green);
  border-color: rgba(16, 185, 129, 0.35);
}
.et-btn-green:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.2); border-color: var(--et-green);
  box-shadow: 0 0 14px rgba(16, 185, 129, 0.2);
}
.et-btn-red {
  background: rgba(239, 68, 68, 0.1); color: var(--et-red);
  border-color: rgba(239, 68, 68, 0.3);
}
.et-btn-red:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.18); border-color: var(--et-red);
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.2);
}
.et-btn-gold {
  background: rgba(212, 160, 23, 0.1); color: var(--et-gold);
  border-color: rgba(212, 160, 23, 0.3);
}
.et-btn-gold:hover:not(:disabled) {
  background: rgba(212, 160, 23, 0.18); border-color: var(--et-gold);
  box-shadow: 0 0 14px rgba(212, 160, 23, 0.2);
}
.et-btn-ghost {
  background: transparent; color: var(--et-text-dim); border-color: var(--et-border);
}
.et-btn-ghost:hover:not(:disabled) {
  color: var(--et-text); border-color: var(--et-border-hover);
  background: var(--et-surface-2);
}
.et-action-row { display: flex; gap: 12px; flex-wrap: wrap; }

/* ── Status Line ───────────────────────────────────────────────────────────── */
.et-status-line {
  font-family: var(--et-mono); font-size: 10px; color: var(--et-text-dim);
  letter-spacing: 0.04em; padding: 6px 0;
}
.et-instance-btns { display: flex; gap: 4px; }
.et-instance-btn {
  font-family: var(--et-mono); font-size: 11px; padding: 3px 10px;
  background: rgba(0,20,20,0.6); border: 1px solid var(--et-border); color: var(--et-text-dim);
  border-radius: 3px; cursor: pointer;
}
.et-instance-btn.active { border-color: var(--et-cyan); color: var(--et-cyan); background: rgba(var(--nc-primary-rgb),0.08); }

/* ── Log Panel ─────────────────────────────────────────────────────────────── */
.et-log-panel {
  margin-top: 12px; border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 4px;
  background: #030808; overflow: hidden;
}
.et-log-header {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.1em;
  color: var(--et-cyan); padding: 5px 10px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  background: rgba(var(--nc-primary-rgb),0.03);
}
.et-log-title { font-weight: 700; }
.et-log-legend { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.et-log-legend-label { color: var(--et-text-dim); letter-spacing: 0.06em; }
.et-log-legend-chip {
  font-weight: 700; font-size: 9px; letter-spacing: 0.06em; text-transform: lowercase;
  padding: 1px 7px; border: 1px solid currentColor; border-radius: 99px;
  background: color-mix(in srgb, currentColor 10%, transparent);
}
.et-log-body {
  max-height: 400px; overflow-y: auto; padding: 8px 14px;
  font-family: var(--et-mono); font-size: 12.5px; line-height: 1.7;
}
.et-log-line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.et-log-line.log-cycle { color: #22c55e; }
.et-log-line.log-fail { color: #ef4444; }
.et-log-line.log-tx { color: var(--et-text-dim); }
.et-log-inst {
  display: inline-block; min-width: 13px; text-align: center; margin-right: 7px;
  font-weight: 700; font-size: 10px; padding: 0 4px;
  border: 1px solid currentColor; border-radius: 4px;
  background: color-mix(in srgb, currentColor 12%, transparent);
}
.et-log-empty { color: var(--et-text-dim); font-style: italic; }

/* ── Agent Tab ─────────────────────────────────────────────────────────────── */
.et-action-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.et-fund-inline { display: flex; gap: 6px; align-items: center; }
.et-input-sm {
  width: 90px; padding: 4px 8px; font-family: var(--et-mono); font-size: 12px;
  background: rgba(0,20,20,0.8); border: 1px solid var(--et-border); color: var(--et-text);
  border-radius: 4px; text-align: right;
}
.et-input-sm:focus { outline: none; border-color: var(--et-cyan); }
.et-fund-result {
  font-family: var(--et-mono); font-size: 10px; color: var(--et-green);
  letter-spacing: 0.04em;
}
.et-summary {
  font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim);
  letter-spacing: 0.04em;
}
.et-empty {
  font-family: var(--et-mono); font-size: 12px; color: var(--et-text-muted);
  text-align: center; padding: 40px 0;
}
.et-registry-list { display: flex; flex-direction: column; gap: 12px; }
.et-registry-header { cursor: pointer; user-select: none; }
.et-registry-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.et-collapse-icon {
  font-size: 10px; color: var(--et-text-dim); width: 14px; text-align: center;
}
.et-registry-name {
  font-family: var(--et-mono); font-size: 12px; font-weight: 700; color: var(--et-cyan);
}
.et-registry-frame {
  font-family: var(--et-mono); font-size: 10px; color: var(--et-text-dim);
}
.et-registry-meta {
  font-family: var(--et-mono); font-size: 10px; color: var(--et-text-muted);
}
.et-funded-badge {
  font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.08em;
  color: var(--et-text-dim); background: rgba(var(--nc-primary-rgb), 0.06);
  padding: 3px 8px; border-radius: 4px; border: 1px solid var(--et-border);
}

/* ── Agent Rows ────────────────────────────────────────────────────────────── */
.et-agent-list { display: flex; flex-direction: column; gap: 6px; padding: 12px 20px; }
.et-agent-row {
  display: grid; grid-template-columns: 180px 1fr 80px;
  align-items: center; gap: 12px; padding: 4px 0;
}
.et-agent-name {
  font-family: var(--et-mono); font-size: 11px; color: var(--et-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.et-agent-balance {
  font-family: var(--et-mono); font-size: 11px; font-weight: 600;
  text-align: right;
}

/* ── Balance Bars ──────────────────────────────────────────────────────────── */
.et-balance-track {
  height: 6px; background: rgba(var(--nc-primary-rgb), 0.06);
  border-radius: 3px; overflow: hidden;
}
.et-balance-bar {
  height: 100%; border-radius: 3px; transition: width 0.3s ease;
  min-width: 2px;
}
.bar-green  { background: linear-gradient(90deg, rgba(16,185,129,0.6), rgba(16,185,129,0.9)); }
.bar-yellow { background: linear-gradient(90deg, rgba(245,158,11,0.5), rgba(245,158,11,0.8)); }
.bar-red    { background: linear-gradient(90deg, rgba(239,68,68,0.5), rgba(239,68,68,0.8)); }

/* Text colors matching bars */
.et-agent-balance.bar-green  { color: var(--et-green); }
.et-agent-balance.bar-yellow { color: var(--et-yellow); }
.et-agent-balance.bar-red    { color: var(--et-red); }

/* ── Topology Placeholder ──────────────────────────────────────────────────── */
.et-topology-placeholder { border-color: rgba(var(--nc-primary-rgb), 0.25); }
.et-topo-title {
  font-family: var(--et-mono); font-size: 14px; font-weight: 700;
  color: var(--et-cyan); letter-spacing: 0.06em; margin-bottom: 6px;
}
.et-topo-sub {
  font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim);
}

/* ── Spinner ───────────────────────────────────────────────────────────────── */
.et-spin { display: inline-block; animation: spin 1s linear infinite; }

/* ── Responsive ────────────────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .et-header { padding: 14px 16px; }
  .et-content { padding: 16px; }
  .et-agent-row { grid-template-columns: 120px 1fr 60px; gap: 8px; }
  .et-stat-row { grid-template-columns: repeat(2, 1fr); }
}

/* ── Preview Panel ──────────────────────────────────────── */
.et-preview-panel {
  background: rgba(16,185,129,0.05); border: 1px solid rgba(16,185,129,0.15);
  border-radius: 8px; padding: 16px; margin-bottom: 16px;
}
.et-preview-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 6px 24px; margin-bottom: 12px;
}
.et-preview-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.et-preview-label { font-size: 12px; color: var(--et-text-dim); text-transform: uppercase; letter-spacing: 0.5px; }
.et-preview-value { font-family: var(--et-mono); font-size: 14px; color: var(--et-text); }
.et-deficit { color: #ef4444 !important; font-weight: 600; }
.et-surplus { color: #10b981 !important; }
.et-mint-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
/* Generic primary action → theme accent (recolors neural↔sovereign). Mint buttons are
   CURRENCY-categorical per the 3-currency glyph convention: AVT=green, JDAY=blue #00b0ff. */
.et-btn-cyan { background: rgba(var(--nc-primary-rgb),0.15); color: var(--et-cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.3); }
.et-btn-cyan:hover { background: rgba(var(--nc-primary-rgb),0.25); }
.et-btn-mint { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
.et-btn-mint:hover { background: rgba(16,185,129,0.25); }
.et-btn-mint-b { background: rgba(0,176,255,0.15); color: #00b0ff; border: 1px solid rgba(0,176,255,0.3); }
.et-btn-mint-b:hover { background: rgba(0,176,255,0.25); }
.et-mint-result { font-family: var(--et-mono); font-size: 13px; color: #10b981; }

/* ── Funding Progress Log ───────────────────────────────── */
.et-fund-log {
  background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px; margin-bottom: 16px; overflow: hidden;
}
.et-fund-log-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; background: rgba(0,0,0,0.2);
  font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
  color: var(--et-text-dim);
}
.et-fund-log-body {
  max-height: 300px; overflow-y: auto; padding: 8px 12px;
  font-family: var(--et-mono); font-size: 12px; line-height: 1.6;
}
.et-fund-log-line { white-space: pre-wrap; }
.et-log-ok { color: #10b981; }
.et-log-error { color: #ef4444; }
.et-log-warn { color: #f59e0b; }
.et-log-info { color: var(--et-text-dim); }
.et-log-done { color: #10b981; font-weight: 600; }

/* ── Config selects / inputs (2026-05-31) ──────────────────────────────────── */
.et-select {
  width: 100%; box-sizing: border-box;
  font-family: var(--et-mono); font-size: 12px;
  background: var(--et-surface-2); color: var(--et-text);
  border: 1px solid var(--et-border); border-radius: var(--et-radius);
  padding: 7px 10px; cursor: pointer;
}
.et-select:hover { border-color: var(--et-border-hover); }
.et-select:focus { outline: none; border-color: var(--et-cyan); }
.et-hint { display: block; font-family: var(--et-mono); font-size: 9px; color: var(--et-text-muted); margin-top: 4px; letter-spacing: 0.02em; }
.et-input-full { width: 100%; box-sizing: border-box; }
.et-config-wide { grid-column: 1 / -1; }

/* ── Stress presets ────────────────────────────────────────────────────────── */
.et-preset-stress { border-color: rgba(239,68,68,0.35); }
.et-preset-stress .et-preset-name { color: var(--et-red); }
.et-preset-stress:hover { border-color: var(--et-red); box-shadow: 0 0 14px rgba(239,68,68,0.12); }

/* ── Telemetry ─────────────────────────────────────────────────────────────── */
.et-unit { font-size: 11px; color: var(--et-text-dim); margin-left: 3px; font-weight: 400; }
.et-card-sub { font-family: var(--et-mono); font-size: 9px; color: var(--et-text-muted); letter-spacing: 0.08em; }
.et-tele-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 860px) { .et-tele-grid { grid-template-columns: 1fr; } }

.et-lat-row {
  display: grid; grid-template-columns: 1.1fr 0.9fr repeat(3, 0.7fr);
  align-items: center; gap: 8px;
  font-family: var(--et-mono); font-size: 12px;
  padding: 9px 4px; border-bottom: 1px solid var(--et-border);
}
.et-lat-row:last-child { border-bottom: none; }
.et-lat-label { color: var(--et-cyan); font-weight: 600; }
.et-lat-count { color: var(--et-text-dim); font-size: 10px; }
.et-lat-val { color: var(--et-text); text-align: right; }
.et-lat-val.dim { color: var(--et-text-muted); }
.et-lat-empty { text-align: left; }

.et-badge { font-family: var(--et-mono); font-size: 9px; letter-spacing: 0.12em; padding: 2px 9px; border-radius: 10px; border: 1px solid transparent; }
.badge-green { color: var(--et-green); background: rgba(16,185,129,0.08); border-color: rgba(16,185,129,0.25); }
.badge-dim { color: var(--et-text-muted); background: rgba(255,255,255,0.02); border-color: var(--et-border); }

.et-gauge { margin-bottom: 14px; }
.et-gauge:last-child { margin-bottom: 0; }
.et-gauge-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 5px; }
.et-gauge-label { font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim); letter-spacing: 0.04em; }
.et-gauge-val { font-family: var(--et-mono); font-size: 12px; color: var(--et-text); }
.et-gauge-val.red { color: var(--et-red); }
.et-gauge-val.warn { color: var(--et-yellow); }
.et-gauge-max { color: var(--et-text-muted); font-size: 10px; }
.et-gauge-track { height: 6px; border-radius: 3px; background: rgba(255,255,255,0.04); overflow: hidden; }
.et-gauge-fill { height: 100%; border-radius: 3px; background: var(--et-green); transition: width 0.5s ease; }
.et-gauge-fill.warn { background: var(--et-yellow); }
.et-gauge-fill.red { background: var(--et-red); }

.et-laststop {
  display: flex; align-items: center; gap: 8px;
  margin-top: 14px; padding: 9px 12px; border-radius: var(--et-radius);
  font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim);
  background: rgba(255,255,255,0.02); border: 1px solid var(--et-border);
}
.et-laststop-warn { color: var(--et-yellow); background: rgba(245,158,11,0.06); border-color: rgba(245,158,11,0.25); }
.et-laststop strong { color: var(--et-text); }
.et-laststop-warn strong { color: var(--et-yellow); }
.et-laststop-icon { font-size: 12px; }
.et-laststop-ago { margin-left: auto; color: var(--et-text-muted); white-space: nowrap; }

.et-inst-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; }
.et-inst-card { background: var(--et-surface-2); border: 1px solid var(--et-border); border-radius: var(--et-radius); padding: 10px 12px; }
.et-inst-head { font-family: var(--et-mono); font-size: 11px; color: var(--et-cyan); font-weight: 600; }
.et-inst-cyc { color: var(--et-text-muted); font-weight: 400; font-size: 9px; }
.et-inst-tps { font-family: var(--et-mono); font-size: 18px; color: var(--et-text); margin: 4px 0 2px; }
.et-inst-okfail { font-family: var(--et-mono); font-size: 10px; }
.et-inst-okfail .green { color: var(--et-green); }
.et-inst-okfail .red { color: var(--et-red); }
.et-inst-okfail .dim { color: var(--et-text-muted); }

/* ── Demand Director (market mode) ──────────────────────────────────────────── */
.dd-note { display: flex; align-items: center; gap: 7px; font-size: 11px; line-height: 1.5; color: var(--et-text-dim); margin-bottom: 12px; }
.dd-note :deep(svg) { width: 13px; height: 13px; flex: none; opacity: 0.7; }
.dd-note b { color: var(--et-text); }
.dd-table { width: 100%; border-collapse: collapse; font-family: var(--et-mono); }
.dd-table th { text-align: left; font-size: 9px; letter-spacing: 0.12em; color: var(--et-text-muted); text-transform: uppercase; padding: 4px 8px; border-bottom: 1px solid var(--et-border); }
.dd-table td { padding: 6px 8px; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.07); vertical-align: middle; }
.dd-sym { color: var(--et-cyan); font-weight: 700; font-size: 12px; }
.dd-venue { color: var(--et-text-dim); font-size: 10px; }
.dd-dir { display: inline-flex; gap: 5px; flex-wrap: wrap; }
.dd-seg { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; min-height: 30px; font-family: var(--et-mono); font-size: 9.5px; font-weight: 800; letter-spacing: 0.06em; color: var(--et-text-dim); background: rgba(var(--nc-primary-rgb), 0.04); border: 1px solid var(--et-border); border-radius: 7px; padding: 5px 10px; transition: all 0.15s; }
.dd-seg :deep(svg) { width: 12px; height: 12px; }
.dd-seg:hover { color: var(--et-text); border-color: var(--et-border-hover); }
.dd-seg.up.active { color: var(--et-green); background: rgba(16, 185, 129, 0.14); border-color: rgba(16, 185, 129, 0.55); }
.dd-seg.down.active { color: var(--et-red); background: rgba(239, 68, 68, 0.14); border-color: rgba(239, 68, 68, 0.55); }
.dd-seg.flat.active { color: var(--et-cyan); background: rgba(var(--nc-primary-rgb), 0.14); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.dd-strength { width: 80px; min-height: 30px; padding: 5px 9px; font-family: var(--et-mono); font-size: 12px; font-weight: 700; color: var(--et-text); background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.3); border-radius: 7px; }
.dd-strength:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.7); box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb), 0.2); }
.dd-master { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; min-height: 28px; margin-left: auto; font-family: var(--et-mono); font-size: 10px; font-weight: 800; letter-spacing: 0.1em; color: var(--et-text-dim); background: rgba(var(--nc-primary-rgb), 0.04); border: 1px solid var(--et-border); border-radius: 7px; padding: 4px 11px; transition: all 0.15s; }
.dd-master .dd-master-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--et-text-muted); transition: all 0.15s; }
.dd-master:hover { border-color: var(--et-border-hover); }
.dd-master.on { color: #f59e0b; background: rgba(245, 158, 11, 0.12); border-color: rgba(245, 158, 11, 0.55); }
.dd-master.on .dd-master-dot { background: #f59e0b; box-shadow: 0 0 7px rgba(245, 158, 11, 0.85); }
.dd-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.dd-save { background: rgba(var(--nc-primary-rgb), 0.1); }
.dd-off { color: #f59e0b; border-color: rgba(245, 158, 11, 0.4); }
.dd-saved { display: inline-flex; align-items: center; gap: 6px; font-family: var(--et-mono); font-size: 10px; letter-spacing: 0.06em; color: var(--et-green); }
.dd-saved :deep(svg) { width: 13px; height: 13px; }

/* ── Campaign Engine (market mode) ──────────────────────────────────────────── */
.camp-badge { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; font-family: var(--et-mono); font-size: 10px; font-weight: 800; letter-spacing: 0.1em; color: var(--et-text-muted); background: rgba(var(--nc-primary-rgb), 0.04); border: 1px solid var(--et-border); border-radius: 7px; padding: 4px 11px; }
.camp-badge-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--et-text-muted); }
.camp-badge.live { color: var(--et-green); background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.5); }
.camp-badge.live .camp-badge-dot { background: var(--et-green); box-shadow: 0 0 7px rgba(16, 185, 129, 0.85); animation: camp-pulse 1.6s ease-in-out infinite; }
@keyframes camp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.camp-status { background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid var(--et-border); border-radius: 9px; padding: 12px 14px; margin-bottom: 14px; }
.camp-status-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 9px; }
.camp-name { display: inline-flex; align-items: center; gap: 6px; font-family: var(--et-mono); font-size: 13px; font-weight: 800; color: var(--et-cyan); letter-spacing: 0.04em; }
.camp-name :deep(svg) { width: 14px; height: 14px; }
.camp-phase { font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim); }
.camp-phase b { color: var(--et-text); text-transform: uppercase; letter-spacing: 0.05em; }
.camp-progress { height: 7px; border-radius: 4px; background: rgba(var(--nc-primary-rgb), 0.1); overflow: hidden; }
.camp-progress-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--et-cyan), #f59e0b); transition: width 0.6s ease; }
.camp-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-top: 9px; font-family: var(--et-mono); font-size: 11px; color: var(--et-text-dim); }
.camp-meta :deep(svg) { width: 12px; height: 12px; vertical-align: -2px; margin-right: 3px; }
.camp-dir { display: inline-flex; align-items: center; gap: 4px; font-weight: 700; }
.camp-dir.up { color: var(--et-green); }
.camp-dir.down { color: var(--et-red); }
.camp-dir.flat { color: var(--et-text-dim); }
.camp-idle { margin-bottom: 14px; }
.camp-controls { display: flex; flex-direction: column; gap: 10px; }
.camp-field { display: flex; align-items: center; gap: 10px; }
.camp-label { font-family: var(--et-mono); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--et-text-muted); min-width: 64px; }
.camp-select { flex: 1; max-width: 280px; min-height: 34px; padding: 6px 10px; font-family: var(--et-mono); font-size: 12px; font-weight: 700; color: var(--et-text); background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.3); border-radius: 7px; }
.camp-select:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.7); box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb), 0.2); }
.camp-preset-desc { margin: 0; font-size: 11.5px; line-height: 1.5; color: var(--et-text-dim); }
.camp-preset-meta { display: block; margin-top: 3px; font-family: var(--et-mono); font-size: 10px; color: var(--et-text-muted); letter-spacing: 0.04em; }
.camp-restore { font-size: 11px; }
.camp-start { background: rgba(16, 185, 129, 0.12); color: var(--et-green); border-color: rgba(16, 185, 129, 0.4); }
.camp-stop { color: var(--et-red); border-color: rgba(239, 68, 68, 0.4); }
.camp-refresh { padding-left: 10px; padding-right: 10px; }
</style>
