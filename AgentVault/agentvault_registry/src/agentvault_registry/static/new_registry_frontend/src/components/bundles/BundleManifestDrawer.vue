<!--
  §pass51 — BundleManifestDrawer
  Side-drawer that shows a bundle's manifest as formatted JSON + extracted
  README excerpt. Opens via BundleCard's "View" button.
-->
<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { ref, watch, computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useBundlesStore } from '@/stores/bundles'

const props = defineProps<{ bundleId: string | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const bundlesStore = useBundlesStore()
const loading = ref(false)
const manifest = ref<any | null>(null)
const error = ref('')

watch(() => props.bundleId, async (id) => {
  if (!id) { manifest.value = null; return }
  loading.value = true
  error.value = ''
  try {
    manifest.value = await bundlesStore.viewManifest(id)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load manifest'
  } finally {
    loading.value = false
  }
}, { immediate: true })

const exporter = computed(() => manifest.value?.exporter || {})
const contents = computed(() => manifest.value?.contents || {})
const audit = computed(() => manifest.value?.audit?.economic_state_snapshot_at_export)

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => !!props.bundleId, () => emit('close'))
</script>

<template>
  <Teleport to="body">
    <Transition name="bdl-drawer">
      <aside v-if="bundleId" class="bdl-drawer" @click.self="emit('close')">
        <div class="bdl-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="bdl-drawer-title" @click.stop>
          <header class="bdl-drawer-head">
            <div>
              <div class="bdl-drawer-eyebrow">MANIFEST</div>
              <h2 id="bdl-drawer-title" class="bdl-drawer-title">{{ manifest?.name || 'Loading…' }}</h2>
              <code class="bdl-drawer-id">{{ manifest?.bundle_id }}</code>
            </div>
            <button type="button" class="bdl-drawer-close" aria-label="Close" @click="emit('close')"><Icon name="mdi:close" /></button>
          </header>

          <section v-if="loading" class="bdl-drawer-loading">Loading…</section>
          <section v-else-if="error" class="bdl-drawer-error"><Icon name="mdi:alert" /> {{ error }}</section>
          <section v-else-if="manifest" class="bdl-drawer-body">

            <div class="bdl-d-block">
              <div class="bdl-d-label">Exporter</div>
              <div class="bdl-d-row"><b>Developer:</b> {{ exporter.developer_name }}</div>
              <div class="bdl-d-row"><b>Email:</b> {{ exporter.developer_email_redacted }}</div>
              <div class="bdl-d-row"><b>Registry:</b> {{ exporter.registry_origin }}</div>
              <div class="bdl-d-row"><b>Frame:</b> {{ exporter.frame }}</div>
              <div class="bdl-d-row"><b>Exported:</b> {{ exporter.exported_at }}</div>
            </div>

            <div class="bdl-d-block">
              <div class="bdl-d-label">Contents ({{ contents.total_agents || 0 }} agent{{ contents.total_agents === 1 ? '' : 's' }})</div>
              <div v-for="a in contents.agents || []" :key="a.source_did" class="bdl-d-agent">
                <strong>{{ a.name }}</strong>
                <code>{{ a.source_did }}</code>
                <span v-if="a.has_cicd" class="bdl-d-flag">+ CI/CD</span>
                <span v-if="a.flare_tier" class="bdl-d-flag">flare: {{ a.flare_tier }}</span>
              </div>
            </div>

            <div v-if="audit" class="bdl-d-block bdl-d-audit">
              <div class="bdl-d-label">Audit-only economic state (NOT restored)</div>
              <pre class="bdl-d-pre">{{ JSON.stringify(audit, null, 2) }}</pre>
            </div>

            <div class="bdl-d-block">
              <div class="bdl-d-label">Instructions</div>
              <pre class="bdl-d-pre">{{ JSON.stringify(manifest.instructions, null, 2) }}</pre>
            </div>

            <details class="bdl-d-block bdl-d-raw">
              <summary>Show raw manifest JSON</summary>
              <pre class="bdl-d-pre">{{ JSON.stringify(manifest, null, 2) }}</pre>
            </details>
          </section>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bdl-drawer { position: fixed; inset: 0; z-index: 10080; background: rgba(0,0,0,0.55); backdrop-filter: blur(4px); display: flex; justify-content: flex-end; font-family: 'IBM Plex Mono', monospace; }
