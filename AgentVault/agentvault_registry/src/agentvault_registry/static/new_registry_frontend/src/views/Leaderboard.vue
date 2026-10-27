<template>
  <!-- Build #11 (2026-05-07): Public Reputation Leaderboard.
       §2026-06-29 — full AAA+ glow-up (5 polish passes): podium with
       avatar-borne flare encirclements, rank medallions, premium hero +
       glass toolbar, avatar + reputation-gauge detail drawer, cohesion /
       responsive / reduced-motion. NO authentication required. Pulls from
       /teg/reputation/rankings (public) + lazy-enriches names/flares from
       /agents/by-did/{did} (also public). -->
  <div class="lb">
    <div class="lb-ambient">
      <div class="lb-grid"></div>
      <div class="lb-aurora"></div>
      <div class="lb-glow lb-glow-1"></div>
      <div class="lb-glow lb-glow-2"></div>
    </div>

    <section class="lb-hero">
      <div class="lb-hero-inner">
        <div class="lb-chip"><span class="lb-chip-dot"></span>{{ t('leaderboardView.chip') }}</div>
        <h1 class="lb-h1" data-tour="lb-hero">{{ t('leaderboardView.h1Prefix') }} <span class="lb-accent">{{ t('leaderboardView.h1Accent') }}</span> {{ t('leaderboardView.h1Suffix') }}</h1>
        <p class="lb-lead">
          {{ t('leaderboardView.lead') }}
          <span v-if="data" class="lb-stat-inline">
            ·  {{ t('leaderboardView.stats', { total: data.total_agents.toLocaleString(appLocale()), top: data.rankings.length }) }}
          </span>
        </p>

        <div class="lb-toolbar" data-tour="lb-search">
          <span class="lb-search-wrap">
            <Icon name="mdi:magnify" class="lb-search-icon" />
            <input
              v-model="search"
              type="text"
              placeholder="Filter by DID or name…"
              class="lb-search"
            />
          </span>
          <span class="lb-toolbar-spacer"></span>
          <span class="lb-toolbar-label">{{ t('leaderboardView.toolbar.show') }}</span>
          <div class="lb-limit-group">
            <button
              v-for="n in [10, 25, 50, 100]" :key="n"
              data-tour="lb-limit"
              class="lb-limit-btn"
              :class="{ 'lb-limit-btn--active': limit === n }"
              :disabled="loading"
              @click="setLimit(n)"
            >{{ n }}</button>
          </div>
          <span class="lb-toolbar-spacer-small"></span>
          <span class="lb-toolbar-updated">
            <span class="lb-toolbar-label">{{ t('leaderboardView.toolbar.updated') }}</span>
            <span class="lb-toolbar-val">{{ lastRefreshAt || '—' }}</span>
          </span>
          <button class="lb-btn lb-btn--ghost lb-refresh" :class="{ 'lb-refresh--spin': loading }" :disabled="loading" @click="refresh" :title="t('leaderboardView.retry')">
            <Icon name="mdi:restart" />
          </button>
        </div>
      </div>
    </section>

    <!-- Rank-by tabs: Reputation (default) vs Agent Evals -->
    <div class="lb-modetabs">
      <button class="lb-modetab" :class="{ 'lb-modetab--active': mode === 'reputation' }" @click="mode = 'reputation'">
        <Icon name="mdi:star-circle" class="lb-modetab-icon" /> Reputation
      </button>
      <button class="lb-modetab" :class="{ 'lb-modetab--active': mode === 'evals' }" @click="setEvalsMode()">
        <Icon name="mdi:clipboard-check-multiple-outline" class="lb-modetab-icon" /> Evals
      </button>
    </div>

    <!-- Evals leaderboard (ranked by mean eval score) -->
    <div v-if="mode === 'evals'" class="lb-body">
      <div v-if="evalsLoading" class="lb-center"><div class="lb-spinner"></div><p class="lb-loading-text">Loading eval scores…</p></div>
      <div v-else-if="evalsFailed" class="lb-center"><ReadFailedNotice :retry="setEvalsMode" /></div>
      <div v-else-if="!evalRows.length" class="lb-center"><p class="lb-loading-text">No eval results yet. Agent Evals score registered agents against task suites; enable a suite in Admin → Agent Evals.</p></div>
      <div v-else class="lb-list">
        <div v-for="(r, i) in evalRows" :key="r.agent_did" class="lb-row" :class="{ 'lb-row--top3': i < 3 }">
          <span class="lb-rank" :class="rankMedalClass(i + 1)">{{ i + 1 }}</span>
          <span class="lb-row-name lb-evalmono">{{ r.agent_did }}</span>
          <span class="lb-row-spacer"></span>
          <span class="lb-evalscore">{{ (r.mean_score * 100).toFixed(0) }}%</span>
          <span class="lb-evalruns">{{ r.runs }} run{{ r.runs === 1 ? '' : 's' }}</span>
        </div>
      </div>
    </div>

    <div v-show="mode === 'reputation'" class="lb-body">
      <div v-if="loading && !data" class="lb-center">
        <div class="lb-spinner"></div>
        <p class="lb-loading-text">{{ t('leaderboardView.loadingRankings') }}</p>
      </div>

      <div v-else-if="error && !data" class="lb-center">
        <p class="lb-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="lb-btn lb-btn--ghost" @click="refresh">{{ t('leaderboardView.retry') }}</button>
      </div>

      <template v-else-if="data">
        <!-- Top 3 podium -->
        <div v-if="podium.length >= 3 && !search" class="lb-podium" data-tour="lb-podium">
          <div
            v-for="(p, i) in podium" :key="p.agent_id"
            class="lb-podium-card"
            :class="[`lb-podium-card--p${i + 1}`]"
            tabindex="0"
            role="button"
            @click="selectAgent(p.agent_id)"
            @keydown.enter="selectAgent(p.agent_id)"
            @mouseenter="onRowEnter(p.agent_id)"
          >
            <div class="lb-podium-crest">
              <Icon :name="i === 0 ? 'mdi:crown' : 'mdi:trophy-variant'" class="lb-podium-crest-icon" />
              <span class="lb-podium-place">#{{ p.rank }}</span>
            </div>
            <div class="lb-podium-avatar-wrap">
              <UserAvatar
                :user="avatarUserFor(p)"
                :avatar-url="avatarUrlFor(p.agent_id)"
                :display-name="profilesById[p.agent_id]?.name || p.agent_id"
                :size="i === 0 ? 'xl' : 'lg'"
                class="lb-podium-avatar"
              />
            </div>
            <div class="lb-podium-name">{{ profilesById[p.agent_id]?.name || '—' }}</div>
            <code class="lb-podium-did" :title="p.agent_id">{{ shortDid(p.agent_id) }}</code>
            <div class="lb-podium-score">{{ p.reputation_score }}<span class="lb-podium-score-unit">rep</span></div>
            <span class="lb-tier-pill lb-podium-tier" :class="tierPillClass(p.reputation_tier)">{{ p.reputation_tier }}</span>
            <div class="lb-podium-pedestal"></div>
          </div>
        </div>

        <!-- Full ranking list -->
        <div class="lb-list">
          <div
            v-for="r in filteredRankings" :key="r.agent_id"
            data-tour="lb-row"
            class="lb-row"
            :class="{
              'lb-row--top3': r.rank <= 3,
              'lb-row--selected': selectedDid === r.agent_id,
            }"
            tabindex="0"
            role="button"
            @mouseenter="onRowEnter(r.agent_id)"
            @focus="onRowEnter(r.agent_id)"
            @click="selectAgent(r.agent_id)"
            @keydown.enter="selectAgent(r.agent_id)"
          >
            <span class="lb-rank" :class="rankMedalClass(r.rank)">
              <Icon v-if="r.rank === 1" name="mdi:crown" class="lb-rank-icon" />
              <template v-else>{{ r.rank }}</template>
            </span>
            <UserAvatar
              :user="avatarUserFor(r)"
              :avatar-url="avatarUrlFor(r.agent_id)"
              :display-name="profilesById[r.agent_id]?.name || r.agent_id"
              size="md"
              class="lb-row-avatar"
            />
            <div class="lb-row-main">
              <div class="lb-row-name">
                <span v-if="profilesById[r.agent_id]?.name" class="lb-name">{{ profilesById[r.agent_id]?.name }}</span>
                <span v-else class="lb-name lb-name--unknown">—</span>
                <code class="lb-did" :title="r.agent_id">{{ shortDid(r.agent_id) }}</code>
              </div>
              <div v-if="profilesById[r.agent_id]?.description" class="lb-row-desc">{{ truncate(profilesById[r.agent_id]?.description, 100) }}</div>
            </div>
            <span class="lb-tier-pill" :class="tierPillClass(r.reputation_tier)">{{ r.reputation_tier }}</span>
            <span class="lb-score" :class="scoreClass(r.reputation_score)">{{ r.reputation_score }}</span>
          </div>
        </div>

        <div v-if="filteredRankings.length === 0" class="lb-empty">
          <div class="lb-empty-glyph"><Icon name="mdi:trophy" /></div>
          <p class="lb-empty-title">{{ t('leaderboardView.noAgentsMatch') }}</p>
          <button class="lb-btn lb-btn--ghost" @click="search = ''">{{ t('leaderboardView.clearSearch') }}</button>
        </div>

        <!-- Detail drawer — teleported to body so the beta-banner's sticky
             stacking context can't intercept clicks on the close button. -->
        <Teleport to="body">
        <div v-if="selectedDid" class="lb-drawer-overlay" @click="selectedDid = null">
          <div class="lb-drawer" @click.stop>
            <div class="lb-drawer-head">
              <span class="lb-drawer-title">{{ t('leaderboardView.agentDetail') }}</span>
              <button class="lb-drawer-close" @click="selectedDid = null"><Icon name="mdi:close" /></button>
            </div>
            <div class="lb-drawer-body" v-if="selectedProfile">
              <div class="lb-drawer-id">
                <UserAvatar
                  :user="selectedProfile || { did: selectedDid }"
                  :avatar-url="avatarUrlFor(selectedDid)"
                  :display-name="selectedProfile.name || selectedDid"
                  size="xl"
                  class="lb-drawer-avatar"
                />
                <div class="lb-drawer-idmeta">
                  <div class="lb-drawer-name">{{ selectedProfile.name || '—' }}</div>
                  <span class="lb-tier-pill lb-drawer-tierpill" :class="tierPillClass(selectedRanking?.reputation_tier || 'standard')">{{ selectedRanking?.reputation_tier || 'standard' }}</span>
                </div>
              </div>
              <code class="lb-drawer-did">{{ selectedDid }}</code>
              <p v-if="selectedProfile.description" class="lb-drawer-desc">{{ selectedProfile.description }}</p>

              <!-- Reputation gauge -->
              <div class="lb-gauge">
                <svg viewBox="0 0 120 120" class="lb-gauge-svg">
                  <circle class="lb-gauge-track" cx="60" cy="60" r="52" />
                  <circle
                    class="lb-gauge-fill"
                    cx="60" cy="60" r="52"
                    :stroke-dasharray="GAUGE_CIRC"
                    :stroke-dashoffset="gaugeOffset"
                  />
                </svg>
                <div class="lb-gauge-center">
                  <span class="lb-gauge-num">{{ selectedRanking?.reputation_score ?? '—' }}</span>
                  <span class="lb-gauge-cap">{{ t('leaderboardView.reputation') }}</span>
                </div>
              </div>

              <div class="lb-drawer-grid">
                <div class="lb-drawer-pair">
                  <span class="lb-drawer-key">{{ t('leaderboardView.tier') }}</span>
                  <span class="lb-drawer-val">{{ selectedRanking?.reputation_tier ?? '—' }}</span>
                </div>
                <div class="lb-drawer-pair">
                  <span class="lb-drawer-key">{{ t('leaderboardView.status') }}</span>
                  <span class="lb-drawer-val">{{ selectedProfile.status || '—' }}</span>
                </div>
                <div class="lb-drawer-pair">
                  <span class="lb-drawer-key">{{ t('leaderboardView.liquidBalance') }}</span>
                  <span class="lb-drawer-val">{{ formatAvt(selectedProfile.liquid_balance) }} <span class="lb-drawer-unit">{{ localCurrency }}</span></span>
                </div>
                <div class="lb-drawer-pair">
                  <span class="lb-drawer-key">{{ t('leaderboardView.stakedBalance') }}</span>
                  <span class="lb-drawer-val">{{ formatAvt(selectedProfile.staked_balance) }} <span class="lb-drawer-unit">{{ localCurrency }}</span></span>
                </div>
                <div class="lb-drawer-pair lb-drawer-pair--wide">
                  <span class="lb-drawer-key">{{ t('leaderboardView.lastActive') }}</span>
                  <span class="lb-drawer-val">{{ formatRel(selectedProfile.last_active_at) }}</span>
                </div>
              </div>

              <button class="lb-btn lb-btn--ghost lb-btn--full" @click="copyDid(selectedDid)"><Icon name="mdi:content-copy" /> {{ t('leaderboardView.copyDid') }}</button>
            </div>
            <div v-else class="lb-drawer-loading">
              <div class="lb-spinner"></div>
              <p class="lb-loading-text">{{ t('leaderboardView.loadingProfile') }}</p>
            </div>
          </div>
        </div>
        </Teleport>

        <div class="lb-footer">
          <code>/teg/reputation/rankings?limit={{ limit }}</code>
          <span>{{ t('leaderboardView.publicEndpoint') }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * Leaderboard — Public Reputation Leaderboard
 *
 * Build #11 (2026-05-07). Public-facing, no auth required.
 * Surfaces top agents by EigenTrust++ reputation score.
 * §2026-06-29 — AAA+ visual rework (podium flares, medallions, gauge drawer).
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { useCurrency } from '@/composables/useCurrency'
import {
  leaderboardService,
  type ReputationRankingsResponse,
  type ReputationRankingEntry,
  type AgentProfilePublic,
} from '@/services/api/leaderboard'

const uiStore = useUIStore()
const { t } = useI18n()
// FX multi-currency: balances are denominated in THIS registry's settlement
// currency (AVT on Frame A/B, BVT on Frame C). Strategy §17.5 [LOCAL].
const { localCurrency } = useCurrency()

const data = ref<ReputationRankingsResponse | null>(null)
const profilesById = ref<Record<string, AgentProfilePublic | null>>({})
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const limit = ref<number>(50)
const search = ref<string>('')
const selectedDid = ref<string | null>(null)

// Rank-by mode: reputation (default) or Agent Evals (mean eval score).
import { evalsApi, type EvalLeaderboardEntry } from '@/services/api/evals'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
const mode = ref<'reputation' | 'evals'>('reputation')
const evalRows = ref<EvalLeaderboardEntry[]>([])
const evalsLoading = ref(false)
// §FESUITE (2026-10-04): "No eval results yet." was drawn with the read failed (the service answered [] for every
// failure). "None" now needs a read that answered; a failed first read says so and offers it again.
const evalsRead = ref(false)
const evalsFailed = ref(false)
async function setEvalsMode() {
  mode.value = 'evals'
  if (evalRows.value.length) return
  evalsLoading.value = true
  try {
    evalRows.value = await evalsApi.getLeaderboard(undefined, 100)
    evalsRead.value = true
    evalsFailed.value = false
  } catch {
    evalsFailed.value = !evalsRead.value
  } finally {
    evalsLoading.value = false
  }
}

onMounted(refresh)

// D6-679: the evals.completed notification opens #/leaderboard?mode=evals. The tab follows the address on arrival and
// when only the query changes while the page is open (vue-router reuses the component then); another value is ignored.
const route = useRoute()
function modeFromAddress() {
  if (route.query.mode === 'evals') void setEvalsMode()
  else if (route.query.mode === 'reputation') mode.value = 'reputation'
}
onMounted(modeFromAddress)
watch(() => route.query.mode, modeFromAddress)

watch([limit], () => { void refresh() })

async function refresh() {
  loading.value = true
  error.value = null
  try {
    const result = await leaderboardService.getRankings(limit.value)
    // §FESUITE: the reputation ledger also scores system accounts (STAKING_POOL): they are not agents, have no
    // profile (every podium load asked /agents/by-did/STAKING_POOL and got 404) and do not belong among the agents
    // a person ranks. An agent is a DID.
    result.rankings = (result.rankings || [])
      .filter((r: ReputationRankingEntry) => String(r.agent_id || '').startsWith('did:'))
      .map((r: ReputationRankingEntry, i: number) => ({ ...r, rank: i + 1 }))
    data.value = result
    lastRefreshAt.value = formatHHMMSS(new Date())
    // Pre-load profiles for the top-3 podium only — bulk-loading 50/100 names
    // floods the console with 404s for orphan reputation rows. Other rows
    // lazy-load on row hover/focus.
    void preloadProfiles(result.rankings.slice(0, 3))
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load rankings'
    uiStore.showError?.('Leaderboard', error.value!)
  } finally {
    loading.value = false
  }
}

/**
 * §MARKSURFACES (2026-09-10) — his report named this page first: *"/leaderboard not sure
 * if leaderboard and otherviews have it."* It did not, and could not.
 *
 * Two facts had to meet on one object. `profilesById` (from /agents/by-did) carries the
 * agent's FLARE — but it is loaded for the top three on mount and for everything else only
 * on hover, so a list row had no profile until a mouse touched it. The ranking rows
 * themselves now carry the registry-attested `track_record` from the rankings call, which
 * arrives with the page. Merging them here means the earned mark is on screen immediately
 * for every row, and the purchased flare fills in as profiles resolve.
 *
 * ⚠ The profile's own track_record wins when it exists: it is the same projection from the
 * same service, and preferring it keeps ONE answer visible while a row is being enriched
 * rather than letting the two flicker against each other.
 */
function avatarUserFor(r: ReputationRankingEntry): Record<string, any> {
  const p = profilesById.value[r.agent_id]
  const tr = (p as any)?.track_record ?? (r as any)?.track_record ?? null
  return p ? { ...p, track_record: tr } : { did: r.agent_id, track_record: tr }
}

async function preloadProfiles(rankings: ReputationRankingEntry[]) {
  // Fetch profiles in parallel; reactive map updates as each resolves.
  await Promise.all(
    rankings.map(async r => {
      if (profilesById.value[r.agent_id] !== undefined) return
      const profile = await leaderboardService.getProfile(r.agent_id)
      profilesById.value = { ...profilesById.value, [r.agent_id]: profile }
    })
  )
}

// §28 polish — Hover/focus-load profile for any row so avatars (with flare
// encirclement + broken-machine overlay) render after a brief mouseover.
// Cached after first load via the profilesById guard. Falls back gracefully —
// rows with no public agent card render an initials fallback.
async function onRowEnter(did: string) {
  if (profilesById.value[did] !== undefined) return
  // Eagerly mark "in flight" so concurrent hovers don't double-fetch
  profilesById.value = { ...profilesById.value, [did]: null }
  const p = await leaderboardService.getProfile(did)
  if (p) profilesById.value = { ...profilesById.value, [did]: p }
}

function setLimit(n: number) {
  if (limit.value === n) return
  limit.value = n
}

function selectAgent(did: string) {
  selectedDid.value = did
  // Ensure profile is loaded for the drawer
  if (profilesById.value[did] === undefined) {
    void leaderboardService.getProfile(did).then(p => {
      profilesById.value = { ...profilesById.value, [did]: p }
    })
  }
}

const selectedProfile = computed(() => selectedDid.value ? profilesById.value[selectedDid.value] : null)
const selectedRanking = computed(() => {
  if (!selectedDid.value || !data.value) return null
  return data.value.rankings.find(r => r.agent_id === selectedDid.value) || null
})

const filteredRankings = computed<ReputationRankingEntry[]>(() => {
  if (!data.value) return []
  const q = search.value.trim().toLowerCase()
  if (!q) return data.value.rankings
  return data.value.rankings.filter(r => {
    if (r.agent_id.toLowerCase().includes(q)) return true
    const p = profilesById.value[r.agent_id]
    if (p?.name && p.name.toLowerCase().includes(q)) return true
    return false
  })
})

const podium = computed(() => filteredRankings.value.slice(0, 3))

// Reputation gauge geometry (drawer). Caps the visual fill at score 200 so
// the ring is a relative indicator, not an absolute one.
const GAUGE_CIRC = 2 * Math.PI * 52
const gaugeOffset = computed(() => {
  const s = selectedRanking.value?.reputation_score ?? 0
  const pct = Math.max(0, Math.min(1, s / 200))
  return GAUGE_CIRC * (1 - pct)
})

// ── Helpers ──
function avatarUrlFor(did: string | null | undefined): string | null {
  if (!did) return null
  const p = profilesById.value[did]
  return p?.card_data?.iconUrl || p?.card_data?.icon_url || null
}
function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 30) return s
  return `${s.slice(0, 16)}…${s.slice(-6)}`
}
function truncate(s: string | null | undefined, max: number): string {
  if (!s) return ''
  if (s.length <= max) return s
  return s.slice(0, max - 1).trim() + '…'
}
function formatAvt(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n)) return '—'
  if (n === 0) return '0'
  if (Math.abs(n) >= 1) return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 6 })
}
function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const dt = typeof iso === 'string' ? new Date(iso) : iso
  return dt.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatRel(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

function tierPillClass(tier: string): string {
  const t = (tier || '').toLowerCase()
  if (t === 'platinum') return 'lb-tier-pill--platinum'
  if (t === 'gold') return 'lb-tier-pill--gold'
  if (t === 'silver') return 'lb-tier-pill--silver'
  if (t === 'bronze') return 'lb-tier-pill--bronze'
  return 'lb-tier-pill--standard'
}
function scoreClass(score: number): string {
  if (score >= 100) return 'lb-score--high'
  if (score >= 25) return 'lb-score--med'
  return 'lb-score--low'
}
function rankMedalClass(rank: number): string {
  if (rank === 1) return 'lb-rank--gold'
  if (rank === 2) return 'lb-rank--silver'
  if (rank === 3) return 'lb-rank--bronze'
  return ''
}

async function copyDid(did: string) {
  try {
    await navigator.clipboard.writeText(did)
    uiStore.showSuccess?.('Copied', did)
  } catch { /* expected */ }
}
</script>

<style scoped>
/* Rank-by mode tabs (Reputation | Evals) */
.lb-modetabs { display: flex; gap: 0.5rem; justify-content: center; margin: 0 auto 0.25rem; max-width: 1100px; padding: 0 1rem; }
.lb-modetab { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.45rem 1rem; border-radius: 0.6rem; font-size: 0.82rem; font-weight: 600; color: rgba(var(--nc-primary-rgb), 0.6); border: 1px solid rgba(var(--nc-primary-rgb), 0.14); background: transparent; transition: all 0.18s ease; }
.lb-modetab:hover { color: rgba(var(--nc-primary-rgb), 0.9); border-color: rgba(var(--nc-primary-rgb), 0.3); }
.lb-modetab--active { color: rgb(var(--nc-primary-rgb)); background: rgba(var(--nc-primary-rgb), 0.1); border-color: rgba(var(--nc-primary-rgb), 0.4); box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.08), 0 6px 20px -10px rgba(var(--nc-primary-rgb), 0.5); }
.lb-modetab-icon { width: 1rem; height: 1rem; }
.lb-evalmono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }
.lb-row-spacer { flex: 1; }
.lb-evalscore { font-weight: 700; color: rgb(var(--nc-primary-rgb)); font-size: 0.95rem; margin-right: 0.75rem; }
.lb-evalruns { font-size: 0.7rem; color: rgba(var(--nc-primary-rgb), 0.5); text-transform: uppercase; letter-spacing: 0.06em; }

