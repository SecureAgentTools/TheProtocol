<!-- COMMONS ADMIN (§MEMBERSHIP phase C, 2026-10-02) — admin_treasury's controls for a season: open one (its budget is
     read from the fee collector now and published with it), close it (the tally is fixed), pay the awards (through the
     reward funding waterfall: the fee collector first, then the treasury; a second run pays only what is still unpaid),
     or cancel one nothing was paid from. Every press asks once more before it acts; the server re-checks all of it. -->
<template>
  <section v-if="mode" class="cma" data-testid="commons-admin" :data-mode="mode">
    <h4 class="cma-title"><Icon name="mdi:shield-account" /> {{ t('commons.admin.title', 'Season administration') }}</h4>

    <!-- open the next season -->
    <form v-if="mode === 'open'" class="cma-open" @submit.prevent="ask('open')">
      <p class="cma-muted">{{ t('commons.admin.openHint', "The budget is read from the fee collector's balance the moment you open the season, plus the seed, and published with it. It cannot change afterwards.") }}</p>
      <div class="cma-grid">
        <label class="tp-field">
          <span class="tp-label">{{ t('commons.admin.seasonTitle', 'Title (optional)') }}</span>
          <input v-model="title" class="tp-input" maxlength="160" data-testid="commons-open-title" />
        </label>
        <label class="tp-field">
          <span class="tp-label">{{ t('commons.admin.days', 'Days open') }}</span>
          <input v-model.number="days" class="tp-input" type="number" min="1" max="120" step="1" inputmode="numeric" data-testid="commons-open-days" />
        </label>
        <label class="tp-field">
          <span class="tp-label">{{ t('commons.admin.feePct', 'Part of the fee collector (%)') }}</span>
          <input v-model="feePct" class="tp-input" type="number" min="0" max="100" step="any" inputmode="decimal"
                 :placeholder="t('commons.admin.feePctDefault', 'registry default')" data-testid="commons-open-pct" />
        </label>
        <label class="tp-field">
          <span class="tp-label">{{ t('commons.admin.seed', 'Seed from the treasury (optional)') }}</span>
          <input v-model="seed" class="tp-input" type="number" min="0" step="any" inputmode="decimal" data-testid="commons-open-seed" />
        </label>
      </div>
      <p v-if="openProblem" class="cma-warn" role="status">{{ openProblem }}</p>
      <button v-if="pending !== 'open'" type="submit" class="tp-btn tp-btn--primary" :disabled="busy || !!openProblem" data-testid="commons-open">
        <Icon name="mdi:plus" /> {{ t('commons.admin.open', 'Open a season') }}
      </button>
    </form>

    <!-- a season that takes submissions and ballots, or whose window has ended -->
    <div v-else-if="mode === 'running'" class="cma-row">
      <p class="cma-muted">{{ t('commons.admin.closeHint', 'Closing fixes the tally from the ballots of those who are members at that moment. Submissions and ballots stop.') }}</p>
      <button v-if="!pending" type="button" class="tp-btn tp-btn--primary" :disabled="busy" data-testid="commons-close" @click="ask('close')">
        {{ t('commons.admin.close', 'Close the season') }}
      </button>
    </div>

    <!-- a closed season: pay what the tally awarded -->
    <div v-else-if="mode === 'closed'" class="cma-row">
      <p class="cma-muted" data-testid="commons-pay-summary">{{ tp('commons.admin.payHint', 'Unpaid awards: {n}, {total} {cur} in all. Paying draws on the fee collector first, then the treasury, and never creates new units. A failed payment is sent again by a run within 23 hours of its first attempt; after that it waits for a decision.',
        { n: unpaid.count, total: amount(unpaid.total), cur: season?.currency || '' }) }}</p>
      <button v-if="!pending" type="button" class="tp-btn tp-btn--primary" :disabled="busy || unpaid.count === 0" data-testid="commons-pay" @click="ask('pay')">
        <Icon name="mdi:cash-check" /> {{ t('commons.admin.pay', 'Pay the awards') }}
      </button>
    </div>

    <!-- cancel: only while nothing was paid (the server refuses a partly paid season) -->
    <div v-if="(mode === 'running' || (mode === 'closed' && !payStarted)) && pending !== 'cancel'" class="cma-row">
      <button v-if="!pending" type="button" class="tp-btn tp-btn--ghost" :disabled="busy" data-testid="commons-cancel" @click="ask('cancel')">
        {{ t('commons.admin.cancel', 'Cancel the season') }}
      </button>
    </div>
    <form v-if="pending === 'cancel'" class="cma-row" @submit.prevent="confirm">
      <input v-model="reason" class="tp-input" maxlength="240" :placeholder="t('commons.admin.cancelReason', 'Why (shown publicly)')" data-testid="commons-cancel-reason" />
    </form>

    <!-- the second press -->
    <div v-if="pending" class="cma-confirm" role="alertdialog" :aria-label="confirmText" data-testid="commons-admin-confirm">
      <span>{{ confirmText }}</span>
      <button type="button" class="tp-btn tp-btn--danger" :disabled="busy || (pending === 'cancel' && reason.trim().length < 5)"
              data-testid="commons-admin-confirm-yes" @click="confirm">{{ t('commons.admin.yes', 'Yes, do it') }}</button>
      <button type="button" class="tp-btn tp-btn--ghost" :disabled="busy" @click="pending = null">{{ t('common.cancel', 'Cancel') }}</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { fmt } from '@/services/cockpit/num'
