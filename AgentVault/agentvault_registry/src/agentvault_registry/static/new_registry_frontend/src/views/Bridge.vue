<!-- MissionControl.vue — §BRIDGE: THE BRIDGE OF THE SHIP.
     The stage is the whole viewport; the HUD are instruments around it. Every
     number here comes from a rail this app already had — the recomposition is
     what changed, not the truth. -->
<template>
  <div ref="brgEl" class="brg"
       :class="{ 'brg--demo': railsCollapsed, 'brg--attract': attract, 'brg--focus': stageFocus, 'brg--lite': gfxMode === 'lite' }"
       :data-gfx="gfxMode" data-testid="bridge-root">

    <!-- ═══ THE STAGE (full-bleed, behind everything) ═══
         §LITEBRIDGE — `v-if`, not `v-show`. A hidden WebGL context still holds
         its GPU memory and still runs whatever its owner asks it to; the whole
         point of the light bridge is that the expensive thing is NOT THERE. -->
    <BridgeStage v-if="gfxMode === 'full'"
                 ref="stageRef" :mine-dids="fleetDids" :star-dids="activeStarDids" :owned-homes="starHomes"
                 :can-open-forensics="authStore.isAdmin" :search="searchQ"
                 :atmosphere="atmosphere"
                 @select-agent="onSelect" />

    <!-- ═══ THE HUD ═══ -->
    <div class="brg-hud">

      <!-- ── SPINE ─────────────────────────────────────────────────────── -->
      <header class="brg-spine" data-tour="mc-spine">
        <div class="brg-spine-id">
          <span class="brg-spine-name">{{ mcRegistryName || t('mc.title', 'MISSION CONTROL') }}</span>
          <span class="brg-spine-cur">{{ fleetCurrency }}</span>
        </div>

        <!-- Δ SEAL — the prime directive, permanently on screen. -->
        <button
          type="button"
          class="brg-seal"
          data-tour="mc-seal"
          :class="sealClass"
          :title="sealTitle"
          @click="refreshSeal"
        >
          <span class="brg-seal-dot"></span>
          <span class="brg-seal-label">&#916;</span>
          <span class="brg-seal-val">{{ sealValue }}</span>
          <span class="brg-seal-age">{{ sealAge }}</span>
        </button>

        <!-- Corridor chips: which frames are actually streaming to this page. -->
        <div class="brg-corridors">
          <span
            v-for="f in ledger.frames.value" :key="`cor-${f.key}`"
            class="brg-cor" :class="f.connected ? 'is-live' : f.gaveUp ? 'is-gone' : 'is-down'"
            :title="`${f.label} · ${f.currency} · ${f.connected ? t('bridge.stream.live', 'LIVE') : t('bridge.ledger.reconnecting', 'Reconnecting')}`"
          >{{ f.key }}</span>
        </div>

        <!-- ALARM SLOT — stays empty until something is genuinely wrong. -->
        <div class="brg-alarm-slot" aria-live="polite">
          <span v-if="alarmText" class="brg-alarm">{{ alarmText }}</span>
          <span v-else-if="replayNote" class="brg-follow-note">{{ replayNote }}</span>
          <span v-else-if="followNote" class="brg-follow-note">{{ followNote }}</span>
          <!-- SELECTED is the state that matters to the actions; FOLLOWING is
               only the camera, so the chip names both and can show one without
               the other (§BRIDGE R9). -->
          <span v-else-if="selectedDid" class="brg-follow-note" data-testid="following-chip">
            {{ t('bridge.follow.selected', 'SELECTED') }}
            {{ fleetAgentNames[selectedDid] || `${selectedDid.slice(0, 18)}...` }}
            <span v-if="followingDid" class="brg-follow-cam">{{ t('bridge.follow.cam', '· camera on') }}</span>
            <button type="button" class="brg-follow-x" :title="t('bridge.follow.release', 'Release (Esc)')"
                    @click="onSelect(selectedDid)">&times;</button>
          </span>
          <span v-else-if="followingDid" class="brg-follow-note" data-testid="following-chip">
            {{ t('bridge.follow.following', 'FOLLOWING') }}
            {{ fleetAgentNames[followingDid] || `${followingDid.slice(0, 18)}...` }}
            <button type="button" class="brg-follow-x" :title="t('bridge.follow.release', 'Release (Esc)')"
                    @click="onFollow(followingDid)">&times;</button>
          </span>
        </div>

        <!-- AGORA: COLLAPSED AT START, by the Commander's word. The ticker is a
             marquee with its own polling and animation; at boot it competed with
             the stage for frames and grew the spine to two rows. It is not
             mounted at all until asked for, so nothing moves and nothing fetches
             until you open it. -->
        <div class="brg-spine-ticker" :class="{ 'is-open': tickerOpen && tickerState === 'ready' }">
          <button
            type="button"
            class="brg-door brg-ticker-toggle"
            :aria-expanded="tickerOpen ? 'true' : 'false'"
            :title="t('bridge.doors.tickerHelp', 'Show the AGORA market ticker')"
            @click="toggleTicker"
          >
            <Icon :name="tickerOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'" :size="12" />
            <span>{{ t('bridge.doors.ticker', 'AGORA') }}</span>
          </button>
          <!-- The ticker paints nothing until its (slow) fetch lands, so SAY what
               is happening rather than opening an empty gap. -->
          <span v-if="tickerOpen && tickerState === 'loading'" class="brg-ticker-note">
            {{ t('bridge.doors.tickerLoading', 'loading markets...') }}
          </span>
          <span v-else-if="tickerOpen && tickerState === 'empty'" class="brg-ticker-note">
            {{ t('bridge.doors.tickerEmpty', 'no markets reachable') }}
          </span>
          <ExchangeTicker v-if="tickerOpen" class="brg-ticker-body" @loaded="onTickerLoaded" />
        </div>

        <div class="brg-spine-doors">
          <!-- #B8 the fleet lens. Keyboard: F to isolate, Esc to restore. -->
          <!-- §BRIDGE R10 — HOW DEEP AM I LOGGED IN? His ask: *"a small button
               that may take your there. the button could change colors depending
               on how deep/many accounts you are logged in with on how many
               registries or also show a number on the button."* It is a status
               light AND the door to where that state is managed (Settings ->
               Multi-Frame), and it counts REGISTRIES YOU HOLD A SESSION ON —
               this one always, plus every connected sibling. -->
          <router-link
            to="/settings?tab=multiframe"
            class="brg-door brg-reach" :class="`is-${reachTier}`"
            data-testid="bridge-reach"
            :title="reachTitle"
          >
            <Icon name="mdi:layers" :size="12" />
            <span class="brg-reach-n" data-testid="bridge-reach-n">{{ reachCount }}</span>
          </router-link>

          <!-- §BRIDGE R10 — FIND AN AGENT. "it would be good to have a search
               for a specific agent which highlights him. check how the galactic
               command did it." The canvas already dims non-matches and beacons
               matches; this is the control that feeds it, plus an honest count
               of how many of the POPULATION matched (not just how many stars
               are drawn). Enter selects the first match. -->
          <div class="brg-find" :class="{ 'is-active': !!searchQ }">
            <Icon name="mdi:magnify" :size="12" />
            <input
              v-model="searchQ"
              type="search"
              class="brg-find-in"
              data-testid="bridge-search"
              :placeholder="t('bridge.find.ph', 'find agent')"
              :title="t('bridge.find.help', 'Highlight agents by name or DID. Enter selects the first match.')"
              @keydown.enter.prevent="selectFirstMatch"
              @keydown.esc.prevent="searchQ = ''"
            />
            <span v-if="searchQ.trim().length >= 2" class="brg-find-n" data-testid="bridge-search-count">
              {{ searchMatchCount }}
            </span>
            <button v-if="searchQ" type="button" class="brg-find-x"
                    :title="t('bridge.find.clear', 'Clear')" @click="searchQ = ''">&times;</button>
          </div>
          <button
            type="button" class="brg-door brg-door-lens" :class="{ 'is-on': fleetLens }"
            data-testid="fleet-lens"
            :aria-pressed="fleetLens"
            :title="t('bridge.doors.lensHelp', 'Isolate your own agents traffic (F). Esc restores.')"
            @click="setFleetLens(!fleetLens)"
          >
            <Icon name="mdi:eye" :size="12" />
            <span>{{ t('bridge.doors.lens', 'FLEET') }}</span>
          </button>
          <button
            type="button" class="brg-door brg-door-chime" :class="{ 'is-on': chimeOn }"
            data-testid="fleet-chime"
            :aria-pressed="chimeOn"
            :title="t('bridge.doors.chimeHelp', 'A soft chime when your own agents act. Off by default.')"
            @click="toggleChime"
          >
            <Icon :name="chimeOn ? 'mdi:bell' : 'mdi:bell-off'" :size="12" />
          </button>
          <!-- §LITEBRIDGE — three states, not a toggle. A two-way switch cannot
               express "let the machine decide", and a tour step that clicks a
               toggle would switch the wrong way for half its readers. -->
          <span class="brg-gfx" data-tour="mc-gfx" data-testid="gfx-control"
                :title="gfxRes.reason">
            <span class="brg-gfx-k">{{ t('bridge.gfx.label', 'VIEW') }}</span>
            <button type="button" class="brg-door-sm brg-gfx-b" :class="{ 'is-on': gfxPref === 'auto' }"
                    data-tour="mc-gfx-auto" data-testid="gfx-auto"
                    :aria-pressed="gfxPref === 'auto'"
                    :title="t('bridge.gfx.autoHelp', 'Let this machine decide: the light bridge only when a fact says the stage cannot run well here — no WebGL context, or very few cores.')"
                    @click="setGfx('auto')">{{ t('bridge.gfx.auto', 'AUTO') }}</button>
            <!-- Disabled where it cannot work: a control that accepts a click
                 and then does nothing is worse than one that says why not. -->
            <button type="button" class="brg-door-sm brg-gfx-b" :class="{ 'is-on': gfxPref === 'full' }"
                    data-tour="mc-gfx-full" data-testid="gfx-full"
                    :aria-pressed="gfxPref === 'full'"
                    :disabled="gfxProbed && !gfxCaps.webgl"
                    :title="gfxProbed && !gfxCaps.webgl
                      ? t('bridge.gfx.fullImpossible', 'This browser cannot open a WebGL context, so the stage would render nothing here.')
                      : t('bridge.gfx.fullHelp', 'The stage: a live 3D starmap of ledger traffic. Needs a GPU.')"
                    @click="setGfx('full')">{{ t('bridge.gfx.full', 'FULL') }}</button>
            <button type="button" class="brg-door-sm brg-gfx-b" :class="{ 'is-on': gfxPref === 'lite' }"
                    data-tour="mc-gfx-lite" data-testid="gfx-lite"
                    :aria-pressed="gfxPref === 'lite'"
                    :title="t('bridge.gfx.liteHelp', 'The light bridge: no WebGL, no per-frame drawing, exact numbers. Every instrument still works.')"
                    @click="setGfx('lite')">{{ t('bridge.gfx.lite', 'LIGHT') }}</button>
          </span>
          <button
            v-if="gfxMode === 'full'"
            type="button" class="brg-door brg-door-atmos" :class="{ 'is-off': atmosphere === 'off' }"
            data-testid="atmos-cycle"
            :title="t('bridge.doors.atmosHelp', 'Background haze over the starfield: CLEAR removes it entirely, HAZE keeps a little (default), DEEP is the full look.')"
            @click="cycleAtmosphere"
          >
            <Icon name="mdi:weather-hazy" :size="12" />
            <span>{{ ATMOS_LABEL[atmosphere] }}</span>
          </button>
          <button
            type="button" class="brg-door brg-door-priv" :class="{ 'is-on': privacyHidden }"
            data-testid="privacy-toggle"
            :aria-pressed="privacyHidden"
            :title="t('bridge.doors.privHelp', 'Hide every amount on the bridge \u2014 balances, bounties, ledger figures, holdings. Nothing is fetched differently; it is a screen you can safely show someone.')"
            @click="togglePrivacy"
          >
            <Icon :name="privacyHidden ? 'mdi:eye-off' : 'mdi:eye'" :size="12" />
          </button>
          <button type="button" class="brg-door" :title="t('bridge.doors.railsHelp', 'Collapse the rails for a clean stage')" @click="railsCollapsed = !railsCollapsed">
            <Icon :name="railsCollapsed ? 'mdi:arrow-expand-horizontal' : 'mdi:arrow-collapse-horizontal'" :size="12" />
          </button>
          <router-link class="brg-door brg-door-cmd" to="/galactic-command" :title="t('bridge.doors.commandHelp', 'Galactic Command Center')">
            {{ t('bridge.doors.command', 'OPEN COMMAND') }}
          </router-link>
        </div>
      </header>

      <!-- ── RAILS ─────────────────────────────────────────────────────── -->
      <div class="brg-body" :class="{ 'l-closed': !railLeftOpen, 'r-closed': !railRightOpen }">

        <!-- LEFT: your fleet -->
        <aside class="brg-rail brg-rail-l" :class="{ 'is-closed': !railLeftShown }" data-tour="mc-fleet">
          <!-- Collapse handle: a hairline on the rail edge. It is meant to be
               almost invisible until you look for it (Commander: "a very, almost
               invisible collapse button ... as little extra space as possible"),
               so it costs 10px of width and nothing else. -->
          <button type="button" class="brg-railtab brg-railtab-l"
                  :aria-expanded="railLeftOpen ? 'true' : 'false'"
                  :title="railLeftOpen ? t('bridge.rail.hide', 'Hide this panel') : t('bridge.rail.show', 'Show this panel')"
                  @click="stageFocus ? (stageFocus = false) : (railLeftOpen = !railLeftOpen)">
            <span class="brg-railtab-mark">{{ railLeftOpen ? '\u2039' : '\u203a' }}</span>
          </button>
          <section v-show="railLeftShown" class="brg-card brg-fleet">
            <header class="brg-card-hdr">
              <span class="brg-card-title">{{ fleetCardMode === 'agent' && selectedAgentDid
                ? t('mc.yourAgent.title', 'YOUR AGENT') : t('mc.yourFleet.title', 'YOUR FLEET') }}</span>
              <!-- R16.2 — one switch, both answers. AGENT is what you are acting
                   as; FLEET is the aggregate. Neither hides the other. -->
              <button type="button" class="brg-card-sw" data-testid="fleet-card-mode"
                      :title="t('bridge.fleet.swap', 'Switch between the agent you are acting as and your whole fleet')"
                      @click="fleetCardMode = fleetCardMode === 'agent' ? 'fleet' : 'agent'">
                {{ fleetCardMode === 'agent' ? t('bridge.fleet.toFleet', 'FLEET') : t('bridge.fleet.toAgent', 'AGENT') }}
              </button>
              <router-link to="/my-agents" class="brg-card-link">{{ fleetAgentCount }} {{ t('bridge.fleet.agents', 'agents') }}</router-link>
            </header>

            <!-- ── THE SELECTED AGENT ─────────────────────────────────────── -->
            <template v-if="fleetCardMode === 'agent' && selectedAgentDid">
              <div class="brg-sel" data-testid="fleet-selected-agent">
                <div class="brg-sel-id">
                  <span class="brg-sel-name" :title="selectedAgentDid">{{ selectedAgentName }}</span>
                  <span v-if="selectedMarks.tier" class="brg-sel-rank" data-testid="fleet-selected-rank"
                        :title="t('bridge.fleet.rankHelp', 'Earned mark, from verified work')">
                    {{ selectedMarks.tier }}
                    <span class="brg-sel-jobs">{{ selectedMarks.jobs }}</span>
                  </span>
                  <span v-else class="brg-sel-rank is-none" data-testid="fleet-selected-rank">
                    {{ t('bridge.fleet.noRank', 'NO VERIFIED WORK YET') }}
                  </span>
                </div>

                <p v-if="selAgentLoading" class="brg-sel-note">{{ t('common.loading', 'Working') }}</p>
                <!-- Read failure is STATED. Zeros for an agent we could not read
                     is the one thing this card must never show. -->
                <p v-else-if="selAgentFailed" class="brg-sel-note" data-testid="fleet-selected-failed">
                  {{ t('bridge.fleet.selFailed', 'Could not read this agent right now \u2014 the figures below are not shown rather than shown as zero.') }}
                </p>
                <div v-else class="brg-sel-grid">
                  <div class="brg-stat" :title="privacyHidden ? '' : `${formatNumber(selAgentProfile?.liquid_balance)} ${fleetCurrency}`">
                    <span class="brg-stat-val brg-v-cyan" data-testid="sel-liquid">{{ money(formatCompact(selAgentProfile?.liquid_balance)) }}</span>
                    <span class="brg-stat-lbl">{{ t('bridge.fleet.liquid', 'LIQUID') }} {{ fleetCurrency }}</span>
                  </div>
                  <div class="brg-stat" :title="privacyHidden ? '' : `${formatNumber(selAgentProfile?.staked_balance)} ${fleetCurrency}`">
                    <span class="brg-stat-val brg-v-blue">{{ money(formatCompact(selAgentProfile?.staked_balance)) }}</span>
                    <span class="brg-stat-lbl">{{ t('bridge.fleet.staked', 'LOCKED') }}</span>
                  </div>
                  <div class="brg-stat" :title="t('bridge.fleet.repHelp', 'Reputation, as the rest of the app reads it')">
                    <span class="brg-stat-val brg-v-gold">{{ selectedRepPct === null ? '\u2014' : selectedRepPct + '%' }}</span>
                    <span class="brg-stat-lbl">{{ t('bridge.fleet.rep', 'REPUTATION') }}</span>
                  </div>
                  <div class="brg-stat" :title="t('bridge.fleet.crossHelp', 'Verified work done on another registry')">
                    <span class="brg-stat-val" :class="selectedMarks.cross ? 'brg-v-green' : ''">{{ selectedMarks.cross ? t('bridge.fleet.yes', 'YES') : t('bridge.fleet.no', 'NO') }}</span>
                    <span class="brg-stat-lbl">{{ t('bridge.fleet.cross', 'TRAVELS') }}</span>
                  </div>
                </div>

                <!-- The aggregate, kept but quiet. -->
                <p class="brg-sel-fleetline" data-testid="fleet-line">
                  {{ t('bridge.fleet.lineFleet', 'fleet') }}:&#32;{{ fleetAgentCount }}&#32;{{ t('bridge.fleet.agents', 'agents') }}
                  &middot;&#32;{{ money(formatCompact(fleetData.total_balance)) }}&#32;{{ fleetCurrency }}
                  &middot;&#32;{{ fleetMarkTier }}
                </p>
              </div>
            </template>

            <p v-else-if="fleetCardMode === 'agent'" class="brg-sel-note" data-testid="fleet-no-agent">
              {{ t('bridge.fleet.pick', 'No agent selected. Pick one in the agent selector and this card becomes about it \u2014 its rank, its balances, its reach.') }}
            </p>

            <template v-if="fleetCardMode === 'fleet' && fleetAgentCount > 0">
              <div class="brg-fleet-grid">
                <div class="brg-stat" :title="`${formatNumber(fleetData.total_liquid_balance)} ${fleetCurrency}`">
                  <span class="brg-stat-val brg-v-cyan">{{ money(formatCompact(fleetData.total_liquid_balance)) }}</span>
                  <span class="brg-stat-lbl">{{ t('bridge.fleet.liquid', 'LIQUID') }} {{ fleetCurrency }}</span>
                </div>
                <div class="brg-stat" :title="`${formatNumber(fleetData.total_staked_balance)} ${fleetCurrency}`">
                  <span class="brg-stat-val brg-v-blue">{{ money(formatCompact(fleetData.total_staked_balance)) }}</span>
                  <span class="brg-stat-lbl">{{ t('bridge.fleet.staked', 'LOCKED') }}</span>
                </div>
                <div class="brg-stat" :title="`${formatNumber(fleetData.total_balance)} ${fleetCurrency}`">
                  <span class="brg-stat-val brg-v-green">{{ money(formatCompact(fleetData.total_balance)) }}</span>
                  <span class="brg-stat-lbl">{{ t('bridge.fleet.total', 'TOTAL') }}</span>
                </div>
                <div class="brg-stat" :title="t('bridge.fleet.markHelp', 'Earned-mark tier, from verified work')">
                  <span class="brg-stat-val brg-v-gold">{{ fleetMarkTier }}</span>
                  <span class="brg-stat-lbl">{{ t('bridge.fleet.mark', 'EARNED MARK') }}</span>
                </div>
              </div>

              <div v-if="achievementCount > 0" class="brg-ach">
                <span class="brg-ach-badge">{{ achievementCount }}/{{ achievementTotal }} {{ t('bridge.fleet.achievements', 'achievements') }}</span>
                <span class="brg-ach-avt">{{ money(formatCompact(achievementAvt)) }} {{ fleetCurrency }}</span>
                <button
                  v-if="achievementPending > 0"
                  type="button" class="brg-ach-claim"
                  :disabled="claimingAchievements"
                  @click="claimAchievements"
                >{{ claimingAchievements ? t('common.loading', 'Working') : `${t('bridge.fleet.claim', 'CLAIM')} ${achievementPending}` }}</button>
              </div>
            </template>

            <div v-else-if="fleetCardMode === 'fleet'" class="brg-cta">
              <p class="brg-cta-text">{{ t('bridge.fleet.empty', 'No agents yet. Create one and it becomes a star on this map, with everything it does landing here as it happens.') }}</p>
              <button type="button" class="brg-cta-btn" data-tour="mc-create-agent" @click="uiStore.openQuickAgentModal()">
                {{ t('bridge.fleet.create', 'CREATE YOUR WALLET AGENT') }}
              </button>
            </div>
          </section>

          <BridgeFleetLog v-show="railLeftShown" class="brg-grow" :agent-names="fleetAgentNames" :has-fleet="fleetAgentCount > 0" :following="followingDid" :selected="selectedDid"
                          @select="onSelect" @follow="onFollow" />
        </aside>

        <!-- CENTER: the stage shows through — or, with no stage, the board
             stands in its place. Same column, same modals over it. -->
        <div class="brg-center">
          <!-- Measured, not felt: this appears only when the stage's OWN draw
               timer says it is over budget across a real sample, and saying no
               once ends the conversation. -->
          <div v-if="gfxOffer" class="brg-gfxoffer" data-testid="gfx-offer" role="status">
            <Icon name="mdi:timer-sand" :size="13" />
            <span class="brg-gfxoffer-t">{{ gfxOfferText }}</span>
            <button type="button" class="brg-door-sm is-on" data-testid="gfx-offer-accept"
                    @click="setGfx('lite')">{{ t('bridge.gfx.offerYes', 'USE THE LIGHT BRIDGE') }}</button>
            <button type="button" class="brg-door-sm" data-testid="gfx-offer-dismiss"
                    @click="dismissGfxOffer">{{ t('bridge.gfx.offerNo', 'NO, KEEP THE STAGE') }}</button>
          </div>
          <BridgeBoard v-if="gfxMode === 'lite'"
                       class="brg-board"
                       :registries="boardRegistries"
                       :mine-by-key="boardMine"
                       :index="boardIx"
                       :tick="boardTick"
                       :focus-key="boardFocusKey"
                       :reason="gfxRes.reason"
                       :automatic="gfxRes.automatic"
                       :window-ms="activityWindowMs"
                       @focus="(k) => (boardFocusKey = k)" />
    <!-- §BOOTSEQ — the boot screen. Deliberately NOT AgentWorld's pattern:
               that one prints two fixed lines ("INITIALIZING AGENTWORLD" /
               "Resolving network topology…") no matter what is happening, which looks
               like progress and reports nothing. Every line here is a real step with
               a real state, and the same records drive the battery. -->
          <!-- ONE element, TWO meanings: the boot screen, and the same log
               reopened afterwards from the BOOT button. Nothing distinguished
               them, so a gate asking "did the boot screen come back?" could not
               tell a regression from a battery that had clicked BOOT itself —
               and duly reported one. `data-mode` is the difference, stated. -->
          <div v-if="bootVisible || bootLogOpen" class="brg-boot" data-testid="boot-screen"
               :data-mode="bootVisible ? 'boot' : 'log'">
            <div class="brg-boot-card">
              <div class="brg-boot-hd">
                <span class="brg-boot-title">{{ t('bridge.boot.title', 'BRINGING UP THE BRIDGE') }}</span>
                <span class="brg-boot-sum au-mono" data-testid="boot-summary">{{ bootSummaryLine }}</span>
              </div>
              <div class="brg-boot-bar"><i :style="{ width: bootProgress.total ? (bootProgress.settled / bootProgress.total * 100) + '%' : '0%' }" /></div>
              <ul class="brg-boot-log" data-testid="boot-log">
                <li v-for="r in bootRecords" :key="r.id" :class="['brg-boot-row', 'is-' + r.state]" :data-testid="`boot-step-${r.id}`">
                  <span class="brg-boot-gl" aria-hidden="true">{{
                    r.state === 'ok' ? '✓' : r.state === 'failed' ? '✕' : r.state === 'skipped' ? '–' : r.state === 'running' ? '◐' : '·' }}</span>
                  <span class="brg-boot-lb">{{ r.label }}</span>
                  <span v-if="!r.required" class="brg-boot-tag">{{ t('bridge.boot.streams', 'streams in') }}</span>
                  <span class="brg-boot-dt au-mono">{{ r.error || r.detail || '' }}</span>
                  <button v-if="r.state === 'failed' || r.state === 'skipped'" type="button"
                          class="brg-boot-retry" :data-testid="`boot-retry-${r.id}`"
                          @click="retryBootStep(r.id)">{{ t('bridge.boot.retry', 'RETRY') }}</button>
                </li>
              </ul>
              <p class="brg-boot-note">
                {{ bootReady
                  ? t('bridge.boot.readyNote', 'The bridge is usable. The rest is still streaming in and will appear as it lands.')
                  : t('bridge.boot.waitNote', 'Waiting only on the small things the view cannot be honest without.') }}
              </p>
              <div class="brg-boot-actions">
                <button type="button" class="brg-door-sm" data-testid="boot-dismiss"
                        @click="bootDismissed = true; bootLogOpen = false">
                  {{ bootReady ? t('bridge.boot.enter', 'ENTER') : t('bridge.boot.anyway', 'CONTINUE ANYWAY') }}
                </button>
              </div>
            </div>
          </div>

          <!-- §BRIDGE R11 #2 — MAP MUST NOT BE A ONE-WAY DOOR.
               Measured 2026-08-19 before touching anything: after MAP the two
               10px hairlines ARE present and ARE hit-testable (a scripted click
               on one restores the panels), so this was never unreachable — it
               was UNDISCOVERABLE. The button that put you here (`door-map`)
               lives inside the panel it hides, and the only way back was a
               strip at 16% opacity floating mid-canvas with no label.
               The control that creates a state now survives that state. -->
          <button v-if="stageFocus" type="button" class="brg-focus-exit"
                  data-testid="focus-exit"
                  :title="t('bridge.focus.exitHelp', 'Bring the panels back (Esc also works)')"
                  @click="stageFocus = false">
            <span class="brg-focus-exit-dot" aria-hidden="true"></span>
            {{ t('bridge.focus.exit', 'PANELS HIDDEN \u2014 CLICK OR PRESS ESC TO RESTORE') }}
          </button>

          <!-- §BRIDGE R14.5 — the readout he can screenshot. Renders ONLY behind
               `?bridgedebug=1`; on every normal load this component mounts,
               reads location.search, and draws nothing. It sits in the stage
               column so it can never cover the live ledger. -->
          <BridgePerfHud />
        </div>

        <!-- RIGHT: the network -->
        <aside class="brg-rail brg-rail-r" :class="{ 'is-closed': !railRightShown }" data-tour="mc-vitals">
          <button type="button" class="brg-railtab brg-railtab-r"
                  :aria-expanded="railRightOpen ? 'true' : 'false'"
                  :title="railRightOpen ? t('bridge.rail.hide', 'Hide this panel') : t('bridge.rail.show', 'Show this panel')"
                  @click="stageFocus ? (stageFocus = false) : (railRightOpen = !railRightOpen)">
            <span class="brg-railtab-mark">{{ railRightOpen ? '\u203a' : '\u2039' }}</span>
          </button>
          <section v-show="railRightShown" class="brg-card brg-vitals">
            <header class="brg-card-hdr">
              <span class="brg-card-title">{{ t('bridge.vitals.title', 'NETWORK') }}</span>
              <span class="brg-card-sub" :class="spineHealthClass">{{ spineHealthLabel }}</span>
            </header>

            <div class="brg-vit-row">
              <span class="brg-vit-k">{{ t('bridge.vitals.registries', 'REGISTRIES') }}</span>
              <span class="brg-vit-v">{{ scoredPending > 0 && scoredHealthy === 0 ? '--' : scoredHealthy }}/{{ scoredTotal }}</span>
            </div>
            <div class="brg-vit-row">
              <span class="brg-vit-k">{{ t('bridge.vitals.supply', 'SUPPLY') }}</span>
              <span class="brg-vit-v" :title="formatNumber(totalSupply)">{{ formatCompact(totalSupply) }}</span>
            </div>
            <div class="brg-vit-row">
              <span class="brg-vit-k">{{ t('bridge.vitals.agents', 'AGENTS') }}</span>
              <span class="brg-vit-v">{{ uniqueAgents.toLocaleString(appLocale()) }}</span>
            </div>
            <div class="brg-vit-row">
              <span class="brg-vit-k">{{ t('bridge.vitals.events', 'EVENTS') }}</span>
              <span class="brg-vit-v" :title="`${Number(totalEvents).toLocaleString(appLocale())} events in the ledger`">{{ formatCompact(totalEvents) }}</span>
            </div>
            <div class="brg-vit-row">
              <span class="brg-vit-k">{{ t('bridge.vitals.latency', 'LATENCY') }}</span>
              <span class="brg-vit-v">{{ hwAvgResponseTime }}ms</span>
            </div>

            <!-- The sandbox tier is off by design and is NEVER counted as a failure. -->
            <p v-if="sandboxTotal > 0" class="brg-vit-note"
               :title="t('bridge.vitals.sandboxHelp', 'The sandbox tier is off by default by design, so it is excluded from the health score.')">
              {{ sandboxTotal }} {{ t('bridge.vitals.sandboxOff', 'sandbox probes excluded (off by design)') }}
            </p>

            <!-- §BRIDGE R8 — QUICK ACTIONS. His words: "make the most important
                 actions quick actionable from this view. so it displays a modal or
                 something. modals already exist. could be reused from the views."
                 They act on the agent you are FOLLOWING, so the thing you are
                 watching and the thing you are about to move money to are the same
                 thing. Existing modals, existing rails, nothing new. -->
            <BridgeQuickActions
              data-tour="mc-quick-actions"
              :target-did="selectedDid"
              :target-name="selectedDid ? (fleetAgentNames[selectedDid] || null) : null"
              :owned-dids="fleetDids"
              :currency="actionCurrency"
            
              @open-lane="(l) => openTerminal(l as TerminalLane)"
            />

            <div class="brg-vit-doors" data-tour="mc-doors">
              <!-- §BRIDGE R3 — these are no longer doors. "this is mission control.
                   from here you should be able to see all the things your agents
                   do." MAP clears the rails so you can see the stage you are
                   already looking at; the other three open the in-view terminal,
                   which keeps a FULL VIEW link for everything it does not carry. -->
              <button type="button" class="brg-door-sm" :class="{ 'is-on': replaying }"
                      data-testid="door-replay"
                      :title="t('bridge.doors.replayHelp', 'Replay what this session has seen. A live stream has no past, so this can only replay what it witnessed.')"
                      @click="toggleReplay">{{ t('bridge.doors.replay', 'REPLAY') }}</button>
              <!-- §ACTIVITY — "show only active agents in the last 10-15 minutes
                   or set a timeframe yourself, so the inactive agents disappear
                   and reappear based on activity."
                   It filters what the stage DRAWS; it never invents a star, and
                   the caption states how much of the window it has watched. -->
              <button type="button" class="brg-door-sm" data-testid="boot-log-open"
                      :class="{ 'is-warn': bootRecords.some(r => r.state === 'failed') }"
                      :title="t('bridge.boot.logHelp', 'What loaded, what did not, and why')"
                      @click="bootLogOpen = true">{{ t('bridge.boot.log', 'BOOT') }}</button>
              <span class="brg-actwin" data-testid="activity-window">
                <span class="brg-actwin-k">{{ t('bridge.activity.label', 'ACTIVE') }}</span>
                <button v-for="w in ACTIVITY_WINDOWS" :key="w.ms"
                        type="button" class="brg-door-sm brg-actwin-b"
                        :class="{ 'is-on': activityWindowMs === w.ms }"
                        :data-testid="`activity-${w.label}`"
                        :title="gfxMode === 'full'
                          ? t('bridge.activity.help', 'Draw only agents seen acting inside this window. Counts what THIS session watched — a page just opened cannot see a whole hour.')
                          : t('bridge.activity.helpLite', 'List only registries seen acting inside this window; your home registry is always listed. Counts what THIS session watched — a page just opened cannot see a whole hour.')"
                        @click="setActivityWindow(w.ms)">{{ w.label }}</button>
                <input v-model="activityCustomMin" type="number" min="1" max="1440"
                       class="brg-actwin-in" data-testid="activity-custom"
                       :placeholder="t('bridge.activity.min', 'min')"
                       :title="t('bridge.activity.customHelp', 'Your own window, in minutes')"
                       @keyup.enter="applyCustomActivityWindow" />
                <button v-if="activityWindowMs" type="button" class="brg-door-sm brg-actwin-b"
                        data-testid="activity-off"
                        :title="t('bridge.activity.offHelp', 'Show every agent again')"
                        @click="activityWindowMs = null">{{ t('bridge.activity.off', 'ALL') }}</button>
              </span>
              <!-- §STAGENOTE (Commander 2026-08-21): "the description makes the
                   active gui part with the minute selector unaligned. its the
                   text it needs a better framework to fit without rearranging
                   the gui all the time."
                   It did: the caption was a FLEX SIBLING of the ACTIVE buttons
                   and the `min` input, with no shrink guard, so a longer string
                   wrapped to three lines, grew the row and dragged the spinner
                   out of line. It now owns a full-width slot of RESERVED height
                   that clips instead of wrapping — any caption, any length,
                   identical geometry, and it can never move a control again. -->
              <span class="brg-stagenote" data-testid="stage-note"
                    :title="activityCaption ? activityCaption : (orbitNote ? orbitTitle : '')">
                <template v-if="activityCaption"><span data-testid="activity-note">{{ activityCaption }}</span></template>
                <template v-else-if="orbitNote"><span data-testid="orbit-note">{{ orbitNote }}</span></template>
              </span>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': stageFocus }"
                      data-testid="door-map"
                      :title="t('bridge.doors.mapHelp', 'Clear the panels and look at the map you are already on')"
                      @click="toggleStageFocus">{{ t('bridge.doors.map', 'MAP') }}</button>
              <!-- §BRIDGE R12 — "contracts quick view modals maybe settlements
                   and guild work of your agents". ONE door, three tabs, all of
                   it scoped to the agent you are ACTING AS, every list off the
                   rail the full page already uses. -->
              <button type="button" class="brg-door-sm brg-door-attn"
                      :class="{ 'is-on': attentionOpen, 'has-items': (attentionCount || 0) > 0 }"
                      data-testid="door-attention"
                      :title="t('bridge.doors.attnHelp', 'What is waiting on your decision right now')"
                      @click="attentionOpen = true">
                {{ t('bridge.doors.attn', 'NEEDS YOU') }}
                <span v-if="(attentionCount || 0) > 0" class="brg-attn-badge">{{ attentionCount }}</span>
              </button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': workOpen }"
                      data-testid="door-work"
                      :title="t('bridge.doors.workHelp', 'Your contracts, guild work and disputes, for the agent you are acting as')"
                      @click="workOpen = true">{{ t('bridge.doors.work', 'WORK') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'discovery' }"
                      data-testid="door-discovery"
                      @click="openTerminal('discovery')">{{ t('bridge.doors.discovery', 'DISCOVERY') }}</button>
              <!-- a door opens only where the room is there: the lock lane only where staking_enabled is true -->
              <button v-if="brgStakingOn" type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'staking' }"
                      data-testid="door-staking"
                      @click="openTerminal('staking')">{{ t('bridge.doors.staking', 'LOCKS') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'senate' }"
                      data-testid="door-senate"
                      :title="t('bridge.doors.senateHelp', 'Open proposals, and vote as the agent you are acting as')"
                      @click="openTerminal('senate')">{{ t('bridge.doors.senate', 'SENATE') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'guild' }"
                      data-testid="door-guild"
                      :title="t('bridge.doors.guildHelp', 'Open work you can bid on, and post work of your own')"
                      @click="openTerminal('guild')">{{ t('bridge.doors.guild', 'GUILD') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'exchange' }"
                      data-testid="door-exchange"
                      @click="openTerminal('exchange')">{{ t('bridge.doors.exchange', 'AGORA') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'ourstate' }"
                      data-testid="door-ourstate"
                      :title="t('bridge.doors.ourstateHelp', 'Your threads — the same OurChat, docked in view')"
                      @click="openTerminal('ourstate')">{{ t('bridge.doors.ourstate', 'OURSTATE') }}</button>
              <button type="button" class="brg-door-sm" :class="{ 'is-on': terminalLane === 'assistant' }"
                      data-testid="door-assistant"
                      :title="t('bridge.doors.assistantHelp', 'Ask or command — grammar, your Claude bridge, or your own API key')"
                      @click="openTerminal('assistant')">{{ t('bridge.doors.assistant', 'ASSISTANT') }}</button>
            </div>
          </section>

          <BridgeLedger v-show="railRightShown" class="brg-grow" :can-open-forensics="authStore.isAdmin" :mine-dids="focusedFleetDids" :scope-note="boardFocusNote || fleetScopeNote" />
        </aside>
      </div>

      <BridgeTerminal :lane="terminalLane" :currency="fleetCurrency" @close="terminalLane = null" />
      <BridgeWorkView :show="workOpen" :initial-tab="workLane" @close="workOpen = false" />

      <!-- Always mounted, panel only when open: the badge has to be able to
           tell you something BEFORE you think to click. -->
      <BridgeAttention ref="attentionRef" :show="attentionOpen"
                       @close="attentionOpen = false"
                       @count="(n) => attentionCount = n"
                       @open-work="(tab?: 'contracts' | 'guild' | 'disputes') => { workLane = tab; workOpen = true }"
                       @open-lane="(l) => openTerminal(l as TerminalLane)" />

      <!-- PULSE BAR: the last hour of the network's heartbeat, session-honest. -->
      <BridgePulse />
    </div>
  </div>
</template>

<script setup lang="ts">
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import ExchangeTicker from '@/components/exchange/ExchangeTicker.vue'
// §BRIDGE 2026-08-18 — Mission Control became THE BRIDGE. The stage is the real
// federation starmap fed by real ledger events; these three components are the
// only new surfaces, and each composes rails this view already loaded.
import BridgeStage from '@/components/bridge/BridgeStage.vue'
import BridgeFleetLog from '@/components/bridge/BridgeFleetLog.vue'
import BridgeWorkView from '@/components/bridge/BridgeWorkView.vue'
import BridgeAttention from '@/components/bridge/BridgeAttention.vue'
import { usePrivacy } from '@/composables/usePrivacy'
import { compactFromSummary, earnedMarks, type TrackRecordCompact } from '@/services/api/trackRecord'
import { didOrNull } from '@/services/bridge/identity'
import { useCommandSessions } from '@/stores/commandSessions'
import { peerGet } from '@/services/api/peer'
import { directGet } from '@/services/api/peerDirect'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import {
  createActivityIndex, noteActivity, activeDids, activityNote,
  ACTIVITY_WINDOWS, windowFromMinutes,
} from '@/services/bridge/activity'
import { partiesOfEnvelope } from '@/services/bridge/grammar'
import {
  BootSequencer, bootSummary, isSettled, type BootRecord,
  bootAlreadyShown, markBootShown,
} from '@/services/bridge/boot'
import { buildStarPlan } from '@/services/bridge/ownedHomes'
import {
  resolveGfx, readCaps, loadGfxPref, saveGfxPref, shouldOfferLite, offerText,
  GFX_OFFER_DISMISSED_KEY, type GfxPref, type GfxCaps,
} from '@/services/bridge/graphics'
import { createBoardIndex, noteBoardActivity, type BoardRegistry } from '@/services/bridge/board'
import BridgeBoard from '@/components/bridge/BridgeBoard.vue'
import { getRegistryDirectoryOrPublic, type RegistryDirectory } from '@/services/api/command'
import BridgeQuickActions from '@/components/bridge/BridgeQuickActions.vue'
import BridgeLedger from '@/components/bridge/BridgeLedger.vue'
import BridgePulse from '@/components/bridge/BridgePulse.vue'
import BridgePerfHud from '@/components/bridge/BridgePerfHud.vue'
import BridgeTerminal, { type TerminalLane } from '@/components/bridge/BridgeTerminal.vue'
import { useLedgerStream } from '@/composables/useLedgerStream'
/**
 * MissionControl.vue — OWL21 v3: Browser-Side Health Probes
 * 
 * Same approach as Health Monitor: ping endpoints FROM THE BROWSER and measure
 * response times with performance.now(). No stale DB data, no admin auth,
 * no backend self-requests. Real-time, live measurements on every refresh.
 *
 * 5 parallel probe endpoints (all public, no auth):
 *   GET /health                          → Registry ping
 *   GET /api/v1/federation/health-check  → Federation
 *   GET /api/v1/agent-cards              → Agents + DB
 *   GET /api/v1/metrics/network-health   → Metrics service
 *   GET /api/v1/teg/transactions/analytics → TEG + Event Store
 *
 * All fire in parallel → total wall-clock ~100-200ms.
 * Health score = % of probes healthy, with latency penalties.
 * Service Health Matrix = real response times per service.
 * Auto-refresh re-runs probes every cycle → live data always.
 */
import { ref, computed, watch, onMounted, onUnmounted, reactive, nextTick } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { esStatsUrl } from '@/config/frames'  // §2026-06-14 per-frame currency; §BRIDGE R7-B ES URLs from the ONE source
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { useTegStore } from '@/stores/teg'
import { useStakingStore } from '@/stores/staking'
import { useI18n } from '@/composables/useI18n'
import { useFederationStore } from '@/stores/federation'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import { useLogger } from '@/composables/useLogger'
import { useCurrency } from '@/composables/useCurrency'
import { useActingContext } from '@/composables/useActingContext'

const log = useLogger('MissionControl')

// Stores
const authStore = useAuthStore()
const cmdSessions = useCommandSessions()

/**
 * §FOREIGNDEV — a developer-scoped read on a foreign registry.
 *
 * A session's token is only valid at the registry that minted it, so the call goes there: the token and the address
 * move together (the admin relay that once carried these reads is gone, §FEFRAME W4).
 *
 * ONE helper rather than a branch at each call site — two sites asking the same
 * question two ways is exactly the §FANOUTFIX class.
 */
async function foreignGet<T = any>(k: string, path: string, tok: string, params?: Record<string, any>): Promise<T> {
  const s: any = cmdSessions.sessionFor(k)
  if (s?.via === 'direct' && s.baseUrl) return directGet<T>(s.baseUrl, path, tok, params)
  return peerGet<T>(k, path, tok, params)
}
const agentStore = useAgentStore()
const tegStore = useTegStore()
const stakingStore = useStakingStore()
const { t } = useI18n()
// FX multi-currency (2026-06-03): "Your Fleet" balances are in the LOCAL frame's
// settlement currency — AVT on Frame A/B, BVT on Frame C. Was hardcoded "AVT".
const { localCurrency } = useCurrency()
const { actingCurrencyLabel, isForeign: actingIsForeign } = useActingContext()
/**
 * §ORGPOCKET O4 (2026-08-28) — the label on the fleet aggregate now comes from
 * the SAME response as the number.
 *
 * What was actually measured, before changing anything: `fleetData` is filled
 * from `GET /developers/me/teg-summary`, whose handler sums THIS registry's
 * `agents` rows where `creator_developer_id = me`. One registry, one settlement
 * currency — so there is no live cross-currency total anywhere in this view, and
 * the old `localCurrency` label was not wrong. (EigenTrustCommand's registry
 * total is the one place that genuinely spans frames, and §17.3 already makes it
 * filter by currency before adding.)
 *
 * The reason to change it anyway is that "correct by accident" is one widening
 * away from "confidently wrong": the day that endpoint learns to aggregate
 * across frames, a viewer-derived label would silently start describing a mixed
 * sum with one unit. The response now declares the currency it summed in, and
 * this reads it. Falling back to the local currency is not a guess — it is the
 * same fact from a second source for a registry that has not shipped the field.
 */
const fleetCurrency = computed(() => String(fleetData.value?.currency || localCurrency.value))
/**
 * §FOREIGNACT (2026-08-24) — the label on an ACTION follows the acting agent,
 * not the page. `fleetCurrency` stays the viewer's own for the fleet aggregates
 * (a local-fleet view), but the quick actions MOVE MONEY as whichever agent is
 * selected, and the api client already sends those calls to that agent's home
 * registry. This is where the Commander's misread was inherited from: the
 * desktop bridge labelled a foreign agent's spend in the viewer's currency, and
 * Pocket copied the pattern. Empty while a foreign registry's card is still
 * loading — never the wrong unit.
 */
const actionCurrency = computed(() =>
  actingIsForeign.value ? actingCurrencyLabel.value : fleetCurrency.value)
const federationStore = useFederationStore()
const uiStore = useUIStore()

// State
const selectedPeriod = ref('24h')
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null

// ─── LIVE INFRASTRUCTURE HEALTH (11-service hw tile system) ────────────
interface ServiceStatus {
  name: string; port: number; url: string
  status: 'pending' | 'healthy' | 'down'; ms: number | null; failCount: number
  // §pass62.9 (2026-05-22) — publicUrl carried through from /stack-health response
  // so operator tiles can become clickable hyperlinks (mirrors LandingPage pattern).
  publicUrl?: string | null
}

// Core services — populated from backend /stack-health response.
// On mainframe: 9 services (Registry A, TEG, EventStore, OPA, 5 sandbox).
// On operators: 2 services (Registry, TEG Layer) — detected via /public/registry-config.
const mainframeCoreServiceDefs = [
  { name: 'Registry A',    port: 8000, path: '/health', group: 'core' },
  { name: 'TEG Layer A',   port: 8100, path: '/health', group: 'core' },
  { name: 'Event Store',   port: 8200, path: '/health', group: 'core' },
  { name: 'OPA Engine',    port: 8288, path: '/health', group: 'core' },
]
const operatorCoreServiceDefs = [
  { name: 'Registry',  port: 8000, path: '/health', group: 'core' },
  { name: 'TEG Layer', port: 8080, path: '/health', group: 'core' },
]
const mcIsFederatedOperator = ref(false)
// FX strip visibility — durable, from /public/registry-config fx_enabled (FX_ENABLED env).
const mcFxEnabled = ref(false)

// §2026-07-29 — a STANDALONE sovereign frame (own EventStore, no FX triangle, not an operator)
// has no Frame B/C to stream. It rendered the A/B/C panes anyway, so its OWN ledger sat under
// the label "Frame A" while two permanently empty panes claimed to be B and C.
// The discriminator is LIVE CONFIG, never a name match: fx_enabled is true on all three prod
// mainframes AND on all 13 cloud operators (asserted against all 16 nodes before shipping),
// so this is a no-op everywhere except a frame that genuinely stands alone.
const mcRegistryName = ref('')
// §HETZNERLOCK-16 — driven by registry-config.multi_frame (is a Frame B/C EventStore
// even configured here?), NOT by fx_enabled + the operator flag. That old pair could
// never be true for an operator, so an op under a STANDALONE frame still rendered the
// cluster's three panes and streamed its ledgers. A cloud-op has no EventStore of its
// own — it writes to its PARENT frame's — so its single pane is that frame's ledger.
const mcMultiFrame = ref(true)   // assume multi until config answers (no pane flash)
const mcSingleFrame = computed(() => !mcMultiFrame.value)

// The EventStore returns total_events = -1 when the count is not materialised (a sentinel, not
// a measurement). Rendering "-1 events" on a fresh frame reads as broken, so fall back to the
// sum of the per-type counts, which is the honest number for a young ledger. Never fires on a
// frame that reports a real total.

// Operator services are loaded DYNAMICALLY from the backend stack-health response.
// No hardcoded operator list — new operators appear automatically when added as peers.

// §2026-06-03 — FORCED false: the localhost branch built direct cross-origin URLs to
// EventStore ports (:8200/:8201/:8206 /projections/stats + /ws/events) and raw service
// ports, which the browser CORS-blocks (registry origin ≠ ES origin) — the console-error
// storm seen on the post-login dashboard. The same-origin registry proxies
// (/api/v1/public/eventstore-stats{,-b,-c}, /ws/events{,-b,-c}, /api/v1/stack-health)
// exist and degrade gracefully, so we ALWAYS use them. Sandbox is reached via localhost
// too, so host-sniffing was the wrong signal.
const mcIsLocalDev = false

function buildServiceRefs(defs: typeof mainframeCoreServiceDefs): ServiceStatus[] {
  return defs.map(d => ({
    name: d.name, port: d.port,
    url: mcIsLocalDev
      ? `${window.location.protocol}//${window.location.hostname}:${d.port}${d.path}`
      : `${window.location.origin}${d.path}`,
    status: 'pending', ms: null, failCount: 0,
  }))
}

const hwCoreServices = ref<ServiceStatus[]>(buildServiceRefs(mainframeCoreServiceDefs))
const hwOperatorServices = ref<ServiceStatus[]>([])
const hwServices = computed<ServiceStatus[]>(() => [...hwCoreServices.value, ...hwOperatorServices.value])

const hwLastCheckTime = ref<Date | null>(null)

const hwAvgResponseTime = computed(() => {
  const w = hwServices.value.filter(s => s.ms !== null)
  return w.length ? Math.round(w.reduce((a, s) => a + (s.ms || 0), 0) / w.length) : 0
})


async function checkHwService(svc: ServiceStatus) {
  const start = performance.now()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 4000)
  let reachable = false; let measuredMs: number | null = null
  try {
    const res = await fetch(svc.url, { mode: 'cors', signal: controller.signal, cache: 'no-store' })
    clearTimeout(timeout); measuredMs = Math.round(performance.now() - start); reachable = res.ok
  } catch {
    clearTimeout(timeout)
    const start2 = performance.now()
    const c2 = new AbortController(); const t2 = setTimeout(() => c2.abort(), 4000)
    try {
      await fetch(svc.url, { mode: 'no-cors', signal: c2.signal, cache: 'no-store' })
      clearTimeout(t2); measuredMs = Math.round(performance.now() - start2); reachable = true
    } catch { clearTimeout(t2); reachable = false }
  }
  if (reachable) {
    svc.ms = measuredMs; svc.failCount = 0; svc.status = 'healthy'
  } else {
    svc.failCount = (svc.failCount || 0) + 1
    if (svc.failCount >= 2) { svc.ms = null; svc.status = 'down' }
  }
}

async function runHealthProbes() {
  if (!mcIsLocalDev) {
    // Production: use backend proxy that probes internal services
    try {
      const res = await fetch(`${window.location.origin}/api/v1/stack-health`, { cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        // Build operator services dynamically from backend response
        const opProbes = (data.services || []).filter((p: any) => p.group === 'operator')
        hwOperatorServices.value = opProbes.map((p: any) => ({
          name: p.name, port: 0, url: '',
          status: p.status === 'healthy' ? 'healthy' : 'down',
          ms: p.ms, failCount: p.status === 'healthy' ? 0 : 1,
          // §pass62.9 (2026-05-22) — carry through publicUrl for hyperlink rendering
          publicUrl: p.publicUrl ?? null,
        } as ServiceStatus))

        // §pass62.9 (2026-05-22) — REPLACE hwCoreServices from backend response.
        // Previously we only UPDATED rows where backend name matched a hardcoded
        // mainframe service def — that worked for Frame A but Frame B's backend
        // returns "Frame B Registry"/"Frame B TEG"/etc. which don't match the
        // hardcoded "Registry A"/"TEG Layer A"/etc. defs → tiles stuck pending.
        // Treat the backend as source-of-truth for the core service list.
        const coreProbes = (data.services || []).filter((p: any) => p.group === 'core')
        hwCoreServices.value = coreProbes.map((p: any) => ({
          name: p.name, port: 0, url: '',
          status: p.status === 'healthy' ? 'healthy' : 'down',
          ms: p.ms, failCount: p.status === 'healthy' ? 0 : 1,
          publicUrl: p.publicUrl ?? null,
        } as ServiceStatus))
        hwLastCheckTime.value = new Date()
        return
      }
    } catch { /* fall through to per-service checks */ }
  }
  const allServices = [...hwCoreServices.value, ...hwOperatorServices.value]
  await Promise.allSettled(allServices.map(s => checkHwService(s)))
  hwLastCheckTime.value = new Date()
}

// Analytics state
const analyticsData = ref<any>(null)
const analyticsLoading = ref(false)

// ─── NEW: Fleet, Pulse, Senate, Trust ────────────────────────
const fleetData = ref<any>({ agent_count: 0, total_liquid_balance: 0, total_staked_balance: 0, total_balance: 0, aggregate_reputation_score: 0, treasury_balance: 0 })
const achievementCount = ref(0)
const achievementTotal = ref(0)
const achievementAvt = ref(0)
// §FEPARITY-2 — pending payout claim (backend rail existed with no FE caller)
const achievementPending = ref(0)
const claimingAchievements = ref(false)
async function claimAchievements() {
  if (claimingAchievements.value) return
  const agents = agentStore.agents || []
  const target = agents.find((a: any) => a.status === 'active' && a.did) || agents.find((a: any) => a.did)
  if (!target?.did) {
    uiStore.showError('No payout target', 'Create or activate an agent first: achievement payouts go to an agent wallet.')
    return
  }
  claimingAchievements.value = true
  try {
    const res = await apiClient.post('/achievements/claim-pending', { agent_did: target.did })
    const d = res.data || {}
    uiStore.showSuccess('Achievements claimed', `${d.claimed ?? 0} payout${(d.claimed ?? 0) === 1 ? '' : 's'} → ${target.name || target.did.slice(0, 18)}`)
    await fetchFleetData()   // refresh pending count + TEG summary
  } catch (e: any) {
    uiStore.showError('Claim failed', e?.response?.data?.detail || 'request failed')
  } finally {
    claimingAchievements.value = false
  }
}
const senateProposals = ref<any[]>([])
const apyTiers = ref<{ lock: number; apy: string }[]>([])
const topAgents = ref<{ did: string; name: string; score: number }[]>([])
const fedPeers = ref(0)

// ─── AUTH ────────────────────────────────────────────────────
const isAdmin = computed(() => authStore.user?.role === 'admin' || authStore.user?.is_admin === true)

// ─── CONNECTION STATUS ───────────────────────────────────────

// ─── FEDERATION ──────────────────────────────────────────────

// ─── SYSTEM HEALTH (from hw 11-service probes) ───────────────



// healthComponents not needed — replaced by hw-tiles in template

// ─── RESOURCE METRICS — Admin only ──────────────────────────

// ─── ANALYTICS ───────────────────────────────────────────────
const totalSupply = computed(() => analyticsData.value?.summary?.total_supply || '0')
const totalEvents = computed(() => analyticsData.value?.summary?.total_events || 0)
const uniqueAgents = computed(() => analyticsData.value?.summary?.unique_agents || 0)

// ─── SOVEREIGN STATE bottom section ──────────────────────────
// Economy Pulse — 2x2 hero grid sourced from analyticsData.event_type_breakdown
// Adaptive senate: when empty, collapse to a slim status strip
// Lock tiers: max rate for bar scaling
// Top reputation: max score for bar scaling

// ─── SENATE proposal helpers — richer proposal cards (for/against split,
//     status pill, turnout + time-remaining). All derived from the already-
//     fetched senateProposals payload; no new requests. ────────────────────

// ─── AGENT METRICS ───────────────────────────────────────────

// ─── REPUTATION ──────────────────────────────────────────────

// ─── EVENT TYPE BREAKDOWN ────────────────────────────────────

// ─── SERVICE HEALTH MATRIX (from hw 11-service probes) ──────

// ─── HELPERS ─────────────────────────────────────────────────
function formatNumber(value: string | number | undefined): string {
  if (value === undefined || value === null) return '0.00'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '0.00'
  return num.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ─── DATA FETCHING ───────────────────────────────────────────
/*
 * §BOOTSEQ — the bridge boots as a declared SEQUENCE, not a race.
 *
 * What this replaces: four promises fired into Promise.allSettled, one of them
 * carrying `restoreReach().then(() => setTimeout(loadForeignFleets, 4000))` —
 * a guess about how long session restore takes. When the guess was wrong the
 * fan-out ran against a PARTIAL registry set and kept whatever landed first.
 * That is why the same page showed 2, then 5, then 9 registries on different
 * loads: nothing was broken, nothing was ordered either.
 *
 * `needs` replaces the delay. `inputSig` replaces the guesswork: if the
 * connected set moved while the fan-out was running, the sequencer runs it once
 * more against what is true NOW.
 *
 * REQUIRED steps are deliberately the SMALL ones. Blocking on the foreign
 * fan-out would punish exactly the account that has the most to load.
 */
const bootRecords = ref<BootRecord[]>([])
const bootReady = ref(false)
const bootDone = ref(false)
/*
 * The DATA may refresh on re-entry; the SCREEN must not.
 *
 * 🔴 MY OWN COMMENT HERE CLAIMED A BEHAVIOUR THE API DOES NOT HAVE. It said
 * "tab-scoped, so a real reload still shows it" — `sessionStorage` survives a
 * reload and only clears when the TAB closes, so the boot screen showed exactly
 * once, ever, and he reported precisely that: "somehow the boot sequence
 * doesnt show up anymore on reload".
 *
 * A module-scope flag is what "this page load" actually means: it dies with the
 * document (so F5 boots) and outlives a route change (so leaving the tab and
 * coming back does not re-run a bridge he is already using).
 */
const bootDismissed = ref(bootAlreadyShown())
watch(bootDismissed, (v) => { if (v) markBootShown() })
/** Reopen the log after dismissal — "what actually happened" must stay readable. */
const bootLogOpen = ref(false)
const bootSummaryLine = computed(() => bootSummary(bootRecords.value))
const bootProgress = computed(() => {
  const rs = bootRecords.value
  return { settled: rs.filter(r => isSettled(r.state)).length, total: rs.length }
})
/** The screen is up while required work is outstanding and he has not dismissed it. */
const bootVisible = computed(() => !bootDismissed.value && !bootReady.value && bootRecords.value.length > 0)
let sequencer: BootSequencer | null = null

function buildSequencer(): BootSequencer {
  const steps = [
    { id: 'agents', label: 'Your agents on this registry', required: true,
      run: async () => { await agentStore.fetchMyAgents(); return `${(agentStore.agents || []).length} agents` } },
    { id: 'fleetids', label: 'Fleet identity', required: true,
      // `fleetDids` is a computed ARRAY; reading `.size` on it returned
      // undefined and the log cheerfully printed "0 DIDs" next to a green tick.
      // Report what THIS step fetched, and say when the scope is partial.
      run: async () => {
        await loadFleetDids()
        const n = fleetDidsFull.value.length
        const state = fleetDidState.value
        return state === 'failed' ? 'could not read the fleet list'
          : `${n.toLocaleString(appLocale())} DIDs${state === 'partial' ? ' (partial — server capped it)' : ''}`
      } },
    { id: 'topology', label: 'Registry topology', required: true,
      /*
       * "its 3 direct peers probably (frames) but there is also a discovered
       * tier. which you probably didnt count" — he was right, and this line
       * was the §BOOTSEQ misreporting class a second time. `federationStore`
       * holds DIRECT peers only (3 on frame-c); the bridge draws 16, the rest
       * arriving through topology discovery. Count both, name both.
       */
      run: async () => {
        await federationStore.fetchRegistries()
        const direct = (federationStore.registries || []).length
        /*
         * §NONADMINBOARD — this was `getRegistryDirectory()` alone, and that
         * endpoint is ADMIN-GATED. For every non-admin it 403'd, the catch
         * wrote null, and the board this whole view is built around rendered
         * BLANK — while this very line printed a green tick with a peer count
         * beside it. Third time on this surface for that class.
         *
         * Report the SOURCE too: a narrower list must never read as a smaller
         * network, and "unavailable" must not read as "empty".
         */
        const dir = await getRegistryDirectoryOrPublic()
        registryDir.value = dir.directory
        dirSource.value = dir.source
        const known = dir.directory?.registries?.length || 0
        if (!known) return `${direct} direct peers · registry list unavailable`
        return dir.source === 'public'
          ? `${direct} direct peers · ${known} registries (public topology)`
          : `${direct} direct peers · ${known} registries in the directory`
      } },
    { id: 'reach', label: 'Sessions on other registries', required: false,
      run: async () => { await restoreReach(); return `${(cmdSessions.connectedKeys || []).length} connected` } },
    { id: 'foreign', label: 'Agents you own elsewhere', required: false, needs: ['reach'],
      // THE fix: the fan-out declares the set it consumes, so a session that
      // connects mid-run cannot leave the fleet frozen at a partial answer.
      inputSig: () => ((cmdSessions.connectedKeys || []) as string[]).slice().sort().join(','),
      run: async () => {
        await loadForeignFleets(true)
        return `${foreignRegistries.value.length} registries · ${foreignDids.value.length} agents`
      } },
  ]
  if (authStore.agentToken) {
    steps.push(
      { id: 'balance', label: 'Your balances', required: false, run: async () => { await tegStore.fetchBalance(); return 'ok' } } as any,
      { id: 'txs', label: 'Transaction history', required: false, run: async () => { await tegStore.fetchTransactionHistory(); return 'ok' } } as any,
      { id: 'staking', label: 'Locks', required: false, run: async () => { await stakingStore.fetchMyStakingStats(); return 'ok' } } as any,
    )
  }
  return new BootSequencer(steps as any, {
    onChange: (r) => {
      bootRecords.value = r
      bootReady.value = sequencer?.ready() ?? false
      bootDone.value = sequencer?.done() ?? false
    },
  })
}

async function fetchAllData() {
  try {
    sequencer = buildSequencer()
    bootRecords.value = sequencer.records()
    await sequencer.run()
    bootReady.value = sequencer.ready()
    bootDone.value = sequencer.done()
    if (bootReady.value) markBootShown()
  } catch (err) {
    // The sequencer isolates step failures, so reaching here means the boot
    // itself could not be constructed — say so instead of a blank stage.
    console.error('MissionControl boot:', err)
    uiStore.showError('Dashboard Error', 'The bridge could not start its load sequence. Please refresh.')
    bootReady.value = true
  }
}

/** Re-run one boot step from the log's retry control. */
async function retryBootStep(id: string) { await sequencer?.retry(id) }

async function fetchAnalytics() {
  analyticsLoading.value = true
  try {
    const response = await apiClient.get('/teg/transactions/analytics', { params: { period: selectedPeriod.value } })
    analyticsData.value = response.data
  } catch (err) {
    log.warn('Analytics:', err)
    uiStore.showWarning('Analytics Unavailable', 'Transaction analytics could not be loaded.')
  } finally { analyticsLoading.value = false }
}

/* §POCKETBRIDGE2 W7.1 — fetchResourceMetrics deleted: an uncalled orphan
   referencing state removed in the P4 cleanup (resourcesLoading/resourceData).
   Dead code that still LOOKS live is how half-features linger. */

function formatCompact(val: any): string {
  const num = typeof val === 'string' ? parseFloat(val) : (typeof val === 'number' ? val : 0)
  if (isNaN(num) || num === 0) return '0'
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M'
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K'
  return Math.round(num).toLocaleString(appLocale())
}

async function fetchFleetData() {
  try {
    const [tegRes, achRes, achCatRes] = await Promise.allSettled([
      apiClient.get('/developers/me/teg-summary'),
      apiClient.get('/achievements/me'),
      apiClient.get('/achievements/catalog'),
    ])
    if (tegRes.status === 'fulfilled') {
      fleetData.value = { ...fleetData.value, ...tegRes.value.data }
    }
    if (achRes.status === 'fulfilled') {
      achievementCount.value = achRes.value.data?.total || 0
      achievementAvt.value = achRes.value.data?.total_payout || 0
      achievementPending.value = achRes.value.data?.pending_count || 0   // §FEPARITY-2
    }
    if (achCatRes.status === 'fulfilled') {
      achievementTotal.value = achCatRes.value.data?.total || 0
    }
    // Treasury
    try {
      const tRes = await apiClient.get('/developers/me/teg-summary/treasury')
      fleetData.value.treasury_balance = tRes.data?.balance || 0
    } catch { /* expected */ }
  } catch { /* expected */ }
}

async function fetchSenateData() {
  try {
    const res = await apiClient.get('/governance/proposals', { params: { limit: 3 } })
    const items = res.data?.items || res.data || []
    senateProposals.value = (Array.isArray(items) ? items : []).slice(0, 3)
  } catch { /* expected */ }
}

async function fetchTrustData() {
  try {
    const [apyRes, repRes, fedRes] = await Promise.allSettled([
      apiClient.get('/staking/apy-tiers'),
      apiClient.get('/teg/reputation/rankings', { params: { limit: 5 } }),
      apiClient.get('/federation/network-stats'),
    ])
    if (apyRes.status === 'fulfilled') {
      const tiers = apyRes.value.data?.tiers || apyRes.value.data?.apy_tiers || apyRes.value.data || []
      apyTiers.value = (Array.isArray(tiers) ? tiers : []).map((t: any) => ({
        lock: t.lock_period || t.lockPeriod || t.lock_days || 0,
        apy: (t.apy || t.apy_percent || t.rate || 0).toFixed(1),
      })).filter((t: any) => t.lock > 0).slice(0, 4)
    }
    if (repRes.status === 'fulfilled') {
      const rankings = repRes.value.data?.rankings || []
      topAgents.value = rankings.slice(0, 5).map((r: any) => ({
        did: r.agent_did || r.agent_id || '',
        name: r.agent_name || r.name || '',
        score: r.reputation_score || r.score || 0,
      }))
    }
    if (fedRes.status === 'fulfilled') {
      fedPeers.value = fedRes.value.data?.activeRegistries || fedRes.value.data?.totalRegistries || 0
    }
  } catch { /* expected */ }
}



function setupAutoRefresh() {
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null }
  // Fixed 60s internal refresh — no UI selector needed
  autoRefreshTimer = setInterval(() => {
    runHealthProbes()
    fetchAllData()
    fetchAnalytics()
    mcFetchFxRate()
    // Re-poll the per-frame ledger stats — the WS only INCREMENTS the counter; if a
    // frame's snapshot was empty/slow/failed at mount or its socket never opened, this
    // HTTP backstop (which the WS give-up logic already assumes) re-fetches and self-heals.
    mcFetchStats()
  }, 60000)
}

// ─── MC LIVE EVENT TICKER (WS feed, same as LandingPage ef section) ──────────
interface McFeedEvent {
  id: string; time: string; rawTimestamp: string
  event_type: string
  did_short: string; color: string; fresh: boolean
  rawData?: any; rawId?: string; expanded?: boolean
}
interface McLedgerStats {
  total_events: number; unique_agents: number
  event_counts: Record<string, number>
}

// Init non-null so the live counter (mcLedgerStats.value.total_events++)
// ticks from event #1 instead of waiting for fetchStats() to resolve.
const mcLedgerStats = ref<McLedgerStats>({ total_events: 0, unique_agents: 0, event_counts: {} })
// §pass62.9 (2026-05-21) — start UN-paused so live events fill the feed
// immediately on mount. Previously defaulted true → mcAddEvent() early-exited
// at line 986 → mcEventFeed stayed empty → "AWAITING EVENTS" placeholder
// rendered forever even with active WS traffic. Mirrors EventLedgerLive.vue
// (LandingPage's variant) which defaults paused=false.
const mcPaused = ref(false)

// ── Live cross-currency FX bridge (2026-06-03): public sanitized /teg/fx/rate
// (rate only, no auth) drives the AVT⇄BVT bridge between the ledger streams so
// Frame C is unmistakably a different currency with a LIVE exchange rate. ──
const mcFxRate = ref<any>(null)
async function mcFetchFxRate() {
  try {
    // §2026-06-14 — all-pairs /fx/rates (the AVT/JDAY/BVT triangle); was single-pair /fx/rate.
    const r = await fetch(`${window.location.origin}/api/v1/teg/fx/rates`, { cache: 'no-store' })
    if (r.ok) mcFxRate.value = await r.json()
  } catch { /* bridge degrades silently */ }
}
// One "1 b = a_per_b a" readout per live cross-currency pair (e.g. 1 JDAY = 1.0085 AVT).

function mcTruncateDid(did: string): string {
  if (!did || did.length < 20) return did || '—'
  return did.substring(0, 10) + '…' + did.substring(did.length - 4)
}

function mcFormatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return '—' }
}

function mcDeepFind(obj: any, key: string, depth = 0): any {
  if (!obj || typeof obj !== 'object' || depth > 4) return undefined
  if (obj[key] !== undefined && obj[key] !== null && obj[key] !== '') return obj[key]
  for (const k of Object.keys(obj)) {
    if (typeof obj[k] === 'object') {
      const found = mcDeepFind(obj[k], key, depth + 1)
      if (found !== undefined) return found
    }
  }
  return undefined
}

/* §POCKETBRIDGE2 W7.1 — mcAddEvent + mcEventFeed deleted: the legacy feed
   path replaced by useLedgerStream; nothing called it and nothing read the
   ref, and it referenced the deleted MC_MAX_FEED. */

// §BRIDGE P4: the three per-frame sockets this view used to open, and the
// fail-quiet guard that nursed them, are GONE. `useLedgerStream()` owns exactly
// one socket per frame for the whole app. They had already been unwired in P1;
// this removes the ~190 lines that were still sitting here looking live.



async function mcFetchStats() {
  // §FEFRAME W2: THIS frame's ledger stats (an operator's: its parent's), by no letter. The per-letter B and C
  // polls are gone: their results were written and never read, and on EU/ASIA they asked for frames that do not
  // exist. Every frame's live counter comes from the one ledger stream (useLedgerStream).
  try {
    const res = await fetch(esStatsUrl(''), { cache: 'no-store' })
    if (res.ok) mcLedgerStats.value = await res.json()
  } catch { /* optional */ }
}




// ─── LIFECYCLE ───────────────────────────────────────────────
// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a bridge left during its config read starts no refresh, listener or attract loop when it lands
const alive = useAlive()
const brgStakingOn = ref(false)   // the lock door, where registry-config says staking_enabled is true
onMounted(async () => {
  // Detect operator mode and rebuild service list before probing
  try {
    // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
    const cfg: any = await loadRegistryConfig()
    {
      mcIsFederatedOperator.value = cfg.is_federated_operator ?? false
      mcFxEnabled.value = cfg.fx_enabled ?? false
      mcMultiFrame.value = cfg.multi_frame ?? true
      mcRegistryName.value = cfg.self?.display_name || cfg.registry_name || ''
      brgStakingOn.value = cfg.staking_enabled === true
      if (mcIsFederatedOperator.value) {
        hwCoreServices.value = buildServiceRefs(operatorCoreServiceDefs)
      }
    }
  } catch { /* non-fatal */ }
  if (!alive()) return
  runHealthProbes()
  fetchAllData()
  fetchAnalytics()
  fetchFleetData()
  fetchSenateData()
  fetchTrustData()
  setupAutoRefresh()
  // §BRIDGE 2026-08-18 — the three raw per-frame sockets this view used to open
  // are GONE. `useLedgerStream()` owns exactly one socket per frame for the whole
  // app, and both the stage and the merged ledger read from it. Opening these as
  // well would have put SIX sockets on one page against the same three endpoints
  // (the §FANOUTFIX shape: N askers of one question, free to disagree).
  // The HTTP stats polls stay — they are the cheap backfill for the totals.
  mcFetchStats()
  mcFetchFxRate()
  // #B8: the fleet lens keys. Bound on the window so the shortcut works wherever
  // the focus happens to be on this page, and ignored while typing.
  window.addEventListener('keydown', onBridgeKey)
  // #B18: any input at all is a wake signal. Passive listeners so scrolling and
  // pointer movement never wait on this handler.
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel'] as const) {
    window.addEventListener(ev, wakeFromAttract, { passive: true })
  }
  armAttract()
  try { chimeOn.value = localStorage.getItem('brg.chime') === '1' } catch { /* private mode */ }
})

onUnmounted(() => {
  if (replayTimer) clearInterval(replayTimer)
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null }
  // No per-frame sockets to tear down any more — see the note in onMounted.
  window.removeEventListener('keydown', onBridgeKey)
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel'] as const) {
    window.removeEventListener(ev, wakeFromAttract)
  }
  if (attractTimer) clearTimeout(attractTimer)
})
// ═══════════════════════════════════════════════════════════════════════════
// §BRIDGE — HUD state. Everything below READS rails this view already loaded.
// The only new network call on this page is the public supply-invariant seal.
// ═══════════════════════════════════════════════════════════════════════════
const stageRef = ref<any>(null)
const railsCollapsed = ref(false)
/**
 * The AGORA ticker starts CLOSED and is not mounted until it is opened
 * (Commander 2026-08-18: "do not render the moving agora strip at start ...
 * collapsed at start"). Deliberately NOT persisted: "at start" means every
 * start, so the landing page never boots into a marquee.
 */
