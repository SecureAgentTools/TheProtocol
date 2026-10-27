<template>
  <Teleport to="body">
    <div v-if="show" class="ca-overlay" @click.self="emit('close')">
      <div ref="modalRef" class="ca-modal" :class="`ca-modal--${tone}`" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1">
        <div class="ca-modal-header">
          <span :id="titleId" class="ca-modal-title">{{ title }}</span>
          <button class="ca-modal-close" @click="emit('close')" aria-label="Close" :disabled="busy">✕</button>
        </div>

        <div class="ca-modal-body">
          <p class="ca-modal-message" v-html="message"></p>

          <p v-if="warning" class="ca-banner ca-banner--warn">
            <strong>{{ warningTitle }}</strong> {{ warning }}
          </p>

          <div v-if="reasonRequired || reasonOptional || requiredMatch !== undefined" class="ca-field">
            <label :for="reasonId" class="ca-label">
              <template v-if="requiredMatch !== undefined">Type to confirm</template>
              <template v-else-if="reasonOptional">Reason (optional)</template>
              <template v-else>Reason{{ reasonMinLength ? ` * (min ${reasonMinLength} chars)` : ' *' }}</template>
            </label>
            <textarea
              :id="reasonId"
              ref="reasonRef"
              v-model="reason"
              class="ca-input"
              :rows="3"
              :placeholder="reasonPlaceholder || 'Explain why…'"
              :disabled="busy"
            />
          </div>

          <p v-if="validationError" class="ca-banner ca-banner--danger" role="alert"><Icon name="mdi:alert" /> {{ validationError }}</p>
        </div>

        <div class="ca-modal-footer">
          <button class="ca-btn ca-btn--ghost" @click="emit('close')" :disabled="busy">{{ cancelText }}</button>
          <button
            :class="['ca-btn', tone === 'danger' ? 'ca-btn--danger' : tone === 'warn' ? 'ca-btn--warn' : 'ca-btn--primary']"
            :disabled="busy || disabledByValidation"
            @click="onConfirm"
          >
            <span v-if="busy" class="ca-spinner"></span>
            {{ busy ? (busyText || 'Working…') : confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch, nextTick, toRef } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'

const props = withDefaults(defineProps<{
  show: boolean
  title: string
  message: string                      // HTML allowed via v-html — caller responsibility to sanitize
  /** Tone — controls accent color of confirm button + modal border. */
  tone?: 'primary' | 'warn' | 'danger'
  /** Confirm button label. */
  confirmText?: string
  /** Cancel button label. */
  cancelText?: string
  /** Label shown on the confirm button while `busy` is true. */
  busyText?: string
  /** External busy flag — prevents double-submit and disables Cancel/Close. */
  busy?: boolean
  /** Optional secondary warning banner inside the body. */
  warning?: string
  warningTitle?: string
  /** When true, render a reason textarea + require min N chars. */
  reasonRequired?: boolean
  /** When true, render reason as optional (no validation). */
  reasonOptional?: boolean
  /** Minimum character count for required reason. Defaults to 10. */
  reasonMinLength?: number
  /** Reason input placeholder. */
  reasonPlaceholder?: string
  /**
   * Typed-name confirmation pattern. When set, the reason input must exactly
   * match this string (case-sensitive) before confirm is enabled. Overrides
   * `reasonRequired` + `reasonMinLength` semantics — the message should tell
   * the user what to type. Used for "type ORG_NAME to delete" flows.
   */
  requiredMatch?: string
}>(), {
  tone: 'primary',
  confirmText: 'Confirm',
  cancelText: 'Cancel',
  busy: false,
  warningTitle: '⚠',
  reasonMinLength: 10,
})

const emit = defineEmits<{
  (e: 'close'): void
  /** Fires when user clicks confirm. Receives the reason if reasonRequired/reasonOptional. */
  (e: 'confirm', reason: string): void
}>()

const reason = ref('')
const validationError = ref('')
const reasonRef = ref<HTMLTextAreaElement | null>(null)
const modalRef = ref<HTMLElement | null>(null)
const titleId = `ca-title-${Math.random().toString(36).slice(2, 8)}`
const reasonId = `ca-reason-${Math.random().toString(36).slice(2, 8)}`

// G (2026-05-08): WCAG focus-trap. Activates when `show` flips true,
// deactivates when false. Restores focus to trigger element on close.
useFocusTrap(modalRef, { activeWhen: toRef(props, 'show') })

const disabledByValidation = computed(() => {
  if (props.requiredMatch !== undefined) {
    return reason.value !== props.requiredMatch
  }
  if (props.reasonRequired && (reason.value.trim().length < (props.reasonMinLength ?? 10))) return true
  return false
})

watch(
  () => props.show,
  async (v) => {
    if (v) {
      reason.value = ''
      validationError.value = ''
      await nextTick()
      reasonRef.value?.focus()
    }
  },
)

function onConfirm() {
  if (props.requiredMatch !== undefined) {
    if (reason.value !== props.requiredMatch) {
      validationError.value = `Must match exactly: "${props.requiredMatch}"`
      return
    }
  } else if (props.reasonRequired) {
    const min = props.reasonMinLength ?? 10
    if (reason.value.trim().length < min) {
      validationError.value = `Reason must be at least ${min} characters (got ${reason.value.trim().length}).`
      return
    }
  }
  validationError.value = ''
  emit('confirm', reason.value.trim())
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, () => emit('close'), () => !props.busy)
</script>

<style scoped>
.ca-overlay {
  /* z-index 10100 sits above .tp-overlay (9999) and .fed-drawer-overlay (9999)
   * so ConfirmActionModal can stack on top of parent modals (e.g. delete-org
   * confirm inside OrganizationDashboard, approve-frame-federation confirm
   * inside Federation invitations review). */
  position: fixed; inset: 0; z-index: 10100;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  animation: ca-fade-in 0.15s ease;
}
.ca-modal {
  background: #0d1626;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 12px;
  width: min(96vw, 520px);
  max-height: 90vh; overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6), 0 0 40px rgba(var(--nc-primary-rgb), 0.05);
  animation: ca-entry 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}
