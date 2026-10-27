<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed } from 'vue'
import { apiClient } from '@/services/api/client'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { usePolledData } from '@/composables/usePolledData'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

const { t } = useI18n()
// Canary pre-funds are real transfers in THIS frame's currency (BVT on Frame C).
const { localCurrency } = useCurrency()

dayjs.extend(relativeTime)

interface PathStats {
  passed: number
  failed: number
  fired: number
  total: number
  pass_rate: number | null
  avg_latency_ms?: number | null
  max_latency_ms?: number | null
  min_latency_ms?: number | null
}

interface LastResult {
  test_id: string
  outcome: string
  fired_at: string | null
  completed_at: string | null
  http_status: number | null
  http_latency_ms: number | null
  total_latency_ms: number | null
  transfer_id: string | null
  failure_type: string | null
  failure_detail: Record<string, unknown> | null
}

interface CanaryPath {
  id: number
  path_id: string
  sender_name: string | null
  sender_did: string | null
  receiver_name: string | null
  receiver_did: string | null
  backend: string
  amount: string
  interval_sec: number
  slo_http_ms: number
  slo_settled_sec: number
  is_active: boolean
  stats_24h: PathStats
  stats_5m: PathStats
  last_result: LastResult | null
  frame_pair: string
}

interface CanaryAgent {
  id: number
  name: string
  agent_did: string
  client_id: string
  registry_id: string
  registry_url: string
  frame: string
  is_active: boolean
  prefund_amount: string
  created_at: string | null
}

interface RecentFailure {
  test_id: string
  path_id: number
  fired_at: string | null
  backend: string
  sender_did: string
  receiver_did: string
  failure_type: string | null
  failure_detail: Record<string, unknown> | null
  http_status: number | null
}

interface CanarySummary {
  total_paths: number
  active_paths: number
  pass_rate_24h: number | null
  passes_24h: number
  failures_24h: number
  pending_count: number
  tests_per_minute_5m: number
  delta_frame_a: number | null
  delta_frame_b: number | null
  snapshot_at: string
}

interface CanaryStatusResponse {
  summary: CanarySummary
  paths: CanaryPath[]
  agents: CanaryAgent[]
  recent_failures: RecentFailure[]
}

const error = ref('')
const autoRefresh = ref(true)
const expandedPathId = ref<number | null>(null)
const backendFilter = ref<'all' | 'async' | '2pc' | 'intra'>('all')
/* §CANARYUNIFY pass 4 — the page used to render TWO panels: the Fleet Cockpit
   (remote paths this registry SCHEDULES on other homes) and the path cards
   (paths that RUN here). Disjoint data, two different UIs, and the reader had
   to learn both. They are now ONE grid of the same card, tagged by scope. */
const scopeFilter = ref<'all' | 'local' | 'federated'>('all')
const fireBusy = ref<number | null>(null)
const fireFlash = ref<string>('')
const infoOpen = ref(false)

// Phase 11 (2026-05-04): live event log feed.
// Captures every distinct last_result we've seen across refresh cycles, so the
// log fills in without waiting for a separate streaming endpoint. Capped at
// LOG_MAX entries; oldest evicted on overflow.
interface LogEntry {
  test_id: string
  fired_at: string | null
  outcome: string
  backend: string
  sender: string
  receiver: string
  http_status: number | null
  total_latency_ms: number | null
  http_latency_ms: number | null
  failure_type: string | null
}
const LOG_MAX = 200
const eventLog = ref<LogEntry[]>([])
const seenTestIds = new Set<string>()
const logFilter = ref<'all' | 'passed' | 'failed' | 'fired'>('all')
const logAutoTail = ref(true)
const logCollapsed = ref(false)
// Counts events arriving while the log is collapsed so we can badge the header
const newEventsWhileCollapsed = ref(0)

// Adjustable refresh cadence — persisted in localStorage so the choice survives reloads
const REFRESH_OPTIONS = [
  { value: 5, label: '5s' },
  { value: 10, label: '10s' },
  { value: 30, label: '30s' },
  { value: 60, label: '1m' },
  { value: 300, label: '5m' },
] as const
const _stored = (() => {
  try { return parseInt(localStorage.getItem('cn-refresh-sec') || '') || NaN } catch { return NaN }
})()
const refreshSec = ref<number>(
  REFRESH_OPTIONS.some((o) => o.value === _stored) ? _stored : 10
)

const ingestNewEvents = (resp: CanaryStatusResponse) => {
  // Walk every path's last_result; if the test_id is unseen, prepend.
  // Sort the new batch by fired_at desc before merging so the log stays
  // ordered even if multiple paths advanced between refreshes.
  const fresh: LogEntry[] = []
  for (const p of resp.paths) {
    const lr = p.last_result
    if (!lr || !lr.test_id) continue
    if (seenTestIds.has(lr.test_id)) continue
    seenTestIds.add(lr.test_id)
    fresh.push({
      test_id: lr.test_id,
      fired_at: lr.fired_at,
      outcome: lr.outcome,
      backend: p.backend,
      sender: (p.sender_name || '').replace('canary-', ''),
      receiver: (p.receiver_name || '').replace('canary-', ''),
      http_status: lr.http_status,
      total_latency_ms: lr.total_latency_ms,
      http_latency_ms: lr.http_latency_ms,
      failure_type: lr.failure_type,
    })
  }
  if (!fresh.length) return
  fresh.sort((a, b) => {
    const ta = a.fired_at ? Date.parse(a.fired_at) : 0
    const tb = b.fired_at ? Date.parse(b.fired_at) : 0
    return tb - ta
  })
  eventLog.value = [...fresh, ...eventLog.value].slice(0, LOG_MAX)
  if (logCollapsed.value) {
    newEventsWhileCollapsed.value = Math.min(newEventsWhileCollapsed.value + fresh.length, 999)
  }
  // Cap the seen-set so it doesn't grow unbounded over a long session.
  if (seenTestIds.size > LOG_MAX * 4) {
    const keep = new Set(eventLog.value.map((e) => e.test_id))
    seenTestIds.clear()
    keep.forEach((id) => seenTestIds.add(id))
  }
}

// Visibility-guarded polling via shared composable (#6, 2026-05-08).
// Reactive interval — usePolledData watches refreshSecMs and restarts the
// timer when the user picks a new cadence from the dropdown.
const refreshSecMs = computed(() => refreshSec.value * 1000)
const polled = usePolledData<CanaryStatusResponse>(async () => {
  try {
    const resp = await apiClient.get<CanaryStatusResponse>('/admin/canary/status')
    error.value = ''
    ingestNewEvents(resp.data)
    void fetchFleet() // §V0046 cockpit layer refreshes on the same cadence (best-effort)
    return resp.data
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = `Failed to load canary status: ${msg}`
    throw e
  }
}, { interval: refreshSecMs, autoStart: autoRefresh.value })

const data = polled.data
const loading = polled.loading
const lastRefreshAt = computed(() =>
  polled.lastFetchAt.value ? dayjs(polled.lastFetchAt.value).format('HH:mm:ss') : ''
)

const fetchStatus = () => polled.refetch()

const toggleAutoRefresh = () => {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    polled.resume()
    polled.refetch()
  } else {
    polled.pause()
  }
}

const onRefreshSecChange = () => {
  try { localStorage.setItem('cn-refresh-sec', String(refreshSec.value)) } catch { /* ignore */ }
  // The composable's watch(options.interval, ...) restarts the timer
  // automatically when refreshSecMs flips, so no manual stop/start here.
}

// ── §V0046 FLEET COCKPIT (Canary Cockpit, V0045 backend) ────────────────────
// This registry can be the fleet's canary scheduler (CANARY_RUNNER_MODE=master on
// registry-a): its runner schedules the LOCAL paths below AND dispatches the
// FEDERATED paths to their home registries over federation mTLS — the homes fire
// their own canary agents (SVIDs/creds stay home) and judge locally. This panel
// surfaces that scheduling layer + the one-button fleet pause.
interface FleetLastDispatch {
  outcome: string
  dispatched_at: string | null
  http_status: number | null
  latency_ms: number | null
  error: string | null
  test_id: string
}
interface FleetRemotePath {
  id: number
  home_registry: string
  remote_path_id: number
  path_label: string
  interval_sec: number
  is_active: boolean
  notes: string | null
  last_dispatch: FleetLastDispatch | null
}
interface FleetStatus {
  mode: string
  fleet_paused: boolean
  paused_at: string | null
  local_paths: { active: number; total: number }
  remote_paths: FleetRemotePath[]
  dispatch_24h_by_home: Record<string, Record<string, number>>
}
const fleet = ref<FleetStatus | null>(null)
const fleetBusy = ref(false)
const fleetFlash = ref('')
// §FESUITE (V0578): only a 404 (a build without the endpoint) means "no fleet cockpit here". Any other failure hid the
// fleet bar (PAUSED / SCHEDULING and the fleet kill switch), the look of a registry with no cockpit, and a later failed
// read kept the old state as if it were current: the operator could not see that the fleet was paused, or resumed.
const fleetFailed = ref(false)
const fleetReadAt = ref('')
const fetchFleet = async () => {
  try {
    const resp = await apiClient.get<FleetStatus>('/admin/canary/fleet/status')
    fleet.value = resp.data
    fleetFailed.value = false
    fleetReadAt.value = dayjs().format('HH:mm:ss')
  } catch (e: any) {
    if (e?.response?.status === 404) { fleet.value = null; fleetFailed.value = false; return }
    fleetFailed.value = true
  }
}
const showCockpit = computed(() =>
  !!fleet.value && (fleet.value.mode === 'master' || (fleet.value.remote_paths?.length || 0) > 0)
)
const fleetByHome = computed(() => {
  const groups: Record<string, FleetRemotePath[]> = {}
  for (const r of fleet.value?.remote_paths || []) {
    (groups[r.home_registry] = groups[r.home_registry] || []).push(r)
  }
  return Object.entries(groups).map(([home, paths]) => ({
    home,
    paths,
    agg: (fleet.value?.dispatch_24h_by_home || {})[home] || {},
  }))
})
/* One shape both sources map into, so a single card renders either. Fields the
   other side genuinely lacks stay null and the card omits that tile — better an
   honest gap than a fabricated zero. */
