<!-- POCKET · Notification history (§NOTIFLOG 2026-07-27) — every notification DECISION, not just
     the ones that arrived. The 24h reason breakdown sits at the top because the real question is
     never "what did I get", it is "why did I not get that one". Source: /notifications/history. -->
<template>
  <div class="nl-wrap">
    <div class="nl-head">
      <!-- §FINDFIX F5 — embedded (Settings tab) renders a section header, not a
           page <h1>: the tab already carries the page heading, so the old
           double-h1 read as two page titles stacked. Pocket unchanged. -->
      <component :is="embedded ? 'h2' : 'h1'" class="nl-title" :class="{ 'nl-title-embedded': embedded }">
        {{ t('pocket.notifLog.title', 'Notifications') }}</component>
      <button class="nl-refresh" :disabled="loading" :aria-label="t('common.refresh', 'Refresh')" @click="load()">
        <Icon name="mdi:refresh" :class="{ 'nl-spin': loading }" />
      </button>
    </div>

    <!-- 24h breakdown: the debugging surface -->
    <section v-if="!loading && summary.length" class="nl-summary">
      <div class="nl-sum-head">
        <span class="nl-sum-title">{{ t('pocket.notifLog.last24h', 'LAST 24 HOURS') }}</span>
        <span class="nl-sum-mode">{{ t('pocket.notifLog.mode', 'mode') }} {{ mode }}</span>
      </div>
      <ul class="nl-sum-list">
        <li v-for="s in summary" :key="s.outcome + (s.reason || '')" class="nl-sum-row">
          <span class="nl-dot" :class="s.outcome"></span>
          <span class="nl-sum-label">
            {{ outcomeLabel(s.outcome) }}<template v-if="s.reason"> · {{ reasonLabel(s.reason) }}</template>
          </span>
          <span class="nl-sum-n">{{ s.count }}</span>
        </li>
      </ul>
      <p v-if="allSuppressed" class="nl-hint">
        <Icon name="mdi:information" />
        {{ t('pocket.notifLog.allSuppressed', 'Nothing reached a device in this window. Reasons above tell you which knob to turn:') }}
        <strong>default_off</strong> {{ t('pocket.notifLog.defaultOffHint', 'means the type is off for that channel in your matrix.') }}
      </p>
    </section>

    <!-- filters -->
    <div class="nl-filters">
      <button v-for="f in FILTERS" :key="f.id" class="nl-chip" :class="{ on: filter === f.id }"
              @click="setFilter(f.id)">{{ f.label }}</button>
    </div>

    <div v-if="loading" class="nl-list"><div v-for="n in 5" :key="n" class="nl-skel"></div></div>

    <ReadFailedNotice v-else-if="readFailed" :retry="load" />

    <ul v-else-if="entries.length" class="nl-list">
      <li v-for="e in entries" :key="e.id" class="nl-row" :class="e.outcome"
          @click="open = open === e.id ? null : e.id">
        <span class="nl-ico" :class="e.outcome"><Icon :name="iconFor(e.outcome)" /></span>
        <div class="nl-body">
          <div class="nl-label">{{ prettyType(e.type_key) }}</div>
          <div class="nl-sub">
            {{ when(e.created_at) }} · {{ channelLabel(e.channel) }}
            <template v-if="e.reason"> · <span class="nl-reason">{{ reasonLabel(e.reason) }}</span></template>
          </div>
          <div v-if="open === e.id" class="nl-detail">
            <div class="nl-det-title">{{ e.title || t('pocket.notifLog.noTitle', '(no title)') }}</div>
            <div class="nl-det-msg">{{ e.message || t('pocket.notifLog.noBody', '(no body)') }}</div>
            <div class="nl-det-meta">{{ e.type_key }} · {{ e.category }} · {{ e.severity }}</div>
          </div>
        </div>
      </li>
    </ul>

    <div v-else class="nl-empty">
      <span class="nl-empty-ring"><Icon name="mdi:bell-off-outline" /></span>
      <p v-if="unavailable"><strong>{{ t('pocket.notifLog.unavailable', 'History not available on this registry.') }}</strong>
        {{ t('pocket.notifLog.unavailableSub', 'It records from the moment this build is deployed.') }}</p>
      <p v-else><strong>{{ t('pocket.notifLog.emptyTitle', 'Nothing yet.') }}</strong> {{ t('pocket.notifLog.emptySub', 'Decisions appear here as notifications are raised for your account.') }}</p>
    </div>

    <button v-if="!loading && entries.length >= limit" class="nl-more" :disabled="loadingMore" @click="loadMore">
      {{ loadingMore ? t('common.loading', 'Loading…') : t('pocket.notifLog.loadOlder', 'Load older') }}
    </button>
    <p v-if="retentionDays" class="nl-foot">{{ tp('pocket.notifLog.retention', 'History is kept for {n} days.', { n: retentionDays }) }}</p>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

