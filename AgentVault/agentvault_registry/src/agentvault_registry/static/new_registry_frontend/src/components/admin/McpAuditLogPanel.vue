<!--
  components/admin/McpAuditLogPanel.vue
  =====================================
  AAA+ shared panel for the MCP audit log surface (§pass68).

  Three mount points:
    • /api-keys?tab=mcp-audit — scope="me", developer self-view
    • AdminDevelopers drawer  — scope="admin", actorId={dev.id}
    • AdminAgents drawer      — scope="admin", actorId={agent.did}

  Behavior:
    • Visibility-guarded 30s auto-refresh via usePolledData.
    • Filter chips (outcome × server) persisted to localStorage per-scope.
    • Search by tool-name substring (client-side over the loaded page).
    • Click row → drawer with full details JSON + OPA shadow + request_id.
    • Keyset pagination via next_cursor (Older / Newer).
    • CSV export of the current loaded page via shared downloadCsv helper.
    • Self-watching warning banner when admin scope + actor_id !== self_id.
    • Empty / loading / error states render distinctly.
    • Mono-row table; sovereign-red + neural-cyan + custom-magenta theme tokens.
-->
<template>
  <div class="mcp-panel">
    <!-- Self-watching warning — only in admin scope when reading someone else's log -->
    <div v-if="showSelfWatchWarning" class="mcp-warn" role="alert">
      <span class="mcp-warn-dot"></span>
      <div class="mcp-warn-body">
        <strong>Self-watched read.</strong>
        Opening this audit log writes an <code>admin_read_mcp_audit</code> row into
        <code>{{ subjectLabel || 'this developer' }}</code>'s own MCP audit history.
        They can see that you read it. Use sparingly.
      </div>
    </div>

    <!-- Filter strip -->
    <div class="mcp-filters">
      <div class="mcp-filter-group">
        <span class="mcp-filter-label">OUTCOME</span>
        <button
          v-for="opt in outcomeFilters"
          :key="opt.value"
          class="mcp-chip"
          :class="{ 'mcp-chip--active': filterOutcome === opt.value }"
          @click="setOutcomeFilter(opt.value)"
        >
          <span class="mcp-chip-dot" :class="`mcp-chip-dot--${opt.value || 'all'}`"></span>
          {{ opt.label }}
          <span v-if="opt.count != null" class="mcp-chip-count">{{ opt.count }}</span>
        </button>
      </div>

      <div v-if="scope !== 'org'" class="mcp-filter-group">
        <span class="mcp-filter-label">SERVER</span>
        <button
          v-for="opt in serverFilters"
          :key="opt.value"
          class="mcp-chip"
          :class="{ 'mcp-chip--active': filterServer === opt.value }"
          @click="setServerFilter(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>

      <div class="mcp-filter-search">
        <input
          v-model="searchTool"
          type="text"
          class="mcp-input"
          placeholder="Filter by tool name…"
          aria-label="Filter by tool name"
        />
      </div>

      <div class="mcp-filter-actions">
        <button
          class="mcp-btn mcp-btn--ghost"
          :disabled="loading || !rows.length"
          @click="exportCsv"
          :title="`Download ${filteredRows.length} row(s) as CSV`"
        >
          CSV
        </button>
        <button
          class="mcp-btn mcp-btn--ghost"
          :disabled="loading"
          @click="refresh"
          :title="lastFetchedLabel"
        >
          <span class="mcp-refresh-spinner" :class="{ spinning: loading }"></span>
          Refresh
        </button>
      </div>
    </div>

    <!-- V0650 (d): an org's log says when this registry records no MCP calls, so a quiet log never reads as an idle org -->
    <div v-if="scope === 'org' && recording === false" class="mcp-warn" role="status" data-testid="mcp-org-not-recording">
      <span class="mcp-warn-dot"></span>
      <div class="mcp-warn-body">{{ t('mcpAuditPanel.org.notRecording', 'This registry does not record MCP calls (MCP audit logging is off), so this list stays empty whatever the agents do.') }}</div>
    </div>

    <!-- Status strip -->
    <div class="mcp-status">
      <div class="mcp-status-left">
        <span v-if="(loading || !answered) && !rows.length" class="mcp-status-pill mcp-status-pill--loading">Loading…</span>
        <span v-else-if="error" class="mcp-status-pill mcp-status-pill--error">
          Error: {{ errorMessage }}
        </span>
        <span v-else-if="!rows.length" class="mcp-status-pill mcp-status-pill--empty">No rows</span>
        <template v-else>
          <span class="mcp-status-pill">
            {{ filteredRows.length }} of {{ rows.length }} row{{ rows.length === 1 ? '' : 's' }} shown
          </span>
          <span class="mcp-status-pill mcp-status-pill--muted">
            window {{ pageStartLabel }} → {{ pageEndLabel }}
          </span>
        </template>
      </div>
      <div class="mcp-status-right">
        <span class="mcp-status-pill mcp-status-pill--muted">
          {{ lastFetchedLabel }}
        </span>
      </div>
    </div>

    <!-- Table -->
    <div class="mcp-table-wrap" v-if="rows.length || (answered && !loading && !error)">
      <table class="mcp-table">
        <thead>
          <tr>
            <th class="mcp-th-ts">Timestamp</th>
            <th>Actor</th>
            <th>Tool</th>
            <th class="mcp-th-tier">Tier</th>
            <th class="mcp-th-outcome">Outcome</th>
            <th class="mcp-th-lat">Latency</th>
            <th class="mcp-th-detail"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!filteredRows.length && rows.length" class="mcp-row-empty">
            <td colspan="7">No rows match the current filters.</td>
          </tr>
          <tr v-if="!rows.length && answered && !loading && !error" class="mcp-row-empty">
            <td colspan="7">
              <div class="mcp-empty-state">
                <div class="mcp-empty-title">No MCP tool calls yet.</div>
                <div class="mcp-empty-body" v-if="scope === 'org'" data-testid="mcp-org-empty">
                  {{ t('mcpAuditPanel.org.empty', "None of this organization's agents has called an MCP tool on this registry with its own credentials yet.") }}
                </div>
                <div class="mcp-empty-body" v-else-if="scope === 'me'">
                  Set up an MCP bridge in Claude Desktop or Claude Code, call any tool, and it
                  will land here within seconds. The audit row writer is fire-and-forget — your
                  MCP response will never be blocked by the logger.
                </div>
                <div class="mcp-empty-body" v-else>
                  Either this subject has no MCP audit history on this registry, or all of their
                  recent activity hit a different registry's audit log. Each registry keeps its
                  own log; an API key created on Frame A only writes to Frame A's log.
                </div>
              </div>
            </td>
          </tr>
          <tr
            v-for="row in filteredRows"
            :key="row.id"
            class="mcp-row"
            :class="[`mcp-row--${row.outcome}`, { 'mcp-row--meta': row.event_type === 'admin_read_mcp_audit' }]"
            @click="openDrawer(row)"
          >
            <td class="mcp-cell-ts" :title="row.timestamp">{{ formatTimestamp(row.timestamp) }}</td>
            <td>
              <span class="mcp-actor-pill" :class="`mcp-actor-pill--${row.actor_type}`">
                {{ row.actor_type }}
              </span>
              <span v-if="row.actor_id" class="mcp-actor-id" :title="row.actor_id">{{ (scope === 'org' && actorNames?.[row.actor_id]) || shortActorId(row.actor_id) }}</span>
            </td>
            <td class="mcp-cell-tool">
              <span v-if="row.event_type === 'admin_read_mcp_audit'" class="mcp-meta-label">
                admin read of <code>{{ shortActorId(row.target_id || '?') }}</code>
              </span>
              <code v-else>{{ row.target_id || '—' }}</code>
            </td>
            <td class="mcp-cell-tier">
              <span v-if="row.tier != null" class="mcp-tier-pill" :class="`mcp-tier-pill--${row.tier}`">
                T{{ row.tier }}
              </span>
              <span v-else class="mcp-muted">—</span>
            </td>
            <td>
              <span class="mcp-outcome-pill" :class="`mcp-outcome-pill--${row.outcome}`">
                {{ row.outcome }}
              </span>
              <span v-if="row.is_error === true" class="mcp-outcome-pill mcp-outcome-pill--error" data-testid="mcp-tool-error">
                {{ t('mcpAuditPanel.toolError', 'tool error') }}</span>
            </td>
            <td class="mcp-cell-lat">{{ row.latency_ms != null ? row.latency_ms.toFixed(1) + 'ms' : '—' }}</td>
            <td class="mcp-cell-detail">
              <button class="mcp-row-open" @click.stop="openDrawer(row)" aria-label="Open row details">›</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="mcp-pagination" v-if="rows.length">
      <button
        class="mcp-btn mcp-btn--ghost"
        :disabled="loading || !cursorStack.length"
        @click="prevPage"
      >
        ← Newer
      </button>
      <span class="mcp-pagination-info">
        page {{ cursorStack.length + 1 }}
        <span class="mcp-muted" v-if="nextCursor">·  more available</span>
        <span class="mcp-muted" v-else>·  end of history</span>
      </span>
      <button
        class="mcp-btn mcp-btn--ghost"
        :disabled="loading || !nextCursor"
        @click="nextPage"
      >
        Older →
      </button>
    </div>

    <!-- Drawer — row details -->
    <div v-if="drawerRow" class="mcp-drawer-scrim" @click="closeDrawer">
      <aside class="mcp-drawer" @click.stop role="dialog" aria-label="MCP audit row detail">
        <header class="mcp-drawer-header">
          <div class="mcp-drawer-title">
            <span class="mcp-drawer-badge" :class="`mcp-outcome-pill--${drawerRow.outcome}`">
              {{ drawerRow.outcome }}
            </span>
            <span class="mcp-drawer-tool">{{ drawerRow.target_id || drawerRow.event_type }}</span>
          </div>
          <button class="mcp-drawer-close" @click="closeDrawer" aria-label="Close">×</button>
        </header>

        <div class="mcp-drawer-meta">
          <div class="mcp-drawer-meta-row">
            <span class="mcp-meta-key">Event</span>
            <code>{{ drawerRow.event_type }}</code>
          </div>
          <div class="mcp-drawer-meta-row">
            <span class="mcp-meta-key">Timestamp</span>
            <span>{{ formatTimestampLong(drawerRow.timestamp) }}</span>
          </div>
          <div class="mcp-drawer-meta-row">
            <span class="mcp-meta-key">Actor</span>
            <span class="mcp-actor-pill" :class="`mcp-actor-pill--${drawerRow.actor_type}`">
              {{ drawerRow.actor_type }}
            </span>
            <code v-if="drawerRow.actor_id">{{ drawerRow.actor_id }}</code>
            <span v-if="drawerRow.actor_ip" class="mcp-muted">@ {{ drawerRow.actor_ip }}</span>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerRow.target_id">
            <span class="mcp-meta-key">Target</span>
            <code>{{ drawerRow.target_id }}</code>
            <span v-if="drawerRow.target_type" class="mcp-muted">({{ drawerRow.target_type }})</span>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerRow.tier != null">
            <span class="mcp-meta-key">Tier</span>
            <span class="mcp-tier-pill" :class="`mcp-tier-pill--${drawerRow.tier}`">T{{ drawerRow.tier }}</span>
            <span v-if="drawerRow.is_admin_server" class="mcp-muted">/mcp/admin/rpc</span>
            <span v-else class="mcp-muted">/mcp/rpc</span>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerRow.latency_ms != null">
            <span class="mcp-meta-key">Latency</span>
            <span>{{ drawerRow.latency_ms.toFixed(2) }}ms</span>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerRow.request_id">
            <span class="mcp-meta-key">Request</span>
            <code>{{ drawerRow.request_id }}</code>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerOpaInfo">
            <span class="mcp-meta-key">OPA</span>
            <span class="mcp-opa-pill" :class="drawerOpaInfo.match ? 'mcp-opa-pill--ok' : 'mcp-opa-pill--mismatch'">
              {{ drawerOpaInfo.match ? 'match' : 'mismatch' }}
            </span>
            <span class="mcp-muted">{{ drawerOpaInfo.decision }} · {{ drawerOpaInfo.latency_ms?.toFixed(1) }}ms</span>
          </div>
          <div class="mcp-drawer-meta-row" v-if="drawerRow.error_message">
            <span class="mcp-meta-key">Error</span>
            <span class="mcp-error-message">{{ drawerRow.error_message }}</span>
          </div>
        </div>

        <div class="mcp-drawer-section" v-if="drawerRow.details">
          <div class="mcp-drawer-section-title">DETAILS (sanitized)</div>
          <pre class="mcp-json">{{ formatDetails(drawerRow.details) }}</pre>
        </div>

        <div class="mcp-drawer-section" v-if="drawerRow.user_agent">
          <div class="mcp-drawer-section-title">USER AGENT</div>
          <code class="mcp-ua">{{ drawerRow.user_agent }}</code>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { usePolledData } from '@/composables/usePolledData'
