<template>
  <!-- §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints -->
  <div class="cicd-module" style="min-height:100vh;padding:24px;position:relative;z-index:1;">

    <!-- Page Header -->
    <div style="margin-bottom:20px;">
      <div class="cicd-section-title" data-tour="cicd-hero" style="margin-bottom:4px;">{{ t('cicdListView.fleetOverview') }}</div>
      <div style="font-size:20px;font-weight:700;color:var(--cicd-text);">{{ t('cicdListView.title') }}</div>
      <div style="font-size:12px;color:var(--cicd-text-muted);margin-top:2px;">
        {{ t('cicdListView.subtitle') }}
      </div>
    </div>

    <!-- Fleet Stats -->
    <div class="cicd-stat-grid" style="margin-bottom:22px;">
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('cicdListView.stats.pipelines') }}</div>
        <div class="stat-value" :title="t('cicdListView.stats.notCounted')">{{ fleetStats.pipelines ?? '—' }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('cicdListView.stats.versions') }}</div>
        <div class="stat-value" :title="t('cicdListView.stats.notCounted')">{{ fleetStats.versions ?? '—' }}</div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('cicdListView.stats.active') }}</div>
        <div class="stat-value" :style="{color: fleetStats.active > 0 ? 'var(--cicd-blue)' : 'var(--cicd-text)'}">
          {{ statsSettled ? fleetStats.active : '—' }}
        </div>
      </div>
      <div class="cicd-stat-tile">
        <div class="stat-label">{{ t('cicdListView.stats.successRate') }}</div>
        <div class="stat-value" :style="{color: !statsSettled || fleetStats.successRate === null ? 'var(--cicd-text)' : fleetStats.successRate >= 80 ? 'var(--cicd-green)' : 'var(--cicd-red)'}">
          {{ statsSettled && fleetStats.successRate !== null ? fleetStats.successRate + '%' : '—' }}
        </div>
      </div>
    </div>

    <!-- Agent Table -->
    <!-- the table scrolls sideways inside its card on a phone, where its last column was clipped out of reach (overflow
         hidden; the camera, 2026-10-13) -->
    <div class="cicd-card" style="margin-bottom:20px;overflow-x:auto;">
      <div style="padding:14px 18px;border-bottom:1px solid var(--cicd-border);display:flex;justify-content:space-between;align-items:center;">
        <div class="cicd-section-title">{{ t('cicdListView.configurations') }}</div>
        <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">
          {{ loading || fleetError ? '— ' + t('cicdListView.agents') : agentRows.length === 1
            ? tp('cicdListView.agentsCountOne', '{n} agent', { n: 1 })
            : tp('cicdListView.agentsCountMany', '{n} agents', { n: agentRows.length }) }}
        </span>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="cicd-empty" style="padding:40px;">
        <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
        <div class="cicd-empty-title">{{ t('cicdListView.loading') }}</div>
      </div>

      <!-- CICD1 (audit 2026-05-07): inline error + retry. -->
      <div v-else-if="fleetError" class="cicd-empty" style="padding:40px;">
        <div class="cicd-empty-icon" style="color:var(--cicd-red);">✕</div>
        <div class="cicd-empty-title">{{ t('cicdListView.loadFailed') }}</div>
        <div style="font-family:var(--cicd-font-mono);font-size:11px;color:var(--cicd-text-muted);margin-top:6px;max-width:420px;text-align:center;">
          {{ fleetError }}
        </div>
        <button @click="loadFleet" class="cicd-btn cicd-btn-primary" style="margin-top:14px;">{{ t('cicdListView.retry') }}</button>
      </div>

      <!-- Empty -->
      <div v-else-if="!agentRows.length" class="cicd-empty" style="padding:40px;">
        <div class="cicd-empty-icon">⬡</div>
        <div class="cicd-empty-title">{{ t('cicdListView.noAgents') }}</div>
        <RouterLink to="/my-agents" class="cicd-btn cicd-btn-primary" style="margin-top:10px;text-decoration:none;">
          {{ t('cicdListView.createAgent') }}
        </RouterLink>
      </div>

      <!-- Table -->
      <table v-else class="cicd-table" data-tour="cicd-fleet">
        <thead>
          <tr>
            <th>{{ t('cicdListView.table.thAgent') }}</th>
            <th>{{ t('cicdListView.table.thPipelines') }}</th>
            <th>{{ t('cicdListView.table.thVersions') }}</th>
            <th>{{ t('cicdListView.table.thDeployments') }}</th>
            <th>{{ t('cicdListView.table.thSuccess') }}</th>
            <th>{{ t('cicdListView.table.thLastDeploy') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in paginatedAgents" :key="a.did">
            <td>
              <div>
                <div style="font-weight:600;color:var(--cicd-text);font-size:13px;">{{ a.name }}</div>
                <div style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">
                  {{ a.did?.split(':').slice(-1)[0]?.substring(0,16) }}…
                </div>
              </div>
            </td>
            <td>
              <span v-if="a.loading" style="color:var(--cicd-text-muted);font-size:11px;">…</span>
              <span v-else style="font-family:var(--cicd-font-mono);" data-col="pipelines">{{ a.pipelines ?? '—' }}</span>
            </td>
            <td>
              <span v-if="a.loading" style="color:var(--cicd-text-muted);font-size:11px;">…</span>
              <span v-else style="font-family:var(--cicd-font-mono);" data-col="versions">{{ a.versions ?? '—' }}</span>
            </td>
            <td>
              <span v-if="a.loading" style="color:var(--cicd-text-muted);font-size:11px;">…</span>
              <span v-else style="font-family:var(--cicd-font-mono);" data-col="deployments">{{ a.stats?.statistics?.total ?? '—' }}</span>
            </td>
            <td>
              <span v-if="a.loading" style="color:var(--cicd-text-muted);font-size:11px;">…</span>
              <span v-else-if="rateOf(a) !== null" style="font-family:var(--cicd-font-mono);font-size:12px;" data-col="success"
                :style="{color: (rateOf(a) ?? 0) >= 80 ? 'var(--cicd-green)' : (rateOf(a) ?? 0) > 50 ? 'var(--cicd-yellow)' : 'var(--cicd-red)'}">
                {{ rateOf(a) }}%
              </span>
              <span v-else style="color:var(--cicd-text-muted);font-size:11px;">—</span>
            </td>
            <td style="font-size:11px;color:var(--cicd-text-muted);">
              <span v-if="a.stats?.last_deployment_at">{{ fmtDate(a.stats.last_deployment_at) }}</span>
              <span v-else>—</span>
            </td>
            <td>
              <RouterLink
                :to="`/agent/${a.did}/ci-cd`"
                class="cicd-btn cicd-btn-primary cicd-btn-sm"
                style="text-decoration:none;"
                data-tour="cicd-manage"
              >{{ t('cicdListView.table.manage') }}</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div
        v-if="agentRows.length > pageSize"
        style="padding:10px 18px;border-top:1px solid var(--cicd-border);display:flex;justify-content:space-between;align-items:center;"
      >
        <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">
          {{ (page - 1) * pageSize + 1 }}–{{ Math.min(page * pageSize, agentRows.length) }} of {{ agentRows.length }}
        </span>
        <div style="display:flex;gap:6px;">
          <button class="cicd-btn cicd-btn-ghost cicd-btn-sm" :disabled="page <= 1" @click="page--">{{ t('cicdListView.pagination.prev') }}</button>
          <button class="cicd-btn cicd-btn-ghost cicd-btn-sm" :disabled="page >= totalPages" @click="page++">{{ t('cicdListView.pagination.next') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import { useAgentStore } from '@/stores/agents'
import { cicdService } from '@/services/api/cicdService'
import { useI18n } from '@/composables/useI18n'
import '@/components/cicd/tp-cicd.css'

const { t, tp } = useI18n()
const agentStore = useAgentStore()
const loading = ref(true)
// CICD1 (audit 2026-05-07): surface top-level fetch failure inline. Previously
// errors only landed in console.error and the user saw a blank table after the
// spinner cleared.
const fleetError = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

interface AgentRow {
  did: string
  name: string
  loading: boolean
  /** the agent's own lists, counted (null: not read) */
  pipelines: number | null
  versions: number | null
  stats: any | null
}

/** A rate over the agent's own deployments; none without any (an agent that never deployed has no rate, not 0%). */
function rateOf(a: AgentRow): number | null {
  const st = a.stats?.statistics
  if (!st || !st.total) return null
  return Math.round(((st.successful ?? 0) / st.total) * 100)
}

const agentRows = ref<AgentRow[]>([])
/** §FESUITE (the loading sweep): the tiles and the count wait for the agent list and every agent's stats (a 0 says
 *  "none"); after a failed list they keep the dash. */
const statsSettled = computed(() => !loading.value && !fleetError.value && agentRows.value.every(r => !r.loading))

const totalPages = computed(() => Math.max(1, Math.ceil(agentRows.value.length / pageSize)))
const paginatedAgents = computed(() => agentRows.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const fleetStats = computed(() => {
  const rows = agentRows.value.filter(r => !r.loading && r.stats)
  const total = rows.reduce((s, r) => s + (r.stats?.statistics?.total ?? 0), 0)
  const succ = rows.reduce((s, r) => s + (r.stats?.statistics?.successful ?? 0), 0)
  const active = rows.reduce((s, r) => s + (r.stats?.cicd_enabled ? 1 : 0), 0)
  return {
    // §FESUITE: the stats route counts deployments, not pipelines or versions; the rows count each agent's own lists now,
    // and a tile sums them only once every row was read (a dash otherwise, never a 0 for "none").
    pipelines: statsSettled.value && agentRows.value.every(r => r.pipelines !== null)
      ? agentRows.value.reduce((s, r) => s + (r.pipelines ?? 0), 0) : null,
    versions: statsSettled.value && agentRows.value.every(r => r.versions !== null)
      ? agentRows.value.reduce((s, r) => s + (r.versions ?? 0), 0) : null,
    active,
    // a rate over no runs is no rate (it read 100%)
    successRate: total > 0 ? Math.round((succ / total) * 100) : null,
  }
})

function fmtDate(d: string) {
  return new Date(d).toLocaleString(appLocale())
}

async function loadFleet() {
  loading.value = true
  fleetError.value = null
  try {
    await agentStore.fetchMyAgents()
    // the store reports a failed read in its error field and returns; an empty fleet read that way said "0 agents"
    if (agentStore.error) throw new Error(agentStore.error)
    // Seed rows with loading state
    agentRows.value = agentStore.agents.map(a => ({
      did: a.did,
      name: a.name || a.did,
      loading: true,
      pipelines: null,
      versions: null,
      stats: null,
    }))
    loading.value = false

    // Per agent: its stats, and its own pipeline and version lists counted (the columns name them; §FESUITE 131,
    // 2026-10-15). Eight agents at a time: a member's list runs to 200 agents and each agent is three reads. A read that
    // fails leaves its cell a dash, never a 0.
    const work = agentRows.value.map((row, i) => async () => {
      const [stats, pipes, vers] = await Promise.allSettled([
        cicdService.getCICDStats(row.did),
        cicdService.listPipelines(row.did),
        cicdService.listVersions(row.did),
      ])
      agentRows.value[i] = {
        ...agentRows.value[i],
        stats: stats.status === 'fulfilled' ? stats.value : null,
        pipelines: pipes.status === 'fulfilled' ? pipes.value.length : null,
        versions: vers.status === 'fulfilled' ? vers.value.length : null,
        loading: false,
      }
    })
    let next = 0
    await Promise.all(Array.from({ length: Math.min(8, work.length) }, async () => {
      while (next < work.length) await work[next++]()
    }))
  } catch (e: any) {
    console.error('Fleet load failed:', e)
    fleetError.value = e?.response?.data?.detail || e?.message || 'Failed to load agents'
    loading.value = false
  }
}

onMounted(loadFleet)
</script>
