<template>
  <section class="cm-mode" aria-label="CONSUL enforcement mode">
    <div class="cm-mode-row">
      <span class="cm-mode-label">MODE</span>

      <div class="cm-seg">
        <button
          class="cm-seg-btn"
          :class="{ active: modeState?.mode === 'off' }"
          :disabled="busy"
          @click="request('off')"
          title="Poller skips all cycles"
        >OFF</button>
        <button
          class="cm-seg-btn"
          :class="{ active: modeState?.mode === 'dry_run' }"
          :disabled="busy"
          @click="request('dry_run')"
          title="Detect &amp; log, never quarantine"
        >DRY-RUN</button>
        <button
          class="cm-seg-btn"
          :class="{ active: modeState?.mode === 'enforcing' }"
          :disabled="busy"
          @click="request('enforcing')"
          title="Live quarantine (env flag also required)"
        >ENFORCING</button>
      </div>

      <span class="cm-pill" :class="effectiveClass" :title="effectiveTooltip">
        {{ modeState?.effective_enforcement ? 'LIVE ENFORCEMENT' : 'SAFE' }}
      </span>

      <span class="cm-flag" title="IS_CENTRAL_REGISTRY env var">
        <span class="cm-flag-label">IS_CENTRAL_REGISTRY</span>
        <b :class="modeState?.is_central_registry_env_flag ? 'on' : 'off'">
          {{ modeState?.is_central_registry_env_flag ?? '—' }}
        </b>
      </span>
      <span class="cm-flag" title="FEDERATION_ENFORCEMENT_ACTIVE env var">
        <span class="cm-flag-label">FEDERATION_ENFORCEMENT_ACTIVE</span>
        <b :class="modeState?.enforcement_env_flag ? 'on' : 'off'">
          {{ modeState?.enforcement_env_flag ?? '—' }}
        </b>
      </span>

      <span v-if="modeState?.last_changed_at" class="cm-last">
        last change {{ timeAgo(modeState.last_changed_at) }}
        <em v-if="modeState.last_changed_by">· {{ modeState.last_changed_by }}</em>
      </span>
    </div>

    <!-- Confirmation dialog -->
    <div v-if="pendingMode" class="cm-confirm-backdrop" @click.self="cancel">
      <div class="cm-confirm-dialog">
        <h3>Confirm mode change</h3>
        <p>
          <code>{{ modeState?.mode ?? '—' }}</code> →
          <code>{{ pendingMode }}</code>
        </p>
        <p v-if="pendingMode === 'enforcing'" class="cm-warn">
          Arms live quarantine. Drift or 3 consecutive poll failures will trigger
          <code>trigger_quarantine</code> if
          <code>FEDERATION_ENFORCEMENT_ACTIVE=true</code> and
          <code>IS_CENTRAL_REGISTRY=true</code>.
        </p>
        <p v-else-if="pendingMode === 'dry_run'" class="cm-info">
          Detection runs, but no quarantine fires. Drift emits
          <code>ComplianceDryRunDrift</code>. Use this mode for at least one
          observation window before arming.
        </p>
        <p v-else class="cm-info">
          Poller skips every cycle. Existing quarantines are not cleared.
        </p>

        <label class="cm-label">
          Audit reason (5–500 chars, required)
          <textarea
            v-model="reason"
            rows="3"
            placeholder="e.g. Opening dry-run observation window after retro-admission"
            maxlength="500"
          />
        </label>

        <div class="cm-confirm-actions">
          <button class="cm-btn-ghost" @click="cancel" :disabled="busy">Cancel</button>
          <button
            class="cm-btn-primary"
            :disabled="!canConfirm || busy"
            @click="confirm"
          >
            {{ busy ? 'Applying…' : `Set mode to ${pendingMode}` }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

import type { EnforcementMode, EnforcementModeState } from '@/services/api/consulApi'

const props = defineProps<{
  modeState: EnforcementModeState | null
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'change', payload: { mode: EnforcementMode; reason: string }): void
}>()

const pendingMode = ref<EnforcementMode | null>(null)
const reason = ref('')

const effectiveClass = computed(() =>
  props.modeState?.effective_enforcement ? 'cm-pill-live' : 'cm-pill-safe',
)
const effectiveTooltip = computed(() =>
  props.modeState?.effective_enforcement
    ? 'Mode=enforcing AND both env flags on — quarantines fire live'
    : 'Safe: at least one kill switch is off. Quarantines will not fire.',
)