import { downloadCsv, csvFilenameTimestamp } from '@/components/common/csvExport'
import { useAuthStore } from '@/stores/auth'
import {
  getMyMcpAuditLog,
  getAdminMcpAuditLog,
  getOrgMcpAuditLog,
  type McpAuditRow,
  type McpAuditPage,
} from '@/services/api/mcpAuditLog'
import { useI18n } from '@/composables/useI18n'

interface Props {
  /** V0650 (d): 'org' reads an organization's agents' calls (owner or admin), keyed by orgId. */
  scope: 'me' | 'admin' | 'org'
  /** Required when scope === 'org'. */
  orgId?: string
  /** scope 'org': agent DID -> a name to show (agent names are not unique: the DID stays in the title). */
  actorNames?: Record<string, string>
  /** Required when scope === 'admin'. Developer id (numeric string) or agent DID. */
  actorId?: string
  /** Human label for the subject (used in the self-watch warning). */
  subjectLabel?: string
  /** Override the localStorage key prefix so multiple instances don't fight. */
  storageKey?: string
  /** Poll interval in ms (default 30000). Set 0 to disable polling. */
  pollIntervalMs?: number
  /** Rows per page (default 50). §FESUITE (2026-10-04): Settings' API Keys tab shows 15, so the key list above is not
   *  a short head on a 4,000 px page; the pager reads the older rows. */
  pageSize?: number
}