interface Entry {
  id: number; type_key: string; category: string; severity: string; channel: string
  outcome: string; reason: string | null; mode: string; device_id: number | null
  title: string | null; message: string | null; created_at: string | null
}
interface SumRow { outcome: string; reason: string | null; count: number }

// Computed, not a const: the chips must re-label when the locale changes.
const FILTERS = computed(() => [
  { id: '', label: t('pocket.notifLog.filterAll', 'All') },
  { id: 'delivered', label: t('pocket.notifLog.filterDelivered', 'Delivered') },
  { id: 'suppressed', label: t('pocket.notifLog.filterHeld', 'Held back') },
  { id: 'failed', label: t('pocket.notifLog.filterFailed', 'Failed') },
])

const entries = ref<Entry[]>([])
const summary = ref<SumRow[]>([])
const mode = ref('')
const retentionDays = ref(0)
const unavailable = ref(false)
// §FESUITE (2026-10-05): a failed read said "History not available on this registry" (the server's own answer when the
// log is off) over a read that never answered; it says the read failed now. The entries answer one filter: a failed read
// for another filter shows none of the old one's rows, a failed refresh of the same filter keeps them, and an answer that
// arrives after a newer request is dropped.
const readFailed = ref(false)
let shownFilter: string | null = null
let seq = 0
const loading = ref(true)
const loadingMore = ref(false)
const filter = ref<string>('')
const open = ref<number | null>(null)
const limit = 50

const allSuppressed = computed(() =>
  summary.value.length > 0 && !summary.value.some(s => s.outcome === 'delivered' && s.count > 0))

/** "money.received" → "Money received" — the catalog's label_key i18n pass is still open, so the
 *  key itself is the honest fallback rather than an invented English string. */
function prettyType(k: string): string {
  const tail = (k || '').split('.').slice(-1)[0] || k
  const s = tail.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
function channelLabel(c: string): string {
  return c === 'push_mobile' ? t('pocket.notifLog.chanMobile', 'mobile')
       : c === 'push_desktop' ? t('pocket.notifLog.chanDesktop', 'desktop') : c
}
/* The English string is the FALLBACK; the key is what resolves. An outcome or
   reason the server invents later renders as its raw value — a machine fact we
   do not have a translation for is better shown than mislabelled. */
const REASONS: Record<string, [string, string]> = {
  default_off: ['pocket.notifLog.reasonDefaultOff', 'off by default'],
  legacy_pref: ['pocket.notifLog.reasonLegacyPref', 'legacy preference'],
  coalesced: ['pocket.notifLog.reasonCoalesced', 'coalesced'],
  quiet: ['pocket.notifLog.reasonQuiet', 'quiet hours'],
  threshold: ['pocket.notifLog.reasonThreshold', 'below threshold'],
  narrowed: ['pocket.notifLog.reasonNarrowed', 'device allowlist'],
  audience: ['pocket.notifLog.reasonAudience', 'not your audience'],
  mandatory: ['pocket.notifLog.reasonMandatory', 'mandatory'],
  legacy_enable: ['pocket.notifLog.reasonLegacyEnable', 'legacy enabler'],
  rail_error: ['pocket.notifLog.reasonRailError', 'delivery failed'],
}
function reasonLabel(r: string): string { const e = REASONS[r]; return e ? t(e[0], e[1]) : r }
const OUTCOMES: Record<string, [string, string]> = {
  delivered: ['pocket.notifLog.outDelivered', 'delivered'],
  suppressed: ['pocket.notifLog.outSuppressed', 'suppressed'],
  failed: ['pocket.notifLog.outFailed', 'failed'],
}
function outcomeLabel(o: string): string { const e = OUTCOMES[o]; return e ? t(e[0], e[1]) : o }
function iconFor(o: string): string {
  return o === 'delivered' ? 'mdi:check-circle' : o === 'failed' ? 'mdi:alert-circle' : 'mdi:bell-off-outline'
}
function when(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return t('pocket.notifLog.justNow', 'just now')
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' }) + ' ' +
         d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' })
}

async function load(beforeId?: number) {
  const want = filter.value
  const my = beforeId ? seq : ++seq
  if (beforeId) loadingMore.value = true; else loading.value = true
  try {
    const params: Record<string, unknown> = { limit }
    if (want) params.outcome = want
    if (beforeId) params.before_id = beforeId
    const { data } = await apiClient.get('/notifications/history', { params })
    if (my !== seq) return
    unavailable.value = data?.enabled === false && !(data?.entries || []).length
    mode.value = data?.mode || ''
    retentionDays.value = Number(data?.retention_days || 0)
    summary.value = (data?.summary || []) as SumRow[]
    entries.value = beforeId ? [...entries.value, ...(data?.entries || [])] : (data?.entries || [])
    shownFilter = want
    readFailed.value = false
  } catch {
    if (my !== seq || beforeId) return   // an older page that failed: "Load older" stays to press again
    if (shownFilter !== want) { entries.value = []; summary.value = []; unavailable.value = false; readFailed.value = true }
  } finally { if (my === seq) { loading.value = false; loadingMore.value = false } }
}
function loadMore() {
  const last = entries.value[entries.value.length - 1]
  if (last) void load(last.id)
}
function setFilter(f: string) { filter.value = f; open.value = null; void load() }

onMounted(() => { void load() })
</script>

<style scoped>
.nl-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; box-sizing: border-box; }
.nl-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.8rem; }
.nl-title { font-size: 1.15rem; margin: 0; flex: 1 1 auto; }
.nl-title-embedded { font-size: 0.95rem; text-transform: uppercase; letter-spacing: .06em; opacity: .85; }
.nl-refresh { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px; width: 2rem; height: 2rem; display: grid; place-items: center; color: inherit; cursor: pointer; }
.nl-refresh:disabled { opacity: 0.5; }
.nl-spin { animation: nl-rot 1s linear infinite; }
@keyframes nl-rot { to { transform: rotate(360deg); } }

