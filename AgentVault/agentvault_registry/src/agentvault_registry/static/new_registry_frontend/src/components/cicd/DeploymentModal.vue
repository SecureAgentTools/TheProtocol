<template>
  <Teleport to="body">
    <div class="cicd-modal-backdrop cicd-module" @click.self="$emit('close')">
      <div class="cicd-modal">
        <div class="cicd-modal-header">
          <span class="cicd-modal-title">▶ TRIGGER DEPLOYMENT</span>
          <button class="cicd-btn cicd-btn-ghost cicd-btn-icon" @click="$emit('close')">✕</button>
        </div>

        <div class="cicd-modal-body" style="display:flex;flex-direction:column;gap:18px;">

          <!-- Environment Selector -->
          <div>
            <label class="cicd-label">Target Environment</label>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
              <button
                v-for="env in environments"
                :key="env.value"
                class="cicd-env-btn"
                :class="{ active: form.environment === env.value }"
                @click="form.environment = env.value"
              >
                <span style="font-size:18px;">{{ env.icon }}</span>
                <span style="font-family:var(--cicd-font-mono);font-size:10px;font-weight:700;letter-spacing:0.06em;">{{ env.label }}</span>
              </button>
            </div>
          </div>

          <!-- Pipeline (optional) -->
          <div>
            <label class="cicd-label">Pipeline <span style="color:var(--cicd-text-muted);">(optional)</span></label>
            <select v-model="form.pipeline_id" class="cicd-input" style="cursor:pointer;">
              <option value="">— Manual deployment —</option>
              <option v-for="p in cicdStore.pipelines" :key="p.id" :value="p.id" :disabled="!p.webhook_url">
                {{ p.pipeline_name }}{{ p.webhook_url ? '' : ' (no webhook: cannot run)' }}
              </option>
            </select>
            <div v-if="!form.pipeline_id" style="margin-top:5px;font-size:11px;color:var(--cicd-text-muted);">
              Manual deployment records immediately as success.
            </div>
          </div>

          <!-- Version (optional) -->
          <div>
            <label class="cicd-label">Version <span style="color:var(--cicd-text-muted);">(optional)</span></label>
            <select v-model="form.version_id" class="cicd-input" style="cursor:pointer;">
              <option value="">— Use active version —</option>
              <option v-for="v in cicdStore.versions" :key="v.id" :value="v.id">
                v{{ v.version }}{{ v.is_active ? '  ★ active' : '' }}
              </option>
            </select>
          </div>

          <!-- Production warning -->
          <div v-if="form.environment === 'production'" style="
            background:rgba(255,77,106,0.08);
            border:1px solid rgba(255,77,106,0.25);
            border-radius:6px;
            padding:12px 14px;
            display:flex;gap:10px;
          ">
            <span style="color:var(--cicd-red);font-size:16px;flex-shrink:0;"><Icon name="mdi:alert" /></span>
            <div style="font-size:12px;color:#ff8a9a;line-height:1.5;">
              <strong>Production deployment.</strong> This may affect live users.
              Ensure all tests have passed before proceeding.
            </div>
          </div>
        </div>

        <div class="cicd-modal-footer">
          <button class="cicd-btn cicd-btn-ghost" @click="$emit('close')">Cancel</button>
          <button
            class="cicd-btn"
            :class="form.environment === 'production' ? 'cicd-btn-danger' : 'cicd-btn-primary'"
            :disabled="isDeploying"
            @click="submit"
          >
            <span v-if="isDeploying" style="animation:cicd-pulse 1s infinite;display:inline-block;">◌</span>
            <span v-else>▶</span>
            {{ isDeploying ? 'Deploying…' : `Deploy to ${form.environment}` }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref } from 'vue'
import { useCICDStore } from '@/stores/cicd'
import './tp-cicd.css'

const props = defineProps<{ agentDid: string }>()
const emit = defineEmits<{ close: []; deployed: [deployment: any] }>()

const cicdStore = useCICDStore()
const isDeploying = ref(false)

const form = ref({
  environment: 'dev' as 'dev' | 'staging' | 'production',
  pipeline_id: '',
  version_id: '',
})

const environments: { value: 'dev' | 'staging' | 'production'; label: string; icon: string }[] = [
  { value: 'dev',        label: 'DEV',        icon: '⌨' },
  { value: 'staging',    label: 'STAGING',    icon: '⬡' },
  { value: 'production', label: 'PRODUCTION', icon: '🌐' },
]

async function submit() {
  if (isDeploying.value) return
  if (form.value.environment === 'production') {
    if (!confirm('Deploy to PRODUCTION? This may affect live users.')) return
  }
  isDeploying.value = true
  try {
    const result = await cicdStore.triggerDeployment(props.agentDid, {
      environment: form.value.environment,
      pipeline_id: form.value.pipeline_id || undefined,
      version_id: form.value.version_id || undefined,
    })
    emit('deployed', result)
    emit('close')
  } catch {
    // §FESUITE 131: the store toasted the refusal; the door stays open to choose again
  } finally {
    isDeploying.value = false
  }
}
</script>

<style scoped>
.cicd-env-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  background: var(--cicd-surface-2);
  border: 1px solid var(--cicd-border);
  border-radius: var(--cicd-radius);
  color: var(--cicd-text-dim);
  cursor: pointer;
  transition: all 0.15s;
}
.cicd-env-btn:hover {
  border-color: var(--cicd-border-hover);
  color: var(--cicd-text);
}
.cicd-env-btn.active {
  background: var(--cicd-cyan-10);
  border-color: rgba(var(--nc-primary-rgb),0.4);
  color: var(--cicd-cyan);
}
</style>