interface UnifiedPath {
  key: string
  scope: 'local' | 'federated'
  home: string
  title: string
  backend: string | null
  isActive: boolean
  statusText: string
  stateCls: string
  tiles: { label: string; value: string; cls?: string; title?: string }[]
  rows: { label: string; value: string; mono?: boolean }[]
  local?: CanaryPath
  remote?: FleetRemotePath
}

const unifiedPaths = computed<UnifiedPath[]>(() => {
  const out: UnifiedPath[] = []
  if (scopeFilter.value !== 'federated') {
    for (const p of filteredPaths.value) {
      out.push({
        key: `l-${p.id}`, scope: 'local', home: 'local',
        title: `${p.sender_name?.replace('canary-','')} → ${p.receiver_name?.replace('canary-','')}`,
        backend: p.backend, isActive: p.is_active,
        statusText: statusLabel(p), stateCls: cardClass(p).join(' '),
        tiles: [
          { label: '24h Pass', value: formatPercent(p.stats_24h.pass_rate), cls: passRateCls(p.stats_24h.pass_rate) },
          { label: 'Avg Latency', value: formatMs(p.stats_24h.avg_latency_ms), cls: 'cn-stat-cyan' },
          { label: 'Last Latency', value: formatMs(p.last_result?.total_latency_ms ?? null), cls: 'cn-stat-cyan' },
          { label: 'Last fired', value: lastRelativeShort(p.last_result?.fired_at ?? null), title: lastRelative(p.last_result?.fired_at ?? null) },
        ],
        rows: [
          { label: 'Sender', value: p.sender_name || '—', mono: true },
          { label: 'Receiver', value: p.receiver_name || '—', mono: true },
          { label: 'Frames', value: p.frame_pair || '—', mono: true },
          { label: 'Interval', value: `${p.interval_sec}s` },
        ],
        local: p,
      })
    }
  }
  if (scopeFilter.value !== 'local') {
    for (const r of fleet.value?.remote_paths || []) {
      const o = r.last_dispatch?.outcome
      const st = !r.is_active ? 'cn-card cn-card-disabled'
        : (o === 'acked' || o === 'replayed') ? 'cn-card cn-card-ok'
        : (o === 'dispatch_failed' || o === 'rejected') ? 'cn-card cn-card-bad'
        : (o === 'sent') ? 'cn-card cn-card-pending' : 'cn-card'
      out.push({
        key: `f-${r.id}`, scope: 'federated', home: r.home_registry,
        title: r.path_label, backend: null, isActive: r.is_active,
        statusText: !r.is_active ? 'DISABLED' : (o ? o.toUpperCase() : 'NO DISPATCH'),
        stateCls: st,
        tiles: [
          { label: 'Dispatch', value: o ? o : '—' },
          { label: 'Last Latency', value: formatMs(r.last_dispatch?.latency_ms ?? null), cls: 'cn-stat-cyan' },
          { label: 'Interval', value: `${r.interval_sec}s` },
          { label: 'Last sent', value: lastRelativeShort(r.last_dispatch?.dispatched_at ?? null), title: lastRelative(r.last_dispatch?.dispatched_at ?? null) },
        ],
        rows: [
          { label: 'Home', value: r.home_registry, mono: true },
          { label: 'Scheduled by', value: 'this registry (master)' },
          { label: 'Notes', value: r.notes || '—' },
        ],
        remote: r,
      })
    }
  }
  return out
})
const localCount = computed(() => filteredPaths.value.length)
const fedCount = computed(() => (fleet.value?.remote_paths || []).length)

const federatedActive = computed(
  () => (fleet.value?.remote_paths || []).filter((r) => r.is_active).length
)
const fleetPauseToggle = async () => {
  if (!fleet.value || fleetBusy.value) return
  const pausing = !fleet.value.fleet_paused
  if (pausing && !window.confirm('Pause ALL canary scheduling fleet-wide (local fires + federated dispatches)?')) return
  fleetBusy.value = true
  try {
    await apiClient.post(`/admin/canary/fleet/${pausing ? 'pause' : 'resume'}`, {})
    fleetFlash.value = pausing
      ? 'Fleet PAUSED — new cycles stop within 5s; the in-flight dispatch tail drains in under 30s.'
      : 'Fleet RESUMED — paths fire again within their intervals.'
    setTimeout(() => { fleetFlash.value = '' }, 7000)
    await fetchFleet()
  } catch (e) {
    error.value = `Fleet ${pausing ? 'pause' : 'resume'} failed: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    fleetBusy.value = false
  }
}
const toggleRemotePath = async (r: FleetRemotePath) => {
  if (fleetBusy.value) return
  fleetBusy.value = true
  try {
    await apiClient.post('/admin/canary/fleet/remote-paths', {
      paths: [{ home_registry: r.home_registry, remote_path_id: r.remote_path_id, is_active: !r.is_active }],
    })
    await fetchFleet()
  } catch (e) {
    error.value = `Federated path toggle failed: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    fleetBusy.value = false
  }
}
const dispatchChipClass = (o: string | undefined | null): string => {
  if (o === 'acked' || o === 'replayed') return 'cn-chip cn-chip-cyan'
  if (o === 'dispatch_failed' || o === 'rejected') return 'cn-chip cn-chip-red'
  if (o === 'sent') return 'cn-chip cn-chip-amber'
  return 'cn-chip cn-chip-muted'
}
const remoteDot = (r: FleetRemotePath): string => {
  if (!r.is_active) return '⚫'
  const o = r.last_dispatch?.outcome
  if (o === 'acked' || o === 'replayed') return '🟢'
  if (o === 'dispatch_failed' || o === 'rejected') return '🔴'
  if (o === 'sent') return '🟡'
  return '⚪'
}
/* §CANARYUNIFY (2026-08-05) — a cockpit row now carries the SAME state rail a
   path card does. Deliberately mirrors remoteDot/dispatchChipClass above so one
   dispatch outcome can never render green on the dot and red on the rail. */
const fleetRowClass = (r: FleetRemotePath): string => {
  if (!r.is_active) return 'cn-fleet-row-off'
  const o = r.last_dispatch?.outcome
  if (o === 'acked' || o === 'replayed') return 'cn-fleet-row-ok'
  if (o === 'dispatch_failed' || o === 'rejected') return 'cn-fleet-row-bad'
  if (o === 'sent') return 'cn-fleet-row-warn'
  return ''
}

const filteredPaths = computed(() => {
  if (!data.value) return []
  let paths = data.value.paths
  if (backendFilter.value !== 'all') {
    paths = paths.filter(p => p.backend === backendFilter.value)
  }
  // Phase 7.6: backend rank determines secondary sort (intra → async → 2pc).
  // Failed paths float to top, then within same status group order by backend
  // (intra cluster first since they're the newest test category), then path_id.
  const backendRank: Record<string, number> = { intra: 0, async: 1, '2pc': 2 }
  return [...paths].sort((a, b) => {
    const aOk = (a.last_result?.outcome === 'passed') ? 1 : 0
    const bOk = (b.last_result?.outcome === 'passed') ? 1 : 0
    if (aOk !== bOk) return aOk - bOk
    const ar = backendRank[a.backend] ?? 99
    const br = backendRank[b.backend] ?? 99
    if (ar !== br) return ar - br
    return a.path_id.localeCompare(b.path_id)
  })
})

// Phase 7.6: per-backend breakdown for the hero stat row.
// Returns [{backend, total, passed, failing}] sorted intra→async→2pc.
const backendBreakdown = computed(() => {
  if (!data.value) return []
  const buckets: Record<string, { total: number; passed: number }> = {}
  for (const p of data.value.paths) {
    const be = p.backend || 'unknown'
    if (!buckets[be]) buckets[be] = { total: 0, passed: 0 }
    buckets[be].total += 1
    if (p.last_result?.outcome === 'passed') buckets[be].passed += 1
  }
  const order = ['intra', 'async', '2pc']
  return order
    .filter((be) => buckets[be])
    .map((be) => ({ backend: be, total: buckets[be].total, passed: buckets[be].passed }))
})

// Locally hide failures fired before the user-clicked clear time.
// Pure client-side — does NOT delete anything from the DB. Persists across reloads
// in localStorage as cn-failures-cleared-iso.
const failuresClearedAt = ref<string>(localStorage.getItem('cn-failures-cleared-iso') || '')
const visibleFailures = computed(() => {
  if (!data.value) return []
  if (!failuresClearedAt.value) return data.value.recent_failures
  const cutoff = dayjs(failuresClearedAt.value)
  return data.value.recent_failures.filter((f) => {
    if (!f.fired_at) return true
    return dayjs(f.fired_at).isAfter(cutoff)
  })
})
const clearFailures = () => {
  failuresClearedAt.value = new Date().toISOString()
  try { localStorage.setItem('cn-failures-cleared-iso', failuresClearedAt.value) } catch { /* ignore */ }
}

const formatPercent = (n: number | null): string => {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(1)}%`
}

const formatMs = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

const lastRelative = (iso: string | null): string => {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}
/* §CANARYUNIFY pass 3 — tile-sized relative time. "6 minutes ago" wrapped to
   three lines inside a narrow stat tile and inflated the whole row; "6m ago"
   says the same thing on one. Used ONLY in the tiles — the expanded detail and
   the event log keep the full phrasing. */
const lastRelativeShort = (iso: string | null): string => {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 45) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

const cardClass = (p: CanaryPath): string[] => {
  const classes = ['cn-card']
  if (!p.is_active) classes.push('cn-card-disabled')
  const last = p.last_result
  const passRate = p.stats_24h.pass_rate
  if (last?.outcome === 'passed') classes.push('cn-card-ok')
  else if (last?.outcome === 'failed') classes.push('cn-card-bad')
  else if (last?.outcome === 'fired') classes.push('cn-card-pending')
  if (passRate !== null && passRate < 50) classes.push('cn-card-warn')
  return classes
}

const statusEmoji = (p: CanaryPath): string => {
  if (!p.is_active) return '⚫'
  const last = p.last_result
  if (!last) return '⚪'
  if (last.outcome === 'passed') return '🟢'
  if (last.outcome === 'failed') return '🔴'
  if (last.outcome === 'fired') return '🟡'
  return '⚪'
}

const statusLabel = (p: CanaryPath): string => {
  if (!p.is_active) return 'DISABLED'
  const last = p.last_result
  if (!last) return 'NO TESTS YET'
  return last.outcome.toUpperCase()
}

const togglePath = async (id: number) => {
  try {
    await apiClient.post(`/admin/canary/path/${id}/toggle`, {})
    await fetchStatus()
  } catch (e) {
    error.value = `Toggle failed: ${e instanceof Error ? e.message : String(e)}`
  }
}

const firePath = async (id: number) => {
  fireBusy.value = id
  try {
    await apiClient.post('/admin/canary/fire', { path_id: id })
    fireFlash.value = `Path ${id} scheduled — should fire within 5s`
    setTimeout(() => { fireFlash.value = '' }, 6000)
  } catch (e) {
    error.value = `Fire failed: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    fireBusy.value = null
  }
}