/*
 * THE IN-VIEW TERMINAL (§BRIDGE R3). One lane open at a time, none at boot:
 * nothing here fetches or mounts until you ask for it, same discipline as the
 * AGORA strip. Esc closes it (see onBridgeKey).
 */
const terminalLane = ref<TerminalLane | null>(null)
function openTerminal(lane: TerminalLane): void {
  terminalLane.value = terminalLane.value === lane ? null : lane
  if (terminalLane.value) stageFocus.value = false
}
/*
 * #B13 FOLLOW MODE. The stage refuses to follow an agent it cannot place, and
 * that refusal is REPORTED rather than swallowed: an affordance that appears to
 * work and does nothing is the worst of the three outcomes.
 */
/*
 * #B17 REPLAY — session-scoped, and that is the design, not a shortfall.
 *
 * A websocket has no history: you get what arrives after you connect. The only
 * PUBLIC event endpoint on this network is `/public/eventstore-recent`, which
 * returns FIFTEEN events out of a Redis cache — enough to seed a feed, not to
 * reconstruct a window. Querying the real past means an admin-gated EventStore
 * route, i.e. publishing ledger history, which is a data-exposure decision and
 * not one a replay button gets to make on its own.
 *
 * So replay replays WHAT THIS SESSION WITNESSED, states its window, and says
 * when that window is clipped. Exactly the pulse bar's rule.
 */
