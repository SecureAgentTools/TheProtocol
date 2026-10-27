<template>
  <Teleport to="body">
    <div class="cicd-modal-backdrop cicd-module" @click.self="$emit('close')">
      <div class="cicd-modal cicd-modal-wide" style="max-height:90vh;display:flex;flex-direction:column;">

        <!-- Header -->
        <div class="cicd-modal-header" style="flex-shrink:0;">
          <span class="cicd-modal-title">⊞ PIPELINE TEMPLATES</span>
          <button class="cicd-btn cicd-btn-ghost cicd-btn-icon" @click="$emit('close')">✕</button>
        </div>

        <!-- Filter bar -->
        <div style="
          flex-shrink:0;
          padding:10px 22px;
          background:var(--cicd-surface-2);
          border-bottom:1px solid var(--cicd-border);
          display:flex;gap:10px;
        ">
          <input
            v-model="search"
            class="cicd-input"
            placeholder="Search templates…"
            style="flex:1;"
          />
          <select v-model="category" class="cicd-input" style="width:170px;cursor:pointer;">
            <option value="">All Categories</option>
            <option value="web">Web Applications</option>
            <option value="api">API Services</option>
            <option value="ml">Machine Learning</option>
            <option value="data">Data Processing</option>
            <option value="monitoring">Monitoring</option>
          </select>
        </div>

        <!-- Grid -->
        <div style="flex:1;overflow-y:auto;padding:18px 22px;">
          <div v-if="cicdStore.loadingStates.templates" class="cicd-empty">
            <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
            <div class="cicd-empty-title">Loading templates…</div>
          </div>
          <!-- §FESUITE (V0577): templates never read are not "No templates found" -->
          <ReadFailedNotice v-else-if="cicdStore.readFailed.templates && !cicdStore.templates.length"
            :retry="() => cicdStore.fetchTemplates()" data-testid="cicd-templates-failed" />
          <div v-else-if="!visible.length" class="cicd-empty">
            <div class="cicd-empty-icon">⊞</div>
            <div class="cicd-empty-title">No templates found</div>
          </div>
          <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">
            <div
              v-for="t in visible"
              :key="t.id"
              class="cicd-card template-tile"
              :class="{ selected: selected?.id === t.id }"
              @click="selected = t"
            >
              <!-- Top -->
              <div style="padding:14px 16px 10px;display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="flex:1;min-width:0;">
                  <div style="font-family:var(--cicd-font-mono);font-size:12px;font-weight:700;color:var(--cicd-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    {{ t.name }}
                  </div>
                  <div style="margin-top:4px;">
                    <span class="cicd-badge cicd-badge-inactive" style="font-size:9px;padding:1px 6px;">{{ t.category }}</span>
                  </div>
                </div>
                <div style="flex-shrink:0;text-align:right;margin-left:8px;">
                  <span v-if="t.price_teg > 0" style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-yellow);">{{ t.price_teg }} {{ localCurrency }}</span>
                  <span v-else class="cicd-badge cicd-badge-success" style="font-size:9px;padding:1px 6px;">FREE</span>
                </div>
              </div>
              <!-- Description -->
              <div style="padding:0 16px 10px;font-size:11px;color:var(--cicd-text-muted);line-height:1.5;">
                {{ t.description }}
              </div>
              <!-- Footer -->
              <div style="
                padding:8px 16px;
                border-top:1px solid var(--cicd-border);
                display:flex;justify-content:space-between;align-items:center;
              ">
                <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">
                  {{ t.usage_count ?? 0 }} uses
                </span>
                <button
                  class="cicd-btn cicd-btn-ghost cicd-btn-sm"
                  @click.stop="previewing = t"
                >preview</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="cicd-modal-footer" style="flex-shrink:0;justify-content:space-between;">
          <span style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-muted);">
            {{ selected ? `Selected: ${selected.name}` : 'Select a template' }}
          </span>
          <div style="display:flex;gap:8px;">
            <button class="cicd-btn cicd-btn-ghost" @click="$emit('close')">Cancel</button>
            <button
              class="cicd-btn cicd-btn-primary"
              :disabled="!selected"
              @click="use"
            >⊞ Use Template</button>
          </div>
        </div>

        <!-- Inline preview sub-modal -->
        <Teleport to="body">
          <div v-if="previewing" class="cicd-modal-backdrop cicd-module" style="z-index:1100;" @click.self="previewing = null">
            <div class="cicd-modal">
              <div class="cicd-modal-header">
                <span class="cicd-modal-title">{{ previewing.name }}</span>
                <button class="cicd-btn cicd-btn-ghost cicd-btn-icon" @click="previewing = null">✕</button>
              </div>
              <div class="cicd-modal-body">
                <div class="cicd-terminal" style="font-size:10px;">{{ JSON.stringify(previewing.template_config, null, 2) }}</div>
              </div>
              <div class="cicd-modal-footer">
                <button class="cicd-btn cicd-btn-ghost" @click="previewing = null">Close</button>
              </div>
            </div>
          </div>
        </Teleport>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useCICDStore } from '@/stores/cicd'
