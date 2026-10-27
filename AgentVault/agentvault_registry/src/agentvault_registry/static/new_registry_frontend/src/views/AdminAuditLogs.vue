<template>
  <div class="al-root">
    <!-- §pass50.1 — ambient provided by DashboardLayout's <ViewAmbient>
         per route.meta.viewAmbientTone='admin'. Local ambient removed. -->

    <div class="al-content">
      <div class="al-hero" data-tour="audit-hero">
        <div>
          <div class="al-chip-hero"><span class="al-chip-dot"></span>ADMINISTRATION · AUDIT</div>
          <h1 class="al-h1">{{ t('adminAuditLogsView.title') }}</h1>
          <p class="al-lead">{{ t('adminAuditLogsView.subtitle') }}</p>
        </div>
        <div class="al-hero-actions">
          <label class="al-toggle">
            <input type="checkbox" v-model="autoRefresh" />
            <span>{{ t('adminAuditLogsView.autoRefresh') }}</span>
          </label>
          <select v-model.number="sinceHours" class="al-input" @change="load" :aria-label="t('adminAuditLogsView.sinceAria', 'Time window')">
            <option :value="1">1h</option>
            <option :value="6">6h</option>
            <option :value="24">24h</option>
            <option :value="168">7d</option>
            <option :value="720">30d</option>
          </select>
          <button class="al-btn al-btn-primary" @click="load" :disabled="loading">
            {{ loading ? '…' : t('adminAuditLogsView.refresh') }}
          </button>
        </div>
      </div>

      <!-- Severity breakdown tiles — clickable to apply severity filter (§pass50.1) -->
      <div class="al-tile-row">
        <button
          v-for="ti in tileBreakdown"
          :key="ti.label"
          type="button"
          class="al-tile al-tile--clickable"
          :class="[`al-tile--${ti.label}`, { 'al-tile--active': filters.severity === ti.label }]"
          :title="`Filter to ${ti.label} severity`"
          @click="toggleSeverityFilter(ti.label)"
        >
          <div class="al-tile-label">{{ ti.label }}</div>
          <div class="al-tile-value">{{ rowsRead ? ti.count : '—' }}</div>
        </button>
      </div>

      <!-- Filter bar -->
      <div class="al-panel">
        <div class="al-filterbar">
          <input v-model="filters.action" :placeholder="t('adminAuditLogsView.filters.actionPlaceholder')" class="al-input al-input--wide" @keyup.enter="load" />
          <input v-model="filters.actor_id" :placeholder="t('adminAuditLogsView.filters.actorPlaceholder')" class="al-input" @keyup.enter="load" />
          <input v-model="filters.target_id" :placeholder="t('adminAuditLogsView.filters.targetPlaceholder')" class="al-input al-input--wide" @keyup.enter="load" />
          <select v-model="filters.severity" class="al-input" @change="load" :aria-label="t('adminAuditLogsView.severityAria', 'Severity')">
            <option value="">{{ t('adminAuditLogsView.filters.anySeverity') }}</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="error">error</option>
            <option value="critical">critical</option>
          </select>
          <button class="al-btn" @click="load">{{ t('adminAuditLogsView.filters.apply') }}</button>
          <button class="al-btn al-btn-ghost" @click="reset">{{ t('adminAuditLogsView.filters.reset') }}</button>
          <span class="al-spacer"></span>
          <button class="al-btn al-btn-ghost" @click="exportCsv" :disabled="!rows.length">{{ t('adminAuditLogsView.export') }}</button>
        </div>

        <div class="al-table-wrap">
          <table class="al-table">
            <thead>
              <tr>
                <th>{{ t('adminAuditLogsView.cols.time') }}</th>
                <th>{{ t('adminAuditLogsView.cols.action') }}</th>
                <th>{{ t('adminAuditLogsView.cols.actor') }}</th>
                <th>{{ t('adminAuditLogsView.cols.target') }}</th>
                <th>{{ t('adminAuditLogsView.cols.severity') }}</th>
                <th>{{ t('adminAuditLogsView.cols.outcome') }}</th>
                <th>{{ t('adminAuditLogsView.cols.details') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in rows"
                :key="r.id"
                class="al-row al-row--clickable"
                :title="`Click for full details · ${r.action}`"
                @click="openDetail(r)"
              >
                <td class="al-muted al-nowrap">{{ fromNow(r.timestamp) }}</td>
                <td class="al-mono">
                  <span :class="['al-action-tag', actionPrefixClass(r.action)]">{{ actionPrefix(r.action) }}</span>
                  <span class="al-action-suffix">{{ actionSuffix(r.action) }}</span>
                </td>
                <td class="al-mono" @click.stop>
                  <RouterLink v-if="r.actor_id && r.actor_type === 'admin'" :to="`/admin/developers/${r.actor_id}`" class="al-link" :title="`admin:${r.actor_id}`">
                    {{ actorLabel(r) }}
                  </RouterLink>
                  <span v-else class="al-muted">{{ r.actor_type || '—' }}:{{ r.actor_id || '—' }}</span>
                </td>
                <td class="al-mono" @click.stop>
                  <RouterLink v-if="r.target_id && r.target_type === 'agent'" :to="`/agent/${r.target_id}/ci-cd`" class="al-link" :title="r.target_id">
                    {{ targetLabel(r) }}
                  </RouterLink>
                  <RouterLink v-else-if="r.target_id && r.target_type === 'developer'" :to="`/admin/developers/${r.target_id}`" class="al-link">
                    dev:{{ r.target_id }}
                  </RouterLink>
                  <span v-else class="al-muted">{{ r.target_type ? `${r.target_type}:` : '' }}{{ shortDid(r.target_id || '') || '—' }}</span>
                </td>
                <td><span :class="['al-sev', 'al-sev--' + r.severity]">{{ r.severity }}</span></td>
                <td>{{ r.outcome }}</td>
                <td class="al-details">{{ summarizeDetails(r.details) }}</td>
              </tr>
              <tr v-if="!rows.length && !loading && rowsRead"><td colspan="7" class="al-empty">{{ t('adminAuditLogsView.empty') }}</td></tr>
              <!-- §DESKCHROME: loading row only before FIRST data — the 30s autoRefresh poll must not flash the table -->
              <tr v-if="loading && !rows.length"><td colspan="7" class="al-empty">{{ t('adminAuditLogsView.loading') }}</td></tr>
            </tbody>
          </table>
        </div>

        <div class="al-pager">
          <button class="al-btn al-btn-ghost" :disabled="offset === 0" @click="prevPage">‹ {{ t('adminAuditLogsView.prev') }}</button>
          <span class="al-muted">Page {{ Math.floor(offset / limit) + 1 }} · {{ rows.length }} {{ rows.length === 1 ? 'row' : 'rows' }}</span>
          <button class="al-btn al-btn-ghost" :disabled="rows.length < limit" @click="nextPage">{{ t('adminAuditLogsView.next') }} ›</button>
        </div>
      </div>

      <div v-if="error" class="al-error">{{ error }}</div>
    </div>

    <!-- §pass50.1 — Audit log row detail drawer (right-side panel) -->
    <Transition name="ald-drawer">
      <aside v-if="detailRow" class="ald-drawer" role="dialog" aria-label="Audit log row detail">
        <div class="ald-drawer__scrim" @click="closeDetail" aria-hidden="true" />
        <div class="ald-drawer__panel" @click.stop>
          <header class="ald-drawer__head">
            <div>
              <span :class="['al-action-tag', actionPrefixClass(detailRow.action)]" style="margin-right:6px;">{{ actionPrefix(detailRow.action) }}</span>
              <span class="ald-drawer__action-name">{{ actionSuffix(detailRow.action) }}</span>
            </div>
            <button class="ald-drawer__close" @click="closeDetail" aria-label="Close">&times;</button>
          </header>
          <div class="ald-drawer__body">
            <div class="ald-row">
              <div class="ald-label">When</div>
              <div class="ald-value">{{ detailRow.timestamp }} <span class="al-muted">({{ fromNow(detailRow.timestamp) }})</span></div>
            </div>
            <div class="ald-row">
              <div class="ald-label">Actor</div>
              <div class="ald-value">{{ actorLabel(detailRow) }} <code v-if="detailRow.actor_id">[{{ detailRow.actor_type }}:{{ detailRow.actor_id }}]</code></div>
            </div>
            <div class="ald-row" v-if="detailRow.target_id">
              <div class="ald-label">Target</div>
              <div class="ald-value">
                <code>{{ detailRow.target_type ? detailRow.target_type + ':' : '' }}{{ detailRow.target_id }}</code>
              </div>
            </div>
            <div class="ald-row">
              <div class="ald-label">Severity</div>
              <div class="ald-value"><span :class="['al-sev', 'al-sev--' + detailRow.severity]">{{ detailRow.severity }}</span></div>
            </div>
            <div class="ald-row">
              <div class="ald-label">Outcome</div>
              <div class="ald-value">{{ detailRow.outcome }}</div>
            </div>
            <div class="ald-row" v-if="detailRow.details">
              <div class="ald-label">Details (raw)</div>
              <pre class="ald-json">{{ prettifyDetails(detailRow.details) }}</pre>
            </div>
            <div class="ald-row">
              <div class="ald-label">Row ID</div>
              <div class="ald-value"><code>{{ detailRow.id }}</code></div>
            </div>
          </div>
          <footer class="ald-drawer__foot">
            <RouterLink
              v-if="detailRow.target_id && detailRow.target_type === 'agent'"
              :to="`/agent/${detailRow.target_id}/ci-cd`"
              class="al-btn"
              @click="closeDetail"
            >Open agent CI/CD &rsaquo;</RouterLink>
            <RouterLink
              v-if="detailRow.actor_id && detailRow.actor_type === 'admin'"
              :to="`/admin/developers/${detailRow.actor_id}`"
              class="al-btn"
              @click="closeDetail"
            >Open actor profile &rsaquo;</RouterLink>
            <button class="al-btn" @click="closeDetail">Close</button>
          </footer>
        </div>
      </aside>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { cicdAdminService, type AuditLogRow } from '@/services/api/cicdAdmin'
import { useI18n } from '@/composables/useI18n'
import { readAccessToken } from '@/services/accessToken'
import { downloadCsv, csvFilenameTimestamp } from '@/components/common/csvExport'
dayjs.extend(relativeTime)
const { t } = useI18n()

const rows = ref<AuditLogRow[]>([])
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const rowsRead = ref(false)
const sinceHours = ref(24)
const limit = 200
const offset = ref(0)
const autoRefresh = ref(true)
const loading = ref(false)
const error = ref('')
const filters = ref<{action: string; actor_id: string; target_id: string; severity: string}>({
  action: '', actor_id: '', target_id: '', severity: ''
})

const tileBreakdown = computed(() => {
  const buckets: Record<string, number> = { info: 0, warning: 0, error: 0, critical: 0 }
  rows.value.forEach(r => { if (r.severity in buckets) buckets[r.severity]++ })
  return Object.entries(buckets).map(([label, count]) => ({ label, count }))
})

// §pass50.1 — detail drawer state
const detailRow = ref<AuditLogRow | null>(null)
function openDetail(r: AuditLogRow) { detailRow.value = r }
function closeDetail() { detailRow.value = null }

// §pass50.1 — actor email resolution (cached per-session by actor_id)
const actorEmails = ref<Record<string, string>>({})
async function loadActorEmails(ids: number[]) {
  const missing = ids.filter(id => id != null && !(String(id) in actorEmails.value))
  if (missing.length === 0) return
  try {
    // Fetch each developer in parallel (admin endpoint; small N typically)
    const dedup = Array.from(new Set(missing))
    const tok = readAccessToken()
    const results = await Promise.all(dedup.map(id =>
      fetch(`/api/v1/admin/developers/${id}`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} })
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
    ))
    const map = { ...actorEmails.value }
    for (let i = 0; i < dedup.length; i++) {
      const id = dedup[i]
      const dev = results[i]
      map[String(id)] = dev?.email || `admin:${id}`
    }
    actorEmails.value = map
  } catch (_) { /* swallow */ }
}
function actorLabel(r: AuditLogRow): string {
  if (!r.actor_id) return r.actor_type || '—'
  const cached = actorEmails.value[String(r.actor_id)]
  if (cached) return cached
  return `${r.actor_type || 'actor'}:${r.actor_id}`
}

