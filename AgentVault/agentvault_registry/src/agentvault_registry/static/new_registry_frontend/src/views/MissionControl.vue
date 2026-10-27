<!-- MissionControl.vue — the post-login dashboard: fleet + pulse, three folded strips (§MCFOLD), the desk (§ONBOARDQOL P7) -->
<template>
  <div class="nc-page nc-mission-control">

    <!-- ═══ YOUR FLEET + NETWORK PULSE (above everything) ═══ -->
    <div class="mc-hero">
      <div class="mc-top-grid">
        <!-- YOUR FLEET -->
        <div class="mc-fleet-card" data-tour="mc-fleet">
          <div class="mc-card-hdr">
            <span class="mc-card-title">{{ t('mc.yourFleet.title', 'YOUR FLEET') }}</span>
            <span class="mc-card-sub">{{ fleetRead !== 'read' ? '' : (fleetData.agent_count || 0) === 1 ? tp('mc.fleet.agentsOne', '{n} agent', { n: 1 }) : tp('mc.fleet.agentsMany', '{n} agents', { n: fleetData.agent_count || 0 }) }}</span>
          </div>
          <template v-if="fleetData.agent_count > 0">
            <div class="mc-fleet-grid">
              <div class="mc-fleet-stat">
                <span class="mc-fleet-val mc-val-cyan">{{ formatNumber(fleetData.total_liquid_balance) }}</span>
                <span class="mc-fleet-lbl">LIQUID {{ fleetCurrency }}</span>
              </div>
              <div class="mc-fleet-stat">
                <span class="mc-fleet-val mc-val-blue">{{ formatNumber(fleetData.total_staked_balance) }}</span>
                <span class="mc-fleet-lbl">LOCKED {{ fleetCurrency }}</span>
              </div>
              <div class="mc-fleet-stat">
                <span class="mc-fleet-val mc-val-green">{{ formatNumber(fleetData.total_balance) }}</span>
                <span class="mc-fleet-lbl">{{ t('mc.yourFleet.totalBalance', 'TOTAL BALANCE') }}</span>
              </div>
              <div class="mc-fleet-stat">
                <span class="mc-fleet-val mc-val-purple">{{ parseFloat(fleetData.aggregate_reputation_score || 0).toFixed(1) }}</span>
                <span class="mc-fleet-lbl">{{ t('mc.yourFleet.avgReputation', 'AVG REPUTATION') }}</span>
              </div>
            </div>
            <div v-if="achievementCount > 0" class="mc-fleet-achievements">
              <span class="mc-fleet-ach-badge">{{ achievementCount }}/{{ achievementTotal }} achievements</span>
              <span class="mc-fleet-ach-avt">{{ achievementAvt }} {{ fleetCurrency }} paid</span>
              <!-- §FEPARITY-2: pending payouts were visible-but-unclaimable — the
                   claim rail existed backend-side with no FE caller. -->
              <button
                v-if="achievementPending > 0"
                class="mc-fleet-ach-claim"
                :disabled="claimingAchievements"
                :title="`Pay ${achievementPending} pending achievement payout${achievementPending > 1 ? 's' : ''} to your first active agent`"
                @click="claimAchievements"
              >{{ claimingAchievements ? 'Claiming…' : `Claim ${achievementPending} pending` }}</button>
            </div>
            <div v-if="!authStore.agentToken" class="mc-fleet-hint">
              <span class="mc-hint-icon">!</span>
              <span class="mc-hint-text">{{ t('mc.hints.selectAgent', 'Select an agent in the top-right to unlock governance, contracts, and disputes.') }}</span>
            </div>
          </template>
          <template v-else-if="fleetRead === 'read'">
            <div class="mc-fleet-cta">
              <div class="mc-cta-icon"><Icon name="mdi:rocket-launch" /></div>
              <p class="mc-cta-text">{{ t('mc.firstRun.lead', 'No agents yet. Create your first agent to unlock governance, contracts, and trading.') }}</p>
              <div class="mc-cta-btns">
                <!-- §pass50.7 — Quick-onboard takes priority (30s flow) -->
                <button type="button" class="mc-cta-btn mc-cta-primary" data-tour="mc-create-agent" @click="uiStore.openQuickAgentModal()">{{ t('mc.firstRun.create', 'Create your wallet agent') }}</button>
                <router-link to="/tutorials" class="mc-cta-btn mc-cta-secondary">{{ t('mc.firstRun.tutorials', 'API Tutorials') }}</router-link>
              </div>
              <!-- D19: the old hint said "use the agent selector after creation" — but the quick
                   modal authenticates the new agent itself, so the sentence sent a person to a
                   control they did not need. Say what actually happens. -->
              <p class="mc-cta-hint">{{ t('mc.firstRun.hint', 'Your new agent becomes the acting agent by itself. The agent selector (top-right) is for switching between agents later.') }}</p>
            </div>
          </template>
          <!-- §FESUITE (the loading sweep): "no agents yet" only after the fleet's own read; a member with agents saw the
               first-run card at every sign-in while the read was out. A read that failed says so: could not read is not none. -->
          <p v-else class="mc-fleet-reading" role="status">{{ fleetRead === 'unread' ? t('mc.yourFleet.unread', 'Your fleet could not be read just now.') : t('common.loading', 'Loading…') }}</p>
        </div>

        <!-- NETWORK PULSE -->
        <div class="mc-pulse-card" data-tour="mc-pulse">
          <div class="mc-card-hdr">
            <span class="mc-card-title">{{ t('mc.networkPulse.title', 'NETWORK PULSE') }}</span>
            <span class="mc-card-sub">24h snapshot</span>
          </div>
          <div class="mc-pulse-metrics">
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-cyan" :style="{ height: pulseBarHeight(totalSupply, 5000000) }"></div>
              <span class="mc-pm-val">{{ analyticsData ? formatCompact(totalSupply) : '—' }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.supply', 'SUPPLY') }}</span>
            </div>
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-green" :style="{ height: pulseBarHeight(fleetData.treasury_balance, 500000) }"></div>
              <span class="mc-pm-val mc-val-green">{{ fleetData.treasury_balance == null ? '—' : formatCompact(fleetData.treasury_balance) }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.treasury', 'TREASURY') }}</span>
            </div>
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-blue" :style="{ height: pulseBarHeight(stakedSupply, 2000000) }"></div>
              <span class="mc-pm-val mc-val-blue">{{ analyticsData ? formatCompact(stakedSupply) : '—' }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.staked', 'LOCKED') }}</span>
            </div>
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-purple" :style="{ height: pulseBarHeight(uniqueAgents, 1000) }"></div>
              <span class="mc-pm-val mc-val-purple">{{ analyticsData ? uniqueAgents : '—' }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.agents', 'AGENTS') }}</span>
            </div>
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-cyan" :style="{ height: pulseBarHeight(totalEvents, 500000) }"></div>
              <span class="mc-pm-val">{{ analyticsData ? formatCompact(totalEvents) : '—' }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.events', 'EVENTS') }}</span>
            </div>
            <div class="mc-pm">
              <div class="mc-pm-bar mc-pm-green" :style="{ height: pulseBarHeight(fedPeers, 10) }"></div>
              <span class="mc-pm-val mc-val-cyan">{{ fedPeers ?? '—' }}</span>
              <span class="mc-pm-lbl">{{ t('mc.networkPulse.fedPeers', 'FED PEERS') }}</span>
            </div>
          </div>
          <div class="mc-pulse-footer">
            <!-- §FESUITE (the loading sweep): a figure is the page's dash until its own read answered (a 0 says "none") -->
            <span class="mc-pulse-label">{{ analyticsData ? formatCompact(liquidSupply) : '—' }} liquid</span>
            <span class="mc-pulse-dot"></span>
            <span class="mc-pulse-label">{{ analyticsData ? formatCount(transactionEvents) : '—' }} txns</span>
          </div>
        </div>
      </div>
    </div>

    <!-- §MCFOLD (2026-09-02) — HIS ask: the live ledger collapsible and COLLAPSED from the start
         "so it doesn't lock up the user when the network is really active"; the AGORA strip
         (the landing page's two rows: the live ticker tape and the listings) here under the
         Network Pulse instead of above the hero; each of the three folds INDEPENDENTLY.
         A folded strip mounts nothing (no socket, no poll). The ledger is the bridge's
         burst-safe consumer over the ONE shared stream — Mission Control used to open three
         raw sockets itself and re-render the whole view per event. -->
    <div class="mc-folds" data-testid="mc-folds">
      <McSection id="tape" :title="t('mc.section.tape', 'AGORA · LIVE TICKER')" icon="mdi:chart-line-variant">
        <ExchangeTicker rows="tape" :cta="false" />
      </McSection>
      <McSection id="listings" :title="t('mc.section.listings', 'AGORA · LISTINGS')" icon="mdi:chart-candlestick">
        <ExchangeTicker rows="main" />
      </McSection>
      <McSection id="ledger" :title="t('mc.section.ledger', 'LIVE LEDGER')" icon="mdi:swap-horizontal">
        <template v-if="mcFxEnabled && mcFxEdges.length" #summary>
          <span v-for="e in mcFxEdges" :key="e.key" class="mc-fx-edge" data-testid="mc-fx-edge">1 {{ e.b }} = {{ e.rate }} {{ e.a }}</span>
        </template>
        <McLedger />
      </McSection>
    </div>

    <div class="nc-dashboard-container">

      <!-- §ONBOARDQOL P7 (2026-09-02) — HIS ask: "the bottom panels used would be much better
           replaced with modularity from cockpit desk." Where the desk exists, a fixed
           selection of its panes replaces the four sovereign-state cards below; where the
           desk flag is off (the 13 ops) the cards stay, because there is no modularity to
           replace them with. Gated on the router's own predicate, never a second copy. -->
      <DeskArea v-if="cockpitDeskEnabled" />
      <div v-else :class="['mc-sov', senateActive ? 'mc-sov-active' : 'mc-sov-quiet']">

        <!-- Active Senate: full card on the left -->
        <div v-if="senateActive" class="mc-senate-card mc-sov-senate">
          <div class="mc-card-hdr">
            <span class="mc-card-title"><Icon name="mdi:gavel" class="mc-hdr-ico mc-ico-amber" />{{ t('mc.agentSenate.title', 'AGENT SENATE') }}</span>
            <router-link to="/senate" class="mc-card-link">{{ t('mc.viewFloor', 'View Floor →') }}</router-link>
          </div>
          <div class="mc-senate-list">
            <router-link v-for="p in senateProposals" :key="p.id" to="/senate" class="mc-prop">
              <div class="mc-prop-top">
                <span class="mc-prop-id">#{{ p.id }}</span>
                <span class="mc-prop-title">{{ p.title }}</span>
                <span :class="['mc-prop-status', 'mc-ps-' + senateStatusKey(p)]">
                  <i class="mc-prop-status-dot"></i>{{ senateStatusLabel(p) }}
                </span>
              </div>
              <div :class="['mc-prop-bar', { 'mc-prop-bar-empty': senateTotalVotes(p) === 0 }]">
                <div class="mc-prop-seg mc-prop-seg-for" :style="{ width: senateForPct(p) + '%' }"></div>
                <div class="mc-prop-seg mc-prop-seg-against" :style="{ width: senateAgainstPct(p) + '%' }"></div>
              </div>
              <div class="mc-prop-foot">
                <span class="mc-prop-leg mc-prop-leg-for"><i class="mc-prop-dot mc-prop-dot-for"></i>{{ p.votes_for || 0 }}</span>
                <span class="mc-prop-leg mc-prop-leg-against"><i class="mc-prop-dot mc-prop-dot-against"></i>{{ p.votes_against || 0 }}</span>
                <span class="mc-prop-meta">{{ p.total_voters || 0 }} voted</span>
                <span v-if="senateEndsIn(p)" class="mc-prop-ends">{{ senateEndsIn(p) }}</span>
              </div>
            </router-link>
          </div>
        </div>

        <!-- Quiet Senate: slim status strip -->
        <div v-else class="mc-senate-strip">
          <span class="mc-sstr-orb"></span>
          <span class="mc-sstr-label">{{ t('mc.agentSenate.label', 'AGENT SENATE') }}</span>
          <span class="mc-sstr-sep">·</span>
          <span class="mc-sstr-msg" role="status">{{ senateRead === 'read' ? t('mc.noActiveProposals', 'No active proposals') : senateRead === 'unread' ? t('mc.senateUnread', 'Proposals could not be read just now') : t('common.loading', 'Loading…') }}</span>
          <router-link to="/senate" class="mc-sstr-link">{{ t('mc.viewFloor', 'View Floor →') }}</router-link>
        </div>

        <!-- Trust 3-grid (LOCK TIERS / ECONOMY / TOP REP) -->
        <div class="mc-trust-3grid">
          <!-- LOCK TIERS (enhanced) -->
          <div class="mc-trust-card mc-card-apy">
            <div class="mc-card-hdr">
              <span class="mc-card-title"><Icon name="mdi:percent" class="mc-hdr-ico mc-ico-green" />{{ mcRatesOn ? t('mc.apyTiers.title', 'LOCK TIERS') : t('mc.apyTiers.offTitle', 'LOCKS') }}</span>
              <router-link v-if="mcStakingOn" to="/locks" class="mc-card-link">{{ t('mc.stakeAction', 'Lock →') }}</router-link>
            </div>
            <div class="mc-apy-list" v-if="mcRatesOn && apyTiers.length > 0">
              <div class="mc-apy-colhdr"><span>LOCK</span><span>BASE</span><span>PAYOUT</span></div>
              <div class="mc-apy-row-v2" v-for="tier in apyTiers" :key="tier.lock">
                <span class="mc-apy-lock"><b>{{ tier.lock }}</b><i>d</i></span>
                <div class="mc-apy-bar-track">
                  <div class="mc-apy-bar-fill" :style="{ width: (maxApyPct > 0 ? Math.min(100, (parseFloat(tier.apy)/maxApyPct)*100) : 0) + '%' }"></div>
                </div>
                <span class="mc-apy-val-v2">{{ tier.apy }}<i>%</i></span>
              </div>
            </div>
            <div v-else class="mc-estate">
              <div class="mc-estate-icon mc-estate-green"><Icon name="mdi:percent" /></div>
              <!-- §FESUITE (2026-10-04): an unread config is not "switched off" -->
              <p class="mc-estate-msg">{{ mcRatesOn ? t('mc.apyTiers.warming', 'Lock tiers warming up') : mcCfgReadFailed ? t('common.readFailed.text', 'This could not be read just now.') : t('mc.apyTiers.offMsg', 'Nothing is paid on locked units on this registry.') }}</p>
              <router-link v-if="mcStakingOn" to="/locks" class="mc-estate-cta">{{ t('mc.apyTiers.openStaking', 'Open locks →') }}</router-link>
            </div>
          </div>

          <!-- ECONOMY PULSE (new, sourced from analyticsData) -->
          <div class="mc-trust-card mc-card-econ">
            <div class="mc-card-hdr">
              <span class="mc-card-title"><Icon name="mdi:chart-line" class="mc-hdr-ico mc-ico-cyan" />{{ t('mc.economyPulse.title', 'ECONOMY PULSE') }}</span>
            </div>
            <div class="mc-econ-grid">
              <div class="mc-econ-cell mc-ec-green" :class="{ 'mc-econ-zero': !economyStats.transfers }">
                <div class="mc-econ-ico"><Icon name="mdi:bank-transfer" /></div>
                <span class="mc-econ-val mc-val-green">{{ analyticsData ? formatCompact(economyStats.transfers) : '—' }}</span>
                <span class="mc-econ-lbl">{{ t('mc.economyPulse.transfers', 'TRANSFERS') }}</span>
              </div>
              <div class="mc-econ-cell mc-ec-cyan" :class="{ 'mc-econ-zero': !economyStats.crossFrame }">
                <div class="mc-econ-ico"><Icon name="mdi:swap-horizontal-bold" /></div>
                <span class="mc-econ-val mc-val-cyan">{{ analyticsData ? formatCompact(economyStats.crossFrame) : '—' }}</span>
                <span class="mc-econ-lbl">{{ t('mc.economyPulse.crossFrame', 'CROSS-FRAME') }}</span>
              </div>
              <div class="mc-econ-cell mc-ec-orange" :class="{ 'mc-econ-zero': !economyStats.fees }">
                <div class="mc-econ-ico"><Icon name="mdi:percent" /></div>
                <span class="mc-econ-val mc-val-orange">{{ analyticsData ? formatCompact(economyStats.fees) : '—' }}</span>
                <span class="mc-econ-lbl">{{ t('mc.economyPulse.feeEvents', 'FEE EVENTS') }}</span>
              </div>
              <div class="mc-econ-cell mc-ec-blue" :class="{ 'mc-econ-zero': !economyStats.stakeActs }">
                <div class="mc-econ-ico"><Icon name="mdi:lock" /></div>
                <span class="mc-econ-val mc-val-blue">{{ analyticsData ? formatCompact(economyStats.stakeActs) : '—' }}</span>
                <span class="mc-econ-lbl">{{ t('mc.economyPulse.stakeActs', 'LOCKS') }}</span>
              </div>
            </div>
            <div class="mc-econ-foot">
              <span class="mc-econ-foot-dot"></span>
              <span class="mc-econ-foot-txt">{{ econFoot }}</span>
            </div>
          </div>

          <!-- TOP REPUTATION (enhanced) -->
          <div class="mc-trust-card mc-card-rep">
            <div class="mc-card-hdr">
              <span class="mc-card-title"><Icon name="mdi:trophy-variant" class="mc-hdr-ico mc-ico-purple" />{{ t('mc.topReputation.title', 'TOP REPUTATION') }}</span>
              <router-link to="/discovery" class="mc-card-link">All →</router-link>
            </div>
            <div class="mc-rep-list" v-if="topAgents.length > 0">
              <div class="mc-rep-row-v2" v-for="(agent, idx) in topAgents" :key="agent.did">
                <span :class="['mc-rep-badge', 'mc-rep-badge-' + (idx+1)]">{{ idx + 1 }}</span>
                <div class="mc-rep-body">
                  <div class="mc-rep-name-row">
                    <span class="mc-rep-name-v2">{{ agent.name || (agent.did?.slice(-10) || '—') }}</span>
                    <span class="mc-rep-score-v2">{{ agent.score }}</span>
                  </div>
                  <div class="mc-rep-bar-track">
                    <div class="mc-rep-bar-fill" :style="{ width: (maxRepScore > 0 ? Math.min(100, (agent.score/maxRepScore)*100) : 0) + '%' }"></div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="rankingsRead !== 'read'" class="mc-estate">
              <p class="mc-estate-msg" role="status">{{ rankingsRead === 'unread' ? t('mc.topReputation.unread', 'Rankings could not be read just now') : t('common.loading', 'Loading…') }}</p>
            </div>
            <div v-else class="mc-estate">
              <div class="mc-estate-icon mc-estate-purple"><Icon name="mdi:telescope" /></div>
              <p class="mc-estate-msg">{{ t('mc.topReputation.none', 'No rankings yet') }}</p>
              <span class="mc-estate-sub">Reputation builds as agents transact</span>
              <router-link to="/discovery" class="mc-estate-cta">Explore agents →</router-link>
            </div>
          </div>
        </div>

      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import ExchangeTicker from '@/components/exchange/ExchangeTicker.vue'
import McSection from '@/components/dashboard/McSection.vue'
/**
 * MissionControl.vue — the post-login DASHBOARD (restored 2026-09-02 by §DASHRESTORE from the
 * 2026-08-18 snapshot; the 3D bridge lives at /bridge).
 *
 * §ONBOARDQOL P7 (2026-09-02): the browser-side SYSTEM HEALTH probes this file was once
 * named for (OWL21 v3: five parallel pings, a health score, a service matrix) were REMOVED
 * on the Commander's word — "health system display on mission-control is not needed there in
 * this size". The health tooling lives at /health-monitor and in the admin watchtower. What
 * remains: YOUR FLEET, NETWORK PULSE (a 24h snapshot of the federation), the LIVE EVENT
 * LEDGER, and — where the cockpit desk is enabled — a fixed selection of its panes in place
 * of the old sovereign-state cards (DeskArea.vue).
 */
import { ref, computed, onMounted, onUnmounted, reactive, watch, defineAsyncComponent } from 'vue'
import { useAlive } from '@/composables/useAlive'

import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { useTegStore } from '@/stores/teg'
import { useStakingStore } from '@/stores/staking'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig, loadRegistryConfig } from '@/composables/useRegistryConfig'
// §DASHRESTORE — this view predates the §LOCALESWEEP (2026-08-31) by two weeks,
// so it came back carrying bare toLocaleString() calls that format in the OS
// locale, not the app's. Same module the other ~130 files use.
import { appLocale } from '@/services/appLocale'
import { useFederationStore } from '@/stores/federation'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { useLogger } from '@/composables/useLogger'
import { useCurrency } from '@/composables/useCurrency'
import { liveNames } from '@/services/ledgerNames'

const log = useLogger('MissionControl')

// Stores
const authStore = useAuthStore()
const agentStore = useAgentStore()
const tegStore = useTegStore()
const stakingStore = useStakingStore()
const { t, tp } = useI18n()
// FX multi-currency (2026-06-03): "Your Fleet" balances are in the LOCAL frame's
// settlement currency — AVT on Frame A/B, BVT on Frame C. Was hardcoded "AVT".
const { localCurrency } = useCurrency()
const fleetCurrency = computed(() => localCurrency.value)
const federationStore = useFederationStore()
const uiStore = useUIStore()
// §ONBOARDQOL P7 — the desk area is async so a registry with the flag OFF never loads it.
const DeskArea = defineAsyncComponent(() => import('@/components/cockpit/DeskArea.vue'))
// §MCFOLD — the ledger strip (BridgeLedger + the stream) loads only when its fold opens.
const McLedger = defineAsyncComponent(() => import('@/components/dashboard/McLedger.vue'))
const { cockpitDeskEnabled, config: mcRegistryCfg, readFailed: mcCfgReadFailed } = useRegistryConfig()
// §BAFIN (2026-10-01): no rate and no lock link where the registry switched locking (payouts) off.
const mcStakingOn = computed(() => mcRegistryCfg.value.staking_enabled !== false)
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const mcRatesOn = computed(() => mcRegistryCfg.value.staking_rewards_enabled === true)
/* §DASHARRANGE — the area owns its pane list now (the person's own, saved to the account;
 * the default four live in `useCockpitLayouts.DASHBOARD_DEFAULT`). */
// §ONBOARDQOL P1 (D14) — the quick-onboard modal bumps this tick when an agent is
// created; the fleet card and the CTA were rendered against "0 agents" and stayed
// there until F5. Re-read the SERVER, never the modal's copy.
watch(() => uiStore.agentCreatedTick, () => { fetchFleetData().catch(() => {}) })

// State
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null

// FX strip visibility — durable, from /public/registry-config fx_enabled (FX_ENABLED env).
const mcFxEnabled = ref(false)

// §2026-07-29 — a STANDALONE sovereign frame (own EventStore, no FX triangle, not an operator)
// has no Frame B/C to stream. It rendered the A/B/C panes anyway, so its OWN ledger sat under
// the label "Frame A" while two permanently empty panes claimed to be B and C.
// The discriminator is LIVE CONFIG, never a name match: fx_enabled is true on all three prod
// mainframes AND on all 13 cloud operators (asserted against all 16 nodes before shipping),
// so this is a no-op everywhere except a frame that genuinely stands alone.
const mcRegistryName = ref('')


// Operator services are loaded DYNAMICALLY from the backend stack-health response.
// No hardcoded operator list — new operators appear automatically when added as peers.


// Analytics state
const analyticsData = ref<any>(null)
const analyticsLoading = ref(false)

// ─── NEW: Fleet, Pulse, Senate, Trust ────────────────────────
const fleetData = ref<any>({ agent_count: 0, total_liquid_balance: 0, total_staked_balance: 0, total_balance: 0, aggregate_reputation_score: 0, treasury_balance: null })
// §FESUITE (the loading sweep): a card says "none" only after its own read came back. 'reading' until the first answer;
// 'unread' when that answer failed (could not read is not none); once 'read', a later failed refresh keeps what was shown.
type ReadState = 'reading' | 'read' | 'unread'
const fleetRead = ref<ReadState>('reading')
const senateRead = ref<ReadState>('reading')
const rankingsRead = ref<ReadState>('reading')
const settleRead = (state: typeof fleetRead, ok: boolean) => { if (ok) state.value = 'read'; else if (state.value !== 'read') state.value = 'unread' }
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
const fedPeers = ref<number | null>(null)




// §DASHRESTORE (2026-09-02) — REMOVED: the admin RESOURCE METRICS block.
// It came back with the view and was DEAD ON ARRIVAL — and had been dead while
// this view was in production: `resourceMetrics` was a computed rendered by
// nothing, `fetchResourceMetrics()` was defined and called by nothing, and all
// three of resourceData / resourcesLoading / resourcesLoaded were referenced and
// never declared (24 TS2304s — the only new type errors the restore produced).
// It survived precisely BECAUSE it was unreachable: an undeclared name throws
// only when the code runs, and this code never ran. Restoring a view is not the
// place to build a live CPU/MEM/DISK panel, so it is excised, not wired.

// ─── ANALYTICS ───────────────────────────────────────────────
const totalSupply = computed(() => analyticsData.value?.summary?.total_supply || '0')
const liquidSupply = computed(() => analyticsData.value?.summary?.total_liquid_supply || '0')
const stakedSupply = computed(() => analyticsData.value?.summary?.total_staked_supply || '0')
const totalEvents = computed(() => analyticsData.value?.summary?.total_events || 0)
// §FESUITE (V0571, 2026-10-04): the Economy Pulse counts every event since the first. The registry's analytics are the
// Event Store's counts of all its events (one cached snapshot, no window): 24H, 7D and 30D read the same figures, ALL was
// refused, and the footer named the period chosen. The card says since when it counts and offers no period to choose.
const econFoot = computed(() => {
  if (!analyticsData.value) return '—'
  const n = formatCompact(totalEvents.value)
  const first = new Date(String(analyticsData.value.oldest_event || ''))
  if (isNaN(first.getTime())) return tp('mc.economyPulse.eventsAll', '{n} events in all', { n })
  const date = first.toLocaleDateString(appLocale(), { day: 'numeric', month: 'short', year: 'numeric' })
  return tp('mc.economyPulse.eventsSince', '{n} events since {date}', { n, date })
})
const uniqueAgents = computed(() => analyticsData.value?.summary?.unique_agents || 0)
const transactionEvents = computed(() => analyticsData.value?.summary?.total_transaction_events || 0)

// ─── SOVEREIGN STATE bottom section ──────────────────────────
// Economy Pulse — 2x2 hero grid sourced from analyticsData.event_type_breakdown
const economyStats = computed(() => {
  const b = analyticsData.value?.event_type_breakdown || analyticsData.value?.all_event_counts || {}
  // W4 phase 1: an event's count under its old and its new name (UnitsTransferred ...) is one count
  const n = (name: string) => liveNames(name).reduce((sum, k) => sum + (b[k] || 0), 0)
  const stakeActs = n('TokensStaked') + n('TokensUnstaked')
  return {
    transfers: n('TokensTransferred'),
    crossFrame: b.CrossRegistryTransferCompleted || 0,
    fees: b.TransactionFeeCollected || 0,
    stakeActs,
  }
})
// Adaptive senate: when empty, collapse to a slim status strip
const senateActive = computed(() => (senateProposals.value?.length || 0) > 0)
// Lock tiers: max rate for bar scaling
const maxApyPct = computed(() => {
  const tiers = apyTiers.value || []
  if (!tiers.length) return 1
  return Math.max(1, ...tiers.map(t => parseFloat(t.apy) || 0))
})
// Top reputation: max score for bar scaling
const maxRepScore = computed(() => {
  if (!topAgents.value?.length) return 1
  return Math.max(1, ...topAgents.value.map(a => a.score || 0))
})

// ─── SENATE proposal helpers — richer proposal cards (for/against split,
//     status pill, turnout + time-remaining). All derived from the already-
//     fetched senateProposals payload; no new requests. ────────────────────
function senateTotalVotes(p: any): number {
  return (Number(p?.votes_for) || 0) + (Number(p?.votes_against) || 0)
}
function senateForPct(p: any): number {
  const tot = senateTotalVotes(p)
  if (tot <= 0) return 0
  return Math.round(((Number(p?.votes_for) || 0) / tot) * 100)
}
function senateAgainstPct(p: any): number {
  if (senateTotalVotes(p) <= 0) return 0
  return 100 - senateForPct(p)
}
function senateStatusKey(p: any): string {
  const s = String(p?.status || '').toUpperCase()
  if (['VOTING', 'ACTIVE', 'OPEN'].includes(s)) return 'live'
  if (['PASSED', 'APPROVED', 'EXECUTED', 'SUCCEEDED'].includes(s)) return 'pass'
  if (['REJECTED', 'FAILED', 'DEFEATED'].includes(s)) return 'fail'
  return 'idle'
}
function senateStatusLabel(p: any): string {
  const s = String(p?.status || '').toUpperCase()
  return s === 'VOTING' ? 'LIVE' : (s || '—')
}
function senateEndsIn(p: any): string {
  const end = p?.end_timestamp || p?.end_time || p?.ends_at
  if (!end) return ''
  const ms = new Date(end).getTime() - Date.now()
  if (isNaN(ms)) return ''
  if (ms <= 0) return 'closed'
  const h = ms / 3_600_000
  if (h < 1) return `${Math.max(1, Math.round(ms / 60000))}m left`
  if (h < 24) return `${Math.round(h)}h left`
  return `${Math.round(h / 24)}d left`
}

// ─── AGENT METRICS ───────────────────────────────────────────
const totalAgentCount = computed(() => agentStore.agents?.length || agentStore.totalCount || 0)
const activeAgentCount = computed(() => {
  if (!agentStore.agents?.length) return 0
  return agentStore.agents.filter((a: any) => a.status === 'active').length
})

// ─── REPUTATION ──────────────────────────────────────────────
const avgReputation = computed(() => {
  if (!agentStore.agents || agentStore.agents.length === 0) return '0.0'
  // Filter to agents with a name (skip empty placeholder agents with rep=100)
  const namedAgents = agentStore.agents.filter((a: any) => a.name)
  const pool = namedAgents.length > 0 ? namedAgents : agentStore.agents
  const total = pool.reduce((sum: number, agent: any) => {
    // reputation_score is the correct field (0-5 scale for live agents)
    // Legacy placeholder agents may have 100 — normalize those via /20
    const raw = agent.reputation_score ?? agent.reputation ?? 0
    const num = typeof raw === 'number' ? raw : parseFloat(raw) || 0
    return sum + (num > 5 ? num / 20 : num)
  }, 0)
  const avg = total / pool.length
  return Math.min(5, avg).toFixed(1)
})


// ─── HELPERS ─────────────────────────────────────────────────
/** A COUNT, not money: grouped, no decimals, in the app locale (a bare interpolation
 *  printed `875204`; money's formatter printed `875,281.00`). */
function formatCount(value: string | number | undefined): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  return new Intl.NumberFormat(appLocale(), { maximumFractionDigits: 0 }).format(Math.round(n))
}
function formatNumber(value: string | number | undefined): string {
  if (value === undefined || value === null) return '0.00'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '0.00'
  return num.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ─── DATA FETCHING ───────────────────────────────────────────
async function fetchAllData() {
  let failures = 0
  try {
    const promises: Promise<any>[] = [
      agentStore.fetchMyAgents().catch(e => { log.debug('Agent fetch:', e); failures++ }),
      federationStore.fetchRegistries().catch(e => { log.debug('Federation fetch:', e); failures++ })
    ]
    if (authStore.agentToken) {
      promises.push(
        tegStore.fetchBalance().catch(e => { log.debug('TEG:', e); failures++ }),
        tegStore.fetchTransactionHistory().catch(e => { log.debug('TEG tx:', e); failures++ }),
        stakingStore.fetchMyStakingStats().catch(e => { log.debug('Staking:', e); failures++ })
      )
    }
    await Promise.allSettled(promises)
    if (failures > 0) {
      uiStore.showWarning('Partial Load', `Some dashboard data could not be loaded. ${failures} service(s) unavailable.`)
    }
  } catch (err) {
    console.error('MissionControl fetchAllData:', err)
    uiStore.showError('Dashboard Error', 'Failed to load dashboard data. Please try refreshing.')
  }
}

async function fetchAnalytics() {
  analyticsLoading.value = true
  try {
    // no period: every registry counts every event (one asked for "all" before V0571 refused it, 422)
    const response = await apiClient.get('/teg/transactions/analytics')
    analyticsData.value = response.data
  } catch (err) {
    log.warn('Analytics:', err)
    uiStore.showWarning('Analytics Unavailable', 'Transaction analytics could not be loaded.')
  } finally { analyticsLoading.value = false }
}


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
    settleRead(fleetRead, tegRes.status === 'fulfilled')
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
    settleRead(senateRead, true)
  } catch { settleRead(senateRead, false) }
}

async function fetchTrustData() {
  try {
    // each pane settles from its own read: Top Reputation (~60 ms) waited for the federation figures (~1.5 s, a fan-out
    // over the peers) and read "Loading…" all that time (the camera, 2026-10-13)
    const repP = apiClient.get('/teg/reputation/rankings', { params: { limit: 5 } })
    repP.then((res) => {
      const rankings = res.data?.rankings || []
      topAgents.value = rankings.slice(0, 5).map((r: any) => ({
        did: r.agent_did || r.agent_id || '',
        name: r.agent_name || r.name || '',
        score: r.reputation_score || r.score || 0,
      }))
      settleRead(rankingsRead, true)
    }, () => settleRead(rankingsRead, false))
    const [apyRes, , fedRes] = await Promise.allSettled([
      apiClient.get('/staking/apy-tiers'),
      repP,
      apiClient.get('/federation/network-stats'),
    ])
    if (apyRes.status === 'fulfilled') {
      const tiers = apyRes.value.data?.tiers || apyRes.value.data?.apy_tiers || apyRes.value.data || []
      apyTiers.value = (Array.isArray(tiers) ? tiers : []).map((t: any) => ({
        lock: t.lock_period || t.lockPeriod || t.lock_days || 0,
        apy: (t.apy || t.apy_percent || t.rate || 0).toFixed(1),
      })).filter((t: any) => t.lock > 0).slice(0, 4)
    }
    if (fedRes.status === 'fulfilled') {
      fedPeers.value = fedRes.value.data?.activeRegistries || fedRes.value.data?.totalRegistries || 0
    }
  } catch { /* expected */ }
}

function pulseBarHeight(val: any, max: number): string {
  const num = typeof val === 'string' ? parseFloat(val) : (typeof val === 'number' ? val : 0)
  if (isNaN(num) || num <= 0) return '4px'
  const pct = Math.min(100, (num / max) * 100)
  return Math.max(4, Math.round(pct * 0.6)) + 'px'
}

function setupAutoRefresh() {
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null }
  // Fixed 60s internal refresh — no UI selector needed
  autoRefreshTimer = setInterval(() => {
    fetchAllData()
    fetchAnalytics()
    mcFetchFxRate()
  }, 60000)
}




// ── Live cross-currency FX bridge (2026-06-03): public sanitized /teg/fx/rate
// (rate only, no auth) drives the AVT⇄BVT bridge between the ledger streams so
// Frame C is unmistakably a different currency with a LIVE exchange rate. ──
const mcFxRate = ref<any>(null)
function mcFmtRate(s: string | number): string {
  const n = typeof s === 'string' ? parseFloat(s) : s
  return Number.isFinite(n) ? String(+n.toFixed(6)) : String(s)
}
async function mcFetchFxRate() {
  try {
    // §2026-06-14 — all-pairs /fx/rates (the AVT/JDAY/BVT triangle); was single-pair /fx/rate.
    const r = await fetch(`${window.location.origin}/api/v1/teg/fx/rates`, { cache: 'no-store' })
    if (r.ok) mcFxRate.value = await r.json()
  } catch { /* bridge degrades silently */ }
}
// One "1 b = a_per_b a" readout per live cross-currency pair (e.g. 1 JDAY = 1.0085 AVT).
const mcFxEdges = computed(() => {
  const fr: any = mcFxRate.value
  if (!fr || !fr.available || !Array.isArray(fr.pairs)) return []
  return fr.pairs.map((p: any) => ({ key: `${p.a}-${p.b}`, a: p.a, b: p.b, rate: mcFmtRate(p.a_per_b) }))
})


function mcTruncateDid(did: string): string {
  if (!did || did.length < 20) return did || '—'
  return did.substring(0, 10) + '…' + did.substring(did.length - 4)
}

function mcFormatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return '—' }
}


