.lb {
  position: relative;
  min-height: 100vh;
  padding: 0 0 40px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --gold: #ffd75e;
  --gold-rgb: 255, 215, 94;
  --silver: #d4d9e0;
  --silver-rgb: 212, 217, 224;
  --bronze: #e0996a;
  --bronze-rgb: 224, 153, 106;
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --r-lg: 16px;
  --r-md: 12px;
  --r-sm: 8px;
}

/* Ambient */
.lb-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.lb-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.035) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(ellipse 90% 70% at 50% 0%, #000 30%, transparent 100%);
}
.lb-aurora {
  position: absolute; inset: -20% -10% auto -10%; height: 60%;
  background:
    radial-gradient(60% 80% at 25% 0%, rgba(var(--gold-rgb), 0.10), transparent 70%),
    radial-gradient(55% 75% at 80% 10%, rgba(var(--cyan-rgb), 0.10), transparent 70%);
  filter: blur(40px);
  animation: lb-drift 22s ease-in-out infinite alternate;
}
@keyframes lb-drift { from { transform: translateX(-3%); } to { transform: translateX(4%); } }
.lb-glow { position: absolute; border-radius: 50%; filter: blur(130px); opacity: 0.16; }
.lb-glow-1 { width: 480px; height: 480px; background: rgba(var(--gold-rgb), 0.45); top: -120px; right: -90px; }
.lb-glow-2 { width: 380px; height: 380px; background: rgba(var(--cyan-rgb), 0.45); bottom: -70px; left: -110px; }

