<template>
  <div v-if="peer" class="cm-modal-backdrop" @click.self="cancel">
    <div class="cm-modal">
      <h2 class="cm-modal-title"><Icon name="mdi:close-circle" /> BLACKLIST {{ peer.display_name }}</h2>

      <div class="cm-warning-box">
        This action is <strong>PERMANENT and IRREVERSIBLE from the API.</strong>
        It will:
        <ul>
          <li>Set <code>federation_status = 'blacklisted'</code></li>
          <li>Set <code>PeerRegistry.status = 'REJECTED'</code> (this one actually blocks transfers)</li>
          <li>Purge operator from card-relay propagation</li>
          <li>Emit <code>RegistryBlacklisted</code> to the immutable EventStore</li>
        </ul>
        To undo, direct DB intervention is required.
      </div>

      <label class="cm-label">
        <span>TYPE THE OPERATOR NAME TO CONFIRM</span>
        <input
          v-model="confirmText"
          type="text"
          :placeholder="peer.display_name"
          autocomplete="off"
        />
        <small v-if="confirmText && !nameMatches" class="cm-error-text">
          Does not match <code>{{ peer.display_name }}</code>
        </small>
      </label>

      <label class="cm-label">
        <span>REASON (REQUIRED, 20+ CHARS)</span>
        <textarea
          v-model="reason"
          rows="3"
          placeholder="e.g. Sustained supply-integrity policy drift despite 3 grace windows; operator unresponsive"
          maxlength="1000"
        />
        <small class="cm-hint">{{ reason.length }} / 1000 characters</small>
      </label>

      <label class="cm-checkbox">
        <input type="checkbox" v-model="acknowledged" />
        <span>I understand this is <strong>irreversible from the API</strong>.</span>
      </label>

      <div class="cm-modal-actions">
        <button class="cm-btn-ghost" @click="cancel">Cancel</button>
        <button
          class="cm-btn-danger"
          :disabled="!canSubmit || countdown > 0 || busy"
          @click="submit"
        >
          <span v-if="busy">Processing…</span>
          <span v-else-if="countdown > 0">Confirm Blacklist ({{ countdown }}s)</span>
          <span v-else>Confirm Blacklist</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import type { PeerComplianceRow } from '@/services/api/consulApi'

const props = defineProps<{ peer: PeerComplianceRow | null; busy: boolean }>()
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'confirm', reason: string): void }>()

const confirmText = ref('')
const reason = ref('')
const acknowledged = ref(false)
const countdown = ref(10)
let timer: ReturnType<typeof setInterval> | null = null

function startCountdown() {
  stopCountdown()
  countdown.value = 10
  timer = setInterval(() => {
    countdown.value = Math.max(0, countdown.value - 1)
    if (countdown.value <= 0 && timer) { clearInterval(timer); timer = null }
  }, 1000)
}
function stopCountdown() { if (timer) { clearInterval(timer); timer = null } }

watch(() => props.peer, (next) => {
  if (next) { confirmText.value = ''; reason.value = ''; acknowledged.value = false; startCountdown() }
  else stopCountdown()
}, { immediate: true })

onBeforeUnmount(stopCountdown)

const nameMatches = computed(() =>
  props.peer != null && confirmText.value.trim() === props.peer.display_name,
)
const canSubmit = computed(() =>
  props.peer != null && nameMatches.value && reason.value.trim().length >= 20 && acknowledged.value,
)
function cancel() { emit('cancel') }
function submit() { if (canSubmit.value) emit('confirm', reason.value.trim()) }
</script>

<style scoped>
.cm-modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.72);
  display: flex; align-items: center; justify-content: center; z-index: 3000;
}
.cm-modal {
  background: var(--nc-overlay);
  border: 1px solid var(--nc-danger-subtle);
  border-left: 3px solid var(--nc-danger);
  border-radius: 10px;
  padding: 22px;
  max-width: 560px; width: 92%;
  color: var(--nc-text-primary);
  box-shadow: var(--nc-shadow-xl);
  display: flex; flex-direction: column; gap: 14px;
}
.cm-modal-title {
  margin: 0; font-size: 15px; letter-spacing: 0.08em;
  color: var(--nc-danger); font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cm-warning-box {
  background: var(--nc-danger-subtle);
  border: 1px solid var(--nc-danger-subtle);
  border-radius: 6px; padding: 10px 14px;
  font-size: 12px; line-height: 1.55;
  color: var(--nc-text-primary);
}
.cm-warning-box ul { margin: 6px 0 0 0; padding-left: 18px; }
.cm-warning-box li { margin: 2px 0; }
.cm-label { display: flex; flex-direction: column; gap: 6px; font-size: 10px; letter-spacing: 0.1em; color: var(--nc-text-secondary); }
.cm-label input, .cm-label textarea {
  background: var(--nc-deep); color: var(--nc-text-primary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
}
.cm-label textarea { resize: vertical; }
.cm-error-text { color: var(--nc-danger); font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; letter-spacing: 0; }
.cm-hint { color: var(--nc-text-muted); font-size: 10px; font-family: 'JetBrains Mono', ui-monospace, monospace; }
.cm-checkbox {
  display: flex; gap: 8px; align-items: center;
  font-size: 12px; color: var(--nc-text-primary);
  background: var(--nc-warning-subtle);
  padding: 8px 12px; border-radius: 6px;
  border: 1px solid var(--nc-warning-subtle);
}
.cm-modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 4px; }
.cm-btn-ghost {
  background: transparent; color: var(--nc-text-secondary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 12px;
}
.cm-btn-danger {
  background: var(--nc-danger); color: #fff;
  border: none; border-radius: 6px; padding: 9px 20px; cursor: pointer;
  font-size: 11px; letter-spacing: 0.08em; font-weight: 600; text-transform: uppercase;
}
.cm-btn-danger:disabled { opacity: 0.35; cursor: not-allowed; }
code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; background: var(--nc-deep); padding: 1px 5px; border-radius: 3px; }
</style>