const replaying = ref(false)
const replayNote = ref('')
let replayTimer: ReturnType<typeof setInterval> | null = null

function stopReplay(): void {
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null }
  replaying.value = false
}
function toggleReplay(): void {
  if (replaying.value) { stopReplay(); replayNote.value = ''; return }
  const w = ledger.replayWindow()
  if (!w.count) {
    replayNote.value = t('bridge.replay.nothing', 'Nothing seen yet to replay')
    setTimeout(() => { replayNote.value = '' }, 4000)
    return
  }
  const batch = ledger.replayBuffer()
  const spanMin = w.from && w.to ? Math.max(1, Math.round((w.to - w.from) / 60000)) : 0
  // NOTE: this project's legacy t() accepts EITHER an params object OR a string
  // fallback — never both. `t(key, 'text with {n}', { n })` silently returns the
  // fallback verbatim and puts a literal "{n}" on screen (seen, 2026-08-19).
  // Compose the sentence here; t() supplies only whole words.
  const replayVerb = w.capped
    ? t('bridge.replay.capped', 'replaying the last')
    : t('bridge.replay.all', 'replaying all')
  // State the SPLIT. Some of this window was seeded from the frames' own event
  // rings rather than witnessed on this session's sockets, and the caption is
  // where that stops being a detail and becomes something the viewer can see.
  // "by this registry" would be wrong twice over now: the seed is per-FRAME (the
  // ring carries whatever that frame's EventStore stored, not just registry
  // emissions) and it is fetched from every frame the app already streams.
  const parts = [`${replayVerb} ${batch.length} ${t('bridge.replay.events', 'events')}`]
  if (w.seeded > 0) {
    parts.push(`(${w.seeded} ${t('bridge.replay.seeded', 'seeded from the ledgers')}, ` +
               `${w.witnessed} ${t('bridge.replay.witnessed', 'seen live here')})`)
  } else {
    parts.push(`(${t('bridge.replay.sessionOnly', 'this session saw')}, ${spanMin} min)`)
  }
  replayNote.value = parts.join(' ')
  replaying.value = true

  // Feed the stage in wall-clock-compressed order: the whole window in ~20s,
  // in slices, so it reads as a time-lapse of what happened rather than as a
  // dump. Live events keep arriving underneath; replay never blocks the truth.
  let i = 0
  const slices = 40
  const per = Math.max(1, Math.ceil(batch.length / slices))
  replayTimer = setInterval(() => {
    if (i >= batch.length) { stopReplay(); return }
    stageRef.value?.pushVerbs?.(batch.slice(i, i + per).map(d => ({ ...d, id: `replay:${d.id}:${i}` })))
    i += per
  }, 500)
}