const expandPath = (id: number) => {
  expandedPathId.value = expandedPathId.value === id ? null : id
}

const backendChipClass = (backend: string): string => {
  if (backend === 'async') return 'cn-chip cn-chip-cyan'
  if (backend === '2pc') return 'cn-chip cn-chip-purple'
  if (backend === 'intra') return 'cn-chip cn-chip-amber'
  return 'cn-chip cn-chip-muted'
}

const passRateCls = (rate: number | null): string => {
  if (rate === null) return 'cn-stat-muted'
  if (rate >= 95) return 'cn-stat-ok'
  if (rate >= 70) return 'cn-stat-warn'
  return 'cn-stat-bad'
}

// Frame B agents to show with frame-b chip
const frameChip = (frame: string): string => {
  return frame === 'frame-b' ? 'cn-frame-chip cn-frame-b' : 'cn-frame-chip cn-frame-a'
}

// Phase 11 — live log helpers
const filteredLog = computed(() => {
  if (logFilter.value === 'all') return eventLog.value
  return eventLog.value.filter((e) => e.outcome === logFilter.value)
})

const logCounts = computed(() => {
  const c = { passed: 0, failed: 0, fired: 0 }
  for (const e of eventLog.value) {
    if (e.outcome === 'passed') c.passed += 1
    else if (e.outcome === 'failed') c.failed += 1
    else if (e.outcome === 'fired') c.fired += 1
  }
  return c
})

const logRowClass = (e: LogEntry): string => {
  if (e.outcome === 'passed') return 'cn-log-row cn-log-passed'
  if (e.outcome === 'failed') return 'cn-log-row cn-log-failed'
  if (e.outcome === 'fired') return 'cn-log-row cn-log-fired'
  return 'cn-log-row'
}

const logOutcomeIcon = (o: string): string => {
  if (o === 'passed') return '✓'
  if (o === 'failed') return '✗'
  if (o === 'fired') return '◌'
  return '·'
}

const clearLog = () => {
  eventLog.value = []
  seenTestIds.clear()
  newEventsWhileCollapsed.value = 0
}

const toggleLogCollapsed = () => {
  logCollapsed.value = !logCollapsed.value
  if (!logCollapsed.value) newEventsWhileCollapsed.value = 0
}
</script>

