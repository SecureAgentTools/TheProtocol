<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
/**
 * §COCKPITMODULES M4 — AGENT LOGS. The pair to the progress pane.
 *
 * Progress shows an agent talking; this shows it hurting. It answers the question progress
 * raises and cannot: *why did that agent go quiet?* Measured on this account at build time:
 * 36,687 ERROR, 691,270 WARN, 451,945 INFO lines, current to today.
 *
 * ⚠ ONE GROUPED QUERY, not a per-agent fan-out. The existing rail is `/agents/{did}/logs`
 * and is correctly per-agent — but this account owns 4,100+ agents, and asking it once each
 * is the denials mistake with a worse constant (§COCKPITSHOW).
 *
 * ⚠ THE LEVEL IS DECLARED. A quiet ERROR feed and an unread ERROR feed look identical
 * unless the pane says which level it asked for and how many of each exist (§RAT), so the
 * chips carry their counts and stay visible when the list is empty.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.agentlogs
const LEVELS = ['ERROR', 'WARN', 'INFO'] as const

const level = ref<string>(localStorage.getItem('ckd_logs_level') || 'ERROR')
const rows = ref<any[]>([])
/** §COCKPITTILES T1 — fetch a page worth filling a tall tile, then render what fits.
 *  ⚠ The FETCH size is fixed on purpose: tying a request to the viewport would re-query on
 *  every resize. One grouped query over 1.1M rows costs ~24ms either way. */
const FETCH_LIMIT = 60
const listEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(listEl, { rowPx: 46, min: 3, max: FETCH_LIMIT, reservePx: 64 })
/**
 * §COCKPITTILES T4 — FOLD REPEATS, and fold them even when they are not adjacent.
 *
 * His screenshot showed eight consecutive `Glass Gerald [TROPHY] Registry error:` rows —
 * eight rows of a tile spent saying one thing. `PaneChannels` had the same shape and
 * folded only ADJACENT pairs, so an alternating stream reported "0 folded" over fifty
 * near-identical notes. Folding here is by (agent, message) across the whole page: the
 * NEWEST timestamp is kept, the count is shown, and nothing is dropped — a folded row
 * still says how many times it happened, which is more information than eight copies.
 */
type Folded = { r: any; n: number }
const folded = computed<Folded[]>(() => {
  const out: Folded[] = []
  const at = new Map<string, number>()
  for (const r of rows.value) {
    const key = `${r.agent_did || r.agent_name || ''}\u0000${r.message || ''}`
    const seen = at.get(key)
    if (seen === undefined) { at.set(key, out.length); out.push({ r, n: 1 }) }
    else { out[seen].n += 1 }   // rows arrive newest-first, so the kept row is the newest
  }
  return out
})
const shown = computed(() => folded.value.slice(0, fitRows.value))
const heldBack = computed(() => Math.max(0, folded.value.length - shown.value.length))
/** How many LINES the fold saved — stated, because a silent fold is a silent slice. */
const foldedAway = computed(() => rows.value.length - folded.value.length)
const levels = ref<Record<string, any>>({})
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/agent-logs',
      { params: { level: level.value, limit: FETCH_LIMIT } })
    rows.value = Array.isArray(data?.rows) ? data.rows : []
    levels.value = data?.levels || {}
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
function pick(l: string) {
  level.value = l
  try { localStorage.setItem('ckd_logs_level', l) } catch { /* private mode */ }
  loading.value = true
  void load()
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 90) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

// ⚠ NOT `rows.length === 0`: an empty ERROR list is a RESULT, and a pane that renders its
// shell's generic empty state would throw away the chips that say so.
const empty = computed(() => false)