/*
 * SELECTION vs CAMERA — two different questions (§BRIDGE R9).
 *
 * They used to be one variable, and that is why the Commander could not fund or
 * lock anything: `onFollow` asked the stage to follow, and when the stage could
 * not place the agent it set the target back to null. Measured on the live
 * canary: 4,160 agents in his fleet, SEVEN of them drawn as stars (the LOD cap
 * is deliberate — P1). So for 4,153 of his agents, "select" silently failed and
 * the quick actions kept saying *"follow an agent to target it"*.
 *
 * Now: SELECTION is what the actions act on and always succeeds for an openable
 * identity. FOLLOW is a camera pin, offered when the stage can place the agent,
 * and its failure is reported as what it is — the camera could not move, not
 * "you have selected nothing".
 */
/*
 * REACH — how many registries this browser currently holds a session on. The
 * local one is always counted (you are logged in to it by definition); each
 * connected sibling adds one. Colour is a depth ladder, not decoration: one
 * registry is the default state, and it should not look like an alarm.
 */
const reachCount = computed(() => 1 + (cmdSessions.connectedKeys?.length || 0))
const reachTier = computed(() => (reachCount.value >= 4 ? 'deep' : reachCount.value >= 2 ? 'wide' : 'solo'))
/**
 * §B2 — how many agent CREDENTIALS this browser is carrying, and across how
 * many registries. Nothing said this anywhere: the reach control counted
 * registries and contributors, never the credentials themselves, so after
 * importing 608 of them there was no confirmation they had landed.
 */
const credsTick = ref(0)
const heldCreds = computed(() => {
  /*
   * EXPLICIT reactive dependency. `agentCredentialsStore` is a plain class over
   * localStorage, not a reactive store, so a computed reading only its method
   * evaluates ONCE and caches forever (the exact defect that made the ledger's
   * kept/forgotten counter read 12/0 for the life of the page). Bump the tick
   * wherever credentials can change.
   */
  void credsTick.value
  try {
    const all = agentCredentialsStore.getAllCredentials() || {}
    const rows = Object.values(all) as any[]
    const regs = new Set(rows.map(r => String(r?.registry_url || '')).filter(Boolean))
    return { n: rows.length, regs: regs.size }
  } catch { return { n: 0, regs: 0 } }
})

const reachTitle = computed(() => {
  const n = reachCount.value
  /*
   * 🔴 THIS NUMBER WAS LABELLED WRONG. `foreignRegistries` is a list of
   * REGISTRIES, and it was rendered as "<n> contributing agents to your fleet".
   * With 2 registries answered it read "2 contributing agents" to an operator
   * who had just imported 608 credentials — so the honest reading of his own
   * screen was that almost nothing had worked. Say registries when we mean
   * registries, and give the agent count its own number.
   */
  const foreign = foreignRegistries.value.length
  const foreignAgents = foreignDids.value.length
  /* R16.4 — say what connecting BUYS, not just that it exists. SEEING your
   * agents on a registry follows from being SIGNED IN there; the agent
   * credential is only needed to ACT as one. That distinction was invisible
   * here, so an operator signed in everywhere still saw one registry's agents
   * and reasonably concluded the credentials were what made them appear. */
  const base = n === 1
    ? t('bridge.reach.solo', 'Only this registry\u2019s agents are shown. Sign in to the others in Settings \u2192 Multi-Frame and the agents you own there join your fleet \u2014 credentials are needed only to ACT as an agent, never to see it.')
    : `${n} ${t('bridge.reach.many', 'registries signed in')}`
  const held = heldCreds.value
  const credLine = held.n
    ? ` · ${held.n.toLocaleString(appLocale())} agent credential${held.n === 1 ? '' : 's'} held across ${held.regs || 1} registr${(held.regs || 1) === 1 ? 'y' : 'ies'} (you can ACT as these)`
    : ` · no agent credentials imported yet — you can SEE your agents, but acting as one needs its credential`
  const pending = foreignPending.value
    ? ` · ${foreignPending.value} still answering…`
    : ''
  if (!foreign) return base + credLine + pending
  const cap = foreignPartial.value.length
  const tail = cap
    ? ` (${cap} ${t('bridge.reach.truncated', 'truncated at the 6,000-agent page cap')})`
    : ''
  const contrib = `${foreign} ${t('bridge.reach.contributing', 'of them contributing')} ${foreignAgents.toLocaleString(appLocale())} ${t('bridge.reach.agentsWord', 'agents to your fleet')}${tail}`
  return `${base} · ${contrib}${credLine}${pending}`
})

/** §BRIDGE R10 — the HUD's agent search (drives the stage's highlight). */
/*
 * FIT THE BRIDGE TO WHAT IS ACTUALLY LEFT.
 * Never compute from a chrome height we have to know in advance — read this
 * element's own top edge and take the rest of the viewport. Self-correcting
 * when the BETA banner is dismissed, on resize, and on any layout change.
 */
const brgEl = ref<HTMLElement | null>(null)
let fitRo: ResizeObserver | null = null
function fitBridge(): void {
  publishStageBox()
  const el = brgEl.value
  if (!el) return
  const top = el.getBoundingClientRect().top
  const want = Math.max(320, Math.round(window.innerHeight - top))
  const have = Math.round(el.getBoundingClientRect().height)
  if (Math.abs(want - have) <= 1) return      // no thrash, no observer loop
  el.style.height = `${want}px`
}

const searchQ = ref('')
const searchMatchCount = ref(0)
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQ, () => {
  if (searchTimer) clearTimeout(searchTimer)
  // The canvas re-evaluates on the prop; this only refreshes the COUNT, and a
  // count that chases every keystroke would walk the whole population per key.
  searchTimer = setTimeout(() => {
    searchMatchCount.value = stageRef.value?.searchMatchCount?.() ?? 0
  }, 320)
})

/** Enter = act on the top match: select it (and follow when it has a star). */
function selectFirstMatch(): void {
  const dids = stageRef.value?.searchMatchDids?.() ?? []
  const first = dids.find((d: string) => !!didOrNull(d))
  if (!first) { note(t('bridge.find.none', 'No agent matches that')); return }
  onSelect(first)
}

const selectedDid = ref<string | null>(null)
const followingDid = ref<string | null>(null)
const followNote = ref<string | null>(null)
let followNoteTimer: ReturnType<typeof setTimeout> | null = null

function note(msg: string): void {
  followNote.value = msg
  if (followNoteTimer) clearTimeout(followNoteTimer)
  followNoteTimer = setTimeout(() => { followNote.value = null }, 4000)
}

/** The primary gesture: click a row / a star / a receipt and it is now the target. */
function onSelect(did: string | null): void {
  const d = didOrNull(did)
  if (!d) return
  if (selectedDid.value && selectedDid.value.toLowerCase() === d.toLowerCase()) {
    selectedDid.value = null
    stageRef.value?.setFollowAgent?.(null)
    followingDid.value = null
    return
  }
  selectedDid.value = d
  // Ask the camera too — but never let its answer decide the selection.
  const ok = stageRef.value?.setFollowAgent?.(d)
  followingDid.value = ok ? d : null
  if (!ok) note(t('bridge.follow.selectedNoStar', 'Selected. It has no star on this map, so the camera stays put.'))
}

/*
 * The camera control. It ALSO selects — asking to watch something is a stronger
 * statement of interest than clicking it, and a user who pins an agent and then
 * finds FUND greyed out with "select an agent" has been told to do a thing they
 * just did. What stays separate is the FAILURE: if the stage cannot place the
 * agent, the selection stands and only the camera declines.
 */
function onFollow(did: string): void {
  const d = didOrNull(did)
  if (!d) return
  if (followingDid.value && followingDid.value.toLowerCase() === d.toLowerCase()) {
    stageRef.value?.setFollowAgent?.(null)
    followingDid.value = null
    return                                  // release the camera, keep the selection
  }
  selectedDid.value = d
  const ok = stageRef.value?.setFollowAgent?.(d)
  followingDid.value = ok ? d : null
  if (!ok) note(t('bridge.follow.selectedNoStar', 'Selected. It has no star on this map, so the camera stays put.'))
}

/**
 * MAP means "look at the map" — it clears the panels instead of navigating.
 *
 * It deliberately does NOT write to railLeftOpen/railRightOpen: those are
 * PERSISTED preferences, and a momentary "show me the stage" must not survive a
 * reload as "all your panels are gone" — especially when the handle that brings
 * them back is a 10px hairline by his own request. Focus is a derived view over
 * the preference, never a mutation of it.
 */
/** §BRIDGE R12 — the WORK quick view. A modal, per his ask, not a fourth rail. */
const workOpen = ref(false)
// §POCKETBRIDGE5 A' — the attention row can name the lane the modal opens on.
const workLane = ref<'contracts' | 'guild' | 'disputes' | undefined>(undefined)

/* §BRIDGE R14.3 — "what needs you". `null` until the panel has actually looked:
 * a badge reading 0 while nothing has been read yet is a claim we have not
 * earned, and the whole point of this lane is that it can be trusted. */
const attentionOpen = ref(false)
const attentionCount = ref<number | null>(null)
const attentionRef = ref<any>(null)

/* ── §BRIDGE R16.3 — HIDE EVERY FIGURE ────────────────────────────────────── */
const { hidden: privacyHidden, money, toggle: togglePrivacy } = usePrivacy()

/* ── §BRIDGE R16.2 — THE CARD LEADS WITH THE AGENT YOU SELECTED ───────────────
 * His ask: *"the 'your fleet' should just show the agent selected in your agent
 * selector. and its rank ... give the selected agent stats some room."*
 *
 * So the card leads with that agent — name, rank, its own balances, room to
 * breathe — and keeps the fleet aggregate as one quiet line underneath, with a
 * switch to the full fleet view for when the aggregate IS the question.
 *
 * Both halves read rails that are already in use: `/agents/by-did/{did}` (the
 * same profile R13's hover card reads, and it carries `liquid_balance`,
 * `staked_balance` and `reputation_score`) and `/agents/{did}/track-record`
 * through the ONE converter, so the rank here can never disagree with the
 * earned mark on the globe.
 */
type FleetCardMode = 'agent' | 'fleet'
const fleetCardMode = ref<FleetCardMode>('agent')
const selAgentProfile = ref<any>(null)
const selAgentTrack = ref<TrackRecordCompact | null>(null)
const selAgentLoading = ref(false)
const selAgentFailed = ref(false)

