<template>
  <div class="tp-overlay" @click.self="$emit('close')">
    <div ref="dialogEl" role="dialog" aria-modal="true" aria-labelledby="ctr-malpractice-title" class="tp-modal">
      <div class="tp-modal-header">
        <span id="ctr-malpractice-title" class="tp-modal-title" style="color: rgb(239,68,68);"><Icon name="mdi:alert" /> File Malpractice — Contract {{ ctrLabel(contract) }}</span>
        <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('close')">×</button>
      </div>

      <div class="tp-modal-body">
        <div class="tp-banner tp-banner--warn">
          This creates a DDR (Distributed Dispute Resolution) case. Both parties will be
          notified. False claims may affect your trust score.
        </div>

        <!-- Summary -->
        <div style="margin-bottom: 1rem;">
          <div class="tp-row">
            <span class="tp-row__label">Contract</span>
            <span class="tp-row__value tp-row__value--mono">{{ ctrLabel(contract) }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Your role</span>
            <span class="tp-row__value">{{ myRole }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Defendant</span>
            <span class="tp-row__value tp-row__value--mono" style="font-size:0.72rem;">{{ defendantDid }}</span>
          </div>
          <div class="tp-row">
            <span class="tp-row__label">Status</span>
            <span class="tp-row__value">{{ contract.status }}</span>
          </div>
        </div>

        <div class="tp-field">
          <label class="tp-label">Reason *</label>
          <textarea
            v-model="reason"
            class="tp-textarea"
            rows="4"
            placeholder="Describe the malpractice clearly. Include evidence if available."
            maxlength="2000"
          />
          <p class="tp-hint">{{ reason.length }}/2000</p>
        </div>

        <!-- Success state -->
        <div v-if="disputeId" class="tp-banner tp-banner--success">
          Dispute #{{ disputeId }} filed. Navigate to Disputes to track its status.
        </div>

        <div v-if="error" class="tp-banner tp-banner--danger">{{ error }}</div>
      </div>

      <div class="tp-modal-footer">
        <button v-if="!disputeId" class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="loading">Cancel</button>
        <button
          v-if="!disputeId"
          class="tp-btn tp-btn--danger"
          @click="submit"
          :disabled="loading || reason.trim().length < 10"
        >
          <span v-if="loading" class="tp-spinner" />
          <span v-else>File Dispute</span>
        </button>
        <button v-if="disputeId" class="tp-btn tp-btn--ghost" @click="$emit('close')">Close</button>
        <button
          v-if="disputeId"
          class="tp-btn tp-btn--primary"
          @click="goToDisputes"
        >
          View Disputes →
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import type { BackendContract } from '@/services/api/contracts'
import { ctrRef, ctrLabel } from '@/services/api/contracts'
import { useAuthStore } from '@/stores/auth'
import { useContractStore } from '@/stores/contracts'
import './tp-contract-modals.css'
import { computed as _dlgComputed, ref as _dlgRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ contract: BackendContract }>()
const emit = defineEmits<{ close: [] }>()

const authStore = useAuthStore()
const contractStore = useContractStore()
const router = useRouter()

// §FESUITE — a modal is a dialog: named, Escape closes it, focus stays inside and returns to the opener.
const { t } = useI18n()
const dialogEl = _dlgRef<HTMLElement | null>(null)
useFocusTrap(dialogEl, { activeWhen: _dlgComputed(() => true) })

const myDid = computed(
  () => authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
)

const myRole = computed(() => {
  if (props.contract.client_agent_did === myDid.value) return 'Client'
  if (props.contract.upgrader_agent_did === myDid.value) return 'Upgrader'
  return 'Observer'
})

const defendantDid = computed(() => {
  if (props.contract.client_agent_did === myDid.value) return props.contract.upgrader_agent_did || 'N/A'
  return props.contract.client_agent_did
})

const reason = ref('')
const loading = ref(false)
const error = ref('')
const disputeId = ref<number | null>(null)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const result = await contractStore.reportMalpractice(ctrRef(props.contract), reason.value.trim())
    disputeId.value = result.dispute_id
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'Failed to file dispute'
  } finally {
    loading.value = false
  }
}

function goToDisputes() {
  emit('close')
  // X3 fix (2026-05-06): pass new dispute_id via hash so /disputes can
  // auto-open the matching drawer.
  if (disputeId.value) {
    router.push({ path: '/disputes', hash: `#dispute-${disputeId.value}` })
  } else {
    router.push('/disputes')
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
