<template>
  <!-- V0657 (a): the correction rail. The corrected ruling, why (required: kept and told to both parties), and what the
       correction does before the click: the reputation changes undone, the enforcement reversed, what it does not undo
       (a slash's money, a suspension), the corrected ruling's own rule. A correction moves no money. -->
  <div class="dsp-cor" data-testid="correction-panel">
    <p class="dsp-cor__now">{{ tp('disputesView.v2.corNow', 'Ruled now: {words}', { words: words(dispute.ruling) }) }}</p>
    <fieldset class="dsp-cor__choices">
      <legend>{{ t('disputesView.v2.corTo', 'Correct it to') }}</legend>
      <label v-for="opt in options" :key="opt" class="dsp-cor__choice" :data-ruling="opt">
        <input v-model="ruling" type="radio" name="dsp-correct" :value="opt" />
        <span>{{ words(opt) }}</span>
      </label>
    </fieldset>
    <label class="dsp-cor__note">
      <span>{{ t('disputesView.v2.corWhy', 'Why the ruling is corrected (at least 10 characters)') }}</span>
      <textarea v-model="note" rows="4" data-testid="correction-note" />
    </label>
    <section class="dsp-cor__preview" data-testid="correction-preview" :data-state="state">
      <p v-if="state === 'loading'" class="dsp-cor__muted">{{ t('disputesView.v2.previewLoading', 'Reading what it would do…') }}</p>
      <p v-else-if="state === 'failed'" class="dsp-cor__err">{{ error }}</p>
      <template v-else-if="plan">
        <h4 class="dsp-cor__h">{{ t('disputesView.v2.corUndone', 'Undone') }}</h4>
        <ul class="dsp-cor__list">
          <li v-if="!plan.reverse_reputation.length && !plan.reverse_enforcement.length">{{ t('disputesView.v2.corNothing', 'Nothing to undo.') }}</li>
          <li v-for="r in plan.reverse_reputation" :key="'r' + r.did" :title="r.did">
            {{ tp('disputesView.v2.corRep', '{who}: {change} reputation given back', { who: name(r.did), change: signed(-r.change) }) }}
          </li>
          <li v-for="e in plan.reverse_enforcement" :key="e.action_id" :title="e.agent_did">
            {{ tp('disputesView.v2.corEnf', '{who}: the {action} is reversed (the offense leaves the count)', { who: name(e.agent_did), action: e.action }) }}
            <span v-if="e.not_returned" class="dsp-cor__warn"> {{ e.not_returned }}</span>
            <span v-if="e.suspension_stays" class="dsp-cor__warn"> {{ e.suspension_stays }}</span>
          </li>
        </ul>
        <h4 class="dsp-cor__h">{{ t('disputesView.v2.corApplied', 'Applied') }}</h4>
        <ul class="dsp-cor__list">
          <li v-if="!plan.apply_reputation.length">{{ t('disputesView.v2.noReputation', 'No reputation changes.') }}</li>
          <li v-for="r in plan.apply_reputation" :key="'a' + r.did" :title="r.did">
            {{ tp('disputesView.v2.repLine', '{who}: {change} reputation ({why})', { who: name(r.did), change: signed(r.change), why: r.why }) }}
          </li>
        </ul>
        <p class="dsp-cor__muted">{{ t('disputesView.v2.corNoMoney', 'A correction moves no money: the escrow settled when it settled.') }}</p>
      </template>
    </section>
    <footer class="dsp-cor__foot">
      <button type="button" class="tp-btn tp-btn--ghost" @click="emit('cancel')">{{ t('disputesView.rulingModal.cancel', 'Cancel') }}</button>
      <button type="button" class="tp-btn tp-btn--success" :disabled="!canConfirm" data-testid="correction-confirm" @click="confirm">
        {{ t('disputesView.v2.corConfirm', 'Correct the ruling') }}
      </button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { disputesApi, type CorrectionPreview, type Dispute, type RulingValue } from '@/services/api/disputes'

const props = defineProps<{ dispute: Dispute }>()
const emit = defineEmits<{ (e: 'done', result: any): void; (e: 'cancel'): void }>()
const { t, tp } = useI18n()
const uiStore = useUIStore()

const ALL: RulingValue[] = ['IN_FAVOR_OF_COMPLAINANT', 'IN_FAVOR_OF_DEFENDANT', 'DISMISSED']
const options = computed(() => ALL.filter((r) => r !== props.dispute.ruling))
const ruling = ref<RulingValue | ''>('')
const note = ref('')
const plan = ref<CorrectionPreview | null>(null)
const state = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle')
const error = ref('')
const busy = ref(false)
let seq = 0

const canConfirm = computed(() => !!ruling.value && note.value.trim().length >= 10 && state.value === 'ready' && !busy.value)

function words(r?: string | null): string {
  if (r === 'IN_FAVOR_OF_COMPLAINANT') return t('disputesView.v2.wordsComplainant', 'in favour of the complainant')
  if (r === 'IN_FAVOR_OF_DEFENDANT') return t('disputesView.v2.wordsDefendant', 'in favour of the defendant')
  if (r === 'DISMISSED') return t('disputesView.v2.wordsDismissed', 'dismissed')
  return r || '—'
}
function name(did: string): string {
  const p: any = props.dispute.parties
  if (p?.complainant?.did === did) return p.complainant.name || did
  if (p?.defendant?.did === did) return p.defendant.name || did
  return did
}
function signed(n: number): string { return n > 0 ? `+${n}` : String(n) }

watch(ruling, async (r) => {
  if (!r) return
  const mine = ++seq
  state.value = 'loading'
  try {
    const p = await disputesApi.previewCorrection(String(props.dispute.id), r as RulingValue)
    if (mine !== seq) return
    plan.value = p
    state.value = 'ready'
  } catch (e: any) {
    if (mine !== seq) return
    plan.value = null
    error.value = e?.response?.data?.detail || e?.message || t('disputesView.v2.previewFailed', 'The preview could not be read; nothing was ruled.')
    state.value = 'failed'
  }
})

async function confirm() {
  if (!canConfirm.value) return
  busy.value = true
  try {
    const result = await disputesApi.correctRuling(String(props.dispute.id), ruling.value as RulingValue, note.value.trim())
    uiStore.showSuccess(t('disputesView.v2.corDone', 'Ruling corrected'), words(ruling.value))
    emit('done', result)
  } catch (e: any) {
    uiStore.showError(t('disputesView.v2.corFailed', 'The ruling was not corrected'), e?.response?.data?.detail || e?.message || '')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.dsp-cor { display: flex; flex-direction: column; gap: 12px; }
.dsp-cor__choices { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.dsp-cor__choice { display: flex; gap: 8px; align-items: center; cursor: pointer; }
.dsp-cor__note { display: flex; flex-direction: column; gap: 6px; }
.dsp-cor__note textarea { width: 100%; min-height: 90px; }
.dsp-cor__preview { border: 1px solid var(--drc-line, rgba(255, 255, 255, .12)); border-radius: 8px; padding: 10px 12px; }
.dsp-cor__h { margin: 6px 0 4px; font-size: 13px; }
.dsp-cor__list { margin: 0; padding-left: 18px; }
.dsp-cor__muted { opacity: .7; margin: 6px 0 0; }
.dsp-cor__warn { color: var(--drc-amber, #fbbf24); }
.dsp-cor__err { color: var(--drc-red, #f87171); }
.dsp-cor__foot { display: flex; justify-content: flex-end; gap: 8px; }
.dsp-cor__now { margin: 0; }
</style>
