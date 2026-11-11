<template>
  <!-- V0657 (a), items 5, 6 and 7: the three rulings, the split for a Guild order, the ruler's reason, and what the
       ruling does BEFORE the click (the server's preview, from the rules the ruling applies): one confirm. -->
  <div class="dsp-rule" data-testid="ruling-panel">
    <fieldset class="dsp-rule__choices">
      <legend class="dsp-rule__legend">{{ t('disputesView.v2.ruling', 'Ruling') }}</legend>
      <label v-for="opt in options" :key="opt.value" class="dsp-rule__choice" :data-ruling="opt.value">
        <input v-model="ruling" type="radio" name="dsp-ruling" :value="opt.value" />
        <span>{{ opt.label }}</span>
      </label>
    </fieldset>

    <div v-if="isGuild" class="dsp-rule__split">
      <label class="dsp-rule__check">
        <input v-model="splitOn" type="checkbox" data-testid="ruling-split-on" />
        <span>{{ t('disputesView.v2.splitOn', 'Set the split of the order\'s escrow myself') }}</span>
      </label>
      <div v-if="splitOn" class="dsp-rule__split-row">
        <input v-model.number="workerPct" type="range" min="0" max="100" step="5" data-testid="ruling-split" />
        <span class="dsp-rule__split-val">{{ tp('disputesView.v2.splitWorker', 'Worker {pct}%, poster {rest}%', { pct: workerPct, rest: 100 - workerPct }) }}</span>
      </div>
    </div>

    <label class="dsp-rule__note">
      <span>{{ t('disputesView.v2.reason', 'Your reason (kept on the record; both parties read it)') }}</span>
      <textarea v-model="note" rows="4" data-testid="ruling-note" />
    </label>

    <section class="dsp-rule__preview" data-testid="ruling-preview" :data-state="state">
      <h4 class="dsp-rule__h">{{ t('disputesView.v2.preview', 'What this ruling does') }}</h4>
      <p v-if="state === 'idle'" class="dsp-rule__muted">{{ t('disputesView.v2.pick', 'Pick a ruling to see what it does.') }}</p>
      <p v-else-if="state === 'loading'" class="dsp-rule__muted">{{ t('disputesView.v2.previewLoading', 'Reading what it would do…') }}</p>
      <p v-else-if="state === 'failed'" class="dsp-rule__err" data-testid="ruling-preview-failed">{{ error }}</p>
      <template v-else-if="preview">
        <ul class="dsp-rule__list" data-testid="ruling-money">
          <li v-for="(line, i) in moneyLines" :key="'m' + i">{{ line }}</li>
        </ul>
        <ul class="dsp-rule__list" data-testid="ruling-reputation">
          <li v-if="!preview.reputation.length">{{ t('disputesView.v2.noReputation', 'No reputation changes.') }}</li>
          <li v-for="r in preview.reputation" :key="r.did" :title="r.did">
            {{ tp('disputesView.v2.repLine', '{who}: {change} reputation ({why})', { who: r.name || shortDid(r.did), change: signed(r.change), why: r.why }) }}
          </li>
        </ul>
        <p class="dsp-rule__enf" data-testid="ruling-enforcement">{{ enforcementLine }}</p>
      </template>
    </section>

    <footer class="dsp-rule__foot">
      <button type="button" class="tp-btn tp-btn--ghost" @click="emit('cancel')">{{ t('disputesView.rulingModal.cancel', 'Cancel') }}</button>
      <button type="button" class="tp-btn tp-btn--success" :disabled="!canConfirm" data-testid="ruling-confirm" @click="confirm">
        {{ busy ? t('disputesView.v2.rulingBusy', 'Ruling…') : t('disputesView.v2.confirm', 'Rule') }}
      </button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { disputesApi, type Dispute, type RulingPreview, type RulingValue } from '@/services/api/disputes'
import { useDisputesStore } from '@/stores/disputes'

const props = defineProps<{ dispute: Dispute }>()
const emit = defineEmits<{ (e: 'done', result: any): void; (e: 'cancel'): void }>()
const { t, tp } = useI18n()

const ruling = ref<RulingValue | ''>('')
const note = ref('')
const splitOn = ref(false)
const workerPct = ref(100)
const preview = ref<RulingPreview | null>(null)
const state = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
const error = ref('')
const busy = ref(false)
let seq = 0

const isGuild = computed(() => !!props.dispute.guild_order_id)
const options = computed(() => [
  { value: 'IN_FAVOR_OF_COMPLAINANT' as RulingValue,
    label: tp('disputesView.v2.forComplainant', 'In favour of the complainant ({who})', { who: who('complainant') }) },
  { value: 'IN_FAVOR_OF_DEFENDANT' as RulingValue,
    label: tp('disputesView.v2.forDefendant', 'In favour of the defendant ({who})', { who: who('defendant') }) },
  { value: 'DISMISSED' as RulingValue, label: t('disputesView.v2.dismiss', 'Dismiss the complaint') },
])
const share = computed<number | null>(() => (isGuild.value && splitOn.value ? workerPct.value / 100 : null))
const canConfirm = computed(() => !!ruling.value && note.value.trim().length > 0 && state.value === 'ready' && !busy.value)

function who(side: 'complainant' | 'defendant'): string {
  const d: any = props.dispute
  const name = side === 'complainant' ? d.claimant_name : d.respondent_name
  return name || shortDid(side === 'complainant' ? d.claimant_did : d.respondent_did)
}
function shortDid(did?: string | null): string {
  if (!did) return '?'
  const core = did.replace(/^did:[a-z0-9]+:/i, '')
  return core.length > 16 ? core.slice(0, 6) + '…' + core.slice(-6) : core
}
function signed(n: number): string { return n > 0 ? `+${n}` : String(n) }
function amt(s: any): string {
  const n = Number(s)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : String(s ?? '')
}

const moneyLines = computed<string[]>(() => {
  const m: any = preview.value?.money || {}
  const cur = m.currency ? ` ${m.currency}` : ''
  if (m.kind === 'guild_split') {
    if (!m.moves) return [m.why || t('disputesView.v2.noMoney', 'This ruling moves no money.')]
    const lines = [tp('disputesView.v2.guildSplit', 'The order\'s escrow ({escrow}): the worker gets {worker}, the poster gets {poster}. No fee.',
      { escrow: amt(m.escrow) + cur, worker: amt(m.worker_gets) + cur, poster: amt(m.poster_gets) + cur })]
    if (m.stake) lines.push(tp('disputesView.v2.collateral', 'The worker\'s collateral ({amount}) goes to {to}.', { amount: amt(m.stake.amount) + cur, to: m.stake.goes_to }))
    if (!isGuildHandedIn(m)) lines.push(t('disputesView.v2.nothingHandedIn', 'Nothing was handed in.'))
    return lines
  }
  if (m.kind === 'contract_split') {
    if (!m.moves) return [t('disputesView.v2.contractSettled', 'The contract is not disputed any more: this ruling moves no money.')]
    return [tp('disputesView.v2.contractSplit', 'The contract\'s unreleased escrow ({rem}): the provider gets {p}, the client gets {c}.',
      { rem: amt(m.remainder), p: amt(m.provider_gets), c: amt(m.client_gets) })]
  }
  if (m.kind === 'wallet_compensation') {
    if (!m.moves) return [m.why || t('disputesView.v2.noMoney', 'This ruling moves no money.')]
    return [tp('disputesView.v2.wallet', '{amount} moves from the defendant\'s wallet to the complainant (the amount claimed when it was filed).', { amount: amt(m.amount) })]
  }
  return [m.why || t('disputesView.v2.noMoney', 'This ruling moves no money.')]
})
function isGuildHandedIn(m: any): boolean { return m.handed_in !== false }

const enforcementLine = computed(() => {
  const e: any = preview.value?.enforcement
  if (!e) return t('disputesView.v2.noEnforcement', 'No enforcement step.')
  const parts = [tp('disputesView.v2.enfHead', 'Enforcement on {who}: offense {n}, level {level}, {action}', {
    who: e.agent_name || shortDid(e.agent_did), n: (e.offense_count_before ?? 0) + 1, level: e.escalation_level, action: e.action })]
  if (e.slash_amount) parts.push(tp('disputesView.v2.enfSlash', 'a slash of {amount}', { amount: amt(e.slash_amount) }))
  if (e.pause_days) parts.push(tp('disputesView.v2.enfPause', 'payouts paused {days} days', { days: e.pause_days }))
  if (e.suspends) parts.push(t('disputesView.v2.enfSuspends', 'the agent is suspended'))
  if (e.admin_review_required) parts.push(t('disputesView.v2.enfReview', 'an administrator approves it first'))
  return parts.join('; ') + '.'
})

async function loadPreview() {
  if (!ruling.value) { state.value = 'idle'; preview.value = null; return }
  const mine = ++seq
  state.value = 'loading'
  try {
    const p = await disputesApi.previewRuling(String(props.dispute.id), ruling.value as RulingValue, share.value)
    if (mine !== seq) return
    preview.value = p
    state.value = 'ready'
  } catch (e: any) {
    if (mine !== seq) return
    preview.value = null
    error.value = e?.response?.data?.detail || e?.message || t('disputesView.v2.previewFailed', 'The preview could not be read; nothing was ruled.')
    state.value = 'failed'
  }
}
watch([ruling, share], () => { void loadPreview() })

async function confirm() {
  if (!canConfirm.value) return
  busy.value = true
  try {
    const result = await useDisputesStore().updateRuling(String(props.dispute.id), ruling.value as RulingValue, note.value.trim(), share.value)
    emit('done', result)
  } catch {
    /* the store said why */
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.dsp-rule { display: flex; flex-direction: column; gap: 14px; }
.dsp-rule__choices { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.dsp-rule__legend { font-size: 12px; opacity: .7; margin-bottom: 4px; }
.dsp-rule__choice, .dsp-rule__check { display: flex; gap: 8px; align-items: center; cursor: pointer; }
.dsp-rule__split { display: flex; flex-direction: column; gap: 4px; }
.dsp-rule__split-row { display: flex; gap: 10px; align-items: center; margin-top: 6px; }
.dsp-rule__split-val { font-variant-numeric: tabular-nums; min-width: 12ch; }
.dsp-rule__note { display: flex; flex-direction: column; gap: 6px; }
.dsp-rule__note textarea { width: 100%; min-height: 96px; }
.dsp-rule__preview { border: 1px solid var(--drc-line, rgba(255, 255, 255, .12)); border-radius: 8px; padding: 10px 12px; }
.dsp-rule__h { margin: 0 0 6px; font-size: 13px; }
.dsp-rule__list { margin: 0 0 6px; padding-left: 18px; }
.dsp-rule__muted { opacity: .7; margin: 0; }
.dsp-rule__err { color: var(--drc-red, #f87171); margin: 0; }
.dsp-rule__enf { margin: 0; }
.dsp-rule__foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