// §pass50.1 — target label (agent name for agent-type, dev:id for dev-type)
const targetAgentNames = ref<Record<string, string>>({})
// §FESUITE: one lookup per DISTINCT agent, four at a time. A page whose rows named one agent six times asked six times
// at once, and fifty lookups in one burst every 30 s is what tipped a small frame's connection pool ("too many clients
// already" -> 500 on these very reads, measured on sbx-alpha). Only a 404 is remembered (the agent is not on this
// frame); any other failure is not cached as the agent's name, so the next refresh asks again.
const TARGET_LOOKUPS_AT_ONCE = 4
async function loadTargetAgentNames(dids: string[]) {
  const missing = Array.from(new Set(dids.filter(d => d && !(d in targetAgentNames.value))))
  if (missing.length === 0) return
  const tok = readAccessToken() || ''
  const headers: Record<string, string> = {}
  if (tok) headers['Authorization'] = `Bearer ${tok}`
  const found: Record<string, string> = {}
  let next = 0
  const lookUp = async () => {
    while (next < missing.length) {
      const did = missing[next++]
      try {
        // §pass50.2 — exact-DID lookup per agent
        const res = await fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`, { headers })
        if (res.status === 404) { found[did] = shortDid(did); continue }
        if (!res.ok) continue
        const data = await res.json()
        found[did] = data?.name || shortDid(did)
      } catch { /* not cached: targetLabel() shows the short DID meanwhile */ }
    }
  }
  await Promise.all(Array.from({ length: Math.min(TARGET_LOOKUPS_AT_ONCE, missing.length) }, lookUp))
  targetAgentNames.value = { ...targetAgentNames.value, ...found }
}
function targetLabel(r: AuditLogRow): string {
  if (!r.target_id) return '—'
  if (r.target_type === 'agent') {
    return targetAgentNames.value[r.target_id] || shortDid(r.target_id)
  }
  return shortDid(r.target_id) || r.target_id
}

// §pass50.1 — action prefix tagging (admin.X / security.X / broadcast.X / cicd.X)
function actionPrefix(action: string): string {
  const dot = action.indexOf('.')
  return dot > 0 ? action.slice(0, dot) : action
}
function actionSuffix(action: string): string {
  const dot = action.indexOf('.')
  return dot > 0 ? action.slice(dot + 1) : ''
}
function actionPrefixClass(action: string): string {
  const p = actionPrefix(action)
  if (p === 'admin') return 'al-action-tag--admin'
  if (p === 'security') return 'al-action-tag--security'
  if (p === 'broadcast') return 'al-action-tag--broadcast'
  if (p === 'cicd') return 'al-action-tag--cicd'
  if (p === 'org' || p === 'organization') return 'al-action-tag--org'
  return 'al-action-tag--other'
}

// §pass50.1 — collapse a JSON-stringified details blob into a 1-line summary
function summarizeDetails(d: string | null | undefined): string {
  if (!d) return '—'
  try {
    const obj = JSON.parse(d)
    if (typeof obj !== 'object' || obj === null) return String(obj).slice(0, 60)
    const keys = Object.keys(obj)
    if (keys.length === 0) return '{}'
    return keys.slice(0, 3).map(k => `${k}=${JSON.stringify(obj[k])}`).join(' · ').slice(0, 80)
  } catch {
    return d.length > 60 ? d.slice(0, 60) + '…' : d
  }
}
function prettifyDetails(d: string | null | undefined): string {
  if (!d) return ''
  try {
    return JSON.stringify(JSON.parse(d), null, 2)
  } catch {
    return d
  }
}

// §pass50.1 — tile-as-filter
function toggleSeverityFilter(label: string) {
  filters.value.severity = filters.value.severity === label ? '' : label
  load()
}

function shortDid(s: string): string {
  if (!s) return ''
  return s.length > 32 ? s.slice(0, 28) + '…' : s
}
function fromNow(ts: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}

async function _enrichLabels() {
  // §pass50.1 — fire-and-forget actor/agent name resolution after a load
  const actorIds: number[] = []
  const agentDids: string[] = []
  for (const r of rows.value) {
    if (r.actor_id && r.actor_type === 'admin') actorIds.push(r.actor_id as any)
    if (r.target_id && r.target_type === 'agent') agentDids.push(r.target_id)
  }
  loadActorEmails(actorIds).catch(() => {})
  loadTargetAgentNames(agentDids).catch(() => {})
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const r = await cicdAdminService.listAuditLogs({
      action: filters.value.action || undefined,
      actor_id: filters.value.actor_id || undefined,
      target_id: filters.value.target_id || undefined,
      severity: filters.value.severity || undefined,
      since_hours: sinceHours.value,
      limit, offset: offset.value,
    })
    rows.value = r.items
    rowsRead.value = true
    _enrichLabels()  // §pass50.1 — resolve actor + agent labels in background
  } catch (e: any) {
    error.value = `Failed to load audit logs: ${e.message}`
  } finally {
    loading.value = false
  }
}
function reset() {
  filters.value = { action: '', actor_id: '', target_id: '', severity: '' }
  offset.value = 0
  load()
}
function nextPage() { offset.value += limit; load() }
function prevPage() { offset.value = Math.max(0, offset.value - limit); load() }
function exportCsv() {
  downloadCsv(rows.value, [
    { label: 'timestamp', value: r => r.timestamp },
    { label: 'action', value: r => r.action },
    { label: 'actor_type', value: r => r.actor_type ?? '' },
    { label: 'actor_id', value: r => r.actor_id ?? '' },
    { label: 'target_type', value: r => r.target_type ?? '' },
    { label: 'target_id', value: r => r.target_id ?? '' },
    { label: 'event_type', value: r => r.event_type },
    { label: 'severity', value: r => r.severity },
    { label: 'outcome', value: r => r.outcome },
    { label: 'details', value: r => r.details ?? '' },
    { label: 'error_message', value: r => r.error_message ?? '' },
    { label: 'correlation_id', value: r => r.correlation_id ?? '' },
    { label: 'request_id', value: r => r.request_id ?? '' },
  ], `admin_audit_logs_${csvFilenameTimestamp()}.csv`)
}

let timer: any = null
onMounted(() => {
  load()
  timer = setInterval(() => { if (autoRefresh.value && !document.hidden) load() }, 30000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.al-root {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366;
  --green: #00ff88;
  --amber: #ff9500;
  --muted: #788593;  /* §FESUITE: 4.75:1 on the darkest row (#6b7785 was 3.9-4.2:1) */
  --border: rgba(var(--cyan-rgb), 0.18);
  --surface: #0a0d16;
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;

  position: relative; min-height: 100vh;
  /* §pass50.1 — background removed; layout's <ViewAmbient> paints the admin tone. */
  color: var(--text-bright);
  padding: 24px; overflow-x: hidden;
}
.al-content { position: relative; z-index: 1; max-width: 1500px; margin: 0 auto; }

.al-hero { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.al-hero-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.al-chip-hero {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px; border-radius: 12px;
  background: rgba(var(--cyan-rgb), 0.08); border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: var(--cyan); font-size: 10px; font-weight: 700;
  letter-spacing: 0.16em; text-transform: uppercase;
}
.al-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }
.al-h1 { font-size: 28px; font-weight: 800; margin: 8px 0 4px 0; color: var(--text-bright); letter-spacing: -0.02em; }
.al-lead { font-size: 13px; color: var(--muted); margin: 0; }

/* four 110 px floors and their gaps need ~470 px: the last tile ran past a phone's edge, two columns there (the camera,
   2026-10-13) */
.al-tile-row { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 10px; margin-bottom: 16px; }
@media (max-width: 640px) {
  .al-tile-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.al-tile {
  background: rgba(var(--cyan-rgb), 0.03); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px 14px;
}
.al-tile-label { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
.al-tile-value { font-size: 22px; font-weight: 800; margin-top: 4px; }
.al-tile--info     .al-tile-value { color: #9ad6ff; }
.al-tile--warning  .al-tile-value { color: var(--amber); }
.al-tile--error    .al-tile-value { color: var(--red); }
.al-tile--critical .al-tile-value { color: #ff2d4f; }

.al-panel {
  background: rgba(var(--cyan-rgb), 0.025); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px;
}
.al-filterbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.al-spacer { flex: 1; }
.al-toggle { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; cursor: pointer; }
.al-toggle input { accent-color: var(--cyan); }
.al-input {
  background: rgba(0,0,0,0.35); color: var(--text-bright);
  border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px;
  font-size: 12px; font-family: var(--mono);
}
.al-input--wide { min-width: 220px; }
.al-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }
.al-btn {
  background: rgba(var(--cyan-rgb), 0.12); color: var(--cyan);
  border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 4px; padding: 6px 14px; font-size: 12px; cursor: pointer; font-weight: 600;
}
.al-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); }
.al-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.al-btn-primary { background: var(--cyan); color: var(--surface); border-color: var(--cyan); font-weight: 700; }
.al-btn-ghost { background: transparent; color: var(--muted); border-color: var(--border); }

.al-table-wrap { overflow-x: auto; border-radius: 4px; }
.al-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.al-table th {
  text-align: left; padding: 10px 12px; color: var(--muted);
  font-weight: 700; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.2);
}
.al-table td { padding: 7px 12px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.06); }
.al-row:hover td { background: rgba(var(--cyan-rgb), 0.04); }
/* §pass50.1 — additions */
.al-row--clickable { cursor: pointer; }
.al-tile--clickable {
  cursor: pointer; border: 1px solid rgba(var(--cyan-rgb), 0.15);
  background: rgba(var(--cyan-rgb), 0.02); padding: 12px 14px;
  text-align: left; transition: border-color 0.15s, transform 0.05s, background 0.15s;
  font: inherit; color: inherit;
}
.al-tile--clickable:hover { border-color: rgba(var(--cyan-rgb), 0.55); transform: translateY(-1px); }
.al-tile--active { border-color: var(--cyan, #00d2d2); background: rgba(var(--cyan-rgb), 0.08); }
.al-action-tag {
  display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px;
  font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  padding: 2px 6px; border-radius: 3px; margin-right: 6px;
  background: rgba(255,255,255,0.04); color: #b0c0d0;
}
.al-action-tag--admin     { background: rgba(59,130,246,0.14); color: #93c5fd; }
.al-action-tag--security  { background: rgba(220,38,38,0.16); color: #fca5a5; }
.al-action-tag--broadcast { background: rgba(var(--cyan-rgb), 0.16); color: var(--cyan, #00d2d2); }
.al-action-tag--cicd      { background: rgba(255,149,0,0.16); color: #ffb24a; }
.al-action-tag--org       { background: rgba(168,85,247,0.18); color: #d8b4fe; }
.al-action-tag--other     { background: rgba(255,255,255,0.06); color: #c8d8e8; }
.al-action-suffix { color: #b0c0d0; font-size: 11px; }

/* Audit log detail drawer */
.ald-drawer {
  position: fixed; inset: 0; z-index: 10050;
  display: flex; justify-content: flex-end;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}
.ald-drawer__scrim { position: absolute; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(3px); }
.ald-drawer__panel {
  position: relative; width: min(520px, 96vw); height: 100vh; background: #0c1320;
  border-left: 1px solid rgba(var(--cyan-rgb), 0.22); display: flex; flex-direction: column;
  box-shadow: -10px 0 40px rgba(0,0,0,0.6); color: var(--text-bright);
}
.ald-drawer__head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 18px 18px 14px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.ald-drawer__action-name { font-size: 14px; font-weight: 700; color: #e8eaed; }
.ald-drawer__close {
  background: transparent; border: none; color: var(--muted); font-size: 22px; cursor: pointer;
  width: 32px; height: 32px; display: grid; place-items: center; border-radius: 4px;
}
.ald-drawer__close:hover { background: rgba(255,68,68,0.1); color: #ff4444; }
.ald-drawer__body { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; flex: 1; overflow-y: auto; }
.ald-row { display: flex; flex-direction: column; gap: 4px; }
.ald-label {
  font-size: 9.5px; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--cyan-rgb), 0.55); font-weight: 700;
}
.ald-value { font-size: 13px; color: #c8d8e8; word-break: break-all; }
.ald-value code {
  background: rgba(255,255,255,0.04); padding: 2px 6px; border-radius: 3px;
  font-size: 12px; color: #b0c0d0;
}
.ald-json {
  background: rgba(0,0,0,0.4); padding: 12px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; line-height: 1.45;
  color: #b0c0d0; max-height: 280px; overflow: auto; white-space: pre-wrap;
}
.ald-drawer__foot {
  display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap;
  padding: 14px 18px; border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
}
.ald-drawer-enter-active, .ald-drawer-leave-active { transition: opacity 0.18s; }
.ald-drawer-enter-from, .ald-drawer-leave-to { opacity: 0; }
.ald-drawer-enter-active .ald-drawer__panel, .ald-drawer-leave-active .ald-drawer__panel {
  transition: transform 0.22s ease;
}
.ald-drawer-enter-from .ald-drawer__panel, .ald-drawer-leave-to .ald-drawer__panel {
  transform: translateX(100%);
}
@media (prefers-reduced-motion: reduce) {
  .ald-drawer-enter-active, .ald-drawer-leave-active,
  .ald-drawer-enter-active .ald-drawer__panel, .ald-drawer-leave-active .ald-drawer__panel { transition: none; }
}
.al-mono { font-family: var(--mono); font-size: 11px; }
.al-muted { color: var(--muted); font-size: 11px; }
.al-nowrap { white-space: nowrap; }
.al-link { color: var(--cyan); text-decoration: none; }
.al-link:hover { text-decoration: underline; }
.al-empty { text-align: center; padding: 24px; color: var(--muted); }
.al-details {
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.al-sev {
  display: inline-block; padding: 2px 8px; border-radius: 8px;
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
}
.al-sev--info     { background: rgba(154, 214, 255, 0.18); color: #9ad6ff; }
.al-sev--warning  { background: rgba(255, 149, 0, 0.20); color: var(--amber); }
.al-sev--error    { background: rgba(255, 51, 102, 0.22); color: var(--red); }
.al-sev--critical { background: rgba(255, 45, 79, 0.28); color: #ff5b76; }

.al-pager { display: flex; gap: 10px; margin-top: 12px; align-items: center; font-size: 11px; }

.al-error {
  margin-top: 14px; padding: 10px 14px;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.35);
  color: var(--red); border-radius: 4px; font-size: 12px;
}
</style>
