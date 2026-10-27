<script setup lang="ts">
import type { CheckResult, TargetSummary } from '@/services/api/types/diagnostics'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

withDefaults(defineProps<{
  alerts: { target: TargetSummary; result: CheckResult }[]
  // §MCPTEST30 (V0561): false when no check has run on any target: "No active alerts" over nothing measured read as
  // an all-clear
  measured?: boolean
}>(), { measured: true })

defineEmits<{
  (e: 'open-target', operator_id: string): void
}>()
</script>

<template>
  <div class="cc-alerts">
    <div class="cc-alerts-head">
      <span class="cc-alerts-title">{{ t('commandCenterView.alerts.title', 'Active alerts') }}</span>
      <span class="cc-alerts-count">{{ alerts.length }}</span>
    </div>
    <div v-if="!alerts.length && !measured" class="cc-alerts-empty" data-testid="cc-alerts-unmeasured">{{ t('commandCenterView.alerts.unmeasured', 'Nothing measured yet') }}</div>
    <div v-else-if="!alerts.length" class="cc-alerts-empty">{{ t('commandCenterView.alerts.none', 'No active alerts') }}</div>
    <div v-else class="cc-alerts-list">
      <div
        v-for="(alert, i) in alerts.slice(0, 8)"
        :key="`${alert.target.operator_id}-${alert.result.check_id}-${i}`"
        class="cc-alert-row"
        :data-status="alert.result.status"
        @click="$emit('open-target', alert.target.operator_id)"
      >
        <span class="cc-alert-dot" :data-status="alert.result.status"></span>
        <div class="cc-alert-text">
          <div class="cc-alert-title">{{ alert.target.display_name }}</div>
          <div class="cc-alert-detail">{{ alert.result.check_id }} — {{ alert.result.summary }}</div>
        </div>
        <span class="cc-alert-cta">→</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cc-alerts {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 280px;
  flex: 1;
}
.cc-alerts-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.cc-alerts-title {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  letter-spacing: 0.18em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
}
.cc-alerts-count {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  color: var(--nc-danger);
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--nc-danger-subtle);
  border: 1px solid var(--nc-danger-subtle);
}
.cc-alerts-empty {
  color: var(--nc-text-muted);
  font-size: 11px;
  padding: 12px 8px;
  text-align: center;
  font-style: italic;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cc-alerts-list { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; }
.cc-alert-row {
  display: grid; grid-template-columns: 8px 1fr auto;
  gap: 10px; align-items: center;
  padding: 6px 10px; border-radius: 5px;
  background: var(--nc-deep); border: 1px solid var(--nc-border);
  cursor: pointer; transition: background 0.18s ease, border-color 0.18s ease;
}
.cc-alert-row:hover { background: var(--nc-elevated); border-color: var(--nc-border-strong); }
.cc-alert-row[data-status="fail"] { border-left: 2px solid var(--nc-danger); }
.cc-alert-row[data-status="warn"] { border-left: 2px solid var(--nc-warning); }
.cc-alert-dot { width: 8px; height: 8px; border-radius: 50%; }
.cc-alert-dot[data-status="fail"] { background: var(--nc-danger); box-shadow: 0 0 6px var(--nc-danger-glow); }
.cc-alert-dot[data-status="warn"] { background: var(--nc-warning); box-shadow: 0 0 6px var(--nc-warning-glow); }
.cc-alert-title { font-size: 12px; color: var(--nc-text-primary); }
.cc-alert-detail { font-size: 10px; color: var(--nc-text-muted); font-family: 'JetBrains Mono', ui-monospace, monospace; margin-top: 1px; }
.cc-alert-cta { color: var(--nc-text-muted); font-size: 14px; }
</style>
