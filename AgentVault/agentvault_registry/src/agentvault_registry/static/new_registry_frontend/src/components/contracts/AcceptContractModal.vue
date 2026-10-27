<template>
  <div class="tp-overlay" @click.self="$emit('close')">
    <div ref="dialogEl" role="dialog" aria-modal="true" aria-labelledby="ctr-accept-title" class="tp-modal">
      <div class="tp-modal-header">
        <span id="ctr-accept-title" class="tp-modal-title">⬡ Accept Contract {{ ctrLabel(contract) }}</span>
        <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('close')">×</button>
      </div>

      <div class="tp-modal-body">
        <div class="tp-banner tp-banner--info">
          {{ tp('contractsView.modal.acceptEscrow', 'By accepting you commit to delivering the work described below. Accepting moves {amount} {ccy} from the client into escrow; it is paid to you when the client approves the work.', { amount: contract.payment_amount.toLocaleString(appLocale()), ccy: localCurrency }) }}
        </div>

        <!-- Contract summary -->
        <div style="margin-bottom: 1rem;">
          <div class="tp-row">
            <span class="tp-row__label">Contract</span>
            <span class="tp-row__value tp-row__value--mono">{{ ctrLabel(contract) }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Client</span>
            <span class="tp-row__value tp-row__value--mono" style="font-size:0.72rem;">{{ contract.client_agent_did }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Payment</span>
            <span class="tp-row__value tp-row__value--big">{{ contract.payment_amount.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Repository</span>
            <span class="tp-row__value" style="font-size:0.8rem; color: rgba(var(--nc-primary-rgb),0.8);">
              {{ contract.source_code_repo_url }}
            </span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Branch</span>
            <span class="tp-row__value tp-row__value--mono">{{ contract.source_code_branch }}</span>
          </div>
        </div>

        <!-- Scope -->
        <div class="tp-field">
          <label class="tp-label">Scope</label>
          <p style="color: #c8d6e8; font-size: 0.875rem; line-height: 1.55; background: rgba(255,255,255,0.03); border-radius: 6px; padding: 0.65rem 0.85rem; border: 1px solid rgba(var(--nc-primary-rgb),0.1);">
            {{ contract.scope_description }}
          </p>
        </div>

        <!-- Criteria -->
        <div v-if="criteriaEntries.length" class="tp-field">
          <label class="tp-label">Acceptance Criteria</label>
          <div v-for="([k, v]) in criteriaEntries" :key="k" class="tp-row">
            <span class="tp-row__label">{{ k }}</span>
            <span class="tp-row__value tp-row__value--mono">{{ v }}</span>
          </div>
        </div>

        <!-- Upgrader DID -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-accept-as">{{ t('contractsView.modal.acceptAs', 'Your acting agent accepts as the upgrader') }}</label>
          <input id="ctr-accept-as" class="tp-input" :value="upgraderDid" readonly />
          <p class="tp-hint">{{ t('contractsView.modal.acceptSwitch', 'The registry accepts only for the agent you act as. Switch agents in the header to accept as another.') }}</p>
        </div>

        <div v-if="error" class="tp-banner tp-banner--danger">{{ error }}</div>
      </div>

      <div class="tp-modal-footer">
        <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="loading">Cancel</button>
        <button class="tp-btn tp-btn--primary" @click="submit" :disabled="loading || !upgraderDid">
          <span v-if="loading" class="tp-spinner" />
          <span v-else>Accept Contract</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import { ref, computed } from 'vue'
import type { BackendContract } from '@/services/api/contracts'
import { ctrRef, ctrLabel } from '@/services/api/contracts'
import { useAuthStore } from '@/stores/auth'
import { useContractStore } from '@/stores/contracts'
import './tp-contract-modals.css'
import { useCurrency } from '@/composables/useCurrency'
import { computed as _dlgComputed, ref as _dlgRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ contract: BackendContract }>()
const emit = defineEmits<{ close: []; accepted: [id: number] }>()
const { localCurrency } = useCurrency()
// §FESUITE — a modal is a dialog: named, Escape closes it, focus stays inside and returns to the opener.
const { t, tp } = useI18n()
const dialogEl = _dlgRef<HTMLElement | null>(null)
useFocusTrap(dialogEl, { activeWhen: _dlgComputed(() => true) })

const authStore = useAuthStore()
const contractStore = useContractStore()

/* §FESUITE — the upgrader IS the acting agent (the rail refuses any other DID), so the field is the acting agent,
   read-only, and follows a switch made while the dialog is open. */
const upgraderDid = computed(() => authStore.activeAgent?.did || authStore.activeAgent?.agent_did || '')

const criteriaEntries = computed(() =>
  Object.entries(props.contract.acceptance_criteria || {})
)

const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await contractStore.acceptContract(ctrRef(props.contract), upgraderDid.value)
    emit('accepted', ctrRef(props.contract))
    emit('close')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'Failed to accept'
  } finally {
    loading.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
