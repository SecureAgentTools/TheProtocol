<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §HEARTBEAT (§COCKPITPOLISH P5c, 2026-08-31) — HIS ASK: *"a module … that shows the
 * agents that are currently having a heartbeat."*
 *
 * 🔴 THE ONE HONESTY CONSTRAINT THAT SHAPED THE WHOLE PANE. There is no dedicated
 * heartbeat signal on this protocol. `POST /agents/heartbeat` does nothing but stamp
 * `last_active_at` through the ordinary `get_current_agent` dependency — its own
 * docstring says so — so ANY authenticated call from an agent stamps it identically. A
 * pane titled "heartbeat" that implied a separate liveness protocol would be inventing a
 * rail that does not exist, which is the §HIRECOHERE blank promise wearing a dashboard.
 *
 * So the pane says exactly what it measures: THE LAST TIME EACH AGENT CALLED THIS
 * REGISTRY WITH ITS OWN CREDENTIALS. That is a real and useful fact, and it is printed on
 * screen rather than left to be inferred from the title.
 *
 * TWO DIRECTIONS, SIDE BY SIDE, NEVER FOLDED (§COCKPITA R3):
 *   · CALLED US  — `last_active_at`, the agent reaching in on its own initiative.
 *   · WE PROBED  — `last_health` + `last_health_at`, the health checker reaching out.
 * Their DISAGREEMENT is the finding: an agent that calls us every minute but probes
 * `unreachable` is behind a broken published address, and an agent we probe healthy but
 * which has not called in a day has stopped working while still answering the door. One
 * blended light would hide both.
 *
 * ⚠ A verdict with no age is a fossil (§CARDPULLTICK), so `last_health_at` rides beside
 * the word and an unstamped verdict is shown as unstamped rather than as current.
 *
 * ⚠ THE FILTER HIDES ROWS, SO THE FILTER SAYS SO. Chips are Option A of the fork he was
 * given (one pane + filters, versus parameterised pane instances that would have needed
 * every saved layout to carry `id + params` forever). Ranking sinks; filtering hides; the
 * count of what is hidden therefore stays on screen at all times.
 *
 * Measured baseline on registry-a the day this shipped: 21 agents inside 15 minutes and
 * 39 inside 24 hours, out of 4,130 owned — the four Ironhands, all eleven sovereigns, the
 * mTLS senders and two service agents.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { rankAgents, livenessTier, probeVerdict, secondsSinceCall, type LivenessTier } from '@/services/agentLiveness'
import { usePrivacy } from '@/composables/usePrivacy'

const { t, tp } = useI18n()
/* §COCKPITSHOW C1 — every figure this pane renders goes through the SHARED hide switch.
 * ⚠ `money()` takes the ALREADY-FORMATTED string, so the pane keeps its own compact /
 * tabular rules and privacy only decides whether the reader may see them. A pane that
 * formatted differently under the mask would give the mask away by its column width. */
const { money } = usePrivacy()
const def = PANES.heartbeat
const FETCH_LIMIT = 50          // also the batch-balance cap, so one page = one balance call
// §COCKPITTILES T1 — was a CONSTANT 14, so a taller tile bought whitespace and nothing
// else. The floor stays 6 (a pane must be worth reading at one row unit) and the ceiling
// is what the fetch page holds.
const ROW_FLOOR = 6
const rowsEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(rowsEl, { rowPx: 30, min: ROW_FLOOR, max: FETCH_LIMIT, reservePx: 108 })

type Filter = 'live' | 'quiet' | 'all'
const FILTER_KEY = 'ckd_heartbeat_filter'

const agents = ref<any[]>([])
const balances = ref<Record<string, any>>({})
const balancesTried = ref(false)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const filter = ref<Filter>('live')
let poll: ReturnType<typeof setInterval> | null = null

/** ⚠ Read the reader before writing the key (§BUYSERVICE's `gt_dismissed`): this stores a
 *  bare string and validates it on the way back in, so a stale or hand-edited value can
 *  never put the pane into a state its own chips cannot leave. */
try {
  const v = localStorage.getItem(FILTER_KEY)
  if (v === 'live' || v === 'quiet' || v === 'all') filter.value = v
} catch { /* private windows and blocked storage are not a broken pane */ }