.nl-summary { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
  border-radius: 14px; padding: 0.7rem 0.8rem; margin-bottom: 0.8rem; }
.nl-sum-head { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.5rem; }
.nl-sum-title { font-size: 0.64rem; letter-spacing: 0.1em; opacity: 0.45; font-weight: 700; flex: 1 1 auto; }
.nl-sum-mode { font-size: 0.62rem; opacity: 0.4; font-variant-numeric: tabular-nums; }
.nl-sum-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.nl-sum-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem; }
.nl-sum-label { flex: 1 1 auto; opacity: 0.85; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nl-sum-n { font-variant-numeric: tabular-nums; font-weight: 700; }
.nl-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; flex: 0 0 auto; background: #7c8797; }
.nl-dot.delivered { background: #34d399; }
.nl-dot.suppressed { background: #f59e0b; }
.nl-dot.failed { background: #ff8a8a; }
.nl-hint { font-size: 0.7rem; opacity: 0.6; margin: 0.55rem 0 0; line-height: 1.45; display: flex; gap: 0.35rem; }
.nl-hint :deep(svg) { width: 0.85rem; height: 0.85rem; flex: 0 0 auto; margin-top: 0.15rem; }

.nl-filters { display: flex; gap: 0.35rem; margin-bottom: 0.7rem; flex-wrap: wrap; }
.nl-chip { font-size: 0.72rem; padding: 0.28rem 0.6rem; border-radius: 999px; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); color: inherit; }
.nl-chip.on { background: rgba(0,212,255,0.12); border-color: rgba(0,212,255,0.35); color: var(--nc-primary, #00d4ff); }

.nl-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.nl-row { display: flex; align-items: flex-start; gap: 0.65rem; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 13px; padding: 0.65rem 0.75rem; cursor: pointer; }
.nl-row.delivered { border-color: rgba(52,211,153,0.22); }
.nl-ico { width: 2.05rem; height: 2.05rem; border-radius: 11px; display: grid; place-items: center; flex: 0 0 auto; }
.nl-ico :deep(svg) { width: 1rem; height: 1rem; }
.nl-ico.delivered { background: rgba(16,185,129,0.12); color: #34d399; }
.nl-ico.suppressed { background: rgba(245,158,11,0.1); color: #f59e0b; }
.nl-ico.failed { background: rgba(255,107,107,0.1); color: #ff8a8a; }
.nl-body { flex: 1 1 auto; min-width: 0; }
.nl-label { font-size: 0.85rem; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nl-sub { font-size: 0.68rem; opacity: 0.5; font-variant-numeric: tabular-nums; }
.nl-reason { opacity: 0.95; }
.nl-detail { margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.07); }
.nl-det-title { font-size: 0.78rem; font-weight: 600; }
.nl-det-msg { font-size: 0.74rem; opacity: 0.75; margin-top: 0.15rem; line-height: 1.4; overflow-wrap: anywhere; }
.nl-det-meta { font-size: 0.64rem; opacity: 0.4; margin-top: 0.35rem; overflow-wrap: anywhere; }

.nl-skel { height: 62px; border-radius: 13px; background: linear-gradient(90deg,
  rgba(255,255,255,0.04), rgba(255,255,255,0.07), rgba(255,255,255,0.04)); }
.nl-empty { text-align: center; padding: 2.2rem 1rem; opacity: 0.7; }
.nl-empty-ring { width: 3rem; height: 3rem; border-radius: 50%; display: inline-grid; place-items: center;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); margin-bottom: 0.6rem; }
.nl-empty p { font-size: 0.82rem; line-height: 1.5; }
.nl-more { width: 100%; margin-top: 0.6rem; padding: 0.6rem; border-radius: 12px; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); color: inherit; font-size: 0.78rem; }
.nl-foot { font-size: 0.64rem; color: var(--nc-text-muted, #8f9399); text-align: center; margin-top: 0.8rem; } /* §FESUITE: was opacity 0.35, 2.6:1 */
</style>
