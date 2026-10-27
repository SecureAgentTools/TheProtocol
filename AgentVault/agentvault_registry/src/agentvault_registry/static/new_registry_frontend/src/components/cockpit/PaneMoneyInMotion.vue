<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPIT P1 — MONEY IN MOTION. The developer's own aggregate, dev-scoped.
 *
 * Source: `GET /developers/me/teg-summary`. §ORGPOCKET O4 made that response
 * DECLARE the currency it summed, precisely so a caller labels from the same
 * place the number came from instead of from the viewer's own frame. This pane
 * renders `currency` verbatim and shows NOTHING where the field is absent —
 * §FOREIGNACT's rule: empty unit, never the wrong unit.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'

const { t } = useI18n()
const { money } = usePrivacy()
const def = PANES.money
const sum = ref<any>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try { const r = await apiClient.get('/developers/me/teg-summary'); sum.value = r.data; err.value = ''; readAt.value = Date.now() }
  catch (e: any) { err.value = e?.response?.data?.detail || e?.message || 'unreachable' }
  finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 45) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

/** The unit the SUM declared. Absent ⇒ we say so; we never substitute the frame's. */
const unit = computed(() => String(sum.value?.currency || ''))
function fmt(v: any): string {
  const n = Number(v)
  return money(Number.isFinite(n) ? nFmt(n, 6) : '—')
}
const rows = computed(() => sum.value ? [
  { k: t('cockpit.money.liquid', 'liquid'), v: fmt(sum.value.total_liquid_balance) },
  { k: t('cockpit.money.staked', 'locked'), v: fmt(sum.value.total_staked_balance) },
  { k: t('cockpit.money.total',  'total'),  v: fmt(sum.value.total_balance) },
] : [])
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load">
    <div class="ckd-money">
      <p class="ckd-money-unit" data-testid="ckd-money-unit">
        <template v-if="unit">{{ t('cockpit.money.denominated', 'denominated in') }} <b>{{ unit }}</b></template>
        <span v-else class="ckd-unit-missing">{{ t('cockpit.money.noUnit', 'the summary did not declare a currency') }}</span>
      </p>
      <dl class="ckd-money-rows">
        <div v-for="r in rows" :key="r.k"><dt>{{ r.k }}</dt><dd>{{ r.v }}</dd></div>
      </dl>
      <p class="ckd-money-foot">
        {{ sum?.active_agent_count ?? '—' }} / {{ sum?.agent_count ?? '—' }}
        {{ t('cockpit.money.agentsActive', 'agents active') }}
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-money { display: flex; flex-direction: column; gap: .4rem; }
.ckd-money-unit { margin: 0; font-size: .68rem; color: var(--nc-text-dim, #8b949e); letter-spacing: .03em; }
.ckd-money-unit b { color: var(--nc-primary, #00e5ff); }
.ckd-unit-missing { color: var(--nc-warning, #d29922); }
.ckd-money-rows { margin: 0; display: flex; flex-direction: column; gap: .22rem; }
/* §COCKPITTILES T3 — his words: "some look very cheap for displaying huge sums". Three
   label/number lines at .76rem in a laptop-sized box is why. The box is one row unit now
   (T1) and the FIGURE is the thing that reads: tabular so the columns line up, and never
   truncated — a rounded number that does not say it rounded is a wrong number. */
.ckd-money-rows > div { display: flex; justify-content: space-between; align-items: baseline;
  gap: .5rem; font-size: .76rem; }
.ckd-money-rows dt { margin: 0; color: var(--nc-text-dim, #8b949e); }
.ckd-money-rows dd { margin: 0; font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; font-size: .92rem; letter-spacing: -.01em;
  color: var(--nc-text-primary, #e6edf3); }
.ckd-money-foot { margin: 0; font-size: .68rem; color: var(--nc-text-muted, #6e7681); }
</style>
