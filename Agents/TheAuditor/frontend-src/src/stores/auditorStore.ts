import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import type { AuditResult, AuditStats, Breach, FrameConfig, Maintenance } from '@/types/auditor'

// §LIVESTATS (2026-09-15): the store keeps no copy of the server's rule for which rows count. Every live row carries the
// server's counts_ok and counts_breach (database.counts_ok / counts_breach, the Python form of the SQL get_stats counts
// with) and get_stats serves ok_audits, so the audit count, the streak, the uptime and the last breach move as the
// server's do. §MTLSHOPS (a): a public-only frame's reading carries null for both, since it counts for nothing in the
// stats. The max deltas round like the server's, to 6 places.
const round6 = (x: number) => Math.round(x * 1e6) / 1e6

export const useAuditorStore = defineStore('auditor', () => {
  const frames = ref<FrameConfig[]>([])
  const latestByFrame = ref<Record<string, AuditResult | null>>({})
  const history = ref<AuditResult[]>([])
  const stats = ref<AuditStats | null>(null)
  const breaches = ref<Breach[]>([])
  const maintenance = ref<Maintenance | null>(null)
  // §VENUESHARES — 13 of the federation's 16 venues are cloud-ops, not frames, so
  // their share registers never rode `latest.extra_data.shares` and the panel could
  // only ever show the 3 frames' listings. This is the rest of the book.
  const venueShares = ref<Record<string, any>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── Tiers (prod | sandbox | legacy) ──────────────────────────────────────
  // ONE app audits every tier: prod is the live EU/ASIA cluster, sandbox the
  // dry-run frames, legacy the retiring registry-a / frame-b / frame-c stack
  // (§LEGACYTIER 2026-09-09). The displayed tier defaults to whatever the
  // subdomain implies (sandbox-auditor.* → sandbox, auditor.* → prod) and is
  // flippable via the header toggle. The list itself comes from the server —
  // never hardcode it, or a new tier is invisible until the bundle is rebuilt.
  function defaultMode(): string {
    if (typeof window !== 'undefined' && window.location.hostname.includes('sandbox')) return 'sandbox'
    return 'prod'
  }
  const mode = ref<string>(defaultMode())
  const availableModes = ref<string[]>(['prod', 'sandbox'])
  // Which tiers carry a TPSA-1 attestation chain (server-derived: ATTEST_MODES).
  // The seal and the badge gate on THIS, not on the literal 'prod' — a tier that
  // signs must show its seal, and one that does not must not promise one.
  const attestModes = ref<string[]>(['prod'])

  // Computed: history partitioned by frame (for charts)
  const historyByFrame = computed(() => {
    const result: Record<string, AuditResult[]> = {}
    for (const row of history.value) {
      const fid = row.frame || 'frame-a'
      if (!result[fid]) result[fid] = []
      result[fid].push(row)
    }
    return result
  })

  async function fetchFrames() {
    try {
      const { data } = await axios.get<FrameConfig[]>('/api/auditor/frames', {
        params: { mode: mode.value },
      })
      frames.value = data
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function fetchLatest() {
    try {
      const { data } = await axios.get<Record<string, AuditResult>>('/api/auditor/latest', {
        params: { mode: mode.value },
      })
      latestByFrame.value = data
    } catch (e: any) {
      if (e.response?.status !== 404) {
        error.value = e.message
      }
    }
  }

  async function fetchHistory(limit = 200) {
    try {
      const { data } = await axios.get<AuditResult[]>('/api/auditor/history', {
        params: { limit, mode: mode.value },
      })
      history.value = data
    } catch (e: any) {
      error.value = e.message
    }
  }

  // Set of frame-ids belonging to the currently-viewed mode. WS streams ALL
  // frames (both modes) over one connection; the dashboard shows one mode, so
  // we drop foreign-mode events at ingestion to keep latest/history/stats scoped.
  function inCurrentMode(fid: string): boolean {
    if (frames.value.length === 0) return true // pre-load: don't drop everything
    return frames.value.some((f) => f.id === fid)
  }

  async function fetchStats() {
    try {
      const { data } = await axios.get<AuditStats>('/api/auditor/stats', {
        params: { mode: mode.value },
      })
      stats.value = data
    } catch (e: any) {
      error.value = e.message
    }
  }

  // One pending stats refetch at a time. A live row or a stats read without the server's counts (an older server: a
  // rollback, or a page left open across a recreate) asks the server once instead of guessing, never once per row.
  let statsRefetch: ReturnType<typeof setTimeout> | null = null
  function refetchStatsSoon() {
    if (statsRefetch) return
    statsRefetch = setTimeout(() => {
      statsRefetch = null
      void fetchStats()
    }, 2000)
  }

  async function fetchBreaches() {
    try {
      const { data } = await axios.get<Breach[]>('/api/auditor/breaches')
      breaches.value = data
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function fetchVenueShares() {
    try {
      const { data } = await axios.get<{ venues: Record<string, any> }>('/api/auditor/venue-shares')
      venueShares.value = data?.venues || {}
    } catch {
      venueShares.value = {}   // endpoint absent on an older auditor — panel just shows frames
    }
  }

  async function fetchMaintenance() {
    try {
      const { data } = await axios.get<Maintenance>('/api/auditor/maintenance')
      maintenance.value = data
    } catch (e: any) {
      // non-fatal — banner just won't render
    }
  }

  function setMaintenance(m: Maintenance) {
    maintenance.value = m
  }

  async function fetchModes() {
    try {
      const { data } = await axios.get<{ modes: string[]; default: string; attest?: string[] }>('/api/auditor/modes')
      if (Array.isArray(data.attest)) attestModes.value = data.attest
      if (Array.isArray(data.modes) && data.modes.length) {
        availableModes.value = data.modes
        // Honour the subdomain default, but fall back to the server default if
        // the subdomain-implied mode has no frames configured.
        if (!data.modes.includes(mode.value)) mode.value = data.default
      }
    } catch {
      // non-fatal — keep the subdomain default + the static fallback list
    }
  }

  async function setMode(m: string) {
    if (m === mode.value) return
    mode.value = m
    // Re-fetch every mode-scoped view so the whole dashboard (frames, latest,
    // trend/audit-log history, and the headline stat panel) flips environments
    // together — no stale prod numbers lingering under a sandbox view.
    latestByFrame.value = {} // drop the other env's rows so panels don't blend
    await Promise.all([fetchFrames(), fetchLatest(), fetchHistory(), fetchStats()])
  }

  async function fetchAll() {
    loading.value = true
    error.value = null
    await fetchModes()
    await Promise.all([
      fetchFrames(),
      fetchLatest(),
      fetchHistory(),
      fetchStats(),
      fetchBreaches(),
      fetchMaintenance(),
      fetchVenueShares(),
    ])
    loading.value = false
  }

  function handleWsAudit(data: AuditResult, frame: string) {
    const fid = frame || data.frame || 'frame-a'
    if (!inCurrentMode(fid)) return // ignore the other environment's stream
    data.frame = fid
    latestByFrame.value[fid] = data

    // Prepend to interleaved history, cap at 400 (200 per frame)
    history.value.unshift(data)
    if (history.value.length > 400) {
      history.value = history.value.slice(0, 400)
    }

    // Update combined stats locally. §LIVESTATS (2026-09-15): three live defects on auditor.theprotocol.cloud, all older
    // than (a). The uptime was recounted over the rows this page happens to hold, so the header switched from the server's
    // all-rows figure to a recent-window figure at the first live row; the max deltas never moved after page load; and the
    // streak skipped a maintenance row the server counts. Each row now moves the stats the way get_stats counts it: the
    // count, the streak and ok_audits by the row's counts_ok, the last breach by counts_breach (an ERROR row set it here
    // while the server never did), the uptime as ok_audits over the count, the max deltas by each row's absolute deltas,
    // and monitoring-since by the first row when the server had none. §MTLSHOPS (a): a public-only frame's reading
    // carries counts_ok null, the server's word that it counts for nothing here, and moves none of the stats.
    const s = stats.value
    if (s && data.counts_ok !== null) {
      if (typeof data.counts_ok !== 'boolean' || typeof s.ok_audits !== 'number') {
        refetchStatsSoon()
        return
      }
      s.total_audits++
      if (data.counts_ok) {
        s.ok_audits++
        s.consecutive_ok++
      } else {
        s.consecutive_ok = 0
      }
      if (data.counts_breach) s.last_breach = data.timestamp
      s.uptime_pct = Math.round((s.ok_audits / s.total_audits) * 10000) / 100
      if (typeof data.delta === 'number') s.max_delta = round6(Math.max(s.max_delta ?? 0, Math.abs(data.delta)))
      if (typeof data.atomic_delta === 'number') {
        s.max_atomic_delta = round6(Math.max(s.max_atomic_delta ?? 0, Math.abs(data.atomic_delta)))
      }
      if (!s.oldest_audit) s.oldest_audit = data.timestamp
    }
  }

  function handleWsLatestBatch(latestMap: Record<string, AuditResult>) {
    for (const [fid, result] of Object.entries(latestMap)) {
      if (result && inCurrentMode(fid)) {
        result.frame = fid
        latestByFrame.value[fid] = result
      }
    }
  }

  return {
    frames,
    latestByFrame,
    history,
    historyByFrame,
    stats,
    breaches,
    maintenance,
    venueShares,
    loading,
    error,
    mode,
    availableModes,
    attestModes,
    fetchModes,
    setMode,
    fetchFrames,
    fetchLatest,
    fetchHistory,
    fetchStats,
    fetchBreaches,
    fetchMaintenance,
    setMaintenance,
    fetchVenueShares,
    fetchAll,
    handleWsAudit,
    handleWsLatestBatch,
  }
})
