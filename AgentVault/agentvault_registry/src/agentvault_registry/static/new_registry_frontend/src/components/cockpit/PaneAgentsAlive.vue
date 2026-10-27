<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPIT P1 — AGENTS ALIVE, repaired 2026-08-31 (§COCKPITPOLISH P5 + P5b).
 *
 * 🔴 HIS REPORT: *"balance is only shown for the first 4 agents."* Exactly right, and
 * there were TWO faults stacked in that one column.
 *
 *   1. `METRIC_LIMIT = 4` — the pane fetched `/agent-metrics/{did}` for the first four
 *      rows only (an N+1 it capped rather than batched) and rendered `—` for rows 5-8.
 *      That dash was indistinguishable from "this agent has no traffic": the §RAT trap
 *      one pane over, where NOT FETCHED and NOTHING TO SHOW must never render the same.
 *   2. The value was not balance at all. It was the 24h request count, while the footer
 *      read "top {n} by balance · 24h requests" — the sort key and the column described
 *      different quantities, which is what invited the reading he gave it.
 *
 * FIXED BY USING A RAIL THAT WAS ALREADY BUILT AND UNUSED: `POST /developers/me/agents/
 * balances` takes up to 50 DIDs in ONE request and handles partial failures. So balance
 * is shown for EVERY row, with no cap and no N+1.
 *
 * ⚠ AND THE PARTIAL-FAILURE SHAPE IS ITSELF A TRAP: that endpoint answers
 * `{balance: "0", error: "..."}` when the TEG read fails, so a failed lookup is
 * byte-identical to an agent holding nothing unless you read `error`. This pane reads it
 * and renders an honest gap, because telling an operator their funded agent holds zero is
 * a worse lie than telling them nothing.
 *
 * The 24h request count is GONE from here rather than kept as a four-row tease: it has no
 * batch rail, and the pane that shows traffic properly (`agentops`, §RAT) already
 * separates "never observed" from "failing everything". One honest column beats two
 * columns where one of them is a guess.
 *
 * P5: the ORDER is liveness, not balance — a pane called "Agents alive" that ranks by
 * balance listed `Sim-Registry-A-01`, `canary-registry-a` and three mTLS senders while
 * every sovereign was missing. Ranking is the shared rail (`services/agentLiveness.ts`),
 * so this pane and both agent pickers cannot drift apart.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { rankAgents, livenessTier, countLive, secondsSinceCall } from '@/services/agentLiveness'
import { usePrivacy } from '@/composables/usePrivacy'

const { t, tp } = useI18n()
/* §COCKPITSHOW C1 — every figure this pane renders goes through the SHARED hide switch.
 * ⚠ `money()` takes the ALREADY-FORMATTED string, so the pane keeps its own compact /
 * tabular rules and privacy only decides whether the reader may see them. A pane that
 * formatted differently under the mask would give the mask away by its column width. */
const { money } = usePrivacy()
const def = PANES.agents
// §COCKPITTILES T1 — was 8, a constant that a taller tile could not spend. The FETCH is
// still fixed (a request must not re-fire on resize); the DISPLAY follows the tile.
const LIST_LIMIT = 24
const listEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(listEl, { rowPx: 26, min: 3, max: LIST_LIMIT, reservePx: 40 })
const shown = computed(() => agents.value.slice(0, fitRows.value))
const heldBack = computed(() => Math.max(0, agents.value.length - shown.value.length))

const agents = ref<any[]>([])
/** did → { balance, currency, error? }. A missing key means "not asked"; an entry with
 *  `error` means "asked and could not read" — two different silences. */
const balances = ref<Record<string, any>>({})
const balancesTried = ref(false)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/agents', {
      params: { limit: LIST_LIMIT, sort: 'live', top_level_only: true },
    })
    const list = Array.isArray(data) ? data : (data?.items ?? [])
    agents.value = rankAgents(list)
    err.value = ''; readAt.value = Date.now()

    // ONE request for every row on screen. The endpoint caps at 50 and this pane shows 8.
    const dids = agents.value.map((a: any) => a.did).filter(Boolean).slice(0, 50)
    if (dids.length) {
      try {
        const r = await apiClient.post('/developers/me/agents/balances', { agent_dids: dids })
        balances.value = (r.data && r.data.balances) || {}
      } catch {
        balances.value = {}
      } finally { balancesTried.value = true }
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
onMounted(() => { loadWhenAuthed(); poll = setJitteredInterval(() => { if (authStore.token) void load() }, (def.pollSeconds ?? 60) * 1000) })
/* §PANEDOORS — the empty state offers the quick modal; the modal's tick makes this pane re-read
 * the SERVER, so the door leaves on the truth, not on the modal's word. */
const uiStore = useUIStore()
watch(() => uiStore.agentCreatedTick, () => { void load() })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && agents.value.length === 0)
const liveNow = computed(() => countLive(agents.value))