const selectedAgentDid = computed<string | null>(() => authStore.activeAgent?.did || null)
const selectedAgentName = computed<string>(() =>
  authStore.activeAgent?.name || (selectedAgentDid.value ? `${selectedAgentDid.value.slice(0, 18)}\u2026` : ''))
const selectedMarks = computed(() => earnedMarks(selAgentTrack.value))
/** Reputation is stored 0..1 and read as a PERCENT — a raw hand-off paints
 *  every meter at 1% (measured in R13, on this very field). */
const selectedRepPct = computed<number | null>(() => {
  const r = selAgentProfile.value?.reputation_score
  return typeof r === 'number' ? Math.round(r * 100) : null
})

async function loadSelectedAgent(did: string | null): Promise<void> {
  selAgentProfile.value = null; selAgentTrack.value = null; selAgentFailed.value = false
  if (!did || !/^did:/.test(did)) return
  selAgentLoading.value = true
  try {
    const [pr, tr] = await Promise.all([
      fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`/api/v1/agents/${encodeURIComponent(did)}/track-record`).then(r => r.ok ? r.json() : null).catch(() => null),
    ])
    selAgentProfile.value = pr
    selAgentTrack.value = tr ? compactFromSummary(tr) : null
    // An agent we could not read is SAID, never rendered as zeros.
    if (!pr) selAgentFailed.value = true
  } catch { selAgentFailed.value = true } finally { selAgentLoading.value = false }
}
watch(selectedAgentDid, (d) => { void loadSelectedAgent(d) }, { immediate: true })

/**
 * §BRIDGE R13 #10 — "the modals should not blcok the live ledger view."
 *
 * The bridge modals are Teleported to <body> and were `inset: 0`, so they
 * centred on the VIEWPORT and sat over both rails — you lost the live ledger
 * exactly when you opened something to compare against it. The terminal lane
 * had the same problem from the other side (screenshot 3: the EXCHANGE lane
 * overlapping the LIVE LEDGER header).
 *
 * Teleported content cannot inherit a CSS variable from `.brg`, so the measured
 * stage column is published on the ROOT element instead and the modals bound
 * themselves to it. Republished on resize and whenever a rail opens or closes,
 * because those are exactly the moments the column moves.
 */
function publishStageBox(): void {
  if (typeof document === 'undefined') return
  const el = document.querySelector('.brg-center') as HTMLElement | null
  const root = document.documentElement
  if (!el) return
  const r = el.getBoundingClientRect()
  // A rail can be collapsed to a hairline; below this the "column" is not a
  // usable place to put a dialog and it falls back to the viewport.
  if (r.width < 420) {
    root.style.setProperty('--brg-stage-l', '0px')
    root.style.setProperty('--brg-stage-r', '0px')
    return
  }
  root.style.setProperty('--brg-stage-l', `${Math.round(r.left)}px`)
  root.style.setProperty('--brg-stage-r', `${Math.round(window.innerWidth - r.right)}px`)
}

const stageFocus = ref(false)
function toggleStageFocus(): void {
  stageFocus.value = !stageFocus.value
  if (stageFocus.value) terminalLane.value = null
}
const railLeftShown = computed(() => railLeftOpen.value && !stageFocus.value)
const railRightShown = computed(() => railRightOpen.value && !stageFocus.value)

const tickerOpen = ref(false)
/**
 * The wrapper must NOT claim width before there is content.
 *
 * Measured 2026-08-19: `/agora/federation-tickers` answers in 7.3-11.5s
 * (its neighbours answer in 0.05-0.18s). Because the wrapper flipped to
 * `flex: 1 1 auto` on click while the component itself rendered nothing until
 * that call returned, opening AGORA shoved the FLEET and COMMAND buttons across
 * the spine and showed empty space for ten seconds — exactly what the Commander
 * reported as "something happens but doesn't show the agora strip".
 */
const tickerState = ref<'idle' | 'loading' | 'ready' | 'empty'>('idle')
function toggleTicker(): void {
  tickerOpen.value = !tickerOpen.value
  if (tickerOpen.value && tickerState.value === 'idle') tickerState.value = 'loading'
}
function onTickerLoaded(venueCount: number): void {
  tickerState.value = venueCount > 0 ? 'ready' : 'empty'
}

/**
 * Each rail collapses on its own, and the choice sticks. Unlike the ticker this
 * IS persisted: hiding a panel is a working preference, not a boot condition,
 * and having it spring back on every navigation would be its own annoyance.
 */
function railPref(key: string): boolean {
  try { return localStorage.getItem(key) !== '0' } catch { return true }
}
/**
 * #B8 THE FLEET LENS — `F` isolates your own traffic, `Esc` restores it.
 * The galaxy eases back and everyone else's photons drop to 8%; nothing is
 * hidden and nothing is invented, the rest of the network just goes quiet.
 * Ignored while a text field has focus, so typing an "f" never dims the page.
 */
const fleetLens = ref(false)

/*
 * §BRIDGE R14.4 — THE ATMOSPHERE DIAL.
 *
 * He has reported the same defect three times ("empty blackness", "expands and
 * contracts with zooming", "just got lighter so its more noticeable"). R13
 * finally identified it — a broad additive wash raising the sky level — and cut
 * it, but his GPU reads that wash at 15-33 where this box's software renderer
 * reads ~9, and I cannot measure his machine from here. Rather than spend a
 * fourth round guessing at a constant, the constant becomes his.
 *
 * `subtle` is exactly today's authored values, so nothing changes for anyone who
 * never touches it. `off` is the escape hatch that has effectively been missing.
 */
const ATMOS_STEPS = ['off', 'subtle', 'full'] as const
type AtmosStep = typeof ATMOS_STEPS[number]
const ATMOS_LABEL: Record<AtmosStep, string> = { off: 'CLEAR', subtle: 'HAZE', full: 'DEEP' }
/* CLEAR = no decorative wash at all · HAZE = 45% of it (the new default,
 * lighter than what shipped) · DEEP = the full authored look. */
const atmosphere = ref<AtmosStep>('subtle')
try {
  const saved = localStorage.getItem('bridge.atmosphere') as AtmosStep | null
  if (saved && (ATMOS_STEPS as readonly string[]).includes(saved)) atmosphere.value = saved
} catch { /* private mode: the default stands */ }

function cycleAtmosphere(): void {
  const i = ATMOS_STEPS.indexOf(atmosphere.value)
  atmosphere.value = ATMOS_STEPS[(i + 1) % ATMOS_STEPS.length]
  try { localStorage.setItem('bridge.atmosphere', atmosphere.value) } catch { /* not fatal */ }
  // Drive the stage the way this file ALREADY drives it (see setFleetLens):
  // one imperative call down the ref. Measured on the canary: the prop reached
  // BridgeStage and the label and localStorage both changed, but the canvas
  // never saw the new mode — so the prop+watch path was doing nothing the
  // established pattern was not already doing better. The prop is kept for the
  // BOOT case, where stageRef is still null and only a watcher can deliver.
  stageRef.value?.setAtmosphere?.(atmosphere.value)
}

function isTypingTarget(el: EventTarget | null): boolean {
  const n = el as HTMLElement | null
  if (!n || !n.tagName) return false
  const tag = n.tagName.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || n.isContentEditable === true
}

function setFleetLens(on: boolean): void {
  fleetLens.value = on
  stageRef.value?.setFleetLens?.(on)
}

/**
 * #B24 — the OPTIONAL fleet chime. DEFAULT OFF, and it stays default off: the
 * Commander's standing instruction on this is "never" turn it on by default.
 * A landing page that makes noise at someone who did not ask for noise is a
 * landing page people close.
 *
 * It sounds only for YOUR agents' events, at most once every few seconds, and
 * it is a single soft sine blip - not a soundtrack, not an alert. The AudioContext
 * is created inside the click that enables it, which is also the user gesture
 * browsers require, so nothing can make sound without an explicit human act.
 */
const chimeOn = ref(false)
let audioCtx: AudioContext | null = null
let lastChimeAt = 0
const CHIME_MIN_GAP_MS = 4000

function toggleChime(): void {
  chimeOn.value = !chimeOn.value
  try { localStorage.setItem('brg.chime', chimeOn.value ? '1' : '0') } catch { /* private mode */ }
  if (chimeOn.value && !audioCtx) {
    try { audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)() } catch { audioCtx = null }
  }
}

function chime(): void {
  if (!chimeOn.value || !audioCtx) return
  const now = Date.now()
  if (now - lastChimeAt < CHIME_MIN_GAP_MS) return
  lastChimeAt = now
  try {
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.type = 'sine'
    osc.frequency.value = 880
    gain.gain.setValueAtTime(0.0001, audioCtx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.045, audioCtx.currentTime + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.28)
    osc.connect(gain); gain.connect(audioCtx.destination)
    osc.start(); osc.stop(audioCtx.currentTime + 0.3)
  } catch { /* audio is a garnish; it never breaks the page */ }
}

/**
 * #B18 — ATTRACT MODE. After 90 seconds untouched the rails ease away and the
 * stage is left alone: the perpetual demo on every screen this is left on. Any
 * input at all snaps it back instantly, and it never engages while the fleet
 * lens is on or a receipt is open, because those are states someone is READING.
 *
 * It collapses the rails; it does not start anything new. Nothing here spends a
 * frame that the stage was not already spending.
 */
const ATTRACT_AFTER_MS = 90_000
const attract = ref(false)
let attractTimer: ReturnType<typeof setTimeout> | null = null

function armAttract(): void {
  if (attractTimer) clearTimeout(attractTimer)
  attractTimer = setTimeout(() => {
    if (fleetLens.value) return           // someone is reading their own traffic
    attract.value = true
    railsCollapsed.value = true
  }, ATTRACT_AFTER_MS)
}

function wakeFromAttract(): void {
  if (attract.value) {
    attract.value = false
    railsCollapsed.value = false
  }
  armAttract()
}

function onBridgeKey(ev: KeyboardEvent): void {
  if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey) return
  if (isTypingTarget(ev.target)) return
  if (ev.key === 'f' || ev.key === 'F') { setFleetLens(!fleetLens.value); ev.preventDefault() }
  else if (ev.key === 'Escape' && replaying.value) { stopReplay(); replayNote.value = ''; ev.preventDefault() }
  else if (ev.key === 'Escape' && (followingDid.value || selectedDid.value)) {
    stageRef.value?.setFollowAgent?.(null); followingDid.value = null; selectedDid.value = null; ev.preventDefault()
  }
  else if (ev.key === 'Escape' && terminalLane.value) { terminalLane.value = null; ev.preventDefault() }
  else if (ev.key === 'Escape' && stageFocus.value) { stageFocus.value = false; ev.preventDefault() }
  else if (ev.key === 'Escape' && fleetLens.value) { setFleetLens(false); ev.preventDefault() }
}

const railLeftOpen = ref(railPref('brg.rail.l'))
const railRightOpen = ref(railPref('brg.rail.r'))
// A rail opening or closing MOVES the stage column, so the box the modals bind
// to has to be re-measured then — not only on resize.
watch(railLeftOpen, (v) => {
  try { localStorage.setItem('brg.rail.l', v ? '1' : '0') } catch { /* private mode */ }
  nextTick(() => setTimeout(publishStageBox, 280))   // after the 260ms rail transition
})
watch(railRightOpen, (v) => {
  try { localStorage.setItem('brg.rail.r', v ? '1' : '0') } catch { /* private mode */ }
  nextTick(() => setTimeout(publishStageBox, 280))
})
watch(stageFocus, () => { nextTick(() => setTimeout(publishStageBox, 280)) })
const alarmText = ref('')

/** The shared stream singleton (one socket set for the whole app). */
const ledger = useLedgerStream()

// ─── Fleet identity: drives the lens and the log's human names ──────────────
const fleetAgentCount = computed<number>(() => {
  const n = Number(fleetData.value?.agent_count ?? 0)
  if (Number.isFinite(n) && n > 0) return n
  return (agentStore.agents || []).length
})
/*
 * THE VIEWER'S WHOLE FLEET — §BRIDGE R1 (2026-08-19).
 *
 * This used to read `agentStore.agents` alone, which is `/developers/me/agents`
 * capped at 200 rows. The Commander owns 4,093 agents on frame-c, so the bridge
 * knew 4.9% of his fleet — and the 200 it knew were the most RECENTLY created
 * (Gödel-Forge fixtures), not the sim agents actually moving money. MINE was
 * empty while his own agents transacted continuously in front of him.
 *
 * `/developers/me/agent-dids` returns identity only, so the whole fleet costs
 * one request and ~150KB of strings instead of 9 paged, hydrated round trips.
 * The hydrated stores are still merged in: they are the working set, they
 * arrive first, and belt-and-braces here costs nothing.
 */
type FleetDidState = 'loading' | 'ready' | 'partial' | 'failed'
const fleetDidState = ref<FleetDidState>('loading')
const fleetDidsFull = ref<string[]>([])
const fleetDidTotal = ref<number>(0)

/*
 * §BRIDGE R10 — YOUR AGENTS ON EVERY REGISTRY YOU ARE LOGGED IN TO.
 *
 * His ask: *"we have a multi frame login in the settings (all 3 frames same
 * master login). if we are logged in on all 3 frames we should also see our
 * agents on all those 3 frames."*
 *
 * The bridge already streams every frame's ledger; what it did not know was
 * which of the parties on the OTHER frames were his, because "mine" was built
 * from the LOCAL registry alone. Now each connected session contributes its own
 * `/developers/me/agent-dids` through the same-origin peer relay — the identical
 * endpoint, asked of that registry with that registry's own token, no new rail.
 *
 * Honest about scope: a registry you are not connected to contributes nothing,
 * and the fleet chip says how many registries the count covers.
 */
const foreignDids = ref<string[]>([])
/**
 * The relay's own registry directory (16 entries on frame-c today).
 *
 * TWO jobs, one request. (1) It is the ONLY namespace in which a registry has a
 * single name: the fan-out speaks session keys ('op-berlin'), credentials speak
 * URLs ('op-berlin.op.theprotocol.cloud'), the map speaks node names
 * ('op-berlin') and trust domains. Bucketing on two of those at once hands one
 * registry a double share of the star budget. (2) He is right that
 * `federationStore.registries` is the DIRECT-PEER tier — 3 on frame-c — while
 * the bridge draws 16, so a boot line quoting it under-reports by 13.
 */
const registryDir = ref<RegistryDirectory | null>(null)
/** Which source filled the directory: 'admin' | 'public' | 'none'.
 *  Exposed so a gate can prove the non-admin path actually ran. */
const dirSource = ref<'admin' | 'public' | 'none'>('none')

/* directoryKeyForUrl / homeMetaFor live in services/bridge/ownedHomes.ts and
 * are asked THERE, once. Two copies of the same predicate in two files is the
 * §FANOUTFIX defect exactly: they disagreed for one class of row and that class
 * went missing for weeks. */

/** This registry's own key in that namespace. */
const localHomeKey = computed<string>(() => registryDir.value?.local_key || '__local__')

/**
 * did -> the registry KEY it is owned on (§OWNEDHOMES 2026-08-21).
 *
 * The fan-out knew this and threw it away: it flattened every registry's answer
 * into one array, so by the time the stage asked "where does this agent live?"
 * the only honest answer left was "somewhere". Measured on frame-c: of 4,440
 * owned DIDs, the 1,689 the map could place were ALL frame-c — not because the
 * others failed to load, but because nothing recorded where they belonged.
 */
const foreignHomes = ref<Map<string, string>>(new Map())
/** How many connected registries have not answered yet (§FLEETFAN). */
const foreignPending = ref(0)
const foreignRegistries = ref<string[]>([])
/** Registries whose fleet we could only read through the capped legacy list. */
const foreignPartial = ref<string[]>([])

/*
 * A RELOAD MUST NOT SILENTLY DROP YOUR REACH.
 *
 * `commandSessions` keeps access tokens in MEMORY by Commander decision D2, and
 * refresh tokens in sessionStorage. Measured: connect Frame A in Settings, hard-
 * reload the bridge, and reach reads 1 again while the refresh token sits
 * unused — the connection looks lost when it is merely unclaimed. So the bridge
 * re-mints from the tokens THIS TAB already holds. No password, no new rail, and
 * a registry whose refresh has expired simply does not come back.
 */
async function restoreReach(): Promise<void> {
  // §FEFRAME W3: every session this tab remembers reconnects AT its registry, for an admin and a non-admin alike (the
  // session hub keeps each session's road); before W3 a non-admin's reach was never restored (the relay is admin-only)
  try {
    const n = await cmdSessions.reconnectRemembered()
    if (n) log.debug(`[bridge] reach restored on ${n} registr${n === 1 ? 'y' : 'ies'} (direct)`)
  } catch { /* a refused refresh leaves that registry disconnected; the console says so */ }
}

// §BOOTSEQ — foreignKeySig / foreignBusy / foreignAgain DELETED. Ordering and
// single-flight belong to the sequencer, which can prove both in a unit test;
// three ad-hoc flags in a 2,300-line view could not, and between them they
// still dropped a trigger and froze the fleet at 2 registries.
async function loadForeignFleets(force = false): Promise<void> {
  const keys = (cmdSessions.connectedKeys || []) as string[]
  if (!keys.length) {
    /*
     * EMPTY IS NOT THE SAME AS DISCONNECTED (measured 2026-08-19).
     * `connectedKeys` only counts status==='connected', and a session that is
     * re-minting sits at 'connecting' for a moment. The watcher fires on that
     * dip, and the naive branch wiped a fleet of 3,695 foreign agents that was
     * still perfectly valid — observed as mine 7,866 -> 4,171 with the registry
     * still listed as connected seconds later. So a dip while anything is still
     * connecting, or while a refresh token is still held, changes nothing.
     */
    const settling = Object.values(cmdSessions.sessions || {}).some((x: any) => x?.status === 'connecting')
    if (settling || foreignDids.value.length) return
    foreignDids.value = []; foreignRegistries.value = []; foreignPartial.value = []
    foreignHomes.value = new Map()
    return
  }
  // Paging a fleet costs megabytes; do it once per connected SET, not per tick.
  const sig = keys.slice().sort().join(',')
  /*
   * §BOOTSEQ — the guards are GONE. This used to carry four overlapping ones
   * (foreignBusy, foreignAgain, foreignKeySig, fanTimer) which between them
   * still managed to drop a trigger and freeze the fleet at 2 registries. The
   * sequencer now owns single-flight AND the re-run when the connected set
   * moves, so this function does one thing: fetch the current set.
   */
  void sig
  const out: string[] = []
  const covered: string[] = []
  const partial: string[] = []
  /*
   * §FLEETFAN (2026-08-20) — TWO PHASES, because the old blanket "sequential,
   * and deliberately so" rationale was measured and is now STALE.
   *
   * It assumed most registries lack `/developers/me/agent-dids` and would page
   * ~7 MB each, so parallelism meant tens of MB competing with the stage. That
   * was true when the endpoint was canary-only. Measured 2026-08-20 through the
   * real relay: ALL 16 registries answer it, the whole fan-out moved 12,865
   * DIDs, and the cost was almost entirely round-trip latency, not bytes.
   *
   * Sequentially that is 44.3s of wall-clock — which is exactly what "the
   * topology builds longer than usual" was, and why a screenshot taken during
   * it showed 2 registries contributing out of 16. It was not stuck; it was
   * queueing.
   *
   * So: the CHEAP slim probe runs concurrently, bounded, because latency
   * parallelises and bytes do not. Any registry that falls back to the
   * expensive paging path is collected and done SEQUENTIALLY afterwards, where
   * the original reasoning still holds.
   */
  foreignPending.value = keys.length
  const legacyQueue: string[] = []
  const homes = new Map<string, string>()

  const slimOne = async (k: string): Promise<void> => {
    const tok = cmdSessions.adminTokenFor(k)
    if (!tok) { foreignPending.value = Math.max(0, foreignPending.value - 1); return }
    const SLIM_MISS = `bridge_no_agent_dids:${k}`
    let slimKnownMissing = false
    try { slimKnownMissing = sessionStorage.getItem(SLIM_MISS) === '1' } catch { /* blocked */ }
    if (slimKnownMissing) {
      legacyQueue.push(k)
      foreignPending.value = Math.max(0, foreignPending.value - 1)
      return
    }
    try {
      const d = await foreignGet<any>(k, 'developers/me/agent-dids', tok)
      const dids = Array.isArray(d?.dids) ? d.dids : []
      if (dids.length) {
        for (const x of dids) { const v = String(x); out.push(v); homes.set(v, k) }
        covered.push(k)
      }
    } catch {
      try { sessionStorage.setItem(SLIM_MISS, '1') } catch { /* blocked */ }
      legacyQueue.push(k)
    } finally {
      foreignPending.value = Math.max(0, foreignPending.value - 1)
      // Publish as we go: a fleet that grows visibly is honest about being
      // partial, where a number frozen at 2 for 40s reads as broken.
      foreignDids.value = out.slice()
      foreignRegistries.value = covered.slice()
      foreignHomes.value = new Map(homes)
    }
  }

  const CONC = 4
  for (let i = 0; i < keys.length; i += CONC) {
    await Promise.all(keys.slice(i, i + CONC).map(slimOne))
  }

  for (const k of legacyQueue) {
    await (async () => {
    const tok = cmdSessions.adminTokenFor(k)
    if (!tok) return
    /*
     * THE LEGACY PATH — and it is COMPLETE, not capped (measured 2026-08-19).
     *
     * `/developers/me/agent-dids` is R1 code and lives only on this canary so
     * far: Frame A answers 404. My first reading was that this left foreign
     * fleets stuck at the 200-row cap until the fleet roll — the Commander
     * challenged it, and he was right to. `/developers/me/agents` takes
     * `limit` (hard cap 500) AND `offset`, so the whole fleet is reachable
     * today on every registry. Measured on Frame A: 3,693 agents, 8 pages,
     * 7.2 MB, 8.7s.
     *
     * So the roll makes this CHEAPER (172 KB instead of 7.2 MB), not possible.
     * Until then: page it, bounded, in the background, and record that this
     * registry was read the expensive way so the reach tooltip can say so.
     */
    try {
      const LIMIT = 500
      const MAX_PAGES = 12                    // 6,000 agents; a hard stop, not a guess
      const dids: string[] = []
      let truncated = false
      for (let page = 0; page < MAX_PAGES; page++) {
        const d2 = await foreignGet<any>(k, 'developers/me/agents', tok, { limit: LIMIT, offset: page * LIMIT })
        const arr = Array.isArray(d2) ? d2 : (d2?.agents ?? d2?.items ?? [])
        for (const a of arr || []) { const did = String(a?.did || ''); if (did) dids.push(did) }
        if (!Array.isArray(arr) || arr.length < LIMIT) break
        if (page === MAX_PAGES - 1) truncated = true
      }
      if (dids.length) {
        out.push(...dids)
        for (const v of dids) homes.set(v, k)
        covered.push(k)
        // "partial" now means only what it says: we stopped at the page cap.
        if (truncated) partial.push(k)
      }
    } catch {
      // A registry that will not answer contributes nothing and says nothing.
    }
    })()
  }
  /*
   * Never let a transient failure shrink MINE. Measured: the note said "across
   * 2 registries" and 15s later said nothing, because a refresh pass that came
   * back empty overwrote a good result. A registry you are still connected to
   * does not stop being yours because one request failed — so an empty pass on
   * a still-connected set is DISCARDED, and only a real disconnect clears it.
   */
  if (!out.length && foreignDids.value.length && keys.length) {
    log.debug('[bridge] foreign fleet refresh returned nothing; keeping the previous result')
    return
  }
  foreignDids.value = out
  foreignRegistries.value = covered
  foreignPartial.value = partial
  foreignHomes.value = homes
  foreignPending.value = 0
  credsTick.value++          // an import usually arrives with a reconnect
}

