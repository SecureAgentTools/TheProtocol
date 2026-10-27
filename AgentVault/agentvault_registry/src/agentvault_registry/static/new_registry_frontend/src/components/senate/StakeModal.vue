<template>
  <Teleport to="body">
    <div v-if="show" class="tp-overlay" @click.self="$emit('update:show', false)">
      <div ref="panelRef" class="tp-modal tp-modal--lg" role="dialog" aria-modal="true" :aria-labelledby="titleId">

        <div class="tp-modal-header">
          <span :id="titleId" class="tp-modal-title"><Icon name="mdi:lock" /> Lock {{ localCurrency }}</span>
          <button type="button" class="tp-modal-close" aria-label="Close" @click="$emit('update:show', false)">✕</button>
        </div>

        <div class="tp-modal-body">

          <!-- Balance banner -->
          <div class="sn-balance-bar">
            <span class="sn-balance-bar__label">Available Balance</span>
            <span class="sn-balance-bar__value">{{ formatNum(tegBalance) }} {{ localCurrency }}</span>
          </div>

          <!-- Amount -->
          <div class="tp-field">
            <label class="tp-label">Amount to Lock <span style="color:#ef4444">*</span></label>
            <div class="sn-amount-wrap">
              <input
                v-model="amount"
                type="number"
                min="10"
                step="any"
                class="tp-input"
                :placeholder="`Minimum 10 ${localCurrency}`"
              />
              <button class="sn-max-btn" @click="setMax">MAX</button>
            </div>
            <div v-if="amountError" class="tp-hint" style="color:rgb(239,68,68)">{{ amountError }}</div>
          </div>

          <!-- Lock period tiles -->
          <div class="tp-field">
            <label class="tp-label">Lock Period</label>
            <div class="tp-lock-grid">
              <div
                v-for="tier in tiers"
                :key="tier.lockPeriod"
                :class="['tp-lock-tile', selectedPeriod === tier.lockPeriod && 'tp-lock-tile--active']"
                @click="selectedPeriod = tier.lockPeriod"
              >
                <div class="tp-lock-tile__days">{{ tier.lockPeriod === 0 ? 'Flexible' : tier.lockPeriod + 'd' }}</div>
                <div v-if="ratesOn !== false" class="tp-lock-tile__apy">{{ tier.apy }}%</div>
                <div v-if="tier.lockPeriod === 0" class="tp-lock-tile__flex">Anytime</div>
                <div v-else-if="ratesOn !== false" class="tp-lock-tile__bonus">+{{ tier.lockPremium }}% bonus</div>
              </div>
            </div>
          </div>

          <!-- Estimate -->
          <div v-if="estimate && ratesOn !== false" class="tp-banner tp-banner--info" style="margin-bottom:0">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap">
              <div>
                <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;opacity:0.7;margin-bottom:0.25rem">Estimated Return ({{ estimate.period === 0 ? 'per year' : estimate.period + ' days' }})</div>
                <div style="font-size:1.1rem;font-weight:700">+{{ estimate.amount }} {{ localCurrency }}</div>
              </div>
              <div style="text-align:right">
                <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;opacity:0.7;margin-bottom:0.25rem">Payout rate</div>
                <div style="font-size:1rem;font-weight:700">{{ estimate.apy }}%</div>
              </div>
            </div>
          </div>

        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('update:show', false)">Cancel</button>
          <button
            class="tp-btn tp-btn--primary"
            :disabled="!canStake || loading"
            @click="handleStake"
          >
            <span v-if="loading"><span class="tp-spinner"></span> Locking…</span>
            <span v-else><Icon name="mdi:lock" /> Lock {{ amount ? formatNum(amount) : '' }} {{ localCurrency }}</span>
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
import { ref, computed, watch } from 'vue'
import { useCurrency } from '@/composables/useCurrency'

const props = defineProps<{
  show: boolean
  tegBalance: string | number
  tiers: Array<{
    lockPeriod: number
    apy: number
    lockPremium: number
    minAmount: string
    label: string
    description: string
  }>
  loading: boolean
  /** §BAFIN: false where payouts on locked units are switched off — no rate, bonus or return estimate is shown */
  ratesOn?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'stake', amount: string, lockPeriod: number): void
}>()

// §COCKPITDESK (2026-10-15): a dialog says it is one (role, aria-modal, its title as its name) and Escape closes it
// wherever the focus is, never while it submits (agentvault2-5b's scoped run of 99 on V0616: Create a proposal
// opened as no dialog at all)
const panelRef = ref<HTMLElement | null>(null)
const titleId = `sn-dlg-${Math.random().toString(36).slice(2, 10)}`
useEscapeClose(() => !!props.show, () => emit('update:show', false), () => !props.loading, () => panelRef.value)

// FX multi-currency: lock amounts are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

const amount      = ref('')
const selectedPeriod = ref(0)

const amountError = computed(() => {
  const n = parseFloat(amount.value)
  if (!amount.value) return ''
  if (isNaN(n) || n < 10) return `The smallest lock is 10 ${localCurrency.value}`
  if (n > parseFloat(String(props.tegBalance))) return 'Insufficient balance'
  return ''
})

const canStake = computed(() => {
  const n = parseFloat(amount.value)
  return n >= 10 && n <= parseFloat(String(props.tegBalance)) && !amountError.value
})

const selectedTier = computed(() =>
  props.tiers.find(t => t.lockPeriod === selectedPeriod.value)
)

const estimate = computed(() => {
  const n = parseFloat(amount.value)
  const tier = selectedTier.value
  if (!n || !tier || isNaN(n)) return null
  const period = tier.lockPeriod === 0 ? 365 : tier.lockPeriod
  const earned = (n * (tier.apy / 100) * (period / 365)).toFixed(2)
  return { amount: earned, apy: tier.apy, period: tier.lockPeriod }
})

function setMax() {
  amount.value = String(parseFloat(String(props.tegBalance)).toFixed(2))
}

function formatNum(v: string | number) {
  const n = parseFloat(String(v))
  if (isNaN(n)) return '0.00'
  return n.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function handleStake() {
  if (!canStake.value || props.loading) return
  emit('stake', amount.value, selectedPeriod.value)
}

// Reset on open
watch(() => props.show, (v) => {
  if (v) { amount.value = ''; selectedPeriod.value = 0 }
})
</script>

<style scoped>
.sn-balance-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 8px; padding: 0.65rem 1rem;
  margin-bottom: 1.25rem;
}
.sn-balance-bar__label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em; color: #7b91b2;
}
.sn-balance-bar__value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.95rem; font-weight: 700; color: rgb(0,210,210);
}
.sn-amount-wrap { position: relative; }
.sn-max-btn {
  position: absolute; right: 0.5rem; top: 50%; transform: translateY(-50%);
  font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 700;
  padding: 0.2rem 0.55rem; border-radius: 4px;
  background: rgba(var(--nc-primary-rgb),0.12); color: rgb(0,210,210);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25); cursor: pointer;
  transition: all 0.15s;
}
.sn-max-btn:hover { background: rgba(var(--nc-primary-rgb),0.22); }
</style>