/** 🔴 A TRUNCATED NUMBER IS A WRONG NUMBER. The first cut right-aligned the raw figure in
 *  a fixed column, so a canary holding 26,729,662.41 rendered as `26,729,662…` — which
 *  reads as a number and is not one. Compact notation is the honest way to keep the column
 *  a column: `26.7M` is a rounded quantity that announces its own rounding, and the exact
 *  value with its currency stays in the title. Below a million nothing is abbreviated,
 *  because that is where the digits actually matter. */
function fmtAmount(raw: any): string {
  // App locale, never the host's (§COCKPITTILES T0).
  const n = Number(raw)
  if (!Number.isFinite(n)) return String(raw)
  return nAuto(n)
}

/** Three outcomes, three renderings. `null` = we have not asked yet. */
function balanceOf(a: any): { text: string; unknown: boolean; title: string } {
  const b = balances.value[a.did]
  if (!balancesTried.value && !b) {
    return { text: '·', unknown: true, title: t('cockpit.agents.balPending', 'Reading balance…') }
  }
  if (!b || b.error) {
    return {
      text: '—', unknown: true,
      title: b?.error
        ? tp('cockpit.agents.balError', 'Balance could not be read: {e}', { e: String(b.error) })
        : t('cockpit.agents.balMissing', 'Balance could not be read. This is not a statement that it holds nothing.'),
    }
  }
  return { text: money(fmtAmount(b.balance)), unknown: false,
           title: money(`${b.balance} ${b.currency || ''}`.trim()) }
}

function ageOf(a: any): string {
  const s = secondsSinceCall(a)
  if (s === null) return '—'          // see §HEARTBEAT: a word in a duration column ragged it
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.agents.empty', 'You own no agents on this registry.')"
             :empty-action-label="t('cockpit.door.createFirst', 'Create your wallet agent')"
             @empty-action="uiStore.openQuickAgentModal()">
    <ul class="ckd-ag-list" ref="listEl" :data-fit="fitRows">
      <li v-for="a in shown" :key="a.did || a.id" class="ckd-ag" data-testid="ckd-agent">
        <span class="ckd-dot" :class="`is-${livenessTier(a)}`"
              :title="tp('cockpit.agents.lastCall', 'Last called this registry: {age} ago', { age: ageOf(a) })" />
        <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
        <AgentLink class="ckd-ag-name" :did="a.did" :label="a.name || a.agent_name || a.did" />
        <span class="ckd-ag-age" data-testid="ckd-agent-age">{{ ageOf(a) }}</span>
        <span class="ckd-ag-bal" data-testid="ckd-agent-balance"
              :class="{ 'is-unknown': balanceOf(a).unknown }" :title="balanceOf(a).title">
          {{ balanceOf(a).text }}
        </span>
      </li>
    </ul>
    <p v-if="heldBack" class="ckd-ag-more" data-testid="ckd-ag-more">
      {{ tp('cockpit.agents.more', '+{n} more live — make the tile taller in Arrange.', { n: heldBack }) }}
    </p>
    <!-- The footer describes the columns that are ACTUALLY there. The old one named a
         sort key ("by balance") the pane did not use and a column it did not show. -->
    <p class="ckd-ag-foot" data-testid="ckd-agents-foot">
      {{ tp('cockpit.agents.shown2',
            '{n} of your agents, most recently active first · {live} alive now · age = last call, then balance',
            { n: agents.length, live: liveNow }) }}
    </p>
  </PaneShell>
</template>

<style scoped>
.ckd-ag-more { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-dim, #8b949e); }
.ckd-ag-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .2rem; }
.ckd-ag { display: flex; align-items: center; gap: .4rem; font-size: .74rem; }
.ckd-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
/* The freshness vocabulary, shared with §HEARTBEAT so the desk says one thing. */
.ckd-dot.is-fresh  { background: var(--nc-success, #3fb950); box-shadow: 0 0 5px rgba(63,185,80,.7); }
.ckd-dot.is-recent { background: var(--nc-success, #3fb950); }
.ckd-dot.is-quiet  { background: var(--nc-warning, #d29922); }
.ckd-dot.is-silent { background: var(--nc-text-muted, #6e7681); }
.ckd-dot.is-never  { background: transparent; border: 1px solid var(--nc-text-muted, #6e7681); }
.ckd-ag-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--nc-text-secondary, #c9d1d9); }
/* Same fix as §HEARTBEAT, same reason: `min-width` is a floor, so the column edge moved
   per row. Fixed width + tabular figures, and the full value stays in the title. */
.ckd-ag-age {
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .66rem; color: var(--nc-text-muted, #6e7681);
  flex: 0 0 3.1rem; width: 3.1rem; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-ag-bal {
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  color: var(--nc-text-dim, #8b949e);
  flex: 0 0 4.6rem; width: 4.6rem; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-ag-bal.is-unknown { color: var(--nc-text-muted, #6e7681); }
.ckd-ag-foot { margin: .45rem 0 0; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
</style>