/** Reconnecting or importing a vault must widen MINE without a reload. A real
 *  disconnect (no sessions left at all) narrows it again. */
let fanTimer: ReturnType<typeof setTimeout> | null = null
watch(() => cmdSessions.connectedKeys.join(','), () => {
  /*
   * §FLEETFAN-2 (2026-08-20) — DEBOUNCED, and this is where the time went.
   *
   * Restoring 9 peer sessions fires this watcher 9 times, and each firing ran a
   * COMPLETE fan-out over every key connected so far, re-fetching registries
   * that had already answered. Measured navigation-to-settled: 70s. Waiting for
   * the connected set to stop moving collapses that to one pass over the final
   * set. The trailing edge is what matters, so a fixed short delay is enough;
   * a real disconnect still narrows the fleet on the next quiet tick.
   */
  // A reconnect after boot re-runs the SAME declared step, so it inherits the
  // sequencer's single-flight and its input-set re-run. The 1.5s debounce only
  // coalesces a burst of sessions restoring together.
  if (fanTimer) clearTimeout(fanTimer)
  fanTimer = setTimeout(() => { fanTimer = null; void retryBootStep('foreign') }, 1500)
})
watch(() => Object.keys(cmdSessions.sessions || {}).length, (n) => {
  if (n === 0) { foreignDids.value = []; foreignRegistries.value = []; foreignPartial.value = []; foreignHomes.value = new Map() }
})

async function loadFleetDids(): Promise<void> {
  try {
    const res = await apiClient.get('/developers/me/agent-dids')
    const dids = Array.isArray(res.data?.dids) ? res.data.dids : []
    fleetDidsFull.value = dids.map((d: any) => String(d))
    fleetDidTotal.value = Number(res.data?.total ?? dids.length) || dids.length
    fleetDidState.value = res.data?.complete === false ? 'partial' : 'ready'
  } catch (e) {
    // HONEST failure: fall back to the capped store list and SAY the scope is
    // partial. Never silently present 200-of-4093 as "your fleet".
    log.debug('agent-dids:', e)
    fleetDidState.value = 'failed'
  }
}

const fleetDids = computed<string[]>(() => {
  const out: string[] = []
  for (const d of fleetDidsFull.value) out.push(d)
  for (const d of foreignDids.value) out.push(d)
  for (const a of (agentStore.agents || []) as any[]) if (a?.did) out.push(String(a.did))
  for (const a of (authStore.availableAgents || []) as any[]) if (a?.did) out.push(String(a.did))
  return Array.from(new Set(out))
})

/**
 * WHICH of the viewer's agents get their own star.
 *
 * `fleetDids` is identity and must be complete (4,098 on frame-c). Geometry
 * must not be: strategy §7.4 caps mission mode at the viewer's own agents
 * precisely because one sprite per agent blocked the renderer for minutes, and
 * handing that filter a complete fleet quietly undoes the cap. The hydrated
 * working set (what the stores actually loaded) is both bounded and the right
 * answer — those are the agents he is working with — and the hard cap below is
 * a floor under the worst case rather than a number anyone should reach.
 */
/**
 * §STARCAP (Commander 2026-08-21) — 240 was set when every star also cost a
 * 512x80 label canvas. Labels are lazy now and the body geometry dropped from
 * ~1,216 triangles to ~168, so 1000 stars costs less than 240 used to. His
 * reason for the number: 40 sim agents x 16 registries is already 640, and the
 * fleet keeps growing. Fixed, not a user setting — the LOD work paid for it.
 */
const STAR_CAP = 1000
/**
 * STICKY. The stores clear their arrays before refilling them on a refresh
 * (auth.ts does it deliberately, to force Vue to see the change), so a naive
 * computed goes empty for a tick — and an empty star list rebuilds the instanced
 * mesh with nothing in it. Measured: the viewer's own stars blinked 0 -> 1 -> 0
 * -> 4 while the page warmed up. Those agents did not stop existing for a
 * moment, so the stage should not say they did.
 *
 * Grows and holds; only a real change in membership replaces it.
 */
/**
 * §ACTIVITY — "show only agents active in the last N minutes".
 *
 * Fed from the stream this page already consumes, so it costs no request. It
 * can only speak for what THIS SESSION has watched, and `activityNote` says so
 * rather than letting a young page report a quiet fleet.
 */
/* ═══ §LITEBRIDGE — the graphics mode, and the board that replaces the stage ══
 *
 * Carried since §BRIDGE R8 and finally asked for: *"build the low performance
 * mission control for when people don't have the compute to display the new
 * bridge."*
 *
 * NOT a second copy of this view. The rails, the boot sequencer, the stream,
 * the stores and the quick actions are the same objects either way — only the
 * expensive thing changes. A parallel LiteMissionControl.vue would drift from
 * this one within a fortnight and be wrong in exactly the places nobody looks.
 */
const gfxPref = ref<GfxPref>(loadGfxPref())
const gfxCaps = ref<GfxCaps>({ webgl: true })      // replaced on mount by a real probe
const gfxProbed = ref(false)
const gfxRes = computed(() => resolveGfx(gfxPref.value, gfxCaps.value))
/* Until the probe has run we assume the machine is CAPABLE, so a fast machine
 * never flashes the board on its way to the stage. The probe is synchronous and
 * runs before first paint of the stage anyway (BridgeStage defers its mount). */
const gfxMode = computed(() => (gfxProbed.value ? gfxRes.value.mode : (gfxPref.value === 'lite' ? 'lite' : 'full')))
function setGfx(p: GfxPref) { gfxPref.value = p; saveGfxPref(p); gfxOffer.value = false }

/** The measured offer to switch — never an automatic switch. */
const gfxOffer = ref(false)
const gfxOfferMs = ref(0)
const gfxOfferDismissed = ref((() => {
  try { return localStorage.getItem(GFX_OFFER_DISMISSED_KEY) === '1' } catch { return false }
})())
function dismissGfxOffer() {
  gfxOffer.value = false
  gfxOfferDismissed.value = true
  try { localStorage.setItem(GFX_OFFER_DISMISSED_KEY, '1') } catch { /* blocked */ }
}
const gfxOfferText = computed(() => offerText(gfxOfferMs.value))

const boardIx = createBoardIndex(Date.now())
const boardTick = ref(0)                    // the index is plain Maps, like activityIx
const boardFocusKey = ref<string | null>(null)

/** did -> registry key, for EVERY agent you own — not just the drawn ones. */
const didHome = computed<Map<string, string>>(() => {
  const m = new Map<string, string>()
  const localKey = localHomeKey.value
  for (const d of fleetDidsFull.value) m.set(String(d), localKey)
  for (const [did, k] of foreignHomes.value) m.set(String(did), k)
  return m
})

/** The registries the board lists: the directory, which is the widest honest set. */
const boardRegistries = computed<BoardRegistry[]>(() => {
  const localKey = localHomeKey.value
  const entries = (registryDir.value?.registries || []) as any[]
  if (!entries.length) return []
  return entries.map(e => ({
    key: e.key,
    name: e.name || e.key,
    frame: e.frame || null,
    currency: e.currency || null,
    local: e.key === localKey || !!e.is_local,
  }))
})

/** Agents you own per registry. EXACT — the board's whole point. */
const boardMine = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  const localKey = localHomeKey.value
  out[localKey] = fleetDidsFull.value.length
  for (const [, k] of foreignHomes.value) {
    const key = k
    out[key] = (out[key] || 0) + 1
  }
  return out
})

/** Rails narrowed to one registry — the board's equivalent of following a star. */
const focusedFleetDids = computed<string[]>(() => {
  const k = boardFocusKey.value
  if (!k) return fleetDids.value
  const home = didHome.value
  return fleetDids.value.filter(d => home.get(String(d)) === k)
})
/*
 * ONE writer for "which DIDs are mine", and it is this view.
 *
 * The stage used to own it, which meant the light bridge would have shown an
 * empty fleet log and an empty MINE ledger on a machine whose only problem was
 * not having a GPU. Narrowing it is also how the board focuses a registry: the
 * fleet log and the ledger both read the same stream predicate, so one call
 * moves both and they can never disagree.
 */
watch(focusedFleetDids, (dids) => ledger.setMineDids(dids || []), { immediate: true })

const boardFocusNote = computed<string | null>(() => {
  const k = boardFocusKey.value
  if (!k) return null
  const n = focusedFleetDids.value.length
  const name = boardRegistries.value.find(r => r.key === k)?.name || k
  return `${name}: ${n.toLocaleString(appLocale())} ${t('bridge.board.ofYours', 'of your agents')}`
})

const activityIx = createActivityIndex(Date.now())
const activityWindowMs = ref<number | null>(null)   // null = mode OFF
const activityCustomMin = ref<string>('')
const activityTick = ref(0)                          // the index is a plain Map
try {
  const saved = localStorage.getItem('bridge.activityWindowMs')
  if (saved) { const v = parseInt(saved, 10); if (Number.isFinite(v) && v > 0) activityWindowMs.value = v }
} catch { /* blocked */ }
watch(activityWindowMs, (v) => {
  try {
    if (v) localStorage.setItem('bridge.activityWindowMs', String(v))
    else localStorage.removeItem('bridge.activityWindowMs')
  } catch { /* blocked */ }
})
function setActivityWindow(ms: number | null) {
  activityWindowMs.value = (activityWindowMs.value === ms) ? null : ms
}
function applyCustomActivityWindow() {
  const ms = windowFromMinutes(parseInt(activityCustomMin.value, 10))
  if (ms) activityWindowMs.value = ms
}

const starDidsHeld = ref<string[]>([])
const starHomesHeld = ref<Array<{ did: string; name?: string | null; local?: boolean; names?: string[]; trustDomain?: string | null }>>([])
/** Candidates the fan-out handed us with no nameable home — counted, never guessed. */
const starUnplaced = ref(0)
const starRegistryCountHeld = ref(0)

/**
 * §STARQUOTA + §OWNEDHOMES — every registry you own agents on gets stars, and
 * the stage is told where each one lives.
 *
 * The first half of this shipped on 2026-08-21 and was only half the bug. The
 * slice was real: `availableAgents` is sorted credentialed-first, so
 * `slice(0, 240)` gave every slot to a handful of registries and he saw agents
 * orbiting exactly FIVE of the sixteen he is signed in to. But spreading the
 * slots does nothing if the candidates cannot be attributed, and they could not
 * be: this list was built from the LOCAL stores only, so an agent owned as a
 * developer on op-berlin — which arrives from the fan-out as a bare DID — was
 * not a candidate at all, and one that did arrive carried no registry.
 *
 * Measured on frame-c 2026-08-21, and it is unambiguous: 4,440 owned DIDs;
 * 1,689 of them present in the map's source (`/agents/locations/`, a 6,000-row
 * SAMPLE of 13,797); and every single one of those 1,689 carried trust_domain
 * `frame-c`. Zero foreign. Nothing had failed to load.
 *
 * So the candidate list is now the WHOLE owned fleet — local DIDs from
 * `/developers/me/agent-dids`, foreign DIDs from the fan-out — each carrying
 * the directory key of the registry it is owned on. Credentialed agents go in
 * FIRST because order decides which of a registry's agents win its slots, and
 * the ones he holds keys for are the ones he can act as.
 */
const fleetStarDids = computed<string[]>(() => {
  const plan = buildStarPlan({
    localKey: localHomeKey.value,
    cap: STAR_CAP,
    localOrigin: window.location.origin,
    credentialed: ((authStore.availableAgents || []) as any[])
      .filter(a => a?.did)
      .map(a => ({ did: String(a.did), name: a.name ?? null, registryUrl: a.registry_url ?? null })),
    localAgents: ((agentStore.agents || []) as any[])
      .filter(a => a?.did).map(a => ({ did: String(a.did), name: a.name ?? null })),
    localDids: fleetDidsFull.value,
    foreign: foreignDids.value.map(d => {
      const k = foreignHomes.value.get(String(d)) || null
      return { did: String(d), key: k || null }
    }),
    directory: (registryDir.value?.registries || []).map((e: any) => ({
      key: e.key, name: e.name, trustDomain: e.trust_domain ?? e.match?.trust_domain ?? null,
      names: e.match?.names || [],
    })),
  })
  starUnplaced.value = plan.unplaced
  if (plan.chosen.length) {
    starDidsHeld.value = plan.chosen
    starHomesHeld.value = plan.homes
    starRegistryCountHeld.value = plan.registries
  }
  return starDidsHeld.value
})

/** Where the stage should place each drawn star. Only what we can name. */
const starHomes = computed(() => { void fleetStarDids.value; return starHomesHeld.value })

/** How many registries the drawn stars actually cover — the honest caption. */
const starRegistryCount = computed<number>(() => { void fleetStarDids.value; return starRegistryCountHeld.value })

/**
 * What the stage actually draws. With the mode off this is the held set
 * unchanged — the filter can only ever REMOVE, never invent a star.
 */
const activeStarDids = computed<string[]>(() => {
  const base = fleetStarDids.value
  const w = activityWindowMs.value
  if (!w) return base
  void activityTick.value
  const live = activeDids(activityIx, w, Date.now())
  return base.filter(d => live.has(d))
})
const activityCaption = computed<string | null>(() => {
  const w = activityWindowMs.value
  if (!w) return null
  // In light mode the window filters REGISTRIES, and the board's own header
  // already says how many it is hiding. Two captions counting different things
  // in the same corner is how a reader stops trusting either.
  if (gfxMode.value !== 'full') return null
  void activityTick.value
  return activityNote(activityIx, w, Date.now(), activeStarDids.value.length, fleetStarDids.value.length)
})

/**
 * What is actually in orbit, and over how many registries.
 *
 * The stage draws a BOUNDED set — 240 of a fleet that is 4,440 on this registry
 * alone — and until now nothing on screen said so, which is why "only five
 * registries have agents" read as a loading failure rather than as a budget.
 * A number he can check against the registry count beside it.
 */
const orbitNote = computed<string | null>(() => {
  // Nothing is in orbit when there is no stage. Seen in the first light-bridge
  // screenshot: "240 of 4,448 in orbit · 1 registry" printed beside a board
  // with no starfield anywhere near it — a caption describing furniture that is
  // not on the screen, which is the §OPGUIDE-7 defect wearing a number.
  if (gfxMode.value !== 'full') return null
  const drawn = fleetStarDids.value.length
  if (!drawn) return null
  const regs = starRegistryCount.value
  const total = fleetDids.value.length
  if (drawn >= total) return `${drawn} in orbit · ${regs} registr${regs === 1 ? 'y' : 'ies'}`
  return `${drawn} of ${total.toLocaleString(appLocale())} in orbit · ${regs} registr${regs === 1 ? 'y' : 'ies'}`
})
const orbitTitle = computed<string>(() => {
  const parts = [
    `The stage draws ${STAR_CAP} stars at most, shared across every registry you own agents on — a floor each, then the rest in proportion.`,
  ]
  if (starUnplaced.value) parts.push(`${starUnplaced.value} agent(s) came back from a registry this bridge cannot name, so they are counted but not drawn.`)
  return parts.join(' ')
})

/** What the MINE filter is allowed to claim about itself, in one word. */
const fleetScopeNote = computed<string | null>(() => {
  if (fleetDidState.value === 'loading') return t('bridge.fleet.matching', 'matching your fleet...')
  if (fleetDidState.value === 'failed') {
    return `${t('bridge.fleet.scopePartial', 'partial scope:')} ${fleetDids.value.length} ${t('bridge.fleet.known', 'known')}`
  }
  if (fleetDidState.value === 'partial') {
    return `${fleetDids.value.length} ${t('bridge.fleet.ofWord', 'of')} ${fleetDidTotal.value} ${t('bridge.fleet.agents', 'agents')}`
  }
  // §BRIDGE R10 — when MINE spans more than this registry, say so. A count that
  // silently grows because you logged in somewhere else is a number nobody can
  // check; naming the registries makes it checkable.
  if (foreignRegistries.value.length) {
    const n = foreignRegistries.value.length
    const cap = foreignPartial.value.length
      ? ` · ${foreignPartial.value.length} ${t('bridge.fleet.truncated', 'truncated at 6,000')}`
      : ''
    return `${t('bridge.fleet.across', 'across')} ${n + 1} ${t('bridge.fleet.registries', 'registries')}${cap}`
  }
  return null
})
const fleetAgentNames = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  const add = (a: any) => {
    if (a?.did && a?.name) { m[String(a.did)] = String(a.name); m[String(a.did).toLowerCase()] = String(a.name) }
  }
  for (const a of (agentStore.agents || []) as any[]) add(a)
  for (const a of (authStore.availableAgents || []) as any[]) add(a)
  return m
})

/** The earned-mark ladder (§MARKGUILLOCHE). Speaks tiers, never truncated hex. */
const EARNED_LADDER: Array<[number, string]> = [
  [250, 'SOVEREIGN'], [100, 'MASTER'], [50, 'EXPERT'], [25, 'VETERAN'],
  [10, 'SEASONED'], [5, 'ESTABLISHED'], [1, 'PROVEN'],
]
const fleetMarkTier = computed<string>(() => {
  const jobs = Number(fleetData.value?.verified_jobs ?? 0)
  for (const [n, label] of EARNED_LADDER) if (jobs >= n) return label
  return t('bridge.fleet.unranked', 'UNRANKED')
})

// ─── Honest health (§BRIDGE B6) ────────────────────────────────────────────
// The old score divided healthy by EVERY probe, including the five sandbox
// registries that are OFF BY DESIGN. That is how the dashboard came to read
// "80.0% GOOD" beside "5 DOWN" — measured live on registry-a the same day:
// 19/25 healthy, five of the six down being exactly the sandbox tier. The
// landing page scores what is SUPPOSED to be up: this node's spine plus the
// federation it can see. The backend now states the tier per probe; this
// predicate is the client-side belt to that braces, so an older backend
// (mid-roll) still scores honestly.
function isSandboxProbe(name: string): boolean {
  return /(^|\s)sandbox(\s|$)/i.test(name || '')
}
const scoredServices = computed(() => [
  ...hwCoreServices.value.filter(sv => !isSandboxProbe(sv.name)),
  ...hwOperatorServices.value,
])
const sandboxTotal = computed(() => hwCoreServices.value.filter(sv => isSandboxProbe(sv.name)).length)
const scoredTotal = computed(() => scoredServices.value.length)
const scoredHealthy = computed(() => scoredServices.value.filter(sv => sv.status === 'healthy').length)
/** Probes that have not answered yet. NOT failures — the difference matters. */
const scoredPending = computed(() => scoredServices.value.filter(sv => sv.status === 'pending').length)
const scoredDown = computed(() => scoredServices.value.filter(sv => sv.status === 'down').length)
const spineHealthLabel = computed(() => {
  if (!scoredTotal.value) return t('bridge.vitals.checking', 'CHECKING')
  // A probe that has not answered yet is UNKNOWN, not down. Calling the first
  // 4 seconds after mount "4 DEGRADED" is the same self-alarming lie as scoring
  // the sandbox tier as failures, just on a shorter timescale.
  if (scoredPending.value > 0 && scoredDown.value === 0) return t('bridge.vitals.checking', 'CHECKING')
  if (scoredDown.value === 0) return t('bridge.vitals.allUp', 'ALL SYSTEMS UP')
  return `${scoredDown.value} ${t('bridge.vitals.degraded', 'DEGRADED')}`
})
const spineHealthClass = computed(() => {
  if (!scoredTotal.value || (scoredPending.value > 0 && scoredDown.value === 0)) return 'brg-h-wait'
  return scoredDown.value === 0 ? 'brg-h-ok' : 'brg-h-warn'
})

// ─── The Δ SEAL — the prime directive, permanently on screen ────────────────
// Public read-only proxy over this node's own EventStore invariant. When it
// cannot verify, it SAYS so. A seal showing a comforting zero it did not
// measure would be the exact opposite of what this product is about.
const sealDelta = ref<number | null>(null)
const sealStatus = ref<string>('UNKNOWN')
const sealCheckedAt = ref<number | null>(null)
/*
 * THE SEAL IS A READING, NOT A CLOCK — §BRIDGE R2 (Commander, 2026-08-19):
 * "it should load once and not refresh the delta."
 *
 * It used to re-fetch every 60s and tick its own age every second, so a number
 * that is 0.00 by construction sat there animating for attention it had not
 * earned. It now loads once, states WHEN it was verified, and re-checks only
 * when you ask it to. Nothing about the invariant's honesty changes: the value
 * is still real, still fetched from /public/supply-invariant, still UNKNOWN
 * rather than a comforting zero when it cannot be read.
 */

