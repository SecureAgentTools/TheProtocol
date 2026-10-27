<template>
  <Teleport to="body">
    <div v-if="modelValue" class="tp-overlay" @click.self="close">
      <div class="tp-modal tp-modal--lg" role="dialog" aria-modal="true" aria-labelledby="fd-title">

        <!-- Header -->
        <div class="tp-modal-header">
          <span id="fd-title" class="tp-modal-title"><Icon name="mdi:lightning-bolt" /> File Dispute</span>
          <button type="button" class="tp-modal-close" aria-label="Close" @click="close"><span aria-hidden="true">✕</span></button>
        </div>

        <!-- Body -->
        <div class="tp-modal-body">

          <!-- Warning banner -->
          <div class="tp-banner tp-banner--warn">
            <Icon name="mdi:alert" /> Disputes are recorded on the immutable EventStore. File only legitimate grievances.
            False disputes may result in reputation penalties.
          </div>

          <!-- Complainant (read-only) -->
          <div class="tp-field">
            <label class="tp-label" for="fd-complainant">Complainant (You)</label>
            <input id="fd-complainant" class="tp-input tp-input--readonly" :value="complainantDisplay" readonly />
            <div class="tp-hint">Filing as active agent — {{ activeAgentDid }}</div>
          </div>

          <!-- Defendant DID -->
          <div class="tp-field">
            <label class="tp-label" for="fd-defendant">Defendant Agent DID <span style="color:#ef4444">*</span></label>
            <input
              id="fd-defendant"
              v-model="form.defendant_did"
              class="tp-input"
              :class="{ 'tp-input--error': errors.defendant_did }"
              placeholder="did:theprotocol:…"
              @blur="validateDid"
            />
            <div v-if="errors.defendant_did" class="tp-hint" style="color:#ef4444">{{ errors.defendant_did }}</div>
            <div v-else class="tp-hint">Full DID of the agent you are filing against</div>
          </div>

          <!-- Category -->
          <div class="tp-field">
            <label class="tp-label" for="fd-category">Category <span style="color:#ef4444">*</span></label>
            <select id="fd-category" v-model="form.category" class="tp-select">
              <option value="">Select a category...</option>
              <option value="contract_breach">Contract Breach</option>
              <option value="service_failure">Service Failure</option>
              <option value="payment_dispute">Payment Dispute</option>
              <option value="non_delivery">Non-Delivery</option>
              <option value="quality_dispute">Quality Dispute</option>
              <option value="other">Other</option>
            </select>
            <div v-if="errors.category" class="tp-hint" style="color:#ef4444">{{ errors.category }}</div>
          </div>

          <!-- Description -->
          <div class="tp-field">
            <label class="tp-label" for="fd-description">Description <span style="color:#ef4444">*</span></label>
            <textarea
              id="fd-description"
              v-model="form.description"
              class="tp-textarea"
              rows="4"
              placeholder="Describe the dispute clearly: what happened, when, and what resolution you seek..."
              style="min-height: 100px"
            ></textarea>
            <div v-if="errors.description" class="tp-hint" style="color:#ef4444">{{ errors.description }}</div>
            <div class="tp-hint">This becomes the first evidence entry on the dispute.</div>
          </div>

          <!-- Amount Disputed (optional) -->
          <div class="tp-field">
            <label class="tp-label" for="fd-amount">Amount Disputed ({{ localCurrency }}) <span class="fd-optional">— optional</span></label>
            <input
              id="fd-amount"
              v-model.number="form.amount_disputed"
              class="tp-input"
              type="number"
              min="0"
              step="1"
              placeholder="0"
            />
            <div class="tp-hint">
              If specified, the compensation engine will attempt to transfer this amount from defendant to you upon ruling in your favour.
            </div>
          </div>

          <!-- Summary row -->
          <div v-if="form.defendant_did && form.category && form.description" class="tp-banner tp-banner--info" style="margin-top:0.5rem; margin-bottom:0">
            <div class="tp-row" style="border:none; padding:0.2rem 0">
              <span class="tp-row__label">Against</span>
              <span class="tp-row__value tp-row__value--mono" style="font-size:0.73rem">{{ form.defendant_did }}</span>
            </div>
            <div class="tp-row" style="border:none; padding:0.2rem 0">
              <span class="tp-row__label">Category</span>
              <span class="tp-row__value">{{ categoryLabel }}</span>
            </div>
            <div v-if="form.amount_disputed" class="tp-row" style="border:none; padding:0.2rem 0">
              <span class="tp-row__label">Amount</span>
              <span class="tp-row__value tp-row__value--big">{{ form.amount_disputed.toLocaleString(appLocale()) }} {{ localCurrency }}</span>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="close" :disabled="submitting">Cancel</button>
          <button
            class="tp-btn tp-btn--danger"
            :disabled="!canSubmit || submitting"
            @click="submit"
          >
            <span v-if="submitting"><span class="tp-spinner"></span> Filing…</span>
            <span v-else><Icon name="mdi:lightning-bolt" /> File Dispute</span>
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useDisputesStore } from '@/stores/disputes'
import './tp-disputes-modals.css'
import { useCurrency } from '@/composables/useCurrency'
import { useEscapeClose } from '@/composables/useEscapeClose'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'filed'): void }>()

