<template>
  <div class="tp-overlay" @click.self="$emit('close')">
    <div ref="dialogEl" role="dialog" aria-modal="true" aria-labelledby="ctr-submit-title" class="tp-modal">
      <div class="tp-modal-header">
        <span id="ctr-submit-title" class="tp-modal-title">⬡ Submit Work — Contract {{ ctrLabel(contract) }}</span>
        <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('close')">×</button>
      </div>

      <div class="tp-modal-body">
        <div class="tp-banner tp-banner--info">
          Submitting transitions this contract to <strong>PENDING_MERGE</strong>. The client will
          review your pull request and approve or request changes.
        </div>

        <div class="tp-field">
          <label class="tp-label">Contract</label>
          <div class="tp-row">
            <span class="tp-row__label">ID</span>
            <span class="tp-row__value tp-row__value--mono">{{ ctrLabel(contract) }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Scope</span>
            <span class="tp-row__value" style="font-size:0.8rem; max-width: 70%;">{{ contract.scope_description }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Payment</span>
            <span class="tp-row__value tp-row__value--big">{{ contract.payment_amount.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
          </div>
        </div>

        <div class="tp-field">
          <label class="tp-label" for="ctr-submit-pr">Pull Request URL *</label>
          <input
            id="ctr-submit-pr"
            v-model="prUrl"
            class="tp-input"
            placeholder="https://github.com/org/repo/pull/42"
          />
          <p class="tp-hint">Must be publicly accessible. Client will review this URL.</p>
        </div>

        <div v-if="error" class="tp-banner tp-banner--danger">{{ error }}</div>
      </div>

      <div class="tp-modal-footer">
        <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="loading">Cancel</button>
        <button class="tp-btn tp-btn--primary" @click="submit" :disabled="loading || !prUrl.trim()">
          <span v-if="loading" class="tp-spinner" />
          <span v-else>Submit for Review</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import { ref } from 'vue'
import type { BackendContract } from '@/services/api/contracts'
import { ctrRef, ctrLabel } from '@/services/api/contracts'
import { useContractStore } from '@/stores/contracts'
import './tp-contract-modals.css'
import { useCurrency } from '@/composables/useCurrency'
import { computed as _dlgComputed, ref as _dlgRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ contract: BackendContract }>()
const emit = defineEmits<{ close: []; submitted: [id: number] }>()
const { localCurrency } = useCurrency()

// §FESUITE — a modal is a dialog: named, Escape closes it, focus stays inside and returns to the opener.
const { t } = useI18n()
const dialogEl = _dlgRef<HTMLElement | null>(null)
useFocusTrap(dialogEl, { activeWhen: _dlgComputed(() => true) })

const contractStore = useContractStore()
const prUrl = ref(props.contract.pr_url || '')
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await contractStore.submitWork(ctrRef(props.contract), prUrl.value.trim())
    emit('submitted', ctrRef(props.contract))
    emit('close')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'Submit failed'
  } finally {
    loading.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