// ─── LIFECYCLE ───────────────────────────────────────────────
// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a page left during its config read starts no auto-refresh when it lands
const alive = useAlive()
onMounted(async () => {
  // Detect operator mode and rebuild service list before probing
  try {
    // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
    const cfg: any = await loadRegistryConfig()
    mcFxEnabled.value = cfg.fx_enabled ?? false
    mcRegistryName.value = cfg.self?.display_name || cfg.registry_name || ''
  } catch { /* non-fatal */ }
  if (!alive()) return
  fetchAllData()
  fetchAnalytics()
  fetchFleetData()
  fetchSenateData()
  fetchTrustData()
  setupAutoRefresh()
  mcFetchFxRate()
})

onUnmounted(() => {
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null }
})
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
.nc-mission-control { min-height: 100vh; }
.nc-header-bar { background: var(--nc-surface); border-bottom: 1px solid var(--nc-border); padding: 1rem 0; }
.nc-header-container { max-width: 1440px; margin: 0 auto; padding: 0 2rem; }
.nc-header-main { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.nc-h1 { font-size: 1.5rem; font-weight: 300; letter-spacing: 0.1em; color: var(--nc-text-primary); }
.nc-subtitle { font-size: 0.875rem; color: var(--nc-text-muted); letter-spacing: 0.1em; }
.nc-controls { display: flex; align-items: center; gap: 1.5rem; }
.nc-control-group { display: flex; align-items: center; gap: 0.5rem; }
.nc-control-label { font-size: 0.625rem; font-weight: 600; letter-spacing: 0.1em; color: var(--nc-text-muted); }
.nc-select { background: var(--nc-dark); border: 1px solid var(--nc-border); color: var(--nc-text-primary); padding: 0.375rem 0.75rem; font-size: 0.875rem; cursor: pointer; transition: all var(--nc-duration-fast); }
.nc-select:hover { border-color: var(--nc-primary); }
.nc-select:focus { outline: none; border-color: var(--nc-primary); box-shadow: 0 0 0 2px var(--nc-primary-subtle); }
.nc-status-indicator { display: flex; align-items: center; gap: 0.5rem; }
.nc-status-label { font-size: 0.75rem; font-weight: 500; color: var(--nc-text-secondary); letter-spacing: 0.05em; }
.nc-status-dot { width: 6px; height: 6px; background: var(--nc-text-muted); animation: nc-pulse 2s infinite; }
.nc-status-dot.online { background: var(--nc-success); box-shadow: 0 0 8px var(--nc-success-glow); }
.nc-status-dot.warning { background: var(--nc-warning); box-shadow: 0 0 8px var(--nc-warning-glow); }
.nc-status-dot.offline { background: var(--nc-danger); box-shadow: 0 0 8px var(--nc-danger-glow); }
@keyframes nc-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.nc-dashboard-container { max-width: 1440px; margin: 0 auto; padding: 2rem; }
.nc-card-header-flex { display: flex; justify-content: space-between; align-items: center; }
.nc-h2 { font-size: 1.125rem; font-weight: 400; letter-spacing: 0.05em; color: var(--nc-text-primary); }
.nc-score-value { font-size: 2rem; font-weight: 200; font-variant-numeric: tabular-nums; }
.nc-score-status { font-size: 0.75rem; padding: 0.25rem 0.75rem; border: 1px solid; text-transform: uppercase; letter-spacing: 0.05em; }
.nc-components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
.nc-component-card { background: var(--nc-dark); border: 1px solid var(--nc-border); padding: 0.75rem; }
.nc-component-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.nc-component-name { font-size: 0.625rem; font-weight: 600; letter-spacing: 0.1em; color: var(--nc-text-muted); }
.nc-component-value { font-size: 0.875rem; color: var(--nc-text-primary); font-variant-numeric: tabular-nums; }
.nc-resources-section { margin-top: 1rem; }
.nc-resources-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
.nc-resources-placeholder { display: flex; align-items: center; gap: 1rem; padding: 0.5rem 0; }
.nc-load-resources-btn { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.375rem 0.75rem; font-size: 0.75rem; font-weight: 500; letter-spacing: 0.05em; color: var(--nc-text-secondary); background: var(--nc-dark); border: 1px solid var(--nc-border); cursor: pointer; transition: all var(--nc-duration-fast); }
.nc-load-resources-btn:hover:not(:disabled) { border-color: var(--nc-primary); color: var(--nc-primary); }
.nc-load-resources-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.nc-resources-note { font-size: 0.6875rem; color: var(--nc-text-muted); font-style: italic; }
.nc-resource { display: flex; flex-direction: column; gap: 0.5rem; }
.nc-resource-header { display: flex; justify-content: space-between; align-items: center; }
.nc-resource-name { font-size: 0.625rem; font-weight: 600; letter-spacing: 0.1em; color: var(--nc-text-muted); }
.nc-resource-value { font-size: 0.875rem; color: var(--nc-text-primary); font-variant-numeric: tabular-nums; }
.nc-progress { height: 4px; background: var(--nc-border); overflow: hidden; }
.nc-progress-bar { height: 100%; transition: width var(--nc-duration-normal); }
.nc-progress-success { background: var(--nc-success); }
.nc-progress-warning { background: var(--nc-warning); }
.nc-progress-danger { background: var(--nc-danger); }
.nc-metrics-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
.nc-metric-card { display: flex; align-items: center; padding: 1.5rem !important; }
.nc-metric-icon { margin-right: 1rem; }
.nc-metric-content { flex: 1; }
.nc-metric-label { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.1em; color: var(--nc-text-muted); margin-bottom: 0.5rem; text-transform: uppercase; }
.nc-metric-value { font-size: 1.5rem; font-weight: 200; color: var(--nc-text-primary); margin-bottom: 0.25rem; }
.nc-metric-details, .nc-metric-percentage { font-size: 0.875rem; color: var(--nc-text-secondary); }
.nc-reputation-stars { font-size: 1rem; letter-spacing: 0.1em; }
.nc-star-filled { color: var(--nc-warning); }
.nc-star-empty { color: var(--nc-text-muted); opacity: 0.3; }
.nc-charts-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem; }
.nc-chart-card { min-height: 300px; }
.nc-h3 { font-size: 1rem; font-weight: 400; letter-spacing: 0.05em; color: var(--nc-text-primary); text-transform: uppercase; }
.nc-chart-empty { display: flex; align-items: center; justify-content: center; height: 200px; color: var(--nc-text-muted); font-size: 0.875rem; }
.nc-chart-bars, .nc-health-matrix { padding: 1rem; }
.nc-bar-chart { display: flex; flex-direction: column; gap: 0.625rem; }
.nc-bar-row { display: flex; align-items: center; gap: 0.75rem; }
.nc-bar-label { width: 140px; min-width: 140px; font-size: 0.6875rem; color: var(--nc-text-secondary); text-align: right; letter-spacing: 0.02em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-bar-track { flex: 1; height: 22px; background: var(--nc-dark); border: 1px solid var(--nc-border); position: relative; display: flex; align-items: center; }
.nc-bar-fill { height: 100%; display: flex; align-items: center; justify-content: flex-end; padding-right: 0.5rem; transition: width 0.6s ease; min-width: 2px; }
.nc-bar-value-inside { font-size: 0.6875rem; font-weight: 600; color: rgba(0,0,0,0.8); text-shadow: 0 0 4px rgba(255,255,255,0.3); }
.nc-bar-value-outside { font-size: 0.6875rem; font-weight: 600; color: var(--nc-text-secondary); margin-left: 0.5rem; }
.nc-bar-cyan { background: #22d3ee; } .nc-bar-green { background: #4ade80; } .nc-bar-yellow { background: #facc15; }
.nc-bar-purple { background: #a78bfa; } .nc-bar-orange { background: #fb923c; } .nc-bar-pink { background: #f472b6; }
.nc-bar-blue { background: #60a5fa; } .nc-bar-red { background: #f87171; } .nc-bar-teal { background: #2dd4bf; }
.nc-bar-indigo { background: #818cf8; } .nc-bar-lime { background: #a3e635; } .nc-bar-amber { background: #fbbf24; }
.nc-bar-emerald { background: #34d399; }
/* 6-col grid, wraps to 5+6 for 11 services */
/* §pass62.9 (2026-05-22) — clickable variant when tile renders as <a>. */
/* ── Operator Registry Health Section ── */


/* Operator tiles: green tint instead of cyan for healthy */
/* ══ END HW TILES ════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════════
   NEW MISSION CONTROL SECTIONS
   ═══════════════════════════════════════════════════════════════ */

/* ── Card Base ── */
.mc-card-hdr { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.mc-card-title { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.15em; color: rgba(var(--nc-primary-rgb),0.6); }
.mc-card-sub { font-size: 0.6rem; color: rgba(255,255,255,0.25); letter-spacing: 0.08em; font-family: 'Fira Code', monospace; }
.mc-card-link { font-size: 0.6rem; color: rgba(var(--nc-primary-rgb),0.5); text-decoration: none; letter-spacing: 0.05em; transition: color 0.2s; }
.mc-card-link:hover { color: rgba(var(--nc-primary-rgb),0.9); }

/* ── Top Grid: Fleet + Pulse ── */
.mc-top-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
.mc-fleet-card, .mc-pulse-card, .mc-senate-card, .mc-trust-card {
  background: rgba(10,12,18,0.7); border: 1px solid rgba(var(--nc-primary-rgb),0.06); border-radius: 10px; padding: 1.25rem;
}

/* ── Fleet ── */
.mc-fleet-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
.mc-fleet-stat { text-align: center; padding: 0.6rem 0.5rem; background: rgba(var(--nc-primary-rgb),0.02); border-radius: 6px; border: 1px solid rgba(var(--nc-primary-rgb),0.04); }
.mc-fleet-val { display: block; font-size: 1.1rem; font-weight: 300; font-family: 'Fira Code', monospace; color: rgba(255,255,255,0.85); }
.mc-fleet-lbl { display: block; font-size: 0.5rem; letter-spacing: 0.12em; color: rgba(255,255,255,0.25); margin-top: 0.25rem; }
.mc-val-cyan { color: rgba(var(--nc-primary-rgb),0.9); }
.mc-val-blue { color: rgba(59,130,246,0.9); }
.mc-val-green { color: rgba(16,220,129,0.9); }
.mc-val-purple { color: rgba(139,92,246,0.9); }

.mc-fleet-achievements { margin-top: 0.75rem; display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0.75rem; background: rgba(245,158,11,0.04); border: 1px solid rgba(245,158,11,0.1); border-radius: 6px; }
.mc-fleet-ach-claim { margin-left: auto; padding: 3px 12px; border-radius: 5px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.04em; cursor: pointer; color: #f59e0b; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.45); }
.mc-fleet-ach-claim:hover:not(:disabled) { background: rgba(245,158,11,0.22); }
.mc-fleet-ach-claim:disabled { opacity: 0.6; cursor: default; }
.mc-fleet-ach-badge { font-size: 0.65rem; color: rgba(245,158,11,0.7); }
.mc-fleet-ach-avt { font-size: 0.65rem; color: rgba(245,158,11,0.5); margin-left: auto; }

/* ── Fleet CTA (no agents) ── */
.mc-fleet-cta { text-align: center; padding: 1rem 0.5rem; }
.mc-fleet-reading { text-align: center; padding: 1.25rem 0.5rem; font-size: 0.8rem; color: var(--nc-text-muted, #94a3b8); }
.mc-cta-icon { font-size: 2rem; margin-bottom: 0.75rem; }
.mc-cta-text { font-size: 0.75rem; color: rgba(255,255,255,0.5); line-height: 1.5; margin-bottom: 1rem; }
.mc-cta-btns { display: flex; gap: 0.75rem; justify-content: center; margin-bottom: 0.75rem; }
.mc-cta-btn { font-size: 0.7rem; padding: 0.5rem 1rem; border-radius: 6px; text-decoration: none; font-weight: 600; letter-spacing: 0.05em; transition: all 0.2s; }
.mc-cta-primary { background: rgba(var(--nc-primary-rgb),0.15); border: 1px solid rgba(var(--nc-primary-rgb),0.3); color: rgba(var(--nc-primary-rgb),0.9); }
.mc-cta-primary:hover { background: rgba(var(--nc-primary-rgb),0.25); }
.mc-cta-secondary { background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.2); color: rgba(139,92,246,0.8); }
.mc-cta-secondary:hover { background: rgba(139,92,246,0.2); }
.mc-cta-hint { font-size: 0.6rem; color: rgba(255,255,255,0.2); font-style: italic; }

/* ── Hero wrapper ── */
.mc-hero { padding: 1.5rem 2rem 0; max-width: 1440px; margin: 0 auto; }
/* §MCFOLD — the three folded strips under the pulse; ~40px each while folded. */
.mc-folds { padding: 0.9rem 2rem 0; max-width: 1440px; margin: 0 auto; display: flex; flex-direction: column; gap: 0.55rem; }
.mc-fx-edge { font-family: ui-monospace, monospace; font-size: 0.66rem; margin-right: 0.7rem; color: rgba(var(--nc-primary-rgb), 0.85); }
@media (max-width: 768px) { .mc-folds { padding: 0.75rem 1rem 0; } }

/* ── Pulse (bar chart style) ── */
.mc-pulse-metrics { display: flex; justify-content: space-between; gap: 0.5rem; align-items: flex-end; height: 100px; padding: 0 0.5rem; }
.mc-pm { display: flex; flex-direction: column; align-items: center; flex: 1; gap: 0.3rem; }
.mc-pm-bar { width: 100%; border-radius: 3px 3px 0 0; transition: height 0.8s ease; min-height: 4px; }
.mc-pm-cyan { background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.5), rgba(var(--nc-primary-rgb),0.15)); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.15); }
.mc-pm-green { background: linear-gradient(180deg, rgba(16,220,129,0.5), rgba(16,220,129,0.15)); box-shadow: 0 0 8px rgba(16,220,129,0.15); }
.mc-pm-blue { background: linear-gradient(180deg, rgba(59,130,246,0.5), rgba(59,130,246,0.15)); box-shadow: 0 0 8px rgba(59,130,246,0.15); }
.mc-pm-purple { background: linear-gradient(180deg, rgba(139,92,246,0.5), rgba(139,92,246,0.15)); box-shadow: 0 0 8px rgba(139,92,246,0.15); }
.mc-pm-val { font-size: 0.85rem; font-weight: 400; font-family: 'Fira Code', monospace; color: rgba(255,255,255,0.8); }
.mc-pm-lbl { font-size: 0.45rem; letter-spacing: 0.12em; color: rgba(255,255,255,0.2); text-align: center; }
.mc-pulse-footer { display: flex; align-items: center; justify-content: center; gap: 0.6rem; margin-top: 0.75rem; padding-top: 0.6rem; border-top: 1px solid rgba(var(--nc-primary-rgb),0.04); }
.mc-pulse-label { font-size: 0.55rem; color: rgba(255,255,255,0.2); font-family: 'Fira Code', monospace; letter-spacing: 0.05em; }
.mc-pulse-dot { width: 3px; height: 3px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.2); }

/* ═══ SOVEREIGN STATE (bottom section AAA+) ══════════════════ */
.mc-sov { display: grid; gap: 1.25rem; margin-top: 1.5rem; }
.mc-sov-quiet { grid-template-columns: 1fr; }
.mc-sov-active { grid-template-columns: minmax(280px, 1fr) minmax(0, 2fr); align-items: stretch; }
.mc-empty-hint { font-size: 0.7rem; color: rgba(255,255,255,0.2); text-align: center; padding: 1rem; }

/* ── Adaptive Senate ── */
.mc-senate-list { display: flex; flex-direction: column; gap: 0.5rem; }
.mc-senate-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0.6rem; background: rgba(245,180,30,0.03); border-radius: 5px; border: 1px solid rgba(245,180,30,0.05); }
.mc-senate-id { font-size: 0.6rem; color: rgba(245,180,30,0.5); font-family: 'Fira Code', monospace; min-width: 28px; }
.mc-senate-title { font-size: 0.7rem; color: rgba(255,255,255,0.6); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mc-senate-votes { font-size: 0.6rem; font-family: 'Fira Code', monospace; flex-shrink: 0; }
.mc-vote-for { color: rgba(16,220,129,0.8); }
.mc-vote-sep { color: rgba(255,255,255,0.15); margin: 0 2px; }
.mc-vote-against { color: rgba(240,70,70,0.7); }

.mc-senate-strip {
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.7rem 1.1rem;
  background: linear-gradient(90deg, rgba(245,180,30,0.04), rgba(10,12,18,0.7) 60%);
  border: 1px solid rgba(245,180,30,0.08); border-left: 2px solid rgba(245,180,30,0.35);
  border-radius: 8px;
  font-family: 'Fira Code', monospace; font-size: 0.68rem;
}
.mc-sstr-orb {
  width: 7px; height: 7px; border-radius: 50%;
  background: rgba(245,180,30,0.7);
  box-shadow: 0 0 10px rgba(245,180,30,0.5);
  animation: mc-sstr-pulse 2.2s ease-in-out infinite;
}
@keyframes mc-sstr-pulse { 0%,100% { opacity: 0.7; } 50% { opacity: 1; } }
.mc-sstr-label { font-weight: 600; letter-spacing: 0.12em; color: rgba(245,180,30,0.8); }
.mc-sstr-sep { color: rgba(255,255,255,0.2); }
.mc-sstr-msg { color: rgba(255,255,255,0.45); flex: 1; }
.mc-sstr-link {
  color: rgba(245,180,30,0.7); text-decoration: none;
  letter-spacing: 0.08em; font-weight: 500;
  transition: color 0.2s, transform 0.2s;
}
.mc-sstr-link:hover { color: rgba(245,180,30,1); transform: translateX(2px); }

/* ── Trust 3-grid ── */
.mc-trust-3grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1.25rem;
  align-items: stretch;
}
.mc-trust-card { display: flex; flex-direction: column; }
.mc-card-apy  { border-top: 1px solid rgba(16,220,129,0.16); }
.mc-card-econ { border-top: 1px solid rgba(var(--nc-primary-rgb),0.16); }
.mc-card-rep  { border-top: 1px solid rgba(139,92,246,0.16); }

.mc-card-select {
  background: rgba(0,0,0,0.25);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  color: rgba(var(--nc-primary-rgb),0.85);
  font-family: 'Fira Code', monospace; font-size: 0.55rem; letter-spacing: 0.1em;
  padding: 0.2rem 0.4rem; border-radius: 3px; cursor: pointer;
  transition: border-color 0.2s;
}
.mc-card-select:hover  { border-color: rgba(var(--nc-primary-rgb),0.35); }
.mc-card-select:focus  { outline: none; border-color: rgba(var(--nc-primary-rgb),0.5); box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb),0.1); }

/* ── LOCK TIERS (enhanced) ── */
.mc-apy-list { display: flex; flex-direction: column; gap: 0.6rem; margin-top: 0.5rem; flex: 1; justify-content: center; }
.mc-apy-row-v2 {
  display: grid;
  grid-template-columns: 38px 1fr 52px;
  align-items: center; gap: 0.7rem;
}
.mc-apy-lock {
  font-size: 0.65rem; color: rgba(255,255,255,0.5);
  font-family: 'Fira Code', monospace; letter-spacing: 0.05em;
}
.mc-apy-bar-track {
  height: 6px; background: rgba(255,255,255,0.04);
  border-radius: 3px; overflow: hidden;
  border: 1px solid rgba(255,255,255,0.03);
}
.mc-apy-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(16,220,129,0.4), rgba(var(--nc-primary-rgb),0.8));
  box-shadow: 0 0 8px rgba(16,220,129,0.25);
  border-radius: 3px;
  transition: width 0.8s ease;
}
.mc-apy-val-v2 {
  font-size: 0.95rem; font-weight: 300;
  color: rgba(16,220,129,0.95);
  font-family: 'Fira Code', monospace;
  text-align: right;
  text-shadow: 0 0 10px rgba(16,220,129,0.2);
}