async function refreshSeal() {
  try {
    const r = await fetch(`${window.location.origin}/api/v1/public/supply-invariant`, { cache: 'no-store' })
    if (!r.ok) throw new Error(String(r.status))
    const d = await r.json()
    sealDelta.value = typeof d?.delta === 'number' ? d.delta : null
    sealStatus.value = String(d?.status || 'UNKNOWN')
  } catch {
    sealDelta.value = null
    sealStatus.value = 'UNKNOWN'
  }
  sealCheckedAt.value = Date.now()
}
const sealValue = computed(() => {
  if (sealDelta.value === null) return '?'
  return Math.abs(sealDelta.value) < 1e-9 ? '0.00' : sealDelta.value.toFixed(2)
})
const sealClass = computed(() => {
  if (sealDelta.value === null) return 'brg-seal--unknown'
  return Math.abs(sealDelta.value) < 1e-9 ? 'brg-seal--ok' : 'brg-seal--breach'
})
/** WHEN it was verified — a fixed stamp, not a countdown. */
const sealAge = computed(() => {
  if (!sealCheckedAt.value) return ''
  const d = new Date(sealCheckedAt.value)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
})
const sealTitle = computed(() => {
  if (sealDelta.value === null) {
    return t('bridge.seal.unknownHelp', 'Supply invariant could not be verified from here. Click to retry.')
  }
  return Math.abs(sealDelta.value) < 1e-9
    ? t('bridge.seal.okHelp', 'Supply invariant holds: issued minus destroyed equals circulating, exactly. Click to re-check.')
    : t('bridge.seal.breachHelp', 'Supply invariant does NOT hold. Click to re-check.')
})

// A real breach is the one thing on this page allowed to shout.
watch(sealDelta, (d) => {
  if (d !== null && Math.abs(d) >= 1e-9) raiseAlarm(t('bridge.alarm.supply', 'SUPPLY INVARIANT BREACH'))
  else if (alarmFromSeal) { alarmText.value = ''; alarmFromSeal = false }
})

/**
 * #B16 — THE ALARM INTERRUPT (V7).
 *
 * The grammar classifies exactly six event types as breach-class; everything
 * else, including refunds, halts and swept 2PC rows, is routine and never turns
 * this red. That discipline is the whole reason a real alarm lands: if the page
 * cried wolf at ordinary failure, nobody would look when it mattered.
 *
 * The alarm holds for a while after the event rather than blinking away, and it
 * says WHAT it saw - a red bar with no noun is just anxiety.
 */
let alarmFromSeal = false
let alarmTimer: ReturnType<typeof setTimeout> | null = null
const ALARM_HOLD_MS = 45_000

function raiseAlarm(text: string, fromSeal = true): void {
  alarmFromSeal = fromSeal
  alarmText.value = text
  if (alarmTimer) clearTimeout(alarmTimer)
  // A seal breach is a STANDING condition - it clears when the seal clears, not
  // on a timer. A stream alarm is an event, so it fades once it has been seen.
  if (!fromSeal) {
    alarmTimer = setTimeout(() => { alarmText.value = ''; alarmTimer = null }, ALARM_HOLD_MS)
  }
}

let offAlarmVerbs: (() => void) | null = null
let offActivityRaw: (() => void) | null = null
/*
 * The index is a plain Map, so nothing re-evaluates on its own. Agents must
 * AGE OUT visibly ("disappear and reappear based on activity"), which needs a
 * heartbeat. Only while the mode is on — an off switch that still burns a timer
 * is not off.
 */
let activityTimer: ReturnType<typeof setInterval> | null = null
let boardTimer: ReturnType<typeof setInterval> | null = null
let gfxOfferTimer: ReturnType<typeof setInterval> | null = null
watch(activityWindowMs, (v) => {
  if (activityTimer) { clearInterval(activityTimer); activityTimer = null }
  if (v) activityTimer = setInterval(() => { activityTick.value++ }, 10_000)
}, { immediate: true })
onMounted(() => {
  // §ACTIVITY — every raw event names its parties; that IS the activity signal.
  // Uses the grammar's own party scan so it can never disagree with `mine`.
  offActivityRaw = ledger.onRaw((_frameKey, inner) => {
    try {
      const parties = partiesOfEnvelope(inner)
      const now = Date.now()
      noteActivity(activityIx, parties, now)
      // §LITEBRIDGE — the SAME party scan feeds the board, so the two can never
      // disagree about whose event it was (§FANOUTFIX: one predicate, asked in
      // both places). Only parties we can place are counted; a registry we
      // cannot name gets no credit rather than a guessed one.
      const home = didHome.value
      const keys: string[] = []
      for (const d of parties) { const k = home.get(String(d)); if (k) keys.push(k) }
      if (keys.length) noteBoardActivity(boardIx, keys, now)
    } catch { /* never break the stream */ }
  })
  // One tick a second drives the board's live dots and its "last seen" column.
  // It runs ONLY in lite mode: the whole promise of this view is that it costs
  // nothing when you are not looking at it.
  boardTimer = setInterval(() => { if (gfxMode.value === 'lite') boardTick.value++ }, 1000)
  // The capability probe. Synchronous, one throwaway canvas, then released.
  gfxCaps.value = readCaps()
  gfxProbed.value = true
  // And the measured OFFER: read the stage's own draw timer, never a feeling.
  gfxOfferTimer = setInterval(() => {
    if (gfxMode.value !== 'full' || gfxOfferDismissed.value) return
    const st: any = (stageRef.value as any)?.bridgeStats?.()
    const r = st?.renderMs
    const p50 = typeof r?.p50 === 'number' ? r.p50 : null
    const n = typeof r?.n === 'number' ? r.n : 0
    if (shouldOfferLite({ mode: 'full', renderMsP50: p50, samples: n, dismissed: gfxOfferDismissed.value })) {
      gfxOfferMs.value = p50 as number
      gfxOffer.value = true
    }
  }, 15_000)
  offAlarmVerbs = ledger.onVerbs((batch) => {
    // #B24: your own agents, and only if you asked for sound.
    if (chimeOn.value && batch.some(d => d.mine)) chime()
    for (const d of batch) {
      if (d.verb !== 'alarm') continue
      raiseAlarm(String(d.eventType || '').replace(/([a-z])([A-Z])/g, '$1 $2').toUpperCase(), false)
      // Full frame rate for a beat: an alarm is the one moment the stage should
      // not be running at its lazy ambient rate.
      stageRef.value?.missionBoost?.(2000)
      break
    }
  })
})
function onCredsStorage(e: StorageEvent) {
  if (!e.key || /credential/i.test(e.key)) credsTick.value++
}

onUnmounted(() => {
  offAlarmVerbs?.()
  offActivityRaw?.()
  if (activityTimer) { clearInterval(activityTimer); activityTimer = null }
  if (boardTimer) { clearInterval(boardTimer); boardTimer = null }
  if (gfxOfferTimer) { clearInterval(gfxOfferTimer); gfxOfferTimer = null }
  if (alarmTimer) clearTimeout(alarmTimer)
  window.removeEventListener('storage', onCredsStorage)
})

onMounted(() => {
  // Once. No interval, by instruction. `refreshSeal` stays bound to the click.
  void refreshSeal()
})

/**
 * Dev seam for the battery, behind `?bridgedebug=1` ONLY — mirrors the canvas's
 * `__canvasProfile` hook, including removing itself on unmount (a stale global
 * pinned this component's closures once already, and made a gate pass for the
 * wrong reason).
 *
 * It exists because of the R1.6 lesson: the repeat-drop is invisible unless
 * something counts it, and a defect nothing counts is a defect nothing catches.
 */
function streamDebugOn(): boolean {
  if (typeof window === 'undefined') return false
  try { return new URLSearchParams(window.location.search).has('bridgedebug') } catch { return false }
}
onMounted(() => {
  /*
   * 🔴 LAYOUT FITTING IS NOT A DEBUG FEATURE, AND IT HAD BEEN ONE.
   *
   * `fitBridge()` and its listeners used to sit BELOW `if (!streamDebugOn())
   * return`, so the whole R9 fix — "the bridge fits from its OWN top edge,
   * self-correcting on resize and on banner dismiss" — only ever ran for a
   * session carrying `?bridgedebug=1`. Every real user got the un-fitted
   * layout, and every battery that passed did so BECAUSE it sets the flag.
   *
   * Measured on the canary at 1280x720 with the BETA banner up:
   *   .brg  y=88  h=656  ->  bottom 744  in a 720 viewport
   * i.e. 24px past the bottom — the same 24px R9 measured — which pushes the
   * rails' scroll containers off screen and collapses the ledger feed to 13px.
   * A gate can only see this WITHOUT the debug flag, which is why three
   * viewport gates went red the moment a battery ran without it.
   */
  fitBridge()
  window.addEventListener('resize', fitBridge)
  try {
    fitRo = new ResizeObserver(() => fitBridge())
    fitRo.observe(document.body)
  } catch { /* no ResizeObserver: the CSS fallback stands */ }

  // §B2 — the credential count comes from a plain localStorage-backed class, so
  // it needs an explicit nudge: once on mount, and again when another tab (or
  // the import modal, which writes the same key) changes it.
  credsTick.value++
  window.addEventListener('storage', onCredsStorage)

  // Dev seams only, from here down.
  if (!streamDebugOn()) return
  ;(window as any).__bridgeStream = () => ({
    totalEvents: ledger.totalEvents.value,
    ...ledger.replayWindow(),
  })
  // §BRIDGE R10 — the multi-registry fleet, observable. "mine grew" and "mine
  // grew for the reason I think" are different claims.
  ;(window as any).__bridgeAttention = () => attentionRef.value?.foreignState?.() ?? null
  ;(window as any).__bridgeFleet = () => ({
    localDids: fleetDidsFull.value.length,
    foreignDids: foreignDids.value.length,
    foreignRegistries: foreignRegistries.value.slice(),
    truncated: foreignPartial.value.slice(),
    connected: (cmdSessions.connectedKeys || []).slice(),
    reach: reachCount.value,
    mine: fleetDids.value.length,
    // §NONADMINBOARD: which source filled the registry list, and how many rows
    // the board actually got. A blank board must be provable, not eyeballed.
    dirSource: dirSource.value,
    boardRegistries: boardRegistries.value.length,
  })
})
onUnmounted(() => {
  window.removeEventListener('resize', fitBridge)
  fitRo?.disconnect(); fitRo = null
  if (typeof window !== 'undefined') { delete (window as any).__bridgeStream; delete (window as any).__bridgeFleet }
})

</script>

<style scoped>
/* §BOOTSEQ — the boot screen. Covers the stage column only; the app chrome
   stays reachable so a stuck boot can never trap anyone. */
