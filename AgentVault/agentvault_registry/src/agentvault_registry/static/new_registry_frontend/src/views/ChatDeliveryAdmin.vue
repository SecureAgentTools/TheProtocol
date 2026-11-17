<!-- V0663 (order gwo_01681f32a8cfe7390b773532, his suggestion 6): the admins' chat delivery panel (#/admin/chat-delivery,
     behind the federation admin flag). Per peer, what waits in the chat federation outbox, read from
     GET /admin/chat/federation/delivery (services/chat_delivery on the registry): the verdict, the rows waiting and the
     age of the oldest, the most attempts, the next attempt, the latest error, the last delivery.
     V0664 (order gwo_efdd53bd198423a5ec2b742d): a peer's rows open from its line (GET .../delivery/rows), each with its
     state; Retry now and Drop are offered only where the registry says the row may take them, a drop asks for its
     reason first; a refusal is shown in the registry's words. The message itself is never deleted. -->
<template>
  <div class="cdp">
    <header class="cdp-head">
      <h1 class="cdp-title">{{ t('chatDelivery.title', 'Chat delivery') }}</h1>
      <p class="cdp-lede">{{ t('chatDelivery.lede', 'What waits in the cross-registry chat outbox, per peer. A row that reached its last attempt waits for a person.') }}</p>
      <button type="button" class="cdp-btn" :disabled="loading" data-testid="cdp-refresh" @click="load">{{ t('chatDelivery.refresh', 'Refresh') }}</button>
    </header>

    <p v-if="error" class="cdp-error" role="alert" data-testid="cdp-error">{{ t('chatDelivery.readFailed', 'The panel could not be read; try again.') }}</p>
    <template v-else-if="answer">
      <p v-if="!answer.enabled" class="cdp-note" data-testid="cdp-off">{{ t('chatDelivery.off', 'Cross-registry chat is switched off on this registry, so nothing is delivered to peers.') }}</p>
      <p class="cdp-headline" :data-state="headlineState" data-testid="cdp-headline">{{ headline }}</p>
      <p class="cdp-worker" data-testid="cdp-worker">
        {{ tp('chatDelivery.worker', 'The delivery worker: {cycles} cycles, {delivered} delivered, {failed} failed; read at {at}.', {
          cycles: answer.worker?.cycles ?? '?', delivered: answer.worker?.delivered ?? '?', failed: answer.worker?.failed ?? '?', at: shortTime(answer.as_of) }) }}
      </p>
      <table class="cdp-table">
        <thead>
          <tr>
            <th>{{ t('chatDelivery.peer', 'Peer') }}</th><th>{{ t('chatDelivery.state', 'State') }}</th>
            <th>{{ t('chatDelivery.waiting', 'Waiting') }}</th><th>{{ t('chatDelivery.oldest', 'Oldest') }}</th>
            <th>{{ t('chatDelivery.attempts', 'Attempts') }}</th><th>{{ t('chatDelivery.lastError', 'Latest error') }}</th>
            <th>{{ t('chatDelivery.lastDelivered', 'Last delivered') }}</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="p in answer.peers" :key="p.peer_base_url">
          <tr class="cdp-row" :data-verdict="p.verdict" data-testid="cdp-row">
            <td><span class="cdp-name">{{ p.name || p.peer_base_url }}</span>
              <span class="cdp-url">{{ p.peer_base_url }}</span>
              <span v-if="!p.active_peer" class="cdp-gone">{{ t('chatDelivery.notAPeer', 'no longer an active peer') }}</span></td>
            <td><span class="cdp-verdict" :data-verdict="p.verdict">{{ verdictWord(p.verdict) }}</span></td>
            <td class="cdp-num">{{ p.waiting }}<span v-if="p.given_up" class="cdp-gave"> ({{ tp('chatDelivery.givenUp', '{n} given up', { n: p.given_up }) }})</span>
              <span v-if="p.dropped" class="cdp-dropped" data-testid="cdp-dropped">{{ tp('chatDelivery.dropped', '{n} dropped', { n: p.dropped }) }}</span>
              <button v-if="p.waiting" type="button" class="cdp-btn cdp-open" data-testid="cdp-open" @click="toggleRows(p.peer_base_url)">
                {{ openPeer === p.peer_base_url ? t('chatDelivery.hideRows', 'Hide rows') : t('chatDelivery.rows', 'Rows') }}</button></td>
            <td class="cdp-num" data-testid="cdp-age">{{ p.oldest_age_seconds == null ? '' : age(p.oldest_age_seconds) }}</td>
            <td class="cdp-num">{{ p.waiting ? `${p.attempts_max} / ${answer.max_attempts}` : '' }}</td>
            <td class="cdp-err">{{ p.last_error || '' }}</td>
            <td class="cdp-num">{{ p.last_delivered_at ? shortTime(p.last_delivered_at) : t('chatDelivery.never', 'never') }}</td>
          </tr>
          <tr v-if="openPeer === p.peer_base_url" class="cdp-detail">
            <td colspan="7">
              <p class="cdp-note">{{ t('chatDelivery.actNote', 'Retry now tries a row at once (a given-up row gets one more try). A dropped row is never sent; its message stays in the thread, and the reason is kept.') }}</p>
              <p v-if="rowsError" class="cdp-error" role="alert">{{ t('chatDelivery.rowsFailed', 'The rows could not be read; try again.') }}</p>
              <p v-if="actError" class="cdp-error" role="alert" data-testid="cdp-act-error">{{ actError }}</p>
              <p v-if="!rowsError && rows.length === 0" class="cdp-note">{{ t('chatDelivery.rowsEmpty', 'Nothing waits for this peer.') }}</p>
              <div v-for="r in rows" :key="r.id" class="cdp-item" :data-state="r.state" data-testid="cdp-item">
                <span class="cdp-verdict" :data-verdict="r.state">{{ stateWord(r) }}</span>
                <span class="cdp-item-what">{{ r.kind === 'event' ? t('chatDelivery.kindEvent', 'event') : t('chatDelivery.kindMessage', 'message') }}
                  {{ tp('chatDelivery.seq', 'seq {seq}', { seq: r.seq }) }} · <span class="cdp-url">{{ r.conversation_id }}</span></span>
                <span class="cdp-num">{{ tp('chatDelivery.rowAttempts', '{n} / {max} attempts', { n: r.attempts, max: rowsMax }) }}</span>
                <span class="cdp-err">{{ r.last_error || '' }}</span>
                <span class="cdp-acts">
                  <button type="button" class="cdp-btn" data-testid="cdp-retry" :disabled="!r.can_retry || acting" @click="retry(r)">{{ t('chatDelivery.retry', 'Retry now') }}</button>
                  <button type="button" class="cdp-btn" data-testid="cdp-drop" :disabled="!r.can_drop || acting" @click="askDrop(r)">{{ t('chatDelivery.drop', 'Drop') }}</button>
                </span>
                <div v-if="dropFor === r.id" class="cdp-reason">
                  <label class="cdp-note" :for="`cdp-reason-${r.id}`">{{ t('chatDelivery.reasonLabel', 'Why is this row dropped? The reason is kept with it.') }}</label>
                  <input :id="`cdp-reason-${r.id}`" v-model="reason" class="cdp-input" maxlength="500" data-testid="cdp-reason"
                         :placeholder="t('chatDelivery.reasonPh', 'for example: the peer left the federation')" />
                  <button type="button" class="cdp-btn" data-testid="cdp-drop-confirm" :disabled="!reason.trim() || acting" @click="drop(r)">{{ t('chatDelivery.dropConfirm', 'Drop the row') }}</button>
                  <button type="button" class="cdp-btn" @click="dropFor = null">{{ t('chatDelivery.cancel', 'Cancel') }}</button>
                </div>
              </div>
            </td>
          </tr>
          </template>
        </tbody>
      </table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'

