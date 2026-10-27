<!--
  §pass51 — NewBundleModal
  Pick agents from a list, pick kind/visibility, name + description, create.
-->
<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { ref, computed, watch, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useBundlesStore } from '@/stores/bundles'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', result: any): void }>()

const bundlesStore = useBundlesStore()
const authStore = useAuthStore()
const uiStore = useUIStore()

const name = ref('')
const description = ref('')
const kind = ref<'snapshot' | 'template' | 'migration'>('snapshot')
const visibility = ref<'private' | 'org' | 'public'>('private')
const selectedDids = ref<string[]>([])
const submitting = ref(false)
const error = ref('')

const availableAgents = computed(() => authStore.availableAgents || [])
const canSubmit = computed(() => selectedDids.value.length > 0 && !submitting.value)

watch(() => props.show, async (open) => {
  if (open) {
    name.value = ''
    description.value = ''
    kind.value = 'snapshot'
    visibility.value = 'private'
    selectedDids.value = []
    error.value = ''
    if (availableAgents.value.length === 0) await authStore.fetchAvailableAgents()
  }
})

function toggleDid(did: string) {
  const i = selectedDids.value.indexOf(did)
  if (i >= 0) selectedDids.value.splice(i, 1)
  else selectedDids.value.push(did)
}

