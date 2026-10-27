<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

const props = defineProps<{
  loading: boolean
  autoRefresh: boolean
  lastRunAt: string | null
  ok: number
  warn: number
  fail: number
  total: number
  exporting?: boolean
  exportProgress?: { done: number; total: number } | null
}>()

const emit = defineEmits<{
  (e: 'run'): void
  (e: 'toggle-auto'): void
  (e: 'export'): void
}>()

function formatLastRun(ts: string | null): string {
  if (!ts) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000))
  if (seconds < 5) return t('commandCenterView.header.justNow', 'just now')
  if (seconds < 60) return tp('commandCenterView.tile.secondsAgo', '{n}s ago', { n: seconds })
  if (seconds < 3600) return tp('commandCenterView.tile.minutesAgo', '{n}m ago', { n: Math.round(seconds / 60) })
  return tp('commandCenterView.tile.hoursAgo', '{n}h ago', { n: Math.round(seconds / 3600) })
}

const lastRunLabel = computed(() => formatLastRun(props.lastRunAt))

// §CCUX — one place for the explanations so the wording stays consistent with what the
// numbers actually mean. Deliberately plain: these are read at 2am during an incident.
// §MCPTEST30 (V0562): translated, and true again: "Total" no longer names the retired sandbox advisory rule, and a
// target runs as many checks as apply to it (this registry itself five; an operator with containers more).
const TIP = computed(() => ({
  ok: t('commandCenterView.header.tipOk', 'Checks that passed. Counts individual CHECKS, not targets.'),
  warn: t('commandCenterView.header.tipWarn', 'Checks that found something off but not broken (a threshold approached). Investigate, do not panic.'),
  fail: t('commandCenterView.header.tipFail', 'Checks that found a real fault. These are what the alert list below is drawn from.'),
  total: t('commandCenterView.header.tipTotal', 'Checks run across every target. A check that could not measure counts here and in none of the three above.'),
  export: t('commandCenterView.header.tipExport', 'Re-runs every check on every target, then downloads a .json evidence file: the full per-check results, per-target config slices, and a summary.'),
  run: t('commandCenterView.header.tipRun', 'Runs every applicable check against every target now. Results are cached for about 30 s; this forces a fresh pass.'),
  auto: t('commandCenterView.header.tipAuto', 'Re-runs every check automatically every 10 seconds. Handy on an incident call, noisy otherwise.'),
}))
</script>

