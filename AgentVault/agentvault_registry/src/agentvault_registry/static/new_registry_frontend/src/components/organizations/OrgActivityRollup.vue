<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// ─────────────────────────────────────────────────────────────────────────────
// E3 — Org activity roll-up (the ACTIVITY tab).
//
// One screen answering "what did my org's agents do with money this window":
// spend per agent, denials across all org agents, approvals by status, and the
// treasury's balance + windowed flow. Every number is fetched from ONE backend
// aggregate whose sources are the SAME tables the gates read (velocity_metrics
// for spend, the B1 rows for denials, agent_spend_approvals, the ES org
// aggregate for treasury flow) — no second bookkeeping, so this view can never
// disagree with an actual denial or cap.
//
// Treasury flow is honest about absence: when the EventStore is unreachable the
// backend says flows_available=false and this renders "ledger unavailable",
// never a fabricated zero.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { organizationService } from '@/services/api/organizationService'

const { t } = useI18n()
const props = defineProps<{ orgId: string; active: boolean }>()

const loading = ref(false)
const loadError = ref<string | null>(null)
const data = ref<any>(null)
const days = ref(7)
let loadedFor = ''

const fmt = (v: any, max = 6) =>
  Number(v ?? 0).toLocaleString(appLocale(), { maximumFractionDigits: max })
const denialLabel = (action: string) => action.replace(/^ironkey\./, '').replace(/_/g, ' ')

async function load() {
  loading.value = true
  loadError.value = null
  try {
    data.value = await organizationService.getOrgActivityRollup(props.orgId, days.value)
    loadedFor = `${props.orgId}:${days.value}`
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message
      || t('orgActivity.loadFailed', 'Could not load the activity roll-up')
  } finally {
    loading.value = false
  }
}

// lazy: fetch on first activation, refetch on org/window change while active
watch([() => props.active, () => props.orgId, days], ([act]) => {
  if (act && loadedFor !== `${props.orgId}:${days.value}`) void load()
}, { immediate: true })

const agents = computed(() => data.value?.agents || [])
const totals = computed(() => data.value?.totals || {})
const approvals = computed(() => Object.entries(data.value?.approvals || {}) as [string, number][])
const denialKinds = computed(() => Object.entries(data.value?.denial_breakdown || {}) as [string, number][])
const treasury = computed(() => data.value?.treasury || null)
</script>

