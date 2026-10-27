<template>
  <Teleport to="body">
    <div v-if="show" class="gam-overlay" @click.self="onCancel">
      <div class="gam-panel" role="dialog" aria-modal="true" :aria-labelledby="ids.title">
        <header class="gam-head">
          <h3 :id="ids.title" class="gam-title">{{ title }}</h3>
          <button class="gam-x" type="button" aria-label="Cancel" @click="onCancel">
            <Icon name="mdi:close" :size="14" />
          </button>
        </header>

        <!-- Target echo — the mis-target guard. Always names BOTH sides. -->
        <div class="gam-target">
          <div class="gam-target-row">
            <span class="gam-target-k">Target</span>
            <span class="gam-target-v">{{ targetLabel }}</span>
          </div>
          <div class="gam-target-row">
            <span class="gam-target-k">Executing as</span>
            <span class="gam-target-v gam-target-exec">{{ executorLabel }}</span>
          </div>
        </div>

        <div class="gam-body">
          <label class="gam-label" :for="ids.amount">{{ amountLabel }} <span v-if="currency" class="gam-ccy">{{ currency }}</span></label>
          <input
            :id="ids.amount"
            ref="amountInput"
            v-model.trim="amount"
            class="gam-input gam-amount"
            type="text"
            inputmode="decimal"
            autocomplete="off"
            spellcheck="false"
            placeholder="0.00"
            :disabled="busy"
            @keydown.enter="onConfirm"
          />
          <p v-if="amount && !amountValid" class="gam-err">Enter a positive number (up to 8 decimals).</p>

          <label v-if="reasonEnabled" class="gam-label" :for="ids.reason">Reason <span class="gam-opt">(optional)</span></label>
          <input
            v-if="reasonEnabled"
            :id="ids.reason"
            v-model.trim="reason"
            class="gam-input"
            type="text"
            autocomplete="off"
            :placeholder="defaultReason || 'operator action'"
            :disabled="busy"
          />

          <div v-if="needsTypedConfirm" class="gam-warn">
            <Icon name="mdi:alert" :size="14" class="gam-warn-ic" />
            <div>
              <p class="gam-warn-t">Large amount — type <strong class="gam-mono">{{ amount }}</strong> to confirm.</p>
              <input
                v-model.trim="typed"
                class="gam-input gam-mono"
                type="text"
                inputmode="decimal"
                autocomplete="off"
                :disabled="busy"
                aria-label="Type the amount again to confirm"
              />
            </div>
          </div>
        </div>

        <footer class="gam-foot">
          <button class="gam-btn" type="button" :disabled="busy" @click="onCancel">Cancel</button>
          <button class="gam-btn gam-btn-go" type="button" :disabled="!canConfirm || busy" @click="onConfirm">
            <span v-if="busy" class="gam-spin" aria-hidden="true"></span>
            {{ busy ? 'Executing…' : confirmText }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'

const props = withDefaults(defineProps<{
  show: boolean
  title: string
  targetLabel: string
  executorLabel: string
  amountLabel?: string
  currency?: string
  confirmText?: string
  warnThreshold?: number
  reasonEnabled?: boolean
  defaultReason?: string
  busy?: boolean
}>(), {
  amountLabel: 'Amount',
  currency: '',
  confirmText: 'Execute',
  warnThreshold: 100000,
  reasonEnabled: true,
  defaultReason: '',
  busy: false,
})

const emit = defineEmits<{ (e: 'confirm', p: { amount: string; reason: string }): void; (e: 'cancel'): void }>()

const uid = Math.random().toString(36).slice(2, 8)
const ids = { title: `gam-t-${uid}`, amount: `gam-a-${uid}`, reason: `gam-r-${uid}` }

const amount = ref('')
const reason = ref('')
const typed = ref('')
const amountInput = ref<HTMLInputElement | null>(null)

// Amounts stay STRINGS end-to-end (Decimal doctrine); parseFloat only gates the warn UI.
const amountValid = computed(() => /^\d+(\.\d{1,8})?$/.test(amount.value) && parseFloat(amount.value) > 0)
const needsTypedConfirm = computed(() => amountValid.value && parseFloat(amount.value) >= props.warnThreshold)
const canConfirm = computed(() => amountValid.value && (!needsTypedConfirm.value || typed.value === amount.value))

watch(() => props.show, async (v) => {
  if (v) {
    amount.value = ''; reason.value = ''; typed.value = ''
    await nextTick()
    amountInput.value?.focus()
  }
})

function onConfirm() {
  if (!canConfirm.value || props.busy) return
  emit('confirm', { amount: amount.value, reason: reason.value || props.defaultReason })
}
function onCancel() { if (!props.busy) emit('cancel') }

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, onCancel)
</script>