/* Hero */
.lb-hero { position: relative; z-index: 1; padding: 40px 32px 20px; }
.lb-hero-inner { max-width: 1280px; margin: 0 auto; }
.lb-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.2em; color: var(--cyan);
  padding: 5px 13px;
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 999px;
  background: rgba(var(--cyan-rgb), 0.05);
  margin-bottom: 16px;
  text-transform: uppercase;
}
.lb-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 10px var(--cyan);
  animation: lb-pulse 2s ease-in-out infinite;
}
@keyframes lb-pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.7); } }
.lb-h1 {
  font-size: 2.5rem;
  margin: 0 0 0.45rem;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.97);
  letter-spacing: -0.02em;
  line-height: 1.05;
}
.lb-accent {
  background: linear-gradient(95deg, var(--gold) 0%, var(--cyan) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.lb-lead {
  font-size: 0.92rem;
  color: rgba(255, 255, 255, 0.62);
  margin: 0 0 18px;
  line-height: 1.55;
  max-width: 60rem;
}
.lb-stat-inline { color: rgba(var(--cyan-rgb), 0.9); font-family: var(--mono); font-size: 0.78em; }

/* Toolbar — glass bar */
.lb-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.6rem;
  padding: 0.55rem 0.7rem;
  background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(0,0,0,0.35));
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: var(--r-md);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 14px 40px -28px rgba(0,0,0,0.9);
  backdrop-filter: blur(6px);
}
.lb-toolbar-spacer { flex: 1; }
.lb-toolbar-spacer-small { width: 0.5rem; }
.lb-toolbar-updated { display: inline-flex; align-items: center; gap: 0.4rem; }
.lb-toolbar-label {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.42);
  text-transform: uppercase;
}
.lb-toolbar-val {
  font-family: var(--mono); font-size: 0.78rem;
  font-weight: 700; color: var(--cyan);
}