<template>
  <section class="oar-root" data-tour="org-activity" data-testid="org-activity">
    <div class="oar-head">
      <p class="oar-sub">
        {{ t('orgActivity.subtitle', 'What your agents did with money in this window. Spend is settled volume from the same source the daily cap reads; denials are the durable audit rows.') }}
      </p>
      <div class="oar-window" role="group" aria-label="window">
        <button :class="['oar-win-btn', { 'oar-win-btn--on': days === 7 }]" @click="days = 7">7d</button>
        <button :class="['oar-win-btn', { 'oar-win-btn--on': days === 30 }]" @click="days = 30">30d</button>
      </div>
    </div>

    <div v-if="loading" class="oar-state">
      <Icon name="loader" class="oar-spin" />
      <span>{{ t('orgActivity.loading', 'Aggregating the window') }}</span>
    </div>
    <div v-else-if="loadError" class="oar-alert" role="alert">
      <Icon name="mdi:alert-octagon" />
      <span>{{ loadError }}</span>
      <button class="oar-retry" @click="load">{{ t('orgActivity.retry', 'Retry') }}</button>
    </div>

    <template v-else-if="data">
      <!-- stat chips -->
      <div class="oar-stats">
        <div class="oar-stat" data-testid="oar-spend">
          <span class="oar-stat-label">{{ t('orgActivity.stat.spend', 'Settled spend') }}</span>
          <span class="oar-stat-value">{{ fmt(totals.spend) }}</span>
        </div>
        <div class="oar-stat">
          <span class="oar-stat-label">{{ t('orgActivity.stat.txs', 'Transfers') }}</span>
          <span class="oar-stat-value">{{ fmt(totals.tx_count, 0) }}</span>
        </div>
        <div class="oar-stat" :class="{ 'oar-stat--warn': (totals.denials || 0) > 0 }" data-testid="oar-denials">
          <span class="oar-stat-label">{{ t('orgActivity.stat.denials', 'Denials') }}</span>
          <span class="oar-stat-value">{{ fmt(totals.denials, 0) }}</span>
        </div>
        <div class="oar-stat">
          <span class="oar-stat-label">{{ t('orgActivity.stat.active', 'Active agents') }}</span>
          <span class="oar-stat-value">{{ fmt(totals.agents_active, 0) }}<span class="oar-stat-dim">/{{ fmt(totals.agents, 0) }}</span></span>
        </div>
        <div v-if="treasury?.exists" class="oar-stat" data-testid="oar-treasury">
          <span class="oar-stat-label">{{ t('orgActivity.stat.treasury', 'Treasury balance') }}</span>
          <span class="oar-stat-value">{{ fmt(treasury.balance) }}</span>
        </div>
      </div>

      <!-- denial + approval breakdowns -->
      <div class="oar-chips-row" v-if="denialKinds.length || approvals.length">
        <div v-if="denialKinds.length" class="oar-chipset" data-testid="oar-denial-kinds">
          <span class="oar-chipset-label">{{ t('orgActivity.denialsBy', 'Denials by gate:') }}</span>
          <span v-for="[k, n] in denialKinds" :key="k" class="oar-chip oar-chip--warn">{{ denialLabel(k) }} {{ n }}</span>
        </div>
        <div v-if="approvals.length" class="oar-chipset" data-testid="oar-approvals">
          <span class="oar-chipset-label">{{ t('orgActivity.approvalsBy', 'Approvals:') }}</span>
          <span v-for="[k, n] in approvals" :key="k"
                :class="['oar-chip', { 'oar-chip--pending': k === 'pending' }]">{{ k }} {{ n }}</span>
        </div>
      </div>

      <!-- treasury flow -->
      <div v-if="treasury?.exists" class="oar-flow" data-testid="oar-flow">
        <Icon name="mdi:bank-transfer" class="oar-flow-ic" />
        <template v-if="treasury.flows_available">
          <span class="oar-flow-item">{{ t('orgActivity.flowIn', 'Into treasury:') }} <strong>{{ fmt(treasury.flows?.in) }}</strong></span>
          <span class="oar-flow-item">{{ t('orgActivity.flowOut', 'Out of treasury:') }} <strong>{{ fmt(treasury.flows?.out) }}</strong></span>
          <span class="oar-flow-dim">{{ fmt(treasury.flows?.events, 0) }} {{ t('orgActivity.flowEvents', 'movements in window') }}</span>
        </template>
        <span v-else class="oar-flow-dim">{{ t('orgActivity.flowUnavailable', 'Treasury ledger unavailable right now (EventStore unreachable); balance above is live.') }}</span>
      </div>

      <!-- per-agent table -->
      <div class="oar-table-wrap">
        <table class="oar-table" data-testid="oar-agent-table">
          <thead>
            <tr>
              <th>{{ t('orgActivity.col.agent', 'Agent') }}</th>
              <th class="oar-num">{{ t('orgActivity.col.spend', 'Spend') }}</th>
              <th class="oar-num">{{ t('orgActivity.col.txs', 'Transfers') }}</th>
              <th class="oar-num">{{ t('orgActivity.col.denials', 'Denials') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in agents" :key="a.did">
              <td class="oar-agent">
                <span class="oar-agent-name">{{ a.name || a.did }}</span>
                <span v-if="a.name" class="oar-agent-did">{{ a.did }}</span>
              </td>
              <td class="oar-num mono">{{ fmt(a.spend) }}</td>
              <td class="oar-num mono">{{ fmt(a.tx_count, 0) }}</td>
              <td :class="['oar-num', 'mono', { 'oar-warn-text': a.denials > 0 }]">{{ fmt(a.denials, 0) }}</td>
            </tr>
            <tr v-if="!agents.length">
              <td colspan="4" class="oar-empty">{{ t('orgActivity.noAgents', 'No agents assigned to this organization yet.') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.oar-root { display: flex; flex-direction: column; gap: 16px; }
.oar-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.oar-sub { margin: 0; font-size: 0.78rem; line-height: 1.55; color: rgba(148, 163, 184, 0.55); max-width: 680px; }
.oar-window { display: inline-flex; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); border-radius: 6px; overflow: hidden; }
.oar-win-btn {
  background: none; border: none; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 6px 12px; color: rgba(148, 163, 184, 0.6);
}
.oar-win-btn--on { background: rgba(var(--nc-primary-rgb), 0.15); color: rgba(var(--nc-primary-rgb), 0.95); }

.oar-state { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: rgba(148, 163, 184, 0.5); padding: 12px 0; }
.oar-spin { animation: oar-rot 1s linear infinite; }
@keyframes oar-rot { to { transform: rotate(360deg); } }
.oar-alert {
  display: flex; align-items: center; gap: 8px; font-size: 0.78rem;
  color: rgba(239, 68, 68, 0.85); background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 10px 12px;
}
.oar-retry {
  margin-left: auto; background: none; border: 1px solid rgba(239, 68, 68, 0.35);
  color: rgba(239, 68, 68, 0.85); border-radius: 6px; padding: 3px 10px; font-size: 0.7rem; cursor: pointer;
}

.oar-stats { display: flex; gap: 12px; flex-wrap: wrap; }
.oar-stat {
  flex: 1 1 150px; min-width: 150px; padding: 12px 14px;
  background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;
  display: flex; flex-direction: column; gap: 4px;
}
.oar-stat--warn { border-color: rgba(251, 191, 36, 0.3); background: rgba(251, 191, 36, 0.04); }
.oar-stat-label {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; color: rgba(148, 163, 184, 0.45);
}
.oar-stat-value { font-size: 1.15rem; font-weight: 600; color: rgba(226, 232, 240, 0.9); font-family: 'IBM Plex Mono', monospace; }
.oar-stat-dim { font-size: 0.8rem; color: rgba(148, 163, 184, 0.45); }

.oar-chips-row { display: flex; flex-direction: column; gap: 8px; }
.oar-chipset { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.oar-chipset-label { font-size: 0.72rem; color: rgba(148, 163, 184, 0.55); }
.oar-chip {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.64rem; font-weight: 600;
  padding: 2px 10px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(226, 232, 240, 0.75);
}
.oar-chip--warn { border-color: rgba(251, 191, 36, 0.35); color: rgba(251, 191, 36, 0.85); }
.oar-chip--pending { border-color: rgba(var(--nc-primary-rgb), 0.4); color: rgba(var(--nc-primary-rgb), 0.9); }

.oar-flow {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  font-size: 0.78rem; color: rgba(226, 232, 240, 0.8);
  padding: 10px 14px; border-radius: 8px;
  background: rgba(var(--nc-primary-rgb), 0.04); border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
}
.oar-flow-ic { font-size: 1.1rem; color: rgba(var(--nc-primary-rgb), 0.7); }
.oar-flow-item strong { font-family: 'IBM Plex Mono', monospace; }
.oar-flow-dim { font-size: 0.72rem; color: rgba(148, 163, 184, 0.5); }

.oar-table-wrap { overflow-x: auto; }
.oar-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.oar-table th {
  text-align: left; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(148, 163, 184, 0.45); padding: 8px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.oar-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); color: rgba(226, 232, 240, 0.82); }
.oar-num { text-align: right; }
.mono { font-family: 'IBM Plex Mono', monospace; }
.oar-agent { display: flex; flex-direction: column; gap: 1px; min-width: 200px; }
.oar-agent-name { font-weight: 600; }
.oar-agent-did { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: rgba(148, 163, 184, 0.4); word-break: break-all; }
.oar-warn-text { color: rgba(251, 191, 36, 0.9); }
.oar-empty { text-align: center; color: rgba(148, 163, 184, 0.45); padding: 18px 0; }
</style>
