<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import Icon from '@/components/Icon.vue'
/**
 * FrameManagement.vue — sovereign frame federation admin (WS3.5, 2026-04-21).
 *
 * Mirrors /ui#/operator-management pattern: stats row + drift banner + per-section
 * tables + lifecycle modal. Scope is focused on frames (peer_type='frame') — for
 * federation topology across all tiers see /ui#/federation.
 *
 * Admin actions:
 *   - Approve / Reject pending invitations (WS3 handshake)
 *   - Resync EventStore data planes (SF-4 cross_frame_peers + SF-5 federation_operators)
 *   - Revoke federation (destructive — removes SPIRE bundle + suspends SF-4/5)
 *
 * Data sources:
 *   GET  /admin/federation/frame-invitations                — pending + historical
 *   GET  /admin/federation/topology-overview                — filter peer_type=frame
 *   GET  /admin/federation/frames/spire-status              — live SPIRE bundle list
 *   GET  /admin/eventstore/cross-frame-peers                — SF-4 state
 *   GET  /admin/eventstore/federation-operators             — SF-5 state
 *   POST /admin/federation/frame-invitations/{id}/approve|reject
 *   POST /admin/federation/frames/{id}/revoke|resync-eventstore
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import NotificationSystem from '@/components/common/NotificationSystem.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { frameRequestService, type FrameRequestAdminRead } from '@/services/api/frameRequests'
import { provisioningPrefill, requestTags } from '@/services/frameRequestForm'
import { usePermissions } from '@/composables/usePermissions'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import {
  frameRunnerService,
  type FrameSpec,
  type JobState,
  type PlanResult,
  type ProgressEvent,
  type RevealedCredential,
  type RunnerFrame,
  type RunnerInfo,
  type RunnerJob,
} from '@/services/api/frameRunner'
import { elapsedSeconds, foldProgress, formatElapsed, frameRecordSettled, publishesStandupSteps, specKey } from '@/services/frameRunnerSteps'

// §HELLOFRAME: Approve opens the frame kit, so it exists only where the kit does (FRAME_KIT_ENABLED; the registry refuses it too)
const { frameKitEnabled } = useRegistryConfig()
const { t, tp } = useI18n()

// ─── Types ──────────────────────────────────────────────────────────

interface FrameInvitation {
  id: string
  initiator_trust_domain: string
  initiator_bundle_endpoint_url: string
  initiator_federation_endpoint_url: string
  initiator_event_store_url?: string | null
  initiator_name: string
  initiator_contact_email: string
  initiator_description?: string | null
  initiator_ip?: string | null
  status: string
  reviewed_by?: number | null
  reviewed_at?: string | null
  review_notes?: string | null
  rejection_reason?: string | null
  completed_at?: string | null
  peer_registry_id?: number | null
  spire_bundle_imported_at?: string | null
  revoked_at?: string | null
  revoked_reason?: string | null
  created_at: string
  updated_at: string
}

interface FramePeer {
  id: number
  name: string
  base_url: string
  status: string
  peer_type: string
  trust_domain: string | null
  spiffe_bundle_endpoint_url?: string | null
  last_seen_in_topology_at?: string | null
  bfs_reachable?: boolean
  registered_at: string | null
  approved_at: string | null
  drift_flags?: string[]
  has_drift?: boolean
  health_check_failure_count?: number
}

interface CrossFramePeerRow {
  frame_id: string
  url: string
  status: string
  last_timestamp?: string | null
  added_by?: string | null
  added_at: string
  updated_at: string
}

interface FederationOperatorRow {
  id: string
  operator_name: string
  spiffe_id?: string | null
  status: string
  bayesian_discount: number
  event_count: number
  last_event_at?: string | null
  created_at?: string | null
}

interface SpireStatus {
  spire_trust_domains: string[]
  spire_error: string | null
  in_both: string[]
  in_spire_only: string[]
  in_db_only: string[]
  local_trust_domain: string
}

// ─── State ──────────────────────────────────────────────────────────

const authStore = useAuthStore()
// §PROVSHOW (2026-09-15): this page's refusals and confirmations render in its own notice stack, teleported to <body>
// above the page's modals. They went through the ui store's notice rail, whose component App.vue never registers, so
// every one was dropped: a refused plan showed nothing. Registering that rail app-wide is a separate decision: it
// would switch on 600+ dormant call sites at once, among them a toast for every failed request and server notice
// types the component cannot render.
const pageNotices = ref<InstanceType<typeof NotificationSystem>>()
const notices = {
  success: (title: string, message?: string) => pageNotices.value?.success(title, message),
  // A refusal carries the runner's own sentence, which can be long: it stays twice as long as a confirmation.
  error: (title: string, message?: string) => pageNotices.value?.error(title, message, { duration: 10000 }),
}

const loading = ref(false)
const invitations = ref<FrameInvitation[]>([])
const framePeers = ref<FramePeer[]>([])
const crossFramePeers = ref<CrossFramePeerRow[]>([])
const federationOperators = ref<FederationOperatorRow[]>([])
const spireStatus = ref<SpireStatus | null>(null)

// FM2 (audit 2026-05-07): per-section error refs. Previously load failures
// only fired toasts and left the section silently empty — users had no way to
// retry without reloading the page. Each ref carries the last load error and
// drives an inline retry banner under each section header.
const invitationsError = ref<string | null>(null)
const framePeersError = ref<string | null>(null)
/** §FESUITE (the loading sweep): the frame table says "no frames" only after its own read came back */
const framePeersRead = ref(false)
/** §FESUITE (the loading sweep): the stats count frames and invitations only once each list answered; a failed
 *  refresh keeps the list (and these) as shown, so they are set by a success and never cleared. */
const framePeersOk = ref(false)
const invitationsOk = ref(false)
const crossFrameError = ref<string | null>(null)
const fedOpError = ref<string | null>(null)
const spireError = ref<string | null>(null)

const invitationStatusFilter = ref<'pending' | 'all' | 'rejected' | 'completed'>('pending')
const frameStatusFilter = ref<'all' | 'ACTIVE' | 'INACTIVE'>('all')

// Modal state
const showApproveModal = ref(false)
const showRejectModal = ref(false)
const showRevokeModal = ref(false)
const showLifecycleModal = ref(false)
const showResyncModal = ref(false)
const showInviteHelpModal = ref(false)
// §HELLOFRAME: the invitation endpoint the help names is THIS frame's (it said api.theprotocol.cloud on every frame)
const consoleOrigin = typeof window !== 'undefined' ? window.location.origin : ''

const selectedInvitation = ref<FrameInvitation | null>(null)
const selectedPeer = ref<FramePeer | null>(null)

const approveNotes = ref('')
const rejectReason = ref('')
const revokeReason = ref('')
const actionBusy = ref(false)

const DRIFT_LABELS: Record<string, string> = {
  license_revoked_operator_active: 'License revoked — operator still active',
  operator_revoked_license_active: 'Operator revoked — license still active',
  peer_inactive_license_active: 'Peer unreachable — direct peering INACTIVE and no chain connection',
  frame_bundle_stale: 'Frame trust bundle missing in SPIRE — relationship or bundle absent (Resync to repair)',
  frame_bundle_expired: 'Frame trust bundle EXPIRED — present but every root is past not_after; needs a manual `bundle set` (SPIRE cannot recover it)',
  frame_bundle_expiring: 'Frame trust bundle expires soon — SPIRE should refresh first; watch the spire-server log if it does not',
}
const driftLabel = (flag: string) => DRIFT_LABELS[flag] || flag

// ─── Computed ───────────────────────────────────────────────────────

