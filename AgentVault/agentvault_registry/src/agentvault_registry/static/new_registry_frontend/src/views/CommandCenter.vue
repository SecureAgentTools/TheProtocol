<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useCommandCenterStore } from '@/stores/commandCenter'
import CCAlertList from '@/components/command/CCAlertList.vue'
import CCDetailDrawer from '@/components/command/CCDetailDrawer.vue'
import CCFleetRing from '@/components/command/CCFleetRing.vue'
import CCHeaderBar from '@/components/command/CCHeaderBar.vue'
import CCTargetGrid from '@/components/command/CCTargetGrid.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const store = useCommandCenterStore()
const {
  targets,
  targetsRead,
  loading,
  autoRefresh,
  lastRunAt,
  inflightTargets,
  fleetCheckCount,
  fleetOkCount,
  fleetWarnCount,
  fleetFailCount,
  fleetHealthPct,
  targetsReasonCode,
  containersReasonCode,
  failingChecks,
  error,
  exporting,
  exportProgress,
  runningFleet,
} = storeToRefs(store)

const selectedTargetId = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([store.loadChecks(), store.loadTargets()])
  // Auto-refresh stays OFF on cold-open per design Q2 default.
})

onBeforeUnmount(() => {
  store.stopAutoRefresh()
})

async function onRunAll() {
  await store.runFleet(true)
}

function onToggleAuto() {
  store.toggleAutoRefresh()
}

async function onExport() {
  await store.downloadSnapshot()
}

function onOpenTarget(operatorId: string) {
  selectedTargetId.value = operatorId
  // If we don't already have fresh results for the target, kick off a run.
  const t = targets.value.find(x => x.operator_id === operatorId)
  if (!t || !t.check_results.length) {
    store.runAllForTarget(operatorId, true).catch(() => {})
  }
}

function onCloseDrawer() {
  selectedTargetId.value = null
}

function onRerunFromDrawer(operatorId: string) {
  store.runAllForTarget(operatorId, true).catch(() => {})
}

const selectedTarget = computed(() => {
  if (!selectedTargetId.value) return null
  return targets.value.find(t => t.operator_id === selectedTargetId.value) ?? null
})

const selectedInflight = computed(() => {
  if (!selectedTargetId.value) return false
  return inflightTargets.value.has(selectedTargetId.value)
})

// §MCPTEST30 (V0561): the server says why it lists no targets; the console says it in the reader's language
const NO_TARGETS: Record<string, [string, string]> = {
  scope_off: ['commandCenterView.noTargets.scopeOff', 'This registry does not enumerate its operators here (fleet scope is off), so the Command Center has no targets.'],
  no_socket: ['commandCenterView.noTargets.noSocket', 'This registry has no access to its operators\' containers (no Docker socket since the F6 hardening). The operator pages and the federation compliance page read them over the federation instead.'],
  no_operators: ['commandCenterView.noTargets.noOperators', 'No operator belongs to this frame: it holds no cloud operator peer row.'],
}
// V0562: why the container checks do not run here (the operators are listed and measured from their rows either way)
const CONTAINERS: Record<string, [string, string]> = {
  scope_off: ['commandCenterView.containers.scopeOff', "Container checks are off here (fleet scope is off): operators are measured from their federation record and signed card."],
  no_socket: ['commandCenterView.containers.noSocket', "Container checks cannot run here (no Docker socket since the F6 hardening): operators are measured from their federation record and signed card."],
}
const containersText = computed(() => {
  const [key, fallback] = CONTAINERS[containersReasonCode.value || ''] ?? ['', '']
  return key ? t(key, fallback) : ''
})
// V0562: this registry itself is always a target, so the note explains a list with no OPERATOR in it
const operatorTargets = computed(() => targets.value.filter((x) => !x.is_self))
const noTargetsText = computed(() => {
  const code = targetsReasonCode.value
  if (operatorTargets.value.length || !code) return ''
  const [key, fallback] = NO_TARGETS[code] ?? ['', '']
  return key ? t(key, fallback) : ''
})