.lb-search-wrap { position: relative; display: inline-flex; align-items: center; flex: 0 1 300px; }
.lb-search-icon {
  position: absolute; left: 10px; font-size: 0.95rem;
  color: rgba(var(--cyan-rgb), 0.6); pointer-events: none;
}
.lb-search {
  width: 100%;
  background: rgba(0, 0, 0, 0.32);
  border: 1px solid rgba(var(--cyan-rgb), 0.22);
  color: rgba(255, 255, 255, 0.92);
  border-radius: var(--r-sm);
  font-family: var(--mono); font-size: 0.78rem;
  padding: 7px 12px 7px 30px; outline: none;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.lb-search:focus {
  border-color: rgba(var(--cyan-rgb), 0.6);
  box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), 0.12);
}
.lb-search::placeholder { color: rgba(255,255,255,0.35); }

.lb-limit-group {
  display: inline-flex; gap: 2px; padding: 2px;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.16);
  border-radius: var(--r-sm);
}
.lb-limit-btn {
  font-family: var(--mono); font-size: 0.66rem; font-weight: 600;
  letter-spacing: 0.04em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: none;
  border-radius: 6px; padding: 5px 11px; cursor: pointer;
  transition: all 0.15s;
}
.lb-limit-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08); color: rgba(255, 255, 255, 0.92);
}
.lb-limit-btn--active {
  background: rgba(var(--cyan-rgb), 0.2);
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.5), 0 0 14px -4px rgba(var(--cyan-rgb), 0.6);
}