function ageOf(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 90) return `${Math.round(s)}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             data-testid="ckd-agentlogs">
    <div class="ckd-l-wrap" ref="listEl" :data-fit="fitRows">
    <div class="ckd-l-chips" data-testid="ckd-l-chips">
      <button v-for="l in LEVELS" :key="l" type="button" class="ckd-l-chip"
              :class="{ 'is-on': level === l }" :data-level="l"
              data-testid="ckd-l-chip" @click="pick(l)">
        {{ l }}
        <span class="ckd-l-n">{{ (levels[l] && levels[l].count) ?? 0 }}</span>
      </button>
    </div>

    <p v-if="!rows.length" class="ckd-l-none" data-testid="ckd-l-none">
      {{ (levels[level] && levels[level].count)
          ? t('cockpit.logs.noneShown', 'Nothing to show at this level right now.')
          : tp('cockpit.logs.noneEver', 'No {lvl} line has ever been written by your agents.', { lvl: level }) }}
    </p>

    <ul v-else class="ckd-l-list">
      <li v-for="(f, i) in shown" :key="i" class="ckd-l-row" data-testid="ckd-l-row">
        <div class="ckd-l-top">
          <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
          <AgentLink class="ckd-l-who" :did="f.r.agent_did" :label="f.r.agent_name || f.r.agent_did" />
          <span v-if="f.n > 1" class="ckd-l-x" data-testid="ckd-l-x"
                :title="t('cockpit.logs.repeatHint', 'The same line from the same agent, folded. The time shown is the most recent.')">×{{ f.n }}</span>
          <span class="ckd-l-age" :title="f.r.at || ''">{{ ageOf(f.r.at) }}</span>
        </div>
        <p class="ckd-l-msg" :class="`is-${String(f.r.level || '').toLowerCase()}`">{{ f.r.message }}</p>
      </li>
    </ul>

    <!-- ⚠ Filling a tile must never become a silent slice: when the page holds more than
         fits, the pane SAYS so rather than quietly stopping. -->
    <p v-if="foldedAway > 0" class="ckd-l-more" data-testid="ckd-l-folded">
      {{ tp('cockpit.logs.folded', '{n} repeated lines folded.', { n: foldedAway }) }}
    </p>
    <p v-if="heldBack" class="ckd-l-more" data-testid="ckd-l-more">
      {{ tp('cockpit.logs.more', '+{n} more in this page — make the tile taller in Arrange, or narrow by level.', { n: heldBack }) }}
    </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-l-chips { display: flex; gap: .25rem; margin: 0 0 .4rem; flex-wrap: wrap; }
.ckd-l-chip { font-size: .62rem; padding: .12rem .38rem; border-radius: 3px; cursor: pointer;
  background: transparent; color: var(--nc-text-muted, #6e7681);
  border: 1px solid var(--nc-border, #30363d); display: inline-flex; align-items: center; gap: .25rem; }
.ckd-l-chip.is-on { color: var(--nc-text-primary, #e6edf3); border-color: var(--nc-primary, #58a6ff); }
.ckd-l-n { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .58rem; opacity: .8; }
.ckd-l-none { margin: .2rem 0 0; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.ckd-l-wrap { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.ckd-l-wrap > .ckd-l-list { flex: 1 1 auto; min-height: 0; }
.ckd-l-more { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-dim, #8b949e); }
.ckd-l-x { font-size: .58rem; padding: 0 .22rem; border-radius: 3px; font-variant-numeric: tabular-nums;
  background: var(--nc-surface-2, #1c2128); color: var(--nc-text-dim, #8b949e); }
.ckd-l-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .35rem; }
.ckd-l-row { border-left: 2px solid var(--nc-border, #30363d); padding-left: .4rem; }
.ckd-l-top { display: flex; align-items: baseline; gap: .35rem; }
.ckd-l-who { flex: 1; font-size: .68rem; color: var(--nc-text-secondary, #c9d1d9);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ckd-l-age { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .6rem; color: var(--nc-text-muted, #6e7681); flex: 0 0 2.4rem; text-align: right; }
.ckd-l-msg { margin: .05rem 0 0; font-size: .64rem; line-height: 1.35;
  color: var(--nc-text-muted, #6e7681); overflow-wrap: anywhere;
  display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.ckd-l-msg.is-error { color: var(--nc-danger, #f85149); }
.ckd-l-msg.is-warn  { color: var(--nc-warning, #d29922); }
</style>