const fleetSubtitle = computed(() => {
  if (loading.value && !fleetCheckCount.value) return t('commandCenterView.loading')
  if (!targets.value.length) return t('commandCenterView.noTargetsShort', 'No targets on this registry')
  if (!fleetCheckCount.value) return t('commandCenterView.emptyHint')
  return t('commandCenterView.passingSummary', {
    ok: fleetOkCount.value,
    total: fleetCheckCount.value,
    targets: targets.value.length,
  })
})
</script>

<template>
  <div class="cc-page hm-module">
    <CCHeaderBar
      :loading="loading || runningFleet"
      :auto-refresh="autoRefresh"
      :last-run-at="lastRunAt"
      :ok="fleetOkCount"
      :warn="fleetWarnCount"
      :fail="fleetFailCount"
      :total="fleetCheckCount"
      :exporting="exporting"
      :export-progress="exportProgress"
      @run="onRunAll"
      @toggle-auto="onToggleAuto"
      @export="onExport"
    />

    <div class="cc-overview" data-tour="cc-overview">
      <div class="cc-overview-card">
        <CCFleetRing :pct="fleetHealthPct" label="fleet" />
        <div class="cc-overview-meta">
          <div class="cc-overview-line">{{ t('commandCenterView.targetsUnderWatch', { n: targetsRead ? targets.length : '—' }) }}</div>
          <div class="cc-overview-line cc-overview-sub">{{ fleetSubtitle }}</div>
        </div>
      </div>
      <CCAlertList
        :alerts="failingChecks"
        :measured="fleetCheckCount > 0"
        @open-target="onOpenTarget"
      />
    </div>

    <div v-if="error" class="cc-error">{{ error }}</div>
    <p v-if="containersText" class="cc-containers-note" data-testid="cc-containers-note">{{ containersText }}</p>
    <div v-if="noTargetsText" class="cc-no-targets" role="status" data-testid="cc-no-targets">
      <div class="cc-no-targets-title">{{ t('commandCenterView.noTargets.title', 'No operators listed here') }}</div>
      <p>{{ noTargetsText }}</p>
      <router-link class="cc-no-targets-link" :to="{ name: 'consul-compliance-monitor' }">{{ t('commandCenterView.noTargets.compliance', 'Open federation compliance') }} →</router-link>
    </div>

    <CCTargetGrid
      :targets="targets"
      :inflight-targets="inflightTargets"
      @open="onOpenTarget"
    />

    <CCDetailDrawer
      :target="selectedTarget"
      :inflight="selectedInflight"
      @close="onCloseDrawer"
      @rerun="onRerunFromDrawer"
    />
  </div>
</template>

<style scoped>
@import '@/components/healthMonitor/tp-healthmonitor.css';

.cc-page {
  padding: 20px 24px 56px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100vh;
  color: var(--nc-text-primary);
  background: transparent;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  position: relative;
}
.cc-page.hm-module { background: transparent; }

.cc-overview { display: flex; gap: 12px; align-items: stretch; flex-wrap: wrap; }
.cc-overview-card {
  display: flex; gap: 14px; align-items: center;
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 10px 14px;
  /* the card may shrink to the screen and its lines wrap, where it kept its one-line width (flex: 0 0 auto) and the
     fleet line ran past a phone's edge (the camera, 2026-10-13) */
  min-width: min(240px, 100%);
  flex: 0 1 auto;
}
.cc-overview-card:hover { border-color: var(--nc-border-strong); }
.cc-overview-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cc-overview-line { font-size: 12px; color: var(--nc-text-primary); }
.cc-overview-sub { font-size: 10px; color: var(--nc-text-muted); font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.04em; }
.cc-no-targets {
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--nc-text-secondary);
}
.cc-no-targets p { margin: 4px 0 8px; }
.cc-containers-note { margin: 0; font-size: 11.5px; color: var(--nc-text-muted); }
.cc-no-targets-title { color: var(--nc-text-primary); font-weight: 600; font-size: 13px; }
.cc-no-targets-link { color: var(--nc-primary); text-decoration: none; font-size: 12px; }
.cc-no-targets-link:hover, .cc-no-targets-link:focus-visible { text-decoration: underline; }
.cc-error {
  background: var(--nc-danger-subtle);
  border: 1px solid var(--nc-danger-subtle);
  color: var(--nc-danger);
  padding: 8px 14px; border-radius: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px;
}
</style>