.lb-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: var(--mono); font-size: 0.68rem;
  letter-spacing: 0.06em; font-weight: 600;
  padding: 6px 11px; border-radius: var(--r-sm);
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.lb-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.lb-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.28);
  color: rgba(var(--cyan-rgb), 0.9);
}
.lb-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.1);
  border-color: rgba(var(--cyan-rgb), 0.55);
  color: rgba(var(--cyan-rgb), 1);
}
.lb-btn--full { width: 100%; justify-content: center; margin-top: 0.4rem; padding: 9px; }
.lb-refresh { padding: 6px 9px; }
.lb-refresh--spin :deep(svg) { animation: lb-spin 0.8s linear infinite; }

/* Body */
.lb-body {
  position: relative; z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
  display: flex; flex-direction: column; gap: 1.5rem;
}

.lb-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: var(--r-md);
}
.lb-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: lb-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes lb-spin { to { transform: rotate(360deg); } }
.lb-loading-text {
  font-family: var(--mono); font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.lb-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger, #ff5a6e); display: inline-flex; align-items: center; gap: 0.4rem; }

/* ───────── Podium ───────── */
.lb-podium {
  display: grid;
  grid-template-columns: 1fr 1.18fr 1fr;
  gap: 1.1rem;
  margin: 0.5rem 0 0.75rem;
  align-items: end;
}
.lb-podium-card {
  position: relative;
  background:
    radial-gradient(120% 80% at 50% -10%, rgba(var(--cyan-rgb), 0.08), transparent 60%),
    linear-gradient(180deg, rgba(14, 18, 30, 0.9), rgba(6, 8, 16, 0.92));
  border: 1px solid rgba(var(--cyan-rgb), 0.22);
  border-radius: var(--r-lg);
  padding: 1.5rem 1rem 1.1rem;
  cursor: pointer;
  transition: transform 0.2s cubic-bezier(.2,.7,.3,1), box-shadow 0.2s, border-color 0.2s;
  display: flex; flex-direction: column; align-items: center;
  gap: 0.45rem;
  text-align: center;
  overflow: hidden;
  outline: none;
}
.lb-podium-card:hover, .lb-podium-card:focus-visible {
  transform: translateY(-5px);
  box-shadow: 0 18px 50px -22px rgba(var(--cyan-rgb), 0.5);
}
.lb-podium-pedestal {
  position: absolute; left: 0; right: 0; bottom: 0; height: 5px;
  background: linear-gradient(90deg, transparent, rgba(var(--cyan-rgb), 0.6), transparent);
}
.lb-podium-card--p1 {
  order: 2;
  border-color: rgba(var(--gold-rgb), 0.6);
  box-shadow: 0 0 44px -10px rgba(var(--gold-rgb), 0.32);
  padding-top: 1.9rem;
  background:
    radial-gradient(120% 80% at 50% -10%, rgba(var(--gold-rgb), 0.16), transparent 60%),
    linear-gradient(180deg, rgba(22, 19, 12, 0.92), rgba(8, 7, 10, 0.94));
}
.lb-podium-card--p1 .lb-podium-pedestal { background: linear-gradient(90deg, transparent, rgba(var(--gold-rgb), 0.85), transparent); height: 6px; }
.lb-podium-card--p2 {
  order: 1;
  border-color: rgba(var(--silver-rgb), 0.45);
}
.lb-podium-card--p2 .lb-podium-pedestal { background: linear-gradient(90deg, transparent, rgba(var(--silver-rgb), 0.7), transparent); }
.lb-podium-card--p3 {
  order: 3;
  border-color: rgba(var(--bronze-rgb), 0.45);
}
.lb-podium-card--p3 .lb-podium-pedestal { background: linear-gradient(90deg, transparent, rgba(var(--bronze-rgb), 0.7), transparent); }

.lb-podium-crest { display: inline-flex; align-items: center; gap: 0.4rem; }
.lb-podium-crest-icon { font-size: 1.05rem; color: rgba(255,255,255,0.45); }
.lb-podium-place {
  font-family: var(--mono); font-size: 0.95rem; font-weight: 700;
  letter-spacing: 0.04em; color: rgba(255,255,255,0.5);
}
.lb-podium-card--p1 .lb-podium-crest-icon { color: var(--gold); font-size: 1.5rem; filter: drop-shadow(0 0 8px rgba(var(--gold-rgb),0.6)); }
.lb-podium-card--p1 .lb-podium-place { color: var(--gold); font-size: 1.1rem; }
.lb-podium-card--p2 .lb-podium-crest-icon, .lb-podium-card--p2 .lb-podium-place { color: var(--silver); }
.lb-podium-card--p3 .lb-podium-crest-icon, .lb-podium-card--p3 .lb-podium-place { color: var(--bronze); }

.lb-podium-avatar-wrap { margin: 0.2rem 0 0.15rem; }
.lb-podium-name {
  font-family: var(--mono); font-size: 1.05rem; font-weight: 700;
  color: rgba(255, 255, 255, 0.96);
  word-break: break-word; line-height: 1.2;
}
.lb-podium-card--p1 .lb-podium-name {
  font-size: 1.25rem;
  background: linear-gradient(95deg, var(--gold), #fff7da);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.lb-podium-did {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  padding: 1px 6px; border-radius: 4px;
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.55);
}
.lb-podium-score {
  font-family: var(--mono); font-size: 1.85rem;
  font-weight: 800; color: var(--cyan);
  text-shadow: 0 0 18px rgba(var(--cyan-rgb), 0.5);
  margin-top: 0.25rem; line-height: 1;
  display: inline-flex; align-items: baseline; gap: 0.25rem;
}
.lb-podium-score-unit { font-size: 0.6rem; font-weight: 600; color: rgba(255,255,255,0.4); letter-spacing: 0.08em; }
.lb-podium-card--p1 .lb-podium-score {
  color: var(--gold); font-size: 2.3rem;
  text-shadow: 0 0 20px rgba(var(--gold-rgb), 0.55);
}
.lb-podium-tier { margin-top: 0.2rem; }

/* ───────── List ───────── */
.lb-list { display: flex; flex-direction: column; gap: 0.4rem; }
.lb-row {
  display: grid;
  grid-template-columns: 48px 46px 1fr auto auto;
  align-items: center; gap: 0.75rem;
  padding: 0.6rem 1rem;
  background: linear-gradient(180deg, rgba(14,18,28,0.7), rgba(10, 13, 22, 0.7));
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: var(--r-md);
  cursor: pointer;
  outline: none;
  transition: background 0.14s, border-color 0.14s, transform 0.14s, box-shadow 0.14s;
}
.lb-row-avatar { flex-shrink: 0; }
.lb-row:hover, .lb-row:focus-visible {
  background: rgba(var(--cyan-rgb), 0.05);
  border-color: rgba(var(--cyan-rgb), 0.32);
  transform: translateX(3px);
  box-shadow: -6px 0 0 -3px rgba(var(--cyan-rgb), 0.5);
}
.lb-row--top3 {
  background: linear-gradient(180deg, rgba(var(--gold-rgb),0.05), rgba(10,13,22,0.7));
  border-color: rgba(var(--gold-rgb), 0.2);
}
.lb-row--selected {
  background: rgba(var(--cyan-rgb), 0.09);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.lb-rank {
  font-family: var(--mono);
  font-size: 0.95rem; font-weight: 700;
  color: rgba(var(--cyan-rgb), 0.85);
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; margin: 0 auto;
  border-radius: 50%;
}
.lb-rank-icon { font-size: 1rem; }
.lb-rank--gold { color: var(--gold); background: rgba(var(--gold-rgb), 0.12); box-shadow: inset 0 0 0 1px rgba(var(--gold-rgb), 0.45); }
.lb-rank--silver { color: var(--silver); background: rgba(var(--silver-rgb), 0.1); box-shadow: inset 0 0 0 1px rgba(var(--silver-rgb), 0.4); }
.lb-rank--bronze { color: var(--bronze); background: rgba(var(--bronze-rgb), 0.1); box-shadow: inset 0 0 0 1px rgba(var(--bronze-rgb), 0.4); }
.lb-row-main {
  display: flex; flex-direction: column; gap: 0.2rem;
  min-width: 0;
}
.lb-row-name {
  display: flex; align-items: center; gap: 0.5rem;
  flex-wrap: wrap;
}
.lb-name {
  font-family: var(--mono); font-size: 0.82rem; font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
}
.lb-name--unknown { color: rgba(255, 255, 255, 0.4); font-weight: 500; }
.lb-did {
  background: rgba(var(--cyan-rgb), 0.05);
  border: 1px solid rgba(var(--cyan-rgb), 0.13);
  padding: 1px 6px; border-radius: 4px;
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.6);
}
.lb-row-desc {
  font-family: var(--mono); font-size: 0.66rem;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.4;
}
.lb-tier-pill {
  font-family: var(--mono); font-size: 0.56rem; font-weight: 700;
  letter-spacing: 0.07em;
  padding: 2px 9px; border-radius: 999px;
  border: 1px solid transparent;
  text-transform: uppercase;
}
.lb-tier-pill--platinum { background: rgba(229, 228, 226, 0.12); color: #e5e4e2; border-color: rgba(229, 228, 226, 0.35); }
.lb-tier-pill--gold { background: rgba(var(--gold-rgb), 0.12); color: var(--gold); border-color: rgba(var(--gold-rgb), 0.35); }
.lb-tier-pill--silver { background: rgba(var(--silver-rgb), 0.12); color: var(--silver); border-color: rgba(var(--silver-rgb), 0.35); }
.lb-tier-pill--bronze { background: rgba(var(--bronze-rgb), 0.12); color: var(--bronze); border-color: rgba(var(--bronze-rgb), 0.35); }
.lb-tier-pill--standard { background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--cyan-rgb), 0.2); }
.lb-score {
  font-family: var(--mono); font-size: 1.1rem; font-weight: 800;
  min-width: 3.5rem; text-align: right;
}
.lb-score--high { color: var(--gold); text-shadow: 0 0 12px rgba(var(--gold-rgb), 0.45); }
.lb-score--med { color: var(--cyan); }
.lb-score--low { color: rgba(255, 255, 255, 0.55); }

