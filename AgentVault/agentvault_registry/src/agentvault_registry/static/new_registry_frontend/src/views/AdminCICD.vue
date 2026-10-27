<template>
  <div class="ac-root">
    <!-- Ambient is provided by DashboardLayout's <ViewAmbient> per route.meta.viewAmbientTone='admin'.
         Local ambient removed (was duplicate per feedback_route_meta_view_ambient memory). -->

    <div class="ac-content">
      <!-- Hero -->
      <div class="ac-hero">
        <div>
          <div class="ac-chip-hero"><span class="ac-chip-dot"></span>ADMINISTRATION · CI/CD</div>
          <h1 class="ac-h1">{{ t('adminCicdView.title') }}</h1>
          <p class="ac-lead">{{ t('adminCicdView.subtitle') }}</p>
        </div>
        <div class="ac-hero-actions">
          <label class="ac-toggle">
            <input type="checkbox" v-model="autoRefresh" />
            <span>{{ t('adminCicdView.autoRefresh') }}</span>
          </label>
          <select v-model.number="windowHours" class="ac-input" aria-label="Time window">
            <option :value="1">1h</option>
            <option :value="6">6h</option>
            <option :value="24">24h</option>
            <option :value="168">7d</option>
          </select>
          <button class="ac-btn ac-btn-primary" @click="refreshAll" :disabled="loading">
            {{ loading ? '…' : t('adminCicdView.refresh') }}
          </button>
        </div>
      </div>

      <!-- Stat tiles -->
      <div class="ac-stat-grid">
        <div class="ac-stat">
          <div class="ac-stat-label">{{ t('adminCicdView.tiles.pipelines') }}</div>
          <div class="ac-stat-value">{{ summary?.pipelines.total ?? '—' }}</div>
          <div class="ac-stat-sub" v-if="summary?.pipelines.last_created_at">
            {{ t('adminCicdView.tiles.lastCreated', { ago: fromNow(summary.pipelines.last_created_at) }) }}
          </div>
        </div>
        <div class="ac-stat">
          <div class="ac-stat-label">{{ t('adminCicdView.tiles.deployments', { window: windowLabel }) }}</div>
          <div class="ac-stat-value">{{ summary?.deployments.total ?? '—' }}</div>
          <div class="ac-stat-sub">
            <span class="ac-ok">{{ summary?.deployments.success ?? '—' }} ok</span>
            <span class="ac-sep">·</span>
            <span class="ac-fail">{{ summary?.deployments.failed ?? '—' }} fail</span>
            <span class="ac-sep">·</span>
            <span class="ac-warn">{{ summary?.deployments.pending ?? '—' }} pending</span>
          </div>
        </div>
        <div
          class="ac-stat"
          :class="{ 'ac-stat--warn': topFailDid, 'ac-stat--clickable': !!topFailDid }"
          :title="topFailDid ? `Open CI/CD for ${agentLabel(topFailDid)}` : ''"
          @click="topFailDid && $router.push(`/agent/${topFailDid}/ci-cd`)"
        >
          <div class="ac-stat-label">{{ t('adminCicdView.tiles.topFailing') }}</div>
          <div class="ac-stat-value ac-stat-value--did" v-if="topFailDid" :title="topFailDid">{{ agentLabel(topFailDid) }}</div>
          <div class="ac-stat-value ac-ok" v-else-if="summary">{{ t('adminCicdView.tiles.noFailing') }}</div>
          <div class="ac-stat-value" v-else>—</div>
          <div class="ac-stat-sub" v-if="topFailCount">{{ topFailCount }} {{ t('adminCicdView.tiles.failsSuffix') }}</div>
        </div>
        <div class="ac-stat" :class="{ 'ac-stat--warn': flagsUnackedTotal > 0 }">
          <div class="ac-stat-label">{{ t('adminCicdView.tiles.flagsUnacked') }}</div>
          <div class="ac-stat-value">{{ flagsRead ? flagsUnackedTotal : '—' }}</div>
          <div class="ac-stat-sub" v-if="flagsByTypeStr">{{ flagsByTypeStr }}</div>
        </div>
      </div>

      <!-- Tabs -->
      <div class="ac-tabs">
        <button v-for="tab in tabs" :key="tab.id"
                :class="['ac-tab', { 'is-active': activeTab === tab.id }]"
                @click="activeTab = tab.id">
          {{ tab.label }}
          <span v-if="tab.count !== undefined" class="ac-tab-count">{{ tab.count }}</span>
        </button>
      </div>

      <!-- Deployments tab -->
      <div v-if="activeTab === 'deployments'" class="ac-panel">
        <div class="ac-filterbar">
          <select v-model="depFilters.status" class="ac-input" aria-label="Filter by status" @change="loadDeployments">
            <option value="">{{ t('adminCicdView.filters.anyStatus') }}</option>
            <option value="success">success</option>
            <option value="failed">failed</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
          </select>
          <input v-model="depFilters.agent_did" :placeholder="t('adminCicdView.filters.agentDid')"
                 class="ac-input ac-input--wide" @keyup.enter="loadDeployments" />
          <input v-model="depFilters.organization_id" :placeholder="t('adminCicdView.filters.orgId')"
                 class="ac-input ac-input--wide" @keyup.enter="loadDeployments" />
          <button class="ac-btn" @click="loadDeployments">{{ t('adminCicdView.filters.apply') }}</button>
          <button class="ac-btn ac-btn-ghost" @click="resetDeployFilters">{{ t('adminCicdView.filters.reset') }}</button>
          <span class="ac-spacer"></span>
          <button class="ac-btn ac-btn-ghost" @click="exportDeploymentsCsv" :disabled="!deployments.length">
            {{ t('adminCicdView.export') }}
          </button>
        </div>
        <div class="ac-table-wrap">
          <table class="ac-table">
            <thead>
              <tr>
                <th>{{ t('adminCicdView.cols.status') }}</th>
                <th>{{ t('adminCicdView.cols.agent') }}</th>
                <th>{{ t('adminCicdView.cols.pipeline') }}</th>
                <th>{{ t('adminCicdView.cols.version') }}</th>
                <th>{{ t('adminCicdView.cols.env') }}</th>
                <th>{{ t('adminCicdView.cols.started') }}</th>
                <th>{{ t('adminCicdView.cols.duration') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in deployments"
                :key="d.id"
                class="ac-row ac-row--clickable"
                :title="`Open deployment detail · ${shortDid(d.agent_did)}`"
                @click="openDeploymentDetail(d)"
              >
                <td><span :class="['ac-pill', 'ac-st-' + d.status]">{{ d.status }}</span></td>
                <td class="ac-mono" @click.stop>
                  <RouterLink :to="`/agent/${d.agent_did}/ci-cd`" class="ac-link" :title="d.agent_did">{{ agentLabel(d.agent_did) }}</RouterLink>
                </td>
                <td>{{ d.pipeline_name || '—' }}</td>
                <td class="ac-mono">{{ d.version || '—' }}</td>
                <td>{{ d.environment }}</td>
                <td class="ac-muted">{{ fromNow(d.started_at) }}</td>
                <td class="ac-mono">{{ d.duration_seconds !== null ? `${d.duration_seconds}s` : '—' }}</td>
                <td>
                  <span v-if="d.organization_id" class="ac-mini" :title="d.organization_id">org</span>
                </td>
              </tr>
              <!-- §FESUITE (2026-10-05): the three tables' empty rows said none ("no results", "no failing agents", "no
                   flags", the last two in green) over a failed read; the tiles and tab counts already waited for their
                   reads. Each table says its read failed now, with Try again. -->
              <tr v-if="deploymentsRead && !deployments.length && !loading">
                <td colspan="8" class="ac-empty">{{ t('adminCicdView.noResults') }}</td>
              </tr>
              <tr v-else-if="!deploymentsRead && !deployments.length && !loading" data-testid="ac-deployments-failed">
                <td colspan="8"><ReadFailedNotice dense :retry="loadDeployments" /></td>
              </tr>
              <tr v-if="loading">
                <td colspan="8" class="ac-empty">…</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Failing agents tab -->
      <div v-if="activeTab === 'failing'" class="ac-panel">
        <div class="ac-table-wrap">
          <table class="ac-table">
            <thead>
              <tr><th>{{ t('adminCicdView.cols.agent') }}</th><th>{{ t('adminCicdView.cols.failCount') }}</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="row in summary?.deployments.top_failing_agents || []" :key="row.did" class="ac-row ac-row--clickable" @click="$router.push(`/agent/${row.did}/ci-cd`)">
                <td class="ac-mono" :title="row.did">
                  <RouterLink :to="`/agent/${row.did}/ci-cd`" class="ac-link" @click.stop>{{ agentLabel(row.did) }}</RouterLink>
                </td>
                <td><span class="ac-pill ac-st-failed">{{ row.fail_count }}</span></td>
                <td class="ac-muted">{{ t('adminCicdView.cols.window', { window: windowLabel }) }}</td>
              </tr>
              <tr v-if="summary && !summary.deployments.top_failing_agents?.length">
                <td colspan="3" class="ac-empty ac-ok">{{ t('adminCicdView.noFailingAgents') }}</td>
              </tr>
              <tr v-else-if="!summary && !loading" data-testid="ac-failing-failed">
                <td colspan="3"><ReadFailedNotice dense :retry="loadSummary" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Flags tab -->
      <div v-if="activeTab === 'flags'" class="ac-panel">
        <div class="ac-filterbar">
          <label class="ac-toggle">
            <input type="checkbox" v-model="flagsOnlyUnacked" @change="loadFlags" />
            <span>{{ t('adminCicdView.flags.onlyUnacked') }}</span>
          </label>
          <select v-model="flagTypeFilter" @change="loadFlags" class="ac-input" aria-label="Filter by flag type">
            <option value="">{{ t('adminCicdView.flags.anyType') }}</option>
            <option value="jws_verify_threshold">jws_verify_threshold</option>
            <option value="persistent_drift">persistent_drift</option>
          </select>
        </div>
        <div class="ac-table-wrap">
          <table class="ac-table">
            <thead>
              <tr>
                <th>{{ t('adminCicdView.flags.type') }}</th>
                <th>{{ t('adminCicdView.cols.agent') }}</th>
                <th>{{ t('adminCicdView.flags.reason') }}</th>
                <th>{{ t('adminCicdView.flags.raised') }}</th>
                <th>{{ t('adminCicdView.flags.acked') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in flagsRows" :key="f.id" class="ac-row">
                <td><span class="ac-pill ac-st-flag">{{ f.flag_type }}</span></td>
                <td class="ac-mono" :title="f.agent_did">
                  <RouterLink :to="`/agent/${f.agent_did}/ci-cd`" class="ac-link">{{ agentLabel(f.agent_did) }}</RouterLink>
                </td>
                <td class="ac-muted">{{ f.reason || '—' }}</td>
                <td class="ac-muted">{{ fromNow(f.raised_at) }}</td>
                <td>
                  <span v-if="f.acknowledged_at" class="ac-ok">✓ ack</span>
                  <span v-else class="ac-warn"><Icon name="mdi:timer-sand" /> pending</span>
                </td>
                <td>
                  <button v-if="!f.acknowledged_at" class="ac-btn ac-btn-sm" @click="ackFlag(f)">
                    {{ t('adminCicdView.flags.ack') }}
                  </button>
                </td>
              </tr>
              <tr v-if="flagsRead && !flagsRows.length">
                <td colspan="6" class="ac-empty ac-ok">{{ t('adminCicdView.flags.none') }}</td>
              </tr>
              <tr v-else-if="!flagsRead && !flagsRows.length && !loading" data-testid="ac-flags-failed">
                <td colspan="6"><ReadFailedNotice dense :retry="loadFlags" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="error" class="ac-error">{{ error }}</div>
    </div>

    <!-- §pass50.1 — Deployment detail drawer (right-side panel) -->
    <Transition name="dd-drawer">
      <aside v-if="detailDeployment" class="dd-drawer" role="dialog" aria-label="Deployment detail">
        <div class="dd-drawer__scrim" @click="closeDeploymentDetail" aria-hidden="true" />
        <div class="dd-drawer__panel" @click.stop>
          <header class="dd-drawer__head">
            <h3>Deployment detail</h3>
            <button class="dd-drawer__close" @click="closeDeploymentDetail" aria-label="Close">&times;</button>
          </header>
          <div class="dd-drawer__body">
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Status</div>
              <div class="dd-drawer__row-value">
                <span :class="['ac-pill', 'ac-st-' + detailDeployment.status]">{{ detailDeployment.status }}</span>
              </div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Agent</div>
              <div class="dd-drawer__row-value">
                <RouterLink :to="`/agent/${detailDeployment.agent_did}/ci-cd`" class="ac-link" @click="closeDeploymentDetail">
                  {{ agentLabel(detailDeployment.agent_did) }}
                </RouterLink>
                <div style="margin-top:4px;"><code>{{ detailDeployment.agent_did }}</code></div>
              </div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Pipeline</div>
              <div class="dd-drawer__row-value">{{ detailDeployment.pipeline_name || '—' }}</div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Version</div>
              <div class="dd-drawer__row-value"><code>{{ detailDeployment.version || '—' }}</code></div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Environment</div>
              <div class="dd-drawer__row-value">{{ detailDeployment.environment }}</div>
            </div>
            <div class="dd-drawer__row" v-if="detailDeployment.organization_id">
              <div class="dd-drawer__row-label">Organization</div>
              <div class="dd-drawer__row-value"><code>{{ detailDeployment.organization_id }}</code></div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Started</div>
              <div class="dd-drawer__row-value">{{ detailDeployment.started_at || '—' }} <span class="ac-muted">({{ fromNow(detailDeployment.started_at) }})</span></div>
            </div>
            <div class="dd-drawer__row" v-if="detailDeployment.completed_at">
              <div class="dd-drawer__row-label">Completed</div>
              <div class="dd-drawer__row-value">{{ detailDeployment.completed_at }} <span class="ac-muted">({{ fromNow(detailDeployment.completed_at) }})</span></div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Duration</div>
              <div class="dd-drawer__row-value">{{ detailDeployment.duration_seconds != null ? `${detailDeployment.duration_seconds}s` : '—' }}</div>
            </div>
            <div class="dd-drawer__row" v-if="(detailDeployment as any).error_message">
              <div class="dd-drawer__row-label">Error</div>
              <div class="dd-drawer__err">{{ (detailDeployment as any).error_message }}</div>
            </div>
            <div class="dd-drawer__row">
              <div class="dd-drawer__row-label">Deployment ID</div>
              <div class="dd-drawer__row-value"><code>{{ detailDeployment.id }}</code></div>
            </div>
          </div>
          <footer class="dd-drawer__foot">
            <RouterLink :to="`/agent/${detailDeployment.agent_did}/ci-cd`" class="ac-btn" @click="closeDeploymentDetail">Open agent CI/CD &rsaquo;</RouterLink>
            <button class="ac-btn" @click="closeDeploymentDetail">Close</button>
          </footer>
        </div>
      </aside>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { cicdAdminService, type CicdFleetSummary, type CicdAdminDeployment, type AgentFlag } from '@/services/api/cicdAdmin'
import { useI18n } from '@/composables/useI18n'
import { readAccessToken } from '@/services/accessToken'
import { downloadCsv, csvFilenameTimestamp } from '@/components/common/csvExport'
dayjs.extend(relativeTime)
const { t } = useI18n()

const windowHours = ref(24)
const autoRefresh = ref(true)
const loading = ref(false)
const error = ref('')

const summary = ref<CicdFleetSummary | null>(null)
const deployments = ref<CicdAdminDeployment[]>([])
const flagsRows = ref<AgentFlag[]>([])
const flagsByType = ref<Record<string, number>>({})
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const deploymentsRead = ref(false)
const flagsRead = ref(false)

const flagsOnlyUnacked = ref(true)
const flagTypeFilter = ref('')
const depFilters = ref({ status: '', agent_did: '', organization_id: '' })

const activeTab = ref<'deployments' | 'failing' | 'flags'>('deployments')

const tabs = computed(() => [
  { id: 'deployments' as const, label: t('adminCicdView.tabs.deployments'), count: deploymentsRead.value ? deployments.value.length : undefined },
  { id: 'failing'     as const, label: t('adminCicdView.tabs.failing'),     count: summary.value?.deployments.top_failing_agents.length },
  { id: 'flags'       as const, label: t('adminCicdView.tabs.flags'),       count: flagsRead.value ? flagsRows.value.length : undefined },
])

const windowLabel = computed(() => windowHours.value >= 24 ? `${windowHours.value/24}d` : `${windowHours.value}h`)
const flagsUnackedTotal = computed(() => Object.values(flagsByType.value).reduce((a,b)=>a+b,0))
const flagsByTypeStr   = computed(() => Object.entries(flagsByType.value).map(([k,v])=>`${k}: ${v}`).join('  ·  '))
const topFailDid       = computed(() => summary.value?.deployments.top_failing_agents[0]?.did || '')
const topFailCount     = computed(() => summary.value?.deployments.top_failing_agents[0]?.fail_count || 0)

function shortDid(did: string): string {
  if (!did) return '—'
  return did.length > 28 ? did.slice(0, 24) + '…' : did
}
function fromNow(ts: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}

// §pass50.1 — agent name resolution. Populated from /agent-cards/?include_federated
// + cached per session. Falls back to shortDid when name unknown.
const agentNames = ref<Record<string, string>>({})
async function loadAgentNames(dids: string[]) {
  const missing = dids.filter(d => d && !(d in agentNames.value))
  if (missing.length === 0) return
  try {
    const dedup = Array.from(new Set(missing))
    const tok = readAccessToken() || ''
    const headers: Record<string, string> = {}
    if (tok) headers['Authorization'] = `Bearer ${tok}`
    const map: Record<string, string> = { ...agentNames.value }
    // §pass50.2 — exact-DID lookup per agent
    await Promise.all(dedup.map(async (did) => {
      try {
        const res = await fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`, { headers })
        if (!res.ok) { map[did] = shortDid(did); return }
        const data = await res.json()
        map[did] = data?.name || shortDid(did)
      } catch {
        map[did] = shortDid(did)
      }
    }))
    agentNames.value = map
  } catch (_) { /* ignore — fall back to shortDid */ }
}
function agentLabel(did: string): string {
  if (!did) return '—'
  return agentNames.value[did] || shortDid(did)
}

// §pass50.1 — deployment detail drawer
const detailDeployment = ref<CicdAdminDeployment | null>(null)
function openDeploymentDetail(d: CicdAdminDeployment) {
  detailDeployment.value = d
}
function closeDeploymentDetail() {
  detailDeployment.value = null
}

async function loadSummary() {
  try { summary.value = await cicdAdminService.getFleetSummary(windowHours.value) }
  catch (e: any) { error.value = `Failed to load summary: ${e.message}` }
}
async function loadDeployments() {
  try {
    const r = await cicdAdminService.listDeployments({
      status: depFilters.value.status || undefined,
      agent_did: depFilters.value.agent_did || undefined,
      organization_id: depFilters.value.organization_id || undefined,
      limit: 50,
    })
    deployments.value = r.items
    deploymentsRead.value = true
    // §pass50.1 — resolve agent names for the deployment rows + top-failing tile
    const dids = [
      ...r.items.map(d => d.agent_did),
      ...(summary.value?.deployments.top_failing_agents || []).map(x => x.did),
    ]
    loadAgentNames(dids).catch(() => {})
  } catch (e: any) { error.value = `Failed to load deployments: ${e.message}` }
}
async function loadFlags() {
  try {
    const r = await cicdAdminService.listFlagsGlobal({
      flag_type: flagTypeFilter.value || undefined,
      only_unacknowledged: flagsOnlyUnacked.value,
      since_hours: windowHours.value,
      limit: 200,
    })
    flagsRows.value = r.flags
    flagsByType.value = Object.fromEntries(Object.entries(r.by_type))
    flagsRead.value = true
    // §pass50.1 — resolve agent names for the flag rows too
    loadAgentNames(r.flags.map(f => f.agent_did)).catch(() => {})
  } catch (e: any) { error.value = `Failed to load flags: ${e.message}` }
}

async function ackFlag(f: AgentFlag) {
  try {
    const notes = window.prompt('Optional notes for this acknowledgement:', '')
    await cicdAdminService.acknowledgeFlag(f.agent_did, f.id, notes || undefined)
    await loadFlags()
    await loadSummary()
  } catch (e: any) {
    error.value = `Failed to acknowledge: ${e.message}`
  }
}

async function refreshAll() {
  error.value = ''
  loading.value = true
  await Promise.all([loadSummary(), loadDeployments(), loadFlags()])
  loading.value = false
}
function resetDeployFilters() {
  depFilters.value = { status: '', agent_did: '', organization_id: '' }
  loadDeployments()
}
function exportDeploymentsCsv() {
  downloadCsv(deployments.value, [
    { label: 'id', value: r => r.id },
    { label: 'agent_did', value: r => r.agent_did },
    { label: 'pipeline_name', value: r => r.pipeline_name ?? '' },
    { label: 'version', value: r => r.version ?? '' },
    { label: 'status', value: r => r.status },
    { label: 'environment', value: r => r.environment },
    { label: 'organization_id', value: r => r.organization_id ?? '' },
    { label: 'started_at', value: r => r.started_at },
    { label: 'completed_at', value: r => r.completed_at ?? '' },
    { label: 'duration_seconds', value: r => r.duration_seconds ?? '' },
    { label: 'error_message', value: r => r.error_message ?? '' },
  ], `admin_cicd_deployments_${csvFilenameTimestamp()}.csv`)
}

watch(windowHours, refreshAll)

let timer: any = null
onMounted(() => {
  refreshAll()
  timer = setInterval(() => { if (autoRefresh.value && !document.hidden) refreshAll() }, 30000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
/* §pass49 F1 — theme-aligned palette. Mirrors AdminReactors pattern
   (memory: feedback_admincanaries_theme_polish.md). One :scope-level
   alias block lets `theme-neural` / `theme-sovereign` / custom each
   recolor the whole view via a single --nc-primary switch. */
.ac-root {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366;
  --green: #00ff88;
  --amber: #ff9500;
  --muted: #6b7785;
  --border: rgba(var(--cyan-rgb), 0.18);
  --surface: #0a0d16;
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;

  position: relative;
  min-height: 100vh;
  /* §pass50.1 — background removed; DashboardLayout's <ViewAmbient> paints
     the admin tone via route.meta.viewAmbientTone='admin'. */
  color: var(--text-bright);
  padding: 24px;
  overflow-x: hidden;
}

.ac-content { position: relative; z-index: 1; max-width: 1500px; margin: 0 auto; }

/* Hero */
.ac-hero {
  display: flex; justify-content: space-between; align-items: flex-start;
  flex-wrap: wrap; gap: 12px; margin-bottom: 22px;
}
.ac-hero-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ac-chip-hero {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px; border-radius: 12px;
  background: rgba(var(--cyan-rgb), 0.08);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: var(--cyan); font-size: 10px; font-weight: 700;
  letter-spacing: 0.16em; text-transform: uppercase;
}
.ac-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.ac-h1 { font-size: 28px; font-weight: 800; margin: 8px 0 4px 0; color: var(--text-bright); letter-spacing: -0.02em; }
.ac-lead { font-size: 13px; color: var(--muted); margin: 0; max-width: 720px; }

/* Stat tiles */
.ac-stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px; margin-bottom: 22px;
}
.ac-stat {
  background: rgba(var(--cyan-rgb), 0.03);
  border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px;
  position: relative;
}
.ac-stat--warn { border-color: rgba(var(--amber, #ff9500), 0.45); background: rgba(255, 149, 0, 0.04); }
.ac-stat-label {
  font-size: 10px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.1em; font-weight: 700;
}
.ac-stat-value { font-size: 26px; font-weight: 800; margin-top: 6px; color: var(--text-bright); }
.ac-stat-value--did { font-size: 13px; font-family: var(--mono); }
.ac-stat-sub { font-size: 11px; color: var(--muted); margin-top: 6px; }
.ac-ok { color: var(--green); }
.ac-fail { color: var(--red); }
.ac-warn { color: var(--amber); }
.ac-sep { color: var(--muted); margin: 0 6px; }

/* Tabs */
.ac-tabs { display: flex; gap: 2px; margin-bottom: 14px; border-bottom: 1px solid var(--border); }
.ac-tab {
  background: transparent; border: none; color: var(--muted);
  padding: 10px 16px; cursor: pointer; font-size: 12px; font-weight: 700;
  letter-spacing: 0.04em; text-transform: uppercase;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
}
.ac-tab:hover { color: var(--text-bright); }
.ac-tab.is-active { color: var(--cyan); border-bottom-color: var(--cyan); }
.ac-tab-count {
  margin-left: 6px; background: rgba(var(--cyan-rgb), 0.15);
  padding: 2px 7px; border-radius: 10px; font-size: 10px; color: var(--cyan);
}

/* Panel + filterbar */
.ac-panel {
  background: rgba(var(--cyan-rgb), 0.025);
  border: 1px solid var(--border);
  border-radius: 8px; padding: 14px;
}
.ac-filterbar {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  margin-bottom: 12px;
}
.ac-spacer { flex: 1; }
.ac-toggle { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; cursor: pointer; }
.ac-toggle input { accent-color: var(--cyan); }
.ac-input {
  background: rgba(0,0,0,0.35);
  color: var(--text-bright);
  border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 10px; font-size: 12px;
  font-family: var(--mono);
}
.ac-input--wide { min-width: 240px; }
.ac-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }
.ac-btn {
  background: rgba(var(--cyan-rgb), 0.12);
  color: var(--cyan);
  border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 4px; padding: 6px 14px; font-size: 12px; cursor: pointer; font-weight: 600;
  transition: all 0.15s;
}
.ac-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); transform: translateY(-1px); }
.ac-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ac-btn-primary {
  background: var(--cyan); color: var(--surface);
  border-color: var(--cyan); font-weight: 700;
}
.ac-btn-primary:hover:not(:disabled) {
  background: var(--cyan); filter: brightness(1.15);
}
.ac-btn-ghost {
  background: transparent;
  color: var(--muted);
  border-color: var(--border);
}
.ac-btn-sm { padding: 4px 10px; font-size: 10px; }

/* Table */
.ac-table-wrap { overflow-x: auto; border-radius: 4px; }
/* §pass50.1 — clickable rows + stat tiles */
.ac-row--clickable { cursor: pointer; }
.ac-row--clickable:hover td { background: rgba(var(--cyan-rgb), 0.04); }
.ac-stat--clickable { cursor: pointer; transition: border-color 0.15s, transform 0.05s; }
.ac-stat--clickable:hover { border-color: rgba(var(--cyan-rgb), 0.55); transform: translateY(-1px); }

/* §pass50.1 — Deployment detail drawer */
.dd-drawer {
  position: fixed; inset: 0; z-index: 10050;
  display: flex; justify-content: flex-end;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}
.dd-drawer__scrim { position: absolute; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(3px); }
.dd-drawer__panel {
  position: relative; width: min(480px, 94vw); height: 100vh; background: #0c1320;
  border-left: 1px solid rgba(var(--cyan-rgb), 0.22); display: flex; flex-direction: column;
  box-shadow: -10px 0 40px rgba(0,0,0,0.6); color: var(--text-bright);
}
.dd-drawer__head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 18px 14px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.dd-drawer__head h3 { margin: 0; font-size: 14px; font-weight: 700; }
.dd-drawer__close {
  background: transparent; border: none; color: #6b7785; font-size: 22px; cursor: pointer;
  width: 32px; height: 32px; display: grid; place-items: center; border-radius: 4px;
}
.dd-drawer__close:hover { background: rgba(255,68,68,0.1); color: #ff4444; }
.dd-drawer__body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; flex: 1; overflow-y: auto; }
.dd-drawer__row { display: flex; flex-direction: column; gap: 4px; }
.dd-drawer__row-label {
  font-size: 9.5px; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--cyan-rgb), 0.55); font-weight: 700;
}
.dd-drawer__row-value { font-size: 13px; color: #c8d8e8; word-break: break-all; }
.dd-drawer__row-value code {
  background: rgba(255,255,255,0.04); padding: 2px 6px; border-radius: 3px;
  font-size: 12px; color: #b0c0d0;
}
.dd-drawer__err {
  white-space: pre-wrap; background: rgba(255, 68, 68, 0.06);
  border: 1px solid rgba(255, 68, 68, 0.25); padding: 10px; border-radius: 4px;
  color: #ffb4b4; font-size: 11px; line-height: 1.5;
}
.dd-drawer__foot {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 14px 18px; border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.dd-drawer-enter-active, .dd-drawer-leave-active { transition: opacity 0.18s; }
.dd-drawer-enter-from, .dd-drawer-leave-to { opacity: 0; }
.dd-drawer-enter-active .dd-drawer__panel, .dd-drawer-leave-active .dd-drawer__panel {
  transition: transform 0.22s ease;
}
.dd-drawer-enter-from .dd-drawer__panel, .dd-drawer-leave-to .dd-drawer__panel {
  transform: translateX(100%);
}
@media (prefers-reduced-motion: reduce) {
  .dd-drawer-enter-active, .dd-drawer-leave-active,
  .dd-drawer-enter-active .dd-drawer__panel, .dd-drawer-leave-active .dd-drawer__panel { transition: none; }
}
.ac-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ac-table th {
  text-align: left; padding: 10px 12px;
  color: var(--muted); font-weight: 700; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border);
  background: rgba(0,0,0,0.2);
}
.ac-table td { padding: 8px 12px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.06); vertical-align: middle; }
.ac-row:hover td { background: rgba(var(--cyan-rgb), 0.04); }
.ac-mono { font-family: var(--mono); font-size: 11px; }
.ac-muted { color: var(--muted); font-size: 11px; }
.ac-link { color: var(--cyan); text-decoration: none; }
.ac-link:hover { text-decoration: underline; }
.ac-empty { text-align: center; padding: 24px; color: var(--muted); }
.ac-mini {
  display: inline-block; padding: 1px 6px; border-radius: 6px; font-size: 9px;
  background: rgba(var(--cyan-rgb), 0.15); color: var(--cyan); font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em;
}

/* Status pills */
.ac-pill {
  display: inline-block; padding: 2px 9px; border-radius: 10px;
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
}
.ac-st-success { background: rgba(0, 255, 136, 0.16); color: var(--green); }
.ac-st-failed  { background: rgba(255, 51, 102, 0.18); color: var(--red); }
.ac-st-pending,
.ac-st-running { background: rgba(255, 149, 0, 0.18); color: var(--amber); }
.ac-st-cancelled { background: rgba(120,120,120,0.18); color: var(--muted); }
.ac-st-flag { background: rgba(255, 178, 69, 0.18); color: var(--amber); }

/* Error banner */
.ac-error {
  margin-top: 14px; padding: 10px 14px;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.35);
  color: var(--red); border-radius: 4px; font-size: 12px;
}
</style>
