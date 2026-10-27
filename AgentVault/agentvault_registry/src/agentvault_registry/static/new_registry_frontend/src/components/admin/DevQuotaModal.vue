<!--
  §pass51 P48 — Per-dev bundle quota editor.
  Opened from AdminDevelopers row "Quota" button. Reads + writes
  /admin/developers/{id}/quota (admin_platform gated server-side).
-->
<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { apiClient } from '@/services/api/client'
import { useUIStore } from '@/stores/ui'

const props = defineProps<{ show: boolean; developerId: number | null; developerEmail?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const ui = useUIStore()

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const quota = ref<any | null>(null)

watch(() => props.show, async (open) => {
  if (open && props.developerId) {
    loading.value = true
    error.value = ''
    quota.value = null
    try {
      const { data } = await apiClient.get(`/admin/developers/${props.developerId}/quota`)
      quota.value = data
    } catch (e: any) {
      error.value = e?.response?.data?.detail || 'Failed to load quota'
    } finally {
      loading.value = false
    }
  }
})

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function save() {
  if (!props.developerId || !quota.value) return
  saving.value = true
  error.value = ''
  try {
    const payload = {
      max_bundle_count: Number(quota.value.max_bundle_count),
      max_bundle_total_bytes: Number(quota.value.max_bundle_total_bytes),
      max_individual_bundle_bytes: Number(quota.value.max_individual_bundle_bytes),
      bundle_create_rate_per_day: Number(quota.value.bundle_create_rate_per_day),
      custom_quota_reason: quota.value.custom_quota_reason || '',
    }
    await apiClient.patch(`/admin/developers/${props.developerId}/quota`, payload)
    ui.showSuccess?.(`Quota updated for dev #${props.developerId}`)
    emit('close')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Save failed'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dq-fade">
      <div v-if="show" class="dq-scrim" @click.self="emit('close')">
        <Transition name="dq-pop">
          <div v-if="show" class="dq-modal" @click.stop>
            <header class="dq-head">
              <div>
                <div class="dq-eyebrow">BUNDLE QUOTA</div>
                <h2 class="dq-title">dev #{{ developerId }}{{ developerEmail ? ` — ${developerEmail}` : '' }}</h2>
              </div>
              <button class="dq-close" @click="emit('close')"><Icon name="mdi:close" /></button>
            </header>
            <section v-if="loading" class="dq-body dq-body--center">Loading…</section>
            <section v-else-if="quota" class="dq-body">
              <div v-if="quota.is_default" class="dq-alert dq-alert--info">
                <Icon name="mdi:information" />
                No custom quota set — showing defaults. Saving will create a row.
              </div>
              <div v-if="quota.current_usage" class="dq-usage">
                <div class="dq-usage-row"><span>Current bundle count:</span><strong>{{ quota.current_usage.bundle_count }} / {{ quota.max_bundle_count }}</strong></div>
                <div class="dq-usage-row"><span>Current storage used:</span><strong>{{ fmtBytes(quota.current_usage.total_bytes) }} / {{ fmtBytes(quota.max_bundle_total_bytes) }}</strong></div>
              </div>
              <label class="dq-field">
                <span class="dq-label">Max bundle count</span>
                <input v-model.number="quota.max_bundle_count" type="number" min="0" max="100000" class="dq-input" />
              </label>
              <label class="dq-field">
                <span class="dq-label">Max total storage (bytes)</span>
                <input v-model.number="quota.max_bundle_total_bytes" type="number" min="0" class="dq-input" />
                <span class="dq-hint">{{ fmtBytes(quota.max_bundle_total_bytes) }}</span>
              </label>
              <label class="dq-field">
                <span class="dq-label">Max individual bundle (bytes)</span>
                <input v-model.number="quota.max_individual_bundle_bytes" type="number" min="0" class="dq-input" />
                <span class="dq-hint">{{ fmtBytes(quota.max_individual_bundle_bytes) }}</span>
              </label>
              <label class="dq-field">
                <span class="dq-label">Bundle create rate per day</span>
                <input v-model.number="quota.bundle_create_rate_per_day" type="number" min="0" max="10000" class="dq-input" />
              </label>
              <label class="dq-field">
                <span class="dq-label">Reason for custom quota (optional)</span>
                <textarea v-model="quota.custom_quota_reason" rows="2" maxlength="500" class="dq-input" placeholder="e.g., Enterprise customer / verified partner / ops bump"></textarea>
              </label>
              <p v-if="error" class="dq-alert dq-alert--danger"><Icon name="mdi:alert" /> {{ error }}</p>
            </section>
            <footer class="dq-foot">
              <button class="dq-btn dq-btn--ghost" @click="emit('close')" :disabled="saving">Cancel</button>
              <button class="dq-btn dq-btn--primary" @click="save" :disabled="saving || !quota">
                <Icon name="mdi:content-save" />
                <span>{{ saving ? 'Saving…' : 'Save quota' }}</span>
              </button>
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dq-scrim { position: fixed; inset: 0; z-index: 10095; background: radial-gradient(ellipse at center, rgba(2,6,12,0.78) 0%, rgba(0,0,0,0.88) 100%); backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; padding: 1.5rem; font-family: 'IBM Plex Mono', monospace; }
.dq-modal { width: 100%; max-width: 540px; max-height: 92vh; background: linear-gradient(180deg, rgba(14,24,40,0.97) 0%, rgba(8,14,24,0.99) 100%); border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 12px; box-shadow: 0 32px 96px rgba(0,0,0,0.78); display: flex; flex-direction: column; overflow: hidden; color: #e8eaed; }
.dq-head { padding: 1.4rem 1.6rem 1rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.dq-eyebrow { font-size: 0.6rem; letter-spacing: 0.22em; color: rgba(var(--nc-primary-rgb), 0.9); font-weight: 800; margin-bottom: 0.5rem; }
.dq-title { font-size: 1.2rem; margin: 0; color: #fff; font-weight: 700; word-break: break-all; }
.dq-close { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); cursor: pointer; color: #8b95a3; width: 32px; height: 32px; border-radius: 6px; display: grid; place-items: center; }
.dq-close:hover { background: rgba(255,68,68,0.12); color: #ff5252; }
.dq-close svg { width: 16px; height: 16px; }

.dq-body { padding: 1.2rem 1.6rem; overflow-y: auto; display: flex; flex-direction: column; gap: 0.85rem; }
.dq-body--center { text-align: center; color: #99a5b3; font-style: italic; padding: 3rem; }
.dq-alert { display: flex; align-items: center; gap: 0.45rem; padding: 0.55rem 0.75rem; border-radius: 5px; font-size: 0.74rem; }
.dq-alert svg { width: 14px; height: 14px; flex-shrink: 0; }
.dq-alert--info { background: rgba(96, 165, 250, 0.08); border: 1px solid rgba(96, 165, 250, 0.28); color: rgba(96, 165, 250, 0.9); }
.dq-alert--danger { background: rgba(255,68,68,0.08); border: 1px solid rgba(255,68,68,0.3); color: #ffb4b4; }
.dq-usage { background: rgba(0,0,0,0.3); border: 1px solid rgba(var(--nc-primary-rgb), 0.18); border-radius: 6px; padding: 0.6rem 0.85rem; }
.dq-usage-row { display: flex; justify-content: space-between; font-size: 0.78rem; color: #d0d8e0; padding: 3px 0; }
.dq-usage-row strong { color: var(--nc-primary, #00d2d2); font-weight: 700; }
.dq-field { display: flex; flex-direction: column; gap: 0.3rem; }
.dq-label { font-size: 0.65rem; letter-spacing: 0.16em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 700; }
.dq-input { background: rgba(0,0,0,0.45); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 5px; padding: 8px 10px; font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; color: #e8eaed; outline: none; transition: border-color 0.18s; }
.dq-input:focus { border-color: rgba(var(--nc-primary-rgb), 0.7); }
textarea.dq-input { resize: vertical; min-height: 50px; }
.dq-hint { font-size: 0.7rem; color: rgba(var(--nc-primary-rgb), 0.6); font-style: italic; }

.dq-foot { padding: 1rem 1.6rem 1.2rem; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1); background: rgba(0,0,0,0.18); display: flex; gap: 0.5rem; justify-content: flex-end; }
.dq-btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.55rem 1rem; border-radius: 5px; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.06em; }
.dq-btn--ghost { background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.8); }
.dq-btn--ghost:hover { background: rgba(var(--nc-primary-rgb), 0.06); color: var(--nc-primary); }
.dq-btn--primary { background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%); border: 1px solid var(--nc-primary, #00d2d2); color: #04141f; }
.dq-btn--primary:hover:not(:disabled) { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); }
.dq-btn--primary:disabled { opacity: 0.5; cursor: not-allowed; }
.dq-btn svg { width: 13px; height: 13px; }

.dq-fade-enter-active, .dq-fade-leave-active { transition: opacity 0.18s; }
.dq-fade-enter-from, .dq-fade-leave-to { opacity: 0; }
.dq-pop-enter-active { transition: transform 0.26s cubic-bezier(.2,.7,.3,1.25), opacity 0.18s; }
.dq-pop-leave-active { transition: transform 0.16s ease, opacity 0.14s; }
.dq-pop-enter-from { transform: translateY(14px) scale(0.96); opacity: 0; }
.dq-pop-leave-to { transform: translateY(8px) scale(0.98); opacity: 0; }
</style>
