<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * B3 (RBAC plan) — Spend approvals: the human half of the step-up queue.
 *
 * When one of this developer's agents tries to spend over its `require_approval_above`
 * threshold, the spend PARKS as a pending row (pushed to Pocket/desktop) instead of
 * dead-ending. This panel lists the queue; Approve arms a single-use, 15-minute
 * authorization the agent's RETRY of the exact same spend consumes; Deny (or 30
 * minutes of silence) keeps the deny. Mounted as a Settings tab, so it renders in
 * Pocket mode too — the phone can be the approval device without extra plumbing.
 */
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { agentAuthzApi, type SpendApproval } from '@/services/api/agentAuthz'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const rows = ref<SpendApproval[]>([])
const loading = ref(false)
// §FESUITE (2026-10-05): the queue's read has a state. A failed read drew "Nothing waiting on you" (an ask parked here
// expires in 30 minutes, which is a deny); it says the queue could not be read now. The rows answer one filter: a switch
// to the other filter never shows the old one's rows under the new chip, while a failed refresh of the same filter (the
// 20 s poll, the read after a decision) keeps the list that was shown. An answer that arrives after a newer request is
// dropped.
const listRead = ref<'loading' | 'ok' | 'failed'>('loading')
let shownPending: boolean | null = null
let seq = 0
const busy = ref<string>('')      // approval id with an in-flight decision
const msg = ref('')
const msgOk = ref(false)
const onlyPending = ref(true)
let timer: number | undefined

async function load() {
  const want = onlyPending.value
  const my = ++seq
  if (shownPending !== want) { rows.value = []; listRead.value = 'loading' }
  loading.value = true
  try {
    const { approvals } = await agentAuthzApi.spendApprovals(want ? 'pending' : undefined)
    if (my !== seq) return
    rows.value = approvals
    shownPending = want
    listRead.value = 'ok'
  } catch {
    if (my !== seq) return
    if (shownPending !== want) listRead.value = 'failed'   // a failed refresh of the same filter keeps the list
  } finally {
    if (my === seq) loading.value = false
  }
}

async function decide(id: string, decision: 'approve' | 'deny') {
  busy.value = id
  msg.value = ''
  try {
    if (decision === 'approve') {
      const r = await agentAuthzApi.approveSpend(id)
      msgOk.value = true
      msg.value = t('agentAccess.approvals.approvedMsg',
        'Approved: usable once within {m} minutes.').replace('{m}', String(r.usable_for_minutes))
    } else {
      await agentAuthzApi.denySpend(id)
      msgOk.value = true
      msg.value = t('agentAccess.approvals.deniedMsg', 'Denied. The agent stays blocked.')
    }
  } catch (e: any) {
    msgOk.value = false
    msg.value = e?.response?.data?.detail || e?.message || 'failed'
  } finally {
    busy.value = ''
    await load()
  }
}

function fmtAmt(v: string): string {
  // amounts arrive as NUMERIC(30,18) strings — show the number, not the padding
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : v
}
function shortDid(did: string | null): string {
  if (!did) return '—'
  return did.length > 30 ? `${did.slice(0, 27)}…` : did
}
function fmtWhen(iso: string | null): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(appLocale()) } catch { return iso }
}