<template>
  <div class="cc-header">
    <div class="cc-title-block">
      <h1 class="cc-title">{{ t('commandCenterView.header.title', 'Command Center') }}</h1>
      <div class="cc-subtitle">{{ t('commandCenterView.header.subtitle', 'Diagnostics and remediation') }}</div>
    </div>

    <!-- §CCUX (2026-07-28): every number here is a count of CHECKS (not targets), and the
         distinction between "this is broken" and "we could not measure it" was invisible.
         Each tile now carries a plain-language explanation on hover. -->
    <div class="cc-summary">
      <div class="cc-stat" data-tone="ok" :title="TIP.ok">
        <div class="cc-stat-num">{{ ok }}</div>
        <div class="cc-stat-label">{{ t('commandCenterView.header.ok', 'OK') }} <span class="cc-i" aria-hidden="true">i</span></div>
      </div>
      <div class="cc-stat" data-tone="warn" :title="TIP.warn">
        <div class="cc-stat-num">{{ warn }}</div>
        <div class="cc-stat-label">{{ t('commandCenterView.header.warn', 'Warn') }} <span class="cc-i" aria-hidden="true">i</span></div>
      </div>
      <div class="cc-stat" data-tone="fail" :title="TIP.fail">
        <div class="cc-stat-num">{{ fail }}</div>
        <div class="cc-stat-label">{{ t('commandCenterView.header.fail', 'Fail') }} <span class="cc-i" aria-hidden="true">i</span></div>
      </div>
      <div class="cc-stat" :title="TIP.total">
        <div class="cc-stat-num">{{ total }}</div>
        <div class="cc-stat-label">{{ t('commandCenterView.header.total', 'Total') }} <span class="cc-i" aria-hidden="true">i</span></div>
      </div>
    </div>

    <div class="cc-actions">
      <div class="cc-meta">
        <span class="cc-meta-key">{{ t('commandCenterView.header.lastRun', 'Last run') }}</span>
        <span class="cc-meta-val">{{ lastRunLabel }}</span>
        <span class="cc-meta-sep">·</span>
        <span class="cc-meta-key">{{ t('commandCenterView.header.auto', 'Auto') }}</span>
        <button
          class="cc-toggle"
          :class="{ 'cc-toggle-on': autoRefresh }"
          :aria-pressed="autoRefresh ? 'true' : 'false'"
          @click="emit('toggle-auto')"
          :title="TIP.auto"
        >{{ autoRefresh ? t('commandCenterView.header.autoOn', 'On · 10 s') : t('commandCenterView.header.autoOff', 'Off') }}</button>
      </div>
      <div class="cc-action-row">
        <button
          class="cc-export-btn"
          :disabled="exporting || loading"
          :title="exportProgress
            ? tp('commandCenterView.header.collecting', 'Collecting evidence: {done}/{total} calls done', { done: exportProgress.done, total: exportProgress.total })
            : TIP.export"
          @click="emit('export')"
        >
          <span v-if="exporting && exportProgress">⬇ {{ exportProgress.done }}/{{ exportProgress.total }}</span>
          <span v-else-if="exporting">⬇ {{ t('commandCenterView.header.exporting', 'Exporting…') }}</span>
          <span v-else>⬇ {{ t('commandCenterView.header.export', 'Export evidence (.json)') }}</span>
        </button>
        <button
          class="cc-run-btn"
          :disabled="loading"
          :title="TIP.run"
          @click="emit('run')"
        >
          <span v-if="loading">⟳ {{ t('commandCenterView.header.running', 'Running…') }}</span>
          <span v-else>▶ {{ t('commandCenterView.header.run', 'Run all checks') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cc-header {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 18px;
  align-items: center;
  padding: 12px 16px;
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
}
.cc-title {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.12em;
  margin: 0;
  color: var(--nc-primary);
  text-transform: uppercase;
}
.cc-subtitle {
  font-size: 11px;
  color: var(--nc-text-muted);
  letter-spacing: 0.06em;
  margin-top: 2px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cc-summary { display: flex; gap: 8px; }
.cc-stat {
  min-width: 60px; padding: 6px 12px; border-radius: 6px;
  background: var(--nc-deep); border: 1px solid var(--nc-border);
  text-align: center;
  position: relative;
}
.cc-stat[data-tone="ok"]   { border-top: 2px solid var(--nc-success); }
.cc-stat[data-tone="warn"] { border-top: 2px solid var(--nc-warning); }
.cc-stat[data-tone="fail"] { border-top: 2px solid var(--nc-danger);  }
.cc-stat-num {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 18px; font-weight: 600; line-height: 1;
  color: var(--nc-text-primary);
}
.cc-stat[data-tone="ok"]   .cc-stat-num { color: var(--nc-success); }
.cc-stat[data-tone="warn"] .cc-stat-num { color: var(--nc-warning); }
.cc-stat[data-tone="fail"] .cc-stat-num { color: var(--nc-danger); }
.cc-stat-label {
  font-size: 9px; color: var(--nc-text-muted);
  letter-spacing: 0.14em; text-transform: uppercase;
  margin-top: 2px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}

.cc-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.cc-meta {
  display: flex; gap: 6px; align-items: center;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
}
.cc-meta-key { color: var(--nc-text-muted); letter-spacing: 0.08em; text-transform: uppercase; }
.cc-meta-val { color: var(--nc-text-primary); }
.cc-meta-sep { color: var(--nc-border-strong); margin: 0 2px; }
.cc-toggle {
  background: var(--nc-deep); border: 1px solid var(--nc-border);
  color: var(--nc-text-muted); padding: 1px 8px; border-radius: 999px;
  font-family: inherit; font-size: 9px; cursor: pointer; letter-spacing: 0.04em;
  transition: all 0.2s ease;
}
.cc-toggle:hover { color: var(--nc-text-primary); border-color: var(--nc-border-strong); }
.cc-toggle-on { color: var(--nc-success); border-color: var(--nc-success-subtle); background: var(--nc-success-subtle); }

.cc-action-row { display: flex; gap: 6px; align-items: stretch; }
.cc-run-btn, .cc-i {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 11px; height: 11px;
  margin-left: 3px;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 7px;
  font-style: italic;
  line-height: 1;
  opacity: 0.45;
  vertical-align: middle;
  cursor: help;
}
.cc-stat:hover .cc-i { opacity: 0.9; }

.cc-export-btn {
  padding: 7px 14px; border-radius: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10px;
  font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  cursor: pointer; transition: all 0.2s ease; white-space: nowrap;
}
.cc-run-btn {
  background: var(--nc-primary-subtle);
  border: 1px solid var(--nc-primary-subtle);
  color: var(--nc-primary);
}
.cc-run-btn:hover { box-shadow: 0 0 0 1px var(--nc-primary); }
.cc-run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.cc-export-btn {
  background: transparent;
  border: 1px solid var(--nc-border);
  color: var(--nc-text-primary);
}
.cc-export-btn:hover { border-color: var(--nc-primary); color: var(--nc-primary); }
.cc-export-btn:disabled { opacity: 0.5; cursor: progress; }

@media (max-width: 1100px) {
  .cc-header { grid-template-columns: 1fr; }
  .cc-summary { flex-wrap: wrap; }
  .cc-actions { align-items: stretch; }
}
</style>