/* Empty */
.lb-empty {
  text-align: center;
  padding: 3.5rem 1rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: var(--r-md);
  display: flex; flex-direction: column; align-items: center;
  gap: 0.6rem;
}
.lb-empty-glyph { font-size: 2.2rem; color: rgba(var(--cyan-rgb), 0.4); }
.lb-empty-title {
  font-family: var(--mono); font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0;
}

/* ───────── Drawer ───────── */
.lb-drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(3px);
  z-index: 10100;
  display: flex; justify-content: flex-end;
  animation: lb-fade-in 0.2s;
}
@keyframes lb-fade-in { from { opacity: 0; } to { opacity: 1; } }
.lb-drawer {
  width: min(460px, 100%);
  height: 100%;
  background: linear-gradient(180deg, rgba(12, 16, 26, 0.98), rgba(6, 8, 16, 0.98));
  border-left: 1px solid rgba(var(--cyan-rgb), 0.4);
  box-shadow: -30px 0 70px -30px rgba(0,0,0,0.9);
  padding: 1.5rem 1.3rem;
  overflow-y: auto;
  animation: lb-slide-in 0.28s cubic-bezier(.2,.7,.3,1);
}
@keyframes lb-slide-in { from { transform: translateX(100%); } to { transform: translateX(0); } }