<template>
<div class="cn">
  <!-- Ambient background (matches AdminReactors) -->
  <div class="cn-ambient">
    <div class="cn-grid"></div>
    <div class="cn-scan"></div>
    <div class="cn-glow cn-glow-1"></div>
    <div class="cn-glow cn-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="cn-hero">
    <div class="cn-hero-inner">
      <div class="cn-chip-hero"><span class="cn-chip-dot"></span>{{ t('adminCanariesView.hero.chip') }}</div>
      <h1 class="cn-h1">
        {{ t('adminCanariesView.hero.h1a') }}<span class="cn-accent">{{ t('adminCanariesView.hero.h1Accent') }}</span>{{ t('adminCanariesView.hero.h1b') }}
        <button
          class="cn-info-btn"
          @click="infoOpen = !infoOpen"
          :aria-expanded="infoOpen"
          aria-controls="cn-info-panel"
          aria-label="About the canary system"
          title="About the canary system"
        >i</button>
      </h1>
      <p class="cn-lead">{{ t('adminCanariesView.hero.lead') }}</p>

      <!-- Info popover — toggled by the (i) button -->
      <transition name="cn-info">
        <div v-if="infoOpen" id="cn-info-panel" class="cn-info-panel" role="region" aria-label="Canary system architecture">
          <button class="cn-info-close" @click="infoOpen = false" aria-label="Close panel">×</button>
          <h3 class="cn-info-title">{{ t('adminCanariesView.info.title') }}</h3>
          <div class="cn-info-grid">
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.pathMatrix') }}</div>
              <p>Three transfer backends are exercised in parallel: <code>intra</code> (same-registry <code>/teg/transfer</code>), <code>async</code> (SF-4 cross-frame replication), and <code>2pc</code> (synchronous cross-TEG two-phase commit). Each path runs an isolated funded sender → receiver pair.</p>
            </div>
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.fireCadence') }}</div>
              <p>The runner fires each path on its configured interval (default 60s) from a leader-elected worker. Per-fire it inserts a <code>canary_test_results</code> row, writes a Redis state hash, and submits the transfer to the source registry's TEG.</p>
            </div>
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.validation') }}</div>
              <p>The validator subscribes to the EventStore websocket and stamps each test as it observes <code>TokensTransferred</code>, <code>CrossFrameTransferInitiated</code>, and <code>CrossFrameTransferSettled</code>. The judge then evaluates per-backend completion criteria and persists the final outcome.</p>
            </div>
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.failureSemantics') }}</div>
              <p>A test fails if the HTTP submission errors, the SLO is exceeded, or any required event fails to surface within the settled-by deadline. Supply invariance is verified independently by the auditor service — its dedicated dashboard is the source of truth for Δ across both frames.</p>
            </div>
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.observability') }}</div>
              <p>This dashboard polls <code>/api/v1/admin/canary/status</code>. The live event log below tails <code>last_result</code> changes across refreshes. Metrics emit to Prometheus (<code>canary_*</code>) and trip Alertmanager rules on sustained pass-rate breach. Underlying transfers are independent of this metadata table — clearing it never affects the supply invariant.</p>
            </div>
            <div class="cn-info-block">
              <div class="cn-info-h">{{ t('adminCanariesView.info.source') }}</div>
              <p>Runner: <code>background_tasks/canary_runner.py</code>. Validator: <code>background_tasks/canary_validator.py</code>. Judge: <code>background_tasks/canary_judge.py</code>. Status API: <code>routers/admin_canary.py</code>. Tables: <code>canary_agents</code>, <code>canary_paths</code>, <code>canary_test_results</code>.</p>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </section>

  <!-- Loading -->
  <div v-if="loading" class="cn-center">
    <div class="cn-spinner"></div>
    <p class="cn-loading-text">{{ t('adminCanariesView.loading') }}</p>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="cn-center">
    <p class="cn-error-text">{{ error }}</p>
    <button @click="fetchStatus" class="cn-btn cn-btn-ghost" style="margin-top:12px;">{{ t('adminCanariesView.retry') }}</button>
  </div>

  <!-- Dashboard -->
  <div v-else-if="data" class="cn-section">
    <!-- Summary stats -->
    <div class="cn-stats-row">
      <div class="cn-stat cn-stat-cyan">
        <span class="cn-stat-label">{{ t('adminCanariesView.stats.activePaths') }}</span>
        <span class="cn-stat-value">{{ data.summary.active_paths }}</span>
        <span class="cn-stat-sub">/ {{ data.summary.total_paths }} {{ t('adminCanariesView.stats.total') }}</span>
      </div>
      <div class="cn-stat" :class="passRateCls(data.summary.pass_rate_24h)">
        <span class="cn-stat-label">{{ t('adminCanariesView.stats.passRate24h') }}</span>
        <span class="cn-stat-value">{{ formatPercent(data.summary.pass_rate_24h) }}</span>
        <span class="cn-stat-sub">{{ t('adminCanariesView.stats.passesFails', { passes: data.summary.passes_24h, fails: data.summary.failures_24h }) }}</span>
      </div>
      <div class="cn-stat" :class="data.summary.pending_count > 5 ? 'cn-stat-warn' : 'cn-stat-cyan'">
        <span class="cn-stat-label">{{ t('adminCanariesView.stats.pending') }}</span>
        <span class="cn-stat-value">{{ data.summary.pending_count }}</span>
        <span class="cn-stat-sub">{{ t('adminCanariesView.stats.inFlight') }}</span>
      </div>
      <div class="cn-stat cn-stat-cyan">
        <span class="cn-stat-label">{{ t('adminCanariesView.stats.firesPerMin') }}</span>
        <span class="cn-stat-value">{{ data.summary.tests_per_minute_5m.toFixed(1) }}</span>
        <span class="cn-stat-sub">{{ t('adminCanariesView.stats.fiveMinAvg') }}</span>
      </div>
      <div v-if="showCockpit && fleet" class="cn-stat" :class="fleet.fleet_paused ? 'cn-stat-warn' : 'cn-stat-purple'">
        <span class="cn-stat-label">FEDERATED PATHS</span>
        <span class="cn-stat-value">{{ federatedActive }}</span>
        <span class="cn-stat-sub">/ {{ fleet.remote_paths.length }} scheduled from this cockpit</span>
      </div>
    </div>

    <!-- §CANARYUNIFY pass 4 — the Fleet Cockpit's per-home PANELS are gone: their
         paths now live in the one card grid below, tagged with their home. What
         survives here is what is genuinely fleet-level and has no per-path home:
         the scheduler mode and the fleet kill switch. -->
    <div v-if="showCockpit && fleet" class="cn-fleetbar" data-testid="cn-fleet-cockpit">
      <span class="cn-fleet-title">FLEET SCHEDULER</span>
      <span class="cn-chip cn-chip-purple">MODE {{ fleet.mode.toUpperCase() }}</span>
      <span :class="fleet.fleet_paused ? 'cn-chip cn-chip-red' : 'cn-chip cn-chip-cyan'">
        {{ fleet.fleet_paused ? 'PAUSED' : 'SCHEDULING' }}
      </span>
      <span class="cn-fleet-sub">
        {{ federatedActive }}/{{ fleet.remote_paths.length }} federated · {{ fleet.local_paths.active }}/{{ fleet.local_paths.total }} local —
        one scheduler, their agents: fires execute on each home registry over federation mTLS
      </span>
      <button
        class="cn-btn cn-btn-sm"
        :class="fleet.fleet_paused ? 'cn-btn-primary' : 'cn-btn-danger'"
        :disabled="fleetBusy"
        @click="fleetPauseToggle"
        data-testid="cn-fleet-pause"
      >
        {{ fleet.fleet_paused ? '▶ RESUME FLEET' : '⏸ PAUSE FLEET' }}
      </button>
    </div>
    <ReadFailedNotice v-if="fleetFailed" dense data-testid="cn-fleet-unread" :retry="fetchFleet"
      :text="fleet ? `The fleet scheduler could not be read just now. Its state above is from the read at ${fleetReadAt}.` : 'The fleet scheduler could not be read just now, so whether the fleet is paused is not shown.'" />
    <div v-if="fleetFlash" class="cn-flash">{{ fleetFlash }}</div>

    <!-- Phase 7.6: per-backend breakdown -->
    <div v-if="backendBreakdown.length" class="cn-backend-row" data-testid="cn-backend-breakdown">
      <span class="cn-backend-label">Scope</span>
      <button v-for="sc in (['all','local','federated'] as const)" :key="sc"
        @click="scopeFilter = sc"
        :class="['cn-backend-pill', scopeFilter === sc ? 'cn-backend-pill-active' : '', sc === 'federated' ? 'cn-chip-purple' : 'cn-chip-muted']"
        :data-testid="`cn-scope-${sc}`">
        {{ sc === 'all' ? `ALL ${localCount + fedCount}` : sc === 'local' ? `LOCAL ${localCount}` : `FEDERATED ${fedCount}` }}
      </button>
      <span class="cn-backend-label">{{ t('adminCanariesView.backends') }}</span>
      <button
        v-for="b in backendBreakdown"
        :key="b.backend"
        @click="backendFilter = (backendFilter === b.backend ? 'all' : b.backend)"
        :class="['cn-backend-pill', backendChipClass(b.backend), backendFilter === b.backend ? 'cn-backend-pill-active' : '']"
        :title="b.backend === 'intra' ? 'Same-registry /teg/transfer probes (Phase 7.6)' : (b.backend === '2pc' ? 'Two-phase commit cross-TEG (Phase 7)' : 'Async cross-frame via SF-4 broadcast')"
      >
        <span class="cn-backend-pill-name">{{ b.backend }}</span>
        <span class="cn-backend-pill-stat">{{ b.passed }}/{{ b.total }}</span>
      </button>
    </div>

    <!-- Toolbar -->
    <div class="cn-toolbar">
      <div class="cn-toolbar-info">
        <span class="cn-mono-label">{{ t('common.lastRefresh') }}</span>
        <span class="cn-mono-value">{{ lastRefreshAt || '—' }}</span>
        <span class="cn-mono-label" style="margin-left: 14px;">{{ t('adminCanariesView.every') }}</span>
        <select :aria-label="t('adminCanariesView.refreshAria', 'Refresh every')"
          v-model.number="refreshSec"
          @change="onRefreshSecChange"
          :disabled="!autoRefresh"
          class="cn-select"
          data-testid="cn-refresh-interval"
        >
          <option v-for="opt in REFRESH_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <span class="cn-mono-label" style="margin-left: 14px;">{{ t('adminCanariesView.backend') }}</span>
        <select :aria-label="t('adminCanariesView.backendAria', 'Backend')" v-model="backendFilter" class="cn-select">
          <option value="all">{{ t('adminCanariesView.backendOpts.all') }}</option>
          <option value="async">{{ t('adminCanariesView.backendOpts.async') }}</option>
          <option value="2pc">2pc</option>
          <option value="intra">{{ t('adminCanariesView.backendOpts.intra') }}</option>
        </select>
      </div>
      <div class="cn-toolbar-actions">
        <span class="cn-live-dot" :class="{ 'cn-live-dot-active': autoRefresh }" :title="autoRefresh ? 'Auto-refresh active' : 'Auto-refresh paused'" aria-hidden="true"></span>
        <button
          class="cn-btn cn-btn-ghost"
          @click="toggleAutoRefresh"
          :aria-label="autoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh'"
          data-testid="cn-toggle-autorefresh"
        >
          {{ autoRefresh ? t('adminCanariesView.pause') : t('adminCanariesView.resume') }}
        </button>
        <button
          class="cn-btn cn-btn-primary"
          @click="fetchStatus"
          :aria-label="t('adminCanariesView.refreshAriaLabel')"
          data-testid="cn-refresh-now"
        >
          ↻ {{ t('common.refresh') }}
        </button>
      </div>
    </div>

    <!-- Fire flash banner -->
    <div v-if="fireFlash" class="cn-flash">{{ fireFlash }}</div>

    <!-- Recent failures alert (only if there are visible recent failures) -->
    <div v-if="visibleFailures.length > 0" class="cn-failures">
      <div class="cn-failures-head">
        <span class="cn-failures-title"><Icon name="mdi:alert" /> {{ t('adminCanariesView.recentFailures') }}</span>
        <span class="cn-failures-count">
          {{ visibleFailures.length }} {{ failuresClearedAt ? t('adminCanariesView.sinceTime', { time: dayjs(failuresClearedAt).format('HH:mm:ss') }) : t('adminCanariesView.mostRecent') }}
        </span>
        <button
          class="cn-btn cn-btn-ghost cn-btn-sm"
          style="margin-left:auto;"
          @click="clearFailures"
          data-testid="cn-clear-failures"
          :title="t('adminCanariesView.clearTitle')"
        >
          {{ t('adminCanariesView.clear') }}
        </button>
      </div>
      <div class="cn-failures-list">
        <div v-for="f in visibleFailures" :key="f.test_id" class="cn-failure-row">
          <code class="cn-failure-time">{{ f.fired_at ? dayjs(f.fired_at).format('HH:mm:ss') : '—' }}</code>
          <code class="cn-failure-test">{{ f.test_id.slice(0, 40) }}…</code>
          <span class="cn-failure-type">{{ f.failure_type || 'unknown' }}</span>
          <span v-if="f.http_status" class="cn-failure-http">HTTP {{ f.http_status }}</span>
        </div>
      </div>
    </div>

    <!-- Path cards grid -->
    <div v-if="filteredPaths.length === 0" class="cn-empty-block" data-testid="cn-paths-empty">
      <span class="cn-log-empty-pulse" aria-hidden="true"></span>
      <span>{{ t('adminCanariesView.noPathsForFilter', { backend: backendFilter }) }}</span>
    </div>
    <div v-else class="cn-cards" data-testid="cn-paths-grid">
      <!-- §CANARYUNIFY pass 4 — ONE grid. Local paths (executed here) and
           federated paths (scheduled here, executed on another home) used to be
           two separate panels with two different visual languages; they are the
           same concept — a canary path — so they are now the same card, tagged
           by scope. Federated cards carry dispatch data instead of settlement
           stats because that is genuinely all the scheduler knows. -->
      <div
        v-for="u in unifiedPaths"
        :key="u.key"
        :class="u.stateCls"
        :data-testid="`cn-path-${u.key}`"
      >
        <div class="cn-card-head" @click="u.local && expandPath(u.local.id)">
          <div class="cn-card-title-row">
            <span class="cn-emoji">{{ u.local ? statusEmoji(u.local) : remoteDot(u.remote!) }}</span>
            <h3 class="cn-card-title" :title="u.title">{{ u.title }}</h3>
            <span v-if="u.backend" :class="backendChipClass(u.backend)">{{ u.backend }}</span>
            <span :class="u.scope === 'local' ? 'cn-chip cn-chip-muted' : 'cn-chip cn-chip-purple'"
                  :title="u.scope === 'local' ? 'Runs on this registry' : `Scheduled here, executes on ${u.home}`">
              {{ u.scope === 'local' ? 'LOCAL' : u.home }}
            </span>
          </div>
          <div class="cn-card-head-right">
            <span class="cn-card-status">{{ u.statusText }}</span>
            <button
              class="cn-u-toggle"
              :class="{ 'cn-u-toggle-on': !u.isActive }"
              :disabled="u.scope === 'federated' && fleetBusy"
              @click.stop="u.local ? togglePath(u.local.id) : toggleRemotePath(u.remote!)"
              :data-testid="`cn-head-toggle-${u.key}`"
              :aria-label="`${u.isActive ? 'Disable' : 'Enable'} canary path ${u.title}`"
              :title="u.isActive ? 'Disable this path' : 'Enable this path'"
            >
              {{ u.isActive ? 'Disable' : 'Enable' }}
            </button>
          </div>
        </div>

        <div class="cn-card-body">
          <div class="cn-stat-grid-4">
            <div v-for="t in u.tiles" :key="t.label" class="cn-mini-stat">
              <span class="cn-mini-label">{{ t.label }}</span>
              <span class="cn-mini-value" :class="t.cls" :title="t.title">{{ t.value }}</span>
            </div>
          </div>
          <div class="cn-card-divider"></div>
          <div v-for="r in u.rows" :key="r.label" class="cn-card-row">
            <span>{{ r.label }}</span>
            <span :class="r.mono ? 'cn-card-val' : ''">{{ r.value }}</span>
          </div>

          <!-- local paths keep the full expanded detail + Fire Now -->
          <div v-if="u.local && expandedId === u.local.id" class="cn-expanded">
            <div class="cn-card-divider"></div>
            <div v-if="u.local.last_result?.failure_detail" class="cn-card-row cn-card-row-error">
              <span>Failure</span><span class="cn-card-val">{{ u.local.last_result.failure_type }}</span>
            </div>
            <div class="cn-card-actions">
              <button
                class="cn-btn cn-btn-primary"
                :disabled="fireBusy === u.local.id"
                @click.stop="firePath(u.local.id)"
                :data-testid="`cn-fire-${u.local.id}`"
              >
                {{ fireBusy === u.local.id ? 'Firing…' : '⚡ Fire Now' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Canary agents roster -->
    <section class="cn-agents">
      <div class="cn-agents-head">
        <span class="cn-agents-title">CANARY AGENTS</span>
        <span class="cn-agents-count">{{ data.agents.length }} total</span>
      </div>
      <div class="cn-agents-grid" data-testid="cn-agents-grid">
        <div
          v-for="a in data.agents"
          :key="a.id"
          class="cn-agent-card"
          :data-testid="`cn-agent-${a.id}`"
        >
          <div class="cn-agent-head">
            <span class="cn-emoji">{{ a.is_active ? '🟢' : '⚫' }}</span>
            <strong class="cn-agent-name">{{ a.name }}</strong>
            <span :class="frameChip(a.frame)">{{ a.frame }}</span>
          </div>
          <div class="cn-agent-body">
            <div class="cn-card-row">
              <span class="cn-mono-label">Registry</span>
              <code class="cn-code-muted">{{ a.registry_id }}</code>
            </div>
            <div class="cn-card-row">
              <span class="cn-mono-label">DID</span>
              <code class="cn-code-muted cn-code-trunc" :title="a.agent_did">{{ a.agent_did.slice(0, 30) }}…</code>
            </div>
            <div class="cn-card-row">
              <span class="cn-mono-label">Pre-fund</span>
              <span class="cn-card-val">{{ parseFloat(a.prefund_amount).toLocaleString(appLocale()) }} {{ localCurrency }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Phase 11: live event log -->
    <section class="cn-log" :class="{ 'cn-log-collapsed': logCollapsed }" data-testid="cn-log">
      <div class="cn-log-head">
        <div class="cn-log-head-left">
          <button
            class="cn-log-toggle"
            @click="toggleLogCollapsed"
            :aria-expanded="!logCollapsed"
            aria-controls="cn-log-body"
            :title="logCollapsed ? 'Expand log' : 'Collapse log'"
          >
            <span class="cn-log-caret">{{ logCollapsed ? '▸' : '▾' }}</span>
            <span class="cn-log-title">LIVE EVENT LOG</span>
            <span
              v-if="logCollapsed && newEventsWhileCollapsed > 0"
              class="cn-log-new-badge"
              :title="`${newEventsWhileCollapsed} new event${newEventsWhileCollapsed === 1 ? '' : 's'} since collapsed`"
            >+{{ newEventsWhileCollapsed }}</span>
          </button>
          <span class="cn-log-count">
            <span class="cn-log-pill cn-log-pill-passed">{{ logCounts.passed }} ✓</span>
            <span class="cn-log-pill cn-log-pill-failed">{{ logCounts.failed }} ✗</span>
            <span class="cn-log-pill cn-log-pill-fired">{{ logCounts.fired }} ◌</span>
          </span>
        </div>
        <div v-if="!logCollapsed" class="cn-log-head-right">
          <span class="cn-mono-label">Filter:</span>
          <select :aria-label="t('adminCanariesView.logFilterAria', 'Filter the log')" v-model="logFilter" class="cn-select" data-testid="cn-log-filter">
            <option value="all">all</option>
            <option value="passed">passed</option>
            <option value="failed">failed</option>
            <option value="fired">fired</option>
          </select>
          <label class="cn-log-toggle-label" :title="'Auto-scroll to top when new events arrive'">
            <input type="checkbox" v-model="logAutoTail" />
            <span>Auto-tail</span>
          </label>
          <button class="cn-btn cn-btn-ghost cn-btn-sm" @click="clearLog" data-testid="cn-log-clear">
            Clear
          </button>
        </div>
      </div>
      <div v-if="!logCollapsed" id="cn-log-body" class="cn-log-body" :class="{ 'cn-log-body-tailed': logAutoTail }">
        <div v-if="filteredLog.length === 0" class="cn-log-empty">
          <span class="cn-log-empty-pulse" aria-hidden="true"></span>
          {{ eventLog.length === 0 ? 'No events captured yet. Waiting for next refresh…' : `No ${logFilter} events in log.` }}
        </div>
        <div v-else class="cn-log-list" role="log" aria-live="polite" data-testid="cn-log-list">
          <div
            v-for="e in filteredLog"
            :key="e.test_id"
            :class="logRowClass(e)"
          >
            <span class="cn-log-icon" :title="e.outcome">{{ logOutcomeIcon(e.outcome) }}</span>
            <code class="cn-log-time">{{ e.fired_at ? dayjs(e.fired_at).format('HH:mm:ss') : '—' }}</code>
            <span :class="backendChipClass(e.backend)" class="cn-log-backend">{{ e.backend }}</span>
            <span class="cn-log-path">
              <code class="cn-log-name">{{ e.sender }}</code>
              <span class="cn-log-arrow">→</span>
              <code class="cn-log-name">{{ e.receiver }}</code>
            </span>
            <span class="cn-log-meta">
              <span v-if="e.http_status" class="cn-log-http">HTTP {{ e.http_status }}</span>
              <span v-if="e.total_latency_ms !== null" class="cn-log-latency">{{ formatMs(e.total_latency_ms) }}</span>
              <span v-if="e.failure_type" class="cn-log-fail">{{ e.failure_type }}</span>
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <div class="cn-footer">
      Canary system · {{ data.paths.length }} paths · {{ data.agents.length }} agents ·
      <code>/admin/canary/status</code> ·
      Snapshot {{ data.summary.snapshot_at ? dayjs(data.summary.snapshot_at).format('HH:mm:ss') : '' }}
    </div>
  </div>
</div>
</template>

<style scoped>
.cn {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  /* Phase 11 (2026-05-04 polish): theme-aware. Map all "cyan" usage to the
     active brand accent (cyan in 'neural', red in 'sovereign'). Semantic
     status colors (success/warning/danger) preserved across themes — they
     mean specific things and shouldn't be re-tinted by the brand switch.
     Local --cyan/--cyan-rgb aliases are kept as compatibility shims so old
     hardcoded uses below still work after the var swap. */
  --cn-accent: var(--nc-primary, #00d2d2);
  --cn-accent-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --cn-accent-bright: var(--nc-primary-bright, #00e5e5);
  --cn-accent-glow: var(--nc-primary-glow, rgba(0, 210, 210, 0.4));
  --cn-accent-subtle: var(--nc-primary-subtle, rgba(0, 210, 210, 0.1));
  /* Backwards-compatible aliases — re-routed to brand accent so theme switch propagates */
  --cyan: var(--cn-accent);
  --cyan-rgb: var(--cn-accent-rgb);
  /* Semantic status colors — fixed across themes */
  --red: var(--nc-danger, #ff3366);
  --green: var(--nc-success, #00ff88);
  --amber: var(--nc-warning, #ff9500);
  --purple: #b87aff;
  --muted: var(--nc-text-muted, #6b7785);
  --border: rgba(var(--cn-accent-rgb), 0.18);
  --surface: var(--nc-deep, #0a0d16);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: var(--nc-text-primary, #e8eaed);
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints. */
  color: var(--text-bright);
  transition: color 240ms ease;
  z-index: 1;
}

/* ── Ambient ─────────────────────────── */
.cn-ambient {
  position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
}
.cn-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cn-accent-rgb),0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cn-accent-rgb),0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.cn-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0, transparent 3px,
    rgba(var(--cn-accent-rgb),0.025) 3px, rgba(var(--cn-accent-rgb),0.025) 4px
  );
}
.cn-glow {
  position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
}
.cn-glow-1 { width: 480px; height: 480px; background: rgba(var(--cn-accent-rgb),0.6); top: -100px; right: -100px; }
.cn-glow-2 { width: 360px; height: 360px; background: rgba(255,51,102,0.4); bottom: -80px; left: -80px; }

/* ── Hero ───────────────────────────── */
.cn-hero { position: relative; z-index: 1; padding: 48px 32px 24px; }
.cn-hero-inner { max-width: 1280px; margin: 0 auto; }
.cn-chip-hero {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px; border: 1px solid rgba(var(--cn-accent-rgb),0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--cn-accent-rgb),0.04);
}
.cn-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
  animation: cnPulse 1.6s ease-in-out infinite;
}
@keyframes cnPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.cn-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 36px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--text-bright); line-height: 1.15;
}
.cn-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cn-accent-rgb),0.45); }
.cn-lead { color: var(--muted); font-size: 14px; max-width: 760px; line-height: 1.7; margin: 0; }