const props = withDefaults(defineProps<Props>(), {
  pollIntervalMs: 30000,
  storageKey: 'mcp-audit',
  pageSize: 50,
})

const auth = useAuthStore()
const { t } = useI18n()
const recording = ref<boolean | null>(null)

// ─── Filter state ───────────────────────────────────────────────────────
const filterOutcome = ref<'' | 'success' | 'failure' | 'error'>('')
const filterServer = ref<'' | 'public' | 'admin'>('')
const searchTool = ref('')

// §FESUITE V0577: the chips count the rows a read returned; before one answered (or when it failed with nothing shown)
// they said "0" beside "Loading…" or the error, a count of rows nobody had read
const outcomeFilters = computed(() => {
  const counted = rows.value.length > 0 || (answered.value && !error.value)
  const n = (pred: (r: McpAuditRow) => boolean) => (counted ? rows.value.filter(pred).length : null)
  return [
    { label: 'All',     value: '' as const,        count: counted ? rows.value.length : null },
    { label: 'Success', value: 'success' as const, count: n(r => r.outcome === 'success') },
    { label: 'Failure', value: 'failure' as const, count: n(r => r.outcome === 'failure') },
    { label: 'Error',   value: 'error' as const,   count: n(r => r.outcome === 'error') },
  ]
})