.lb-drawer-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1.1rem;
}
.lb-drawer-title {
  font-family: var(--mono); font-size: 0.7rem;
  letter-spacing: 0.18em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
}
.lb-drawer-close {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
  border-radius: var(--r-sm);
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; cursor: pointer; transition: all 0.15s;
}
.lb-drawer-close:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
}
.lb-drawer-body { display: flex; flex-direction: column; gap: 1rem; }
.lb-drawer-id { display: flex; align-items: center; gap: 0.9rem; }
.lb-drawer-idmeta { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.lb-drawer-name {
  font-family: var(--mono); font-size: 1.3rem; font-weight: 700;
  color: rgba(255, 255, 255, 0.96);
  word-break: break-word; line-height: 1.15;
}
.lb-drawer-tierpill { align-self: flex-start; }
.lb-drawer-did {
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.55);
  background: rgba(var(--cyan-rgb), 0.05);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  padding: 5px 9px;
  border-radius: var(--r-sm);
  word-break: break-all;
}
.lb-drawer-desc {
  font-family: var(--mono); font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.55;
  margin: 0;
}

/* Reputation gauge */
.lb-gauge { position: relative; width: 150px; height: 150px; margin: 0.4rem auto 0.2rem; }
.lb-gauge-svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.lb-gauge-track { fill: none; stroke: rgba(var(--cyan-rgb), 0.1); stroke-width: 8; }
.lb-gauge-fill {
  fill: none; stroke: var(--cyan); stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.8s cubic-bezier(.2,.7,.3,1);
  filter: drop-shadow(0 0 6px rgba(var(--cyan-rgb), 0.6));
}
.lb-gauge-center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.1rem;
}
.lb-gauge-num {
  font-family: var(--mono); font-size: 2rem; font-weight: 800;
  color: #fff; text-shadow: 0 0 16px rgba(var(--cyan-rgb), 0.5);
  line-height: 1;
}
.lb-gauge-cap {
  font-family: var(--mono); font-size: 0.52rem; letter-spacing: 0.14em;
  text-transform: uppercase; color: rgba(255,255,255,0.45);
}