/* Hero info button */
.cn-info-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px;
  margin-left: 14px; vertical-align: middle;
  font-family: 'Orbitron', monospace; font-style: italic;
  font-size: 12px; font-weight: 700;
  color: var(--cyan); background: transparent;
  border: 1px solid rgba(var(--cn-accent-rgb), 0.4);
  border-radius: 50%; cursor: pointer;
  transition: all 0.15s ease;
  position: relative; top: -3px;
}
.cn-info-btn:hover {
  background: rgba(var(--cn-accent-rgb), 0.1);
  border-color: rgba(var(--cn-accent-rgb), 0.7);
  box-shadow: 0 0 14px rgba(var(--cn-accent-rgb), 0.35);
}
.cn-info-btn:focus-visible {
  outline: 1px solid rgba(var(--cn-accent-rgb), 0.7);
  outline-offset: 2px;
}
.cn-info-btn[aria-expanded="true"] {
  background: rgba(var(--cn-accent-rgb), 0.18);
  border-color: var(--cyan);
}

.cn-info-panel {
  position: relative;
  margin-top: 22px;
  padding: 22px 26px;
  background: linear-gradient(180deg, rgba(var(--cn-accent-rgb), 0.05), rgba(10,13,22,0.92));
  border: 1px solid rgba(var(--cn-accent-rgb), 0.28);
  border-left: 3px solid var(--cyan);
  border-radius: 5px;
  max-width: 980px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.45), 0 0 36px rgba(var(--cn-accent-rgb), 0.06);
}
.cn-info-close {
  position: absolute; top: 10px; right: 14px;
  width: 24px; height: 24px;
  background: transparent; border: 0; cursor: pointer;
  font-size: 18px; line-height: 1; color: var(--muted);
  border-radius: 4px;
  transition: color 0.15s ease, background 0.15s ease;
}
.cn-info-close:hover { color: var(--cyan); background: rgba(var(--cn-accent-rgb), 0.08); }
.cn-info-close:focus-visible {
  outline: 1px solid rgba(var(--cn-accent-rgb), 0.7);
  outline-offset: 1px;
}
.cn-info-title {
  font-family: 'Orbitron', sans-serif; font-weight: 700; font-size: 14px;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--cyan); margin: 0 0 14px 0;
}
.cn-info-grid {
  display: grid; gap: 16px 28px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}