const canConfirm = computed(() => reason.value.trim().length >= 5)

function request(mode: EnforcementMode) {
  if (mode === props.modeState?.mode) return
  pendingMode.value = mode
  reason.value = ''
}
function cancel() { pendingMode.value = null; reason.value = '' }
function confirm() {
  if (!pendingMode.value || !canConfirm.value) return
  emit('change', { mode: pendingMode.value, reason: reason.value.trim() })
  pendingMode.value = null
  reason.value = ''
}
function timeAgo(ts: string | null) { return ts ? dayjs(ts).fromNow() : '—' }
</script>

<style scoped>
.cm-mode {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 12px 16px;
}
.cm-mode-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  color: var(--nc-text-secondary);
  letter-spacing: 0.08em;
}
.cm-mode-label {
  color: var(--nc-primary);
  font-weight: 600;
}

/* Segmented control */
.cm-seg {
  display: inline-flex;
  background: var(--nc-deep);
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  overflow: hidden;
}
.cm-seg-btn {
  background: transparent;
  border: none;
  color: var(--nc-text-secondary);
  padding: 6px 14px;
  font-family: inherit;
  font-size: 11px;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: background var(--nc-duration-fast), color var(--nc-duration-fast);
}
.cm-seg-btn + .cm-seg-btn { border-left: 1px solid var(--nc-border); }
.cm-seg-btn:hover:not(:disabled) { color: var(--nc-text-primary); background: var(--nc-elevated); }
.cm-seg-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.cm-seg-btn.active {
  color: var(--nc-text-primary);
  background: var(--nc-primary-subtle);
  box-shadow: inset 0 -2px 0 var(--nc-primary);
}

/* Status pill */
.cm-pill {
  padding: 3px 10px;
  border-radius: 10px;
  font-size: 10px;
  letter-spacing: 0.12em;
  border: 1px solid transparent;
}
.cm-pill-safe { background: var(--nc-success-subtle); color: var(--nc-success); border-color: var(--nc-success-subtle); }
.cm-pill-live { background: var(--nc-danger-subtle); color: var(--nc-danger); border-color: var(--nc-danger-subtle); }

/* Env flag chips */
.cm-flag { display: inline-flex; gap: 6px; align-items: center; font-size: 10px; }
.cm-flag-label { color: var(--nc-text-muted); }
.cm-flag b { font-weight: 400; letter-spacing: 0.08em; }
.cm-flag b.on  { color: var(--nc-success); }
.cm-flag b.off { color: var(--nc-text-muted); }  /* §FESUITE: a flag's value, not a disabled control: 5.7:1 (the disabled grey was 1.7:1) */

.cm-last { margin-left: auto; font-size: 10px; color: var(--nc-text-muted); }
.cm-last em { font-style: normal; color: var(--nc-text-secondary); }

/* Confirmation dialog */
.cm-confirm-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 2000;
}
.cm-confirm-dialog {
  background: var(--nc-overlay); border: 1px solid var(--nc-border-strong);
  border-radius: 10px; padding: 22px;
  max-width: 520px; width: 92%;
  color: var(--nc-text-primary);
  display: flex; flex-direction: column; gap: 12px;
  box-shadow: var(--nc-shadow-xl);
}
.cm-confirm-dialog h3 { margin: 0; font-size: 14px; letter-spacing: 0.08em; color: var(--nc-primary); text-transform: uppercase; }
.cm-confirm-dialog p  { margin: 0; font-size: 13px; line-height: 1.55; }
.cm-warn { color: var(--nc-danger); }
.cm-info { color: var(--nc-text-secondary); }
.cm-label { display: flex; flex-direction: column; gap: 6px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--nc-text-secondary); }
.cm-label textarea {
  background: var(--nc-deep); color: var(--nc-text-primary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px; resize: vertical;
}
.cm-confirm-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 4px; }
.cm-btn-ghost {
  background: transparent; color: var(--nc-text-secondary);
  border: 1px solid var(--nc-border);
  border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 12px;
}
.cm-btn-primary {
  background: var(--nc-primary); color: var(--nc-text-inverse);
  border: none; border-radius: 6px; padding: 8px 18px; cursor: pointer;
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600;
}
.cm-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; color: var(--nc-text-primary); background: var(--nc-deep); padding: 1px 5px; border-radius: 3px; }
</style>
