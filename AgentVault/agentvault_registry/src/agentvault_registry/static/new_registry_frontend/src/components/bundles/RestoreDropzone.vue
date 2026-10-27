<!--
  §pass51 — RestoreDropzone
  Drop a .tpb (or legacy .json) file → restore.
-->
<script setup lang="ts">
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useBundlesStore } from '@/stores/bundles'

const emit = defineEmits<{ (e: 'restored', result: any): void }>()

const bundlesStore = useBundlesStore()
const isDragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const conflict = ref<'rename' | 'overwrite' | 'skip'>('rename')
const submitting = ref(false)
const result = ref<any | null>(null)
const error = ref('')

async function handleFile(file: File) {
  error.value = ''
  submitting.value = true
  try {
    const r = await bundlesStore.restoreFromUpload(file, {
      conflict_resolution: conflict.value,
      mode: 'copy',
      include_cicd: true,
    })
    result.value = r
    emit('restored', r)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Restore failed'
  } finally {
    submitting.value = false
  }
}

function onDrop(e: DragEvent) {
  isDragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) handleFile(f)
}
function onFileSelect(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) handleFile(f)
}
</script>

<template>
  <div class="bdl-restore">
    <div class="bdl-restore-controls">
      <label class="bdl-restore-label">Conflict mode:</label>
      <select v-model="conflict" class="bdl-restore-select">
        <option value="rename">Rename — create with new DID (recommended)</option>
        <option value="overwrite">Overwrite — replace existing (destructive)</option>
        <option value="skip">Skip — abort if exists</option>
      </select>
    </div>

    <div
      class="bdl-dropzone"
      :class="{ 'is-dragging': isDragging, 'is-submitting': submitting }"
      @drop.prevent="onDrop"
      @dragover.prevent
      @dragenter.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @click="fileInput?.click()"
    >
      <Icon name="mdi:cloud-upload-outline" class="bdl-dropzone-icon" />
      <div class="bdl-dropzone-text">
        <strong>{{ submitting ? 'Restoring…' : 'Drop a .tpb file here' }}</strong>
        <span>or click to browse — legacy .json exports also accepted</span>
      </div>
      <input ref="fileInput" type="file" accept=".tpb,.json" style="display:none" @change="onFileSelect" />
    </div>

    <div v-if="error" class="bdl-restore-error"><Icon name="mdi:alert" /> {{ error }}</div>

    <div v-if="result?.success" class="bdl-restore-result">
      <header><Icon name="mdi:check-circle" /> Bundle restored — {{ result.produced_agents.length }} new agent(s)</header>
      <div v-for="a in result.produced_agents" :key="a.did" class="bdl-restore-agent">
        <div class="bdl-restore-row"><span class="bdl-rk">DID:</span><code class="bdl-rv">{{ a.did }}</code></div>
        <div class="bdl-restore-row"><span class="bdl-rk">Client ID:</span><code class="bdl-rv">{{ a.client_id }}</code></div>
        <div class="bdl-restore-row"><span class="bdl-rk">Client Secret:</span><code class="bdl-rv bdl-rv--secret">{{ a.client_secret }}</code></div>
      </div>
      <p class="bdl-restore-note">Save the secret(s) — they are shown only once.</p>
      <div v-if="result.warnings?.length" class="bdl-restore-warnings">
        <strong>Warnings:</strong>
        <ul><li v-for="w in result.warnings" :key="w">{{ w }}</li></ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bdl-restore { display: flex; flex-direction: column; gap: 1rem; font-family: 'IBM Plex Mono', monospace; }
.bdl-restore-controls { display: flex; align-items: center; gap: 0.6rem; }
.bdl-restore-label { font-size: 0.7rem; color: rgba(var(--nc-primary-rgb), 0.7); text-transform: uppercase; letter-spacing: 0.16em; font-weight: 700; }
.bdl-restore-select { background: rgba(0,0,0,0.45); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 5px; padding: 6px 10px; font-family: inherit; font-size: 0.75rem; color: #e8eaed; cursor: pointer; }

.bdl-dropzone {
  border: 2px dashed rgba(var(--nc-primary-rgb), 0.3);
  border-radius: 10px;
  padding: 38px 24px;
  text-align: center;
  cursor: pointer;
  background: rgba(0,0,0,0.25);
  transition: border-color 0.18s, background 0.18s;
}
.bdl-dropzone:hover { border-color: rgba(var(--nc-primary-rgb), 0.7); background: rgba(var(--nc-primary-rgb), 0.04); }
.bdl-dropzone.is-dragging { border-color: var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb), 0.12); }
.bdl-dropzone.is-submitting { opacity: 0.6; pointer-events: none; }
.bdl-dropzone-icon { width: 48px; height: 48px; color: rgba(var(--nc-primary-rgb), 0.6); margin-bottom: 0.6rem; }
.bdl-dropzone-text { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; color: #e8eaed; }
.bdl-dropzone-text strong { font-size: 0.95rem; }
.bdl-dropzone-text span { color: #99a5b3; font-size: 0.72rem; }

.bdl-restore-error { display: flex; align-items: center; gap: 0.5rem; padding: 0.7rem 0.9rem; background: rgba(255,68,68,0.08); border: 1px solid rgba(255,68,68,0.3); color: #ffb4b4; border-radius: 6px; font-size: 0.78rem; }
.bdl-restore-error svg { width: 16px; height: 16px; }

.bdl-restore-result { padding: 1rem 1.1rem; background: rgba(0,255,136,0.06); border: 1px solid rgba(0,255,136,0.25); border-radius: 8px; }
.bdl-restore-result header { display: flex; align-items: center; gap: 0.4rem; font-weight: 700; color: #00ff88; font-size: 0.9rem; margin-bottom: 0.7rem; }
.bdl-restore-result svg { width: 18px; height: 18px; }
.bdl-restore-agent { background: rgba(0,0,0,0.3); padding: 0.7rem 0.9rem; border-radius: 6px; margin-bottom: 0.5rem; }
.bdl-restore-row { display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.72rem; padding: 2px 0; }
.bdl-rk { color: rgba(0,255,136,0.85); font-weight: 700; min-width: 120px; }
.bdl-rv { background: rgba(0,0,0,0.4); padding: 3px 8px; border-radius: 3px; color: #d0d8e0; word-break: break-all; }
.bdl-rv--secret { color: #fbbf24; }
.bdl-restore-note { font-style: italic; font-size: 0.7rem; color: #6b7785; margin: 0.5rem 0 0; }
.bdl-restore-warnings { margin-top: 0.7rem; padding-top: 0.7rem; border-top: 1px solid rgba(255,255,255,0.05); font-size: 0.72rem; color: rgba(245,158,11,0.8); }
.bdl-restore-warnings ul { margin: 0.3rem 0 0 1rem; padding: 0; }
</style>