/* ── ECONOMY PULSE (new) ── */
.mc-econ-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;
  margin-top: 0.6rem; flex: 1;
}
.mc-econ-cell {
  display: flex; flex-direction: column; align-items: flex-start;
  padding: 0.8rem 0.75rem;
  background: rgba(var(--nc-primary-rgb),0.025);
  border: 1px solid rgba(var(--nc-primary-rgb),0.05);
  border-radius: 6px;
  transition: background 0.2s, border-color 0.2s, transform 0.2s;
}
.mc-econ-cell:hover {
  background: rgba(var(--nc-primary-rgb),0.045);
  border-color: rgba(var(--nc-primary-rgb),0.12);
  transform: translateY(-1px);
}
.mc-econ-val {
  font-size: 1.25rem; font-weight: 300;
  font-family: 'Fira Code', monospace;
  line-height: 1;
  color: rgba(255,255,255,0.9);
}
.mc-econ-lbl {
  font-size: 0.5rem; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.6);  /* §FESUITE: 0.35 was 3.2:1 (axe, sbx-beta: LOCK ACTS) */
  margin-top: 0.4rem;
}
.mc-val-orange { color: rgba(245,158,11,0.9); text-shadow: 0 0 10px rgba(245,158,11,0.2); }
.mc-econ-cell .mc-val-green  { text-shadow: 0 0 10px rgba(16,220,129,0.2); }
.mc-econ-cell .mc-val-cyan   { text-shadow: 0 0 10px rgba(var(--nc-primary-rgb),0.2); }
.mc-econ-cell .mc-val-blue   { text-shadow: 0 0 10px rgba(59,130,246,0.2); }
.mc-econ-foot {
  display: flex; align-items: center; gap: 0.5rem;
  margin-top: 0.7rem; padding-top: 0.55rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.04);
  font-family: 'Fira Code', monospace; font-size: 0.55rem;
  color: rgba(255,255,255,0.6); letter-spacing: 0.08em;  /* §FESUITE: 0.3 was 2.6:1 */
}
.mc-econ-foot-dot {
  width: 4px; height: 4px; border-radius: 50%;
  background: rgba(var(--nc-primary-rgb),0.6);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb),0.5);
  animation: mc-sstr-pulse 1.8s ease-in-out infinite;
}