interface PeerLine {
  peer_base_url: string; name: string | null; active_peer: boolean; waiting: number; oldest_age_seconds: number | null
  attempts_max: number; given_up: number; last_error: string | null; last_delivered_at: string | null
  dropped?: number
  verdict: 'given_up' | 'late' | 'waiting' | 'clear'
}
interface OutboxRow {
  id: string; kind: 'message' | 'event'; conversation_id: string; seq: number; attempts: number
  last_error: string | null; state: 'given_up' | 'held' | 'due' | 'backing_off'; held_by: string | null
  can_retry: boolean; can_drop: boolean
}
interface Answer {
  enabled: boolean; as_of: string; late_seconds: number; max_attempts: number
  worker?: { cycles?: number | null; delivered?: number; failed?: number } | null
  peers: PeerLine[]
}

const { t, tp } = useI18n()
const answer = ref<Answer | null>(null)
const error = ref(false)
const loading = ref(false)
const openPeer = ref<string | null>(null)
const rows = ref<OutboxRow[]>([])
const rowsMax = ref(0)
const rowsError = ref(false)
const actError = ref('')
const acting = ref(false)
const dropFor = ref<string | null>(null)
const reason = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = false
  try {
    const { data } = await apiClient.get('/admin/chat/federation/delivery')
    answer.value = data
  } catch {
    error.value = true
    answer.value = null
  } finally {
    loading.value = false
  }
}