const pendingInvitations = computed(() => invitations.value.filter(i => i.status === 'pending'))
const filteredInvitations = computed(() => {
  if (invitationStatusFilter.value === 'all') return invitations.value
  return invitations.value.filter(i => i.status === invitationStatusFilter.value)
})
const filteredFrames = computed(() => {
  if (frameStatusFilter.value === 'all') return framePeers.value
  return framePeers.value.filter(p => (p.status || '').toUpperCase() === frameStatusFilter.value)
})
const activeFrames = computed(() => framePeers.value.filter(p => (p.status || '').toUpperCase() === 'ACTIVE'))
const staleFrames = computed(() => framePeers.value.filter(p => p.drift_flags?.includes('frame_bundle_stale')))
const fullyWiredFrames = computed(() => {
  const registered = new Set(crossFramePeers.value.filter(p => p.status === 'active').map(p => p.frame_id))
  const opRegistered = new Set(federationOperators.value.filter(o => o.status === 'active').map(o => (o.spiffe_id || '').replace(/^spiffe:\/\//, '')))
  return activeFrames.value.filter(p =>
    p.trust_domain && registered.has(p.trust_domain) && opRegistered.has(p.trust_domain),
  )
})

function sf4StatusFor(peer: FramePeer): 'registered' | 'missing' | 'suspended' {
  if (!peer.trust_domain) return 'missing'
  const row = crossFramePeers.value.find(p => p.frame_id === peer.trust_domain)
  if (!row) return 'missing'
  if (row.status === 'active') return 'registered'
  return 'suspended'
}
function sf5StatusFor(peer: FramePeer): 'registered' | 'missing' | 'suspended' {
  if (!peer.trust_domain) return 'missing'
  const row = federationOperators.value.find(o => (o.spiffe_id || '').replace(/^spiffe:\/\//, '') === peer.trust_domain)
  if (!row) return 'missing'
  if (row.status === 'active') return 'registered'
  return 'suspended'
}
function sf4WatermarkFor(peer: FramePeer): string | null {
  if (!peer.trust_domain) return null
  const row = crossFramePeers.value.find(p => p.frame_id === peer.trust_domain)
  return row?.last_timestamp || null
}

// ─── Fetch ──────────────────────────────────────────────────────────

// ── §FRAMELIC (2026-09-07) — FRAME FEDERATION LICENCES ──────────────────────────────────────
// His word: "frames get a license from new eu frame when stood up … build it enterprise grade in
// frame management already existing also frontend. operator management is the operator version
// which also has the licenses."
//
// One table backs both classes (`federation_licenses.licensee_type`), so this panel and
// OperatorManagement's must each ask for THEIR class — an unfiltered list would show a frame
// licence in the operator console and read as a stray operator nobody provisioned.
interface FrameLicense {
  id: string
  operator_name: string        // the LICENSEE's name — a frame here, an operator there
  operator_did: string
  licensee_type: string
  license_key_prefix: string
  status: string
  issued_at: string
  revoked_at: string | null
  revoked_reason: string | null
  max_agents: number
  max_events_per_minute: number
  federation_tier: string
  last_seen_at: string | null
  event_count: number
  min_image_version: string | null
}

const frameLicenses = ref<FrameLicense[]>([])
const licenseLoading = ref(false)
const licenseError = ref<string | null>(null)
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const licensesRead = ref(false)
const licenseFilter = ref('all')
const showIssueLicenseModal = ref(false)
const showLicenseKeyModal = ref(false)
const showLicenseActionModal = ref(false)
const licenseAction = ref<'revoke' | 'suspend' | 'reinstate'>('revoke')
const selectedLicense = ref<FrameLicense | null>(null)
const licenseActionReason = ref('')
const issuedKey = ref('')
const licenseBusy = ref(false)
const newFrameLicense = ref({ frame_name: '', trust_domain: '', federation_tier: 'sovereign' })

const filteredLicenses = computed(() =>
  licenseFilter.value === 'all'
    ? frameLicenses.value
    : frameLicenses.value.filter(l => l.status === licenseFilter.value))

const activeLicenseCount = computed(() => frameLicenses.value.filter(l => l.status === 'active').length)

/** A federated frame with no licence row — the gap this panel exists to make visible. Only once the licences were read:
 *  before an answer, or over a failed read, every ACTIVE frame was named as holding no licence, with an "Issue for …"
 *  button beside it (§FESUITE V0577). */
const unlicensedFrames = computed(() => {
  if (!licensesRead.value) return []
  const licensed = new Set(frameLicenses.value
    .filter(l => l.status === 'active')
    .map(l => (l.operator_did || '').replace(/^spiffe:\/\//, '').toLowerCase()))
  return framePeers.value.filter((f: any) =>
    String(f.status || '').toUpperCase() === 'ACTIVE' &&
    f.trust_domain && !licensed.has(String(f.trust_domain).toLowerCase()))
})

async function loadFrameLicenses() {
  licenseLoading.value = true
  licenseError.value = null
  try {
    const res = await apiClient.get('/admin/federation/licenses', { params: { licensee_type: 'frame' } })
    frameLicenses.value = Array.isArray(res.data) ? res.data : []
    licensesRead.value = true
  } catch (e: any) {
    licenseError.value = e?.response?.data?.detail || e?.message || 'Load failed'
  } finally {
    licenseLoading.value = false
  }
}

function openIssueLicense(prefill?: any) {
  newFrameLicense.value = {
    frame_name: prefill?.name || '',
    trust_domain: prefill?.trust_domain || '',
    federation_tier: 'sovereign',
  }
  showIssueLicenseModal.value = true
}

async function submitIssueLicense() {
  const name = newFrameLicense.value.frame_name.trim()
  const td = newFrameLicense.value.trust_domain.trim()
  if (!name || !td) return
  licenseBusy.value = true
  try {
    const res = await apiClient.post('/admin/federation/licenses/generate', {
      operator_name: name,
      operator_did: td.startsWith('spiffe://') ? td : `spiffe://${td}`,
      licensee_type: 'frame',
      federation_tier: newFrameLicense.value.federation_tier,
      max_agents: 100000,
      max_events_per_minute: 100000,
    })
    // Shown ONCE. We only ever stored its hash, so a lost key is re-issued, never recovered.
    issuedKey.value = res.data?.license_key || ''
    showIssueLicenseModal.value = false
    showLicenseKeyModal.value = true
    await loadFrameLicenses()
  } catch (e: any) {
    notices.error('Licence not issued', e?.response?.data?.detail || e?.message || 'Failed')
  } finally {
    licenseBusy.value = false
  }
}

function openLicenseAction(lic: FrameLicense, action: 'revoke' | 'suspend' | 'reinstate') {
  selectedLicense.value = lic
  licenseAction.value = action
  licenseActionReason.value = ''
  showLicenseActionModal.value = true
}

async function submitLicenseAction() {
  const lic = selectedLicense.value
  if (!lic) return
  // Revoke and suspend both END something; the rail requires the reason and so do we.
  if (licenseAction.value !== 'reinstate' && !licenseActionReason.value.trim()) return
  licenseBusy.value = true
  try {
    await apiClient.post(
      `/admin/federation/licenses/${lic.id}/${licenseAction.value}`,
      licenseAction.value === 'reinstate' ? {} : { reason: licenseActionReason.value.trim() })
    showLicenseActionModal.value = false
    await loadFrameLicenses()
  } catch (e: any) {
    notices.error('Action failed', e?.response?.data?.detail || e?.message || 'Failed')
  } finally {
    licenseBusy.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([
      loadFrameLicenses(),
      loadInvitations(),
      loadFramePeers(),
      loadCrossFramePeers(),
      loadFederationOperators(),
      loadSpireStatus(),
    ])
  } finally {
    loading.value = false
  }
}

async function loadInvitations() {
  invitationsError.value = null
  try {
    const res = await apiClient.get('/admin/federation/frame-invitations', { params: { status: 'all' } })
    invitations.value = res.data?.invitations || []
    invitationsOk.value = true
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Load failed'
    invitationsError.value = msg
    notices.error('Invitations', msg)
  }
}
async function loadFramePeers() {
  framePeersError.value = null
  try {
    const res = await apiClient.get('/admin/federation/topology-overview')
    framePeers.value = res.data?.frames || []
    framePeersOk.value = true
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Load failed'
    framePeersError.value = msg
    notices.error('Frames', msg)
  } finally {
    framePeersRead.value = true
  }
}
async function loadCrossFramePeers() {
  crossFrameError.value = null
  try {
    const res = await apiClient.get('/admin/eventstore/cross-frame-peers')
    crossFramePeers.value = res.data?.peers || []
  } catch (e: any) {
    crossFramePeers.value = []
    crossFrameError.value = e?.response?.data?.detail || e?.message || 'EventStore unreachable'
  }
}
async function loadFederationOperators() {
  fedOpError.value = null
  try {
    const res = await apiClient.get('/admin/eventstore/federation-operators')
    federationOperators.value = res.data?.operators || []
  } catch (e: any) {
    federationOperators.value = []
    fedOpError.value = e?.response?.data?.detail || e?.message || 'EventStore unreachable'
  }
}
async function loadSpireStatus() {
  spireError.value = null
  try {
    const res = await apiClient.get('/admin/federation/frames/spire-status')
    spireStatus.value = res.data || null
  } catch (e: any) {
    spireStatus.value = null
    spireError.value = e?.response?.data?.detail || e?.message || 'SPIRE query failed'
  }
}

// ─── Actions ────────────────────────────────────────────────────────

function openApprove(inv: FrameInvitation) {
  selectedInvitation.value = inv
  approveNotes.value = ''
  showApproveModal.value = true
}
function openReject(inv: FrameInvitation) {
  selectedInvitation.value = inv
  rejectReason.value = ''
  showRejectModal.value = true
}
function openLifecycle(peer: FramePeer) {
  selectedPeer.value = peer
  showLifecycleModal.value = true
}
function openRevoke(peer: FramePeer) {
  selectedPeer.value = peer
  revokeReason.value = ''
  showRevokeModal.value = true
}
function openResync(peer: FramePeer) {
  selectedPeer.value = peer
  showResyncModal.value = true
}

async function approveInvitation() {
  if (!selectedInvitation.value || actionBusy.value) return
  actionBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/federation/frame-invitations/${selectedInvitation.value.id}/approve`,
      { notes: approveNotes.value },
    )
    const d = res.data || {}
    if (d.completed && d.sf4_registered && d.sf5_registered) {
      notices.success('Frame Federated', `${selectedInvitation.value.initiator_name} fully wired — handshake + SF-4 + SF-5 all green.`)
    } else if (d.completed) {
      notices.success(
        'Frame Approved (partial)',
        `Handshake OK. SF-4: ${d.sf4_registered ? 'OK' : d.sf4_detail}. SF-5: ${d.sf5_registered ? 'OK' : d.sf5_detail}. Use Resync to retry.`,
      )
    } else {
      notices.error('Approval Partial', d.warning || 'Remote finalize callback failed; use finalize-retry.')
    }
    showApproveModal.value = false
    selectedInvitation.value = null
    await loadAll()
  } catch (e: any) {
    notices.error('Approve failed', e?.response?.data?.detail || e?.message)
  } finally {
    actionBusy.value = false
  }
}

async function rejectInvitation() {
  if (!selectedInvitation.value || actionBusy.value) return
  const reason = rejectReason.value.trim()
  if (!reason) { notices.error('Reject', 'Reason required'); return }
  actionBusy.value = true
  try {
    await apiClient.post(
      `/admin/federation/frame-invitations/${selectedInvitation.value.id}/reject`,
      { reason },
    )
    notices.success('Invitation Rejected', selectedInvitation.value.initiator_name)
    showRejectModal.value = false
    selectedInvitation.value = null
    await loadInvitations()
  } catch (e: any) {
    notices.error('Reject failed', e?.response?.data?.detail || e?.message)
  } finally {
    actionBusy.value = false
  }
}

async function revokeFrame() {
  if (!selectedPeer.value || actionBusy.value) return
  const reason = revokeReason.value.trim()
  if (!reason) { notices.error('Revoke', 'Reason required'); return }
  actionBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/federation/frames/${selectedPeer.value.id}/revoke`,
      { reason },
    )
    const d = res.data || {}
    notices.success(
      'Frame Revoked',
      `${selectedPeer.value.name} — SPIRE: ${d.spire_bundle_remove_ok ? 'OK' : 'warn'}, SF-4: ${d.sf4_suspended ? 'OK' : 'warn'}, SF-5: ${d.sf5_suspended ? 'OK' : 'warn'}`,
    )
    showRevokeModal.value = false
    selectedPeer.value = null
    await loadAll()
  } catch (e: any) {
    notices.error('Revoke failed', e?.response?.data?.detail || e?.message)
  } finally {
    actionBusy.value = false
  }
}

async function resyncFrame() {
  if (!selectedPeer.value || actionBusy.value) return
  actionBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/federation/frames/${selectedPeer.value.id}/resync-eventstore`,
    )
    const d = res.data || {}
    const label = `SF-4: ${d.sf4_registered ? 'OK' : d.sf4_detail}, SF-5: ${d.sf5_registered ? 'OK' : d.sf5_detail}`
    if (d.sf4_registered && d.sf5_registered) {
      notices.success('Resync OK', label)
    } else {
      notices.error('Resync partial', label)
    }
    showResyncModal.value = false
    selectedPeer.value = null
    await loadAll()
  } catch (e: any) {
    notices.error('Resync failed', e?.response?.data?.detail || e?.message)
  } finally {
    actionBusy.value = false
  }
}

// ─── Helpers ────────────────────────────────────────────────────────

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}
function shortId(s: string | null | undefined, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function statusPillClass(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'active' || s === 'completed') return 'frm-pill--active'
  if (s === 'pending') return 'frm-pill--pending'
  if (s === 'approved') return 'frm-pill--approved'
  if (s === 'rejected' || s === 'suspended') return 'frm-pill--suspended'
  if (s === 'revoked' || s === 'removed' || s === 'inactive') return 'frm-pill--revoked'
  return 'frm-pill--neutral'
}

// ─── Lifecycle ──────────────────────────────────────────────────────

// FM3 (audit 2026-05-07): visibility guard on polling. Without this,
// setInterval keeps hitting 5 admin endpoints every 60s while the tab is
// hidden — needless load on registry-a + EventStore + SPIRE. Matches the
// pattern used in HealthMonitorUltimate.vue (Section 17).
let pollTimer: ReturnType<typeof setInterval> | null = null
// ═══════════════════════════════════════════════════════════════════════
// PROVISION FRAME (§FRAMEPROV P3, 2026-09-13)
// His decisions 2026-09-13: a frame is stood up by the HOST frame runner (a
// root service on a local socket with a closed job set), never from this
// registry; this panel is private behind admin_platform; the new frame's
// admin credential is shown once; Start/Stop for frames the runner did not
// build retired. Every refusal here is the runner's own sentence, and Start
// stays off until a plan passed for exactly the spec on screen.
// ═══════════════════════════════════════════════════════════════════════
const { canPlatform } = usePermissions()

const runnerAvailable = ref<boolean | null>(null)   // null until the first answer
const runnerReason = ref('')
const runnerInfo = ref<RunnerInfo | null>(null)
// §TESTBED P0 f (2026-09-19): what the runner's policy really gives a frame, read from its own status. The copy said
// "a pilot frame ... rate limits relaxed and the test tools on ... sends no mail" since Milestone 1; runner-built frames
// have been born production (rate limits on, test tools off) with the policy's relay since §LANTERNT3.
const runnerPostureLine = computed(() => {
  const p = runnerInfo.value?.posture
  if (p === 'production') return 'in production posture (rate limits on, the test tools off).'
  if (p === 'sandbox') return 'in sandbox posture (rate limits relaxed, the test tools on).'
  return "in the posture the runner's policy sets."
})
const runnerMailLine = computed(() => {
  const m = runnerInfo.value?.mail_relay
  if (m === true) return "It sends mail through the relay the runner's policy names."
  if (m === false) return "The runner's policy names no mail relay, so the frame sends no mail until it has one of its own."
  return ''
})
const runnerFrames = ref<RunnerFrame[]>([])
const runnerJobs = ref<RunnerJob[]>([])
const activeJob = ref<RunnerJob | null>(null)
const runnerLoading = ref(false)

// The job on screen: the active one, else the most recent.
const RUNNING: JobState[] = ['running', 'cancelling']
const followedId = ref<string | null>(null)
const followedJob = ref<RunnerJob | null>(null)
const followedEvents = ref<ProgressEvent[]>([])
const nowMs = ref(Date.now())
let eventsCursor = 0
let pollToken = 0
let followTimer: ReturnType<typeof setTimeout> | null = null
// After a job ends the page reads the runner's status until the frame list shows the outcome: the runner writes a
// job's end before its frame record (frameRecordSettled), so one read at the end kept a torn-down frame listed live.
const SETTLE_READS = 10
const SETTLE_GAP_MS = 3000
let settleTimer: ReturnType<typeof setTimeout> | null = null
let unmounted = false
const followedRunning = computed(() => !!followedJob.value && RUNNING.includes(followedJob.value.state))
const folded = computed(() => foldProgress(followedEvents.value, followedJob.value?.state ?? null))
// The facts a job that publishes no steps can still state about itself. Empty when there is nothing to say, so
// the block does not render an empty shell — a heading with no rows is a claim the rows must back.
const followedJobFacts = computed(() => {
  const j = followedJob.value
  if (!j || publishesStandupSteps(j.op)) return []
  const req = (j.request ?? {}) as Record<string, unknown>
  const spec = (req.spec ?? {}) as Record<string, unknown>
  const out: Array<{ label: string, value: string }> = []
  const operator = (spec.operator_name ?? spec.safe_name ?? req.operator ?? '') as string
  if (operator) out.push({ label: 'Operator', value: operator })
  if (spec.phase) out.push({ label: 'Phase', value: String(spec.phase) })
  if (j.refused === true) out.push({ label: 'Refused', value: 'nothing was written, so a re-run is safe' })
  else if (j.state === 'failed' && j.exit_code != null) {
    out.push({ label: 'Exit', value: String(j.exit_code) + (j.exit_code === 4 ? ' (it had already written to the frame)' : '') })
  }
  if (j.reason) out.push({ label: 'Reason', value: String(j.reason) })
  return out
})
const followedElapsed = computed(() =>
  formatElapsed(elapsedSeconds(followedJob.value?.created, followedJob.value?.ended, nowMs.value)))

// The provisioning form: the runner's spec, the numbers empty until someone types them.
interface ProvisionForm extends Omit<FrameSpec, 'mint' | 'lat' | 'lng'> {
  mint: number | ''
  lat: number | ''
  lng: number | ''
}
function blankForm(): ProvisionForm {
  return {
    name: '', frame_label: '', ticker: '', currency_name: '', mint: 1000000, theme: 'neural', description: '',
    operator_label: '', location_label: '', lat: '', lng: '', website: '', registry_image: '', teg_image: '',
  }
}
const showProvisionModal = ref(false)
const form = ref<ProvisionForm>(blankForm())
const planResult = ref<PlanResult | null>(null)
const plannedKey = ref('')
const planning = ref(false)
const starting = ref(false)

// Acts on a frame the runner built.
const resumeStep = ref<Record<string, string>>({})
const teardownTarget = ref<RunnerFrame | null>(null)
const teardownTyped = ref('')
const revealTarget = ref<RunnerFrame | null>(null)
const revealed = ref<RevealedCredential | null>(null)
const revealing = ref(false)

// ─── §FRAMEFORM: public frame requests ───────────────────────────────
// The intake form at /operator/request-frame lands rows here. This panel is
// the review queue; "Use for provisioning" copies a request into the form
// above, which is the whole point of persisting the answers instead of
// re-typing them out of an email.
const frameRequests = ref<FrameRequestAdminRead[]>([])
const frameRequestFilter = ref<'pending' | 'approved' | 'all'>('pending')
const frameRequestsLoading = ref(false)
const frameRequestsError = ref('')

async function loadFrameRequests() {
  frameRequestsLoading.value = true
  frameRequestsError.value = ''
  try {
    frameRequests.value = await frameRequestService.list(
      frameRequestFilter.value === 'all' ? undefined : frameRequestFilter.value,
    )
  } catch (e: any) {
    // A node whose image predates this rail answers 404 here. Say so plainly
    // rather than rendering an empty list, which reads as "no requests".
    frameRequestsError.value = e?.response?.status === 404
      ? 'Frame requests are not available on this node.'
      : 'Could not load frame requests.'
    frameRequests.value = []
  } finally {
    frameRequestsLoading.value = false
  }
}

/** Copy a request into the provisioning form and open it. Only fields the
 *  requester supplied are copied. A request carries no coordinates, and a
 *  frame's location is declared, never invented, so lat/lng stay for the admin. */
function useForProvisioning(r: FrameRequestAdminRead) {
  // One mapping for every request shape, the rebuilt form's and older rows alike (services/frameRequestForm.ts, tested).
  form.value = { ...form.value, ...provisioningPrefill(r) }
  openProvision()
  notices.success('Prefilled', `Provisioning form filled from ${r.contact_name}'s request.`)
}

async function setRequestStatus(r: FrameRequestAdminRead, status: string) {
  try {
    const updated = await frameRequestService.review(r.id, { status })
    Object.assign(r, updated)
    if (status === 'approved') {
      notices.success('Approved', `${r.contact_name} can download the frame kit from their frame page.`)
    }
    if (frameRequestFilter.value === 'pending' && status !== 'pending') {
      frameRequests.value = frameRequests.value.filter(x => x.id !== r.id)
    }
  } catch (e) {
    // the registry's own sentence (an approve for a frame we host is refused with one) beats a generic line
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    notices.error('Failed', typeof detail === 'string' && detail ? detail : 'Could not update the request.')
  }
}

/** The runner's live frame for a request, when it stood one up under the requested name. */
function liveFrameFor(r: FrameRequestAdminRead): string {
  const name = r.frame_name || ''
  return name && runnerFrames.value.some(f => f.name === name && f.state === 'live') ? name : ''
}

/** Close a request once its frame is live: the decision is recorded with the frame it became. */
async function markProvisioned(r: FrameRequestAdminRead) {
  const name = liveFrameFor(r)
  if (!name) return
  try {
    const updated = await frameRequestService.review(r.id, { status: 'provisioned', provisioned_frame: name })
    Object.assign(r, updated)
    if (frameRequestFilter.value === 'pending') {
      frameRequests.value = frameRequests.value.filter(x => x.id !== r.id)
    }
  } catch {
    notices.error('Failed', 'Could not record the request as provisioned.')
  }
}

const FEDERATION_WORDS: Record<string, string> = {
  A: 'federate later', B: 'standalone', C: 'standalone + test operator',
}

// who runs the frame decides its network licence (his words 2026-09-28); the form asks only when the frame federates
const FIRST_YEAR_LICENCES = new Set(['enterprise', 'government'])

function federationWords(r: FrameRequestAdminRead): string {
  const partners = r.answers?.network?.partners || []
  const words = FEDERATION_WORDS[r.federation_choice || ''] || r.federation_choice || '-'
  const said = partners.length ? `${words} (${partners.join(', ')})` : words
  const category = r.answers?.network?.licence_category
  if (!category) return said
  return `${said} · licence: ${category}, ${FIRST_YEAR_LICENCES.has(category) ? 'first year free' : 'free, no end date'}`
}

function requestPlace(r: FrameRequestAdminRead): string {
  const card = r.answers?.card
  if (!card?.location) return '-'
  return card.lat != null && card.lng != null && card.lat !== '' ? `${card.location} (${card.lat}, ${card.lng})` : String(card.location)
}

function requestHosting(r: FrameRequestAdminRead): string {
  const p = r.answers?.provisioning
  if (!p) return r.hostname ? 'their own infrastructure' : '-'
  const hosting = p.hosting === 'self' ? 'their own infrastructure' : 'hosted by us'
  return [hosting, p.posture, p.operators ? `${p.operators} operator(s)` : ''].filter(Boolean).join(' · ')
}

function changedSummary(r: FrameRequestAdminRead): string {
  const f = r.answers?.features || {}
  const t = r.answers?.treasury || {}
  const parts = [
    ...Object.entries(f).map(([k, v]) => `${k}=${v}`),
    ...Object.entries(t).map(([k, v]) => `${k}=${v}`),
  ]
  return parts.length ? parts.join(', ') : 'defaults everywhere'
}

/** The sentence a failed call carries: the runner's own refusal in `detail`, else a plain fallback. */
function runnerSentence(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (e?.response?.status === 404) return "This registry's image has no frame runner rail."
  return fallback
}

async function loadRunner() {
  runnerLoading.value = true
  try {
    const st = await frameRunnerService.status()
    runnerAvailable.value = st.available
    runnerReason.value = st.available
      ? ''
      : `The frame runner is not available on this registry: ${st.reason || 'no reason given'}.`
    runnerInfo.value = st.runner
    runnerFrames.value = st.frames
    runnerJobs.value = st.jobs
    activeJob.value = st.active
    if (st.active && followedId.value !== st.active.id) follow(st.active.id)
    else if (!followedId.value && st.jobs.length) follow(st.jobs[0].id)
  } catch (e: any) {
    runnerAvailable.value = false
    runnerReason.value = runnerSentence(e, 'The frame runner status could not be read.')
  } finally {
    runnerLoading.value = false
  }
}

function stopFollow() {
  if (followTimer) {
    clearTimeout(followTimer)
    followTimer = null
  }
}

function follow(jobId: string) {
  stopFollow()
  followedId.value = jobId
  followedJob.value = null
  followedEvents.value = []
  eventsCursor = 0
  pollFollowed()
}

async function pollFollowed() {
  const id = followedId.value
  if (!id) return
  const token = ++pollToken
  if (document.visibilityState === 'hidden') {
    followTimer = setTimeout(pollFollowed, 5000)
    return
  }
  try {
    const [st, page] = await Promise.all([frameRunnerService.job(id), frameRunnerService.events(id, eventsCursor)])
    if (token !== pollToken || followedId.value !== id) return   // a newer poll, or another job, took over
    nowMs.value = Date.now()
    followedJob.value = st.job
    if (page.events.length) followedEvents.value = followedEvents.value.concat(page.events)
    eventsCursor = page.next
    const fullPage = page.events.length >= 500   // the runner pages at 500 lines: read on before judging the end
    if (fullPage || RUNNING.includes(st.job.state)) {
      followTimer = setTimeout(pollFollowed, fullPage ? 0 : 2000)
    } else if (activeJob.value?.id === id) {
      settleAfterJob(st.job)   // the job ended: its frame and the runner's one job slot changed
    }
  } catch {
    if (token === pollToken && followedId.value === id) followTimer = setTimeout(pollFollowed, 5000)
  }
}

/** Reads the runner's status until the frame list shows how `job` ended, at most SETTLE_READS times. */
async function settleAfterJob(job: RunnerJob, reads = 1) {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  await loadRunner()
  if (unmounted || reads >= SETTLE_READS || frameRecordSettled(job, runnerFrames.value)) return
  settleTimer = setTimeout(() => settleAfterJob(job, reads + 1), SETTLE_GAP_MS)
}

async function cancelFollowed() {
  const id = followedId.value
  if (!id) return
  try {
    await frameRunnerService.cancel(id)
  } catch (e: any) {
    notices.error('Not cancelled', runnerSentence(e, 'The runner did not cancel the job.'))
  }
  stopFollow()
  pollFollowed()
}

/** What is sent: trimmed text, the ticker in capitals, the name in lower case, numbers as numbers. The runner
 *  judges every value; the plan gate keys on exactly this. */
function formSpec(): FrameSpec {
  const f = form.value
  return {
    name: f.name.trim().toLowerCase(), frame_label: f.frame_label.trim(), ticker: f.ticker.trim().toUpperCase(),
    currency_name: f.currency_name.trim(), mint: Number(f.mint), theme: f.theme, description: f.description.trim(),
    operator_label: f.operator_label.trim(), location_label: f.location_label.trim(), lat: Number(f.lat),
    lng: Number(f.lng), website: f.website.trim(), registry_image: f.registry_image, teg_image: f.teg_image,
  }
}
const coordsDeclared = computed(() => form.value.lat !== '' && form.value.lng !== ''
  && Number.isFinite(Number(form.value.lat)) && Number.isFinite(Number(form.value.lng)))
const formKey = computed(() => specKey(formSpec()))
const planPassedForForm = computed(() => !!planResult.value?.plan_ok && plannedKey.value === formKey.value)
const planIsStale = computed(() => !!planResult.value && plannedKey.value !== formKey.value)
const PLAN_FIELDS = ['public_url', 'es_public_url', 'trust_domain', 'ports', 'dns', 'certificate', 'vhosts', 'stack_dir']
const planRows = computed<[string, string][]>(() => {
  const derived = planResult.value?.plan?.derived || {}
  return PLAN_FIELDS.filter(k => derived[k] !== undefined && derived[k] !== null)
    .map(k => [k, typeof derived[k] === 'string' ? (derived[k] as string) : JSON.stringify(derived[k])])
})

function openProvision() {
  const images = runnerInfo.value?.images
  if (images) {
    if (!images.registry.includes(form.value.registry_image)) form.value.registry_image = images.registry[0] || ''
    if (!images.teg.includes(form.value.teg_image)) form.value.teg_image = images.teg[0] || ''
  }
  showProvisionModal.value = true
}

async function checkPlan() {
  if (!coordsDeclared.value) return
  const key = formKey.value
  planning.value = true
  try {
    planResult.value = await frameRunnerService.plan(formSpec())
    plannedKey.value = key
  } catch (e: any) {
    planResult.value = null
    plannedKey.value = ''
    notices.error('No plan', runnerSentence(e, 'The plan did not run.'))
  } finally {
    planning.value = false
  }
}

async function startStandup() {
  if (!planPassedForForm.value) return
  const key = formKey.value
  starting.value = true
  try {
    const res = await frameRunnerService.start(formSpec())
    if (res.started && res.job) {
      showProvisionModal.value = false
      planResult.value = null
      plannedKey.value = ''
      form.value = blankForm()
      follow(res.job.id)
      loadRunner()
    } else {
      // The runner planned again on the host and refused: show that plan, not the earlier one.
      planResult.value = { exit_code: res.exit_code ?? 2, plan_ok: false, plan: res.plan ?? null, stderr_tail: res.stderr_tail }
      plannedKey.value = key
    }
  } catch (e: any) {
    notices.error('Not started', runnerSentence(e, 'The standup did not start.'))
  } finally {
    starting.value = false
  }
}

/** A display link: the runner derives every frame address as <name>.<domain> (driver_argv in frame_runner.py). */
function frameConsole(f: RunnerFrame): string {
  return runnerInfo.value ? `https://${f.name}.${runnerInfo.value.domain}` : ''
}

async function resumeFrame(f: RunnerFrame) {
  const step = resumeStep.value[f.name]
  if (!step) return
  try {
    const res = await frameRunnerService.resume(f.name, step)
    resumeStep.value[f.name] = ''
    follow(res.job.id)
    loadRunner()
  } catch (e: any) {
    notices.error('Resume refused', runnerSentence(e, 'The resume did not start.'))
  }
}

function askTeardown(f: RunnerFrame) {
  teardownTarget.value = f
  teardownTyped.value = ''
}

async function confirmTeardown() {
  const f = teardownTarget.value
  if (!f || teardownTyped.value.trim() !== f.name) return
  teardownTarget.value = null
  try {
    const res = await frameRunnerService.teardown(f.name)
    follow(res.job.id)
    loadRunner()
  } catch (e: any) {
    notices.error('Teardown refused', runnerSentence(e, 'The teardown did not start.'))
  }
}

function askReveal(f: RunnerFrame) {
  revealTarget.value = f
  revealed.value = null
}

async function confirmReveal() {
  const f = revealTarget.value
  if (!f) return
  revealing.value = true
  try {
    revealed.value = await frameRunnerService.reveal(f.name)
  } catch (e: any) {
    revealTarget.value = null
    notices.error('Not handed over', runnerSentence(e, 'The credential was not handed over.'))
  } finally {
    revealing.value = false
    loadRunner()
  }
}

/** Closes the confirmation, never a credential on screen: that closes only through its own button. */
function dismissReveal() {
  if (!revealed.value) revealTarget.value = null
}

/** The page's only copy of the credential, forgotten as its dialog closes. */
function closeReveal() {
  revealed.value = null
  revealTarget.value = null
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    notices.success('Copied')
  } catch {
    notices.error('Copy failed', 'Select the text and copy it by hand.')
  }
}

onMounted(async () => {
  // The provisioning panel resolves FIRST and is deliberately not awaited behind
  // loadAll(). loadAll() fans out to five admin endpoints; on a loaded box that
  // takes seconds, and until it returned the panel sat on its initial `idle`
  // state saying "no frame job has run" while a frame was demonstrably live.
  // Wrong answer confidently displayed is worse than a spinner.
  if (canPlatform.value) loadRunner()
  loadFrameRequests()
  document.addEventListener('keydown', onKeydown)
  await loadAll()
  // §FESUITE (the leave sweep): a page left during loadAll() starts no poll when it lands (`unmounted` is its own flag)
  if (unmounted) return
  pollTimer = setInterval(() => {
    if (document.visibilityState !== 'hidden') {
      loadAll()
    }
  }, 60_000)
})
onUnmounted(() => {
  unmounted = true
  if (pollTimer) clearInterval(pollTimer)
  if (settleTimer) clearTimeout(settleTimer)
  stopFollow()
  followedId.value = null   // an answer still in flight must not schedule another poll
  document.removeEventListener('keydown', onKeydown)
})

// FM4 (audit 2026-05-07): ESC closes whichever modal is open. Keyboard a11y
// gap — previously only backdrop click + cancel button could close them.
function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (revealTarget.value) { dismissReveal(); return }
  if (teardownTarget.value) { teardownTarget.value = null; return }
  if (showProvisionModal.value) { showProvisionModal.value = false; return }
  if (showLicenseActionModal.value) { showLicenseActionModal.value = false; return }
  if (showLicenseKeyModal.value)    { showLicenseKeyModal.value = false; return }
  if (showIssueLicenseModal.value)  { showIssueLicenseModal.value = false; return }
  if (showLifecycleModal.value)   { showLifecycleModal.value = false; return }
  if (showResyncModal.value)      { showResyncModal.value = false; return }
  if (showRevokeModal.value)      { showRevokeModal.value = false; return }
  if (showRejectModal.value)      { showRejectModal.value = false; return }
  if (showApproveModal.value)     { showApproveModal.value = false; return }
  if (showInviteHelpModal.value)  { showInviteHelpModal.value = false; return }
}
</script>

<template>
  <div class="frm-page">
    <Teleport to="body">
      <NotificationSystem ref="pageNotices" style="z-index: 100050" data-testid="fm-notices" />
    </Teleport>
    <!-- FM1 (audit 2026-05-07): ambient background to match Federation/MyAgents/etc. -->
    <!-- Header -->
    <div class="frm-header">
      <h1 class="frm-title">{{ t('frameManagementView.title') }}</h1>
      <p class="frm-subtitle">
        {{ t('frameManagementView.subtitle') }}
        <button class="frm-btn-link" @click="showInviteHelpModal = true">{{ t('frameManagementView.howItWorks') }}</button>
      </p>
    </div>

    <!-- ═══ PROVISION FRAME (§FRAMEPROV P3, 2026-09-13) ═════════════════ -->
    <!-- The host frame runner's view, private behind admin_platform. -->
    <section v-if="canPlatform" class="fmp" data-testid="fmp-runner">
      <div class="fmp-head">
        <div>
          <h2 class="fmp-title">Provision sovereign frame</h2>
          <p class="fmp-sub">
            The host frame runner stands up a frame under this network: its own database, ledger, EventStore
            and SPIRE identity root, {{ runnerPostureLine }} It boots standalone, federates through the invitation
            rail and provisions its own cloud operators through the runner. {{ runnerMailLine }}
          </p>
        </div>
        <div class="fmp-actions">
          <button class="fmp-btn" :disabled="runnerLoading" data-testid="fmp-refresh" @click="loadRunner()">
            <Icon name="mdi:refresh" :size="14" /> Refresh
          </button>
          <button
            class="fmp-btn fmp-btn--primary"
            :disabled="!runnerAvailable || !!activeJob"
            :title="activeJob ? 'The runner takes one job at a time.' : ''"
            data-testid="fmp-new"
            @click="openProvision()"
          >
            <Icon name="mdi:plus-circle" :size="14" /> New frame
          </button>
        </div>
      </div>

      <p v-if="runnerAvailable === null" class="fmp-idle">Reading the frame runner…</p>
      <p v-else-if="!runnerAvailable" class="fmp-fatal fmp-unavailable" data-testid="fmp-unavailable">{{ runnerReason }}</p>
      <template v-else>
        <div v-if="runnerFrames.length" class="fmp-frames">
          <div class="fmp-frames-head">
            <span>Frames the runner built</span>
            <span class="fmp-frames-sub">frames it did not build are not managed here</span>
          </div>
          <div v-for="f in runnerFrames" :key="f.name" class="fmp-frame" :data-frame="f.name">
            <div class="fmp-frame-id">
              <span class="fmp-frame-dot" :class="f.state === 'live' ? 'is-up' : 'is-down'"></span>
              <div>
                <div class="fmp-frame-name">{{ f.spec?.frame_label || f.name }}</div>
                <div class="fmp-frame-meta">
                  <code>{{ f.name }}</code>
                  <span v-if="f.spec?.ticker" class="fmp-frame-ticker">{{ f.spec.ticker }}</span>
                </div>
              </div>
            </div>
            <div class="fmp-frame-state">
              <span class="fmp-frame-pill" :class="f.state === 'live' ? 'is-up' : 'is-down'">{{ f.state }}</span>
              <a v-if="f.state === 'live' && frameConsole(f)" :href="frameConsole(f)" target="_blank" rel="noopener" class="fmp-frame-link">
                Open <Icon name="mdi:open-in-new" :size="12" />
              </a>
            </div>
            <div class="fmp-frame-actions">
              <button v-if="!f.revealed_at" class="fmp-btn" :disabled="!!activeJob" @click="askReveal(f)">
                <Icon name="mdi:key" :size="14" /> Admin credential
              </button>
              <select v-model="resumeStep[f.name]" class="fmp-select" :disabled="!!activeJob" :aria-label="`Resume ${f.name} from a step`">
                <option value="">Resume from…</option>
                <option v-for="step in runnerInfo?.resumable_steps || []" :key="step" :value="step">{{ step }}</option>
              </select>
              <button class="fmp-btn" :disabled="!!activeJob || !resumeStep[f.name]" @click="resumeFrame(f)">
                <Icon name="mdi:play-circle" :size="14" /> Resume
              </button>
              <button class="fmp-btn fmp-btn--danger" :disabled="!!activeJob" @click="askTeardown(f)">
                <Icon name="mdi:trash-can-outline" :size="14" /> Tear down
              </button>
            </div>
          </div>
        </div>
        <p v-else class="fmp-idle">No frame built by the runner is running.</p>

        <div v-if="followedJob" class="fmp-live" data-testid="fmp-job">
          <div class="fmp-stage-row">
            <span v-if="followedRunning" class="fmp-pulse"></span>
            <span class="fmp-stage">{{ followedJob.op }} · {{ followedJob.name }} · {{ followedJob.state }}</span>
            <span class="fmp-elapsed">{{ followedElapsed }}</span>
            <button v-if="followedJob.state === 'running'" class="fmp-btn fmp-btn--danger fmp-count" data-testid="fmp-cancel" @click="cancelFollowed()">
              <Icon name="mdi:stop-circle" :size="14" /> Cancel
            </button>
          </div>

          <ol v-if="publishesStandupSteps(followedJob.op)" class="fmp-steps">
            <li v-for="row in folded.rows" :key="row.step" class="fmp-step" :class="'fmp-step--' + row.state">
              <span class="fmp-svc-dot"></span>
              <span class="fmp-step-name">{{ row.step }}</span>
              <span class="fmp-step-state">{{ row.state === 'unreached' ? 'not run' : row.state }}</span>
              <span v-if="row.sentence" class="fmp-step-sentence">{{ row.sentence }}</span>
            </li>
          </ol>
          <template v-else>
            <p class="fmp-note" data-testid="fmp-no-steps">
              {{ followedJob.op === 'teardown'
                ? "The teardown script writes no step events; the job's state above is its answer."
                : "This job publishes no step events, so there is no step list to show. Its state above is its answer." }}
            </p>
            <!-- What an operator job CAN say about itself: which phase was asked for, for whom, and, when it
                 failed, the runner's own reason. `refused` is the one distinction that changes what a reader
                 should do: nothing was written, so a re-run is safe. -->
            <dl v-if="followedJobFacts.length" class="fmp-facts fmp-note" data-testid="fmp-job-facts">
              <template v-for="f in followedJobFacts" :key="f.label">
                <dt>{{ f.label }}</dt><dd>{{ f.value }}</dd>
              </template>
            </dl>
          </template>

          <div v-if="folded.live" class="fmp-done">
            <div class="fmp-done-head">
              <Icon name="mdi:check-circle" :size="18" />
              <span>{{ followedJob.name }} is live</span>
            </div>
            <dl class="fmp-kv">
              <template v-for="(url, label) in (folded.live.urls || {})" :key="label">
                <dt>{{ label }}</dt>
                <dd><a :href="safeExternalUrl(url)" target="_blank" rel="noopener noreferrer">{{ url }}</a></dd>
              </template>
            </dl>
            <p class="fmp-next">
              Next: hand its admin credential over (once). Its admin signs in, funds its reserves and
              federates through the invitation rail when ready.
            </p>
          </div>
          <div v-else-if="folded.failure" class="fmp-failed">
            <div class="fmp-done-head fmp-done-head--bad">
              <Icon name="mdi:alert-circle" :size="18" />
              <span>Stopped at {{ folded.failure.step }}</span>
            </div>
            <p class="fmp-fatal">{{ folded.failure.sentence }}</p>
          </div>
        </div>

        <details v-if="runnerJobs.length" class="fmp-jobs">
          <summary>Recent runner jobs ({{ runnerJobs.length }})</summary>
          <ul>
            <li v-for="j in runnerJobs" :key="j.id">
              <button class="fmp-loglink" :disabled="followedId === j.id" @click="follow(j.id)">{{ j.op }} {{ j.name }}</button>
              <span>{{ j.state }} · {{ j.created }}</span>
            </li>
          </ul>
        </details>
      </template>
    </section>

    <!-- Drift banner -->
    <div v-if="staleFrames.length > 0" class="frm-drift-banner">
      {{ t('frameManagementView.drift.banner', { count: staleFrames.length, domains: staleFrames.map(f => f.trust_domain).join(', ') }) }}
    </div>
    <div v-else class="frm-drift-clean">{{ t('frameManagementView.drift.clean') }}</div>

    <!-- Stats row -->
    <div class="frm-stats">
      <div class="frm-stat frm-stat--violet">
        <span class="frm-stat-lbl">{{ t('frameManagementView.stats.total') }}</span>
        <span class="frm-stat-val">{{ framePeersOk ? framePeers.length : '—' }}</span>
      </div>
      <div class="frm-stat frm-stat--green">
        <span class="frm-stat-lbl">{{ t('frameManagementView.stats.active') }}</span>
        <span class="frm-stat-val">{{ framePeersOk ? activeFrames.length : '—' }}</span>
      </div>
      <div class="frm-stat frm-stat--amber">
        <span class="frm-stat-lbl">{{ t('frameManagementView.stats.pendingInv') }}</span>
        <span class="frm-stat-val">{{ invitationsOk ? pendingInvitations.length : '—' }}</span>
      </div>
      <div class="frm-stat frm-stat--red">
        <span class="frm-stat-lbl">{{ t('frameManagementView.stats.missing') }}</span>
        <span class="frm-stat-val">{{ framePeersOk ? staleFrames.length : '—' }}</span>
      </div>
      <div class="frm-stat frm-stat--cyan">
        <span class="frm-stat-lbl">{{ t('frameManagementView.stats.wired') }}</span>
        <span class="frm-stat-val">{{ framePeersOk ? `${fullyWiredFrames.length}/${activeFrames.length}` : '—' }}</span>
      </div>
    </div>

    <!-- Section: Frame Requests (§FRAMEFORM) -->
    <section class="frm-section">
      <div class="frm-section-head">
        <h2 class="frm-section-title">Frame requests</h2>
        <select v-model="frameRequestFilter" class="frm-filter" data-testid="fq-filter" @change="loadFrameRequests" :aria-label="t('frameManagementView.requestFilterAria', 'Filter frame requests')">
          <option value="pending">Pending</option>
          <option v-if="frameKitEnabled" value="approved">Approved (kit)</option>
          <option value="all">All</option>
        </select>
      </div>

      <div v-if="frameRequestsLoading" class="fq-empty">Loading…</div>
      <div v-else-if="frameRequestsError" class="fq-empty fq-empty--err">{{ frameRequestsError }}</div>
      <div v-else-if="!frameRequests.length" class="fq-empty">
        Nothing waiting. Submissions from the public form at /frame-commander land here.
      </div>

      <div v-else class="fq-list" data-testid="fq-list">
        <article v-for="r in frameRequests" :key="r.id" class="fq-card" data-testid="fq-card" :data-request="r.id">
          <header class="fq-head">
            <div>
              <div class="fq-who">{{ r.organization || r.contact_name }}</div>
              <div class="fq-sub">{{ r.contact_name }} &middot; {{ r.contact_email }}</div>
            </div>
            <span class="fq-status" :class="'fq-status--' + r.status">{{ r.status }}</span>
          </header>

          <div class="fq-grid">
            <div><span>FRAME</span>{{ r.frame_name || '-' }}</div>
            <div><span>DISPLAY</span>{{ r.display_name || '-' }}</div>
            <div><span>HOST</span>{{ r.hostname || 'we host it' }}</div>
            <div><span>TRUST DOMAIN</span>{{ r.trust_domain || '-' }}</div>
            <div><span>CURRENCY</span>{{ r.ticker || '-' }}<template v-if="r.currency_name"> ({{ r.currency_name }})</template></div>
            <div><span>FEDERATION</span>{{ federationWords(r) }}</div>
            <div><span>HOSTING</span>{{ requestHosting(r) }}</div>
            <div><span>PLACE</span>{{ requestPlace(r) }}</div>
            <div><span>THEME</span>{{ r.answers?.card?.theme || '-' }}</div>
            <div v-if="requestTags(r).length"><span>TAGS</span>{{ requestTags(r).join(', ') }}</div>
            <div v-if="r.provisioned_frame"><span>PROVISIONED AS</span>{{ r.provisioned_frame }}</div>
            <div v-if="r.kit_approved_at" data-testid="fq-kit"><span>FRAME KIT</span>{{ r.kit_download_count || 0 }} download(s) since {{ String(r.kit_approved_at).slice(0, 10) }}</div>
          </div>

          <p class="fq-changed"><span>CHANGED</span>{{ changedSummary(r) }}</p>
          <!-- §FESUITE V0595: what those choices mean as env, from the server's catalog (the lines a provisioning writes) -->
          <p v-if="r.env_preview?.length" class="fq-changed" data-testid="fq-env"><span>ENV</span>{{ r.env_preview.join(' · ') }}</p>
          <p v-if="r.use_case" class="fq-text"><span>WHY</span>{{ r.use_case }}</p>
          <p v-if="r.notes" class="fq-text"><span>NOTES</span>{{ r.notes }}</p>

          <footer class="fq-actions">
            <button v-if="canPlatform && r.status !== 'provisioned'" class="fmp-btn fmp-btn--primary" :disabled="!runnerAvailable" data-testid="fq-use" @click="useForProvisioning(r)">Use for provisioning</button>
            <button v-if="canPlatform && r.status !== 'provisioned' && liveFrameFor(r)" class="fmp-btn" data-testid="fq-mark-provisioned" @click="markProvisioned(r)">Mark provisioned as {{ liveFrameFor(r) }}</button>
            <!-- §HELLOFRAME: a frame its applicant runs is APPROVED here, which opens their frame kit download (and mails them
                 when FRAME_KIT_ENABLED is on); approving again opens a new download window. A frame we host keeps its path. -->
            <button v-if="frameKitEnabled && r.answers?.provisioning?.hosting === 'self' && r.status !== 'provisioned' && r.status !== 'rejected'"
                    class="fmp-btn fmp-btn--primary" data-testid="fq-approve" @click="setRequestStatus(r, 'approved')">
              {{ r.status === 'approved' ? 'Renew kit window' : 'Approve' }}
            </button>
            <button v-if="r.status !== 'reviewed' && r.status !== 'provisioned' && r.status !== 'approved'" class="fmp-btn" data-testid="fq-mark-reviewed" @click="setRequestStatus(r, 'reviewed')">Mark reviewed</button>
            <button v-if="r.status !== 'rejected' && r.status !== 'provisioned'" class="fmp-btn" data-testid="fq-reject" @click="setRequestStatus(r, 'rejected')">Reject</button>
            <a class="fq-mail" data-testid="fq-mail" :href="'mailto:' + r.contact_email">Reply by mail</a>
          </footer>
        </article>
      </div>
    </section>

    <!-- Section: Pending Invitations -->
    <section class="frm-section">
      <div class="frm-section-head">
        <h2 class="frm-section-title">{{ t('frameManagementView.sections.pending') }}</h2>
        <select v-model="invitationStatusFilter" class="frm-filter" :aria-label="t('frameManagementView.inviteFilterAria', 'Filter invitations by status')">
          <option value="pending">{{ t('frameManagementView.inviteFilter.pending') }}</option>
          <option value="all">{{ t('frameManagementView.inviteFilter.all') }}</option>
          <option value="rejected">{{ t('frameManagementView.inviteFilter.rejected') }}</option>
          <option value="completed">{{ t('frameManagementView.inviteFilter.completed') }}</option>
        </select>
      </div>
      <!-- FM2: error banner with retry -->
      <div v-if="invitationsError" class="frm-error-banner">
        <span><Icon name="mdi:alert" /> {{ invitationsError }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadInvitations">{{ t('frameManagementView.retry') }}</button>
      </div>
      <div class="frm-table-wrap">
        <table class="frm-table">
          <thead>
            <tr>
              <th>{{ t('frameManagementView.inviteTable.thName') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thTrustDomain') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thFedEndpoint') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thContact') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thSourceIp') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thStatus') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thCreated') }}</th>
              <th>{{ t('frameManagementView.inviteTable.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <!-- §FESUITE V0577: "No invitations match the current filter." only after the invitations answered -->
            <tr v-if="invitationsError && !invitations.length">
              <td colspan="8"><ReadFailedNotice dense :retry="loadInvitations" data-testid="frm-inv-unread" /></td>
            </tr>
            <tr v-else-if="!invitationsOk">
              <td colspan="8" class="frm-empty-cell">{{ t('common.loading', 'Loading…') }}</td>
            </tr>
            <tr v-else-if="filteredInvitations.length === 0">
              <td colspan="8" class="frm-empty-cell">{{ t('frameManagementView.inviteTable.empty') }}</td>
            </tr>
            <tr v-for="inv in filteredInvitations" :key="inv.id">
              <td><strong>{{ inv.initiator_name }}</strong></td>
              <td><code>{{ inv.initiator_trust_domain }}</code></td>
              <td class="frm-td-url">{{ inv.initiator_federation_endpoint_url }}</td>
              <td>{{ inv.initiator_contact_email }}</td>
              <td><code>{{ inv.initiator_ip || '—' }}</code></td>
              <td><span class="frm-pill" :class="statusPillClass(inv.status)">{{ inv.status }}</span></td>
              <td>{{ timeAgo(inv.created_at) }}</td>
              <td>
                <template v-if="inv.status === 'pending'">
                  <button class="frm-btn frm-btn--green" @click="openApprove(inv)">{{ t('frameManagementView.inviteTable.approve') }}</button>
                  <button class="frm-btn frm-btn--red" @click="openReject(inv)">{{ t('frameManagementView.inviteTable.reject') }}</button>
                </template>
                <span v-else-if="inv.rejection_reason" class="frm-td-reason" :title="inv.rejection_reason">
                  {{ t('frameManagementView.inviteTable.rejectedPrefix') }}{{ shortId(inv.rejection_reason, 40) }}
                </span>
                <span v-else class="frm-muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Section: Federated Frames -->
    <section class="frm-section">
      <div class="frm-section-head">
        <h2 class="frm-section-title">{{ t('frameManagementView.sections.federated') }}</h2>
        <select v-model="frameStatusFilter" class="frm-filter" :aria-label="t('frameManagementView.frameFilterAria', 'Filter frames by status')">
          <option value="all">{{ t('frameManagementView.frameFilter.all') }}</option>
          <option value="ACTIVE">{{ t('frameManagementView.frameFilter.active') }}</option>
          <option value="INACTIVE">{{ t('frameManagementView.frameFilter.inactive') }}</option>
        </select>
      </div>
      <!-- FM2: error banners with retry -->
      <div v-if="framePeersError" class="frm-error-banner">
        <span>{{ t('frameManagementView.errors.framesPrefix') }} {{ framePeersError }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadFramePeers">{{ t('frameManagementView.retry') }}</button>
      </div>
      <div v-if="crossFrameError" class="frm-error-banner frm-error-banner--soft">
        <span>{{ t('frameManagementView.errors.sf4Prefix') }} {{ crossFrameError }} {{ t('frameManagementView.errors.sf4Suffix') }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadCrossFramePeers">{{ t('frameManagementView.retry') }}</button>
      </div>
      <div v-if="fedOpError" class="frm-error-banner frm-error-banner--soft">
        <span>{{ t('frameManagementView.errors.sf5Prefix') }} {{ fedOpError }} {{ t('frameManagementView.errors.sf5Suffix') }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadFederationOperators">{{ t('frameManagementView.retry') }}</button>
      </div>
      <div class="frm-table-wrap">
        <table class="frm-table">
          <thead>
            <tr>
              <th>{{ t('frameManagementView.frameTable.thName') }}</th>
              <th>{{ t('frameManagementView.frameTable.thTrustDomain') }}</th>
              <th>{{ t('frameManagementView.frameTable.thBaseUrl') }}</th>
              <th>{{ t('frameManagementView.frameTable.thLastSeen') }}</th>
              <th>{{ t('frameManagementView.frameTable.thStatus') }}</th>
              <th>{{ t('frameManagementView.frameTable.thDrift') }}</th>
              <th>{{ t('frameManagementView.frameTable.thSf4') }}</th>
              <th>{{ t('frameManagementView.frameTable.thSf5') }}</th>
              <th>{{ t('frameManagementView.frameTable.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredFrames.length === 0">
              <td colspan="9" class="frm-empty-cell" role="status">{{ !framePeersRead ? t('common.loading', 'Loading…') : framePeersError ? t('frameManagementView.frameTable.unread', 'The frames could not be read just now.') : t('frameManagementView.frameTable.empty') }}</td>
            </tr>
            <tr v-for="f in filteredFrames" :key="f.id" @click="openLifecycle(f)" class="frm-row-clickable">
              <td><strong>{{ f.name }}</strong></td>
              <td><code>{{ f.trust_domain }}</code></td>
              <td class="frm-td-url">{{ f.base_url }}</td>
              <td>{{ timeAgo(f.last_seen_in_topology_at) }}</td>
              <td><span class="frm-pill" :class="statusPillClass(f.status)">{{ f.status }}</span></td>
              <td>
                <span v-if="f.has_drift" class="frm-pill frm-pill--drift" :title="(f.drift_flags || []).map(driftLabel).join('\n')">
                  <Icon name="mdi:alert" /> {{ (f.drift_flags || []).length }}
                </span>
                <span v-else class="frm-muted">—</span>
              </td>
              <td>
                <span class="frm-pill" :class="{
                  'frm-pill--active': sf4StatusFor(f) === 'registered',
                  'frm-pill--suspended': sf4StatusFor(f) === 'suspended',
                  'frm-pill--revoked': sf4StatusFor(f) === 'missing',
                }">{{ sf4StatusFor(f) }}</span>
              </td>
              <td>
                <span class="frm-pill" :class="{
                  'frm-pill--active': sf5StatusFor(f) === 'registered',
                  'frm-pill--suspended': sf5StatusFor(f) === 'suspended',
                  'frm-pill--revoked': sf5StatusFor(f) === 'missing',
                }">{{ sf5StatusFor(f) }}</span>
              </td>
              <td @click.stop>
                <button class="frm-btn frm-btn--cyan" @click="openLifecycle(f)">{{ t('frameManagementView.frameTable.lifecycle') }}</button>
                <button class="frm-btn frm-btn--amber" @click="openResync(f)">{{ t('frameManagementView.frameTable.resync') }}</button>
                <button v-if="(f.status || '').toUpperCase() === 'ACTIVE'"
                        class="frm-btn frm-btn--red" @click="openRevoke(f)">{{ t('frameManagementView.frameTable.revoke') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ───────────── §FRAMELIC: frame federation licences (2026-09-07) ───────────── -->
    <section class="frm-section" data-testid="frm-licences">
      <div class="frm-section-head">
        <h2 class="frm-section-title">
          Frame federation licences
          <span class="frm-lic-count">{{ licensesRead ? `${activeLicenseCount} active / ${frameLicenses.length}` : '—' }}</span>
        </h2>
        <div class="frm-head-actions">
          <select v-model="licenseFilter" class="frm-filter" data-testid="frm-lic-filter" :aria-label="t('frameManagementView.licenceFilterAria', 'Filter licences by status')">
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="revoked">Revoked</option>
          </select>
          <button class="frm-btn frm-btn--ghost" @click="loadFrameLicenses">{{ t('frameManagementView.refresh') }}</button>
          <button class="frm-btn frm-btn--cyan" data-testid="frm-lic-issue" @click="openIssueLicense()">Issue licence</button>
        </div>
      </div>

      <p class="frm-muted frm-lic-note">
        This frame is the anchor of its network: a frame that federates here holds a licence issued
        here, exactly as a cloud operator does. Revoking one stops that frame federating without
        touching its identity or its ledger. The key is shown once — we store only its hash.
      </p>

      <div v-if="licenseError" class="frm-error-banner">
        <span><Icon name="mdi:alert" /> {{ licenseError }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadFrameLicenses">{{ t('frameManagementView.retry') }}</button>
      </div>

      <!-- A federated frame with NO licence is the gap this panel exists to show. Naming it
           beats an empty table that reads as "nothing to do here". -->
      <div v-if="unlicensedFrames.length" class="frm-warn-banner" data-testid="frm-lic-unlicensed">
        <span>
          <Icon name="mdi:alert" />
          {{ unlicensedFrames.length }} federated frame(s) hold no active licence:
          {{ unlicensedFrames.map((f: any) => f.name).join(', ') }}
        </span>
        <button class="frm-btn frm-btn--cyan" @click="openIssueLicense(unlicensedFrames[0])">
          Issue for {{ unlicensedFrames[0].name }}
        </button>
      </div>

      <div class="frm-table-wrap">
        <table class="frm-table">
          <thead>
            <tr>
              <th>Frame</th><th>Trust domain</th><th>Key</th><th>Status</th>
              <th>Tier</th><th>Issued</th><th>Last seen</th><th>Events</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="licenseLoading && !frameLicenses.length"><td colspan="9" class="frm-muted">Loading…</td></tr>
            <tr v-else-if="licenseError && !frameLicenses.length"><td colspan="9"><ReadFailedNotice dense :retry="loadFrameLicenses" data-testid="frm-lic-unread" /></td></tr>
            <tr v-else-if="!filteredLicenses.length && licensesRead"><td colspan="9" class="frm-muted">No frame licences.</td></tr>
            <tr v-for="lic in filteredLicenses" :key="lic.id" :data-lic-status="lic.status">
              <td>{{ lic.operator_name }}</td>
              <td class="frm-code">{{ (lic.operator_did || '').replace('spiffe://', '') }}</td>
              <td class="frm-code">{{ lic.license_key_prefix }}…</td>
              <td>
                <span class="frm-pill" :class="'frm-pill--' + lic.status">{{ lic.status }}</span>
                <span v-if="lic.status !== 'active' && (lic.revoked_reason || '')" class="frm-muted frm-lic-reason">
                  {{ lic.revoked_reason }}
                </span>
              </td>
              <td>{{ lic.federation_tier }}</td>
              <td class="frm-code">{{ (lic.issued_at || '').slice(0, 10) }}</td>
              <!-- A licence that has never been presented is a licence nobody is using; say so
                   rather than printing an empty cell that reads as a load failure. -->
              <td class="frm-code">{{ lic.last_seen_at ? lic.last_seen_at.slice(0, 16).replace('T', ' ') : 'never presented' }}</td>
              <td class="frm-code">{{ lic.event_count }}</td>
              <td class="frm-td-actions">
                <button v-if="lic.status === 'active'" class="frm-btn frm-btn--amber"
                        @click="openLicenseAction(lic, 'suspend')">Suspend</button>
                <button v-if="lic.status !== 'active'" class="frm-btn frm-btn--cyan"
                        @click="openLicenseAction(lic, 'reinstate')">Reinstate</button>
                <button v-if="lic.status !== 'revoked'" class="frm-btn frm-btn--red"
                        @click="openLicenseAction(lic, 'revoke')">Revoke</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Section: SPIRE Trust Bundles (live) -->
    <section class="frm-section">
      <div class="frm-section-head">
        <h2 class="frm-section-title">{{ t('frameManagementView.sections.trustBundles') }}</h2>
        <button class="frm-btn frm-btn--ghost" @click="loadSpireStatus">{{ t('frameManagementView.refresh') }}</button>
      </div>
      <!-- FM2: error banner with retry -->
      <div v-if="spireError" class="frm-error-banner">
        <span><Icon name="mdi:alert" /> SPIRE: {{ spireError }}</span>
        <button class="frm-btn frm-btn--ghost" @click="loadSpireStatus">{{ t('frameManagementView.retry') }}</button>
      </div>
      <div v-if="spireStatus" class="frm-spire-grid">
        <div class="frm-spire-cell">
          <div class="frm-spire-label">{{ t('frameManagementView.spire.local') }}</div>
          <code>spiffe://{{ spireStatus.local_trust_domain }}</code>
        </div>
        <div class="frm-spire-cell">
          <div class="frm-spire-label">{{ t('frameManagementView.spire.inBoth', { count: spireStatus.in_both.length }) }}</div>
          <ul>
            <li v-for="d in spireStatus.in_both" :key="d"><code>{{ d }}</code></li>
            <li v-if="spireStatus.in_both.length === 0" class="frm-muted">—</li>
          </ul>
        </div>
        <div class="frm-spire-cell frm-spire-cell--warn" v-if="spireStatus.in_db_only.length > 0">
          <div class="frm-spire-label">{{ t('frameManagementView.spire.dbOnly') }}</div>
          <ul>
            <li v-for="d in spireStatus.in_db_only" :key="d"><code>{{ d }}</code></li>
          </ul>
        </div>
        <div class="frm-spire-cell frm-spire-cell--warn" v-if="spireStatus.in_spire_only.length > 0">
          <div class="frm-spire-label">{{ t('frameManagementView.spire.spireOnly') }}</div>
          <ul>
            <li v-for="d in spireStatus.in_spire_only" :key="d"><code>{{ d }}</code></li>
          </ul>
        </div>
        <div v-if="spireStatus.spire_error" class="frm-spire-cell frm-spire-cell--error">
          {{ t('frameManagementView.spire.queryError') }} {{ spireStatus.spire_error }}
        </div>
      </div>
      <div v-else-if="!spireError" class="frm-muted">{{ t('frameManagementView.spire.loading') }}</div>
    </section>

    <!-- ───────────── Modals ───────────── -->

    <!-- Approve -->
    <Teleport to="body">
      <div v-if="showApproveModal" class="frm-overlay" @click.self="showApproveModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.approveModal.title') }}</h3>
            <button class="frm-modal-close" @click="showApproveModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <p v-if="selectedInvitation">
              {{ tp('frameManagementView.approveModal.body', 'Federate with {name} (trust domain {domain})?', { name: selectedInvitation.initiator_name, domain: selectedInvitation.initiator_trust_domain }) }}
            </p>
            <div class="frm-approve-steps">
              {{ t('frameManagementView.approveModal.stepsTitle') }}
              <ol>
                <li>{{ t('frameManagementView.approveModal.step1') }}</li>
                <li>{{ t('frameManagementView.approveModal.step2') }}</li>
                <li>{{ t('frameManagementView.approveModal.step3') }}</li>
                <li>{{ t('frameManagementView.approveModal.step4') }}</li>
                <li>{{ t('frameManagementView.approveModal.step5') }}</li>
              </ol>
            </div>
            <label class="frm-field">
              <span class="frm-field-label">{{ t('frameManagementView.approveModal.notesLabel') }}</span>
              <input v-model="approveNotes" class="frm-input" :placeholder="t('frameManagementView.approveModal.notesPlaceholder')" />
            </label>
            <div class="frm-modal-actions">
              <button class="frm-btn frm-btn--ghost" @click="showApproveModal = false">{{ t('frameManagementView.approveModal.cancel') }}</button>
              <button class="frm-btn frm-btn--green" :disabled="actionBusy" @click="approveInvitation">
                {{ actionBusy ? t('frameManagementView.approveModal.busy') : t('frameManagementView.approveModal.confirm') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Reject -->
    <Teleport to="body">
      <div v-if="showRejectModal" class="frm-overlay" @click.self="showRejectModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.rejectModal.title') }}</h3>
            <button class="frm-modal-close" @click="showRejectModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <p v-if="selectedInvitation">
              {{ t('frameManagementView.rejectModal.body') }} <strong>{{ selectedInvitation.initiator_name }}</strong>?
            </p>
            <label class="frm-field">
              <span class="frm-field-label">{{ t('frameManagementView.rejectModal.reasonLabel') }}</span>
              <textarea v-model="rejectReason" class="frm-input" rows="3" :placeholder="t('frameManagementView.rejectModal.reasonPlaceholder')"></textarea>
            </label>
            <div class="frm-modal-actions">
              <button class="frm-btn frm-btn--ghost" @click="showRejectModal = false">{{ t('frameManagementView.rejectModal.cancel') }}</button>
              <button class="frm-btn frm-btn--red" :disabled="actionBusy || !rejectReason.trim()" @click="rejectInvitation">
                {{ actionBusy ? t('frameManagementView.rejectModal.busy') : t('frameManagementView.rejectModal.confirm') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Revoke -->
    <Teleport to="body">
      <div v-if="showRevokeModal" class="frm-overlay" @click.self="showRevokeModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.revokeModal.title') }}</h3>
            <button class="frm-modal-close" @click="showRevokeModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <div class="frm-danger-banner">
              {{ t('frameManagementView.revokeModal.danger') }}
            </div>
            <p v-if="selectedPeer">
              {{ t('frameManagementView.revokeModal.body') }} <strong>{{ selectedPeer.name }}</strong> (<code>{{ selectedPeer.trust_domain }}</code>).
            </p>
            <label class="frm-field">
              <span class="frm-field-label">{{ t('frameManagementView.revokeModal.reasonLabel') }}</span>
              <input v-model="revokeReason" class="frm-input" :placeholder="t('frameManagementView.revokeModal.reasonPlaceholder')" />
            </label>
            <div class="frm-modal-actions">
              <button class="frm-btn frm-btn--ghost" @click="showRevokeModal = false">{{ t('frameManagementView.revokeModal.cancel') }}</button>
              <button class="frm-btn frm-btn--red" :disabled="actionBusy || !revokeReason.trim()" @click="revokeFrame">
                {{ actionBusy ? t('frameManagementView.revokeModal.busy') : t('frameManagementView.revokeModal.confirm') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Resync -->
    <Teleport to="body">
      <div v-if="showResyncModal" class="frm-overlay" @click.self="showResyncModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.resyncModal.title') }}</h3>
            <button class="frm-modal-close" @click="showResyncModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <p v-if="selectedPeer">
              {{ t('frameManagementView.resyncModal.body') }} <strong>{{ selectedPeer.name }}</strong> (<code>{{ selectedPeer.trust_domain }}</code>).
            </p>
            <p class="frm-help-footnote">
              {{ t('frameManagementView.resyncModal.footnote') }}
            </p>
            <div class="frm-modal-actions">
              <button class="frm-btn frm-btn--ghost" @click="showResyncModal = false">{{ t('frameManagementView.resyncModal.cancel') }}</button>
              <button class="frm-btn frm-btn--cyan" :disabled="actionBusy" @click="resyncFrame">
                {{ actionBusy ? t('frameManagementView.resyncModal.busy') : t('frameManagementView.resyncModal.confirm') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Lifecycle -->
    <Teleport to="body">
      <div v-if="showLifecycleModal && selectedPeer" class="frm-overlay" @click.self="showLifecycleModal = false">
        <div class="frm-modal frm-modal--wide">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.lifecycleModal.title') }} — {{ selectedPeer.name }}</h3>
            <button class="frm-modal-close" @click="showLifecycleModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <div v-if="selectedPeer.drift_flags && selectedPeer.drift_flags.length > 0" class="frm-drift-pane">
              <strong><Icon name="mdi:alert" /> {{ selectedPeer.drift_flags.length }} {{ t('frameManagementView.lifecycleModal.driftFlags') }}</strong>
              <ul>
                <li v-for="flag in selectedPeer.drift_flags" :key="flag">
                  <code>{{ flag }}</code> — {{ driftLabel(flag) }}
                </li>
              </ul>
            </div>

            <div class="frm-lc-stack">
              <!-- Layer 1: Invitation -->
              <div class="frm-lc-layer">
                <div class="frm-lc-tag">{{ t('frameManagementView.lifecycleModal.tagInvitation') }}</div>
                <div class="frm-lc-body">
                  <template v-if="invitations.find(i => i.peer_registry_id === selectedPeer!.id)">
                    <span>id: <code>{{ shortId(invitations.find(i => i.peer_registry_id === selectedPeer!.id)!.id) }}</code></span>
                    <span class="frm-pill" :class="statusPillClass(invitations.find(i => i.peer_registry_id === selectedPeer!.id)!.status)">
                      {{ invitations.find(i => i.peer_registry_id === selectedPeer!.id)!.status }}
                    </span>
                    <span v-if="invitations.find(i => i.peer_registry_id === selectedPeer!.id)!.reviewed_by">
                      {{ t('frameManagementView.lifecycleModal.reviewedBy') }} #{{ invitations.find(i => i.peer_registry_id === selectedPeer!.id)!.reviewed_by }}
                    </span>
                  </template>
                  <em v-else>{{ t('frameManagementView.lifecycleModal.noInvitation') }}</em>
                </div>
              </div>

              <!-- Layer 2: Peer Registry -->
              <div class="frm-lc-layer">
                <div class="frm-lc-tag">{{ t('frameManagementView.lifecycleModal.tagPeerRegistry') }}</div>
                <div class="frm-lc-body">
                  <span>peer:{{ selectedPeer.id }}</span>
                  <code>{{ selectedPeer.base_url }}</code>
                  <span class="frm-pill" :class="statusPillClass(selectedPeer.status)">{{ selectedPeer.status }}</span>
                  <span>{{ t('frameManagementView.lifecycleModal.registered') }} {{ timeAgo(selectedPeer.registered_at) }}</span>
                </div>
              </div>

              <!-- Layer 3: SPIRE Trust Bundle -->
              <div class="frm-lc-layer">
                <div class="frm-lc-tag">{{ t('frameManagementView.lifecycleModal.tagSpire') }}</div>
                <div class="frm-lc-body">
                  <code>spiffe://{{ selectedPeer.trust_domain }}</code>
                  <span v-if="selectedPeer.spire_bundle_active === true" class="frm-pill frm-pill--active">{{ t('frameManagementView.lifecycleModal.pillActive') }}</span>
                  <span v-else-if="selectedPeer.spire_bundle_active === false" class="frm-pill frm-pill--revoked">{{ t('frameManagementView.lifecycleModal.pillMissing') }}</span>
                  <span v-else class="frm-pill frm-pill--pending">{{ t('frameManagementView.lifecycleModal.pillUnknown') }}</span>
                </div>
                <div v-if="selectedPeer.spire_bundle_active === false" class="frm-lc-subtext">
                  {{ t('frameManagementView.lifecycleModal.spireMissing') }}
                </div>
                <div v-else-if="selectedPeer.spire_bundle_active === true" class="frm-lc-subtext">
                  {{ t('frameManagementView.lifecycleModal.spireLive') }}
                </div>
                <div v-else class="frm-lc-subtext">
                  {{ t('frameManagementView.lifecycleModal.spireUnavailable') }}
                </div>
                <div v-if="selectedPeer.spiffe_bundle_endpoint_url" class="frm-lc-subtext">
                  endpoint: <code>{{ selectedPeer.spiffe_bundle_endpoint_url }}</code>
                </div>
              </div>

              <!-- Layer 4: Cross-Frame Peer (SF-4) -->
              <div class="frm-lc-layer">
                <div class="frm-lc-tag">{{ t('frameManagementView.lifecycleModal.tagSf4') }}</div>
                <div class="frm-lc-body">
                  <span class="frm-pill" :class="{
                    'frm-pill--active': sf4StatusFor(selectedPeer) === 'registered',
                    'frm-pill--suspended': sf4StatusFor(selectedPeer) === 'suspended',
                    'frm-pill--revoked': sf4StatusFor(selectedPeer) === 'missing',
                  }">{{ sf4StatusFor(selectedPeer) }}</span>
                  <span v-if="sf4WatermarkFor(selectedPeer)">
                    {{ t('frameManagementView.lifecycleModal.sf4Watermark') }} {{ timeAgo(sf4WatermarkFor(selectedPeer)) }}
                  </span>
                  <span v-else class="frm-muted">{{ t('frameManagementView.lifecycleModal.sf4NoEvents') }}</span>
                </div>
              </div>

              <!-- Layer 5: Federation Operator (SF-5) -->
              <div class="frm-lc-layer">
                <div class="frm-lc-tag">{{ t('frameManagementView.lifecycleModal.tagSf5') }}</div>
                <div class="frm-lc-body">
                  <span class="frm-pill" :class="{
                    'frm-pill--active': sf5StatusFor(selectedPeer) === 'registered',
                    'frm-pill--suspended': sf5StatusFor(selectedPeer) === 'suspended',
                    'frm-pill--revoked': sf5StatusFor(selectedPeer) === 'missing',
                  }">{{ sf5StatusFor(selectedPeer) }}</span>
                  <template v-if="federationOperators.find(o => (o.spiffe_id || '').replace(/^spiffe:\/\//, '') === selectedPeer!.trust_domain)">
                    <span>{{ t('frameManagementView.lifecycleModal.sf5Trust') }} {{
                      (federationOperators.find(o => (o.spiffe_id || '').replace(/^spiffe:\/\//, '') === selectedPeer!.trust_domain)!.bayesian_discount * 100).toFixed(1)
                    }}%</span>
                    <span>{{ federationOperators.find(o => (o.spiffe_id || '').replace(/^spiffe:\/\//, '') === selectedPeer!.trust_domain)!.event_count }} {{ t('frameManagementView.lifecycleModal.sf5Events') }}</span>
                  </template>
                </div>
              </div>
            </div>

            <div class="frm-modal-actions">
              <button class="frm-btn frm-btn--amber" @click="showLifecycleModal = false; openResync(selectedPeer)">{{ t('frameManagementView.lifecycleModal.resync') }}</button>
              <button v-if="(selectedPeer.status || '').toUpperCase() === 'ACTIVE'"
                      class="frm-btn frm-btn--red" @click="showLifecycleModal = false; openRevoke(selectedPeer)">{{ t('frameManagementView.lifecycleModal.revoke') }}</button>
              <button class="frm-btn frm-btn--ghost" @click="showLifecycleModal = false">{{ t('frameManagementView.lifecycleModal.close') }}</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Invite help -->
    <Teleport to="body">
      <div v-if="showInviteHelpModal" class="frm-overlay" @click.self="showInviteHelpModal = false">
        <div class="frm-modal frm-modal--wide">
          <header class="frm-modal-head">
            <h3>{{ t('frameManagementView.helpModal.title') }}</h3>
            <button class="frm-modal-close" @click="showInviteHelpModal = false">&times;</button>
          </header>
          <div class="frm-modal-body frm-help-body">
            <p>
              <strong>Sovereign frames</strong> federate through a bilateral SPIRE trust bundle exchange. Approving an
              invitation also issues the joining frame a federation licence, delivered in the finalize callback; each
              frame keeps its own ledger, currency and trust domain.
            </p>
            <h4>Remote frame initiates:</h4>
            <pre class="frm-code"><code>POST {{ consoleOrigin }}/api/v1/federation/frame-invitations
Content-Type: application/json

{
  "trust_domain": "frame.example.org",
  "bundle_endpoint_url": "https://frame.example.org:8444/",
  "federation_endpoint_url": "https://frame.example.org:8443",
  "event_store_url": "https://frame.example.org:8445",
  "name": "Example Frame",
  "contact_email": "admin@example.org",
  "description": "Research network, 50 agents.",
  "initiator_nonce": "&lt;32 hex chars, stored locally&gt;"
}</code></pre>
            <p>
              A frame stood up from the frame kit sends this with <code>frame-federate.py</code>, after it has trusted
              this frame's bundle; the kit's <code>PUBLIC_DOCS/FRAME_FEDERATION.md</code> lists every call both frames make.
            </p>
            <h4>You approve → we auto-wire 5 planes:</h4>
            <ol>
              <li>Fetch their SPIRE bundle + import to our SPIRE</li>
              <li>INSERT peer_registries row (peer_type='frame')</li>
              <li>Issue their federation licence, then POST back to their /finalize with our bundle, the nonce echo and the licence</li>
              <li>Register SF-4 cross-frame peer → EventStore starts replicating their events</li>
              <li>Register SF-5 federation_operator → cross-frame votes weight correctly</li>
            </ol>
            <h4>Partial success?</h4>
            <p>
              Use the <strong>Resync</strong> action on a frame row to re-run steps 4+5.
              Safe to run multiple times — idempotent UPSERTs on EventStore side.
            </p>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Provision a frame through the host frame runner (§FRAMEPROV P3) -->
    <Teleport to="body">
      <div v-if="showProvisionModal && canPlatform" class="frm-overlay" @click.self="showProvisionModal = false">
        <div class="frm-modal fmp-modal" data-testid="fmp-provision-modal">
          <div class="frm-modal-head">
            <h3>// PROVISION SOVEREIGN FRAME</h3>
            <button class="frm-modal-close" @click="showProvisionModal = false">&times;</button>
          </div>
          <div class="frm-modal-body">
            <div class="fmp-form">
              <label>Frame name<span>a-z, 0-9 and '-': names its stack, containers and hostnames</span>
                <input v-model="form.name" class="fmp-lower" type="text" spellcheck="false" autocomplete="off" data-testid="fmp-f-name" />
              </label>
              <label>Display name<span>shown on the signed registry card</span>
                <input v-model="form.frame_label" type="text" data-testid="fmp-f-label" />
              </label>
              <label>Currency ticker<span>capital letters</span>
                <input v-model="form.ticker" class="fmp-upper" type="text" spellcheck="false" autocomplete="off" data-testid="fmp-f-ticker" />
              </label>
              <label>Currency name
                <input v-model="form.currency_name" type="text" data-testid="fmp-f-currency" />
              </label>
              <label>Treasury issuance<span>whole units, issued once after the emission gate passes</span>
                <input v-model.number="form.mint" type="number" min="1" step="1" data-testid="fmp-f-mint" />
              </label>
              <label>Theme<span>the card's mark and palette</span>
                <select v-model="form.theme" data-testid="fmp-f-theme">
                  <option value="neural">neural</option>
                  <option value="sovereign">sovereign</option>
                </select>
              </label>
              <label class="fmp-form-wide">Description<span>the registry card's description</span>
                <textarea v-model="form.description" rows="3" data-testid="fmp-f-description"></textarea>
              </label>
              <label>Operator<span>who runs it, as the card says</span>
                <input v-model="form.operator_label" type="text" data-testid="fmp-f-operator" />
              </label>
              <label>Location<span>a real place name</span>
                <input v-model="form.location_label" type="text" data-testid="fmp-f-location" />
              </label>
              <label>Latitude<span>declared, never invented</span>
                <input v-model.number="form.lat" type="number" step="any" min="-90" max="90" data-testid="fmp-f-lat" />
              </label>
              <label>Longitude<span>declared, never invented</span>
                <input v-model.number="form.lng" type="number" step="any" min="-180" max="180" data-testid="fmp-f-lng" />
              </label>
              <label>Website<span>optional, https://</span>
                <input v-model="form.website" type="text" spellcheck="false" data-testid="fmp-f-website" />
              </label>
              <label>Registry image<span>allowlisted on the host</span>
                <select v-model="form.registry_image" data-testid="fmp-f-registry-image">
                  <option v-for="img in runnerInfo?.images.registry || []" :key="img" :value="img">{{ img }}</option>
                </select>
              </label>
              <label>TEG image<span>allowlisted on the host</span>
                <select v-model="form.teg_image" data-testid="fmp-f-teg-image">
                  <option v-for="img in runnerInfo?.images.teg || []" :key="img" :value="img">{{ img }}</option>
                </select>
              </label>
            </div>

            <div v-if="planResult" class="fmp-plan" data-testid="fmp-plan">
              <div class="fmp-done-head" :class="{ 'fmp-done-head--bad': !planResult.plan_ok }">
                <Icon :name="planResult.plan_ok ? 'mdi:check-circle' : 'mdi:alert-circle'" :size="16" />
                <span>{{ planResult.plan_ok ? 'The plan passed' : 'The plan refused' }}{{ planIsStale ? ', for an earlier version of this form' : '' }}</span>
              </div>
              <ul v-if="(planResult.plan?.refusals || []).length" class="fmp-plan-list fmp-plan-list--bad">
                <li v-for="(line, i) in planResult.plan?.refusals || []" :key="'r' + i">{{ line }}</li>
              </ul>
              <ul v-if="(planResult.plan?.warnings || []).length" class="fmp-plan-list fmp-plan-list--warn">
                <li v-for="(line, i) in planResult.plan?.warnings || []" :key="'w' + i">{{ line }}</li>
              </ul>
              <dl v-if="planRows.length" class="fmp-kv">
                <template v-for="[k, v] in planRows" :key="k">
                  <dt>{{ k }}</dt>
                  <dd><code>{{ v }}</code></dd>
                </template>
              </dl>
              <pre v-if="!planResult.plan && planResult.stderr_tail" class="fmp-log">{{ planResult.stderr_tail }}</pre>
            </div>

            <p class="fmp-note">
              A plan is read-only; Start stays off until a plan passed for exactly what this form says. A standup
              takes about three minutes.
            </p>
          </div>
          <div class="frm-modal-foot">
            <button class="fmp-btn" @click="showProvisionModal = false">Cancel</button>
            <button class="fmp-btn" :disabled="planning || starting || !coordsDeclared" data-testid="fmp-plan-btn" @click="checkPlan()">
              {{ planning ? 'Planning…' : 'Check plan' }}
            </button>
            <button class="fmp-btn fmp-btn--primary" :disabled="!planPassedForForm || starting || planning" data-testid="fmp-start" @click="startStandup()">
              {{ starting ? 'Starting…' : 'Start standup' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Tear down a frame the runner built -->
    <Teleport to="body">
      <div v-if="teardownTarget" class="frm-overlay" @click.self="teardownTarget = null">
        <div class="frm-modal" data-testid="fmp-teardown-modal">
          <div class="frm-modal-head">
            <h3>// TEAR DOWN {{ teardownTarget.name.toUpperCase() }}</h3>
            <button class="frm-modal-close" @click="teardownTarget = null">&times;</button>
          </div>
          <div class="frm-modal-body">
            <p>
              Removes {{ teardownTarget.spec?.frame_label || teardownTarget.name }}: its containers, volumes,
              stack directory and vhosts.
            </p>
            <p class="fmp-note">
              The runner tears down only a frame it built, and never a name on the host's protected list.
            </p>
            <div class="fmp-form fmp-form--single">
              <label>Type the frame name to confirm
                <input v-model="teardownTyped" type="text" spellcheck="false" autocomplete="off" data-testid="fmp-teardown-typed" />
              </label>
            </div>
          </div>
          <div class="frm-modal-foot">
            <button class="fmp-btn" @click="teardownTarget = null">Cancel</button>
            <button class="fmp-btn fmp-btn--danger" :disabled="teardownTyped.trim() !== teardownTarget.name" data-testid="fmp-teardown-confirm" @click="confirmTeardown()">
              Tear down
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Hand the new frame's admin credential over, once -->
    <Teleport to="body">
      <div v-if="revealTarget" class="frm-overlay" @click.self="dismissReveal()">
        <div class="frm-modal" data-testid="fmp-reveal-modal">
          <div class="frm-modal-head">
            <h3>// ADMIN CREDENTIAL · {{ revealTarget.name.toUpperCase() }}</h3>
            <button v-if="!revealed" class="frm-modal-close" @click="dismissReveal()">&times;</button>
          </div>
          <div v-if="!revealed" class="frm-modal-body">
            <p>
              This shows the new frame's admin email and password once. The runner deletes its copy as it
              answers, so this page cannot show them again.
            </p>
            <p class="fmp-note">Store them before closing. The frame's own env on the host still holds the password.</p>
          </div>
          <div v-else class="frm-modal-body">
            <dl class="fmp-kv fmp-secret">
              <dt>Console</dt>
              <dd><a :href="revealed.console" target="_blank" rel="noopener">{{ revealed.console }}</a></dd>
              <dt>Email</dt>
              <dd>
                <code>{{ revealed.admin_email }}</code>
                <button class="fmp-loglink" @click="copyText(revealed.admin_email)"><Icon name="mdi:content-copy" :size="12" /> copy</button>
              </dd>
              <dt>Password</dt>
              <dd>
                <code data-testid="fmp-reveal-password">{{ revealed.admin_password }}</code>
                <button class="fmp-loglink" @click="copyText(revealed.admin_password)"><Icon name="mdi:content-copy" :size="12" /> copy</button>
              </dd>
            </dl>
            <p class="fmp-note">Shown once. When this dialog closes the page forgets it.</p>
          </div>
          <div class="frm-modal-foot">
            <template v-if="!revealed">
              <button class="fmp-btn" @click="dismissReveal()">Cancel</button>
              <button class="fmp-btn fmp-btn--primary" :disabled="revealing" data-testid="fmp-reveal-confirm" @click="confirmReveal()">
                {{ revealing ? 'Handing over…' : 'Show it once' }}
              </button>
            </template>
            <button v-else class="fmp-btn fmp-btn--primary" data-testid="fmp-reveal-done" @click="closeReveal()">I stored it</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
    <!-- §FRAMELIC: issue a frame licence -->
    <Teleport to="body">
      <div v-if="showIssueLicenseModal" class="frm-overlay" @click.self="showIssueLicenseModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>Issue frame federation licence</h3>
            <button class="frm-modal-close" @click="showIssueLicenseModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <label class="frm-field-label">Frame name</label>
            <input v-model="newFrameLicense.frame_name" class="frm-input" data-testid="frm-lic-name"
                   placeholder="ASIA" />
            <label class="frm-field-label">Trust domain</label>
            <input v-model="newFrameLicense.trust_domain" class="frm-input" data-testid="frm-lic-td"
                   placeholder="asia.theprotocol.cloud" />
            <label for="framemanagement-sel-2083" class="frm-field-label">Tier</label>
            <select id="framemanagement-sel-2083" v-model="newFrameLicense.federation_tier" class="frm-input">
              <option value="sovereign">sovereign</option>
              <option value="standard">standard</option>
              <option value="enterprise">enterprise</option>
            </select>
            <p class="frm-muted">The key appears once on the next screen. Store it before closing.</p>
          </div>
          <footer class="frm-modal-actions">
            <button class="frm-btn frm-btn--ghost" @click="showIssueLicenseModal = false">Cancel</button>
            <button class="frm-btn frm-btn--cyan" data-testid="frm-lic-submit"
                    :disabled="licenseBusy || !newFrameLicense.frame_name.trim() || !newFrameLicense.trust_domain.trim()"
                    @click="submitIssueLicense">{{ licenseBusy ? 'Issuing…' : 'Issue' }}</button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- §FRAMELIC: the key, once -->
    <Teleport to="body">
      <div v-if="showLicenseKeyModal" class="frm-overlay" @click.self="showLicenseKeyModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3>Licence key — shown once</h3>
            <button class="frm-modal-close" @click="showLicenseKeyModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <p>Give this to the joining frame as <code>FEDERATION_LICENSE_KEY</code>. We stored only
               its hash, so it cannot be recovered — a lost key is re-issued, never recalled.</p>
            <pre class="frm-key" data-testid="frm-lic-key">{{ issuedKey }}</pre>
          </div>
          <footer class="frm-modal-actions">
            <button class="frm-btn frm-btn--cyan" @click="showLicenseKeyModal = false">I have stored it</button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- §FRAMELIC: revoke / suspend / reinstate -->
    <Teleport to="body">
      <div v-if="showLicenseActionModal" class="frm-overlay" @click.self="showLicenseActionModal = false">
        <div class="frm-modal">
          <header class="frm-modal-head">
            <h3 class="frm-cap">{{ licenseAction }} licence</h3>
            <button class="frm-modal-close" @click="showLicenseActionModal = false">&times;</button>
          </header>
          <div class="frm-modal-body">
            <p v-if="selectedLicense">
              <strong>{{ selectedLicense.operator_name }}</strong>
              (<span class="frm-code">{{ (selectedLicense.operator_did || '').replace('spiffe://', '') }}</span>)
            </p>
            <p v-if="licenseAction === 'revoke'" class="frm-warn">
              Revoking is permanent for this key: that frame stops federating here until a NEW
              licence is issued. Its identity, its agents and its ledger are untouched.
            </p>
            <p v-else-if="licenseAction === 'suspend'" class="frm-warn">
              Suspending stops federation now and is reversible with the same key.
            </p>
            <template v-if="licenseAction !== 'reinstate'">
              <label class="frm-field-label">Reason (required, recorded)</label>
              <input v-model="licenseActionReason" class="frm-input" data-testid="frm-lic-reason" />
            </template>
          </div>
          <footer class="frm-modal-actions">
            <button class="frm-btn frm-btn--ghost" @click="showLicenseActionModal = false">Cancel</button>
            <button class="frm-btn" :class="licenseAction === 'reinstate' ? 'frm-btn--cyan' : 'frm-btn--red'"
                    data-testid="frm-lic-action-submit"
                    :disabled="licenseBusy || (licenseAction !== 'reinstate' && !licenseActionReason.trim())"
                    @click="submitLicenseAction">{{ licenseBusy ? 'Working…' : licenseAction }}</button>
          </footer>
        </div>
      </div>
    </Teleport>
</template>

<style scoped>
.frm-page { padding: 24px 32px; max-width: 1600px; margin: 0 auto; color: #e2e8f0; font-family: 'Inter', sans-serif; }

.frm-header { margin-bottom: 20px; }
.frm-title { font-size: 28px; font-weight: 700; margin: 0 0 4px; color: #f1f5f9; }
.frm-subtitle { font-size: 13px; color: #94a3b8; margin: 0; }
.frm-btn-link { background: none; border: none; color: #22d3ee; cursor: pointer; font-size: 13px; padding: 0 4px; }
.frm-btn-link:hover { color: #67e8f9; text-decoration: underline; }

.frm-drift-banner {
  background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px; padding: 10px 14px; font-size: 13px; color: #fca5a5;
  margin-bottom: 14px;
}
.frm-drift-clean {
  background: rgba(34, 197, 94, 0.06); border: 1px solid rgba(34, 197, 94, 0.2);
  border-radius: 6px; padding: 8px 14px; font-size: 12px; color: #86efac;
  margin-bottom: 14px;
}
/* FM2: per-section inline error banner with retry button. */
.frm-error-banner {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: 6px; padding: 10px 14px; font-size: 12px; color: #fca5a5;
  margin: 0 0 12px;
}
.frm-error-banner--soft {
  background: rgba(251, 191, 36, 0.06); border-color: rgba(251, 191, 36, 0.25);
  color: rgba(251, 191, 36, 0.95);
}
.frm-error-banner span { flex: 1; min-width: 0; }

.frm-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 24px; }
.frm-stat {
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.06);
  border-left: 3px solid #64748b; border-radius: 6px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.frm-stat-lbl { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8; }
.frm-stat-val { font-size: 24px; font-weight: 700; color: #f1f5f9; }
.frm-stat--violet { border-left-color: #a855f7; }
.frm-stat--green  { border-left-color: #22c55e; }
.frm-stat--amber  { border-left-color: #f59e0b; }
.frm-stat--red    { border-left-color: #ef4444; }
.frm-stat--cyan   { border-left-color: #22d3ee; }

.frm-section { margin-bottom: 28px; }

/* -- §FRAMEFORM review cards ------------------------------------------ */
.fq-empty { padding: 18px; border: 1px dashed rgba(148,163,184,0.25); border-radius: 6px; color: #94a3b8; font-size: 13px; }
.fq-empty--err { border-color: rgba(248,113,113,0.4); color: #f87171; }
.fq-list { display: flex; flex-direction: column; gap: 12px; }
.fq-card { padding: 16px; border: 1px solid rgba(148,163,184,0.18); border-radius: 8px; background: rgba(0,0,0,0.18); }
.fq-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.fq-who { font-size: 15px; font-weight: 600; color: #e2e8f0; }
.fq-sub { font-size: 12px; color: #94a3b8; margin-top: 2px; }
.fq-status { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; padding: 4px 8px; border-radius: 3px; border: 1px solid rgba(148,163,184,0.3); color: #94a3b8; white-space: nowrap; }
.fq-status--pending { border-color: rgba(251,191,36,0.5); color: #fbbf24; }
.fq-status--reviewed { border-color: rgba(56,189,248,0.5); color: #38bdf8; }
.fq-status--approved { border-color: rgba(52,211,153,0.5); color: #34d399; }
.fq-status--provisioned { border-color: rgba(74,222,128,0.5); color: #4ade80; }
.fq-status--rejected { border-color: rgba(248,113,113,0.5); color: #f87171; }
.fq-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px 16px; margin-bottom: 10px; }
.fq-grid div { min-width: 0; overflow-wrap: anywhere; font-size: 13px; color: #e2e8f0; font-family: 'IBM Plex Mono', monospace; }
.fq-grid span, .fq-changed span, .fq-text span { display: block; font-size: 9px; letter-spacing: 0.12em; color: #73839a; text-transform: uppercase; margin-bottom: 2px; }  /* §FESUITE: 4.8-5.1:1 (#64748b was 3.9-4.1:1) */
.fq-changed, .fq-text { font-size: 12px; color: #cbd5e1; line-height: 1.6; margin: 0 0 8px; white-space: pre-wrap; }
.fq-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(148,163,184,0.14); }
.fq-mail { font-size: 12px; color: #94a3b8; text-decoration: underline; margin-left: auto; }
.fq-mail:hover { color: #e2e8f0; }
.frm-section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.frm-section-title { font-size: 15px; font-weight: 600; color: #cbd5e1; margin: 0; text-transform: uppercase; letter-spacing: 0.08em; font-family: 'IBM Plex Mono', monospace; }
.frm-filter {
  background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; padding: 6px 10px; color: #e2e8f0; font-size: 12px;
  font-family: 'IBM Plex Mono', monospace;
}

.frm-table-wrap {
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px; overflow-x: auto;
}
.frm-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.frm-table th {
  text-align: left; padding: 10px 14px; font-family: 'IBM Plex Mono', monospace;
  font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.frm-table td { padding: 10px 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); color: #cbd5e1; }
.frm-table tbody tr:hover { background: rgba(15, 23, 42, 0.9); }
.frm-table code { font-family: 'IBM Plex Mono', monospace; font-size: 11px; background: rgba(0, 0, 0, 0.3); padding: 2px 5px; border-radius: 3px; }
.frm-td-url { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.frm-td-reason { font-style: italic; color: #94a3b8; font-size: 11px; }
.frm-empty-cell { text-align: center; padding: 24px; color: #73839a; font-style: italic; }
.frm-row-clickable { cursor: pointer; }
.frm-muted { color: #73839a; }

.frm-pill {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.05em;
  border: 1px solid rgba(148, 163, 184, 0.25); background: rgba(148, 163, 184, 0.12); color: #cbd5e1;
}
.frm-pill--active    { background: rgba(34, 197, 94, 0.15);  color: #86efac; border-color: rgba(34, 197, 94, 0.3); }
.frm-pill--pending   { background: rgba(245, 158, 11, 0.15); color: #fcd34d; border-color: rgba(245, 158, 11, 0.3); }
.frm-pill--approved  { background: rgba(34, 211, 238, 0.15); color: #67e8f9; border-color: rgba(34, 211, 238, 0.3); }
.frm-pill--suspended { background: rgba(234, 179, 8, 0.15);  color: #fde047; border-color: rgba(234, 179, 8, 0.3); }
.frm-pill--revoked   { background: rgba(239, 68, 68, 0.15);  color: #fca5a5; border-color: rgba(239, 68, 68, 0.3); }
.frm-pill--drift     { background: rgba(239, 68, 68, 0.2);   color: #f87171; border-color: rgba(239, 68, 68, 0.4); cursor: help; }

.frm-btn {
  display: inline-block; padding: 4px 10px; border-radius: 4px;
  font-size: 11px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.03em;
  border: 1px solid rgba(255, 255, 255, 0.1); background: transparent;
  color: #e2e8f0; cursor: pointer; margin-right: 4px;
}
.frm-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.05); }
.frm-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.frm-btn--green { background: rgba(34, 197, 94, 0.12); color: #86efac; border-color: rgba(34, 197, 94, 0.3); }
.frm-btn--red   { background: rgba(239, 68, 68, 0.12); color: #f87171; border-color: rgba(239, 68, 68, 0.3); }
.frm-btn--amber { background: rgba(245, 158, 11, 0.12); color: #fcd34d; border-color: rgba(245, 158, 11, 0.3); }
.frm-btn--cyan  { background: rgba(34, 211, 238, 0.12); color: #67e8f9; border-color: rgba(34, 211, 238, 0.3); }
.frm-btn--ghost { color: #94a3b8; }

.frm-spire-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; padding: 14px; }
.frm-spire-cell {
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px; padding: 10px 12px; font-size: 12px;
}
.frm-spire-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.05em; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; }
.frm-spire-cell ul { margin: 4px 0; padding-left: 16px; list-style: none; }
.frm-spire-cell li { padding: 2px 0; }
.frm-spire-cell--warn { border-color: rgba(245, 158, 11, 0.3); background: rgba(245, 158, 11, 0.05); }
.frm-spire-cell--error { border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.06); color: #fca5a5; }

/* Modals */
.frm-overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 9999; padding: 20px;
}
.frm-modal {
  background: #0f172a; border: 1px solid rgba(0, 210, 210, 0.2);
  border-radius: 10px; width: min(520px, 95vw); max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
}
.frm-modal--wide { width: min(820px, 95vw); }
.frm-modal-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.frm-modal-head h3 { margin: 0; font-size: 15px; color: #f1f5f9; }
.frm-modal-close {
  background: none; border: none; color: #94a3b8; font-size: 24px; line-height: 1; cursor: pointer;
  padding: 0 6px;
}
.frm-modal-close:hover { color: #e2e8f0; }
.frm-modal-body { padding: 16px 18px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; color: #cbd5e1; font-size: 13px; }
.frm-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255, 255, 255, 0.06); }
.frm-field { display: flex; flex-direction: column; gap: 4px; }
.frm-field-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.05em; text-transform: uppercase; color: #94a3b8; }
.frm-input {
  background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; padding: 8px 10px; color: #e2e8f0; font-size: 13px;
  font-family: 'IBM Plex Mono', monospace; resize: vertical;
}
.frm-input:focus { outline: none; border-color: #22d3ee; }

.frm-danger-banner {
  background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 4px; padding: 10px 12px; font-size: 12px; color: #fca5a5;
}

.frm-approve-steps { font-size: 12px; color: #94a3b8; }
.frm-approve-steps ol { margin: 6px 0 0; padding-left: 20px; }
.frm-approve-steps li { margin: 3px 0; }

.frm-help-body { font-size: 13px; color: #cbd5e1; line-height: 1.55; }
.frm-help-body h4 { font-size: 12px; font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.06em; color: #22d3ee; margin: 12px 0 4px; }
.frm-help-body code { background: rgba(0, 0, 0, 0.3); padding: 1px 5px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
.frm-help-body ol, .frm-help-body ul { margin: 6px 0; padding-left: 20px; }
.frm-help-body li { margin: 3px 0; }
.frm-help-footnote { margin-top: 8px; font-size: 11px; color: #94a3b8; font-style: italic; }
.frm-code { background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 4px; padding: 10px 12px; font-size: 11px; color: #cbd5e1; overflow-x: auto; }

.frm-drift-pane {
  background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 4px; padding: 10px 12px; font-size: 12px; color: #fca5a5;
}
.frm-drift-pane ul { margin: 4px 0; padding-left: 20px; }

.frm-lc-stack { display: flex; flex-direction: column; gap: 8px; }
.frm-lc-layer { background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 4px; padding: 10px 12px; }
.frm-lc-tag { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; color: #22d3ee; margin-bottom: 6px; }
.frm-lc-body { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; }
.frm-lc-subtext { margin-top: 6px; font-size: 11px; color: #94a3b8; }
.frm-lc-body code, .frm-lc-subtext code { font-family: 'IBM Plex Mono', monospace; background: rgba(0, 0, 0, 0.3); padding: 2px 5px; border-radius: 3px; font-size: 10px; }

@media (max-width: 900px) {
  .frm-stats { grid-template-columns: repeat(2, 1fr); }
  .frm-table-wrap { font-size: 11px; }
  .frm-modal--wide { width: 95vw; }
}

/* ─── Provisioned frames panel (§2026-07-29) ─────────────────────────── */
.fmp-frames { margin-top: 14px; border: 1px solid rgba(148,163,184,0.16); border-radius: 10px; overflow: hidden; }
.fmp-frames-head { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 14px;
  background: rgba(148,163,184,0.06); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #cbd5e1; }
.fmp-frames-sub { font-size: 11px; letter-spacing: .04em; text-transform: none; color: #94a3b8; }
.fmp-frame { display: flex; align-items: center; gap: 16px; padding: 12px 14px; border-top: 1px solid rgba(148,163,184,0.1); flex-wrap: wrap; }
.fmp-frame-id { display: flex; align-items: center; gap: 10px; min-width: 240px; flex: 1; }
.fmp-frame-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.fmp-frame-dot.is-up { background: #4ade80; box-shadow: 0 0 8px rgba(74,222,128,0.7); }
.fmp-frame-dot.is-down { background: #64748b; }
.fmp-frame-name { font-size: 14px; font-weight: 600; color: #f1f5f9; }
.fmp-frame-meta { display: flex; align-items: center; gap: 8px; margin-top: 2px; }
.fmp-frame-meta code { font-size: 11px; color: #94a3b8; }
.fmp-frame-ticker { font-size: 10px; padding: 1px 6px; border-radius: 4px; color: #fbbf24; border: 1px solid rgba(251,191,36,0.35); }
.fmp-frame-state { display: flex; align-items: center; gap: 12px; min-width: 240px; }
.fmp-frame-pill { font-size: 10px; font-weight: 700; letter-spacing: .08em; padding: 2px 8px; border-radius: 4px; }
.fmp-frame-pill.is-up { color: #4ade80; border: 1px solid rgba(74,222,128,0.4); }
.fmp-frame-pill.is-down { color: #94a3b8; border: 1px solid rgba(148,163,184,0.3); }
.fmp-frame-count { font-size: 12px; color: #94a3b8; font-variant-numeric: tabular-nums; }
.fmp-frame-link { font-size: 12px; color: #22d3ee; text-decoration: none; display: inline-flex; align-items: center; gap: 3px; }
.fmp-frame-actions { margin-left: auto; display: flex; gap: 8px; }
.fmp-btn--start { color: #4ade80; border-color: rgba(74,222,128,0.4); }
.fmp-btn--start:hover:not(:disabled) { background: rgba(74,222,128,0.08); border-color: #4ade80; }

/* ─── Provision Frame (§2026-07-27) ─────────────────────────────────── */
.fmp { border: 1px solid var(--border-color, rgba(148,163,184,0.18)); border-radius: 8px; padding: 16px; margin-bottom: 18px; background: var(--surface-1, rgba(15,23,42,0.35)); }
.fmp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.fmp-title { font-size: 14px; font-weight: 600; margin: 0 0 4px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-primary, #e2e8f0); }
.fmp-sub { font-size: 12px; color: var(--text-secondary, #94a3b8); margin: 0; max-width: 68ch; line-height: 1.5; }
.fmp-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.fmp-btn { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; padding: 6px 12px; border-radius: 4px; border: 1px solid rgba(148,163,184,0.3); background: transparent; color: var(--text-secondary, #94a3b8); cursor: pointer; letter-spacing: 0.05em; text-transform: uppercase; transition: all .15s; }
.fmp-btn:hover:not(:disabled) { border-color: rgba(148,163,184,0.6); color: #e2e8f0; }
.fmp-btn:disabled { opacity: .45; cursor: not-allowed; }
.fmp-btn--primary { color: #22d3ee; border-color: rgba(34,211,238,0.4); }
/* Start-existing: green to read as "resume", distinct from primary "create". */
.fmp-btn--start { color: #4ade80; border-color: rgba(74,222,128,0.4); }
.fmp-btn--start:hover:not(:disabled) { background: rgba(74,222,128,0.08); border-color: #4ade80; }
.fmp-btn--primary:hover:not(:disabled) { background: rgba(34,211,238,0.08); border-color: #22d3ee; }
.fmp-btn--danger { color: #f87171; border-color: rgba(248,113,113,0.4); }
.fmp-btn--danger:hover:not(:disabled) { background: rgba(248,113,113,0.08); border-color: #f87171; }

.fmp-live { margin-top: 14px; }
.fmp-stage-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.fmp-pulse { width: 8px; height: 8px; border-radius: 50%; background: #22d3ee; animation: fmp-pulse 1.2s ease-in-out infinite; flex: none; }
@keyframes fmp-pulse { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
.fmp-stage { font-size: 13px; font-weight: 600; color: #e2e8f0; }
.fmp-elapsed, .fmp-count { font-size: 11px; font-family: 'IBM Plex Mono', monospace; color: var(--text-secondary, #94a3b8); }
.fmp-count { margin-left: auto; }

.fmp-miles { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.fmp-mile { font-size: 10px; letter-spacing: .06em; text-transform: uppercase; padding: 3px 9px; border-radius: 999px; border: 1px solid rgba(148,163,184,0.25); color: var(--text-secondary, #94a3b8); }
.fmp-mile--on { border-color: rgba(16,185,129,0.55); color: #10b981; }

.fmp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px; }
.fmp-svc { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 4px; border: 1px solid rgba(148,163,184,0.16); background: rgba(15,23,42,0.4); font-size: 11px; }
.fmp-svc-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; background: #475569; }
.fmp-svc-name { color: #cbd5e1; flex: 1; }
.fmp-svc-state { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-secondary, #94a3b8); text-transform: uppercase; letter-spacing: .04em; }
.fmp-svc--ok .fmp-svc-dot { background: #10b981; }
.fmp-svc--ok .fmp-svc-state { color: #10b981; }
.fmp-svc--warn .fmp-svc-dot { background: #fbbf24; animation: fmp-pulse 1.4s ease-in-out infinite; }
.fmp-svc--warn .fmp-svc-state { color: #fbbf24; }
.fmp-svc--bad .fmp-svc-dot { background: #f87171; }
.fmp-svc--bad .fmp-svc-state { color: #f87171; }
.fmp-svc--idle { opacity: .55; }

.fmp-lastline { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-secondary, #94a3b8); margin: 10px 0 4px; overflow-wrap: anywhere; }
.fmp-loglink { background: none; border: none; color: #22d3ee; font-size: 10px; cursor: pointer; padding: 0; text-transform: uppercase; letter-spacing: .05em; }
.fmp-log { max-height: 260px; overflow: auto; background: rgba(2,6,23,0.7); border: 1px solid rgba(148,163,184,0.18); border-radius: 4px; padding: 10px; font-size: 10px; line-height: 1.5; color: #94a3b8; margin-top: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }

.fmp-done, .fmp-failed { margin-top: 14px; }
.fmp-done-head { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #10b981; margin-bottom: 10px; }
.fmp-done-head--bad { color: #f87171; }
.fmp-kv { display: grid; grid-template-columns: minmax(90px, auto) 1fr; gap: 4px 14px; margin: 0 0 10px; font-size: 11px; }
.fmp-kv dt { color: var(--text-secondary, #94a3b8); text-transform: uppercase; letter-spacing: .04em; font-size: 10px; }
.fmp-kv dd { margin: 0; overflow-wrap: anywhere; }
.fmp-kv a { color: #22d3ee; text-decoration: none; }
.fmp-kv a:hover { text-decoration: underline; }
.fmp-kv code { font-family: 'IBM Plex Mono', monospace; color: #cbd5e1; }
.fmp-next { font-size: 11px; color: var(--text-secondary, #94a3b8); line-height: 1.5; margin: 0; }
.fmp-fatal { font-size: 12px; color: #fca5a5; margin: 0 0 8px; overflow-wrap: anywhere; }
.fmp-idle { font-size: 12px; color: var(--text-secondary, #94a3b8); margin: 12px 0 0; }

.fmp-modal { width: min(680px, 94vw); }
.fmp-form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.fmp-form label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; font-weight: 600; color: #cbd5e1; text-transform: uppercase; letter-spacing: .04em; }
.fmp-form label span { font-size: 10px; font-weight: 400; text-transform: none; letter-spacing: 0; color: var(--text-secondary, #94a3b8); }
.fmp-form input[type=text], .fmp-form input[type=number] { background: rgba(2,6,23,0.6); border: 1px solid rgba(148,163,184,0.25); border-radius: 4px; padding: 7px 9px; color: #e2e8f0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; }
.fmp-form input:focus { outline: none; border-color: #22d3ee; }
.fmp-check { grid-column: 1 / -1; flex-direction: row !important; align-items: center; gap: 8px !important; text-transform: none !important; letter-spacing: 0 !important; font-weight: 400 !important; }
.fmp-check span { font-size: 11px !important; color: #cbd5e1 !important; }
.fmp-note { font-size: 11px; color: var(--text-secondary, #94a3b8); line-height: 1.5; margin: 12px 0 0; }
@media (max-width: 640px) { .fmp-form { grid-template-columns: 1fr; } .fmp-count { margin-left: 0; } }
@media (prefers-reduced-motion: reduce) { .fmp-pulse, .fmp-svc--warn .fmp-svc-dot { animation: none; } }

/* ─── Frame runner panel (§FRAMEPROV P3) ────────────────────────────── */
.fmp-steps { list-style: none; margin: 4px 0 0; padding: 0; display: grid; gap: 2px; }
.fmp-step { display: grid; grid-template-columns: 7px minmax(90px, 120px) 64px minmax(0, 1fr); align-items: baseline; gap: 10px; font-size: 11px; padding: 3px 0; }
.fmp-step .fmp-svc-dot { align-self: center; }
.fmp-step-name { font-family: 'IBM Plex Mono', monospace; color: #cbd5e1; }
.fmp-step-state { font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-secondary, #94a3b8); }
.fmp-step-sentence { color: var(--text-secondary, #94a3b8); overflow-wrap: anywhere; }
.fmp-step--done .fmp-svc-dot { background: #10b981; }
.fmp-step--done .fmp-step-state { color: #10b981; }
.fmp-step--running .fmp-svc-dot { background: #22d3ee; animation: fmp-pulse 1.2s ease-in-out infinite; }
.fmp-step--running .fmp-step-state { color: #22d3ee; }
.fmp-step--failed .fmp-svc-dot { background: #f87171; }
.fmp-step--failed .fmp-step-state, .fmp-step--failed .fmp-step-sentence { color: #fca5a5; }
.fmp-step--skipped, .fmp-step--unreached { opacity: .6; }
.fmp-frame-actions { flex-wrap: wrap; }
.fmp-select, .fmp-form select, .fmp-form textarea { background: rgba(2,6,23,0.6); border: 1px solid rgba(148,163,184,0.25); border-radius: 4px; padding: 6px 8px; color: #e2e8f0; font-size: 12px; font-family: 'IBM Plex Mono', monospace; }
.fmp-form textarea { resize: vertical; min-height: 60px; font-family: inherit; }
.fmp-select:focus, .fmp-form select:focus, .fmp-form textarea:focus { outline: none; border-color: #22d3ee; }
.fmp-form-wide { grid-column: 1 / -1; }
.fmp-form--single { grid-template-columns: 1fr; margin-top: 12px; }
.fmp-upper { text-transform: uppercase; }
.fmp-lower { text-transform: lowercase; }
.fmp-unavailable { margin-top: 12px; }
.fmp-plan { margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(148,163,184,0.14); }
.fmp-plan-list { margin: 0 0 10px; padding-left: 18px; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.fmp-plan-list--bad { color: #fca5a5; }
.fmp-plan-list--warn { color: #fcd34d; }
.fmp-jobs { margin-top: 14px; font-size: 11px; color: var(--text-secondary, #94a3b8); }
.fmp-jobs summary { cursor: pointer; text-transform: uppercase; letter-spacing: .05em; font-size: 10px; }
.fmp-jobs ul { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 4px; }
.fmp-jobs li { display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; }
.fmp-secret code { font-size: 13px; user-select: all; overflow-wrap: anywhere; }
@media (max-width: 640px) {
  .fmp-step { grid-template-columns: 7px minmax(0, 1fr) auto; }
  .fmp-step-sentence { grid-column: 2 / -1; }
  .fmp-frame-actions { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) { .fmp-step--running .fmp-svc-dot { animation: none; } }

/* §FRAMELIC (2026-09-07) — frame licence panel */
.frm-modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px;
  padding-top: 8px; border-top: 1px solid rgba(255, 255, 255, 0.06); }
.frm-warn { color: var(--nc-warning, #ffaa00); }
.frm-lic-count { margin-left: .5rem; font-size: .78rem; opacity: .72; font-weight: 400; }
.frm-td-actions { display: flex; gap: .35rem; flex-wrap: wrap; }
.frm-lic-note { margin: 0 0 .6rem; max-width: 78ch; font-size: 12px; line-height: 1.5; }
.frm-head-actions { display: flex; gap: .4rem; align-items: center; }
.frm-warn-banner {
  display: flex; align-items: center; justify-content: space-between; gap: .75rem;
  padding: .55rem .75rem; margin-bottom: .6rem; border-radius: 6px;
  border: 1px solid rgba(255, 170, 0, .45); background: rgba(255, 170, 0, .08);
}
.frm-lic-reason { margin-left: .4rem; font-size: .78em; }
.frm-key {
  padding: .6rem .75rem; border-radius: 6px; overflow-x: auto;
  background: rgba(0, 0, 0, .35); border: 1px solid rgba(255, 255, 255, .12);
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .82rem;
  word-break: break-all; white-space: pre-wrap;
}
.frm-cap { text-transform: capitalize; }
</style>