/* ── TOP REPUTATION (enhanced) ── */
.mc-rep-list { display: flex; flex-direction: column; gap: 0.6rem; margin-top: 0.5rem; flex: 1; }
.mc-rep-row-v2 {
  display: grid; grid-template-columns: 28px 1fr; gap: 0.6rem; align-items: center;
  padding: 0.35rem 0;
}
.mc-rep-badge {
  width: 24px; height: 24px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Fira Code', monospace; font-size: 0.7rem; font-weight: 600;
}
.mc-rep-badge-1 {
  background: linear-gradient(135deg, rgba(250,204,21,0.4), rgba(250,204,21,0.15));
  color: rgba(250,204,21,1); border: 1px solid rgba(250,204,21,0.5);
  box-shadow: 0 0 12px rgba(250,204,21,0.2);
}
.mc-rep-badge-2 {
  background: linear-gradient(135deg, rgba(203,213,225,0.35), rgba(203,213,225,0.12));
  color: rgba(226,232,240,1); border: 1px solid rgba(203,213,225,0.4);
  box-shadow: 0 0 8px rgba(203,213,225,0.15);
}
.mc-rep-badge-3 {
  background: linear-gradient(135deg, rgba(217,119,6,0.35), rgba(217,119,6,0.12));
  color: rgba(251,146,60,1); border: 1px solid rgba(217,119,6,0.4);
  box-shadow: 0 0 8px rgba(217,119,6,0.15);
}
.mc-rep-badge-4, .mc-rep-badge-5 {
  background: rgba(59,130,246,0.08); color: rgba(139,172,246,0.85);
  border: 1px solid rgba(59,130,246,0.2);
}
.mc-rep-body { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
.mc-rep-name-row { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.mc-rep-name-v2 {
  font-size: 0.72rem; color: rgba(255,255,255,0.85); font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mc-rep-score-v2 {
  font-size: 0.75rem; font-weight: 300;
  font-family: 'Fira Code', monospace;
  color: rgba(139,92,246,0.9);
  text-shadow: 0 0 8px rgba(139,92,246,0.25);
  flex-shrink: 0;
}
.mc-rep-bar-track {
  height: 3px; background: rgba(139,92,246,0.06);
  border-radius: 2px; overflow: hidden;
}
.mc-rep-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(139,92,246,0.4), rgba(139,92,246,0.85));
  box-shadow: 0 0 6px rgba(139,92,246,0.3);
  border-radius: 2px;
  transition: width 0.8s ease;
}

/* ── Card-header inline icon (AAA+ §2026-06-27) ── */
.mc-card-title { display: inline-flex; align-items: center; gap: 0.4rem; }
.mc-hdr-ico { font-size: 0.82rem; opacity: 0.9; }
.mc-ico-green  { color: rgba(16,220,129,0.85); }
.mc-ico-cyan   { color: rgba(var(--nc-primary-rgb),0.85); }
.mc-ico-purple { color: rgba(139,92,246,0.85); }
.mc-ico-amber  { color: rgba(245,180,30,0.85); }

/* ── Senate proposal cards (richer than the old plain rows) ── */
.mc-prop {
  display: block; text-decoration: none;
  padding: 0.6rem 0.7rem; border-radius: 8px;
  background: linear-gradient(180deg, rgba(245,180,30,0.045), rgba(245,180,30,0.015));
  border: 1px solid rgba(245,180,30,0.1); border-left: 2px solid rgba(245,180,30,0.4);
  transition: border-color 0.2s, background 0.2s, transform 0.2s;
}
.mc-prop:hover {
  background: linear-gradient(180deg, rgba(245,180,30,0.08), rgba(245,180,30,0.025));
  border-left-color: rgba(245,180,30,0.7);
  transform: translateX(2px);
}
.mc-prop-top { display: flex; align-items: center; gap: 0.5rem; }
.mc-prop-id {
  font-size: 0.58rem; color: rgba(245,180,30,0.65);
  font-family: 'Fira Code', monospace; flex-shrink: 0;
}
.mc-prop-title {
  font-size: 0.72rem; color: rgba(255,255,255,0.82); font-weight: 500; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;
}
.mc-prop-status {
  display: inline-flex; align-items: center; gap: 0.25rem; flex-shrink: 0;
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.1em;
  padding: 0.12rem 0.4rem; border-radius: 3px; border: 1px solid;
  font-family: 'Fira Code', monospace;
}
.mc-prop-status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.mc-ps-live { color: rgba(var(--nc-primary-rgb),0.9); border-color: rgba(var(--nc-primary-rgb),0.3); background: rgba(var(--nc-primary-rgb),0.06); }
.mc-ps-live .mc-prop-status-dot { box-shadow: 0 0 6px currentColor; animation: mc-sstr-pulse 1.6s ease-in-out infinite; }
.mc-ps-pass { color: rgba(16,220,129,0.9); border-color: rgba(16,220,129,0.3); background: rgba(16,220,129,0.06); }
.mc-ps-fail { color: rgba(240,70,70,0.85); border-color: rgba(240,70,70,0.3); background: rgba(240,70,70,0.06); }
.mc-ps-idle { color: rgba(255,255,255,0.4); border-color: rgba(255,255,255,0.12); background: rgba(255,255,255,0.03); }
.mc-prop-bar {
  display: flex; height: 5px; margin: 0.55rem 0 0.45rem;
  border-radius: 3px; overflow: hidden; background: rgba(255,255,255,0.05);
  gap: 1px;
}
.mc-prop-seg { height: 100%; transition: width 0.7s ease; }
.mc-prop-seg-for { background: linear-gradient(90deg, rgba(16,220,129,0.55), rgba(16,220,129,0.9)); box-shadow: 0 0 6px rgba(16,220,129,0.3); }
.mc-prop-seg-against { background: linear-gradient(90deg, rgba(240,70,70,0.85), rgba(240,70,70,0.55)); }
.mc-prop-bar-empty {
  background: repeating-linear-gradient(90deg, rgba(255,255,255,0.06), rgba(255,255,255,0.06) 4px, transparent 4px, transparent 8px);
}
.mc-prop-foot {
  display: flex; align-items: center; gap: 0.6rem;
  font-size: 0.56rem; font-family: 'Fira Code', monospace;
}
.mc-prop-leg { display: inline-flex; align-items: center; gap: 0.25rem; }
.mc-prop-dot { width: 5px; height: 5px; border-radius: 50%; }
.mc-prop-dot-for { background: rgba(16,220,129,0.9); }
.mc-prop-dot-against { background: rgba(240,70,70,0.8); }
.mc-prop-leg-for { color: rgba(16,220,129,0.8); }
.mc-prop-leg-against { color: rgba(240,70,70,0.7); }
.mc-prop-meta { color: rgba(255,255,255,0.3); }
.mc-prop-ends { color: rgba(245,180,30,0.6); margin-left: auto; }

/* ── Shared empty-state (icon + message + CTA) — mirrors the no-agent
     fleet CTA the Commander already likes ── */
.mc-estate {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: 0.5rem; padding: 1.5rem 1rem; min-height: 130px;
}
.mc-estate-icon {
  width: 40px; height: 40px; border-radius: 11px; font-size: 1.2rem;
  display: flex; align-items: center; justify-content: center;
}
.mc-estate-green  { color: rgba(16,220,129,0.85); background: rgba(16,220,129,0.07); border: 1px solid rgba(16,220,129,0.18); box-shadow: 0 0 18px rgba(16,220,129,0.06) inset; }
.mc-estate-purple { color: rgba(139,92,246,0.9); background: rgba(139,92,246,0.07); border: 1px solid rgba(139,92,246,0.2); box-shadow: 0 0 18px rgba(139,92,246,0.06) inset; }
.mc-estate-msg { font-size: 0.72rem; color: rgba(255,255,255,0.55); font-weight: 500; margin: 0; }
.mc-estate-sub { font-size: 0.58rem; color: rgba(255,255,255,0.3); line-height: 1.4; }
.mc-estate-cta {
  margin-top: 0.25rem; font-size: 0.62rem; letter-spacing: 0.05em; font-weight: 600;
  color: rgba(var(--nc-primary-rgb),0.85); text-decoration: none;
  padding: 0.3rem 0.7rem; border-radius: 5px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05);
  transition: all 0.2s;
}
.mc-estate-cta:hover { background: rgba(var(--nc-primary-rgb),0.12); border-color: rgba(var(--nc-primary-rgb),0.4); }