async function loadRows(peer: string): Promise<void> {
  rowsError.value = false
  try {
    const { data } = await apiClient.get('/admin/chat/federation/delivery/rows', { params: { peer } })
    rows.value = data?.rows || []
    rowsMax.value = data?.max_attempts ?? 0
  } catch {
    rowsError.value = true
    rows.value = []
  }
}

async function toggleRows(peer: string): Promise<void> {
  actError.value = ''
  dropFor.value = null
  if (openPeer.value === peer) {
    openPeer.value = null
    return
  }
  openPeer.value = peer
  await loadRows(peer)
}

function refusal(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' && d ? d : t('chatDelivery.actFailed', 'The registry refused the action.')
}

async function act(call: () => Promise<unknown>): Promise<void> {
  acting.value = true
  actError.value = ''
  try {
    await call()
    dropFor.value = null
    reason.value = ''
  } catch (e) {
    actError.value = refusal(e)
  } finally {
    acting.value = false
  }
  await load()
  if (openPeer.value) await loadRows(openPeer.value)
}

function retry(r: OutboxRow): Promise<void> {
  return act(() => apiClient.post(`/admin/chat/federation/delivery/rows/${encodeURIComponent(r.id)}/retry`))
}

function askDrop(r: OutboxRow): void {
  actError.value = ''
  reason.value = ''
  dropFor.value = r.id
}

function drop(r: OutboxRow): Promise<void> {
  const why = reason.value.trim()
  return act(() => apiClient.post(`/admin/chat/federation/delivery/rows/${encodeURIComponent(r.id)}/drop`, { reason: why }))
}

function stateWord(r: OutboxRow): string {
  switch (r.state) {
    case 'given_up': return t('chatDelivery.stateGivenUp', 'Given up')
    case 'held': return t('chatDelivery.stateHeld', 'Held behind an earlier row')
    case 'due': return t('chatDelivery.stateDue', 'Due now')
    default: return t('chatDelivery.stateBackingOff', 'Backing off')
  }
}

const headlineState = computed(() => {
  const ps = answer.value?.peers || []
  if (ps.some((p) => p.verdict === 'given_up' || p.verdict === 'late')) return 'stuck'
  if (ps.some((p) => p.verdict === 'waiting')) return 'waiting'
  return 'clear'
})
const headline = computed(() => {
  const ps = answer.value?.peers || []
  const stuck = ps.filter((p) => p.verdict === 'given_up' || p.verdict === 'late').length
  if (headlineState.value === 'stuck') return tp('chatDelivery.stuck', 'Delivery to {n} peer(s) is stuck.', { n: stuck })
  if (headlineState.value === 'waiting') return t('chatDelivery.moving', 'Messages are waiting, none late.')
  return t('chatDelivery.clear', 'Nothing waits for any peer.')
})

function verdictWord(v: PeerLine['verdict']): string {
  switch (v) {
    case 'given_up': return t('chatDelivery.verdictGivenUp', 'Given up')
    case 'late': return t('chatDelivery.verdictLate', 'Late')
    case 'waiting': return t('chatDelivery.verdictWaiting', 'Waiting')
    default: return t('chatDelivery.verdictClear', 'Clear')
  }
}

