<template>
  <div class="tp-overlay" @click.self="$emit('close')">
    <div ref="dialogEl" role="dialog" aria-modal="true" aria-labelledby="ctr-create-title" class="tp-modal tp-modal--lg">
      <div class="tp-modal-header">
        <span id="ctr-create-title" class="tp-modal-title">⬡ Propose Contract</span>
        <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('close')">×</button>
      </div>

      <div class="tp-modal-body">
        <!-- Client agent pre-fill -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-create-client">Client Agent (you)</label>
          <input id="ctr-create-client" class="tp-input" :value="activeAgentDid" readonly />
          <p class="tp-hint">Your active agent is the client. Switch agents in the header to change.</p>
        </div>

        <!-- Scope description -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-create-scope">Scope Description *</label>
          <textarea
            id="ctr-create-scope"
            v-model="form.scope_description"
            class="tp-textarea"
            rows="3"
            placeholder="What needs to be built or fixed? Be precise."
            maxlength="1000"
          />
          <p class="tp-hint">{{ form.scope_description.length }}/1000</p>
        </div>

        <!-- Repo URL -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-create-repo">Source Code Repository URL *</label>
          <input
            id="ctr-create-repo"
            v-model="form.source_code_repo_url"
            class="tp-input"
            placeholder="https://github.com/org/repo"
          />
        </div>

        <!-- Branch -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-create-branch">Branch</label>
          <input
            id="ctr-create-branch"
            v-model="form.source_code_branch"
            class="tp-input"
            placeholder="main"
          />
        </div>

        <!-- Payment amount — §BLOGSHOTS-FIX: currency comes from the frame, never hardcoded
             (this label read "(AVT)" on BVT and JDAY frames). -->
        <div class="tp-field">
          <label class="tp-label" for="ctr-create-amount">Payment Amount ({{ localCurrency }}) *</label>
          <input
            id="ctr-create-amount"
            v-model.number="form.payment_amount"
            class="tp-input"
            type="number"
            min="1"
            step="1"
            :aria-invalid="!amountOk"
            placeholder="e.g. 500"
          />
          <p v-if="!amountOk" class="tp-hint" data-testid="ctr-create-amount-warn" style="color: rgb(251,191,36);">{{ t('contractsView.modal.wholeUnits', 'A whole number of units, from 1 to 10,000,000.') }}</p>
          <p v-else-if="insufficientBalance" class="tp-hint" style="color: rgb(251,191,36);">
            <Icon name="mdi:alert" /> Your liquid balance is {{ liquidBalance.toLocaleString(appLocale()) }} {{ localCurrency }} — this exceeds it.
          </p>
          <p v-else-if="liquidBalance > 0" class="tp-hint">
            Your liquid balance: {{ liquidBalance.toLocaleString(appLocale()) }} {{ localCurrency }}
          </p>
        </div>

        <!-- Acceptance criteria -->
        <div class="tp-field">
          <label class="tp-label">Acceptance Criteria</label>
          <div v-for="(pair, idx) in criteriaRows" :key="idx" class="tp-kv-row">
            <input v-model="pair.key" class="tp-input" placeholder="criterion key" />
            <input v-model="pair.val" class="tp-input" placeholder="expected value" />
            <button class="tp-kv-remove" @click="removeCriteria(idx)">−</button>
          </div>
          <button class="tp-btn tp-btn--ghost" style="font-size:0.68rem; margin-top:0.25rem;" @click="addCriteria">
            + Add Criterion
          </button>
        </div>

        <!-- §FESUITE: a "Preferred Upgrader DID" field stood here and was never sent (the legacy create takes no
             upgrader; anyone may accept a proposed contract), so it promised a reservation that did not exist. -->

        <div v-if="error" class="tp-banner tp-banner--danger" style="margin-top:0.5rem;">
          {{ error }}
        </div>
      </div>

      <div class="tp-modal-footer">
        <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="loading">Cancel</button>
        <button class="tp-btn tp-btn--primary" @click="submit" :disabled="loading || !isValid">
          <span v-if="loading" class="tp-spinner" />
          <span v-else>Propose Contract</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, reactive } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useContractStore } from '@/stores/contracts'
import { ctrRef } from '@/services/api/contracts'
import './tp-contract-modals.css'
import { useCurrency } from '@/composables/useCurrency'
import { computed as _dlgComputed, ref as _dlgRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const emit = defineEmits<{ close: []; created: [id: number | string] }>()

const authStore = useAuthStore()
const contractStore = useContractStore()
const { localCurrency } = useCurrency()
// §FESUITE — a modal is a dialog: named, Escape closes it, focus stays inside and returns to the opener.
const { t, tp } = useI18n()
const dialogEl = _dlgRef<HTMLElement | null>(null)
useFocusTrap(dialogEl, { activeWhen: _dlgComputed(() => true) })

const activeAgentDid = computed(
  () => authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
)
const liquidBalance = computed(
  () => authStore.activeAgent?.liquidBalance ?? 0
)

const form = reactive({
  scope_description: '',
  source_code_repo_url: '',
  source_code_branch: 'main',
  payment_amount: 100,
})

const criteriaRows = ref<{ key: string; val: string }[]>([{ key: '', val: '' }])

function addCriteria() {
  criteriaRows.value.push({ key: '', val: '' })
}
function removeCriteria(idx: number) {
  criteriaRows.value.splice(idx, 1)
}

const loading = ref(false)
const error = ref('')

/* §FESUITE — the legacy rail takes a whole number of units (gt=0, le=10,000,000); 1.5 used to leave the page and
   come back as a validation error. */
const amountOk = computed(() => Number.isInteger(form.payment_amount) && form.payment_amount >= 1 && form.payment_amount <= 10_000_000)
const insufficientBalance = computed(
  () => liquidBalance.value > 0 && form.payment_amount > liquidBalance.value
)

const isValid = computed(
  () =>
    activeAgentDid.value &&
    form.scope_description.trim().length >= 10 &&
    form.source_code_repo_url.trim().length > 0 &&
    amountOk.value
)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const criteria: Record<string, any> = {}
    for (const row of criteriaRows.value) {
      if (row.key.trim()) criteria[row.key.trim()] = row.val.trim()
    }
    const contract = await contractStore.createContract({
      client_agent_did: activeAgentDid.value,
      scope_description: form.scope_description.trim(),
      source_code_repo_url: form.source_code_repo_url.trim(),
      source_code_branch: form.source_code_branch.trim() || 'main',
      acceptance_criteria: criteria,
      payment_amount: form.payment_amount
    })
    emit('created', ctrRef(contract))
    emit('close')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'Failed to create contract'
  } finally {
    loading.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
