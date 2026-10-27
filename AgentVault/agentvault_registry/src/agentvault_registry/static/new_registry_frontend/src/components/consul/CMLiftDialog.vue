<template>
  <div v-if="peer" class="cm-lift-backdrop" @click.self="cancel">
    <div class="cm-lift-dialog">
      <h3>Lift quarantine · {{ peer.display_name }}</h3>

      <p class="cm-lift-info">
        Restores <code>federation_status</code> to <strong>federated</strong> and
        replaces the admission hash with the hash you provide below. Use this
        after the operator has submitted a corrected policy via
        <code>POST /admin/federation/policy-update-request</code> and you've
        verified the new canonical hash.
      </p>

      <div class="cm-lift-current" v-if="peer.quarantine_reason">
        <div class="cm-dim">CURRENT QUARANTINE REASON</div>
        <code>{{ peer.quarantine_reason }}</code>
      </div>

      <label class="cm-label">
        <span>NEW CANONICAL POLICY HASH (64 HEX CHARS)</span>
        <input
          v-model="newHash"
          type="text"
          placeholder="e.g. 7f4a3c…"
          autocomplete="off"
          maxlength="64"
        />
        <small v-if="newHash && !hashValid" class="cm-error-text">
          Must be exactly 64 hexadecimal characters.
        </small>
      </label>

      <div class="cm-lift-actions">
        <button class="cm-btn-ghost" @click="cancel" :disabled="busy">Cancel</button>
        <button
          class="cm-btn-primary"
          :disabled="!hashValid || busy"
          @click="submit"
        >
          {{ busy ? 'Lifting…' : 'Lift quarantine' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PeerComplianceRow } from '@/services/api/consulApi'

const props = defineProps<{ peer: PeerComplianceRow | null; busy: boolean }>()
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'confirm', newHash: string): void }>()

const newHash = ref('')
watch(() => props.peer, () => { newHash.value = '' })
const hashValid = computed(() => /^[0-9a-fA-F]{64}$/.test(newHash.value))

function cancel() { emit('cancel') }
function submit() {
  if (!hashValid.value) return
  emit('confirm', newHash.value.toLowerCase())
}
</script>

<style scoped>
.cm-lift-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 2500;
}
.cm-lift-dialog {
  background: var(--nc-overlay);
  border: 1px solid var(--nc-success-subtle);
  border-left: 3px solid var(--nc-success);
  border-radius: 10px;
  padding: 20px 22px;
  max-width: 520px; width: 92%;
  color: var(--nc-text-primary);
  display: flex; flex-direction: column; gap: 12px;
  box-shadow: var(--nc-shadow-xl);
}
.cm-lift-dialog h3 { margin: 0; font-size: 14px; letter-spacing: 0.08em; color: var(--nc-success); text-transform: uppercase; }
.cm-lift-info { font-size: 12px; line-height: 1.6; margin: 0; color: var(--nc-text-secondary); }
.cm-lift-current {
  background: var(--nc-warning-subtle);
  border: 1px solid var(--nc-warning-subtle);
  padding: 9px 12px; border-radius: 6px;
  font-size: 11px; line-height: 1.5;
}
.cm-dim { color: var(--nc-text-muted); font-size: 9px; letter-spacing: 0.1em; margin-bottom: 4px; }
.cm-lift-current code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; color: var(--nc-text-primary); display: block; word-break: break-all; background: transparent; padding: 0; }
.cm-label { display: flex; flex-direction: column; gap: 6px; font-size: 10px; letter-spacing: 0.1em; color: var(--nc-text-secondary); }
.cm-label input {
  background: var(--nc-deep); color: var(--nc-text-primary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
}
.cm-error-text { color: var(--nc-danger); font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; letter-spacing: 0; }
.cm-lift-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 2px; }
.cm-btn-ghost {
  background: transparent; color: var(--nc-text-secondary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 12px;
}
.cm-btn-primary {
  background: var(--nc-success); color: var(--nc-text-inverse);
  border: none; border-radius: 6px; padding: 8px 18px; cursor: pointer;
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
}
.cm-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; background: var(--nc-deep); padding: 1px 5px; border-radius: 3px; color: var(--nc-text-primary); }
</style>