.bdl-drawer-panel { width: 540px; max-width: 92vw; height: 100%; background: linear-gradient(180deg, rgba(14,24,40,0.99) 0%, rgba(8,14,24,1) 100%); border-left: 1px solid rgba(var(--nc-primary-rgb), 0.28); display: flex; flex-direction: column; overflow: hidden; box-shadow: -20px 0 80px rgba(0,0,0,0.7); }
.bdl-drawer-head { padding: 1.4rem 1.6rem 1rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.bdl-drawer-eyebrow { font-size: 0.6rem; letter-spacing: 0.22em; color: rgba(var(--nc-primary-rgb), 0.9); font-weight: 800; margin-bottom: 0.5rem; }
.bdl-drawer-title { font-size: 1.25rem; margin: 0; color: #fff; font-weight: 700; }
.bdl-drawer-id { font-size: 0.7rem; color: #6b7785; word-break: break-all; }
.bdl-drawer-close { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); cursor: pointer; color: #8b95a3; width: 32px; height: 32px; border-radius: 6px; display: grid; place-items: center; }
.bdl-drawer-close:hover { background: rgba(255,68,68,0.12); color: #ff5252; }
.bdl-drawer-close svg { width: 16px; height: 16px; }

.bdl-drawer-loading { padding: 2rem; color: #99a5b3; font-style: italic; }
.bdl-drawer-error { padding: 1rem 1.5rem; color: #ffb4b4; display: flex; align-items: center; gap: 0.5rem; }
.bdl-drawer-error svg { width: 16px; height: 16px; }
.bdl-drawer-body { padding: 1.2rem 1.6rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.2rem; }

.bdl-d-block { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 0.8rem 1rem; }
.bdl-d-label { font-size: 0.65rem; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 700; margin-bottom: 0.5rem; }
.bdl-d-row { font-size: 0.78rem; color: #e8eaed; padding: 2px 0; }
.bdl-d-row b { color: rgba(var(--nc-primary-rgb), 0.85); font-weight: 600; margin-right: 0.4rem; }
.bdl-d-agent { display: flex; flex-direction: column; gap: 2px; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.bdl-d-agent strong { font-size: 0.85rem; color: #e8eaed; }
.bdl-d-agent code { font-size: 0.7rem; color: #99a5b3; word-break: break-all; }
.bdl-d-flag { font-size: 0.65rem; color: rgba(0,255,136,0.85); }

.bdl-d-audit { background: rgba(251,191,36,0.05); border-color: rgba(251,191,36,0.2); }
.bdl-d-audit .bdl-d-label { color: rgba(251,191,36,0.85); }

.bdl-d-pre { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: #b0c0d0; background: rgba(0,0,0,0.4); padding: 0.6rem 0.8rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; max-height: 280px; overflow-y: auto; }

.bdl-d-raw summary { cursor: pointer; font-size: 0.74rem; color: #99a5b3; }

.bdl-drawer-enter-active, .bdl-drawer-leave-active { transition: opacity 0.2s; }
.bdl-drawer-enter-active .bdl-drawer-panel, .bdl-drawer-leave-active .bdl-drawer-panel { transition: transform 0.25s cubic-bezier(.2,.7,.3,1.1); }
.bdl-drawer-enter-from { opacity: 0; }
.bdl-drawer-leave-to { opacity: 0; }
.bdl-drawer-enter-from .bdl-drawer-panel { transform: translateX(100%); }
.bdl-drawer-leave-to .bdl-drawer-panel { transform: translateX(100%); }
</style>