const serverFilters = [
  { label: 'All',           value: '' as const },
  { label: 'Public (/rpc)', value: 'public' as const },
  { label: 'Admin (/admin/rpc)', value: 'admin' as const },
]

const storageOutcomeKey = computed(() => `theprotocol:${props.storageKey}:outcome:${props.scope}`)
const storageServerKey  = computed(() => `theprotocol:${props.storageKey}:server:${props.scope}`)

function setOutcomeFilter(v: '' | 'success' | 'failure' | 'error') {
  filterOutcome.value = v
  try { localStorage.setItem(storageOutcomeKey.value, v) } catch { /* SSR */ }
}
function setServerFilter(v: '' | 'public' | 'admin') {
  filterServer.value = v
  try { localStorage.setItem(storageServerKey.value, v) } catch { /* SSR */ }
}

onMounted(() => {
  try {
    const o = localStorage.getItem(storageOutcomeKey.value) as any
    if (o === 'success' || o === 'failure' || o === 'error') filterOutcome.value = o
    const s = localStorage.getItem(storageServerKey.value) as any
    if (s === 'public' || s === 'admin') filterServer.value = s
  } catch { /* expected */ }
})

// ─── Cursor stack for keyset pagination ────────────────────────────────
const cursorStack = ref<string[]>([])
const currentCursor = ref<string | null>(null)
const nextCursor = ref<string | null>(null)
const rows = ref<McpAuditRow[]>([])
const errorMessage = ref<string>('')

// ─── Fetcher ───────────────────────────────────────────────────────────
async function doFetch(): Promise<McpAuditPage> {
  if (props.scope === 'org') {
    if (!props.orgId) {
      throw new Error('orgId required for org scope')
    }
    return await getOrgMcpAuditLog({ org_id: props.orgId, cursor: currentCursor.value, limit: props.pageSize })
  }
  if (props.scope === 'admin') {
    if (!props.actorId) {
      throw new Error('actorId required for admin scope')
    }
    return await getAdminMcpAuditLog({ actor_id: props.actorId, cursor: currentCursor.value, limit: props.pageSize })
  }
  return await getMyMcpAuditLog({ cursor: currentCursor.value, limit: props.pageSize })
}

const polled = usePolledData<McpAuditPage>(
  doFetch,
  {
    interval: props.pollIntervalMs > 0 ? props.pollIntervalMs : 999_999_000,
    immediate: true,
    pauseWhenHidden: true,
    autoStart: props.pollIntervalMs > 0,
  },
)

const loading = polled.loading
const error = polled.error
const lastFetchAt = polled.lastFetchAt
// §FESUITE (2026-10-05): the first render came before the first fetch and drew "No rows" and "No MCP tool calls yet." over
// a log nobody had read yet; the empty state waits for an answer now
const answered = computed(() => lastFetchAt.value !== null)

