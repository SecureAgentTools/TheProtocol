<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch, onUnmounted } from 'vue'
import { tegApi, type CrossRegistryTransfer, type CrossRegistryTransferResponse } from '@/services/api/teg'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useCurrency } from '@/composables/useCurrency'
import { fxService, type FxQuote } from '@/services/api/fx'
import '@/components/staking/tp-staking.css'

const props = defineProps<{
  show: boolean
  maxAmount?: string
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'transfer-complete': [result: CrossRegistryTransferResponse]
}>()

const uiStore = useUIStore()
const authStore = useAuthStore()
// FX multi-currency: the SENT amount is in the sender's currency (AVT/BVT).
// (Cross-CURRENCY recipient display / FX quote is the Phase-4 swap widget, §15.)
const { localCurrency } = useCurrency()

const receiverDid = ref('')
const amount = ref('')
const message = ref('')
const transferring = ref(false)
const transferResult = ref<CrossRegistryTransferResponse | null>(null)
const step = ref<'form' | 'confirm' | 'result'>('form')

const canTransfer = computed(() => {
  if (!receiverDid.value || !receiverDid.value.startsWith('did:')) return false
  if (!amount.value || parseFloat(amount.value) <= 0) return false
  if (props.maxAmount && parseFloat(amount.value) > parseFloat(props.maxAmount)) return false
  const myDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
  if (receiverDid.value === myDid) return false
  return true
})

// §15 FX swap: when the recipient sits on a different-currency frame, this
// cross-registry transfer becomes a swap. Debounced quote previews the converted
// receive amount; same-currency recipients keep the plain-transfer UX unchanged.
const fxQuote = ref<FxQuote | null>(null)
const fxQuoting = ref(false)
let fxQuoteTimer: ReturnType<typeof setTimeout> | null = null
let fxQuoteSeq = 0   // monotonic guard: a slow in-flight quote from a prior edit must not overwrite a newer one
const isCrossCurrency = computed(() => fxQuote.value?.same_currency === false)
const fxDestCurrency = computed(() => fxQuote.value?.dest_currency || '')
watch([receiverDid, amount], () => {
  fxQuote.value = null
  if (fxQuoteTimer) clearTimeout(fxQuoteTimer)
  const seq = ++fxQuoteSeq   // invalidate any quote already in flight for an older (DID, amount)
  if (!canTransfer.value) return
  fxQuoteTimer = setTimeout(async () => {
    fxQuoting.value = true
    try {
      // /teg/fx/quote is agent-JWT gated; on no-agent it 401s → caught → no FX block (graceful).
      const q = await fxService.quote({ receiver_did: receiverDid.value.trim(), amount: String(amount.value) })
      if (seq === fxQuoteSeq) fxQuote.value = q   // apply only if this is still the latest request
    } catch {
      if (seq === fxQuoteSeq) fxQuote.value = null
    } finally {
      if (seq === fxQuoteSeq) fxQuoting.value = false
    }
  }, 400)
})

// Polish: don't let a pending debounced quote fire after the modal unmounts.
onUnmounted(() => { if (fxQuoteTimer) clearTimeout(fxQuoteTimer) })