.cn-info-block { font-family: var(--mono); font-size: 12px; line-height: 1.65; color: var(--text-bright); }
.cn-info-h {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--cyan); margin-bottom: 4px;
}
.cn-info-block p { margin: 0; color: #b9c1cc; font-size: 11.5px; }
.cn-info-block code {
  background: rgba(var(--cn-accent-rgb), 0.08); color: var(--cyan);
  padding: 1px 5px; border-radius: 2px; font-size: 10.5px;
}

/* Info panel reveal animation */
.cn-info-enter-active, .cn-info-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
.cn-info-enter-from, .cn-info-leave-to {
  opacity: 0; transform: translateY(-6px);
}

/* ── Section ─────────────────────────── */
.cn-section {
  position: relative; z-index: 1;
  max-width: 1280px; margin: 24px auto 0; padding: 0 32px;
  animation: cnFadeIn 0.4s ease-out;
}
@keyframes cnFadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.cn-center { position: relative; z-index: 1; text-align: center; padding: 80px 32px; }
.cn-error-text { color: #f87171; font-family: var(--mono); font-size: 12px; }

/* ── Stats row ───────────────────────── */
.cn-stats-row { display: flex; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
.cn-stat {
  flex: 1; min-width: 140px;
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(10,13,22,0.85), rgba(6,8,16,0.85));
  border: 1px solid var(--border); border-top-color: rgba(var(--cn-accent-rgb),0.32);
  border-radius: 5px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3), inset 0 1px 0 rgba(var(--cn-accent-rgb),0.05);
}
.cn-stat-label {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted);
}
.cn-stat-value {
  font-family: 'Orbitron', monospace; font-weight: 700; font-size: 26px;
  letter-spacing: 0.02em; color: var(--text-bright);
}
.cn-stat-sub { font-family: var(--mono); font-size: 10px; color: var(--muted); }
.cn-stat-cyan .cn-stat-value { color: var(--cyan); }
.cn-stat-ok .cn-stat-value { color: var(--green); }
.cn-stat-bad .cn-stat-value { color: var(--red); }
.cn-stat-warn .cn-stat-value { color: var(--amber); }
.cn-stat-muted .cn-stat-value { color: var(--muted); }

/* ── Toolbar ─────────────────────────── */
.cn-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 14px; margin-bottom: 12px;
  background: rgba(10,13,22,0.6);
  border: 1px solid var(--border); border-radius: 4px;
}
.cn-toolbar-info { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cn-toolbar-actions { display: flex; gap: 8px; }
.cn-mono-label { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.cn-mono-value { font-family: var(--mono); font-size: 11px; color: var(--text-bright); }

.cn-select {
  font-family: var(--mono); font-size: 11px;
  background: rgba(var(--cn-accent-rgb),0.06); color: var(--cyan);
  border: 1px solid rgba(var(--cn-accent-rgb),0.2); border-radius: 3px;
  padding: 3px 8px;
}

/* ── Flash banner ──────────────────── */
.cn-flash {
  margin-bottom: 12px; padding: 10px 14px;
  background: rgba(var(--cn-accent-rgb),0.08);
  border-left: 3px solid var(--cyan);
  border-radius: 4px;
  font-family: var(--mono); font-size: 12px; color: var(--cyan);
  animation: cnFlash 0.3s ease-in;
}
@keyframes cnFlash {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Failures section ────────────────── */
.cn-failures {
  margin-bottom: 16px; padding: 12px 16px;
  background: linear-gradient(180deg, rgba(255,51,102,0.06), rgba(255,51,102,0.02));
  border: 1px solid rgba(255,51,102,0.25);
  border-left-width: 3px;
  border-radius: 4px;
}
.cn-failures-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.cn-failures-title { font-family: var(--mono); font-size: 11px; font-weight: 700; letter-spacing: 0.14em; color: var(--red); }
.cn-failures-count { font-family: var(--mono); font-size: 10px; color: var(--muted); }
.cn-failures-list { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow-y: auto; }
.cn-failure-row {
  display: grid; grid-template-columns: 80px 1fr 120px 80px;
  gap: 12px; align-items: center;
  font-family: var(--mono); font-size: 11px;
  padding: 4px 6px; border-radius: 3px;
}
.cn-failure-row:hover { background: rgba(255,51,102,0.04); }
.cn-failure-time { color: var(--muted); font-size: 10px; }
.cn-failure-test { color: var(--muted); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cn-failure-type { color: #f87171; }
.cn-failure-http { color: var(--amber); font-size: 10px; }

/* ── Cards grid ────────────────────── */
.cn-cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); }
.cn-card {
  position: relative; display: flex; flex-direction: column;
  padding: 16px 18px; cursor: pointer;
  background: linear-gradient(180deg, rgba(10,13,22,0.92), rgba(6,8,16,0.88));
  border: 1px solid var(--border); border-top-color: rgba(var(--cn-accent-rgb),0.18);
  border-radius: 5px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.32), 0 0 32px rgba(var(--cn-accent-rgb),0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.cn-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--cn-accent-rgb),0.5), transparent);
  opacity: 0.6;
}
.cn-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(0,0,0,0.4), 0 0 48px rgba(var(--cn-accent-rgb),0.08);
  border-top-color: rgba(var(--cn-accent-rgb),0.45);
}
.cn-card-ok { border-top-color: rgba(0,255,136,0.4); }
.cn-card-ok::before { background: linear-gradient(90deg, transparent, rgba(0,255,136,0.6), transparent); }
.cn-card-bad { border-top-color: rgba(255,51,102,0.45); }
.cn-card-bad::before { background: linear-gradient(90deg, transparent, rgba(255,51,102,0.6), transparent); }
.cn-card-pending { border-top-color: rgba(255,149,0,0.4); }
.cn-card-pending::before { background: linear-gradient(90deg, transparent, rgba(255,149,0,0.6), transparent); }
.cn-card-warn { border-top-color: rgba(255,149,0,0.5); }
.cn-card-disabled { opacity: 0.55; }

.cn-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
/* §CANARYUNIFY — status + always-visible toggle share the head's right column. */
.cn-card-head-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
/* §CANARYUNIFY pass 3 — was `flex-wrap: wrap`, which stranded the status dot on
   its own line and pushed the backend chip to a third whenever the path name was
   long. One line: the TITLE is the only thing that yields (ellipsis + title attr
   carries the full text); dot, chip and off-tag hold their size.
   NOTE: this is the ONLY .cn-card-title-row declaration — an earlier attempt
   added a second one ABOVE this line and lost, silently, to source order. */
.cn-card-title-row {
  display: flex; align-items: center; gap: 9px;
  flex-wrap: nowrap; min-width: 0; flex: 1 1 auto;
}
.cn-card-title-row > .cn-emoji,
.cn-card-title-row > .cn-chip { flex-shrink: 0; }
.cn-emoji { font-size: 14px; line-height: 1; }
.cn-card-title {
  min-width: 0; flex: 1 1 auto;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: 'Orbitron', sans-serif; font-weight: 700; font-size: 14px; letter-spacing: 0.04em; margin: 0; color: var(--text-bright); }
.cn-card-status { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; color: var(--muted); }
.cn-card-ok .cn-card-status { color: var(--green); }
.cn-card-bad .cn-card-status { color: var(--red); }
.cn-card-pending .cn-card-status { color: var(--amber); }
.cn-card-disabled .cn-card-status { color: var(--muted); }

.cn-chip {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 99px;
}
.cn-chip-cyan { background: rgba(var(--cn-accent-rgb),0.14); color: var(--cyan); border: 1px solid rgba(var(--cn-accent-rgb),0.3); }
.cn-chip-purple { background: rgba(184,122,255,0.14); color: var(--purple); border: 1px solid rgba(184,122,255,0.3); }
.cn-chip-amber { background: rgba(255,149,0,0.14); color: var(--amber); border: 1px solid rgba(255,149,0,0.3); }
.cn-chip-muted { background: rgba(107,119,133,0.14); color: var(--muted); border: 1px solid rgba(107,119,133,0.3); }
.cn-chip-red { background: rgba(248,113,113,0.14); color: var(--red); border: 1px solid rgba(248,113,113,0.3); }

/* ── §CANARYUNIFY (2026-08-05) ────────────────────────────────────────────
   The view had grown TWO design languages: the Fleet Cockpit (flat purple
   rows, 10px text, dashed rules) and the path cards (elevated surface, top
   accent rail, Orbitron numerals, stat tiles). Same page, two apps.

   Resolution — keep the CARD vocabulary (the richer one) and give the cockpit
   its capabilities INSIDE that vocabulary, rather than flattening either side:
     · one surface treatment      (.cn-u-surface)
     · one status rail            (top gradient rail, state-coloured)
     · one chip family            (.cn-chip* now shared by dispatch/backend/agg)
     · one numeral treatment      (Orbitron for every metric, both sections)
   The cockpit keeps what made it useful — always-visible Disable, dispatch
   outcome, interval, per-home aggregates — and the cards gain the same
   always-visible control instead of hiding it behind an expand.
   ------------------------------------------------------------------------ */

/* Shared surface: the card look, reusable at any density. */
.cn-u-surface {
  position: relative;
  background: linear-gradient(180deg, rgba(10,13,22,0.92), rgba(6,8,16,0.88));
  border: 1px solid var(--border);
  border-top-color: rgba(var(--cn-accent-rgb),0.18);
  border-radius: 5px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.32), 0 0 32px rgba(var(--cn-accent-rgb),0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.cn-u-surface::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--cn-accent-rgb),0.5), transparent);
  opacity: 0.6;
}
/* State rail — identical semantics on a cockpit row and on a path card. */
.cn-u-ok   { border-top-color: rgba(0,255,136,0.4); }
.cn-u-ok::before   { background: linear-gradient(90deg, transparent, rgba(0,255,136,0.6), transparent); }
.cn-u-bad  { border-top-color: rgba(255,51,102,0.45); }
.cn-u-bad::before  { background: linear-gradient(90deg, transparent, rgba(255,51,102,0.6), transparent); }
.cn-u-warn { border-top-color: rgba(255,149,0,0.5); }
.cn-u-warn::before { background: linear-gradient(90deg, transparent, rgba(255,149,0,0.6), transparent); }
.cn-u-off  { opacity: 0.5; border-top-color: rgba(107,119,133,0.35); }
.cn-u-off::before  { background: linear-gradient(90deg, transparent, rgba(107,119,133,0.45), transparent); }