// React to incoming data
watch(polled.data, (page) => {
  if (!page) return
  rows.value = page.rows
  nextCursor.value = page.next_cursor
  recording.value = typeof page.recording === 'boolean' ? page.recording : null
}, { immediate: true })

watch(polled.error, (err) => {
  if (!err) { errorMessage.value = ''; return }
  errorMessage.value = (err as any)?.response?.data?.detail || (err as any)?.message || String(err)
})

async function refresh() {
  await polled.refetch()
}

async function nextPage() {
  if (!nextCursor.value) return
  cursorStack.value = [...cursorStack.value, currentCursor.value || '']
  currentCursor.value = nextCursor.value
  await polled.refetch()
}

async function prevPage() {
  if (!cursorStack.value.length) return
  const stack = [...cursorStack.value]
  const prev = stack.pop() as string
  cursorStack.value = stack
  currentCursor.value = prev || null
  await polled.refetch()
}

// Refetch when the subject changes (admin drawer switching from agent A to agent B)
watch(() => props.actorId, () => {
  cursorStack.value = []
  currentCursor.value = null
  rows.value = []
  nextCursor.value = null
  if (props.scope === 'admin' && props.actorId) {
    void polled.refetch()
  }
})

// V0650 (d): another organization is another log
watch(() => props.orgId, () => {
  cursorStack.value = []
  currentCursor.value = null
  rows.value = []
  nextCursor.value = null
  recording.value = null
  if (props.scope === 'org' && props.orgId) {
    void polled.refetch()
  }
})

onBeforeUnmount(() => {
  polled.pause()
})

// ─── Self-watching warning ─────────────────────────────────────────────
const showSelfWatchWarning = computed(() => {
  if (props.scope !== 'admin') return false
  if (!props.actorId) return false
  // Admin endpoint emits admin_read_mcp_audit only when actor_id !== caller's developer_id.
  // User.developer_id is the backend-side numeric developer identifier (the comparison
  // key on the server). User.id is the auth-subject UUID and shouldn't be used here.
  const selfDevId = auth.user?.developer_id
  if (selfDevId == null) return true  // Conservative: warn if we can't compare.
  return String(selfDevId) !== props.actorId
})

// ─── Filtered / display rows ───────────────────────────────────────────
const filteredRows = computed(() => {
  return rows.value.filter(r => {
    if (filterOutcome.value && r.outcome !== filterOutcome.value) return false
    if (filterServer.value === 'public' && r.is_admin_server === true) return false
    if (filterServer.value === 'admin' && r.is_admin_server !== true) return false
    if (searchTool.value && (r.target_id ?? '').toLowerCase().indexOf(searchTool.value.toLowerCase()) < 0) return false
    return true
  })
})

const pageStartLabel = computed(() => {
  const r = rows.value[0]
  return r ? formatTimestamp(r.timestamp) : '—'
})
const pageEndLabel = computed(() => {
  const r = rows.value[rows.value.length - 1]
  return r ? formatTimestamp(r.timestamp) : '—'
})

const lastFetchedLabel = computed(() => {
  if (!lastFetchAt.value) return 'fetching…'
  const secs = Math.max(0, Math.round((Date.now() - lastFetchAt.value.getTime()) / 1000))
  if (secs < 60) return `updated ${secs}s ago`
  return `updated ${Math.round(secs / 60)}m ago`
})

// ─── Drawer ────────────────────────────────────────────────────────────
const drawerRow = ref<McpAuditRow | null>(null)
function openDrawer(r: McpAuditRow) { drawerRow.value = r }
function closeDrawer() { drawerRow.value = null }

const drawerOpaInfo = computed(() => {
  const o = drawerRow.value?.details?.opa
  if (!o || typeof o !== 'object') return null
  return o
})

// ─── Formatters ────────────────────────────────────────────────────────
function formatTimestamp(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const h = String(d.getUTCHours()).padStart(2, '0')
    const m = String(d.getUTCMinutes()).padStart(2, '0')
    const s = String(d.getUTCSeconds()).padStart(2, '0')
    const mo = String(d.getUTCMonth() + 1).padStart(2, '0')
    const day = String(d.getUTCDate()).padStart(2, '0')
    return `${mo}-${day} ${h}:${m}:${s}`
  } catch { return iso }
}

function formatTimestampLong(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toUTCString().replace(' GMT', ' UTC')
  } catch { return iso }
}