function goToQuickDeploy() {
  emit('close')
  // QuickAgentModal is mounted globally via DashboardLayout; uiStore opens it
  uiStore.openQuickAgentModal?.()
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  submitting.value = true
  try {
    const result = await bundlesStore.create({
      agent_dids: selectedDids.value,
      kind: kind.value,
      visibility: visibility.value,
      name: name.value || undefined,
      description: description.value || undefined,
      sign: true,
    })
    emit('created', result)
    emit('close')
  } catch (e: any) {
    const d = e?.response?.data?.detail
    error.value = (typeof d === 'string' && d) || (d ? JSON.stringify(d).slice(0, 240) : '') || e?.message || 'Failed to create bundle'
  } finally {
    submitting.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, () => emit('close'), () => !submitting.value)
</script>

<template>
  <Teleport to="body">
    <Transition name="bdl-fade">
      <div v-if="show" class="bdl-scrim" @click.self="emit('close')">
        <Transition name="bdl-pop">
          <div v-if="show" class="bdl-modal" role="dialog" aria-modal="true" aria-labelledby="bdl-new-title" @click.stop>
            <header class="bdl-modal-head">
              <div>
                <div class="bdl-modal-eyebrow">NEW BUNDLE</div>
                <h2 id="bdl-new-title" class="bdl-modal-title">Create a bundle</h2>
                <p class="bdl-modal-subtitle">
                  Snapshots are private backups. Templates are blueprints others can fork.
                  Migrations are one-shot moves to another registry.
                </p>
              </div>
              <button type="button" class="bdl-modal-close" aria-label="Close" @click="emit('close')"><Icon name="mdi:close" /></button>
            </header>

            <section class="bdl-modal-body">
              <div class="bdl-field">
                <span id="bdl-kind-label" class="bdl-label">Bundle kind</span>
                <div class="bdl-kind-row" role="group" aria-labelledby="bdl-kind-label">
                  <button type="button" class="bdl-kind-btn" :class="{ 'is-active': kind === 'snapshot' }" :aria-pressed="kind === 'snapshot'" @click="kind = 'snapshot'">
                    <Icon name="mdi:content-save-outline" /> Snapshot
                  </button>
                  <button type="button" class="bdl-kind-btn" :class="{ 'is-active': kind === 'template' }" :aria-pressed="kind === 'template'" @click="kind = 'template'">
                    <Icon name="mdi:file-document-multiple-outline" /> Template
                  </button>
                  <button type="button" class="bdl-kind-btn" :class="{ 'is-active': kind === 'migration' }" :aria-pressed="kind === 'migration'" @click="kind = 'migration'">
                    <Icon name="mdi:swap-horizontal-bold" /> Migration
                  </button>
                </div>
              </div>

              <div class="bdl-field">
                <label class="bdl-label" for="bdl-new-name">Name <span class="bdl-opt">optional</span></label>
                <input id="bdl-new-name" v-model="name" class="bdl-input" placeholder="e.g., Weekly backup 2026-05-20" maxlength="160" />
              </div>

              <div class="bdl-field">
                <label class="bdl-label" for="bdl-new-description">Description <span class="bdl-opt">optional</span></label>
                <input id="bdl-new-description" v-model="description" class="bdl-input" placeholder="What is this for?" maxlength="240" />
              </div>

              <div class="bdl-field">
                <label class="bdl-label" for="bdl-new-visibility">Visibility</label>
                <select id="bdl-new-visibility" v-model="visibility" class="bdl-input">
                  <option value="private">Private (only you)</option>
                  <option value="org">Org-scoped</option>
                  <option value="public">Public (marketplace)</option>
                </select>
              </div>

              <div class="bdl-field">
                <span id="bdl-agents-label" class="bdl-label">Pick agents <span class="bdl-opt">at least 1</span></span>
                <div class="bdl-agent-list" role="group" aria-labelledby="bdl-agents-label">
                  <div v-if="!availableAgents.length" class="bdl-empty bdl-empty--rich">
                    <Icon name="mdi:robot-happy-outline" class="bdl-empty-icon" />
                    <p class="bdl-empty-h">You don't have any agents yet</p>
                    <p class="bdl-empty-sub">Bundle creation needs at least one agent to package. Spin one up in 30 seconds, then come back.</p>
                    <button type="button" class="bdl-empty-cta" @click="goToQuickDeploy">
                      <Icon name="mdi:rocket-launch" /> Quick deploy an agent
                    </button>
                  </div>
                  <button v-for="a in availableAgents" :key="a.did" type="button" class="bdl-agent-row" :class="{ 'is-selected': selectedDids.includes(a.did) }" :aria-pressed="selectedDids.includes(a.did)" :data-did="a.did" @click="toggleDid(a.did)">
                    <Icon :name="selectedDids.includes(a.did) ? 'mdi:check-circle' : 'mdi:robot'" />
                    <span class="bdl-agent-name">{{ a.name || 'Unnamed' }}</span>
                    <span class="bdl-agent-did">{{ a.did.slice(0, 32) }}…</span>
                  </button>
                </div>
              </div>

              <p v-if="error" class="bdl-error"><Icon name="mdi:alert" /> {{ error }}</p>
            </section>

            <footer class="bdl-modal-foot">
              <button class="bdl-btn bdl-btn--ghost" @click="emit('close')" :disabled="submitting">Cancel</button>
              <button class="bdl-btn bdl-btn--primary" :disabled="!canSubmit" @click="submit">
                <Icon name="mdi:rocket-launch" />
                <span>{{ submitting ? 'Creating…' : 'Create bundle' }}</span>
              </button>
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bdl-scrim {
  position: fixed; inset: 0; z-index: 10095;
  background: radial-gradient(ellipse at center, rgba(2,6,12,0.78) 0%, rgba(0,0,0,0.88) 100%);
  backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center; padding: 1.5rem;
  font-family: 'IBM Plex Mono', monospace;
}
.bdl-modal {
  width: 100%; max-width: 620px; max-height: 92vh;
  background: linear-gradient(180deg, rgba(14,24,40,0.97) 0%, rgba(8,14,24,0.99) 100%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  border-radius: 12px;
  box-shadow: 0 32px 96px rgba(0,0,0,0.78), 0 0 0 1px rgba(var(--nc-primary-rgb), 0.06), 0 0 80px rgba(var(--nc-primary-rgb), 0.10);
  display: flex; flex-direction: column; overflow: hidden;
  color: #e8eaed;
}
.bdl-modal-head { padding: 1.4rem 1.6rem 1rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.bdl-modal-eyebrow { font-size: 0.6rem; letter-spacing: 0.22em; color: rgba(var(--nc-primary-rgb), 0.9); font-weight: 800; margin-bottom: 0.5rem; }
.bdl-modal-title { font-size: 1.4rem; margin: 0; color: #fff; font-weight: 700; line-height: 1.2; }
.bdl-modal-subtitle { font-size: 0.78rem; color: #99a5b3; line-height: 1.5; margin: 0.5rem 0 0; }
.bdl-modal-close { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); cursor: pointer; color: #8b95a3; width: 32px; height: 32px; border-radius: 6px; display: grid; place-items: center; }
.bdl-modal-close:hover { background: rgba(255,68,68,0.12); color: #ff5252; border-color: rgba(255,82,82,0.4); }
.bdl-modal-close svg { width: 16px; height: 16px; }

.bdl-modal-body { padding: 1.2rem 1.6rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1rem; }
.bdl-field { display: flex; flex-direction: column; gap: 0.4rem; }
.bdl-label { font-size: 0.65rem; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 700; }
.bdl-opt { color: #6b7785; font-weight: 500; letter-spacing: 0.08em; }
.bdl-input { background: rgba(0,0,0,0.45); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 6px; padding: 0.7rem 0.9rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: #e8eaed; outline: none; transition: border-color 0.18s, background 0.18s; }
.bdl-input:focus { border-color: rgba(var(--nc-primary-rgb), 0.75); background: rgba(0,0,0,0.6); }
select.bdl-input { padding: 0.6rem 0.9rem; cursor: pointer; }

.bdl-kind-row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.bdl-kind-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  color: rgba(var(--nc-primary-rgb), 0.85); font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 600;
  padding: 8px 14px; border-radius: 6px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s;
}
.bdl-kind-btn svg { width: 14px; height: 14px; }
.bdl-kind-btn:hover { background: rgba(var(--nc-primary-rgb), 0.14); }
.bdl-kind-btn.is-active { background: rgba(var(--nc-primary-rgb), 0.22); border-color: rgba(var(--nc-primary-rgb), 0.7); color: var(--nc-primary); box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.18); }

.bdl-agent-list { display: flex; flex-direction: column; gap: 0.3rem; max-height: 240px; overflow-y: auto; padding-right: 4px; }
.bdl-empty { color: #6b7785; font-size: 0.78rem; padding: 1rem; text-align: center; border: 1px dashed rgba(var(--nc-primary-rgb), 0.18); border-radius: 6px; }
.bdl-empty--rich { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 1.4rem 1rem; background: rgba(var(--nc-primary-rgb), 0.03); }
.bdl-empty-icon { width: 36px; height: 36px; color: rgba(var(--nc-primary-rgb), 0.55); margin-bottom: 0.2rem; }
.bdl-empty-h { color: #e8eaed; font-size: 0.92rem; font-weight: 700; margin: 0; }
.bdl-empty-sub { color: #99a5b3; font-size: 0.74rem; max-width: 38ch; margin: 0; line-height: 1.5; }
.bdl-empty-cta { display: inline-flex; align-items: center; gap: 0.4rem; margin-top: 0.5rem; background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%); border: 1px solid var(--nc-primary, #00d2d2); color: #04141f; font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 0.76rem; padding: 8px 14px; border-radius: 5px; cursor: pointer; }
.bdl-empty-cta:hover { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); }
.bdl-empty-cta svg { width: 13px; height: 13px; }
.bdl-agent-row { display: flex; align-items: center; gap: 0.6rem; padding: 8px 12px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 5px; cursor: pointer; text-align: left; transition: background 0.15s, border-color 0.15s; }
.bdl-agent-row svg { width: 14px; height: 14px; color: rgba(148,163,184,0.6); flex-shrink: 0; }
.bdl-agent-row:hover { background: rgba(var(--nc-primary-rgb), 0.06); border-color: rgba(var(--nc-primary-rgb), 0.18); }
.bdl-agent-row.is-selected { background: rgba(var(--nc-primary-rgb), 0.14); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.bdl-agent-row.is-selected svg { color: var(--nc-primary, #00d2d2); }
.bdl-agent-name { flex: 1; font-size: 0.82rem; color: #e8eaed; font-weight: 600; }
.bdl-agent-did { font-size: 0.65rem; color: rgba(148,163,184,0.55); }

.bdl-error { display: flex; align-items: center; gap: 0.5rem; margin: 0; padding: 0.7rem 0.9rem; background: rgba(255,68,68,0.08); border: 1px solid rgba(255,68,68,0.3); color: #ffb4b4; border-radius: 6px; font-size: 0.78rem; }
.bdl-error svg { width: 16px; height: 16px; color: #ff8c8c; }

.bdl-modal-foot { padding: 1.1rem 1.6rem 1.3rem; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1); background: linear-gradient(180deg, rgba(0,0,0,0.16) 0%, rgba(0,0,0,0.22) 100%); display: flex; gap: 0.6rem; justify-content: flex-end; }
.bdl-btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.6rem 1.1rem; border-radius: 5px; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.08em; }
.bdl-btn--ghost { background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.8); }
.bdl-btn--ghost:hover { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.55); background: rgba(var(--nc-primary-rgb), 0.05); }
.bdl-btn--primary { background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%); color: #04141f; border: 1px solid var(--nc-primary, #00d2d2); }
.bdl-btn--primary:hover:not(:disabled) { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); }
.bdl-btn--primary:disabled { opacity: 0.4; cursor: not-allowed; }
.bdl-btn svg { width: 14px; height: 14px; }

.bdl-fade-enter-active, .bdl-fade-leave-active { transition: opacity 0.2s; }
.bdl-fade-enter-from, .bdl-fade-leave-to { opacity: 0; }
.bdl-pop-enter-active { transition: transform 0.26s cubic-bezier(.2,.7,.3,1.25), opacity 0.18s; }
.bdl-pop-leave-active { transition: transform 0.16s ease, opacity 0.14s; }
.bdl-pop-enter-from { transform: translateY(14px) scale(0.96); opacity: 0; }
.bdl-pop-leave-to { transform: translateY(8px) scale(0.98); opacity: 0; }
</style>