/* One numeral treatment for every metric in the view. */
.cn-u-num {
  font-family: 'Orbitron', monospace; font-weight: 700;
  font-size: 11px; color: var(--text-bright); letter-spacing: 0.02em;
}

/* §CANARYUNIFY pass 2 — the control must be PRESENT, not LOUD.
   Pass 1 put a full-weight button on all 40 cards and all 29 cockpit rows; the
   least-used control became the loudest thing on the page and crowded the path
   label down to "fram…". Quiet it to a ghost that only asserts itself on hover,
   and let the data have the width back. */
.cn-u-toggle {
  flex-shrink: 0;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 3px 7px; line-height: 1.4;
  color: var(--muted);
  background: transparent;
  border: 1px solid rgba(107,119,133,0.28); border-radius: 3px;
  cursor: pointer; white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.cn-u-toggle:hover:not(:disabled) {
  color: var(--red);
  border-color: rgba(255,51,102,0.45);
  background: rgba(255,51,102,0.1);
}
/* Re-enabling is a constructive act — hover reads green, not red. */
.cn-u-toggle.cn-u-toggle-on:hover:not(:disabled) {
  color: var(--green);
  border-color: rgba(0,255,136,0.45);
  background: rgba(0,255,136,0.1);
}
.cn-u-toggle:disabled { opacity: 0.4; cursor: not-allowed; }
/* NOTE: an "off" tag was tried here and removed — `.cn-card-status` already
   renders DISABLED, so it printed the word twice and stole the title's width.
   The card was never missing the STATE, only the CONTROL. */

/* ── §V0046 FLEET COCKPIT ─────────────────────────────────────────────── */
.cn-stat-purple .cn-stat-value { color: var(--purple); }
.cn-btn-danger { background: rgba(248,113,113,0.12); color: var(--red); border-color: rgba(248,113,113,0.32); }
.cn-btn-danger:hover:not(:disabled) { background: rgba(248,113,113,0.22); }
.cn-fleetbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  border: 1px solid rgba(184,122,255,0.22);
  background: linear-gradient(180deg, rgba(184,122,255,0.06), rgba(184,122,255,0.015));
  border-radius: 5px; padding: 10px 14px; margin: 16px 0;
}
.cn-fleetbar .cn-btn { margin-left: auto; }
.cn-fleet-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cn-fleet-title {
  font-family: var(--mono); font-size: 12px; font-weight: 800;
  letter-spacing: 0.18em; color: var(--purple);
}
.cn-fleet-sub { font-size: 11px; color: var(--muted); flex: 1; min-width: 220px; }
.cn-fleet-head .cn-btn { margin-left: auto; }
.cn-fleet-homes {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 10px; margin-top: 12px;
}
/* §CANARYUNIFY — the home panel is now a card surface, not a flat purple box. */
.cn-fleet-home {
  position: relative;
  border: 1px solid var(--border); border-top-color: rgba(184,122,255,0.3);
  border-radius: 5px;
  padding: 11px 12px 9px;
  background: linear-gradient(180deg, rgba(10,13,22,0.92), rgba(6,8,16,0.88));
  box-shadow: 0 6px 18px rgba(0,0,0,0.32), 0 0 32px rgba(184,122,255,0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.cn-fleet-home::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(184,122,255,0.5), transparent);
  opacity: 0.6;
}
.cn-fleet-home:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(0,0,0,0.4), 0 0 48px rgba(184,122,255,0.08);
  border-top-color: rgba(184,122,255,0.55);
}
.cn-fleet-home-head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin-bottom: 8px; padding-bottom: 7px;
  border-bottom: 1px solid rgba(184,122,255,0.14);
}
.cn-fleet-home-name {
  font-family: var(--mono); font-size: 11px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-bright);
}
/* Aggregates adopt the shared chip family instead of bare coloured glyphs. */
.cn-fleet-home-agg { display: flex; gap: 5px; align-items: center; }
.cn-agg {
  font-family: var(--mono); font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
  border-radius: 3px; padding: 2px 5px; white-space: nowrap;
}
.cn-agg-ok  { color: var(--green); background: rgba(0,255,136,0.1);  border: 1px solid rgba(0,255,136,0.26); }
.cn-agg-bad { color: var(--red);   background: rgba(255,51,102,0.1); border: 1px solid rgba(255,51,102,0.28); }

/* Cockpit rows are now MINI-CARDS: same surface + status rail as a path card,
   at cockpit density, keeping the always-visible Disable that made them useful. */
.cn-fleet-row {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 8px; margin-top: 5px; font-size: 11px;
  border-radius: 4px;
  background: rgba(var(--cn-accent-rgb),0.035);
  border: 1px solid rgba(var(--cn-accent-rgb),0.08);
  border-left: 2px solid rgba(107,119,133,0.35);
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.cn-fleet-row:hover {
  background: rgba(var(--cn-accent-rgb),0.07);
  border-color: rgba(var(--cn-accent-rgb),0.2);
  transform: translateX(2px);
}
.cn-fleet-row-ok   { border-left-color: rgba(0,255,136,0.55); }
.cn-fleet-row-bad  { border-left-color: rgba(255,51,102,0.6); }
.cn-fleet-row-warn { border-left-color: rgba(255,149,0,0.55); }
.cn-fleet-row-off { opacity: 0.45; border-left-color: rgba(107,119,133,0.35); }
.cn-fleet-dot { font-size: 9px; flex-shrink: 0; }
/* pass 2 — the label IS the row's identity; it gets the width first and every
   other element yields to it. Previously it collapsed to "fram…" while five
   secondary elements held their natural size. */
.cn-fleet-label {
  font-family: var(--mono); font-size: 10.5px; color: var(--text-bright);
  flex: 1 1 auto; min-width: 76px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Metrics use the shared numeral treatment — the cockpit no longer whispers. */
.cn-fleet-interval { font-family: 'Orbitron', monospace; font-weight: 700; font-size: 9px; color: var(--muted); flex-shrink: 0; }
.cn-fleet-lat { font-family: 'Orbitron', monospace; font-weight: 700; font-size: 10px; color: var(--cyan); flex-shrink: 0; }
/* Relative time is the least load-bearing field here — it sheds first. */
.cn-fleet-when {
  font-size: 9px; color: var(--muted); white-space: nowrap;
  flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
}
.cn-fleet-toggle { flex-shrink: 0; }
/* The dispatch chip is informative but repeats down the column — trim its
   weight so the label and latency lead. */
.cn-fleet-row .cn-chip { font-size: 8px; padding: 2px 5px; letter-spacing: 0.08em; flex-shrink: 0; }
@media (max-width: 1500px) {
  .cn-fleet-when { display: none; }
}

.cn-card-body { display: flex; flex-direction: column; gap: 6px; }
.cn-card-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; }
.cn-card-row-error { color: #f87171; }
.cn-card-val { color: var(--text-bright); font-family: var(--mono); font-size: 11px; }
.cn-text-ok { color: var(--green); }
.cn-text-bad { color: var(--red); }
.cn-text-warn { color: var(--amber); }
.cn-card-divider { height: 1px; margin: 8px 0; background: linear-gradient(90deg, transparent, rgba(var(--cn-accent-rgb),0.18), transparent); }

.cn-stat-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.cn-stat-grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 6px; }
/* pass 2 — tiles were ragged: "LAST LATENCY" wrapped to 2 lines and "2 minutes
   ago" to 3, so one long value inflated the whole row and left the other tiles
   half empty. Pin the label to a single line, let the value fill the rest, and
   bottom-align the values so the four read as one baseline. */
.cn-mini-stat {
  display: flex; flex-direction: column; gap: 3px;
  padding: 6px 8px; min-width: 0;
  background: rgba(var(--cn-accent-rgb),0.04); border: 1px solid rgba(var(--cn-accent-rgb),0.08); border-radius: 3px;
}
.cn-mini-label {
  font-family: var(--mono); font-size: 8px; font-weight: 600; letter-spacing: 0.08em;
  color: var(--muted); text-transform: uppercase;
  white-space: normal; overflow-wrap: anywhere; line-height: 1.25;
  min-height: 2.5em; /* 2 label lines — keeps all four values on one baseline */
}
.cn-mini-value {
  font-family: 'Orbitron', monospace; font-weight: 700; font-size: 13px;
  color: var(--text-bright);
  margin-top: auto; line-height: 1.25;
  overflow-wrap: anywhere;
}

/* Expanded section */
.cn-expanded { animation: cnExpand 0.2s ease-out; }
@keyframes cnExpand { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.cn-expanded-title { font-family: var(--mono); font-size: 9px; font-weight: 700; letter-spacing: 0.16em; color: var(--cyan); text-transform: uppercase; margin-bottom: 6px; }
.cn-card-actions { display: flex; gap: 8px; margin-top: 10px; }
.cn-empty-text { color: var(--muted); font-size: 11px; font-family: var(--mono); }

/* ── Code ─────────────────────────────── */
.cn-code {
  font-family: var(--mono); font-size: 11px; color: var(--cyan);
  background: rgba(var(--cn-accent-rgb),0.08);
  padding: 1px 6px; border-radius: 3px;
}
.cn-code-muted {
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  background: rgba(255,255,255,0.04);
  padding: 1px 6px; border-radius: 3px;
}
.cn-code-trunc { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }

/* ── Buttons ───────────────────────────── */
.cn-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 6px 14px; border-radius: 4px; border: 1px solid transparent; cursor: pointer;
  transition: all 0.15s;
}
.cn-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.cn-btn:focus-visible {
  outline: 1px solid rgba(var(--cn-accent-rgb), 0.7);
  outline-offset: 2px;
}
.cn-btn-ghost { background: transparent; color: var(--cyan); border-color: rgba(var(--cn-accent-rgb),0.2); }
.cn-btn-ghost:hover { background: rgba(var(--cn-accent-rgb),0.08); border-color: rgba(var(--cn-accent-rgb),0.4); }
.cn-btn-primary { background: rgba(var(--cn-accent-rgb),0.15); color: var(--cyan); border-color: rgba(var(--cn-accent-rgb),0.3); }
.cn-btn-primary:hover { background: rgba(var(--cn-accent-rgb),0.25); }
.cn-btn-sm { padding: 4px 10px; font-size: 11px; }

.cn-select:focus-visible {
  outline: 1px solid rgba(var(--cn-accent-rgb), 0.7);
  outline-offset: 1px;
}

/* Live activity dot (toolbar) */
.cn-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--muted);
  margin-right: 4px;
  transition: background 0.2s ease, box-shadow 0.2s ease;
}
.cn-live-dot-active {
  background: var(--green);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.6);
  animation: cnLivePulse 1.6s ease-in-out infinite;
}
@keyframes cnLivePulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