const formatAmount = (val: string | number) => {
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return '0.00'
  return num.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const formatDid = (did: string) => {
  if (!did) return ''
  if (did.length <= 30) return did
  return `${did.substring(0, 18)}...${did.substring(did.length - 10)}`
}

const setMaxAmount = () => {
  if (props.maxAmount) amount.value = props.maxAmount
}

const initiateTransfer = () => {
  if (!canTransfer.value) return
  step.value = 'confirm'
}

const confirmTransfer = async () => {
  transferring.value = true
  try {
    const result = await tegApi.transferCrossRegistry({
      receiver_did: receiverDid.value.trim(),
      amount: String(amount.value),
      message: message.value || undefined
    })
    transferResult.value = result
    step.value = 'result'
    if (result.status === 'completed') {
      uiStore.showSuccess('Transfer Complete', `${formatAmount(amount.value)} ${localCurrency.value} sent to ${formatDid(receiverDid.value)}`)
    } else if (result.status === 'failed') {
      uiStore.showError('Transfer Failed', result.error_message || 'Cross-registry transfer failed')
    }
    emit('transfer-complete', result)
  } catch (error: any) {
    const msg = error.response?.data?.detail || error.message || 'Failed to initiate cross-registry transfer'
    uiStore.showError('Transfer Failed', msg)
    step.value = 'form'
  } finally {
    transferring.value = false
  }
}

const goBack = () => {
  if (step.value === 'confirm') step.value = 'form'
  else closeModal()
}

const closeModal = () => {
  step.value = 'form'
  receiverDid.value = ''
  amount.value = ''
  message.value = ''
  transferResult.value = null
  fxQuote.value = null
  emit('update:show', false)
}

const copyTransferId = () => {
  if (transferResult.value?.transfer_id) {
    navigator.clipboard.writeText(transferResult.value.transfer_id).then(() => {
      uiStore.showSuccess('Copied', 'Transfer ID copied to clipboard')
    })
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="props.show"
      class="fixed inset-0 z-50 flex items-center justify-center p-4"
      style="background: rgba(0,0,0,0.75);"
      @click.self="closeModal"
    >
      <div class="sk-modal" style="max-width: 480px;">

        <!-- Header -->
        <div class="sk-modal-header">
          <span class="sk-modal-title">
            {{ step === 'result' ? 'Transfer Result' : '⇄ Cross-Registry Transfer' }}
          </span>
          <button @click="closeModal" style="color: var(--sk-text-muted); background:none; border:none; cursor:pointer;">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Body -->
        <div class="sk-modal-body">

          <!-- ── Form ─────────────────────────────────────── -->
          <div v-if="step === 'form'" class="space-y-4">
            <p class="text-sm" style="color: var(--sk-text-muted);">
              Send {{ localCurrency }} tokens to an agent on a federated registry via the 2PC cross-TEG protocol.
            </p>

            <!-- Receiver DID -->
            <div>
              <label class="sk-label">Receiver Agent DID</label>
              <input
                v-model="receiverDid"
                type="text"
                placeholder="did:cos:... or did:theprotocol:..."
                class="sk-input sk-input--mono"
              />
              <div v-if="receiverDid && !receiverDid.startsWith('did:')" class="sk-input-error">
                Must be a valid DID (starts with did:)
              </div>
              <div class="sk-input-hint">Agent must be registered on a federated peer registry</div>
            </div>

            <!-- Amount -->
            <div>
              <label class="sk-label">Amount ({{ localCurrency }})</label>
              <div class="relative">
                <input
                  v-model="amount"
                  type="number" step="0.01" min="0" :max="maxAmount"
                  placeholder="0.00"
                  class="sk-input"
                  style="padding-right: 4rem;"
                />
                <button v-if="maxAmount" @click="setMaxAmount" class="sk-btn sk-btn--max absolute right-2"
                  style="top: 50%; transform: translateY(-50%);">MAX</button>
              </div>
              <div v-if="maxAmount" class="sk-input-hint">
                Available: {{ formatAmount(parseFloat(maxAmount)) }} {{ localCurrency }}
              </div>
              <!-- §15 FX swap preview — only when the recipient is on a different-currency frame -->
              <div v-if="fxQuoting" class="sk-input-hint" style="opacity:0.7; margin-top:8px;">checking corridor…</div>
              <div v-else-if="isCrossCurrency" aria-live="polite" style="margin-top:8px; padding:10px 12px; border:1px solid rgba(255,157,60,0.4); border-radius:8px; background:rgba(255,157,60,0.06);">
                <div style="display:flex; justify-content:space-between; align-items:baseline; font-family:'Fira Code',monospace; font-size:0.8rem;">
                  <span style="color:rgba(255,157,60,0.95);"><span aria-hidden="true">⇄</span> cross-frame swap</span>
                  <span style="font-weight:700; color:var(--cur-bvt, #ff9d3c);">≈ {{ formatAmount(Number(fxQuote?.amount_out)) }} {{ fxDestCurrency }}</span>
                </div>
                <div style="display:flex; gap:14px; margin-top:4px; font-size:0.68rem; opacity:0.65; font-family:'Fira Code',monospace;">
                  <span>rate {{ Number(fxQuote?.rate).toLocaleString(appLocale(), { maximumFractionDigits: 5 }) }}</span>
                  <span v-if="fxQuote?.fee != null">fee {{ formatAmount(Number(fxQuote?.fee)) }}</span>
                  <span v-if="fxQuote?.slippage != null">slippage {{ (Number(fxQuote?.slippage) * 100).toFixed(3) }}%</span>
                  <span v-if="fxQuote?.expires_at">valid until {{ new Date(fxQuote.expires_at).toLocaleTimeString(appLocale()) }}</span>
                </div>
                <div style="margin-top:4px; font-size:0.64rem; opacity:0.5;">Rate is indicative — it moves with the pool until settlement.</div>
              </div>
            </div>

            <!-- Message -->
            <div>
              <label class="sk-label">Message <span style="opacity:0.5;">(Optional)</span></label>
              <input v-model="message" type="text" maxlength="256" placeholder="Transfer note"
                class="sk-input" />
            </div>

            <!-- Info -->
            <div class="sk-info-box flex gap-3 items-start">
              <span style="flex-shrink:0; font-size:1rem;">⛓</span>
              <div class="text-xs" style="color: var(--sk-text-sec);">
                Cross-registry transfers use the <strong style="color:var(--sk-cyan);">2-Phase Commit</strong> protocol.
                Funds lock, transfer to target TEG, then debit atomically.
                If the target TEG is unreachable, funds are automatically returned.
              </div>
            </div>
          </div>

          <!-- ── Confirm ─────────────────────────────────── -->
          <div v-else-if="step === 'confirm'" class="space-y-4">
            <div class="sk-warn-box flex gap-3 items-start">
              <span style="flex-shrink:0;"><Icon name="mdi:alert" /></span>
              <div class="text-xs">
                <strong>Confirm Cross-Registry Transfer</strong><br>
                This will initiate a 2PC transfer to an agent on another registry.
              </div>
            </div>

            <div class="sk-card" style="padding: 1rem; gap: 0;">
              <div class="flex justify-between py-2 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-sm" style="color: var(--sk-text-muted);">Receiver</span>
                <span class="font-mono text-sm" style="color: var(--sk-text);">{{ formatDid(receiverDid) }}</span>
              </div>
              <div class="flex justify-between py-3 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-sm" style="color: var(--sk-text-muted);">Amount</span>
                <span class="font-mono font-bold text-lg" style="color: var(--sk-cyan);">
                  {{ formatAmount(amount) }} {{ localCurrency }}
                </span>
              </div>
              <div v-if="isCrossCurrency" class="flex justify-between py-3 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-sm" style="color: var(--sk-text-muted);">Recipient receives ≈</span>
                <span class="font-mono font-bold" style="color: var(--cur-bvt, #ff9d3c);">
                  {{ formatAmount(Number(fxQuote?.amount_out)) }} {{ fxDestCurrency }}
                </span>
              </div>
              <div v-if="message" class="py-2">
                <span class="text-xs" style="color: var(--sk-text-muted);">Message</span>
                <p class="text-sm mt-1" style="color: var(--sk-text);">{{ message }}</p>
              </div>
            </div>
          </div>

          <!-- ── Result ──────────────────────────────────── -->
          <div v-else-if="step === 'result' && transferResult" class="space-y-4">
            <div class="text-center py-4">
              <div
                :class="[
                  'inline-flex items-center justify-center w-16 h-16 rounded-full mb-4',
                ]"
                :style="transferResult.status === 'completed'
                  ? 'background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.3);'
                  : 'background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.3);'"
              >
                <svg v-if="transferResult.status === 'completed'"
                  class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  style="color: #10b981;">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                <svg v-else class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  style="color: #ef4444;">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>

              <h4 class="font-mono font-semibold mb-1" style="color: var(--sk-text);">
                {{ transferResult.status === 'completed' ? 'Transfer Complete' : 'Transfer Failed' }}
              </h4>
              <p v-if="transferResult.error_message" class="text-sm" style="color: var(--sk-red);">
                {{ transferResult.error_message }}
              </p>
            </div>

            <div class="sk-card" style="padding: 1rem; border-color: rgba(var(--nc-primary-rgb),0.15);">
              <div class="flex justify-between items-center py-2 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-xs" style="color: var(--sk-text-muted);">Transfer ID</span>
                <div class="flex items-center gap-2">
                  <span class="font-mono text-xs" style="color: var(--sk-text);">
                    {{ transferResult.transfer_id.substring(0, 16) }}...
                  </span>
                  <button @click="copyTransferId" style="background:none; border:none; cursor:pointer; color: var(--sk-cyan);">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                    </svg>
                  </button>
                </div>
              </div>
              <div class="flex justify-between items-center py-2 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-xs" style="color: var(--sk-text-muted);">Status</span>
                <span class="sk-badge"
                  :class="{
                    'sk-badge--distributed': transferResult.status === 'completed',
                    'sk-badge--pending': transferResult.status === 'pending',
                    'sk-badge--failed': transferResult.status === 'failed'
                  }">
                  {{ transferResult.status }}
                </span>
              </div>
              <div class="flex justify-between items-center py-2 border-b" style="border-color: var(--sk-border-dim);">
                <span class="text-xs" style="color: var(--sk-text-muted);">Amount</span>
                <span class="font-mono font-bold" style="color: var(--sk-cyan);">{{ formatAmount(transferResult.amount) }} {{ localCurrency }}</span>
              </div>
              <div class="flex justify-between items-center py-2">
                <span class="text-xs" style="color: var(--sk-text-muted);">Route</span>
                <span class="font-mono text-xs" style="color: var(--sk-text);">{{ transferResult.source_teg }} → {{ transferResult.target_teg }}</span>
              </div>
            </div>
          </div>

        </div>

        <!-- Footer -->
        <div class="sk-modal-footer">
          <template v-if="step === 'form'">
            <button @click="closeModal" class="sk-btn sk-btn--ghost flex-1">Cancel</button>
            <button @click="initiateTransfer" :disabled="!canTransfer" class="sk-btn sk-btn--primary flex-1">
              Continue →
            </button>
          </template>
          <template v-else-if="step === 'confirm'">
            <button @click="goBack" :disabled="transferring" class="sk-btn sk-btn--ghost flex-1">← Back</button>
            <button @click="confirmTransfer" :disabled="transferring" class="sk-btn sk-btn--primary flex-1">
              {{ transferring ? 'Sending...' : 'Confirm Transfer' }}
            </button>
          </template>
          <template v-else-if="step === 'result'">
            <button @click="closeModal" class="sk-btn sk-btn--outline flex-1">Close</button>
          </template>
        </div>

      </div>
    </div>
  </Teleport>
</template>