<style scoped>
/* Teleport modal — carries its own token fallbacks (scoped palettes don't reach body). */
.gam-overlay {
  position: fixed; inset: 0; z-index: 10300;
  background: rgba(2, 5, 10, 0.72);
  backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 18px;
}
.gam-panel {
  width: 100%; max-width: 420px;
  background:
    linear-gradient(168deg, rgba(255,255,255,.025), transparent 60%),
    rgba(13, 18, 28, 0.97);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), 0.22);
  border-radius: 12px;
  box-shadow: 0 18px 60px rgba(0,0,0,.55);
  color: var(--nc-text-primary, #e8eaed);
}
.gam-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.gam-title { margin: 0; font-size: .95rem; font-weight: 700; letter-spacing: .02em; }
.gam-x {
  width: 30px; height: 30px; display: grid; place-items: center;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
  border-radius: 7px; color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gam-x:hover { color: #fff; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .4); }

.gam-target {
  margin: 0 16px; padding: 9px 11px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .06);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .25);
  border-radius: 8px; display: grid; gap: 4px;
}
.gam-target-row { display: flex; gap: 10px; align-items: baseline; font-size: .76rem; }
.gam-target-k { color: var(--nc-text-muted, #94a3b8); min-width: 88px; text-transform: uppercase; font-size: .6rem; letter-spacing: .1em; font-weight: 700; }
.gam-target-v { font-weight: 700; color: var(--nc-primary, #00d2d2); word-break: break-all; }
.gam-target-exec { color: var(--nc-text-primary, #e8eaed); font-weight: 600; }

.gam-body { padding: 12px 16px 4px; }
.gam-label { display: block; font-size: .64rem; text-transform: uppercase; letter-spacing: .1em; font-weight: 700; color: var(--nc-text-muted, #94a3b8); margin: 10px 0 5px; }
.gam-ccy { color: var(--nc-primary, #00d2d2); margin-left: 4px; }
.gam-opt { text-transform: none; letter-spacing: 0; font-weight: 500; }
.gam-input {
  width: 100%; padding: 9px 11px;
  background: rgba(4, 8, 14, 0.55);
  border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
  color: var(--nc-text-primary, #e8eaed); font-size: 16px; /* iOS no-zoom */
}
.gam-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .55); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb, 0,210,210), .12); }
.gam-amount { font-variant-numeric: tabular-nums; font-weight: 700; }
.gam-mono { font-family: ui-monospace, monospace; }
.gam-err { margin: 5px 0 0; font-size: .72rem; color: #ef4444; }

.gam-warn {
  margin-top: 12px; padding: 10px;
  display: flex; gap: 9px; align-items: flex-start;
  background: rgba(245, 158, 11, .08); border: 1px solid rgba(245, 158, 11, .35); border-radius: 8px;
}
.gam-warn-ic { color: #f59e0b; flex: 0 0 auto; margin-top: 2px; }
.gam-warn-t { margin: 0 0 6px; font-size: .76rem; color: #fbbf24; }

.gam-foot { display: flex; justify-content: flex-end; gap: 9px; padding: 14px 16px 16px; }
.gam-btn {
  min-height: 38px; padding: 0 16px; border-radius: 8px; cursor: pointer; font-size: .8rem; font-weight: 600;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1); color: var(--nc-text-primary, #e8eaed);
}
.gam-btn:hover:not(:disabled) { border-color: rgba(255,255,255,.25); }
.gam-btn-go {
  background: rgba(var(--nc-primary-rgb, 0,210,210), .14);
  border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45);
  color: var(--nc-primary, #00d2d2);
}
.gam-btn-go:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb, 0,210,210), .22); }
.gam-btn:disabled { opacity: .45; cursor: not-allowed; }
.gam-spin {
  display: inline-block; width: 12px; height: 12px; margin-right: 7px; vertical-align: -1px;
  border: 2px solid rgba(255,255,255,.25); border-top-color: currentColor; border-radius: 50%;
  animation: gam-rot .7s linear infinite;
}
@keyframes gam-rot { to { transform: rotate(360deg); } }

@media (max-width: 640px) {
  .gam-overlay { align-items: flex-end; padding: 0; }
  .gam-panel { max-width: none; border-radius: 14px 14px 0 0; border-bottom: none; }
}
</style>