/* ── Spinner ───────────────────────────── */
.cn-spinner {
  width: 32px; height: 32px;
  border: 2px solid rgba(var(--cn-accent-rgb),0.15);
  border-top-color: var(--cyan);
  border-radius: 50%; margin: 0 auto;
  animation: cnSpin 0.8s linear infinite;
}
@keyframes cnSpin { to { transform: rotate(360deg); } }
.cn-loading-text { color: var(--muted); margin-top: 12px; font-size: 12px; font-family: var(--mono); }

/* ── Agents section ────────────────── */
.cn-agents { margin-top: 32px; }
.cn-agents-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.cn-agents-title { font-family: var(--mono); font-size: 12px; font-weight: 700; letter-spacing: 0.14em; color: var(--cyan); }
.cn-agents-count { font-family: var(--mono); font-size: 10px; color: var(--muted); }
.cn-agents-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.cn-agent-card {
  padding: 12px 14px;
  background: rgba(10,13,22,0.7);
  border: 1px solid rgba(var(--cn-accent-rgb),0.12);
  border-radius: 4px;
}
.cn-agent-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.cn-agent-name { font-family: 'Orbitron', sans-serif; font-size: 12px; color: var(--text-bright); }
.cn-frame-chip {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.1em;
  padding: 2px 7px; border-radius: 99px;
}
.cn-frame-a { background: rgba(var(--cn-accent-rgb),0.12); color: var(--cyan); border: 1px solid rgba(var(--cn-accent-rgb),0.3); }
.cn-frame-b { background: rgba(184,122,255,0.12); color: var(--purple); border: 1px solid rgba(184,122,255,0.3); }
.cn-agent-body { display: flex; flex-direction: column; gap: 4px; }

/* ── Phase 7.6: per-backend breakdown row ─────── */
.cn-backend-row {
  display: flex; align-items: center; flex-wrap: wrap;
  gap: 10px; padding: 8px 0 0; margin-bottom: 8px;
}
.cn-backend-label {
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.cn-backend-pill {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 5px 12px; border-radius: 99px;
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  cursor: pointer; transition: transform 0.12s ease, opacity 0.12s ease;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.08);
}
.cn-backend-pill:hover { transform: translateY(-1px); }
.cn-backend-pill-active { box-shadow: 0 0 0 1px var(--cyan), 0 0 18px rgba(var(--cn-accent-rgb),0.25); }
.cn-backend-pill-name { letter-spacing: 0.1em; text-transform: uppercase; }
.cn-backend-pill-stat { opacity: 0.85; font-weight: 500; }

/* ── Phase 11: Live event log ─────────── */
.cn-log {
  margin-top: 28px;
  background: linear-gradient(180deg, rgba(10,13,22,0.85), rgba(6,8,16,0.92));
  border: 1px solid var(--border);
  border-top: 1px solid rgba(var(--cn-accent-rgb), 0.32);
  border-radius: 5px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.32), 0 0 32px rgba(var(--cn-accent-rgb), 0.04);
  overflow: hidden;
  transition: border-color 240ms ease;
}
.cn-log-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 14px;
  background: rgba(var(--cn-accent-rgb), 0.04);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.cn-log-collapsed .cn-log-head { border-bottom: none; }
.cn-log-head-left, .cn-log-head-right {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.cn-log-toggle {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent; border: 0; cursor: pointer;
  font-family: var(--mono); font-size: 11px; font-weight: 700;
  letter-spacing: 0.16em; color: var(--cyan);
  padding: 0;
}
.cn-log-toggle:focus-visible {
  outline: 1px solid rgba(var(--cn-accent-rgb), 0.6);
  outline-offset: 2px;
  border-radius: 2px;
}
.cn-log-caret {
  display: inline-block; width: 10px; text-align: center;
  color: var(--cyan); transition: transform 0.18s ease;
}
.cn-log-title { color: var(--cyan); }
.cn-log-count { display: flex; gap: 6px; flex-wrap: wrap; }
.cn-log-pill {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  padding: 2px 8px; border-radius: 99px;
  letter-spacing: 0.06em;
}
.cn-log-pill-passed { background: rgba(0, 255, 136, 0.1); color: var(--green); border: 1px solid rgba(0, 255, 136, 0.25); }
.cn-log-pill-failed { background: rgba(255, 51, 102, 0.1); color: var(--red); border: 1px solid rgba(255, 51, 102, 0.25); }
.cn-log-pill-fired  { background: rgba(255, 149, 0, 0.1); color: var(--amber); border: 1px solid rgba(255, 149, 0, 0.25); }

.cn-log-toggle-label {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  letter-spacing: 0.1em; text-transform: uppercase; cursor: pointer;
}
.cn-log-toggle-label input { accent-color: var(--cyan); cursor: pointer; }

.cn-log-body {
  max-height: 360px; overflow-y: auto;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--cn-accent-rgb), 0.35) transparent;
}
.cn-log-body::-webkit-scrollbar { width: 6px; }
.cn-log-body::-webkit-scrollbar-track { background: transparent; }
.cn-log-body::-webkit-scrollbar-thumb {
  background: rgba(var(--cn-accent-rgb), 0.35); border-radius: 3px;
}
.cn-log-body::-webkit-scrollbar-thumb:hover { background: rgba(var(--cn-accent-rgb), 0.55); }

.cn-log-empty {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 24px 14px; text-align: center;
  font-family: var(--mono); font-size: 11px; color: var(--muted);
}
.cn-log-empty-pulse {
  width: 8px; height: 8px; border-radius: 50%;
  background: rgba(var(--cn-accent-rgb), 0.45);
  animation: cnLivePulse 1.6s ease-in-out infinite;
  flex-shrink: 0;
}

.cn-log-new-badge {
  margin-left: 6px;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.04em;
  color: #06090f;
  background: var(--cyan);
  padding: 2px 8px; border-radius: 99px;
  box-shadow: 0 0 12px rgba(var(--cn-accent-rgb), 0.5);
  animation: cnBadgePop 0.2s ease-out;
}
@keyframes cnBadgePop {
  from { transform: scale(0.7); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.cn-log-list { display: flex; flex-direction: column; }
.cn-log-row {
  display: grid;
  grid-template-columns: 22px 70px 60px 1fr auto;
  gap: 12px; align-items: center;
  padding: 5px 14px;
  font-family: var(--mono); font-size: 11px;
  border-bottom: 1px solid rgba(var(--cn-accent-rgb), 0.04);
  transition: background 0.12s ease;
  animation: cnLogIn 0.22s ease-out;
}
.cn-log-row:hover { background: rgba(var(--cn-accent-rgb), 0.05); }
.cn-log-row:last-child { border-bottom: none; }
@keyframes cnLogIn {
  from { opacity: 0; transform: translateY(-3px); }
  to { opacity: 1; transform: translateY(0); }
}

.cn-log-icon { font-size: 13px; font-weight: 700; text-align: center; }
.cn-log-passed .cn-log-icon { color: var(--green); }
.cn-log-failed .cn-log-icon { color: var(--red); }
.cn-log-fired .cn-log-icon { color: var(--amber); }
.cn-log-passed { background: linear-gradient(90deg, rgba(0, 255, 136, 0.04), transparent 60%); }
.cn-log-failed { background: linear-gradient(90deg, rgba(255, 51, 102, 0.05), transparent 60%); }
.cn-log-fired { background: linear-gradient(90deg, rgba(255, 149, 0, 0.04), transparent 60%); }

.cn-log-time { color: var(--muted); font-size: 10px; }
.cn-log-backend { font-size: 8px !important; padding: 1px 6px !important; }
.cn-log-path {
  display: inline-flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cn-log-name {
  background: rgba(255,255,255,0.03);
  padding: 1px 5px; border-radius: 2px;
  color: var(--text-bright); font-size: 10px;
}
.cn-log-arrow { color: var(--muted); }
.cn-log-meta {
  display: inline-flex; gap: 8px; align-items: center; font-size: 10px;
}
.cn-log-http { color: var(--amber); }
.cn-log-latency { color: var(--cyan); font-weight: 600; }
.cn-log-fail { color: var(--red); font-style: italic; }

.cn-empty-block {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding: 40px 16px;
  background: rgba(var(--cn-accent-rgb), 0.03);
  border: 1px dashed rgba(var(--cn-accent-rgb), 0.18);
  border-radius: 5px;
  font-family: var(--mono); font-size: 12px; color: var(--muted);
  letter-spacing: 0.04em;
}

/* ── Footer ────────────────────────────── */
.cn-footer { text-align: center; padding: 28px 0 0; font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.06em; }
.cn-footer code { color: var(--cyan); background: rgba(var(--cn-accent-rgb),0.08); padding: 1px 4px; border-radius: 2px; }

@media (max-width: 720px) {
  .cn-h1 { font-size: 26px; }
  .cn-stats-row { flex-direction: column; }
  .cn-toolbar { flex-direction: column; align-items: flex-start; gap: 8px; }
  /* minmax(0, 1fr): a 1fr column grew to the widest card's content and the path cards ran ~45 px past a phone's edge
     (the camera, 2026-10-13) */
  .cn-cards { grid-template-columns: minmax(0, 1fr); }
  .cn-agents-grid { grid-template-columns: minmax(0, 1fr); }
  .cn-failure-row { grid-template-columns: 1fr; gap: 4px; }
  .cn-log-row { grid-template-columns: 22px 60px 1fr; row-gap: 4px; }
  .cn-log-row .cn-log-meta { grid-column: 1 / -1; padding-left: 28px; }
}

/* Respect prefers-reduced-motion — kill all decorative animations. */
@media (prefers-reduced-motion: reduce) {
  .cn-grid,
  .cn-chip-dot,
  .cn-live-dot-active,
  .cn-log-empty-pulse,
  .cn-spinner,
  .cn-flash,
  .cn-card,
  .cn-section,
  .cn-expanded,
  .cn-log-row,
  .cn-log-new-badge {
    animation: none !important;
    transition: none !important;
  }
}
</style>
