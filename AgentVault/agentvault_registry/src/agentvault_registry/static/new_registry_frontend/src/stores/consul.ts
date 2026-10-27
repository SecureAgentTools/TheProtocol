import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  consulApi,
  type ComplianceEvent,
  type ComplianceOverview,
  type DriftEvent,
  type DriftScanResult,
  type EnforcementMode,
  type EnforcementModeState,
  type PeerComplianceRow,
  type PeerDetail,
  type PollNowResult,
  type PreviewQuarantineResponse,
  type TrustBundleMatrix,
} from '@/services/api/consulApi'

export const useConsulStore = defineStore('consul', () => {
  // ── State ──────────────────────────────────────────────────────────────
  const modeState = ref<EnforcementModeState | null>(null)
  const overview = ref<ComplianceOverview | null>(null)
  const peerDetails = ref<Record<string, PeerDetail>>({}) // keyed by operator_id
  const events = ref<ComplianceEvent[]>([])
  const preview = ref<PreviewQuarantineResponse | null>(null)
  const drifts = ref<DriftEvent[]>([])
  const driftCountsByType = ref<Record<string, number>>({})
  const lastDriftScan = ref<DriftScanResult | null>(null)
  const trustMatrix = ref<TrustBundleMatrix | null>(null)

  const loading = ref(false)
  const loadingDetail = ref<Record<string, boolean>>({})
  const loadingEvents = ref(false)
  const loadingPreview = ref(false)
  const loadingDrifts = ref(false)
  const loadingTrustMatrix = ref(false)
  const runningDriftScan = ref(false)
  const error = ref<string | null>(null)
  // §MCPTEST30 (V0561): a store the server could not read is said where its list would be, never shown as an empty list
  const eventsError = ref<string | null>(null)
  const eventsUnreadable = ref<Array<{ event_type: string; reason: string }>>([])
  const driftsError = ref<string | null>(null)
  const lastRefreshedAt = ref<string | null>(null)
  const pendingActions = ref<Set<string>>(new Set())
  const lastActionResult = ref<string | null>(null)

  // ── Computed ───────────────────────────────────────────────────────────
  const mode = computed<EnforcementMode>(() => modeState.value?.mode ?? 'off')
  const effectiveEnforcement = computed(
    () => modeState.value?.effective_enforcement ?? false,
  )
  const peers = computed<PeerComplianceRow[]>(() => overview.value?.peers ?? [])

  const peersQuarantinedWithGrace = computed(() =>
    peers.value.filter(
      p =>
        p.federation_status === 'quarantined' ||
        p.federation_status === 'soft_quarantined',
    ),
  )

  // ── Actions ────────────────────────────────────────────────────────────
  function _setError(e: unknown, fallback = 'Operation failed') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const anyE = e as any
    const detail = anyE?.response?.data?.detail ?? anyE?.message
    // §MCPTEST30 (V0561): say WHICH read failed. Five loaders share this banner, and a bare "Network Error" named none.
    error.value = detail ? `${fallback}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : fallback
  }

  async function loadMode() {
    try {
      modeState.value = await consulApi.getMode()
    } catch (e) {
      _setError(e, 'Failed to load enforcement mode')
    }
  }

  async function loadOverview() {
    try {
      loading.value = true
      error.value = null
      overview.value = await consulApi.getOverview()
      lastRefreshedAt.value = new Date().toISOString()
    } catch (e) {
      _setError(e, 'Failed to load CONSUL overview')
    } finally {
      loading.value = false
    }
  }

  async function loadPeerDetailByOperator(operatorId: string, force = false) {
    if (!force && peerDetails.value[operatorId]) return peerDetails.value[operatorId]
    try {
      loadingDetail.value = { ...loadingDetail.value, [operatorId]: true }
      const detail = await consulApi.getPeerDetailByOperator(operatorId)
      peerDetails.value = { ...peerDetails.value, [operatorId]: detail }
      return detail
    } catch (e) {
      _setError(e, `Failed to load ${operatorId} detail`)
      return null
    } finally {
      const next = { ...loadingDetail.value }
      delete next[operatorId]
      loadingDetail.value = next
    }
  }

  async function loadEvents(limit = 50) {
    try {
      loadingEvents.value = true
      const resp = await consulApi.getEvents(limit)
      events.value = resp.events
      eventsError.value = resp.error ?? null
      eventsUnreadable.value = resp.unreadable ?? []
    } catch (e) {
      _setError(e, 'Failed to load compliance events')
    } finally {
      loadingEvents.value = false
    }
  }

  async function loadPreview() {
    try {
      loadingPreview.value = true
      preview.value = await consulApi.previewQuarantine()
    } catch (e) {
      _setError(e, 'Failed to run preview simulator')
    } finally {
      loadingPreview.value = false
    }
  }

  async function setMode(newMode: EnforcementMode, reason: string) {
    const key = `setMode:${newMode}`
    if (pendingActions.value.has(key)) return false
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      modeState.value = await consulApi.setMode(newMode, reason)
      lastActionResult.value = `Mode set to ${newMode}`
      return true
    } catch (e) {
      _setError(e, 'Failed to set mode')
      return false
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  async function pollPeerNow(peerId: number, dryRunOnly = true, operatorId?: string): Promise<PollNowResult | null> {
    const key = `poll:${peerId}:${dryRunOnly}`
    if (pendingActions.value.has(key)) return null
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      const result = await consulApi.pollPeerNow(peerId, dryRunOnly)
      lastActionResult.value = `Polled peer ${peerId}: ${result.status}`
      // Refresh overview + detail after action
      loadOverview().catch(() => {})
      if (operatorId) loadPeerDetailByOperator(operatorId, true).catch(() => {})
      return result
    } catch (e) {
      _setError(e, `Failed to poll peer ${peerId}`)
      return null
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  async function manualQuarantine(
    peerId: number,
    payload: { reason: string; grace_hours: number },
    operatorId?: string,
  ) {
    const key = `quarantine:${peerId}`
    if (pendingActions.value.has(key)) return false
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      await consulApi.manualQuarantine(peerId, payload)
      lastActionResult.value = `Quarantined peer ${peerId}`
      loadOverview().catch(() => {})
      if (operatorId) loadPeerDetailByOperator(operatorId, true).catch(() => {})
      return true
    } catch (e) {
      _setError(e, `Failed to quarantine peer ${peerId}`)
      return false
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  async function liftQuarantine(peerId: number, newHash: string, operatorId?: string) {
    const key = `lift:${peerId}`
    if (pendingActions.value.has(key)) return false
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      await consulApi.liftQuarantine(peerId, { new_policy_hash: newHash })
      lastActionResult.value = `Lifted quarantine for peer ${peerId}`
      loadOverview().catch(() => {})
      if (operatorId) loadPeerDetailByOperator(operatorId, true).catch(() => {})
      return true
    } catch (e) {
      _setError(e, `Failed to lift quarantine for peer ${peerId}`)
      return false
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  /** §MCPTEST30 (V0561): accept the peer's CURRENT policy as its baseline. Returns the server's word ('accepted' or
   *  'unchanged'), or null when it refused (the banner says why: a hash that moved since it was reviewed is a 409). */
  async function acceptBaseline(peerId: number, expectedHash: string, reason: string, operatorId?: string) {
    const key = `accept:${peerId}`
    if (pendingActions.value.has(key)) return null
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      const r = await consulApi.acceptBaseline(peerId, { expected_hash: expectedHash, reason })
      lastActionResult.value = r.status === 'unchanged'
        ? `Peer ${peerId} already has this baseline`
        : (r.ledger_recorded === false
          ? `Baseline accepted for peer ${peerId}, but the ledger did not record it`
          : `Baseline accepted for peer ${peerId}`)
      loadOverview().catch(() => {})
      loadEvents(50).catch(() => {})
      if (operatorId) loadPeerDetailByOperator(operatorId, true).catch(() => {})
      return r.status
    } catch (e) {
      _setError(e, `Failed to accept the baseline of peer ${peerId}`)
      return null
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  async function blacklist(peerId: number, reason: string, operatorId?: string) {
    const key = `blacklist:${peerId}`
    if (pendingActions.value.has(key)) return false
    try {
      pendingActions.value = new Set([...pendingActions.value, key])
      await consulApi.blacklist(peerId, { reason })
      lastActionResult.value = `BLACKLISTED peer ${peerId}`
      loadOverview().catch(() => {})
      if (operatorId) loadPeerDetailByOperator(operatorId, true).catch(() => {})
      return true
    } catch (e) {
      _setError(e, `Failed to blacklist peer ${peerId}`)
      return false
    } finally {
      const next = new Set(pendingActions.value)
      next.delete(key)
      pendingActions.value = next
    }
  }

  async function loadDrifts(limit = 25, driftType?: string) {
    try {
      loadingDrifts.value = true
      const resp = await consulApi.getDrifts(limit, driftType)
      drifts.value = resp.drifts
      driftCountsByType.value = resp.by_type || {}
      driftsError.value = resp.error ?? null
    } catch (e) {
      _setError(e, 'Failed to load federation drifts')
      // §FESUITE (2026-10-04): the drift panel draws "No drift events recorded." unless driftsError says the read
      // failed; the shared banner alone left the panel claiming none
      driftsError.value = error.value
    } finally {
      loadingDrifts.value = false
    }
  }

  // Cross-frame trust-bundle drift: does each op's federation gateway trust all
  // 3 frame SPIRE CAs? (federation_trust_drift_scan.sh port.)
  async function loadTrustMatrix() {
    try {
      loadingTrustMatrix.value = true
      trustMatrix.value = await consulApi.getTrustBundleMatrix()
    } catch (e) {
      _setError(e, 'Failed to load cross-frame trust-bundle matrix')
    } finally {
      loadingTrustMatrix.value = false
    }
  }

  async function runDriftScan() {
    if (runningDriftScan.value) return null
    try {
      runningDriftScan.value = true
      const result = await consulApi.runDriftScan()
      lastDriftScan.value = result
      lastActionResult.value =
        `Drift scan: ${result.total_drifts} drift(s) detected. ` +
        `Per-day idempotency means already-emitted drifts are silent no-ops.`
      // Refresh the panel so newly-emitted drifts appear; existing-day drifts
      // stay deduped by EventStore unique constraint on idempotency_key.
      await loadDrifts()
      return result
    } catch (e) {
      _setError(e, 'Failed to run drift scan')
      return null
    } finally {
      runningDriftScan.value = false
    }
  }

  // 2026-04-28: manual federation_sync trigger — bypasses the 300s background
  // cycle so operators can verify peer reachability + agent-card propagation
  // immediately after a peer-config change. Refreshes overview after completion.
  const runningFederationSync = ref(false)
  async function runFederationSync() {
    if (runningFederationSync.value) return null
    try {
      runningFederationSync.value = true
      const result = await consulApi.triggerFederationSync()
      lastActionResult.value =
        `Federation sync triggered: ${result.synced_peers}/${result.total_peers} peers synced.` +
        (result.cascade_sent > 0 ? ` Cascade sent to ${result.cascade_sent} peers.` : '')
      // Pull fresh peer health into the overview pane
      await loadOverview()
      await loadDrifts()
      return result
    } catch (e) {
      _setError(e, 'Failed to trigger federation sync')
      return null
    } finally {
      runningFederationSync.value = false
    }
  }

  async function refreshAll() {
    await Promise.all([
      loadMode(),
      loadOverview(),
      loadEvents(50),
      loadDrifts(25),
      loadTrustMatrix(),
    ])
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout.
  function $reset() {
    modeState.value = null
    overview.value = null
    peerDetails.value = {}
    events.value = []
    preview.value = null
    drifts.value = []
    driftCountsByType.value = {}
    lastDriftScan.value = null
    trustMatrix.value = null
    loading.value = false
    loadingDetail.value = {}
    loadingEvents.value = false
    loadingPreview.value = false
    loadingDrifts.value = false
    loadingTrustMatrix.value = false
    runningDriftScan.value = false
    error.value = null
    eventsError.value = null
    eventsUnreadable.value = []
    driftsError.value = null
  }

  return {
    // state
    modeState,
    overview,
    peerDetails,
    events,
    preview,
    drifts,
    driftCountsByType,
    lastDriftScan,
    trustMatrix,
    loading,
    loadingDetail,
    $reset,
    loadingEvents,
    loadingPreview,
    loadingDrifts,
    loadingTrustMatrix,
    runningDriftScan,
    error,
    eventsError,
    eventsUnreadable,
    driftsError,
    lastRefreshedAt,
    pendingActions,
    lastActionResult,
    // computed
    mode,
    effectiveEnforcement,
    peers,
    peersQuarantinedWithGrace,
    // actions
    loadMode,
    loadOverview,
    loadPeerDetailByOperator,
    loadEvents,
    loadPreview,
    loadDrifts,
    loadTrustMatrix,
    runDriftScan,
    runningFederationSync,
    runFederationSync,
    setMode,
    pollPeerNow,
    manualQuarantine,
    liftQuarantine,
    acceptBaseline,
    blacklist,
    refreshAll,
  }
})
