<template>
  <div class="cicd-module" style="display:flex;flex-direction:column;gap:16px;">

    <!-- Pipeline Config Row -->
    <div class="cicd-card" style="padding:16px 18px;">
      <div class="cicd-section-title" style="margin-bottom:12px;">Pipeline Configuration</div>
      <!-- §FESUITE — editing says so, and saving changes THAT pipeline (it used to create a second one) -->
      <div v-if="cicdStore.currentPipeline" class="cicd-editing" data-testid="cicd-editing">
        <span>{{ tp('pipelineBuilder.editing', 'Editing {name}', { name: cicdStore.currentPipeline.pipeline_name }) }}</span>
        <button type="button" class="cicd-btn cicd-btn-ghost cicd-btn-sm" @click="cicdStore.clearDraftPipeline()">{{ t('pipelineBuilder.stopEditing', 'Stop editing') }}</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div>
          <label class="cicd-label" for="cicd-pipeline-name">Pipeline Name *</label>
          <input
            id="cicd-pipeline-name"
            v-model="cicdStore.draftPipeline.pipeline_name"
            class="cicd-input cicd-input-mono"
            placeholder="e.g. main-pipeline"
          />
        </div>
        <div>
          <label class="cicd-label" for="cicd-trigger-type">Trigger Type</label>
          <select id="cicd-trigger-type" v-model="cicdStore.draftPipeline.trigger_type" class="cicd-input" style="cursor:pointer;">
            <option value="manual">Manual</option>
            <option value="push">On Push</option>
            <option value="tag">On Tag</option>
            <option value="schedule">Scheduled</option>
          </select>
        </div>
        <div v-if="cicdStore.draftPipeline.trigger_type !== 'manual'" style="grid-column:1/-1;">
          <label class="cicd-label" for="cicd-webhook-url">Webhook URL</label>
          <input
            id="cicd-webhook-url"
            v-model="cicdStore.draftPipeline.webhook_url"
            class="cicd-input cicd-input-mono"
            placeholder="https://your-ci-server.com/webhook"
          />
        </div>
      </div>
    </div>

    <!-- Stages -->
    <div class="cicd-card" style="padding:16px 18px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
        <div class="cicd-section-title">Pipeline Stages</div>
        <button class="cicd-btn cicd-btn-primary cicd-btn-sm" @click="cicdStore.addStage()">
          + Add Stage
        </button>
      </div>

      <!-- Empty -->
      <div v-if="!cicdStore.draftPipeline.stages.length" class="cicd-empty" style="padding:32px;">
        <div class="cicd-empty-icon">⬡</div>
        <div class="cicd-empty-title">No stages yet</div>
        <div class="cicd-empty-sub">Add a stage to start building your pipeline.</div>
        <button class="cicd-btn cicd-btn-primary" style="margin-top:10px;" @click="cicdStore.addStage()">+ Add First Stage</button>
      </div>

      <!-- Stage list -->
      <div v-else style="display:flex;flex-direction:column;gap:10px;">
        <div
          v-for="(stage, si) in cicdStore.draftPipeline.stages"
          :key="stage.id"
          class="cicd-stage"
        >
          <!-- Stage Header -->
          <div class="cicd-stage-header">
            <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;">
              <div class="cicd-stage-number">{{ si + 1 }}</div>
              <input
                v-model="stage.name"
                class="cicd-input cicd-input-mono"
                style="padding:4px 8px;font-size:12px;font-weight:600;flex:1;"
                placeholder="Stage name"
                :aria-label="tp('pipelineBuilder.stageNameAria', 'Stage {n} name', { n: si + 1 })"
                @click.stop
              />
            </div>
            <button
              type="button"
              class="cicd-btn cicd-btn-danger cicd-btn-sm"
              :aria-label="tp('pipelineBuilder.removeStage', 'Remove stage {n}', { n: si + 1 })"
              @click="cicdStore.removeStage(si)"
            ><span aria-hidden="true">✕</span></button>
          </div>

          <!-- Steps -->
          <div style="padding:10px 14px;display:flex;flex-direction:column;gap:8px;">
            <div
              v-for="(step, sti) in stage.steps"
              :key="step.id"
              class="cicd-step"
              style="background:var(--cicd-surface-3);border-radius:var(--cicd-radius);padding:10px 12px;"
            >
              <div style="flex:1;display:flex;flex-direction:column;gap:6px;">
                <div style="display:flex;gap:6px;align-items:center;">
                  <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);flex-shrink:0;">{{ sti + 1 }}.</span>
                  <input
                    v-model="step.name"
                    class="cicd-input"
                    style="flex:1;padding:4px 8px;font-size:12px;"
                    placeholder="Step name (e.g. Run Tests)"
                    :aria-label="tp('pipelineBuilder.stepNameAria', 'Step {n} name', { n: sti + 1 })"
                  />
                  <button type="button" class="cicd-btn cicd-btn-danger cicd-btn-icon" style="padding:3px 6px;"
                          :aria-label="tp('pipelineBuilder.removeStep', 'Remove step {n}', { n: sti + 1 })"
                          @click="cicdStore.removeStep(si, sti)"><span aria-hidden="true">✕</span></button>
                </div>
                <input
                  v-model="step.command"
                  class="cicd-input cicd-input-mono"
                  style="padding:4px 8px;font-size:11px;"
                  placeholder="Command (e.g. npm test)"
                  :aria-label="tp('pipelineBuilder.commandAria', 'Step {n} command', { n: sti + 1 })"
                />
                <!-- Advanced -->
                <div style="display:flex;gap:14px;">
                  <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
                    <input type="checkbox" v-model="step.requires_approval" style="accent-color:var(--cicd-yellow);" />
                    <span style="font-size:10px;color:var(--cicd-text-muted);font-family:var(--cicd-font-mono);">approval</span>
                  </label>
                  <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
                    <input type="checkbox" v-model="step.retry_on_failure" style="accent-color:var(--cicd-blue);" />
                    <span style="font-size:10px;color:var(--cicd-text-muted);font-family:var(--cicd-font-mono);">retry on fail</span>
                  </label>
                </div>
              </div>
            </div>

            <!-- Add step button -->
            <button
              class="cicd-btn cicd-btn-ghost"
              style="width:100%;border-style:dashed;font-size:11px;padding:7px;"
              @click="cicdStore.addStep(si)"
            >+ Add Step</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Actions -->
    <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;">
      <div style="display:flex;gap:8px;">
        <button class="cicd-btn cicd-btn-ghost" @click="showTemplates = true">⊞ Template</button>
        <button class="cicd-btn cicd-btn-ghost" @click="cicdStore.saveDraftToLocalStorage()">⬇ Save Draft</button>
      </div>
      <div style="display:flex;gap:8px;">
        <button
          class="cicd-btn cicd-btn-ghost"
          :disabled="!canSave"
          @click="showPreview = true"
        >◫ Preview</button>
        <button
          class="cicd-btn cicd-btn-primary"
          :disabled="!canSave || saving"
          @click="save"
        >
          <span v-if="saving" style="animation:cicd-pulse 1s infinite;display:inline-block;">◌</span>
          <span v-else>✓</span>
          {{ saving ? t('pipelineBuilder.saving', 'Saving…') : cicdStore.currentPipeline ? t('pipelineBuilder.saveChanges', 'Save changes') : t('pipelineBuilder.save', 'Save Pipeline') }}
        </button>
      </div>
    </div>

    <!-- Modals -->
    <PipelinePreviewModal
      v-if="showPreview"
      :pipeline="cicdStore.draftPipeline"
      @close="showPreview = false"
      @save="save"
    />
    <TemplateSelectionModal
      v-if="showTemplates"
      @select="applyTemplate"
      @close="showTemplates = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useCICDStore } from '@/stores/cicd'
import PipelinePreviewModal from './PipelinePreviewModal.vue'
import TemplateSelectionModal from './TemplateSelectionModal.vue'
import { useI18n } from '@/composables/useI18n'
import './tp-cicd.css'

const { t, tp } = useI18n()
const props = defineProps<{ agentDid: string }>()
const cicdStore = useCICDStore()

const showPreview = ref(false)
const showTemplates = ref(false)
const saving = ref(false)

const canSave = computed(() =>
  cicdStore.draftPipeline.pipeline_name &&
  cicdStore.draftPipeline.stages.length > 0 &&
  cicdStore.draftPipeline.stages.every(s => s.name && s.steps.length > 0)
)

function applyTemplate(template: any) {
  cicdStore.useTemplate(template)
  showTemplates.value = false
}

async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    if (cicdStore.currentPipeline) await cicdStore.saveEditedPipeline(props.agentDid)
    else await cicdStore.createPipeline(props.agentDid)
  } catch { /* the store said why in a toast */ } finally {
    saving.value = false
  }
}

onMounted(() => {
  cicdStore.initialize()
  cicdStore.fetchTemplates()
})
</script>