/* ── Payout rate column header + value units ── */
.mc-apy-colhdr {
  display: grid; grid-template-columns: 38px 1fr 52px; gap: 0.7rem;
  font-size: 0.46rem; letter-spacing: 0.14em; color: rgba(255,255,255,0.25);
  font-family: 'Fira Code', monospace; margin-bottom: 0.15rem;
}
.mc-apy-colhdr span:last-child { text-align: right; }
.mc-apy-lock b { color: rgba(255,255,255,0.75); font-weight: 600; }
.mc-apy-lock i { color: rgba(255,255,255,0.35); font-style: normal; }
.mc-apy-val-v2 i { font-size: 0.6rem; opacity: 0.6; font-style: normal; margin-left: 1px; }

/* ── Economy Pulse cell icons + accent + muted-zero ── */
.mc-econ-cell { position: relative; }
.mc-econ-ico {
  position: absolute; top: 0.6rem; right: 0.6rem;
  font-size: 0.78rem; opacity: 0.4;
}
.mc-ec-green  { border-top: 1px solid rgba(16,220,129,0.22); }
.mc-ec-green .mc-econ-ico  { color: rgba(16,220,129,0.7); }
.mc-ec-cyan   { border-top: 1px solid rgba(var(--nc-primary-rgb),0.22); }
.mc-ec-cyan .mc-econ-ico   { color: rgba(var(--nc-primary-rgb),0.7); }
.mc-ec-orange { border-top: 1px solid rgba(245,158,11,0.22); }
.mc-ec-orange .mc-econ-ico { color: rgba(245,158,11,0.7); }
.mc-ec-blue   { border-top: 1px solid rgba(59,130,246,0.22); }
.mc-ec-blue .mc-econ-ico   { color: rgba(59,130,246,0.7); }
/* §FESUITE (2026-10-04): a zero is still a figure, so a quiet tile keeps it readable. The whole-cell opacity 0.5 took the
   label to 1.6:1 (axe, sbx-beta: FEE EVENTS at zero); the accent, the icon and the figure's glow step back instead, and
   the figure stays above 4.5:1 */
