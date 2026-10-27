<template>
  <Teleport to="body">
    <div class="cicd-modal-backdrop cicd-module" @click.self="$emit('close')">
      <div class="cicd-modal cicd-modal-wide" style="max-height:90vh;display:flex;flex-direction:column;">

        <!-- Header -->
        <div class="cicd-modal-header" style="flex-shrink:0;">
          <span class="cicd-modal-title">⬡ PIPELINE PREVIEW</span>
          <button class="cicd-btn cicd-btn-ghost cicd-btn-icon" @click="$emit('close')">✕</button>
        </div>

        <!-- Scrollable body -->
        <div style="flex:1;overflow-y:auto;padding:20px 22px;display:flex;flex-direction:column;gap:20px;">

          <!-- Info card -->
          <div class="cicd-card" style="padding:14px 16px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div>
                <div class="cicd-label">Pipeline Name</div>
                <div style="font-family:var(--cicd-font-mono);font-size:13px;color:var(--cicd-text);">{{ pipeline.pipeline_name }}</div>
              </div>
              <div>
                <div class="cicd-label">Trigger</div>
                <div style="font-family:var(--cicd-font-mono);font-size:13px;color:var(--cicd-cyan);text-transform:uppercase;">{{ pipeline.trigger_type }}</div>
              </div>
              <div v-if="pipeline.webhook_url" style="grid-column:1/-1;">
                <div class="cicd-label">Webhook URL</div>
                <div class="cicd-webhook-block">{{ pipeline.webhook_url }}</div>
              </div>
            </div>
          </div>

          <!-- Flow diagram -->
          <div>
            <div class="cicd-section-title" style="margin-bottom:10px;">Pipeline Flow — {{ pipeline.stages.length }} Stage{{ pipeline.stages.length !== 1 ? 's' : '' }}</div>
            <div style="display:flex;align-items:center;gap:4px;overflow-x:auto;padding-bottom:6px;">
              <template v-for="(stage, i) in pipeline.stages" :key="stage.id">
                <div style="
                  min-width:140px;
                  background:var(--cicd-surface-2);
                  border:1px solid var(--cicd-border);
                  border-top:2px solid var(--cicd-cyan);
                  border-radius:var(--cicd-radius);
                  padding:10px 12px;
                ">
                  <div style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);margin-bottom:3px;">STAGE {{ i + 1 }}</div>
                  <div style="font-size:13px;color:var(--cicd-text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ stage.name }}</div>
                  <div style="font-size:10px;color:var(--cicd-text-muted);margin-top:3px;">{{ stage.steps.length }} step{{ stage.steps.length !== 1 ? 's' : '' }}</div>
                </div>
                <span v-if="i < pipeline.stages.length - 1" style="color:var(--cicd-text-muted);font-size:16px;flex-shrink:0;">→</span>
              </template>
            </div>
          </div>

          <!-- Stage details -->
          <div>
            <div class="cicd-section-title" style="margin-bottom:10px;">Stage Details</div>
            <div style="display:flex;flex-direction:column;gap:10px;">
              <div
                v-for="(stage, si) in pipeline.stages"
                :key="stage.id"
                class="cicd-stage"
              >
                <div class="cicd-stage-header">
                  <div style="display:flex;align-items:center;gap:10px;">
                    <div class="cicd-stage-number">{{ si + 1 }}</div>
                    <span style="font-family:var(--cicd-font-mono);font-size:12px;font-weight:600;color:var(--cicd-text);">{{ stage.name }}</span>
                  </div>
                  <span style="font-size:11px;color:var(--cicd-text-muted);">{{ stage.steps.length }} steps</span>
                </div>
                <div>
                  <div
                    v-for="(step, si2) in stage.steps"
                    :key="step.id"
                    class="cicd-step"
                  >
                    <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);flex-shrink:0;min-width:18px;">{{ si2 + 1 }}.</span>
                    <div style="flex:1;min-width:0;">
                      <div style="font-size:12px;color:var(--cicd-text);font-weight:500;">{{ step.name || 'Unnamed Step' }}</div>
                      <div style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-muted);margin-top:2px;word-break:break-all;">{{ step.command }}</div>
                      <div v-if="step.requires_approval || step.retry_on_failure" style="display:flex;gap:5px;margin-top:4px;">
                        <span v-if="step.requires_approval" class="cicd-badge cicd-badge-pending" style="font-size:9px;">approval required</span>
                        <span v-if="step.retry_on_failure" class="cicd-badge cicd-badge-running" style="font-size:9px;">retry on fail</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- YAML -->
          <div>
            <div class="cicd-section-title" style="margin-bottom:10px;">YAML Config</div>
            <div class="cicd-terminal" style="font-size:11px;">{{ yamlConfig }}</div>
          </div>
        </div>

        <div class="cicd-modal-footer" style="flex-shrink:0;">
          <button class="cicd-btn cicd-btn-ghost" @click="$emit('close')">Cancel</button>
          <button class="cicd-btn cicd-btn-primary" @click="$emit('save'); $emit('close')">
            ✓ Save Pipeline
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import './tp-cicd.css'

const props = defineProps<{
  pipeline: {
    pipeline_name: string
    stages: Array<{
      id: string | number
      name: string
      steps: Array<{
        id: string | number
        name: string
        command: string
        requires_approval?: boolean
        retry_on_failure?: boolean
      }>
    }>
    trigger_type: string
    webhook_url?: string
  }
}>()
const emit = defineEmits<{ close: []; save: [] }>()

const yamlConfig = computed(() => {
  const indent = (s: string, n: number) => s.split('\n').map(l => ' '.repeat(n) + l).join('\n')
  const stages = props.pipeline.stages.map(stage => {
    const steps = stage.steps.map(step =>
      `      - name: ${step.name || 'step'}\n        command: ${step.command}${step.requires_approval ? '\n        requires_approval: true' : ''}${step.retry_on_failure ? '\n        retry_on_failure: true' : ''}`
    ).join('\n')
    return `  - name: ${stage.name}\n    steps:\n${steps}`
  }).join('\n')
  return `name: ${props.pipeline.pipeline_name}
trigger: ${props.pipeline.trigger_type}${props.pipeline.webhook_url ? `\nwebhook: ${props.pipeline.webhook_url}` : ''}

stages:
${stages}`
})
</script>
