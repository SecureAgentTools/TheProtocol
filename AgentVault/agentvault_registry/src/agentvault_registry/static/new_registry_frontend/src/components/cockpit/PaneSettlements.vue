<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — SETTLEMENTS: cross-registry dispute settlements, and the ones waiting for an admin.
 *
 * Admin only (the enforcement flag), over `GET /federation/disputes/settlements` (the newest hundred). The pane
 * counts the rows itself: a settlement waits for a decision in PENDING_ADMIN_APPROVAL (the approve and reject
 * rails accept only that state), while the endpoint's own `stats.pending` counts the slash in flight
 * (PENDING_SLASH, SLASHING). Two different questions; the head says both, and the waiting rows are listed.
 * Approving or rejecting moves money between frames and stays on the Settlements page.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { agoShort } from '@/services/cockpit/when'
import { reportAttention, clearAttention } from '@/services/cockpit/attention'
import { fmt } from '@/services/cockpit/num'
import { usePrivacy } from '@/composables/usePrivacy'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.settlements
const SHOWN = 5
const WAITING = 'PENDING_ADMIN_APPROVAL'
const IN_FLIGHT = new Set(['PENDING_SLASH', 'SLASHING'])

interface Row { id: string; status: string; amount: number; defendant: string; origin: string; at: string | null }

const rows = ref<Row[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

function host(url: string): string {
  try { return new URL(url).host } catch { return url.replace(/^[a-z]+:\/\//i, '').split('/')[0] }
}

async function load() {
  try {
    const r = await apiClient.get('/federation/disputes/settlements')
    const list: any[] = Array.isArray(r.data?.settlements) ? r.data.settlements : []
    rows.value = list.map(s => ({
      id: String(s?.id ?? ''), status: String(s?.status || '').toUpperCase(),
      amount: Number(s?.requested_amount) || 0,
      defendant: String(s?.defendant_did || ''), origin: host(String(s?.origin_registry_url || '')),
      at: (s?.requested_at || s?.created_at || null) as string | null,
    }))
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null; clearAttention('settlements') })

const waiting = computed(() => rows.value.filter(r => r.status === WAITING))
const inFlight = computed(() => rows.value.filter(r => IN_FLIGHT.has(r.status)).length)
const failed = computed(() => rows.value.filter(r => r.status === 'FAILED').length)
const empty = computed(() => !loading.value && rows.value.length === 0)
watch(() => waiting.value.length, (n) => reportAttention('settlements', n, n === 1 ? t('cockpit.attn.settlementsOne', '1 settlement waits for a decision')
  : tp('cockpit.attn.settlements', '{n} settlements wait for a decision', { n })), { immediate: true })

function didTail(did: string): string {
  const s = did.split(':').pop() || did
  return s.length > 12 ? `${s.slice(0, 8)}…` : s
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.stl.empty', 'No cross-registry settlement has been asked of this registry.')">
    <div class="stl" data-testid="ckd-settlements">
      <p class="stl-head" data-testid="stl-head" :class="{ 'is-warn': waiting.length > 0 }">
        {{ tp('cockpit.stl.head', '{w} waiting for a decision · {f} slashing · {x} failed', { w: waiting.length, f: inFlight, x: failed }) }}
      </p>
      <ul v-if="waiting.length" class="stl-list">
        <li v-for="s in waiting.slice(0, SHOWN)" :key="s.id" class="stl-row" data-testid="stl-row">
          <span class="stl-amt">{{ money(fmt(s.amount, 2)) }}</span>
          <span class="stl-who" :title="s.defendant">{{ tp('cockpit.stl.against', 'against {d}', { d: didTail(s.defendant) }) }}</span>
          <span class="stl-meta">{{ tp('cockpit.stl.from', 'asked by {h}', { h: s.origin || '?' }) }}<template v-if="s.at"> · {{ tp('cockpit.stl.age', '{age} ago', { age: agoShort(s.at) }) }}</template></span>
        </li>
      </ul>
      <p v-else class="stl-none">{{ t('cockpit.stl.noneWaiting', 'Nothing is waiting for your decision.') }}</p>
      <p class="stl-foot" data-testid="stl-foot">
        {{ tp('cockpit.stl.foot', 'Counted over the newest {n} settlements.', { n: rows.length }) }}
        <RecordLink kind="settlements" class="ckd-doorsep" :label="t('cockpit.door.settlements', 'Open settlements')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.stl { display: flex; flex-direction: column; gap: .35rem; }
.stl-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.stl-head.is-warn { color: var(--nc-warning, #d29922); }
.stl-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
.stl-row { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: .5rem; min-width: 0; }
.stl-amt { font-size: .72rem; color: var(--nc-primary, #00e5ff); font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.stl-who { font-size: .7rem; color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stl-meta { grid-column: 1 / -1; font-size: .64rem; color: var(--nc-text-muted, #8b949e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stl-none { margin: 0; font-size: .7rem; color: var(--nc-text-muted, #8b949e); }
.stl-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
