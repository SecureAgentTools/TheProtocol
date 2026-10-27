<template>
  <Teleport to="body">
    <div v-if="show && position" class="tp-overlay" @click.self="$emit('update:show', false)">
      <div ref="panelRef" class="tp-modal tp-modal--sm" role="dialog" aria-modal="true" :aria-labelledby="titleId">

        <div class="tp-modal-header">
          <span :id="titleId" class="tp-modal-title"><Icon name="mdi:lock-open" /> Unlock Position</span>
          <button type="button" class="tp-modal-close" aria-label="Close" @click="$emit('update:show', false)">✕</button>
        </div>

        <div class="tp-modal-body">

          <!-- Position summary -->
          <div class="sn-unstake-card">
            <div class="tp-row">
              <span class="tp-row__label">Amount</span>
              <span class="tp-row__value tp-row__value--big">{{ formatNum(position.amount) }} {{ localCurrency }}</span>
            </div>
            <div class="tp-row">
              <span class="tp-row__label">Type</span>
              <span class="tp-row__value">{{ position.lockPeriod === 0 ? 'Flexible' : position.lockPeriod + ' day lock' }}</span>
            </div>
            <div v-if="ratesOn !== false" class="tp-row">
              <span class="tp-row__label">Payout rate</span>
              <span class="tp-row__value tp-row__value--green">{{ position.apy }}%</span>
            </div>
            <div v-if="ratesOn !== false" class="tp-row">
              <span class="tp-row__label">Payouts Received</span>
              <span class="tp-row__value tp-row__value--green">+{{ formatNum(rewards) }} {{ localCurrency }}</span>
            </div>
            <div class="tp-row" style="border-top:1px solid rgba(var(--nc-primary-rgb),0.12);padding-top:0.6rem;margin-top:0.3rem">
              <span class="tp-row__label">You Receive</span>
              <span class="tp-row__value" style="font-family:'IBM Plex Mono',monospace;font-size:1.05rem;font-weight:700;color:#e2e8f0">
                {{ formatNum(total) }} {{ localCurrency }}
              </span>
            </div>
          </div>

          <div class="tp-banner tp-banner--warn" style="margin-bottom:0">
            <Icon name="mdi:alert" /> Unlocking removes this position and its vote power permanently.
          </div>

        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('update:show', false)">Cancel</button>
          <button class="tp-btn tp-btn--primary" :disabled="loading" @click="$emit('confirm')">
            <span v-if="loading"><span class="tp-spinner"></span> Unlocking…</span>
            <span v-else>Confirm Unlock</span>
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { computed, ref } from 'vue'
import { useCurrency } from '@/composables/useCurrency'

const props = defineProps<{
  show: boolean
  loading: boolean
  position: {
    id: string
    amount: string
    lockPeriod: number
    apy: number
    rewards?: { earned?: string; available?: string } | string
  } | null
  /** §BAFIN: false where payouts on locked units are switched off — no rate and no payouts received are shown */
  ratesOn?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'confirm'): void
}>()

// §COCKPITDESK (2026-10-15): a dialog says it is one (role, aria-modal, its title as its name) and Escape closes it
// wherever the focus is, never while it submits (agentvault2-5b's scoped run of 99 on V0616: Create a proposal
// opened as no dialog at all)
const panelRef = ref<HTMLElement | null>(null)
const titleId = `sn-dlg-${Math.random().toString(36).slice(2, 10)}`
useEscapeClose(() => !!(props.show && props.position), () => emit('update:show', false), () => !props.loading, () => panelRef.value)

// FX multi-currency: unlock amounts are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

const rewards = computed(() => {
  if (!props.position) return '0'
  const r = props.position.rewards
  if (typeof r === 'string') return r
  return r?.earned || r?.available || '0'
})

const total = computed(() => {
  if (!props.position) return '0'
  return (parseFloat(props.position.amount) + parseFloat(rewards.value)).toFixed(2)
})

function formatNum(v: string | number) {
  const n = parseFloat(String(v))
  if (isNaN(n)) return '0.00'
  return n.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<style scoped>
.sn-unstake-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px; padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}
</style>
