<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CheckResult } from '@/services/api/types/diagnostics'

const props = defineProps<{
  result: CheckResult
}>()

defineEmits<{
  (e: 'remediate', actionId: string): void
}>()

const expanded = ref(false)

const statusColor = computed(() => {
  switch (props.result.status) {
    case 'ok': return '#00e5a0'
    case 'warn': return '#f5c842'
    case 'fail': return '#ff4d6a'
    default: return '#677a88'
  }
})

const statusGlyph = computed(() => {
  switch (props.result.status) {
    case 'ok': return '✓'
    case 'warn': return '⚠'
    case 'fail': return '✗'
    default: return '?'
  }
})

const detailsJson = computed(() => {
  try { return JSON.stringify(props.result.details, null, 2) }
  catch { return '{}' }
})
</script>

<template>
  <div class="cc-row" :data-status="result.status">
    <div class="cc-row-head" @click="expanded = !expanded">
      <span class="cc-row-glyph" :style="{ color: statusColor, borderColor: statusColor }">{{ statusGlyph }}</span>
      <div class="cc-row-text">
        <div class="cc-row-name">{{ result.check_id }}</div>
        <div class="cc-row-summary">{{ result.summary }}</div>
      </div>
      <span class="cc-row-latency">{{ result.latency_ms }}ms</span>
      <span class="cc-row-toggle">{{ expanded ? '▾' : '▸' }}</span>
    </div>
    <div v-if="expanded" class="cc-row-body">
      <div v-if="Object.keys(result.details || {}).length" class="cc-row-section">
        <div class="cc-row-section-title">DETAILS</div>
        <pre class="cc-row-pre">{{ detailsJson }}</pre>
      </div>
      <div v-if="result.evidence" class="cc-row-section">
        <div class="cc-row-section-title">EVIDENCE</div>
        <pre class="cc-row-pre cc-row-pre-evidence">{{ result.evidence }}</pre>
      </div>
      <div v-if="result.remediation" class="cc-row-remediation">
        <div class="cc-row-remediation-text">
          <div class="cc-row-remediation-action">Suggested: <code>{{ result.remediation.action_id }}</code></div>
          <div class="cc-row-remediation-desc">{{ result.remediation.description }}</div>
        </div>
        <button
          v-if="result.remediation.action_id !== 'manual-investigate'"
          class="cc-row-remediation-btn"
          @click.stop="$emit('remediate', result.remediation.action_id)"
        >Apply →</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cc-row { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; overflow: hidden; }
.cc-row[data-status="fail"] { border-color: rgba(255,23,68,0.45); background: rgba(255,23,68,0.04); }
.cc-row[data-status="warn"] { border-color: rgba(255,179,0,0.4); background: rgba(255,179,0,0.04); }
.cc-row[data-status="ok"]   { border-color: rgba(0,200,83,0.25); }

.cc-row-head { display: grid; grid-template-columns: 24px 1fr auto auto; gap: 12px; align-items: center; padding: 10px 12px; cursor: pointer; }
.cc-row-glyph {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 6px;
  border: 1px solid; font-size: 13px; font-weight: 700;
}
.cc-row-name { font-size: 13px; font-weight: 600; color: #f4f6f8; font-family: 'IBM Plex Mono', monospace; }
.cc-row-summary { font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 2px; }
.cc-row-latency { font-size: 11px; color: rgba(255,255,255,0.5); font-family: 'IBM Plex Mono', monospace; }
.cc-row-toggle { font-size: 12px; color: rgba(255,255,255,0.4); }

.cc-row-body { padding: 0 14px 14px 48px; display: flex; flex-direction: column; gap: 12px; }
.cc-row-section-title { font-size: 10px; letter-spacing: 0.18em; color: rgba(255,255,255,0.45); margin-bottom: 4px; }
.cc-row-pre {
  margin: 0; padding: 10px 12px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.05);
  border-radius: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #d4dee5;
  max-height: 240px; overflow: auto; white-space: pre-wrap; word-break: break-word;
}
.cc-row-pre-evidence { color: #b9c4cc; max-height: 320px; }

.cc-row-remediation {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 6px;
  background: rgba(0,176,255,0.06); border: 1px solid rgba(0,176,255,0.2);
}
.cc-row-remediation-text { flex: 1; }
.cc-row-remediation-action { font-size: 11px; color: #6dd0ff; font-family: 'IBM Plex Mono', monospace; }
.cc-row-remediation-action code { background: rgba(255,255,255,0.06); padding: 1px 5px; border-radius: 3px; }
.cc-row-remediation-desc { font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 3px; }
.cc-row-remediation-btn {
  background: rgba(0,176,255,0.15); border: 1px solid rgba(0,176,255,0.5);
  color: #6dd0ff; padding: 6px 14px; border-radius: 6px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.06em;
}
.cc-row-remediation-btn:hover { background: rgba(0,176,255,0.25); }
</style>