function shortActorId(id: string): string {
  if (!id) return '—'
  if (id.length <= 24) return id
  if (id.startsWith('did:')) {
    // Keep enough of the suffix to be distinctive but trim the middle.
    return `${id.slice(0, 16)}…${id.slice(-8)}`
  }
  return `${id.slice(0, 10)}…${id.slice(-6)}`
}

function formatDetails(d: any): string {
  try { return JSON.stringify(d, null, 2) } catch { return String(d) }
}

function exportCsv() {
  const ts = csvFilenameTimestamp()
  const scopeLabel = props.scope === 'me' ? 'me'
    : props.scope === 'org' ? `org-${(props.orgId || 'unknown').slice(0, 12)}`
    : `admin-${(props.actorId || 'unknown').slice(0, 12)}`
  downloadCsv(
    filteredRows.value,
    [
      { label: 'timestamp',   value: r => r.timestamp },
      { label: 'event_type',  value: r => r.event_type },
      { label: 'actor_type',  value: r => r.actor_type },
      { label: 'actor_id',    value: r => r.actor_id ?? '' },
      { label: 'actor_ip',    value: r => r.actor_ip ?? '' },
      { label: 'target_type', value: r => r.target_type ?? '' },
      { label: 'target_id',   value: r => r.target_id ?? '' },
      { label: 'tier',        value: r => r.tier ?? '' },
      { label: 'is_admin_server', value: r => r.is_admin_server == null ? '' : String(r.is_admin_server) },
      { label: 'outcome',     value: r => r.outcome },
      { label: 'severity',    value: r => r.severity },
      { label: 'latency_ms',  value: r => r.latency_ms ?? '' },
      { label: 'request_id',  value: r => r.request_id ?? '' },
      { label: 'error_message', value: r => r.error_message ?? '' },
    ],
    `mcp-audit-${scopeLabel}-${ts}.csv`,
  )
}
</script>

<style scoped>
.mcp-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: var(--nc-text-primary, #e4ecf4);
  font-size: 13px;
}