const authStore = useAuthStore()
const disputesStore = useDisputesStore()
const { localCurrency } = useCurrency()

const submitting = ref(false)
const form = ref({
  defendant_did: '',
  category: '',
  description: '',
  amount_disputed: undefined as number | undefined
})
const errors = ref({ defendant_did: '', category: '', description: '' })

const activeAgentDid = computed(() =>
  authStore.activeAgent?.did || authStore.activeAgent?.agent_did || 'No agent selected'
)
const complainantDisplay = computed(() => {
  const name = (authStore.activeAgent as any)?.name
  return name ? `${name}` : activeAgentDid.value
})

const categoryLabel = computed(() => {
  const map: Record<string, string> = {
    contract_breach: 'Contract Breach',
    service_failure: 'Service Failure',
    payment_dispute: 'Payment Dispute',
    non_delivery: 'Non-Delivery',
    quality_dispute: 'Quality Dispute',
    other: 'Other'
  }
  return map[form.value.category] || form.value.category
})

const canSubmit = computed(() =>
  !!form.value.defendant_did.trim() &&
  !!form.value.category &&
  !!form.value.description.trim() &&
  !errors.value.defendant_did
)

// Reset on open
watch(() => props.modelValue, (v) => {
  if (v) {
    form.value = { defendant_did: '', category: '', description: '', amount_disputed: undefined }
    errors.value = { defendant_did: '', category: '', description: '' }
  }
})

function validateDid() {
  const did = form.value.defendant_did.trim()
  if (!did) {
    errors.value.defendant_did = 'Defendant DID is required.'
    return false
  }
  if (!did.startsWith('did:')) {
    errors.value.defendant_did = 'Must be a valid DID (starts with "did:").'
    return false
  }
  if (did === activeAgentDid.value) {
    errors.value.defendant_did = 'You cannot file a dispute against yourself.'
    return false
  }
  errors.value.defendant_did = ''
  return true
}

async function submit() {
  if (!validateDid()) return
  if (!form.value.category) { errors.value.category = 'Select a category.'; return }
  if (!form.value.description.trim()) { errors.value.description = 'Description is required.'; return }

  submitting.value = true
  try {
    await disputesStore.createDispute({
      defendant_did: form.value.defendant_did.trim(),
      category: form.value.category,
      description: form.value.description.trim(),
      ...(form.value.amount_disputed ? { amount_disputed: form.value.amount_disputed } : {})
    })
    emit('filed')
    close()
  } catch {
    // §FESUITE — the store has said why in a toast; the form stays open with what the person wrote
  } finally {
    submitting.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}
// Escape closes it wherever the focus is (the overlay's own @keydown.esc never heard it), never while filing.
useEscapeClose(() => props.modelValue, close, () => !submitting.value)
</script>

<style scoped>
/* §FESUITE: the optional note was 2.9:1 */
.fd-optional { color: #8193ab; }
</style>
