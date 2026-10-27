<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — EXCHANGE RATES: what one unit of this frame's currency buys in each currency it can
 * convert to, and back.
 *
 * Public read over `GET /teg/fx/rates`, the same answer the Forex desk renders. Three answers are kept apart:
 * a FAILED read is the pane's error state; `available: false` is this registry saying FX is off (with its reason),
 * shown as the pane's honest empty state; and `available: true` with no pairs is a registry with FX on and no
 * pool to quote from. A rate is a number with a time, so the head carries the source's own `as_of`.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { agoShort } from '@/services/cockpit/when'
import { fmt } from '@/services/cockpit/num'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.forex

interface Pair { a: string; b: string; aPerB: number | null; bPerA: number | null }

const available = ref<boolean | null>(null)
const reason = ref('')
const mode = ref('')
const asOf = ref<string | null>(null)
const pairs = ref<Pair[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

async function load() {
  try {
    const r = await apiClient.get('/teg/fx/rates')
    const d = r.data || {}
    available.value = d.available === true
    reason.value = String(d.reason || '')
    mode.value = String(d.rate_mode || '')
    asOf.value = (d.as_of || null) as string | null
    pairs.value = (Array.isArray(d.pairs) ? d.pairs : []).map((p: any) => ({
      a: String(p?.a || ''), b: String(p?.b || ''), aPerB: num(p?.a_per_b), bPerA: num(p?.b_per_a),
    }))
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && (available.value === false || pairs.value.length === 0))
const emptyText = computed(() => available.value === false
  ? (reason.value
      ? tp('cockpit.fx.offWhy', 'Currency exchange is off on this registry: {r}', { r: reason.value })
      : t('cockpit.fx.off', 'Currency exchange is off on this registry.'))
  : t('cockpit.fx.noPairs', 'Currency exchange is on, but no pool quotes a pair yet.'))

const head = computed(() => [
  pairs.value.length === 1 ? t('cockpit.fx.headOne', '1 pair') : tp('cockpit.fx.head', '{n} pairs', { n: pairs.value.length }),
  mode.value ? tp('cockpit.fx.mode', '{m} rates', { m: mode.value }) : '',
  asOf.value ? tp('cockpit.fx.asOf', 'as of {age} ago', { age: agoShort(asOf.value) }) : '',
].filter(Boolean).join(' · '))

/** Four significant decimals for a rate near 1, more for a small one: a rate rounded to 0.00 is a wrong rate. */
function rate(v: number | null): string {
  if (v === null) return '—'
  return Math.abs(v) >= 0.01 ? fmt(v, 4, 4) : v.toPrecision(3)
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="emptyText">
    <div class="fx" data-testid="ckd-forex">
      <p class="fx-head" data-testid="fx-head">{{ head }}</p>
      <table class="fx-t">
        <thead>
          <tr>
            <th class="fx-pair">{{ t('cockpit.fx.pair', 'pair') }}</th>
            <th class="fx-n">{{ t('cockpit.fx.forward', '1 first buys') }}</th>
            <th class="fx-n">{{ t('cockpit.fx.back', '1 second buys') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in pairs" :key="`${p.a}-${p.b}`" data-testid="fx-row">
            <td class="fx-pair">{{ p.a }} / {{ p.b }}</td>
            <td class="fx-n">{{ rate(p.bPerA) }}<span class="fx-ccy">{{ p.b }}</span></td>
            <td class="fx-n">{{ rate(p.aPerB) }}<span class="fx-ccy">{{ p.a }}</span></td>
          </tr>
        </tbody>
      </table>
      <p class="fx-foot" data-testid="fx-foot">
        {{ t('cockpit.fx.foot', 'A quote on the Forex desk includes its fee; these are the pool rates before it.') }}
        <RecordLink kind="forex" class="ckd-doorsep" :label="t('cockpit.door.forex', 'Open the forex desk')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.fx { display: flex; flex-direction: column; gap: .35rem; }
.fx-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.fx-t { width: 100%; border-collapse: collapse; font-size: .72rem; }
.fx-t th { font-size: .58rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #8b949e);
  font-weight: 500; text-align: right; padding-bottom: .2rem; }
.fx-t th.fx-pair { text-align: left; }
.fx-t td { padding: .1rem 0; color: var(--nc-text-secondary, #c9d1d9); }
.fx-pair { text-align: left; font-weight: 600; white-space: nowrap; }
.fx-n { text-align: right; font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  white-space: nowrap; padding-left: .5rem; }
.fx-ccy { font-size: .55rem; color: var(--nc-text-muted, #8b949e); margin-left: .2rem; }
.fx-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