function age(s: number): string {
  if (s < 90) return `${s} s`
  if (s < 90 * 60) return `${Math.round(s / 60)} min`
  if (s < 48 * 3600) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}

function shortTime(iso: string | null | undefined): string {
  return iso ? `${String(iso).replace('T', ' ').slice(0, 16)}Z` : ''
}

onMounted(load)
</script>

<style scoped>
.cdp { padding: 1.25rem; }
.cdp-head { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.6rem; margin-bottom: 0.8rem; }
.cdp-title { margin: 0; font-size: 1.25rem; font-weight: 500; flex: 1 0 100%; }
.cdp-lede { margin: 0; flex: 1 1 30rem; font-size: 0.82rem; color: var(--nc-text-muted, #9aa0a6); }
.cdp-btn { padding: 4px 12px; border-radius: 3px; cursor: pointer; font-size: 0.78rem; background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); color: var(--nc-text-primary, #e8eaed); }
.cdp-btn:disabled { opacity: 0.5; cursor: default; }
.cdp-error { color: var(--nc-danger, #ef4444); font-size: 0.82rem; }
.cdp-note { font-size: 0.8rem; color: var(--nc-text-muted, #9aa0a6); }
.cdp-headline { margin: 0.4rem 0; font-size: 0.9rem; }
.cdp-headline[data-state='stuck'] { color: var(--nc-danger, #ef4444); }
.cdp-headline[data-state='waiting'] { color: var(--nc-warning, #f59e0b); }
.cdp-worker { margin: 0 0 0.8rem; font-size: 0.76rem; color: var(--nc-text-muted, #9aa0a6); }
.cdp-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.cdp-table th { text-align: left; font-weight: 500; color: var(--nc-text-muted, #9aa0a6); padding: 0.35rem; }
.cdp-row td { padding: 0.4rem 0.35rem; border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08); vertical-align: top; }
.cdp-name { display: block; color: var(--nc-text-primary, #e8eaed); }
.cdp-url { display: block; font-family: ui-monospace, monospace; font-size: 0.7rem; color: var(--nc-text-muted, #9aa0a6); overflow-wrap: anywhere; }
.cdp-gone { display: block; font-size: 0.7rem; color: var(--nc-warning, #f59e0b); }
.cdp-verdict { padding: 1px 6px; border-radius: 3px; border: 1px solid currentColor; font-size: 0.72rem; }
.cdp-verdict[data-verdict='given_up'] { color: var(--nc-danger, #ef4444); }
.cdp-verdict[data-verdict='late'] { color: var(--nc-warning, #f59e0b); }
.cdp-verdict[data-verdict='waiting'] { color: var(--nc-primary-bright, #00e5e5); }
.cdp-verdict[data-verdict='clear'] { color: var(--nc-success-bright, #34d399); }
.cdp-num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.cdp-gave { color: var(--nc-danger, #ef4444); }
.cdp-err { font-family: ui-monospace, monospace; font-size: 0.72rem; overflow-wrap: anywhere; max-width: 28rem; }
.cdp-dropped { display: block; font-size: 0.7rem; color: var(--nc-text-muted, #9aa0a6); }
.cdp-open { margin-top: 0.25rem; padding: 1px 8px; font-size: 0.7rem; }
.cdp-detail td { padding: 0.3rem 0.35rem 0.8rem; background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.03); }
.cdp-item { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; padding: 0.35rem 0;
  border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06); }
.cdp-verdict[data-verdict='held'], .cdp-verdict[data-verdict='backing_off'] { color: var(--nc-warning, #f59e0b); }
.cdp-verdict[data-verdict='due'] { color: var(--nc-primary-bright, #00e5e5); }
.cdp-item-what { font-size: 0.74rem; }
.cdp-acts { display: inline-flex; gap: 0.35rem; margin-left: auto; }
.cdp-reason { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; flex: 1 0 100%; }
.cdp-input { flex: 1 1 18rem; padding: 3px 6px; font-size: 0.76rem; border-radius: 3px; background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); color: var(--nc-text-primary, #e8eaed); }
</style>
