<template>
  <Teleport to="body">
    <div class="cicd-modal-backdrop cicd-module" @click.self="$emit('close')">
      <div class="cicd-modal" role="dialog" aria-modal="true" aria-labelledby="cicd-version-title">
        <div class="cicd-modal-header">
          <span id="cicd-version-title" class="cicd-modal-title">⊕ CREATE VERSION</span>
          <button type="button" class="cicd-btn cicd-btn-ghost cicd-btn-icon" aria-label="Close" @click="$emit('close')"><span aria-hidden="true">✕</span></button>
        </div>

        <div class="cicd-modal-body" style="display:flex;flex-direction:column;gap:16px;">
          <!-- Version number -->
          <div>
            <label class="cicd-label" for="cicd-version-number">Version Number *</label>
            <input
              id="cicd-version-number"
              v-model="form.version"
              class="cicd-input cicd-input-mono"
              placeholder="e.g. 1.0.0, 2.1.3-beta"
              @input="validateVersion"
            />
            <div v-if="versionError" style="margin-top:5px;font-size:11px;color:var(--cicd-red);">{{ versionError }}</div>
          </div>

          <!-- Release notes (backend field name is release_notes) -->
          <div>
            <label class="cicd-label" for="cicd-version-notes">Release Notes</label>
            <textarea
              id="cicd-version-notes"
              v-model="form.release_notes"
              class="cicd-input"
              rows="4"
              placeholder="Describe what's new in this version..."
              style="resize:vertical;"
            />
          </div>

          <!-- Flags row -->
          <div style="display:flex;gap:20px;">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
              <input
                type="checkbox"
                v-model="form.mark_as_stable"
                style="accent-color:var(--cicd-cyan);"
              />
              <span style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-dim);">
                Mark as stable
              </span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
              <input
                type="checkbox"
                v-model="form.auto_activate"
                style="accent-color:var(--cicd-cyan);"
              />
              <span style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-dim);">
                Activate immediately
              </span>
            </label>
          </div>
        </div>

        <div class="cicd-modal-footer">
          <button class="cicd-btn cicd-btn-ghost" @click="$emit('close')">Cancel</button>
          <button
            class="cicd-btn cicd-btn-primary"
            :disabled="!canCreate || isCreating"
            @click="submit"
          >
            <span v-if="isCreating" style="animation:cicd-pulse 1s infinite;display:inline-block;">◌</span>
            <span v-else>⊕</span>
            {{ isCreating ? 'Creating…' : 'Create Version' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { ref, computed } from 'vue'
import { useCICDStore } from '@/stores/cicd'
import './tp-cicd.css'

const props = defineProps<{ agentDid: string }>()
const emit = defineEmits<{ close: []; created: [version: any] }>()

const cicdStore = useCICDStore()

const form = ref({
  version: '',
  release_notes: '',
  mark_as_stable: false,
  auto_activate: false,
})
const versionError = ref('')
const isCreating = ref(false)

const canCreate = computed(() => form.value.version && !versionError.value)

function validateVersion() {
  const v = form.value.version
  if (!v) { versionError.value = ''; return }
  if (!/^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$/.test(v)) {
    versionError.value = 'Must follow semver (e.g. 1.0.0 or 2.0.0-beta.1)'
  } else {
    versionError.value = ''
  }
}

async function submit() {
  if (!canCreate.value || isCreating.value) return
  isCreating.value = true
  try {
    const result = await cicdStore.createVersion(props.agentDid, {
      version: form.value.version,
      release_notes: form.value.release_notes || undefined,
      // §FESUITE — the server reads a top-level is_stable (and defaults it to TRUE); inside config_snapshot it was
      // ignored, so "Mark as stable" changed nothing and every version read stable.
      is_stable: form.value.mark_as_stable,
    })
    if (form.value.auto_activate && result?.version_id) {
      await cicdStore.activateVersion(props.agentDid, result.version_id)
    }
    emit('created', result)
    emit('close')
  } finally {
    isCreating.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>