import { useCurrency } from '@/composables/useCurrency'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import './tp-cicd.css'

const emit = defineEmits<{ select: [template: any]; close: [] }>()
const cicdStore = useCICDStore()
// D6-835: a template's price is in this registry's unit (the loop's `t` is the template, not a translator)
const { localCurrency } = useCurrency()

const search = ref('')
const category = ref('')
const selected = ref<any>(null)
const previewing = ref<any>(null)

// Built-in fallback templates
const builtins = [
  {
    id: 'web-app', name: 'Web Application', description: 'Test → Build → Deploy with Docker and k8s.', category: 'web', price_teg: 0, usage_count: 412, created_at: new Date().toISOString(),
    template_config: { trigger_type: 'push', stages: [
      { id: 1, name: 'Test',  steps: [{ id:1, name:'Install', command:'npm install' }, { id:2, name:'Test', command:'npm test' }] },
      { id: 2, name: 'Build', steps: [{ id:3, name:'Build',   command:'npm run build' }, { id:4, name:'Docker', command:'docker build -t $IMAGE:$VERSION .' }] },
      { id: 3, name: 'Deploy',steps: [{ id:5, name:'Staging', command:'kubectl apply -f k8s/staging.yaml' }, { id:6, name:'Production', command:'kubectl apply -f k8s/prod.yaml', requires_approval:true }] },
    ]},
  },
  {
    id: 'api-svc', name: 'API Service', description: 'Unit tests, security scan, Helm chart deployment.', category: 'api', price_teg: 0, usage_count: 287, created_at: new Date().toISOString(),
    template_config: { trigger_type: 'tag', stages: [
      { id: 1, name: 'Quality', steps: [{ id:1, name:'Unit Tests', command:'pytest tests/unit' }, { id:2, name:'Security', command:'bandit -r src/' }] },
      { id: 2, name: 'Package', steps: [{ id:3, name:'Build', command:'docker build -t api:$VERSION .' }] },
      { id: 3, name: 'Deploy',  steps: [{ id:4, name:'Helm Dev', command:'helm upgrade --install api-dev ./charts' }, { id:5, name:'Helm Prod', command:'helm upgrade --install api-prod ./charts', requires_approval:true }] },
    ]},
  },
  {
    id: 'ml-train', name: 'ML Training Pipeline', description: 'Data prep → train → evaluate → deploy model container.', category: 'ml', price_teg: 0, usage_count: 94, created_at: new Date().toISOString(),
    template_config: { trigger_type: 'manual', stages: [
      { id: 1, name: 'Data Prep', steps: [{ id:1, name:'Fetch', command:'python fetch_data.py' }, { id:2, name:'Preprocess', command:'python preprocess.py' }] },
      { id: 2, name: 'Training',  steps: [{ id:3, name:'Train', command:'python train.py --epochs 100' }, { id:4, name:'Evaluate', command:'python evaluate.py' }] },
      { id: 3, name: 'Ship',      steps: [{ id:5, name:'Package', command:'docker build -f Dockerfile.model -t model:$VERSION .' }, { id:6, name:'Deploy', command:'kubectl apply -f k8s/model.yaml', requires_approval:true }] },
    ]},
  },
]

const pool = computed(() =>
  cicdStore.templates.length ? cicdStore.templates : builtins
)

const visible = computed(() => {
  let t = pool.value
  if (search.value) { const q = search.value.toLowerCase(); t = t.filter(x => x.name.toLowerCase().includes(q) || (x.description || '').toLowerCase().includes(q)) }
  if (category.value) t = t.filter(x => x.category === category.value)
  return t
})

function use() {
  if (selected.value) { emit('select', selected.value); emit('close') }
}

onMounted(() => { if (!cicdStore.templates.length) cicdStore.fetchTemplates() })
</script>

<style scoped>
.template-tile {
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}
.template-tile:hover { transform: translateY(-2px); border-color: var(--cicd-border-hover); }
.template-tile.selected {
  border-color: var(--cicd-cyan) !important;
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb),0.2);
}
</style>