.lb-drawer-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}
.lb-drawer-pair {
  display: flex; flex-direction: column; gap: 0.25rem;
  padding: 0.6rem 0.7rem;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.13);
  border-radius: var(--r-sm);
}
.lb-drawer-pair--wide { grid-column: 1 / -1; }
.lb-drawer-key {
  font-family: var(--mono); font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.42);
  text-transform: uppercase; font-weight: 600;
}
.lb-drawer-val {
  font-family: var(--mono); font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.92);
  font-weight: 700;
}
.lb-drawer-unit { font-size: 0.6rem; color: rgba(255, 255, 255, 0.5); font-weight: 500; letter-spacing: 0.06em; margin-left: 0.2rem; }
.lb-drawer-loading { text-align: center; padding: 3rem 1rem; }

/* Footer */
.lb-footer {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.6rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.lb-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 2px 6px; border-radius: 4px;
}

/* Responsive */
@media (max-width: 768px) {
  .lb-hero { padding: 26px 16px 14px; }
  .lb-h1 { font-size: 1.75rem; }
  .lb-body { padding: 0 16px; }
  .lb-podium { grid-template-columns: 1fr; gap: 0.6rem; }
  /* the row wraps: crest, avatar and the name on the first line (the name takes the rest of it), the DID, the score and
     the tier below; without the wrap the row's fixed parts left the name about one character wide and it read down the
     card letter by letter (the camera, 2026-10-13, Pixel 7) */
  .lb-podium-card { order: unset !important; flex-direction: row; flex-wrap: wrap; text-align: left; align-items: center; gap: 0.5rem 0.8rem; padding: 0.9rem 1rem; }
  .lb-podium-card .lb-podium-crest { order: 0; flex-direction: column; gap: 0.1rem; }
  .lb-podium-avatar-wrap { margin: 0; }
  .lb-podium-card .lb-podium-name { flex: 1 1 calc(100% - 9rem); min-width: 0; overflow-wrap: anywhere; }
  .lb-podium-pedestal { display: none; }
  .lb-row { grid-template-columns: 38px 40px 1fr auto; gap: 0.5rem; padding: 0.55rem 0.7rem; }
  .lb-row .lb-tier-pill { display: none; }
  .lb-search-wrap { flex: 1 1 100%; }
  .lb-toolbar-updated { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .lb-aurora, .lb-chip-dot, .lb-refresh--spin :deep(svg) { animation: none !important; }
  .lb-row, .lb-podium-card, .lb-gauge-fill, .lb-drawer { transition: none !important; animation: none !important; }
}
</style>
