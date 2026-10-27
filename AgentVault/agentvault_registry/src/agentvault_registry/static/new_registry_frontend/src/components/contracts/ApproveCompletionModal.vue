<template>
  <div class="tp-overlay" @click.self="$emit('close')">
    <div ref="dialogEl" role="dialog" aria-modal="true" aria-labelledby="ctr-approve-title" class="tp-modal">
      <div class="tp-modal-header">
        <span id="ctr-approve-title" class="tp-modal-title" style="color: rgb(251,191,36);"><Icon name="mdi:alert" /> Approve Completion — Contract {{ ctrLabel(contract) }}</span>
        <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('close')">×</button>
      </div>

      <div class="tp-modal-body">
        <div class="tp-banner tp-banner--danger">
          <strong>This action is irreversible.</strong>
          {{ tp('contractsView.modal.approveRelease', 'Approving releases the {amount} {ccy} held in escrow since the contract was accepted to the upgrader. There is no undo.', { amount: contract.payment_amount.toLocaleString(appLocale()), ccy: localCurrency }) }}
        </div>

        <!-- Payment details -->
        <div style="margin-bottom: 1rem;">
          <div class="tp-row">
            <span class="tp-row__label">Contract</span>
            <span class="tp-row__value tp-row__value--mono">{{ ctrLabel(contract) }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Upgrader</span>
            <span class="tp-row__value tp-row__value--mono" style="font-size:0.72rem;">{{ contract.upgrader_agent_did }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Payment</span>
            <span class="tp-row__value tp-row__value--big">{{ contract.payment_amount.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
          </div>
          <div v-if="contract.pr_url" class="tp-row">
            <span class="tp-row__label">Pull Request</span>
            <a :href="safeExternalUrl(contract.pr_url)" target="_blank" rel="noopener noreferrer" style="color: rgba(var(--nc-primary-rgb),0.8); font-size: 0.8rem; word-break: break-all; text-align: right; max-width: 70%;">
              {{ contract.pr_url }}
            </a>
          </div>
        </div>

        <!-- Typed confirmation -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-approve-confirm">
            Type the payment amount (<span style="color: rgb(0,210,210);">{{ contract.payment_amount }}</span>) to confirm
          </label>
          <input
            id="ctr-approve-confirm"
            v-model="confirmation"
            class="tp-input"
            :placeholder="`Type ${contract.payment_amount} to confirm`"
            :style="{ borderColor: confirmationOk ? 'rgba(34,197,94,0.5)' : '' }"
          />
        </div>

        <div v-if="error" class="tp-banner tp-banner--danger">{{ error }}</div>
      </div>

      <div class="tp-modal-footer">
        <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="loading">Cancel</button>
        <button
          class="tp-btn tp-btn--success"
          @click="submit"
          :disabled="loading || !confirmationOk"
        >
          <span v-if="loading" class="tp-spinner" />
          <span v-else>Execute Payment &amp; Complete</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed } from 'vue'
import { safeExternalUrl } from '@/utils/safeUrl'
import type { BackendContract } from '@/services/api/contracts'
import { ctrRef, ctrLabel } from '@/services/api/contracts'
import { useContractStore } from '@/stores/contracts'
import { useCurrency } from '@/composables/useCurrency'
import './tp-contract-modals.css'
import { computed as _dlgComputed, ref as _dlgRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ contract: BackendContract }>()
const emit = defineEmits<{ close: []; completed: [id: number] }>()
const { localCurrency } = useCurrency()

// §FESUITE — a modal is a dialog: named, Escape closes it, focus stays inside and returns to the opener.
const { t, tp } = useI18n()
const dialogEl = _dlgRef<HTMLElement | null>(null)
useFocusTrap(dialogEl, { activeWhen: _dlgComputed(() => true) })

const contractStore = useContractStore()
const confirmation = ref('')
const loading = ref(false)
const error = ref('')

const confirmationOk = computed(
  () => confirmation.value.trim() === String(props.contract.payment_amount)
)

async function submit() {
  if (!confirmationOk.value) return
  error.value = ''
  loading.value = true
  try {
    await contractStore.approveCompletion(ctrRef(props.contract))
    emit('completed', ctrRef(props.contract))
    emit('close')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'Approval failed'
  } finally {
    loading.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