.brg-boot {
  /* §BOOTSEQ-2 — scoped to the STAGE COLUMN. It used to sit in the bridge root
     with inset:0, so it dimmed the rails, sidebar and header too and read as a
     distorted full-page takeover. `.brg-center` is position:relative and
     pointer-events:none, so anchor here and re-enable pointers. */
  position: absolute; inset: 0; z-index: 40; pointer-events: auto;
  display: flex; align-items: center; justify-content: center;
  background: color-mix(in srgb, var(--nc-void, #05080f) 88%, transparent);
  backdrop-filter: none;                 /* never over a repainting canvas */
}
.brg-boot-card {
  width: min(92%, 30rem);
  background: var(--nc-elevated, var(--nc-surface));
  border: 1px solid var(--nc-border-strong, var(--nc-border));
  border-radius: 10px; padding: 1rem 1.1rem;
  box-shadow: var(--nc-shadow-lg, 0 20px 60px rgba(0,0,0,.6));
}
.brg-boot-hd { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; }
.brg-boot-title {
  font-family: var(--nc-font-mono, monospace); font-size: 0.72rem;
  letter-spacing: 0.14em; color: var(--nc-primary);
}
.brg-boot-sum { font-size: 0.68rem; color: var(--nc-text-muted); }
.brg-boot-bar {
  height: 2px; margin: 0.6rem 0 0.7rem;
  background: var(--nc-border-subtle, var(--nc-border)); border-radius: 2px; overflow: hidden;
}
.brg-boot-bar i { display: block; height: 100%; background: var(--nc-primary); transition: width .25s ease; }
.brg-boot-log { list-style: none; margin: 0; padding: 0; max-height: 15rem; overflow-y: auto; }
.brg-boot-row {
  display: flex; align-items: baseline; gap: 0.5rem;
  padding: 0.22rem 0; font-size: 0.74rem; color: var(--nc-text-secondary);
}
.brg-boot-gl { width: 1rem; text-align: center; color: var(--nc-text-muted); }
.brg-boot-row.is-ok .brg-boot-gl { color: var(--nc-success); }
.brg-boot-row.is-failed { color: var(--nc-danger); }
.brg-boot-row.is-failed .brg-boot-gl { color: var(--nc-danger); }
.brg-boot-row.is-skipped { color: var(--nc-warning); }
.brg-boot-row.is-running .brg-boot-gl { color: var(--nc-primary); }
.brg-boot-lb { flex: 1 1 auto; }
.brg-boot-tag {
  font-family: var(--nc-font-mono, monospace); font-size: 0.6rem;
  letter-spacing: 0.08em; color: var(--nc-text-disabled, var(--nc-text-muted));
}
.brg-boot-dt {
  flex: 0 1 auto; max-width: 46%; font-size: 0.68rem; color: var(--nc-text-muted);
  overflow-wrap: anywhere;
}
.brg-boot-retry {
  flex: 0 0 auto; font-family: var(--nc-font-mono, monospace); font-size: 0.6rem;
  padding: 0.1rem 0.35rem; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--nc-border); background: transparent; color: var(--nc-text-secondary);
}
.brg-boot-note { margin: 0.6rem 0 0.7rem; font-size: 0.72rem; color: var(--nc-text-muted); }
.brg-boot-actions { display: flex; justify-content: flex-end; }
.brg-door-sm.is-warn { border-color: var(--nc-danger); color: var(--nc-danger); }

/* §ACTIVITY — the window picker sits in the doors row and must not grow it. */
.brg-actwin { display: inline-flex; align-items: center; gap: 0.25rem; flex: 0 0 auto; }
/* Nothing inside the control group may be squeezed by a neighbour: the `min`
   spinner losing width is exactly the defect this guards. */
.brg-actwin > * { flex: 0 0 auto; }
.brg-actwin-k {
  font-family: var(--nc-font-mono, monospace);
  font-size: 0.62rem; letter-spacing: 0.12em;
  color: var(--nc-text-muted); padding-right: 0.15rem;
}
.brg-actwin-b { min-width: 2.2rem; }
.brg-actwin-in {
  width: 3.2rem; padding: 0.15rem 0.3rem;
  background: var(--nc-deep, var(--nc-surface));
  border: 1px solid var(--nc-border-subtle, var(--nc-border));
  border-radius: 4px; color: var(--nc-text-secondary);
  font-family: var(--nc-font-mono, monospace); font-size: 0.66rem;
}
/* §STAGENOTE — one caption slot for the whole stage. Full-width inside the
   wrapping doors row, so it always lands on its OWN line; fixed height, so
   appearing and disappearing shifts nothing; clipped rather than wrapped, so
   the longest string it will ever hold ("1,000 of 12,345 in orbit · 16
   registries") occupies the same box as the shortest. The full text is always
   on the title attribute, so clipping never hides information. */
.brg-stagenote {
  flex: 1 0 100%;
  display: block;
  min-height: 1.05rem; line-height: 1.05rem;
  font-family: var(--nc-font-mono, monospace);
  font-size: 0.66rem; color: var(--nc-text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  padding: 0.15rem 0 0;
}

/* ═══════════════════════════════════════════════════════════════════════════
   §BRIDGE — MISSION CONTROL AS THE BRIDGE OF THE SHIP.

   The stage owns the viewport; the HUD is a thin frame of instruments around
   it. Restraint charter: the boldness lives in ONE place (the stage), so
   everything here is quiet glass on theme tokens and nothing competes.

   Theme tokens only — no literal brand colours. The frame tints (gold / silver
   / emerald) are the ONLY hard-coded hues, because they are identity, not
   decoration: Frame A is gold on every surface in this product.
   ═══════════════════════════════════════════════════════════════════════════ */

/* The bridge fills the SHELL'S CONTENT AREA, not the viewport.
   It used to be `position: fixed; inset: var(--nc-header-h, 0) 0 0 0`, and
   `--nc-header-h` is defined nowhere in this app, so it resolved to 0 and the
   whole HUD escaped the layout: measured at three widths, the spine rendered at
   x=0 y=0 straight under the app header, and the fleet rail at x=10 straight
   under the 256px sidebar (`.sidebar-shell`, z-index 10000) — the rail the
   brief is ABOUT was the one hidden. DashboardLayout already offsets its
   content div (`pl-64`/`pl-16`/`pl-0`, following the user's sidebar mode) and
   puts `<main>` below a 64px header, so staying in normal flow inherits both
   offsets for free and keeps following them when the sidebar mode changes.
   `relative` also gives `.brg-hud` and `.bstage` (both `absolute; inset: 0`)
   the containing block they expect. */
.brg {
  /* ONE token for the pulse strip's height. BridgePulse sizes itself from it and
     the stage's honesty layer (LIVE badge, caption) offsets by it, so the two
     cannot drift apart. Before this, the badge was pinned `bottom: 1rem` inside
     a stage that spans the whole content area, and P3's pulse bar took exactly
     that strip: the LIVE readout ended up underneath it. */
  --brg-pulse-h: 42px;
  position: relative;
  /* FALLBACK ONLY — `fitBridge()` sets the real height from this element's own
     top edge. `--nc-header-h` is defined NOWHERE in this app (found in P1 and
     still true), so this calc silently used 64px while the real offset was 88
     with the BETA banner up: the bridge ran 24px past the viewport and the
     PULSE STRIP'S LABEL ROW WAS THE PART THAT FELL OFF. Measured 2026-08-19:
     .brg y=88 h=1016 -> bottom 1104 in a 1080 viewport; .bpl y=1062 h=42, so
     18 of its 42px were on screen. That is what "the bottom pulse could use
     refinement" was actually looking at. */
  height: calc(100vh - var(--nc-header-h, 64px));
  overflow: hidden;
  background: #05070f;
  color: var(--nc-text, #d6e2f2);
  font-family: var(--nc-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
}

/* The HUD floats over the stage and never blocks it: only the instruments
   themselves take pointer events, so the galaxy stays draggable between them. */
.brg-hud {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  pointer-events: none;
  /* DECLARED, not inferred. The stage and the HUD are absolute siblings, so
     without this their paint order depends on DOM order plus whatever the
     compositor decides — and a WebGL canvas gets promoted to its own layer on
     real GPU hardware but usually not under a software renderer. That is how a
     HUD can be perfect in a headless battery and invisible on the Commander's
     machine. z-index removes the question. */
  z-index: 2;
}
.brg-hud > * { pointer-events: auto; }

/* ── §BRIDGE R8 — CONTAINMENT ──────────────────────────────────────────────
   His reference: "galactic command looks much better ... check it here for
   visual improvement. but don't use such a hard grain filter."

   Comparing the two side by side, the thing Galactic Command has and this did
   not is not texture — it is CONTAINMENT. Its stage is a framed viewport with
   instruments arranged around it, so the composition has an edge and a centre.
   The bridge's canvas ran to all four window edges, so the panels floated on
   nothing and the eye had nowhere to rest.

   So: a hairline frame and a soft vignette, drawn ONCE as a static overlay.
   No grain (his explicit instruction — and film grain over a live canvas is a
   per-frame cost besides), no backdrop-filter (it re-blurs a repainting canvas
   every frame, which is what made his machine lag), no layout change. It costs
   the compositor one static layer and the renderer nothing at all. */
.brg::after {
  content: '';
  position: absolute;
  inset: 0;
  bottom: var(--brg-pulse-h);
  pointer-events: none;
  z-index: 1;                     /* above the canvas, below the HUD (z-index 2) */
  border-radius: 6px;
  /* The edge: a hairline that says where the viewport ends. */
  box-shadow:
    inset 0 0 0 1px rgba(120, 160, 210, 0.10),
    inset 0 0 42px rgba(4, 8, 18, 0.55);
  /* The vignette: the corners fall away so the centre carries the eye. Ellipse,
     not circle, or a wide viewport darkens its own middle. */
  background: radial-gradient(ellipse 120% 100% at 50% 45%, transparent 52%, rgba(2, 5, 12, 0.42) 100%);
}

/* ── §LITEBRIDGE ──────────────────────────────────────────────────────────
   The light bridge is not a skin. Everything here is a COST being removed:

   · no canvas at all (the stage is `v-if`, so no WebGL context exists);
   · no vignette/frame overlay — it exists to contain a stage that is not there,
     and it is one more composited layer for a machine that is short of them;
   · no backdrop-filter anywhere in the subtree. He measured that one himself:
     re-blurring behind a repainting canvas was what made his machine lag, and
     a machine that needs this view can least afford it;
   · no transitions on anything that updates on a tick.

   What it is NOT: a reduced view. Every instrument, door, quick action and
   modal is the same component running the same rails. */
.brg--lite { background: radial-gradient(ellipse 120% 90% at 50% 30%, #0a1020 0%, #060911 60%, #04070e 100%); }
.brg--lite::after { display: none; }
.brg--lite :deep(*) { backdrop-filter: none !important; -webkit-backdrop-filter: none !important; }
.brg--lite .brg-center { padding: 0.5rem; }
/*
 * A DEFINITE BOX, not a percentage.
 *
 * `.bbd { max-height: 100% }` did nothing: `.brg-center` is a grid item with an
 * INDEFINITE height, and a percentage max-height against an indefinite
 * container resolves to `none`. Measured at 1100x780 — the width where the name
 * column starts wrapping and rows grow from 26px to 62px — the board ran to
 * `bottom: 1093` in a 780px viewport, 313px of it off the bottom of the screen.
 * At 1280 and 1440 it happened to fit, which is why nothing caught it.
 *
 * `.brg-center` is already `position: relative`, so filling it is exact at every
 * size and the table scrolls inside instead of the board growing.
 */
.brg--lite .brg-board {
  position: absolute;
  inset: 0.5rem;
  max-height: none;
}

/* The three-state view control. */
.brg-gfx { display: inline-flex; align-items: center; gap: 0.2rem; }
.brg-gfx-k {
  font-size: 0.46rem; letter-spacing: 0.14em; color: var(--nc-text-dim, #6b7f9e);
  margin-right: 0.1rem;
}
.brg-gfx-b { min-width: 2.6rem; }

/* The measured offer. Sits over the stage column, never over the ledger. */
.brg-gfxoffer {
  pointer-events: auto;
  position: absolute; left: 50%; transform: translateX(-50%); top: 0.6rem;
  z-index: 6; display: flex; align-items: center; gap: 0.45rem;
  padding: 0.4rem 0.6rem; max-width: min(46rem, 92%);
  background: rgba(10, 15, 26, 0.96);
  border: 1px solid rgba(245, 196, 81, 0.35);
  border-radius: 4px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: 0.58rem; color: var(--nc-text, #d6e2f2);
}
.brg-gfxoffer-t { color: var(--nc-text-dim, #9db0c8); }

/* ── SPINE ───────────────────────────────────────────────────────────────── */
.brg-spine {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.4rem 0.85rem;
  background: linear-gradient(to bottom, rgba(5, 8, 16, 0.94), rgba(5, 8, 16, 0.72));
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.16));
  font-size: 0.64rem; letter-spacing: 0.12em;
  flex: 0 0 auto;
}
.brg-spine-id { display: flex; align-items: baseline; gap: 0.4rem; min-width: 0; }
.brg-spine-name {
  color: var(--nc-text, #d6e2f2); text-transform: uppercase; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 16rem;
}
.brg-spine-cur { color: var(--nc-primary, #22d3ee); font-size: 0.58rem; }

.brg-seal {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.2rem 0.5rem; border-radius: 3px; cursor: pointer;
  background: rgba(10, 16, 28, 0.8);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  color: var(--nc-text-dim, #8fa3c0);
  font-family: inherit; font-size: 0.62rem; letter-spacing: 0.1em;
}
.brg-seal:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 2px; }
.brg-seal-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nc-text-dim, #6b7f9e); }
.brg-seal-label { opacity: 0.75; }
.brg-seal-val { font-weight: 700; }
.brg-seal-age { opacity: 0.5; font-size: 0.55rem; }
.brg-seal--ok { border-color: rgba(34, 197, 94, 0.4); color: var(--nc-success, #22c55e); }
.brg-seal--ok .brg-seal-dot { background: var(--nc-success, #22c55e); box-shadow: 0 0 7px var(--nc-success, #22c55e); }
.brg-seal--breach { border-color: var(--nc-danger, #ff5252); color: var(--nc-danger, #ff5252); }
.brg-seal--breach .brg-seal-dot { background: var(--nc-danger, #ff5252); animation: brg-throb 900ms ease-in-out infinite; }
.brg-seal--unknown { opacity: 0.65; }

.brg-corridors { display: flex; gap: 0.25rem; }
.brg-cor {
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.15rem; height: 1.15rem; border-radius: 2px;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.2));
  font-size: 0.56rem; font-weight: 700; color: var(--nc-text-dim, #6b7f9e);
}
.brg-cor.is-live { color: var(--nc-text, #d6e2f2); border-color: rgba(34, 197, 94, 0.45); }
.brg-cor.is-down { color: var(--nc-warning, #f59e0b); border-color: rgba(245, 158, 11, 0.4); }
.brg-cor.is-gone { opacity: 0.35; }

.brg-alarm-slot { min-width: 0; flex: 0 1 auto; }
.brg-follow-note {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.14rem 0.4rem; border-radius: 2px;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  color: var(--nc-text-dim, #8fa3c0); font-size: 0.55rem; letter-spacing: 0.1em;
  white-space: nowrap; max-width: 22rem; overflow: hidden; text-overflow: ellipsis;
}
.brg-reach {
  display: inline-flex; align-items: center; gap: .25rem;
  text-decoration: none;
}
.brg-reach-n {
  font-size: 9px; min-width: 12px; text-align: center;
  padding: 0 .2rem; border-radius: 2px; font-weight: 600;
}
.brg-reach.is-solo { color: var(--nc-text-dim, #6b7f9e); }
.brg-reach.is-solo .brg-reach-n { background: rgba(120,160,210,.16); }
.brg-reach.is-wide { color: var(--nc-primary, #22d3ee); border-color: color-mix(in srgb, var(--nc-primary, #22d3ee) 45%, transparent); }
.brg-reach.is-wide .brg-reach-n { background: color-mix(in srgb, var(--nc-primary, #22d3ee) 24%, transparent); }
.brg-reach.is-deep { color: var(--nc-success, #34d399); border-color: color-mix(in srgb, var(--nc-success, #34d399) 50%, transparent); }
.brg-reach.is-deep .brg-reach-n { background: color-mix(in srgb, var(--nc-success, #34d399) 26%, transparent); }
.brg-find {
  display: flex; align-items: center; gap: .25rem;
  padding: 0 .35rem; height: 22px;
  border: 1px solid var(--nc-border, rgba(120,160,210,.22));
  border-radius: 3px; background: rgba(10, 16, 28, .55);
  color: var(--nc-text-dim, #6b7f9e);
  transition: border-color .15s ease, color .15s ease;
}
.brg-find.is-active { border-color: var(--nc-primary, #22d3ee); color: var(--nc-primary, #22d3ee); }
.brg-find-in {
  width: 8.5rem; background: none; border: 0; outline: none;
  color: var(--nc-text, #d6e2f2); font-size: 10px; letter-spacing: .03em;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
}
.brg-find-in::placeholder { color: var(--nc-text-dim, #6b7f9e); opacity: .8; }
.brg-find-in::-webkit-search-cancel-button { display: none; }
.brg-find-n {
  font-size: 9px; padding: 0 .25rem; border-radius: 2px;
  background: color-mix(in srgb, var(--nc-primary, #22d3ee) 22%, transparent);
  color: var(--nc-primary, #22d3ee);
}
.brg-find-x { background: none; border: 0; cursor: pointer; color: inherit; font-size: 12px; line-height: 1; padding: 0 2px; }
.brg-follow-cam { opacity: .55; margin-left: .25rem; }
.brg-follow-x {
  background: transparent; border: 0; cursor: pointer; padding: 0 0.15rem;
  color: inherit; font-size: 0.75rem; line-height: 1;
}
.brg-follow-x:hover { color: var(--nc-primary, #22d3ee); }
.brg-alarm {
  display: inline-block; padding: 0.18rem 0.45rem; border-radius: 2px;
  background: rgba(255, 82, 82, 0.14); border: 1px solid var(--nc-danger, #ff5252);
  color: var(--nc-danger, #ff5252); font-weight: 700; font-size: 0.6rem;
  animation: brg-throb 1.1s ease-in-out infinite;
}

/* Closed, the ticker is just its toggle and takes no room; open, it claims the
   middle of the spine. Keeping it out of the flex grow when closed is what stops
   the spine growing a second row at boot. */
.brg-spine-ticker {
  flex: 0 0 auto; min-width: 0; overflow: hidden;
  display: flex; align-items: center; gap: 0.4rem;
}
.brg-spine-ticker.is-open { flex: 1 1 auto; }
.brg-ticker-body { flex: 1 1 auto; min-width: 0; overflow: hidden; }
.brg-ticker-note {
  flex: 0 0 auto; font-size: 0.55rem; letter-spacing: 0.1em;
  color: var(--nc-text-dim, #6b7f9e); opacity: 0.75; white-space: nowrap;
}
.brg-ticker-toggle { flex: 0 0 auto; }
.brg-spine-doors {
  /* PINNED RIGHT. The Commander's complaint about AGORA was two things, and this
     is the second: "the fleet and open command buttons shift to the right of the
     screen". In a plain flex row, anything that grows to their left pushes them.
     `margin-left: auto` parks them against the spine's right edge, so the ticker
     (and its loading note) expand into the free space in the middle and these
     controls never move at all. */
  margin-left: auto;
  display: flex; align-items: center; gap: 0.35rem; flex: 0 0 auto;
}
.brg-door {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.5rem; border-radius: 3px; cursor: pointer;
  background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  color: var(--nc-text-dim, #8fa3c0); text-decoration: none;
  font-family: inherit; font-size: 0.6rem; letter-spacing: 0.12em;
}
.brg-door:hover { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.brg-door:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 2px; }
.brg-door-cmd { color: var(--nc-primary, #22d3ee); }
/* The lens is a state, so it reads as one when it is on. */
.brg-door-lens.is-on { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.brg-door-chime.is-on { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
/* R14.4: CLEAR is a deliberate, non-default choice, so it is marked as one.
   It is not an alarm colour — nothing is wrong when the sky is clear. */
.brg-door-atmos.is-off { color: var(--nc-warning, #ffb74d); border-color: var(--nc-warning, #ffb74d); }
/* R16.3 — ON means "amounts are hidden", so it is marked, not alarming. */
.brg-door-priv.is-on { color: var(--nc-primary); border-color: var(--nc-primary); }

/* ── R16.2 THE SELECTED AGENT ─────────────────────────────────────────────
   It leads the card, so it gets room: a name that can breathe, a rank beside
   it, and its own figures on the same grid the fleet used. */
.brg-card-sw {
  margin-left: auto; margin-right: 0.4rem;
  border: 1px solid var(--nc-border-subtle); background: transparent;
  color: var(--nc-text-secondary); border-radius: 3px;
  font-size: 0.55rem; letter-spacing: 0.12em; padding: 0.05rem 0.3rem;
  min-height: 20px; cursor: pointer;
}
.brg-card-sw:hover { color: var(--nc-text-primary); border-color: var(--nc-primary); }
.brg-sel { display: flex; flex-direction: column; gap: 0.45rem; padding: 0.15rem 0 0.1rem; }
.brg-sel-id { display: flex; flex-direction: column; gap: 0.15rem; }
.brg-sel-name {
  font-size: 0.92rem; line-height: 1.2; color: var(--nc-text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.brg-sel-rank {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.58rem; letter-spacing: 0.14em; color: var(--nc-warning);
}
.brg-sel-rank.is-none { color: var(--nc-text-muted); letter-spacing: 0.1em; }
.brg-sel-jobs {
  font-variant-numeric: tabular-nums; color: var(--nc-text-primary);
  border: 1px solid var(--nc-border-subtle); border-radius: 999px; padding: 0 0.28rem;
}
.brg-sel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 0.55rem; }
.brg-sel-note { margin: 0.2rem 0; font-size: 0.68rem; color: var(--nc-text-muted); font-style: italic; }
.brg-sel-fleetline {
  margin: 0.1rem 0 0; padding-top: 0.35rem;
  border-top: 1px solid var(--nc-border-subtle);
  font-size: 0.6rem; letter-spacing: 0.06em; color: var(--nc-text-muted);
}
/* R14.3: quiet when there is nothing, and only then. It earns attention by
   being right, not by being loud. */
.brg-door-attn.has-items { color: var(--nc-warning); border-color: var(--nc-warning); }
.brg-attn-badge {
  margin-left: 0.3rem; padding: 0 0.28rem; border-radius: 999px;
  background: var(--nc-warning); color: var(--nc-void, #04070b);
  font-size: 0.6rem; font-variant-numeric: tabular-nums;
}

/* ── RAILS ───────────────────────────────────────────────────────────────── */
.brg-body {
  flex: 1 1 auto; min-height: 0;
  display: grid; grid-template-columns: 20rem 1fr 20rem; gap: 0.65rem;
  padding: 0.65rem;
  pointer-events: none;
}
.brg-rail {
  display: flex; flex-direction: column; gap: 0.65rem; min-height: 0;
  pointer-events: auto;
  transition: opacity 260ms ease, transform 260ms ease;
  /* When the viewport is short (a wide-but-shallow laptop window, or the spine
     grown by a banner), the rail SCROLLS. It used to squeeze its children
     instead: `flex: 1 1 auto; min-height: 0` lets a scroll body shrink all the
     way to zero, which clips its rows away while the header keeps overflowing
     and stays on screen — the panels "disappear" and leave floating labels. */
  overflow-y: auto; overflow-x: hidden;
  scrollbar-width: thin;
}
.brg-center { pointer-events: none; position: relative; }
/* Floor, so a squeeze degrades into a scroll rather than a vanishing act. */
.brg-grow { flex: 1 1 auto; min-height: 9rem; }

/* ── RAIL COLLAPSE ────────────────────────────────────────────────────────
   A hairline on the rail's inner edge. Almost invisible until looked for, and
   it costs 10px of width - the panel itself is what should own the screen, or
   the stage should. Collapsed, a rail is JUST this strip. */
.brg-railtab {
  position: absolute; top: 0; bottom: 0; width: 10px;
  display: flex; align-items: center; justify-content: center;
  padding: 0; cursor: pointer;
  background: transparent; border: 0;
  color: var(--nc-text-dim, #6b7f9e);
  opacity: 0.16; transition: opacity 160ms ease;
  z-index: 3;
}
.brg-railtab:hover, .brg-railtab:focus-visible { opacity: 0.85; }
.brg-railtab:focus-visible { outline: 1px solid var(--nc-primary, #22d3ee); outline-offset: -1px; }
.brg-railtab-mark { font-size: 0.7rem; line-height: 1; }
.brg-railtab-l { right: -2px; }
.brg-railtab-r { left: -2px; }
.brg-rail { position: relative; }
.brg-rail.is-closed { overflow: visible; gap: 0; }

/* The grid gives a closed rail its 10px back and hands the rest to the stage. */
.brg-body.l-closed { grid-template-columns: 0.85rem 1fr 20rem; }
.brg-body.r-closed { grid-template-columns: 20rem 1fr 0.85rem; }
.brg-body.l-closed.r-closed { grid-template-columns: 0.85rem 1fr 0.85rem; }

/* §BRIDGE R11 #2 — the way back out of stage focus. Deliberately quiet (it sits
   over the stage he wanted to see) but it is TEXT, not a 10px invisible strip. */
.brg-focus-exit {
  position: absolute; left: 50%; bottom: 0.9rem; transform: translateX(-50%);
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.3rem 0.7rem; border-radius: 999px;
  font-size: 0.62rem; letter-spacing: 0.08em; font-weight: 600;
  color: var(--nc-text-dim, #6b7f9e);
  background: color-mix(in srgb, var(--nc-bg, #05080f) 72%, transparent);
  border: 1px solid color-mix(in srgb, var(--nc-primary, #22d3ee) 22%, transparent);
  cursor: pointer; pointer-events: auto; opacity: 0.55;
  transition: opacity 160ms ease, color 160ms ease;
  z-index: 4;
}
.brg-focus-exit:hover, .brg-focus-exit:focus-visible {
  opacity: 1; color: var(--nc-primary, #22d3ee);
}
.brg-focus-exit-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--nc-primary, #22d3ee); opacity: 0.7;
}
/* While the panels are hidden their handles stop being a secret. */
.brg--focus .brg-railtab { opacity: 0.5; }

/* Demo mode: rails out of the way, pure stage. Also what attract mode uses. */
.brg--demo .brg-rail { opacity: 0; pointer-events: none; }
.brg--demo .brg-rail-l { transform: translateX(-1rem); }
.brg--demo .brg-rail-r { transform: translateX(1rem); }

.brg-card {
  /* No `backdrop-filter` here. It sat directly over a continuously repainting
     WebGL canvas, which means the browser re-blurs that region EVERY FRAME — a
     real cost on the Commander's machine ("it even lags for me a lot") — and a
     filtered element over a promoted canvas layer is exactly the case where the
     panel's own fill gets dropped while its text and border survive. The card is
     already 82% opaque glass; the blur was buying almost nothing. */
  background: rgba(8, 12, 22, 0.82);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 4px;
  /* §BRIDGE R8 — an instrument should read as a lit thing, not a dark rectangle
     on a dark field. Two static shadows do it: a faint inner glow in the accent
     so the panel has interior depth, and a soft drop so it sits ABOVE the stage
     rather than in it. Both are painted once; neither touches the canvas. */
  box-shadow:
    inset 0 1px 0 rgba(150, 200, 240, 0.055),
    inset 0 0 22px rgba(34, 211, 238, 0.035),
    0 6px 18px rgba(0, 0, 0, 0.34);
}
/* The header carries a hairline of the accent, so the eye finds the title first. */
.brg-card-hdr { position: relative; }
.brg-card-hdr::after {
  content: '';
  position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
  background: linear-gradient(to right,
    color-mix(in srgb, var(--nc-primary, #22d3ee) 34%, transparent),
    transparent 62%);
  pointer-events: none;
}
.brg-card-hdr {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
}
.brg-card-title { font-size: 0.66rem; letter-spacing: 0.18em; color: var(--nc-text, #d6e2f2); }
.brg-card-sub { font-size: 0.55rem; letter-spacing: 0.1em; color: var(--nc-text-dim, #6b7f9e); }
.brg-card-link { font-size: 0.56rem; letter-spacing: 0.1em; color: var(--nc-text-dim, #8fa3c0); text-decoration: none; }
.brg-card-link:hover { color: var(--nc-primary, #22d3ee); }

/* FLEET */
.brg-fleet-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.3rem; padding: 0.55rem 0.6rem; }
.brg-stat { display: flex; flex-direction: column; gap: 0.1rem; cursor: help; }
.brg-stat-val { font-size: 1.05rem; font-weight: 700; line-height: 1.1; }
.brg-stat-lbl { font-size: 0.52rem; letter-spacing: 0.12em; color: var(--nc-text-dim, #6b7f9e); }
.brg-v-cyan { color: var(--nc-primary, #22d3ee); }
.brg-v-blue { color: #82b1ff; }
.brg-v-green { color: var(--nc-success, #22c55e); }
.brg-v-gold { color: #ffc14d; font-size: 0.8rem; }

.brg-ach {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem;
  padding: 0 0.6rem 0.55rem; font-size: 0.55rem; letter-spacing: 0.08em;
}
.brg-ach-badge { color: var(--nc-text-dim, #8fa3c0); }
.brg-ach-avt { color: var(--nc-success, #22c55e); }
.brg-ach-claim {
  margin-left: auto; padding: 0.15rem 0.4rem; border-radius: 2px; cursor: pointer;
  background: transparent; border: 1px solid var(--nc-success, #22c55e);
  color: var(--nc-success, #22c55e); font-family: inherit; font-size: 0.55rem; letter-spacing: 0.1em;
}
.brg-ach-claim:disabled { opacity: 0.5; cursor: default; }

.brg-cta { padding: 0.7rem 0.6rem; }
.brg-cta-text { margin: 0 0 0.55rem; font-size: 0.62rem; line-height: 1.6; color: var(--nc-text-dim, #8fa3c0); }
.brg-cta-btn {
  width: 100%; padding: 0.4rem; border-radius: 3px; cursor: pointer;
  background: var(--nc-primary, #22d3ee); border: 0; color: #04101a;
  font-family: inherit; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.14em;
}
.brg-cta-btn:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 2px; }

/* VITALS */
.brg-vit-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0.22rem 0.6rem; font-size: 0.62rem;
}
.brg-vit-k { color: var(--nc-text-dim, #6b7f9e); letter-spacing: 0.12em; font-size: 0.54rem; }
.brg-vit-v { color: var(--nc-text, #d6e2f2); font-weight: 600; }
.brg-vit-note {
  margin: 0.15rem 0 0; padding: 0.25rem 0.6rem 0.4rem;
  font-size: 0.52rem; line-height: 1.5; color: var(--nc-text-dim, #6b7f9e); cursor: help;
}
.brg-h-ok { color: var(--nc-success, #22c55e); }
.brg-h-warn { color: var(--nc-warning, #f59e0b); }
.brg-h-wait { color: var(--nc-text-dim, #6b7f9e); }
.brg-vit-doors {
  display: flex; flex-wrap: wrap; gap: 0.25rem;
  padding: 0.4rem 0.6rem 0.55rem;
  border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.12));
}
.brg-door-sm.is-on { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.brg-door-sm {
  /* These are <button>s since R3 (they open the in-view terminal rather than
     navigating), so the UA's button chrome has to be reset explicitly. */
  padding: 0.12rem 0.38rem; border-radius: 2px; text-decoration: none;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.2));
  background: transparent; cursor: pointer; font-family: inherit;
  color: var(--nc-text-dim, #8fa3c0); font-size: 0.53rem; letter-spacing: 0.12em;
}
.brg-door-sm:hover { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.brg-door-sm:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 1px; }

@keyframes brg-throb { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* ── RESPONSIVE ──────────────────────────────────────────────────────────
   T3 (small screens): the HUD stacks and the stage becomes a banner behind
   it. Pocket mode stays the real phone answer; this only has to stay usable. */
@media (max-width: 1280px) {
  .brg-body { grid-template-columns: 17rem 1fr 17rem; }
  .brg-body.l-closed { grid-template-columns: 0.85rem 1fr 17rem; }
  .brg-body.r-closed { grid-template-columns: 17rem 1fr 0.85rem; }
  .brg-body.l-closed.r-closed { grid-template-columns: 0.85rem 1fr 0.85rem; }
}
@media (max-width: 1024px) {
  /* Stacked: the rails become the page and the stage is a banner behind them,
     so the bridge grows with its content instead of being clipped to one screen. */
  .brg { height: auto; min-height: calc(100vh - var(--nc-header-h, 64px)); }
  .brg-body {
    grid-template-columns: 1fr;
    grid-template-areas: 'l' 'r';
    padding: 0.5rem;
  }
  .brg-rail-l { grid-area: l; }
  .brg-rail-r { grid-area: r; }
  .brg-center { display: none; }
  .brg-spine { flex-wrap: wrap; row-gap: 0.35rem; }
  .brg-spine-ticker { order: 10; flex-basis: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .brg-rail { transition: none; }
  .brg-seal--breach .brg-seal-dot, .brg-alarm { animation: none; }
}
</style>