.mc-econ-zero { border-top-color: rgba(255,255,255,0.06); }
.mc-econ-zero .mc-econ-val { color: rgba(255,255,255,0.55); text-shadow: none; }
.mc-econ-zero .mc-econ-ico { opacity: 0.25; }


/* ── Agent hint ── */
.mc-fleet-hint { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; padding: 0.5rem 0.75rem; background: rgba(59,130,246,0.04); border: 1px solid rgba(59,130,246,0.1); border-radius: 6px; }
.mc-hint-icon { font-size: 0.8rem; flex-shrink: 0; }
.mc-hint-text { font-size: 0.6rem; color: rgba(59,130,246,0.6); line-height: 1.4; }

/* ═══ END NEW SECTIONS ═══ */

@media (max-width: 1280px) {
  .mc-top-grid { grid-template-columns: 1fr; }
  .mc-sov-active { grid-template-columns: 1fr; }
  .mc-trust-3grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 1024px) {
  .nc-header-main { flex-direction: column; align-items: flex-start; }
  .nc-metrics-row, .nc-charts-row { grid-template-columns: 1fr; }
  .mc-ticker { flex-wrap: wrap; }
  .mc-ticker-pills { display: none; }
  .mc-trust-3grid { grid-template-columns: 1fr; }
  .mc-senate-strip { flex-wrap: wrap; }
}
@media (max-width: 768px) {
  .nc-dashboard-container { padding: 1rem; }
  .nc-resources-grid { grid-template-columns: 1fr; }
  .nc-bar-label { width: 100px; min-width: 100px; font-size: 0.625rem; }
  .mc-econ-grid { grid-template-columns: 1fr; }
}




















</style>