.ca-modal--warn   { border-color: rgba(251, 191, 36, 0.35); }
.ca-modal--danger { border-color: rgba(239, 68, 68, 0.35); }

.ca-modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1.1rem 1.4rem 0.9rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.ca-modal-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: rgb(0, 210, 210);
}
.ca-modal--warn   .ca-modal-title { color: rgb(251, 191, 36); }
.ca-modal--danger .ca-modal-title { color: rgb(239, 68, 68); }

.ca-modal-close {
  width: 26px; height: 26px;
  border-radius: 6px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  background: transparent;
  color: #8fa3be;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem; transition: all 0.15s;
}
.ca-modal-close:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: rgb(0, 210, 210);
}
.ca-modal-close:disabled { opacity: 0.4; cursor: not-allowed; }

.ca-modal-body { padding: 1.1rem 1.4rem; }
.ca-modal-message {
  color: #c8d6e8; font-size: 0.9rem; line-height: 1.5; margin: 0 0 0.85rem;
}
.ca-modal-message :deep(strong) { color: #e2e8f0; }
.ca-modal-message :deep(code)   {
  background: rgba(var(--nc-primary-rgb), 0.1);
  padding: 1px 5px; border-radius: 3px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.82em;
  color: rgb(0, 210, 210);
}

.ca-banner {
  border-radius: 8px; padding: 0.65rem 0.9rem;
  font-size: 0.82rem; line-height: 1.45;
  margin: 0.6rem 0;
}
.ca-banner--warn   { background: rgba(251, 191, 36, 0.08); border: 1px solid rgba(251, 191, 36, 0.25); color: rgba(251, 191, 36, 0.95); }
.ca-banner--danger { background: rgba(239, 68, 68, 0.08);  border: 1px solid rgba(239, 68, 68, 0.25);  color: rgba(239, 68, 68, 0.95); }

.ca-field { margin-top: 0.6rem; }
.ca-label {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: #8fa3be; margin-bottom: 0.4rem;
}
.ca-input {
  width: 100%;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 6px;
  color: #e2e8f0; padding: 0.55rem 0.8rem;
  font-size: 0.85rem; outline: none;
  font-family: inherit; resize: vertical;
  transition: border-color 0.15s;
}
.ca-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(255, 255, 255, 0.06);
}
.ca-input:disabled { opacity: 0.5; cursor: not-allowed; }

.ca-modal-footer {
  display: flex; align-items: center; justify-content: flex-end;
  gap: 0.6rem;
  padding: 0.9rem 1.4rem 1.1rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.ca-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.55rem 1.1rem;
  border-radius: 6px;
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.ca-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ca-btn--ghost   { background: transparent; color: #8fa3be; border-color: rgba(var(--nc-primary-rgb), 0.2); }
.ca-btn--ghost:hover:not(:disabled)   { background: rgba(var(--nc-primary-rgb), 0.08); color: rgb(0, 210, 210); }
.ca-btn--primary { background: rgb(0, 210, 210); color: #060b14; border-color: rgb(0, 210, 210); }
.ca-btn--primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.85); }
.ca-btn--warn    { background: rgba(251, 191, 36, 0.15); color: rgb(251, 191, 36); border-color: rgba(251, 191, 36, 0.4); }
.ca-btn--warn:hover:not(:disabled)    { background: rgba(251, 191, 36, 0.25); }
.ca-btn--danger  { background: rgba(239, 68, 68, 0.15);  color: rgb(239, 68, 68);  border-color: rgba(239, 68, 68, 0.4); }
.ca-btn--danger:hover:not(:disabled)  { background: rgba(239, 68, 68, 0.25); }

.ca-spinner {
  width: 12px; height: 12px;
  border: 2px solid rgba(var(--nc-primary-rgb), 0.3);
  border-top-color: rgb(0, 210, 210);
  border-radius: 50%;
  animation: ca-spin 0.7s linear infinite;
  display: inline-block;
}

@keyframes ca-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes ca-entry   { from { opacity: 0; transform: scale(0.97) translateY(8px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes ca-spin    { to { transform: rotate(360deg); } }
</style>