onMounted(() => {
  void load()
  // a parked ask has a 30-minute fuse — keep the queue honest while the tab is open
  timer = window.setInterval(() => { void load() }, 20000)
})
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <div class="spa-root" data-tour="spend-approvals-panel">
    <div class="spa-head">
      <div>
        <div class="spa-title">{{ t('agentAccess.approvals.title', 'Spend approvals') }}</div>
        <p class="spa-sub">
          {{ t('agentAccess.approvals.sub',
               'Spends above an agent\'s approval threshold park here instead of failing outright. Approving arms a single-use authorization for 15 minutes; the agent\'s retry of the exact same spend consumes it. Unanswered asks expire in 30 minutes, which is a deny.') }}
        </p>
      </div>
      <div class="spa-controls">
        <button :class="['spa-chip', { 'spa-chip--on': onlyPending }]"
                @click="onlyPending = true; load()">
          {{ t('agentAccess.approvals.pendingOnly', 'Pending') }}
        </button>
        <button :class="['spa-chip', { 'spa-chip--on': !onlyPending }]"
                @click="onlyPending = false; load()">
          {{ t('agentAccess.approvals.all', 'All') }}
        </button>
        <button class="spa-chip" @click="load()" :disabled="loading">
          <Icon name="mdi:refresh" />
        </button>
      </div>
    </div>

    <div v-if="msg" :class="['spa-msg', msgOk ? 'spa-msg--ok' : 'spa-msg--err']">{{ msg }}</div>

    <div v-if="listRead === 'loading' && rows.length === 0" class="spa-empty">
      {{ t('agentAccess.approvals.loading', 'Loading the queue…') }}
    </div>
    <ReadFailedNotice v-else-if="listRead === 'failed'" :retry="load" />
    <div v-else-if="rows.length === 0" class="spa-empty">
      <Icon name="mdi:check-decagram" />
      {{ onlyPending
         ? t('agentAccess.approvals.emptyPending', 'Nothing waiting on you: no agent is asking to spend over its threshold.')
         : t('agentAccess.approvals.emptyAll', 'No spend approvals yet. They appear when an agent crosses its require-approval threshold.') }}
    </div>

    <div v-else class="spa-rows">
      <div v-for="r in rows" :key="r.id" class="spa-row">
        <div class="spa-row-main">
          <span :class="['spa-status', `spa-status--${r.status}`]">{{ r.status }}</span>
          <span class="spa-amount">{{ fmtAmt(r.amount) }}<span v-if="r.currency" class="spa-cur">&nbsp;{{ r.currency }}</span></span>
          <span class="spa-did" :title="r.agent_did">{{ shortDid(r.agent_did) }}</span>
          <span v-if="r.counterparty_did" class="spa-cpty" :title="r.counterparty_did">
            → {{ shortDid(r.counterparty_did) }}
          </span>
        </div>
        <div class="spa-row-meta">
          <span>{{ t('agentAccess.approvals.asked', 'asked') }} {{ fmtWhen(r.created_at) }}</span>
          <span v-if="r.status === 'pending' || r.status === 'approved'">
            · {{ t('agentAccess.approvals.expires', 'expires') }} {{ fmtWhen(r.expires_at) }}</span>
          <span v-if="r.consumed_at">
            · {{ t('agentAccess.approvals.consumed', 'consumed') }} {{ fmtWhen(r.consumed_at) }}</span>
        </div>
        <div v-if="r.status === 'pending'" class="spa-actions">
          <button class="spa-btn spa-btn--ok" :disabled="busy === r.id"
                  data-tour="spend-approval-approve" @click="decide(r.id, 'approve')">
            <Icon name="mdi:check" /> {{ t('agentAccess.approvals.approve', 'Approve') }}
          </button>
          <button class="spa-btn spa-btn--no" :disabled="busy === r.id" @click="decide(r.id, 'deny')">
            <Icon name="mdi:close" /> {{ t('agentAccess.approvals.deny', 'Deny') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.spa-root { display: flex; flex-direction: column; gap: 14px; }
.spa-head { display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.spa-title { font-size: 14px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--cmd-text, #d7e3ef); }
.spa-sub { margin: 6px 0 0; font-size: 11.5px; line-height: 1.55; max-width: 640px;
  color: var(--cmd-text-muted, #758296); }
.spa-controls { display: flex; gap: 6px; align-items: flex-start; }
.spa-chip { padding: 5px 12px; font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
  background: rgba(var(--nc-primary-rgb, 64 156 255) / 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb, 64 156 255) / 0.22);
  color: var(--cmd-text-muted, #758296); border-radius: 6px; cursor: pointer; }
.spa-chip--on { color: var(--nc-primary, #58a6ff);
  border-color: rgba(var(--nc-primary-rgb, 64 156 255) / 0.6);
  background: rgba(var(--nc-primary-rgb, 64 156 255) / 0.12); }
.spa-msg { font-size: 11.5px; padding: 8px 12px; border-radius: 6px; }
.spa-msg--ok { color: #7ce38b; background: rgba(80 220 130 / 0.08); border: 1px solid rgba(80 220 130 / 0.25); }
.spa-msg--err { color: #ff8a80; background: rgba(255 90 80 / 0.08); border: 1px solid rgba(255 90 80 / 0.25); }
.spa-empty { display: flex; align-items: center; gap: 8px; padding: 22px 14px; font-size: 12px;
  color: var(--cmd-text-muted, #758296); border: 1px dashed rgba(120 140 160 / 0.25); border-radius: 8px; }
.spa-rows { display: flex; flex-direction: column; gap: 8px; }
.spa-row { padding: 11px 13px; border: 1px solid rgba(120 140 160 / 0.18); border-radius: 8px;
  background: rgba(10 16 22 / 0.35); display: flex; flex-direction: column; gap: 6px; }
.spa-row-main { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.spa-status { font-size: 9.5px; letter-spacing: 0.1em; text-transform: uppercase; padding: 2px 8px;
  border-radius: 999px; border: 1px solid currentColor; }
.spa-status--pending  { color: #ffd479; }
.spa-status--approved { color: #7ce38b; }
.spa-status--consumed { color: #58a6ff; }
.spa-status--denied, .spa-status--expired { color: #ff8a80; }
.spa-amount { font-size: 15px; font-weight: 700; color: var(--cmd-text, #d7e3ef); }
.spa-cur { font-size: 10.5px; font-weight: 600; color: var(--cmd-text-muted, #758296); }
.spa-did, .spa-cpty { font-family: var(--font-mono, monospace); font-size: 10.5px;
  color: var(--cmd-text-muted, #758296); }
.spa-row-meta { font-size: 10px; color: var(--cmd-text-muted, #758296); }
.spa-actions { display: flex; gap: 8px; margin-top: 2px; }
.spa-btn { display: inline-flex; align-items: center; gap: 5px; padding: 6px 14px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.05em; border-radius: 6px; cursor: pointer;
  background: transparent; }
.spa-btn:disabled { opacity: 0.5; cursor: default; }
.spa-btn--ok { color: #7ce38b; border: 1px solid rgba(80 220 130 / 0.45); }
.spa-btn--ok:hover:not(:disabled) { background: rgba(80 220 130 / 0.1); }
.spa-btn--no { color: #ff8a80; border: 1px solid rgba(255 90 80 / 0.4); }
.spa-btn--no:hover:not(:disabled) { background: rgba(255 90 80 / 0.08); }
</style>
