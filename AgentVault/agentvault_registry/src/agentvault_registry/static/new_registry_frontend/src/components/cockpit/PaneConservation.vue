<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPIT P1 — CONSERVATION. The supply invariant, never actionable.
 *
 * Source: `GET /api/v1/public/supply-invariant` — the registry's own wrapper over
 * the EventStore audit, 30 s cached, and honest: when the ES is unreachable it
 * answers `status: UNKNOWN, source: unreachable` rather than a comforting zero.
 * This pane renders that distinction, because "Δ is 0" and "I could not ask"
 * are opposite facts and a pane that shows the same green for both is worse
 * than no pane (§GLOBALSTD, Phase 0).
 *
 * ⚠ Through the vhost, never a raw ES port — the CORS-noise class.
 * There is no button here on purpose. Δ is the prime directive's reading; a
 * human does not "fix" it from a desk tile.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'

const { t } = useI18n()
const { money } = usePrivacy()
const def = PANES.conservation
const data = ref<any>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const r = await apiClient.get('/public/supply-invariant')
    data.value = r.data; err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const reachable = computed(() => data.value?.source === 'eventstore')
const statusText = computed(() => String(data.value?.status ?? 'UNKNOWN'))
const deltaText = computed(() =>
  data.value?.delta === null || data.value?.delta === undefined ? '—' : String(data.value.delta))
function fmt(n: any): string {
  if (n === null || n === undefined) return '—'
  // §COCKPITSHOW C1 — through the shared hide switch. ⚠ The DELTA is deliberately NOT
  // masked (see the template): it is 0.0 or it is a breach, and hiding the one number on
  // this desk that says whether the money is conserved would be hiding the alarm, not the
  // amount. Privacy covers what an amount reveals, never whether the system is sound.
  const v = Number(n)
  return money(Number.isFinite(v) ? nFmt(v, 4) : String(n))
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load">
    <div class="ckd-cons">
      <div class="ckd-cons-delta" :class="reachable ? (statusText === 'OK' ? 'is-ok' : 'is-breach') : 'is-unknown'"
           data-testid="ckd-conservation-delta">
        <span class="ckd-cons-label">Δ</span>
        <span class="ckd-cons-value">{{ deltaText }}</span>
        <span class="ckd-cons-status">{{ statusText }}</span>
      </div>
      <!-- The honest gap: not a zero, and not silence -->
      <p v-if="!reachable" class="ckd-cons-unknown" data-testid="ckd-conservation-unknown">
        {{ t('cockpit.conservation.unreachable', 'The EventStore did not answer. This is not a zero — it is a question that was not asked.') }}
      </p>
      <dl v-else class="ckd-cons-rows">
        <div><dt>{{ t('cockpit.conservation.net', 'net supply') }}</dt><dd>{{ fmt(data?.net_supply) }}</dd></div>
        <div><dt>{{ t('cockpit.conservation.circ', 'circulating') }}</dt><dd>{{ fmt(data?.total_circulating) }}</dd></div>
      </dl>
      <p class="ckd-cons-foot">
        <RecordLink kind="conservation" :label="t('cockpit.door.audit', 'Audit logs')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-cons { display: flex; flex-direction: column; gap: .5rem; }
.ckd-cons-delta { display: flex; align-items: baseline; gap: .5rem; padding: .4rem .55rem; border-radius: 7px; border: 1px solid var(--nc-border, rgba(255,255,255,.08)); }
.ckd-cons-delta.is-ok { border-color: rgba(63,185,80,.35); background: rgba(63,185,80,.06); }
.ckd-cons-delta.is-breach { border-color: rgba(248,81,73,.45); background: rgba(248,81,73,.07); }
.ckd-cons-delta.is-unknown { border-color: rgba(210,153,34,.4); background: rgba(210,153,34,.05); }
.ckd-cons-label { font-size: 1rem; color: var(--nc-text-dim, #8b949e); }
.ckd-cons-value { flex: 1; font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: 1.05rem; color: var(--nc-text-primary, #e6edf3); }
.ckd-cons-status { font-size: .68rem; letter-spacing: .08em; color: var(--nc-text-dim, #8b949e); }
.ckd-cons-unknown { margin: 0; font-size: .72rem; color: var(--nc-warning, #d29922); }
.ckd-cons-rows { margin: 0; display: flex; flex-direction: column; gap: .2rem; }
.ckd-cons-rows > div { display: flex; justify-content: space-between; gap: .5rem; font-size: .72rem; }
.ckd-cons-rows dt { color: var(--nc-text-dim, #8b949e); margin: 0; }
.ckd-cons-rows dd { margin: 0; font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-secondary, #c9d1d9); }
.ckd-cons-foot { margin: .3rem 0 0; font-size: .62rem; }
</style>