import { paymentStarted, seasonPhase, type CommonsAdminAct, type SeasonDetail } from '@/services/commons/commons'

const props = withDefaults(defineProps<{ season: SeasonDetail | null; busy?: boolean }>(), { busy: false })
const emit = defineEmits<{ (e: 'act', act: CommonsAdminAct): void }>()
const { t, tp } = useI18n()

type Action = 'open' | 'close' | 'pay' | 'cancel'
const pending = ref<Action | null>(null)
const title = ref('')
const days = ref<number>(30)
const feePct = ref<string>('')
const seed = ref<string>('')
const reason = ref('')

/** What this box offers: opening (no season given), running (open or window ended), closed (pay), or nothing. */
const mode = computed<'open' | 'running' | 'closed' | null>(() => {
  if (!props.season) return 'open'
  const p = seasonPhase(props.season)
  if (p === 'open' || p === 'ended') return 'running'
  if (p === 'closed') return 'closed'
  return null
})
watch(() => props.season?.id, () => { pending.value = null; reason.value = '' })

function amount(v: unknown) { return fmt(v, 6) }
/** once any award was sent, the season is finished by paying or writing off, never cancelled (the server refuses) */
const payStarted = computed(() => paymentStarted(props.season?.submissions))

const unpaid = computed(() => {
  let count = 0
  let total = 0
  for (const s of props.season?.submissions || []) {
    const a = s.award
    if (a && (a.status === 'pending' || a.status === 'failed')) { count += 1; total += Number(a.amount) || 0 }
  }
  return { count, total }
})

const openProblem = computed(() => {
  const d = Number(days.value)
  if (!Number.isInteger(d) || d < 1 || d > 120) return t('commons.admin.daysRange', 'A season runs from 1 to 120 days.')
  if (feePct.value !== '' && (Number(feePct.value) < 0 || Number(feePct.value) > 100 || !Number.isFinite(Number(feePct.value)))) {
    return t('commons.admin.pctRange', 'The part of the fee collector is between 0 and 100 %.')
  }
  if (seed.value !== '' && !(Number(seed.value) >= 0)) return t('commons.admin.seedRange', 'The seed cannot be negative.')
  return ''
})

const confirmText = computed(() => ({
  open: t('commons.admin.confirmOpen', 'Open the season now? Its budget is fixed at this moment.'),
  close: t('commons.admin.confirmClose', 'Close the season now? Submissions and ballots stop and the tally is fixed.'),
  pay: t('commons.admin.confirmPay', 'Pay every unpaid award now?'),
  cancel: t('commons.admin.confirmCancel', 'Cancel the season? Nothing will be paid from it.'),
} as Record<Action, string>)[pending.value as Action] || '')

function ask(a: Action) { pending.value = a }

function confirm() {
  const a = pending.value
  if (!a || props.busy) return
  if (a === 'open') {
    if (openProblem.value) return
    emit('act', { kind: 'open', body: { title: title.value.trim(), durationDays: Number(days.value),
      seed: seed.value === '' ? undefined : String(seed.value), feeSharePercent: feePct.value === '' ? undefined : String(feePct.value) } })
  } else if (a === 'cancel') {
    if (reason.value.trim().length < 5) return
    emit('act', { kind: 'cancel', reason: reason.value.trim() })
  } else {
    emit('act', { kind: a })
  }
  pending.value = null
}
</script>

<style scoped>
.cma { border: 1px dashed rgba(251,191,36,0.4); border-radius: 10px; padding: 0.8rem 0.9rem; display: flex; flex-direction: column; gap: 0.55rem; }
.cma-title { display: inline-flex; align-items: center; gap: 0.35rem; margin: 0; font-size: 0.8rem; font-weight: 700; color: rgb(251,191,36); }
.cma-title :deep(svg) { width: 0.95rem; height: 0.95rem; }
.cma-muted { margin: 0; font-size: 0.76rem; opacity: 0.85; line-height: 1.45; }
.cma-warn { margin: 0; font-size: 0.76rem; color: rgb(251,191,36); }
.cma-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 0.5rem 0.75rem; }
.cma-grid .tp-input { font-size: 16px; }
.cma-open, .cma-row { display: flex; flex-direction: column; gap: 0.45rem; align-items: flex-start; }
.cma-row .tp-input { width: 100%; max-width: 32rem; font-size: 16px; }
.cma-confirm { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; font-size: 0.8rem; font-weight: 600; }
</style>