function setFilter(f: Filter) {
  filter.value = f
  try { localStorage.setItem(FILTER_KEY, f) } catch { /* the choice still applies this session */ }
}

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/agents', {
      params: { limit: FETCH_LIMIT, sort: 'live', top_level_only: true },
    })
    const list = Array.isArray(data) ? data : (data?.items ?? [])
    agents.value = rankAgents(list)
    err.value = ''; readAt.value = Date.now()

    const dids = agents.value.map((a: any) => a.did).filter(Boolean).slice(0, 50)
    if (dids.length) {
      try {
        const r = await apiClient.post('/developers/me/agents/balances', { agent_dids: dids })
        balances.value = (r.data && r.data.balances) || {}
      } catch { balances.value = {} }
      finally { balancesTried.value = true }
    } else { balances.value = {}; balancesTried.value = true }
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
// §TRUSTCHAIN P4.6 (2026-09-12) — the first read waits for the developer token. During the login
// transition this pane mounted before the store held a token, so its first
// /developers/me/agents went out anonymous and 401'd (measured §MARKSURFACES); the poll
// then succeeded, which is what made it look transient. A request that cannot be
// authenticated is not sent; it is sent the moment it can be.
const authStore = useAuthStore()
function loadWhenAuthed() {
  if (authStore.token) { void load(); return }
  const stop = watch(() => authStore.token, (tok) => { if (tok) { stop(); void load() } })
}
onMounted(() => { loadWhenAuthed(); poll = setJitteredInterval(() => { if (authStore.token) void load() }, (def.pollSeconds ?? 30) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const inBand = (a: any, f: Filter): boolean => {
  const tier: LivenessTier = livenessTier(a)
  if (f === 'all') return true
  if (f === 'live') return tier === 'fresh' || tier === 'recent'
  return tier === 'quiet'            // 15 minutes to 24 hours
}

const counts = computed(() => ({
  live: agents.value.filter(a => inBand(a, 'live')).length,
  quiet: agents.value.filter(a => inBand(a, 'quiet')).length,
  all: agents.value.length,
}))
const matching = computed(() => agents.value.filter(a => inBand(a, filter.value)))
const rows = computed(() => matching.value.slice(0, fitRows.value))
/** Hidden by the FILTER and hidden by the ROW CAP are different hidings; both counted. */
const hiddenByFilter = computed(() => agents.value.length - matching.value.length)
const hiddenByCap = computed(() => Math.max(0, matching.value.length - rows.value.length))
const empty = computed(() => !loading.value && agents.value.length === 0)

function ageOf(a: any): string {
  const s = secondsSinceCall(a)
  // ⚠ A WORD IN A COLUMN OF DURATIONS is what made the ragged edge visible in the first
  // place. The dash keeps the column uniform; `never` still reaches the reader through the
  // row's title, so nothing is hidden — it is just not widening the table.
  if (s === null) return '—'
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

function probeAge(a: any): string {
  if (!a?.last_health_at) return t('cockpit.hb.unstamped', 'no time recorded')
  const s = Math.max(0, Math.round((Date.now() - new Date(a.last_health_at).getTime()) / 1000))
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

/** 🔴 A TRUNCATED NUMBER IS A WRONG NUMBER. The first cut right-aligned the raw figure in
 *  a fixed column, so a canary holding 26,729,662.41 rendered as `26,729,662…` — which
 *  reads as a number and is not one. Compact notation is the honest way to keep the column
 *  a column: `26.7M` is a rounded quantity that announces its own rounding, and the exact
 *  value with its currency stays in the title. Below a million nothing is abbreviated,
 *  because that is where the digits actually matter. */
function fmtAmount(raw: any): string {
  const n = Number(raw)
  if (!Number.isFinite(n)) return String(raw)
  return nAuto(n)
}

function balanceText(a: any): { text: string; unknown: boolean; title: string } {
  const b = balances.value[a.did]
  if (!balancesTried.value && !b) return { text: '·', unknown: true, title: t('cockpit.hb.balPending', 'Reading balance…') }
  if (!b || b.error) {
    return {
      text: '—', unknown: true,
      title: b?.error
        ? tp('cockpit.hb.balError', 'Balance could not be read: {e}', { e: String(b.error) })
        : t('cockpit.hb.balMissing', 'Balance could not be read — not a statement that it holds nothing.'),
    }
  }
  // ⚠ the TITLE is masked too — a tooltip carrying the exact figure would undo the whole
  // switch the moment anyone hovered during a screen share.
  return { text: money(fmtAmount(b.balance)), unknown: false,
           title: money(`${b.balance} ${b.currency || ''}`.trim()) }
}

/** 🔴 The disagreement, named. This is the sentence the pane exists to be able to print. */
function conflict(a: any): string | null {
  const tier = livenessTier(a)
  const probe = probeVerdict(a)
  const alive = tier === 'fresh' || tier === 'recent'
  if (alive && (probe === 'unreachable' || probe === 'unhealthy')) {
    return t('cockpit.hb.conflictIn', 'calling in, but we cannot reach its published address')
  }
  if (!alive && tier !== 'never' && probe === 'healthy') {
    return t('cockpit.hb.conflictOut', 'answering our probe, but it has stopped calling us')
  }
  return null
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.hb.empty', 'You own no agents on this registry.')">
    <div class="hb" data-testid="ckd-heartbeat" data-tour="cockpit-heartbeat" ref="rowsEl" :data-fit="fitRows">
      <!-- WHAT THIS MEASURES, in the pane, not in a tooltip. -->
      <p class="hb-what" data-testid="hb-what">
        {{ t('cockpit.hb.what', 'When each agent last called this registry with its own credentials. There is no separate heartbeat signal — any authenticated call counts.') }}
      </p>

      <nav class="hb-chips" :aria-label="t('cockpit.hb.filterAria', 'Filter by activity')">
        <button class="hb-chip" :class="{ 'is-on': filter === 'live' }" data-testid="hb-chip-live" @click="setFilter('live')">
          {{ tp('cockpit.hb.live', 'Live · {n}', { n: counts.live }) }}
        </button>
        <button class="hb-chip" :class="{ 'is-on': filter === 'quiet' }" data-testid="hb-chip-quiet" @click="setFilter('quiet')">
          {{ tp('cockpit.hb.quiet', 'Quiet · {n}', { n: counts.quiet }) }}
        </button>
        <button class="hb-chip" :class="{ 'is-on': filter === 'all' }" data-testid="hb-chip-all" @click="setFilter('all')">
          {{ tp('cockpit.hb.all', 'All · {n}', { n: counts.all }) }}
        </button>
      </nav>

      <!-- An empty BAND is not an empty fleet, and it says which is which. -->
      <p v-if="!rows.length" class="hb-none" data-testid="hb-band-empty">
        {{ filter === 'live'
             ? t('cockpit.hb.noneLive', 'Nothing has called in the last 15 minutes. Your agents are not necessarily down — try Quiet or All.')
             : t('cockpit.hb.noneBand', 'No agents in this band.') }}
      </p>

      <ul v-else class="hb-list">
        <li v-for="a in rows" :key="a.did" class="hb-row" data-testid="hb-row">
          <span class="hb-dot" :class="`is-${livenessTier(a)}`" />
          <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
          <AgentLink class="hb-name" :did="a.did" :label="a.name || a.did" />

          <span class="hb-age" data-testid="hb-age"
                :title="secondsSinceCall(a) === null
                          ? t('cockpit.hb.neverCalled', 'This agent has never called this registry with its own credentials.')
                          : t('cockpit.hb.ageHint', 'Since its last call to this registry')">{{ ageOf(a) }}</span>

          <!-- The OTHER direction. Never-probed renders as never-probed. -->
          <span class="hb-probe" data-testid="hb-probe"
                :class="probeVerdict(a) ? `is-${probeVerdict(a)}` : 'is-none'"
                :title="probeVerdict(a)
                          ? tp('cockpit.hb.probeHint', 'We probed it {age} ago: {v}', { age: probeAge(a), v: String(probeVerdict(a)) })
                          : t('cockpit.hb.probeNone', 'This registry has never probed it. Never probed is not unhealthy.')">
            {{ probeVerdict(a) || '·' }}
          </span>

          <span class="hb-bal" data-testid="hb-balance"
                :class="{ 'is-unknown': balanceText(a).unknown }" :title="balanceText(a).title">
            {{ balanceText(a).text }}
          </span>
        </li>
      </ul>

      <p v-for="a in rows.filter(conflict)" :key="`c-${a.did}`" class="hb-conflict" data-testid="hb-conflict">
        <Icon name="mdi:alert-circle-outline" class="hb-ci" />
        <strong>{{ a.name || a.did }}</strong> — {{ conflict(a) }}
      </p>

      <p class="hb-foot" data-testid="hb-foot">
        {{ tp('cockpit.hb.foot', 'Showing {shown} of {total} · {hf} outside this filter · {hc} beyond the row limit',
              { shown: rows.length, total: agents.length, hf: hiddenByFilter, hc: hiddenByCap }) }}
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.hb { display: flex; flex-direction: column; gap: .35rem; }
.hb-what { margin: 0; font-size: .63rem; line-height: 1.35; color: var(--nc-text-muted, #6e7681); }
.hb-chips { display: flex; gap: .25rem; flex-wrap: wrap; }
.hb-chip {
  font-size: .64rem; padding: .12rem .45rem; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--nc-border, rgba(255,255,255,.1)); background: transparent;
  color: var(--nc-text-dim, #8b949e);
}
.hb-chip:hover { color: var(--nc-text-primary, #e6edf3); }
.hb-chip.is-on { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255), .5); background: rgba(var(--nc-primary-rgb, 0,229,255), .07); }
.hb-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .18rem; }
.hb-row { display: flex; align-items: center; gap: .4rem; font-size: .73rem; }
.hb-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.hb-dot.is-fresh  { background: var(--nc-success, #3fb950); box-shadow: 0 0 5px rgba(63,185,80,.7); }
.hb-dot.is-recent { background: var(--nc-success, #3fb950); }
.hb-dot.is-quiet  { background: var(--nc-warning, #d29922); }
.hb-dot.is-silent { background: var(--nc-text-muted, #6e7681); }
.hb-dot.is-never  { background: transparent; border: 1px solid var(--nc-text-muted, #6e7681); }
.hb-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--nc-text-secondary, #c9d1d9); }
/* 🔴 HIS REPORT, live: "heartbeats module seconds is not aligned in every row."
   Exactly right, and `min-width` is why: it is a FLOOR, not a width, so a cell grows to
   fit its content and the column edge moves per row. `5s` and `12m` sat at one x, `never`
   and `3d` pushed past it. Three columns pretending to be a table have to actually be one:
   a fixed `width` (never min-width), `flex: 0 0 <same>`, and TABULAR figures so the digits
   themselves line up — a proportional `1` is narrower than a `0` and that alone is enough
   to make a right-aligned number look crooked. Overflow is hidden rather than allowed to
   push, because the full value is in the title either way. */
.hb-age {
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .66rem; color: var(--nc-text-muted, #6e7681);
  flex: 0 0 3.1rem; width: 3.1rem; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hb-probe {
  font-size: .58rem; letter-spacing: .04em; text-transform: uppercase;
  flex: 0 0 5.4rem; width: 5.4rem; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hb-probe.is-healthy { color: var(--nc-success, #3fb950); }
.hb-probe.is-unhealthy { color: var(--nc-warning, #d29922); }
.hb-probe.is-unreachable { color: var(--nc-danger, #f85149); }
.hb-probe.is-none { color: var(--nc-text-muted, #6e7681); }
.hb-bal {
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .68rem; color: var(--nc-text-dim, #8b949e);
  flex: 0 0 4.6rem; width: 4.6rem; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hb-bal.is-unknown { color: var(--nc-text-muted, #6e7681); }
.hb-conflict { margin: 0; display: flex; align-items: center; gap: .25rem; font-size: .63rem; color: var(--nc-warning, #d29922); }
.hb-ci { width: 12px; height: 12px; flex: 0 0 auto; }
.hb-none { margin: .3rem 0; font-size: .68rem; color: var(--nc-text-dim, #8b949e); }
.hb-foot { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
</style>