/* ── Self-watch warning ──────────────────────────────────────────── */
.mcp-warn {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(var(--cyan-rgb, 0, 210, 210), 0.4);
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.06);
  border-radius: 8px;
}
.mcp-warn-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  background: var(--cyan, #00d2d2);
  box-shadow: 0 0 8px var(--cyan, #00d2d2);
  flex: 0 0 auto;
}
.mcp-warn-body {
  font-size: 12.5px;
  line-height: 1.5;
}
.mcp-warn code {
  background: rgba(0, 0, 0, 0.3);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11.5px;
}

/* ── Filters ───────────────────────────────────────────────────── */
.mcp-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}
.mcp-filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mcp-filter-label {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--nc-text-muted, #8b9bb4);
  margin-right: 2px;
}
.mcp-filter-search {
  flex: 1;
  min-width: 200px;
  display: flex;
  align-items: center;
}
.mcp-filter-actions {
  display: flex;
  gap: 6px;
}
.mcp-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 11px;
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.03);
  color: var(--nc-text-secondary, #c4d2e0);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s;
}
.mcp-chip:hover { border-color: rgba(var(--cyan-rgb, 0, 210, 210), 0.4); }
.mcp-chip--active {
  border-color: var(--cyan, #00d2d2);
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.12);
  color: var(--cyan, #00d2d2);
}
.mcp-chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.25);
}
.mcp-chip-dot--success { background: #00d27a; }
.mcp-chip-dot--failure { background: #ff8c5a; }
.mcp-chip-dot--error   { background: #ff4c4c; }
.mcp-chip-count {
  font-variant-numeric: tabular-nums;
  font-size: 10.5px;
  padding: 1px 5px;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 8px;
  color: var(--nc-text-muted, #8b9bb4);
}
.mcp-chip--active .mcp-chip-count { color: inherit; }

.mcp-input {
  width: 100%;
  padding: 6px 10px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: var(--nc-text-primary);
  font-family: inherit;
  font-size: 12.5px;
}
.mcp-input:focus {
  outline: none;
  border-color: var(--cyan, #00d2d2);
  box-shadow: 0 0 0 2px rgba(var(--cyan-rgb, 0, 210, 210), 0.18);
}

.mcp-btn {
  padding: 5px 12px;
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 6px;
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.12);
  border: 1px solid rgba(var(--cyan-rgb, 0, 210, 210), 0.3);
  color: var(--cyan, #00d2d2);
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.mcp-btn:hover { background: rgba(var(--cyan-rgb, 0, 210, 210), 0.2); }
.mcp-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.mcp-btn--ghost {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.1);
  color: var(--nc-text-secondary, #c4d2e0);
}
.mcp-btn--ghost:hover {
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.08);
  border-color: rgba(var(--cyan-rgb, 0, 210, 210), 0.3);
  color: var(--cyan, #00d2d2);
}

.mcp-refresh-spinner {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid transparent;
  border-top-color: currentColor;
  display: inline-block;
}
.mcp-refresh-spinner.spinning { animation: mcp-spin 0.9s linear infinite; }
@keyframes mcp-spin { to { transform: rotate(360deg); } }

/* ── Status strip ──────────────────────────────────────────────── */
.mcp-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  color: var(--nc-text-muted, #8b9bb4);
}
.mcp-status-left, .mcp-status-right { display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mcp-status-pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.1);
  color: var(--cyan, #00d2d2);
  font-weight: 500;
  letter-spacing: 0.02em;
}
.mcp-status-pill--muted {
  background: rgba(255, 255, 255, 0.04);
  color: var(--nc-text-muted);
}
.mcp-status-pill--loading {
  background: rgba(255, 255, 255, 0.04);
  color: var(--nc-text-secondary);
}
.mcp-status-pill--empty {
  background: rgba(255, 255, 255, 0.04);
  color: var(--nc-text-muted);
}
.mcp-status-pill--error {
  background: rgba(255, 76, 76, 0.14);
  color: #ff8c8c;
}

/* ── Table ─────────────────────────────────────────────────────── */
.mcp-table-wrap {
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 8px;
  overflow-x: auto;
  background: rgba(0, 0, 0, 0.25);
}
.mcp-table {
  width: 100%;
  border-collapse: collapse;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
}
.mcp-table th {
  text-align: left;
  padding: 9px 12px;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--cyan, #00d2d2);
  border-bottom: 1px solid rgba(var(--cyan-rgb, 0, 210, 210), 0.18);
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.04);
  font-weight: 600;
  font-family: var(--nc-font-sans, system-ui, sans-serif);
}
.mcp-table td {
  padding: 9px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  vertical-align: middle;
}
.mcp-table tr.mcp-row:hover {
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.05);
  cursor: pointer;
}
.mcp-row--failure td { color: rgba(255, 175, 130, 0.95); }
.mcp-row--error td   { color: rgba(255, 130, 130, 0.95); }
.mcp-row--meta {
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.025);
  font-style: italic;
}
.mcp-row-empty td {
  padding: 28px 12px;
  text-align: center;
  color: var(--nc-text-muted, #8b9bb4);
  font-style: italic;
}
.mcp-th-ts      { width: 110px; }
.mcp-th-tier    { width: 70px; }
.mcp-th-outcome { width: 100px; }
.mcp-th-lat     { width: 80px; text-align: right; }
.mcp-th-detail  { width: 38px; }
.mcp-cell-ts {
  white-space: nowrap;
  color: var(--nc-text-muted, #8b9bb4);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.mcp-cell-tool code {
  font-size: 12px;
  color: var(--nc-text-primary);
  background: rgba(0, 0, 0, 0.3);
  padding: 1px 7px;
  border-radius: 4px;
  font-weight: 500;
}
.mcp-cell-tier { text-align: center; }
.mcp-cell-lat {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--nc-text-muted);
  font-size: 11.5px;
}
.mcp-cell-detail { text-align: right; }
.mcp-row-open {
  background: transparent;
  border: none;
  color: var(--nc-text-muted);
  font-size: 18px;
  line-height: 1;
  padding: 0 6px;
  cursor: pointer;
  border-radius: 4px;
}
.mcp-row-open:hover { color: var(--cyan, #00d2d2); background: rgba(var(--cyan-rgb, 0, 210, 210), 0.1); }

.mcp-actor-pill {
  display: inline-block;
  padding: 1px 7px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: 999px;
  text-transform: uppercase;
  border: 1px solid transparent;
  vertical-align: middle;
}
.mcp-actor-pill--admin      { background: rgba(255, 200, 80, 0.12); color: #ffd27a; border-color: rgba(255, 200, 80, 0.3); }
.mcp-actor-pill--developer  { background: rgba(120, 160, 255, 0.12); color: #9db4ff; border-color: rgba(120, 160, 255, 0.3); }
.mcp-actor-pill--agent      { background: rgba(120, 210, 130, 0.12); color: #a4e6b3; border-color: rgba(120, 210, 130, 0.3); }
.mcp-actor-pill--anonymous  { background: rgba(160, 160, 160, 0.12); color: #b8bcc4; border-color: rgba(160, 160, 160, 0.25); }

.mcp-actor-id {
  margin-left: 6px;
  color: var(--nc-text-muted);
  font-size: 11px;
}

.mcp-tier-pill {
  display: inline-block;
  padding: 1px 7px;
  font-size: 10.5px;
  font-weight: 600;
  border-radius: 999px;
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.1);
  color: var(--cyan, #00d2d2);
  border: 1px solid rgba(var(--cyan-rgb, 0, 210, 210), 0.25);
}
.mcp-tier-pill--admin { background: rgba(255, 130, 130, 0.12); color: #ffb0b0; border-color: rgba(255, 130, 130, 0.3); }

.mcp-outcome-pill {
  display: inline-block;
  padding: 1px 8px;
  font-size: 10.5px;
  font-weight: 600;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.mcp-outcome-pill--success { background: rgba(0, 210, 122, 0.14); color: #5eebaa; border: 1px solid rgba(0, 210, 122, 0.3); }
.mcp-outcome-pill--failure { background: rgba(255, 140, 90, 0.14); color: #ffb088; border: 1px solid rgba(255, 140, 90, 0.3); }
.mcp-outcome-pill--error   { background: rgba(255, 76, 76, 0.16); color: #ff8a8a; border: 1px solid rgba(255, 76, 76, 0.36); }

.mcp-opa-pill {
  display: inline-block;
  padding: 1px 7px;
  font-size: 10.5px;
  font-weight: 600;
  border-radius: 999px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.mcp-opa-pill--ok       { background: rgba(0, 210, 122, 0.14); color: #5eebaa; border: 1px solid rgba(0, 210, 122, 0.3); }
.mcp-opa-pill--mismatch { background: rgba(255, 76, 76, 0.16); color: #ff8a8a; border: 1px solid rgba(255, 76, 76, 0.36); }

.mcp-meta-label {
  font-size: 11.5px;
  color: var(--nc-text-secondary);
}
.mcp-meta-label code {
  font-size: 10.5px;
  padding: 1px 4px;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 3px;
  color: var(--nc-text-primary);
}

.mcp-muted { color: var(--nc-text-muted); }

/* ── Empty state ────────────────────────────────────────────── */
.mcp-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 540px;
  margin: 0 auto;
}
.mcp-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--nc-text-primary);
}
.mcp-empty-body {
  font-size: 12.5px;
  color: var(--nc-text-muted);
  text-align: center;
  line-height: 1.5;
}

/* ── Pagination ─────────────────────────────────────────────── */
.mcp-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 4px 0;
  font-size: 11.5px;
  color: var(--nc-text-muted);
}
.mcp-pagination-info {
  font-variant-numeric: tabular-nums;
}

/* ── Drawer ─────────────────────────────────────────────────── */
.mcp-drawer-scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(2px);
  z-index: 10050;
  display: flex;
  justify-content: flex-end;
}
.mcp-drawer {
  width: min(640px, 96vw);
  height: 100%;
  background: var(--nc-bg-elevated, #0c1521);
  border-left: 1px solid rgba(var(--cyan-rgb, 0, 210, 210), 0.25);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.6);
  overflow-y: auto;
  padding: 20px 22px 28px 22px;
}
.mcp-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}
.mcp-drawer-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.mcp-drawer-badge {
  font-size: 11px;
  text-transform: uppercase;
}
.mcp-drawer-tool {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--nc-text-primary);
}
.mcp-drawer-close {
  background: transparent;
  border: none;
  color: var(--nc-text-muted);
  font-size: 26px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.mcp-drawer-close:hover { color: var(--cyan, #00d2d2); }

.mcp-drawer-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 12px;
}
.mcp-drawer-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.mcp-meta-key {
  width: 80px;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--nc-text-muted);
  flex: 0 0 80px;
}
.mcp-drawer-meta-row code {
  background: rgba(0, 0, 0, 0.4);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11.5px;
  color: var(--nc-text-primary);
}

.mcp-drawer-section {
  margin-bottom: 14px;
}
.mcp-drawer-section-title {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--cyan, #00d2d2);
  margin-bottom: 6px;
  font-weight: 600;
}
.mcp-json {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 10px 14px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--nc-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 50vh;
  overflow-y: auto;
}
.mcp-ua {
  display: inline-block;
  background: rgba(0, 0, 0, 0.4);
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--nc-text-secondary);
  word-break: break-all;
}
.mcp-error-message {
  color: #ff8a8a;
  font-size: 11.5px;
  word-break: break-word;
}

/* Mobile */
@media (max-width: 768px) {
  .mcp-filters { gap: 8px 12px; padding: 8px; }
  .mcp-filter-search { min-width: 100%; }
  .mcp-table th, .mcp-table td { padding: 7px 8px; font-size: 11px; }
  .mcp-th-tier, .mcp-th-detail, .mcp-cell-tier, .mcp-cell-detail { display: none; }
  .mcp-drawer { width: 100%; }
}
</style>
