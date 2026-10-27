/**
 * stores/forensics.ts — Ledger Forensics console state (2026-06-19).
 *
 * Setup-store mirroring the consul.ts conventions (loading flags, error,
 * lastRefreshedAt, pendingActions, $reset). Pure read/aggregation over
 * existing admin endpoints; the only mutation is the f037 policy PUT.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  forensicsApi,
  type AuditorLatest,
  type EmissionPolicy,
  type EmissionPolicyUpdate,
  type ExchangeInvariant,
  type ExchangeOverview,
  type FeeCollectorInfo,
  type GatewayKeeperStatus,
  type ForensicSearchParams,
  type ForensicSearchResult,
  type InventoryResult,
  type OpenFinding,
} from '@/services/api/forensics'
import {
  LOCAL_FRAME,
  type EventStoreEvent,
  type FrameId,
} from '@/services/api/eventStoreAdmin'
import { useAdminFrames } from '@/composables/useAdminFrames'
import { fetchAggregateChain, type ChainWindow } from '@/services/api/eventChain'

export const useForensicsStore = defineStore('forensics', () => {
  // §FEDEVENTS: frame-routed reads — local frame via this registry (frame=local),
  // foreign frames via THEIR OWN registry through the peer proxy + console
  // session. The direct EVENT_STORE_{X}_URL env path silently 401'd cross-frame
  // (wrong per-frame keys), which is why foreign searches "didn't fully work".
  const { frameGet } = useAdminFrames()

  // ── State ──────────────────────────────────────────────────────────────
  const policies = ref<EmissionPolicy[]>([])
  const exchangeInvariant = ref<ExchangeInvariant | null>(null)
  const exchangeOverview = ref<ExchangeOverview | null>(null)
  const auditor = ref<AuditorLatest>({})
  const feeCollector = ref<FeeCollectorInfo | null>(null)
  const gatewayKeeper = ref<GatewayKeeperStatus | null>(null)

  // Trace (event-level) state — aggregate traces are WINDOWED (§FEDEVENTS):
  // ~30d hops over the indexed forensics search instead of the unbounded
  // /events/aggregate rail (which dies on million-event production aggregates).
  const traceAnchor = ref<string>('')
  const traceEvents = ref<EventStoreEvent[]>([])
  const traceWindow = ref<ChainWindow | null>(null)
  const traceWindowEnd = ref<Date | null>(null)
  const traceTruncated = ref(false)
  const traceWalked = ref(0)
  const traceMode = ref<'txid' | 'aggregate'>('txid')

  // Query / Inventory / Findings (backend forensics router)
  const searchResult = ref<ForensicSearchResult | null>(null)
  const searching = ref(false)
  const inventory = ref<InventoryResult | null>(null)
  const loadingInventory = ref(false)
  const openFindings = ref<OpenFinding[]>([])
  const findingsInactive = ref(false)
  /** §FESUITE V0577: the findings read failed (the inbox said "No open findings." with a check, or "Scanner inactive") */
  const findingsFailed = ref(false)
  let findingsSeq = 0
  let findingsStatus: 'open' | 'acked' | undefined
  const loadingFindings = ref(false)

  const loadingPolicies = ref(false)
  /** §FESUITE V0577: what the three tabs' reads did. A failed trace said "No events for <anchor>", a failed policy read
   *  "No policies match." under chips counting 0 (⚠ Violations 0), and a failed search put back "Pick a window +
   *  filters, then Search." with nothing said; each tab says its read failed now. */
  const policiesRead = ref(false)
  const policiesFailed = ref(false)
  const traceFailed = ref(false)
  const searchFailed = ref(false)
  const loadingStuck = ref(false)
  const loadingTrace = ref(false)
  const error = ref<string | null>(null)
  const lastRefreshedAt = ref<string | null>(null)
  // §FESUITE (the failing-reads census, V0569 at sbx-beta, 2026-10-04): the sources the last stuck-funds scan could not
  // read (a 404 is an answer: "not on this frame"). With every read failed the board said "No stuck-funds signals
  // detected." while the frame had signals: an all-clear needs the sources its findings read.
  const stuckUnread = ref<string[]>([])
  const pendingActions = ref<Set<string>>(new Set())
  const lastActionResult = ref<string | null>(null)

  // ── Computed ───────────────────────────────────────────────────────────
  /** Auditor frames keyed by id, ordered, sandbox/errored frames last. */
  const auditorFrames = computed(() => {
    const entries = Object.entries(auditor.value || {})
    return entries
      .map(([key, frame]) => ({ key, ...frame }))
      .sort((a, b) => {
        const aErr = a.status === 'ERROR' || /sbx|sandbox/i.test(a.key)
        const bErr = b.status === 'ERROR' || /sbx|sandbox/i.test(b.key)
        if (aErr !== bErr) return aErr ? 1 : -1
        return a.key.localeCompare(b.key)
      })
  })

  /** Production frames only (drop sandbox + name-resolution errors). */
  const prodAuditorFrames = computed(() =>
    auditorFrames.value.filter(
      f => !/sbx|sandbox/i.test(f.key) && f.extra_data?.live_error == null,
    ),
  )

  // ── Helpers ──────────────────────────────────────────────────────────────
  function _setError(e: unknown, fallback = 'Operation failed') {
    const anyE = e as any
    error.value = anyE?.response?.data?.detail ?? anyE?.message ?? fallback
  }

  // ── Actions ────────────────────────────────────────────────────────────
  async function loadPolicies() {
    try {
      loadingPolicies.value = true
      error.value = null
      policies.value = await forensicsApi.getPolicies()
      policiesRead.value = true
      policiesFailed.value = false
    } catch (e) {
      policiesFailed.value = true
      _setError(e, 'Failed to load emission policies')
    } finally {
      loadingPolicies.value = false
    }
  }

  async function updatePolicy(eventType: string, body: EmissionPolicyUpdate): Promise<boolean> {
    const key = `policy:${eventType}`
    if (pendingActions.value.has(key)) return false
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      const updated = await forensicsApi.updatePolicy(eventType, body)
      const idx = policies.value.findIndex(p => p.event_type === eventType)
      if (idx >= 0) {
        policies.value[idx] = { ...policies.value[idx], ...body, ...(updated || {}) }
      }
      lastActionResult.value = `Updated emission policy for ${eventType}`
      return true
    } catch (e) {
      _setError(e, `Failed to update policy for ${eventType}`)
      return false
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  /** The "what's stuck right now" board — parallel load of the live invariants. */
  async function loadStuckOverview() {
    try {
      loadingStuck.value = true
      error.value = null
      const [inv, ov, aud, fee, gk] = await Promise.allSettled([
        forensicsApi.exchangeInvariant(),
        forensicsApi.exchangeOverview(),
        forensicsApi.auditorLatest(),
        forensicsApi.feeCollector('7d'),
        forensicsApi.gatewayKeeper(),
      ])
      exchangeInvariant.value = inv.status === 'fulfilled' ? inv.value : null
      exchangeOverview.value = ov.status === 'fulfilled' ? ov.value : null
      auditor.value = aud.status === 'fulfilled' ? aud.value : {}
      feeCollector.value = fee.status === 'fulfilled' ? fee.value : null
      gatewayKeeper.value = gk.status === 'fulfilled' ? gk.value : null
      const unread = (r: PromiseSettledResult<unknown>) => r.status === 'rejected' && (r.reason as any)?.response?.status !== 404
      const sources: Array<[string, PromiseSettledResult<unknown>]> = [
        ['the AGORA invariant', inv], ['the AGORA overview', ov], ['the auditor', aud],
        ['the fee collector', fee], ['the gateway keeper', gk],
      ]
      stuckUnread.value = sources.filter(([, r]) => unread(r)).map(([n]) => n)
      lastRefreshedAt.value = new Date().toISOString()
      if (inv.status === 'rejected' && ov.status === 'rejected' && aud.status === 'rejected') {
        _setError(inv.reason, 'Failed to load stuck-funds overview')
      }
    } finally {
      loadingStuck.value = false
    }
  }

  /** Event-level trace: an aggregate's chain (DID / ledger key), fetched in
   *  bounded ~30d windows over the indexed forensics search (§FEDEVENTS — the
   *  old unbounded byAggregate rail dies on million-event aggregates). The
   *  first call auto-walks back through empty windows to the latest activity. */
  async function loadTrace(anchor: string, frame: FrameId = LOCAL_FRAME, opts?: { keepWindow?: boolean }) {
    const a = anchor.trim()
    traceAnchor.value = a
    traceMode.value = 'aggregate'
    traceEvents.value = []
    traceFailed.value = false
    if (!opts?.keepWindow) traceWindowEnd.value = null
    if (!a) return
    try {
      loadingTrace.value = true
      error.value = null
      const r = await fetchAggregateChain(
        (params) => frameGet<any>(frame, 'admin/forensics/search', params),
        a,
        { windowEnd: traceWindowEnd.value ?? undefined, autoWalk: traceWindowEnd.value == null },
      )
      // Page error with rows fetched = partial window: keep the rows, surface
      // the error as a warning banner. Zero-row error = real failure.
      if (r.error && !r.events.length) throw new Error(r.error)
      traceEvents.value = r.events
      traceWindow.value = r.window
      traceTruncated.value = r.truncated
      traceWalked.value = r.walkedBack
      if (r.walkedBack > 0) traceWindowEnd.value = new Date(r.window.end)
      if (r.error) error.value = `Window partially loaded: ${r.error}`
    } catch (e) {
      traceFailed.value = true
      _setError(e, `Failed to trace ${a}`)
    } finally {
      loadingTrace.value = false
    }
  }

  /** Step the aggregate-trace window through history (older/newer/latest). */
  async function traceStep(direction: 'older' | 'newer' | 'latest', frame: FrameId = LOCAL_FRAME) {
    if (traceMode.value !== 'aggregate' || !traceAnchor.value) return
    if (direction === 'latest' || !traceWindow.value) {
      traceWindowEnd.value = null
    } else if (direction === 'older') {
      traceWindowEnd.value = new Date(traceWindow.value.start)
    } else {
      const next = new Date(traceWindow.value.end).getTime() + 30 * 86_400_000
      traceWindowEnd.value = next >= Date.now() ? null : new Date(next)
    }
    await loadTrace(traceAnchor.value, frame, { keepWindow: true })
  }

  /** txid trace — the real cross-leg timeline, frame-routed (§FEDEVENTS). */
  async function loadTraceTxid(txid: string, frame: FrameId = LOCAL_FRAME) {
    const a = txid.trim()
    traceAnchor.value = a
    traceMode.value = 'txid'
    traceEvents.value = []
    traceFailed.value = false
    traceWindow.value = null
    traceTruncated.value = false
    traceWalked.value = 0
    if (!a) return
    try {
      loadingTrace.value = true
      error.value = null
      const r = await frameGet<ForensicSearchResult>(
        frame, `admin/forensics/trace/${encodeURIComponent(a)}`,
      )
      if (r?.error) throw new Error(r.error)
      traceEvents.value = r.events || []
    } catch (e) {
      traceFailed.value = true
      _setError(e, `Failed to trace txid ${a}`)
    } finally {
      loadingTrace.value = false
    }
  }

  async function runSearch(params: ForensicSearchParams) {
    try {
      searching.value = true
      error.value = null
      searchFailed.value = false
      const { frame, ...rest } = params
      searchResult.value = await frameGet<ForensicSearchResult>(
        frame || LOCAL_FRAME, 'admin/forensics/search', rest,
      )
    } catch (e) {
      searchFailed.value = true
      _setError(e, 'Search failed')
      searchResult.value = null
    } finally {
      searching.value = false
    }
  }

  async function loadInventory() {
    try {
      loadingInventory.value = true
      inventory.value = await forensicsApi.inventory()
    } catch (e) {
      _setError(e, 'Failed to load inventory')
    } finally {
      loadingInventory.value = false
    }
  }

  async function loadFindings(status?: 'open' | 'acked') {
    // only the newest read lands: a filter switched while one is in flight listed the other filter's findings under it
    const mine = ++findingsSeq
    findingsStatus = status
    try {
      loadingFindings.value = true
      const r = await forensicsApi.findings(status)
      if (mine !== findingsSeq) return
      openFindings.value = r.findings || []
      findingsInactive.value = !!r.scanner_inactive
      findingsFailed.value = false
    } catch (e) {
      if (mine !== findingsSeq) return
      findingsFailed.value = true
      _setError(e, 'Failed to load findings')
    } finally {
      if (mine === findingsSeq) loadingFindings.value = false
    }
  }

  async function ackFinding(key: string): Promise<boolean> {
    const ok = await forensicsApi.ackFinding(key)
    // read again under the filter on screen (it read every finding, so an acked one stayed listed under Open)
    if (ok) await loadFindings(findingsStatus)
    return ok
  }

  function $reset() {
    policies.value = []
    policiesRead.value = false
    policiesFailed.value = false
    traceFailed.value = false
    searchFailed.value = false
    searchResult.value = null
    inventory.value = null
    openFindings.value = []
    findingsInactive.value = false
    findingsFailed.value = false
    exchangeInvariant.value = null
    exchangeOverview.value = null
    auditor.value = {}
    feeCollector.value = null
    gatewayKeeper.value = null
    traceAnchor.value = ''
    traceEvents.value = []
    traceWindow.value = null
    traceWindowEnd.value = null
    traceTruncated.value = false
    traceWalked.value = 0
    traceMode.value = 'txid'
    loadingPolicies.value = false
    loadingStuck.value = false
    loadingTrace.value = false
    error.value = null
    lastRefreshedAt.value = null
    stuckUnread.value = []
    pendingActions.value = new Set()
    lastActionResult.value = null
  }

  return {
    // state
    policies,
    stuckUnread,
    exchangeInvariant,
    exchangeOverview,
    auditor,
    feeCollector,
    gatewayKeeper,
    traceAnchor,
    traceEvents,
    traceWindow,
    traceWindowEnd,
    traceTruncated,
    traceWalked,
    traceMode,
    searchResult,
    searching,
    inventory,
    loadingInventory,
    openFindings,
    findingsInactive,
    findingsFailed,
    loadingFindings,
    loadingPolicies,
    loadingStuck,
    loadingTrace,
    policiesRead,
    policiesFailed,
    traceFailed,
    searchFailed,
    error,
    lastRefreshedAt,
    pendingActions,
    lastActionResult,
    // computed
    auditorFrames,
    prodAuditorFrames,
    // actions
    loadPolicies,
    updatePolicy,
    loadStuckOverview,
    loadTrace,
    traceStep,
    loadTraceTxid,
    runSearch,
    loadInventory,
    loadFindings,
    ackFinding,
    $reset,
  }
})
