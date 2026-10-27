<script setup lang="ts">
/**
 * §COCKPIT P1 — FLEET HEALTH. Public network metrics, read as published.
 * Source: `GET /api/v1/metrics/network-health` (no auth), through the vhost.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { appLocale } from '@/services/appLocale'

const { t, tp } = useI18n()
const def = PANES.fleet
const data = ref<any>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try { const r = await apiClient.get('/metrics/network-health'); data.value = r.data; err.value = ''; readAt.value = Date.now() }
  catch (e: any) { err.value = e?.response?.data?.detail || e?.message || 'unreachable' }
  finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const services = computed<[string, any][]>(() => Object.entries(data.value?.services || {}))
const score = computed(() => Number(data.value?.overall_health_score ?? 0))
/** §COCKPITDESK (2026-10-14) — why the score is what it is, as the registry computed it (`score_deductions`, one formula,
 *  server-side). "30.8" beside three services at 99.9% said nothing: on sbx-alpha it was 65.5 points for a 755 ms p95 and
 *  4.0 for 1.98% errors. A registry that predates the field shows no line rather than a guess. */
const fmt = (n: number, digits = 1) => n.toLocaleString(appLocale(), { maximumFractionDigits: digits })
const why = computed<string[]>(() => {
  const d = data.value?.score_deductions
  if (!d || typeof d !== 'object') return []
  const out: string[] = []
  const lat = Number(d.latency_p95), err = Number(d.errors)
  if (Number.isFinite(lat) && lat > 0) out.push(tp('cockpit.fleet.whyLatency', '−{n} for a {ms} ms p95', { n: fmt(lat), ms: fmt(Number(data.value?.response_time_p95 ?? 0)) }))
  if (Number.isFinite(err) && err > 0) out.push(tp('cockpit.fleet.whyErrors', '−{n} for {pct}% errors', { n: fmt(err), pct: fmt(Number(data.value?.error_rate ?? 0), 2) }))
  return out
})
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load">
    <div class="ckd-fleet">
      <div class="ckd-fleet-score" data-testid="ckd-fleet-score">
        <span class="ckd-fleet-num">{{ score.toFixed(1) }}</span>
        <span class="ckd-fleet-cap">{{ t('cockpit.fleet.score', 'health score') }}</span>
      </div>
      <p v-if="why.length" class="ckd-fleet-why" data-testid="ckd-fleet-why"
         :title="t('cockpit.fleet.whyHint', 'The registry starts at 100 and takes 2 points per percent of failed requests and 1 point per 10 ms of p95 above 100 ms, over the last hour.')">
        100 {{ why.join(' · ') }}
      </p>
      <ul class="ckd-fleet-svcs">
        <li v-for="[name, s] in services" :key="name">
          <span class="ckd-dot" :class="s?.status === 'healthy' ? 'is-ok' : 'is-bad'" />
          <span class="ckd-svc">{{ name }}</span>
          <span class="ckd-up">{{ s?.uptime ?? '—' }}%</span>
        </li>
      </ul>
      <p class="ckd-fleet-lat">
        p50 {{ data?.response_time_p50 ?? '—' }}ms · p95 {{ data?.response_time_p95 ?? '—' }}ms
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-fleet { display: flex; flex-direction: column; gap: .45rem; }
.ckd-fleet-score { display: flex; align-items: baseline; gap: .4rem; }
.ckd-fleet-num { font-size: 1.3rem; font-weight: 600; color: var(--nc-primary, #00e5ff); font-family: var(--nc-font-mono, ui-monospace, monospace); }
.ckd-fleet-cap { font-size: .68rem; letter-spacing: .06em; color: var(--nc-text-dim, #8b949e); text-transform: uppercase; }
.ckd-fleet-why { margin: -.2rem 0 0; font-size: .66rem; color: var(--nc-text-secondary, #c9d1d9); font-family: var(--nc-font-mono, ui-monospace, monospace); cursor: help; }
.ckd-fleet-svcs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .18rem; }
.ckd-fleet-svcs li { display: flex; align-items: center; gap: .4rem; font-size: .72rem; }
.ckd-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.ckd-dot.is-ok { background: var(--nc-success, #3fb950); }
.ckd-dot.is-bad { background: var(--nc-danger, #f85149); }
.ckd-svc { flex: 1; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-up { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-dim, #8b949e); }
.ckd-fleet-lat { margin: 0; font-size: .68rem; color: var(--nc-text-muted, #6e7681); font-family: var(--nc-font-mono, ui-monospace, monospace); }
</style>
