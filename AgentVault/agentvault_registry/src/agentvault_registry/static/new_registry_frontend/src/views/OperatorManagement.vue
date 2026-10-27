<script setup lang="ts">
import { FRAME_FEATURE_SWITCHES } from '@/services/api/frameRequests'
import { ref, computed, onMounted } from 'vue'
import { safeExternalUrl } from '@/utils/safeUrl'
import { isMainframeOnlyRefusal } from '@/services/mainframeOnly'
import { apiClient } from '@/services/api/client'
import { useUIStore } from '@/stores/ui'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

const { t } = useI18n()

dayjs.extend(relativeTime)

const uiStore = useUIStore()

// ── OPM1 (audit 2026-05-07): themed confirm() helper ────────
// Promise-based wrapper around ConfirmActionModal so call sites can
// `if (!await themeConfirm({...})) return` just like native confirm().
interface ConfirmOpts {
  title: string
  message: string
  tone?: 'primary' | 'warn' | 'danger'
  confirmText?: string
  cancelText?: string
  busyText?: string
  warning?: string
  reasonOptional?: boolean
  reasonRequired?: boolean
  reasonMinLength?: number
  reasonPlaceholder?: string
}
const confirmShow = ref(false)
const confirmOpts = ref<ConfirmOpts>({ title: '', message: '' })
const confirmBusy = ref(false)
let confirmResolver: ((reason: string | null) => void) | null = null

function themeConfirm(opts: ConfirmOpts): Promise<string | null> {
  // Resolves to the captured reason on confirm (string), or null on cancel.
  // Caller checks `result !== null` for the boolean equivalent of confirm().
  if (confirmResolver) confirmResolver(null) // cancel any in-flight prompt
  confirmOpts.value = opts
  confirmShow.value = true
  confirmBusy.value = false
  return new Promise((resolve) => { confirmResolver = resolve })
}
function _onConfirmModalConfirm(reason: string) {
  if (confirmResolver) {
    const r = confirmResolver
    confirmResolver = null
    confirmShow.value = false
    r(reason ?? '')
  }
}
function _onConfirmModalClose() {
  if (confirmResolver) {
    const r = confirmResolver
    confirmResolver = null
    r(null)
  }
  confirmShow.value = false
}

// ── Config ──────────────────────────────────────────────────
const mtlsEnforced = ref(false)

// ── Operator Applications ───────────────────────────────────
interface OperatorApp {
  id: string
  developer_id: number | null
  name: string
  email: string
  organization: string | null
  deployment: string
  experience: string
  use_case: string | null
  /** §FESUITE V0595: the settings the applicant chose differently from the frame's; {} or absent = all inherited */
  env_choices?: Record<string, string>
  status: string
  reviewed_by: number | null
  reviewed_at: string | null
  review_notes: string | null
  created_at: string
  bundle_path: string | null
  bundle_generated_at: string | null
  bundle_download_count: number
  bundle_expires_at: string | null
  docker_registry_username: string | null
  spire_fingerprint: string | null
  docker_pull_token_prefix: string | null
  docker_pull_token_issued_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
  revoked_by: number | null
  // f051: Cloud hosting
  cloud_hosted: boolean
  cloud_url: string | null
  cloud_port_base: number | null
  cloud_provisioned_at: string | null
  cloud_torn_down_at: string | null
}

// §FESUITE V0595: the applicant's chosen settings as the reviewer reads them (the catalog's labels and option words)
const ENV_LABEL = new Map(FRAME_FEATURE_SWITCHES.map(sw => [sw.key, sw.label]))
function envChoiceText(app: OperatorApp): string {
  const chosen = Object.entries(app.env_choices || {})
  if (!chosen.length) return t('operatorManagementView.appTable.envInherited', 'Settings: all as the frame runs them')
  return t('operatorManagementView.appTable.envChosen', 'Settings chosen') + ': '
    + chosen.map(([k, v]) => `${ENV_LABEL.get(k) || k} ${v}`).join(', ')
}

// ── Cloud Operators ────────────────────────────────────────
interface CloudOperator {
  application_id: string
  name: string
  cloud_url: string | null
  cloud_port_base: number | null
  cloud_provisioned_at: string | null
  cloud_torn_down_at: string | null
  active: boolean
  healthy: boolean | null
  email: string
}

const cloudOperators = ref<CloudOperator[]>([])
const cloudActiveCount = ref(0)
/** §FESUITE V0577: a failed read said "No cloud operators provisioned yet" and "0/10 slots used" (the default limit) */
const cloudRead = ref<'reading' | 'read' | 'unread'>('reading')
const cloudBetaLimit = ref(10)
const cloudLoading = ref(false)
const provisioningId = ref<string | null>(null)
const teardownId = ref<string | null>(null)

// §2026-07-27 — live provisioning progress.
// The provision POST is long-running and its result is NOT a reliable verdict:
// under host load the backend's in-request orchestration outlives its DB session
// and returns 500 *after* having created the whole stack. Reporting that raw
// status would show "Provision Failed" for a provision that actually worked.
// So: keep a small live state, and after the POST settles (success OR error)
// gate the verdict on the operator's REAL health instead.
const provisionStage = ref<string>('')          // human-readable current stage
const provisionElapsed = ref(0)                 // seconds since the click
let _provisionTimer: ReturnType<typeof setInterval> | null = null

function _startProvisionClock() {
  provisionElapsed.value = 0
  _provisionTimer = setInterval(() => { provisionElapsed.value += 1 }, 1000)
}
function _stopProvisionClock() {
  if (_provisionTimer) { clearInterval(_provisionTimer); _provisionTimer = null }
}

/** Poll until the operator reports healthy. Returns true if it came up. */
async function _awaitOperatorHealthy(appId: string, maxSeconds = 300): Promise<boolean> {
  const deadline = Date.now() + maxSeconds * 1000
  while (Date.now() < deadline) {
    try {
      const res = await apiClient.get('/admin/cloud-operators')
      const ops: CloudOperator[] = res.data.operators || []
      const op = ops.find(o => o.application_id === appId)
      if (op?.healthy) { cloudOperators.value = ops; return true }
      if (op?.cloud_provisioned_at) provisionStage.value = 'containers starting'
    } catch { /* transient — keep waiting, the stack is still coming up */ }
    await new Promise(r => setTimeout(r, 5000))
  }
  return false
}

async function fetchCloudOperators() {
  cloudLoading.value = true
  try {
    const res = await apiClient.get('/admin/cloud-operators')
    cloudOperators.value = res.data.operators || []
    cloudActiveCount.value = res.data.active_count || 0
    cloudBetaLimit.value = res.data.beta_limit || 10
    cloudRead.value = 'read'
  } catch (e: any) {
    if (cloudRead.value !== 'read') cloudRead.value = 'unread'
    console.error('Failed to fetch cloud operators:', e)
  } finally {
    cloudLoading.value = false
  }
}

async function provisionCloud(appId: string) {
  // OPM1 (audit 2026-05-07): themed confirm replaces native confirm().
  const ok = await themeConfirm({
    title: '// PROVISION CLOUD REGISTRY',
    message: 'Provision a cloud-hosted registry for this operator? This takes <strong>~90 seconds</strong> and creates Docker containers + SPIRE entries + nginx config.',
    tone: 'primary',
    confirmText: 'Provision',
    busyText: 'Provisioning…',
  })
  if (ok === null) return
  provisioningId.value = appId
  provisionStage.value = 'creating stack'
  _startProvisionClock()
  let postError: string | null = null
  let cloudUrl: string | null = null
  try {
    const res = await apiClient.post(`/admin/cloud-operators/${appId}/provision`)
    cloudUrl = res.data?.cloud_url || null
  } catch (e: any) {
    // NOT a verdict — see the note on provisionStage. Remember it, then let
    // the health poll decide.
    postError = e.response?.data?.detail || e.message
  }
  try {
    provisionStage.value = 'waiting for health'
    const healthy = await _awaitOperatorHealthy(appId)
    await fetchCloudOperators()
    await loadApplications()
    if (healthy) {
      const op = cloudOperators.value.find(o => o.application_id === appId)
      uiStore.showSuccess('Cloud Provisioned', op?.cloud_url || cloudUrl || 'Registry is live')
    } else if (postError) {
      uiStore.showError('Provision Failed', postError)
    } else {
      uiStore.showError(
        'Provision Incomplete',
        'The stack was created but the registry did not report healthy in time. ' +
        'Check the operator row and its logs before retrying.',
      )
    }
  } finally {
    _stopProvisionClock()
    provisionStage.value = ''
    provisioningId.value = null
  }
}

// §pass66.6 (2026-05-23) — Restart action for cloud-hosted ops. Cloud-hosted
// ops have no shell access to Frame A's host; this gives Commander (or any
// admin_federation holder) a one-click equivalent of `tp-operator restart`
// from the operator management view. MVP defaults to restarting the
// `registry` service (highest-value case — picks up code + config changes
// + clears in-memory caches). Other services in the allowlist can be
// targeted via the CLI on the host (`tp-operator restart <service>`) until
// a service-picker is wired into ConfirmActionModal.
const restartId = ref<string | null>(null)

// §pass66.9 — Logs viewer modal state + handler
const showLogsModal = ref(false)
const logsAppId = ref<string>('')
const logsOpName = ref<string>('')
const logsService = ref<string>('registry')
const logsTail = ref<number>(200)
const logsLoading = ref(false)
const logsOutput = ref<string>('')
const logsError = ref<string>('')

function openLogsModal(appId: string, opName: string) {
  logsAppId.value = appId
  logsOpName.value = opName
  logsService.value = 'registry'
  logsTail.value = 200
  logsOutput.value = ''
  logsError.value = ''
  showLogsModal.value = true
  fetchLogs()
}

async function fetchLogs() {
  if (!logsAppId.value) return
  logsLoading.value = true
  logsError.value = ''
  try {
    const r = await apiClient.get(
      `/admin/cloud-operators/${logsAppId.value}/logs`,
      { params: { service: logsService.value, tail: logsTail.value } },
    )
    logsOutput.value = r.data.output || ''
  } catch (e: any) {
    logsError.value = e.response?.data?.detail || e.message || 'Failed to fetch logs'
    logsOutput.value = ''
  } finally {
    logsLoading.value = false
  }
}

async function restartCloud(appId: string, opName: string, service: string = 'registry') {
  const ok = await themeConfirm({
    title: '// RESTART CLOUD OPERATOR',
    message: `Restart the \`${service}\` service on ${opName}? The op's containers run on this host; this is the web equivalent of running \`tp-operator restart ${service}\` from a shell that the op admin doesn't have.`,
    tone: 'warn',
    confirmText: 'Restart',
    busyText: 'Restarting…',
    reasonRequired: false,
    warning: `${opName} will be briefly unavailable (~5-15s). Federation peers may see one or two failed requests during the bounce.`,
  })
  if (ok === null) return
  restartId.value = appId
  try {
    const r = await apiClient.post(`/admin/cloud-operators/${appId}/restart-service`, { service })
    uiStore.showSuccess(
      'Restarted',
      `${opName} :: ${r.data.service} bounced in ${r.data.duration_ms}ms`,
    )
    await fetchCloudOperators()
  } catch (e: any) {
    uiStore.showError('Restart Failed', e.response?.data?.detail || e.message)
  } finally {
    restartId.value = null
  }
}

async function teardownCloud(appId: string) {
  // OPM1: themed confirm with required reason replaces native prompt().
  const reason = await themeConfirm({
    title: '// TEARDOWN CLOUD OPERATOR',
    message: 'Teardown the cloud-hosted registry for this operator? Removes the Docker stack + nginx route + SPIRE entries.',
    tone: 'danger',
    confirmText: 'Teardown',
    busyText: 'Tearing down…',
    reasonRequired: true,
    reasonMinLength: 10,
    reasonPlaceholder: 'Why is this operator being torn down?',
    warning: 'Existing federation links to this operator will start failing immediately.',
  })
  if (reason === null) return
  teardownId.value = appId
  try {
    await apiClient.post(`/admin/cloud-operators/${appId}/teardown`, { reason })
    uiStore.showSuccess('Torn Down', 'Cloud operator has been removed')
    await fetchCloudOperators()
    await loadApplications()
  } catch (e: any) {
    uiStore.showError('Teardown Failed', e.response?.data?.detail || e.message)
  } finally {
    teardownId.value = null
  }
}

// ── All Operators Health (from stack-health) ───────────────
interface OperatorHealth {
  name: string
  status: string
  ms: number
}
const allOperatorHealth = ref<OperatorHealth[]>([])

async function fetchAllOperatorHealth() {
  // OPM2 (audit 2026-05-07): /stack-health is a single backend-aggregated
  // endpoint (the backend fans out to 11 operators server-side), but with no
  // per-request timeout it could stall the whole dashboard if the backend
  // hangs. 8s cap via AbortController — admin dashboard prefers stale data
  // over a hung page.
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 8000)
  try {
    const res = await apiClient.get('/stack-health', { signal: controller.signal })
    allOperatorHealth.value = (res.data.services || [])
      .filter((s: any) => s.group === 'operator')
      .sort((a: any, b: any) => a.name.localeCompare(b.name))
  } catch { /* non-fatal — keep stale data */ }
  finally { clearTimeout(timeout) }
}

const showEmails = ref(false)
function redactEmail(email: string): string {
  if (!email) return '—'
  const [local, domain] = email.split('@')
  if (!domain) return '••••@••••'
  return local.substring(0, 2) + '••••@' + domain
}

const applications = ref<OperatorApp[]>([])
/** §FESUITE (the loading sweep): the tables say "none" only after the applications' own read came back */
const appsRead = ref<'reading' | 'read' | 'unread'>('reading')
const applicationFilter = ref('all')

const filteredApplications = computed(() => {
  if (applicationFilter.value === 'all') return applications.value
  return applications.value.filter(a => a.status === applicationFilter.value)
})

// ── Licenses ────────────────────────────────────────────────
interface License {
  id: string
  operator_name: string
  operator_did: string
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

const licenses = ref<License[]>([])
const licenseFilter = ref('all')
const licenseLoading = ref(false)
/** §FESUITE V0577: a failed read said "No licenses found — generate one to start federating" under counts of 0 */
const licensesRead = ref<'reading' | 'read' | 'unread'>('reading')
const expandedLicenseId = ref<string | null>(null)

const filteredLicenses = computed(() => {
  if (licenseFilter.value === 'all') return licenses.value
  return licenses.value.filter(l => l.status === licenseFilter.value)
})

// ── Modal State ─────────────────────────────────────────────
const showRejectModal = ref(false)
const showSuspendModal = ref(false)
const showRevokeOperatorModal = ref(false)
const showGenerateModal = ref(false)
const showKeyDisplay = ref(false)
const showRevokeLicenseModal = ref(false)

const selectedApp = ref<OperatorApp | null>(null)
const selectedAppForAction = ref<OperatorApp | null>(null)
const selectedLicenseForRevoke = ref<License | null>(null)

const rejectReason = ref('')
const actionReason = ref('')
const revokeReason = ref('')
const generatedKey = ref('')
const loading = ref(false)

const newLicense = ref({
  operator_name: '',
  operator_did: '',
  federation_tier: 'standard',
  min_image_version: ''
})

// ── Data Loading ────────────────────────────────────────────
async function loadApplications() {
  try {
    const res = await apiClient.get('/admin/operator-applications')
    if (Array.isArray(res.data)) {
      applications.value = res.data
    } else {
      applications.value = res.data.applications || res.data
      mtlsEnforced.value = res.data.config?.mtls_enforced ?? false
    }
    appsRead.value = 'read'
  } catch (err: any) {
    if (appsRead.value !== 'read') appsRead.value = 'unread'
    console.error('Failed to load operator applications:', err)
  }
}

async function loadLicenses() {
  licenseLoading.value = true
  try {
    // §FRAMELIC (2026-09-07) — one table now backs BOTH classes. Unfiltered, a frame licence
    // would show up here as a stray operator nobody provisioned.
    const res = await apiClient.get('/admin/federation/licenses', { params: { licensee_type: 'operator' } })
    licenses.value = res.data
    licensesRead.value = 'read'
  } catch (err: any) {
    if (licensesRead.value !== 'read') licensesRead.value = 'unread'
    console.error('Failed to load licenses:', err)
  } finally {
    licenseLoading.value = false
  }
}

// ── Option D-light Phase D5 — Lifecycle + drift (2026-04-21) ─────────────
// Fetches the admin/operators/lifecycle-overview once on mount and on refresh.
// Stored as a map of application_id → LifecycleRow so the main Applications
// table can render drift indicators without re-fetching per row.

interface LifecycleRow {
  application: { id: string; name: string; status: string; cloud_hosted: boolean; [k: string]: any }
  federation_license: Record<string, any> | null
  peer_registry: Record<string, any> | null
  cloud: Record<string, any> | null
  drift_flags: string[]
}

const lifecycleByAppId = ref<Record<string, LifecycleRow>>({})
const lifecycleLoading = ref(false)
/** §FESUITE V0577: over a failed overview read both all-clears drew ("✓ No lifecycle drift across 0 operators." and
 *  "✓ No stale-license operators detected"); each says the read failed now */
const lifecycleRead = ref<'reading' | 'read' | 'unread'>('reading')
const showLifecycleModal = ref(false)
const selectedLifecycle = ref<LifecycleRow | null>(null)
const driftScanning = ref(false)

const driftedOperators = computed(() =>
  Object.values(lifecycleByAppId.value).filter(r => r.drift_flags.length > 0)
)

const DRIFT_LABELS: Record<string, string> = {
  license_revoked_operator_active: 'License revoked while operator still active — security gap',
  operator_revoked_license_active: 'Operator revoked but license still active — cascade missed',
  peer_inactive_license_active: 'Peer unreachable — direct peering INACTIVE and no chain connection (license still active)',
}

function driftLabel(flag: string): string {
  return DRIFT_LABELS[flag] || flag
}

async function fetchLifecycleOverview() {
  lifecycleLoading.value = true
  try {
    const res = await apiClient.get('/admin/operators/lifecycle-overview', {
      params: { limit: 500 },
    })
    const rows: LifecycleRow[] = res.data?.operators || []
    const map: Record<string, LifecycleRow> = {}
    for (const row of rows) {
      if (row?.application?.id) map[row.application.id] = row
    }
    lifecycleByAppId.value = map
    lifecycleRead.value = 'read'
  } catch (err: any) {
    if (lifecycleRead.value !== 'read') lifecycleRead.value = 'unread'
    console.error('Failed to load lifecycle overview:', err)
  } finally {
    lifecycleLoading.value = false
  }
}

function openLifecycleModal(app: OperatorApp) {
  const row = lifecycleByAppId.value[app.id]
  if (!row) {
    uiStore.showWarning?.('No lifecycle data', 'Overview not loaded yet — try refreshing.')
    return
  }
  selectedLifecycle.value = row
  showLifecycleModal.value = true
}

function closeLifecycleModal() {
  showLifecycleModal.value = false
  selectedLifecycle.value = null
}

async function runDriftScan() {
  // OPM1: themed confirm.
  const ok = await themeConfirm({
    title: '// RUN DRIFT SCAN',
    message: 'Run a manual drift scan across all operators? Re-emits <code>FederationStateDriftDetected</code> events to the EventStore (deduped per-day).',
    tone: 'primary',
    confirmText: 'Run Scan',
    busyText: 'Scanning…',
  })
  if (ok === null) return
  driftScanning.value = true
  try {
    const res = await apiClient.post('/admin/federation/drift-scan')
    const total = res.data?.total_drifts ?? 0
    uiStore.showInfo?.('Drift scan complete', `${total} drift${total === 1 ? '' : 's'} detected.`)
    await fetchLifecycleOverview()
  } catch (err: any) {
    uiStore.showError?.('Drift scan failed', err.response?.data?.detail || err.message)
  } finally {
    driftScanning.value = false
  }
}

// ── §2026-06-16 Operator IDENTITY (rename Lane B + reconcile) ────────────────
// Wires the mainframe-only operator-rename machinery into the admin view:
//   • reconcile-identity → POST /admin/cloud-operators/reconcile-identity
//       (repairs prior-rename residue: ghost old-slug peers, stale federated-card
//        source_registry SPIFFE, canary master rows — fleet-wide, idempotent)
//   • rename (Lane B)    → POST /admin/cloud-operators/{id}/rename (async cascade)
//                        + GET …/rename-status (poll)
// Both are mainframe-gated server-side (404 `mainframe_only:` on cloud-ops, 503 before V0640: isMainframeOnlyRefusal
// reads both, D6-820) + admin_federation RBAC.
// The destructive paths use an inline typed-confirm; a REAL rename additionally
// needs server env OPERATOR_RENAME_ALLOW_MUTATING=true (dry-run always works).
const showIdentityModal = ref(false)
const identityOp = ref<CloudOperator | null>(null)
const idTab = ref<'reconcile' | 'rename'>('reconcile')

// reconcile sub-form
const idOldSlug = ref('')
const idNewSlug = ref('')
const idReconcileConfirm = ref('')
const idReconBusy = ref(false)
const idReconResult = ref<Record<string, any> | null>(null)
const idReconError = ref('')

// rename (Lane B) sub-form
const idRenameNew = ref('')
const idRenameConfirm = ref('')
const idRenameBusy = ref(false)
const idRenameStatus = ref<Record<string, any> | null>(null)
const idRenameError = ref('')
let idRenamePollTimer: ReturnType<typeof setInterval> | null = null
let idRenamePolls = 0

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/
const RENAME_TERMINAL = ['done', 'failed', 'rolled_back', 'none']

function renameStatePill(state: string): string {
  if (state === 'done') return 'opm-pill--approved'
  if (state === 'failed') return 'opm-pill--revoked'
  if (state === 'rolled_back') return 'opm-pill--suspended'
  return 'opm-pill--pending'
}

function _stopRenamePoll() {
  if (idRenamePollTimer) { clearInterval(idRenamePollTimer); idRenamePollTimer = null }
}

function openIdentityModal(op: CloudOperator) {
  identityOp.value = op
  idTab.value = 'reconcile'
  idOldSlug.value = ''
  idNewSlug.value = op.name || ''
  idReconcileConfirm.value = ''
  idReconResult.value = null
  idReconError.value = ''
  idRenameNew.value = ''
  idRenameConfirm.value = ''
  idRenameStatus.value = null
  idRenameError.value = ''
  _stopRenamePoll()
  showIdentityModal.value = true
  void refreshRenameStatus(true)  // surface any in-flight / last cascade for this op
}

function closeIdentityModal() {
  _stopRenamePoll()
  showIdentityModal.value = false
  identityOp.value = null
}

async function runReconcile(live: boolean) {
  const oldS = idOldSlug.value.trim()
  const newS = idNewSlug.value.trim()
  idReconError.value = ''
  if (!oldS || !newS) { idReconError.value = 'Both the previous slug and the current slug are required.'; return }
  if (oldS === newS) { idReconError.value = 'Previous and current slug must differ (nothing to reconcile).'; return }
  if (live && idReconcileConfirm.value.trim() !== newS) {
    idReconError.value = `Type the current slug "${newS}" to apply a live reconcile.`; return
  }
  idReconBusy.value = true
  try {
    const r = await apiClient.post('/admin/cloud-operators/reconcile-identity', {
      old_slug: oldS, new_slug: newS, dry_run: !live,
    })
    idReconResult.value = r.data
    if (live) {
      uiStore.showSuccess('Reconcile applied', `${r.data.old_slug} → ${r.data.new_slug} · fanout ${r.data.fanout_emitted ? 'emitted' : 'skipped'}`)
      idReconcileConfirm.value = ''
      await Promise.all([fetchLifecycleOverview(), loadLicenses(), fetchCloudOperators()])
    } else {
      uiStore.showInfo?.('Reconcile preview', 'Dry-run complete — nothing was mutated.')
    }
  } catch (e: any) {
    idReconError.value = isMainframeOnlyRefusal(e)
      ? 'Blocked: reconcile is mainframe-only (this registry is a cloud-op).'
      : (e.response?.data?.detail || e.message || 'Reconcile failed')
  } finally {
    idReconBusy.value = false
  }
}

async function refreshRenameStatus(silent = false) {
  if (!identityOp.value) return
  try {
    const r = await apiClient.get(`/admin/cloud-operators/${identityOp.value.application_id}/rename-status`)
    idRenameStatus.value = r.data
  } catch (e: any) {
    if (!silent) idRenameError.value = e.response?.data?.detail || e.message || 'Status poll failed'
  }
}

function _renameSettled(st: Record<string, any> | null): boolean {
  if (!st) return true
  if (RENAME_TERMINAL.includes(st.state)) return true
  // a dry-run rests at plan_gate_ok (quiesce+snapshot+plan, no mutation) — treat as settled
  if (st.dry_run === true && st.state === 'plan_gate_ok') return true
  return false
}

function _startRenamePoll() {
  _stopRenamePoll()
  idRenamePolls = 0
  idRenamePollTimer = setInterval(async () => {
    idRenamePolls++
    await refreshRenameStatus(true)
    if (_renameSettled(idRenameStatus.value) || idRenamePolls > 60) {
      _stopRenamePoll()
      const st = idRenameStatus.value?.state
      if (st === 'done' || st === 'rolled_back') {
        await Promise.all([fetchCloudOperators(), fetchLifecycleOverview(), loadApplications()])
      }
    }
  }, 2500)
}

async function runRename(live: boolean) {
  if (!identityOp.value) return
  const cur = identityOp.value.name || ''
  const ns = idRenameNew.value.trim()
  idRenameError.value = ''
  if (!SLUG_RE.test(ns)) { idRenameError.value = 'New slug must be 3–40 chars of [a-z0-9-] (no leading/trailing dash).'; return }
  if (ns === cur) { idRenameError.value = 'New slug must differ from the current slug.'; return }
  if (live && idRenameConfirm.value.trim() !== cur) {
    idRenameError.value = `Type the current slug "${cur}" to execute the cascade.`; return
  }
  idRenameBusy.value = true
  try {
    const body: Record<string, any> = { new_slug: ns, dry_run: !live }
    if (live) body.confirm = idRenameConfirm.value.trim()
    const r = await apiClient.post(`/admin/cloud-operators/${identityOp.value.application_id}/rename`, body)
    uiStore.showInfo?.(live ? 'Rename cascade started' : 'Rename dry-run started', r.data.note || '')
    if (live) idRenameConfirm.value = ''
    _startRenamePoll()
    void refreshRenameStatus(true)
  } catch (e: any) {
    idRenameError.value = isMainframeOnlyRefusal(e)
      ? 'Blocked: rename is mainframe-only (this registry is a cloud-op).'
      : (e.response?.data?.detail || e.message || 'Rename failed')
  } finally {
    idRenameBusy.value = false
  }
}

// ── §2026-06-16 Stale-license recon (AUDIT surface) ──────────────────────────
// "Active license but operator not present" — reuses the lifecycle-overview drift
// computation (peer unreachable / operator gone while the federation license is
// still active). Read-only audit; the per-row Revoke opens the EXISTING reason-gated
// revoke-license modal so the Commander drives the actual revocation in the loop.
// NOTE: lifecycle-overview on this registry covers FRAME-A-homed operators — a
// fleet-wide sweep must also query the frame-b / frame-c mainframes.
const STALE_LICENSE_FLAGS = ['peer_inactive_license_active', 'operator_revoked_license_active']
const staleLicenseOps = computed(() =>
  Object.values(lifecycleByAppId.value).filter(r =>
    r.federation_license?.status === 'active' &&
    (r.drift_flags || []).some(f => STALE_LICENSE_FLAGS.includes(f))
  )
)
function licenseForRow(row: LifecycleRow): License | null {
  const did = row.federation_license?.operator_did
  if (!did) return null
  return licenses.value.find(l => l.operator_did === did) || null
}
function revokeStaleLicense(row: LifecycleRow) {
  const lic = licenseForRow(row)
  if (!lic) {
    uiStore.showWarning?.('License not matched', 'Could not match this operator to a license row — refresh and retry.')
    return
  }
  openRevokeLicenseModal(lic)  // existing modal: requires a typed reason + confirm
}

onMounted(() => Promise.all([loadApplications(), loadLicenses(), fetchCloudOperators(), fetchAllOperatorHealth(), fetchLifecycleOverview()]))

// ── Application Actions ─────────────────────────────────────
async function approveApplication(app: OperatorApp) {
  // OPM1: themed confirm.
  const ok = await themeConfirm({
    title: '// APPROVE OPERATOR APPLICATION',
    message: `Approve operator application from <strong>${app.name}</strong> (<code>${app.email}</code>)? They become eligible for cloud-provisioning.`,
    tone: 'primary',
    confirmText: 'Approve',
    busyText: 'Approving…',
  })
  if (ok === null) return
  try {
    await apiClient.post(`/admin/operator-applications/${app.id}/approve`, { notes: '' })
    await loadApplications()
    await loadLicenses()
    uiStore.showInfo?.('Approved', `${app.name} is now an approved operator.`)
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

function openRejectModal(app: OperatorApp) {
  selectedApp.value = app
  rejectReason.value = ''
  showRejectModal.value = true
}

async function rejectApplicationConfirm() {
  if (!selectedApp.value || !rejectReason.value) return
  try {
    await apiClient.post(`/admin/operator-applications/${selectedApp.value.id}/reject`, { notes: rejectReason.value })
    showRejectModal.value = false
    selectedApp.value = null
    rejectReason.value = ''
    await loadApplications()
    uiStore.showInfo?.('Rejected', 'Application has been rejected.')
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

function openSuspendModal(app: OperatorApp) {
  selectedAppForAction.value = app
  actionReason.value = ''
  showSuspendModal.value = true
}

function openRevokeOperatorModal(app: OperatorApp) {
  selectedAppForAction.value = app
  actionReason.value = ''
  showRevokeOperatorModal.value = true
}

async function suspendOperator() {
  if (!selectedAppForAction.value || !actionReason.value) return
  try {
    await apiClient.post(`/admin/operator-applications/${selectedAppForAction.value.id}/suspend-operator`, { reason: actionReason.value })
    showSuspendModal.value = false
    selectedAppForAction.value = null
    actionReason.value = ''
    await loadApplications()
    uiStore.showInfo?.('Suspended', 'Operator suspended.')
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

async function revokeOperatorAccess() {
  if (!selectedAppForAction.value || !actionReason.value) return
  try {
    await apiClient.post(`/admin/operator-applications/${selectedAppForAction.value.id}/revoke-operator`, { reason: actionReason.value })
    showRevokeOperatorModal.value = false
    selectedAppForAction.value = null
    actionReason.value = ''
    await loadApplications()
    uiStore.showInfo?.('Revoked', 'Operator fully revoked.')
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

async function reinstateOperator(app: OperatorApp) {
  // OPM1: themed confirm.
  const ok = await themeConfirm({
    title: '// REINSTATE OPERATOR',
    message: `Reinstate <strong>${app.name}</strong>? They will regain operator privileges + their federation license becomes valid again.`,
    tone: 'primary',
    confirmText: 'Reinstate',
    busyText: 'Reinstating…',
  })
  if (ok === null) return
  try {
    await apiClient.post(`/admin/operator-applications/${app.id}/reinstate-operator`)
    await loadApplications()
    uiStore.showInfo?.('Reinstated', 'Operator reinstated.')
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

async function downloadBundle(app: OperatorApp) {
  try {
    const response = await apiClient.get(`/admin/operator-applications/${app.id}/bundle`, {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${app.name.replace(/\s+/g, '-').toLowerCase()}-operator-bundle.tar.gz`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
    await loadApplications()
  } catch (err: any) {
    uiStore.showError?.('Download Failed', err.response?.data?.detail || err.message)
  }
}

// ── License Actions ─────────────────────────────────────────
async function generateLicense() {
  if (!newLicense.value.operator_name || !newLicense.value.operator_did) return
  licenseLoading.value = true
  try {
    const body: Record<string, any> = {
      operator_name: newLicense.value.operator_name,
      operator_did: newLicense.value.operator_did,
      federation_tier: newLicense.value.federation_tier,
    }
    if (newLicense.value.min_image_version) body.min_image_version = newLicense.value.min_image_version
    const res = await apiClient.post('/admin/federation/licenses/generate', body)
    generatedKey.value = res.data.license_key
    showGenerateModal.value = false
    showKeyDisplay.value = true
    newLicense.value = { operator_name: '', operator_did: '', federation_tier: 'standard', min_image_version: '' }
    await loadLicenses()
  } catch (err: any) {
    uiStore.showError?.('Generate Failed', err.response?.data?.detail || err.message || 'Failed to generate license')
  } finally {
    licenseLoading.value = false
  }
}

async function suspendLicense(license: License) {
  try {
    await apiClient.post(`/admin/federation/licenses/${license.id}/suspend`)
    await loadLicenses()
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

function openRevokeLicenseModal(license: License) {
  selectedLicenseForRevoke.value = license
  revokeReason.value = ''
  showRevokeLicenseModal.value = true
}

async function revokeLicenseConfirm() {
  if (!selectedLicenseForRevoke.value || !revokeReason.value) return
  try {
    await apiClient.post(`/admin/federation/licenses/${selectedLicenseForRevoke.value.id}/revoke`, { reason: revokeReason.value })
    showRevokeLicenseModal.value = false
    revokeReason.value = ''
    selectedLicenseForRevoke.value = null
    await loadLicenses()
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

async function reinstateLicense(license: License) {
  try {
    await apiClient.post(`/admin/federation/licenses/${license.id}/reinstate`)
    await loadLicenses()
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

async function deleteLicense(license: License) {
  // OPM1: themed confirm with danger tone for permanent action.
  const ok = await themeConfirm({
    title: '// DELETE FEDERATION LICENSE',
    message: `<strong>Permanently delete</strong> the federation license for <strong>${license.operator_name}</strong>? This cannot be undone — they'd need a fresh license issued.`,
    tone: 'danger',
    confirmText: 'Delete License',
    busyText: 'Deleting…',
    warning: 'Active federation traffic from this operator will be rejected.',
  })
  if (ok === null) return
  try {
    await apiClient.delete(`/admin/federation/licenses/${license.id}`)
    await loadLicenses()
  } catch (err: any) {
    uiStore.showError?.('Error', err.response?.data?.detail || err.message)
  }
}

function toggleLicenseExpand(id: string) {
  expandedLicenseId.value = expandedLicenseId.value === id ? null : id
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
}

// ── f050: Pull Token Rotation ──────────────────────────────
const rotatedToken = ref<string>('')
const showRotatedTokenModal = ref(false)

async function rotatePullToken(app: OperatorApp) {
  // OPM1: themed confirm.
  const ok = await themeConfirm({
    title: '// ROTATE DOCKER PULL TOKEN',
    message: `Rotate the Docker pull token for <strong>${app.name}</strong>? The old token will be immediately invalidated; their CI/CD must update with the new token.`,
    tone: 'warn',
    confirmText: 'Rotate Token',
    busyText: 'Rotating…',
  })
  if (ok === null) return
  try {
    const res = await apiClient.post(`/admin/operator-applications/${app.id}/rotate-pull-token`)
    rotatedToken.value = res.data.pull_token
    showRotatedTokenModal.value = true
    await loadApplications()
  } catch (err: any) {
    uiStore.showError('Rotation Failed', err.response?.data?.detail || 'Failed to rotate pull token')
  }
}

function formatNumber(n: number): string {
  return n >= 1000000 ? (n / 1000000).toFixed(1) + 'M' : n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(Math.round(n))
}
</script>

<template>
<div class="opm-page">
  <!-- Page Header -->
  <div class="opm-header">
    <h1 class="opm-title">{{ t('operatorManagementView.title') }}</h1>
    <p class="opm-subtitle">{{ t('operatorManagementView.subtitle') }}</p>
  </div>

  <!-- SECTION 0 (D5): Drift Alerts Banner -->
  <div
    v-if="driftedOperators.length > 0"
    class="opm-drift-banner"
    :title="'Run drift scan and refresh to re-evaluate'"
  >
    <div class="opm-drift-banner-left">
      <span class="opm-drift-icon" aria-hidden="true">&#9888;</span>
      <div>
        <div class="opm-drift-title">
          {{ driftedOperators.length === 1 ? t('operatorManagementView.drift.banner1') : t('operatorManagementView.drift.bannerN', { count: driftedOperators.length }) }}
        </div>
        <div class="opm-drift-sub">
          {{ t('operatorManagementView.drift.sub') }}
        </div>
      </div>
    </div>
    <button class="opm-btn opm-btn--yellow" :disabled="driftScanning" @click="runDriftScan">
      {{ driftScanning ? t('operatorManagementView.drift.scanning') : t('operatorManagementView.drift.scan') }}
    </button>
  </div>
  <ReadFailedNotice v-else-if="!lifecycleLoading && lifecycleRead === 'unread'" dense :retry="fetchLifecycleOverview" data-testid="opm-drift-unread" />
  <div v-else-if="!lifecycleLoading && lifecycleRead === 'read'" class="opm-drift-clean">
    <span class="opm-drift-clean-icon" aria-hidden="true">&#10003;</span>
    {{ t('operatorManagementView.drift.clean', { count: Object.keys(lifecycleByAppId).length }) }}
    <button class="opm-btn-link" :disabled="driftScanning" @click="runDriftScan">{{ t('operatorManagementView.drift.rescan') }}</button>
  </div>

  <!-- SECTION 1: Application Stats -->
  <div class="opm-stats">
    <div class="opm-stat opm-stat--amber">
      <span class="opm-stat-val">{{ appsRead === 'read' ? applications.filter(a => a.status === 'pending').length : '—' }}</span>
      <span class="opm-stat-lbl">{{ t('operatorManagementView.stats.pending') }}</span>
    </div>
    <div class="opm-stat opm-stat--green">
      <span class="opm-stat-val">{{ appsRead === 'read' ? applications.filter(a => a.status === 'approved').length : '—' }}</span>
      <span class="opm-stat-lbl">{{ t('operatorManagementView.stats.approved') }}</span>
    </div>
    <div class="opm-stat opm-stat--yellow">
      <span class="opm-stat-val">{{ appsRead === 'read' ? applications.filter(a => a.status === 'suspended').length : '—' }}</span>
      <span class="opm-stat-lbl">{{ t('operatorManagementView.stats.suspended') }}</span>
    </div>
    <div class="opm-stat opm-stat--red">
      <span class="opm-stat-val">{{ appsRead === 'read' ? applications.filter(a => a.status === 'revoked').length : '—' }}</span>
      <span class="opm-stat-lbl">{{ t('operatorManagementView.stats.revoked') }}</span>
    </div>
    <div class="opm-stat opm-stat--cyan">
      <span class="opm-stat-val">{{ appsRead === 'read' ? applications.length : '—' }}</span>
      <span class="opm-stat-lbl">{{ t('operatorManagementView.stats.total') }}</span>
    </div>
  </div>

  <!-- SECTION 2: Applications Table -->
  <div class="opm-section">
    <div class="opm-section-header">
      <h2 class="opm-section-title">{{ t('operatorManagementView.sections.applications') }}</h2>
      <select v-model="applicationFilter" class="opm-filter" :aria-label="t('operatorManagementView.applicationFilterAria', 'Filter applications by status')">
        <option value="all">{{ t('operatorManagementView.license.filterAll') }}</option>
        <option value="pending">{{ t('operatorManagementView.stats.pending') }}</option>
        <option value="approved">{{ t('operatorManagementView.stats.approved') }}</option>
        <option value="suspended">{{ t('operatorManagementView.stats.suspended') }}</option>
        <option value="revoked">{{ t('operatorManagementView.stats.revoked') }}</option>
        <option value="rejected">Rejected</option>
      </select>
    </div>
    <div class="opm-table-wrap">
      <table class="opm-table">
        <thead>
          <tr>
            <th>{{ t('operatorManagementView.appTable.thApplicant') }}</th>
            <th>{{ t('operatorManagementView.appTable.thEmail') }}</th>
            <th>{{ t('operatorManagementView.appTable.thOrganization') }}</th>
            <th>{{ t('operatorManagementView.appTable.thDeployment') }}</th>
            <th>{{ t('operatorManagementView.appTable.thStatus') }}</th>
            <th :title="t('operatorManagementView.appTable.thDrift')">{{ t('operatorManagementView.appTable.thDrift') }}</th>
            <th>{{ t('operatorManagementView.appTable.thBundle') }}</th>
            <th>{{ t('operatorManagementView.appTable.thSubmitted') }}</th>
            <th>{{ t('operatorManagementView.appTable.thActions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="app in filteredApplications" :key="app.id">
            <td>
              <span style="font-weight: 600; color: #e2e8f0;">{{ app.name }}</span>
              <div v-if="app.status === 'approved' && (app.docker_registry_username || app.spire_fingerprint)" style="margin-top: 4px;">
                <span v-if="app.docker_registry_username" :title="'Docker user: ' + app.docker_registry_username" style="display: inline-block; font-size: 10px; color: #75859b; background: rgba(59,130,246,0.08); padding: 1px 6px; border-radius: 4px; margin-right: 4px; cursor: help;">docker: {{ app.docker_registry_username }}</span>
                <span v-if="app.spire_fingerprint" :title="'SPIRE fingerprint: ' + app.spire_fingerprint" style="display: inline-block; font-size: 10px; color: #75859b; background: rgba(139,92,246,0.08); padding: 1px 6px; border-radius: 4px; cursor: help;">spire: {{ app.spire_fingerprint.substring(0, 16) }}...</span>
                <span v-if="app.docker_pull_token_prefix" style="display:inline-block;font-size:10px;color:#4ade80;background:rgba(74,222,128,0.08);padding:1px 6px;border-radius:4px;margin-left:4px;font-family:'IBM Plex Mono',monospace;">pull: {{ app.docker_pull_token_prefix }}…</span>
              </div>
            </td>
            <td>
              <span v-if="!showEmails" style="color: #75859b; cursor: pointer; font-size: 12px;" @click="showEmails = true" :title="t('operatorManagementView.appTable.clickReveal')">{{ redactEmail(app.email) }}</span>
              <a v-else :href="'mailto:' + app.email" style="color: #3b82f6;">{{ app.email }}</a>
            </td>
            <td>{{ app.organization || '\u2014' }}</td>
            <td>
              <span class="opm-pill" style="background: rgba(59,130,246,0.1); color: #60a5fa;">{{ app.deployment }}</span>
              <!-- §FESUITE V0595: what the applicant chose to run, in the catalog's words -->
              <div class="opm-env" :data-testid="'opm-env-' + app.id">
                {{ envChoiceText(app) }}
              </div>
            </td>
            <td>
              <span :class="['opm-pill', `opm-pill--${app.status}`]">{{ app.status }}</span>
            </td>
            <td>
              <button
                v-if="lifecycleByAppId[app.id]?.drift_flags?.length"
                class="opm-drift-cell opm-drift-cell--has"
                :title="lifecycleByAppId[app.id].drift_flags.map(driftLabel).join('\n')"
                @click.stop="openLifecycleModal(app)"
              >
                <span aria-hidden="true">&#9888;</span>
                {{ lifecycleByAppId[app.id].drift_flags.length }}
              </button>
              <button
                v-else-if="lifecycleByAppId[app.id]"
                class="opm-drift-cell opm-drift-cell--clean"
                title="No drift — click to view lifecycle state stack"
                @click.stop="openLifecycleModal(app)"
              >
                <span aria-hidden="true">&#8729;</span>
              </button>
              <span v-else style="color:#475569;font-size:10px;">&mdash;</span>
            </td>
            <td>
              <template v-if="app.status === 'approved' && app.bundle_path">
                <span style="font-size: 11px; color: #34d399;">{{ t('operatorManagementView.appTable.bundleReady') }}</span>
                <span style="font-size: 10px; color: #75859b; display: block;">{{ t('operatorManagementView.appTable.bundleDownloads', { count: app.bundle_download_count || 0 }) }}</span>
                <span v-if="app.bundle_expires_at" style="font-size: 10px; color: #75859b; display: block;">{{ t('operatorManagementView.appTable.bundleExpires') }} {{ dayjs(app.bundle_expires_at).fromNow() }}</span>
              </template>
              <template v-else-if="app.status === 'approved'">
                <span style="font-size: 11px; color: #fbbf24;">{{ t('operatorManagementView.appTable.bundleProvisioning') }}</span>
              </template>
              <span v-else style="color: #475569;">&mdash;</span>
            </td>
            <td style="font-size: 11px; color: #94a3b8;">{{ dayjs(app.created_at).fromNow() }}</td>
            <td>
              <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                <template v-if="app.status === 'pending'">
                  <button @click="approveApplication(app)" class="opm-btn opm-btn--green">{{ t('operatorManagementView.appTable.approve') }}</button>
                  <button @click="openRejectModal(app)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.appTable.reject') }}</button>
                </template>
                <template v-else-if="app.status === 'approved'">
                  <button v-if="app.bundle_path" @click="downloadBundle(app)" class="opm-btn opm-btn--blue">{{ t('operatorManagementView.appTable.download') }}</button>
                  <button @click="rotatePullToken(app)" class="opm-btn opm-btn--cyan">{{ t('operatorManagementView.appTable.rotatePullToken') }}</button>
                  <button @click="openSuspendModal(app)" class="opm-btn opm-btn--yellow">{{ t('operatorManagementView.appTable.suspend') }}</button>
                  <button @click="openRevokeOperatorModal(app)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.license.revoke') }}</button>
                </template>
                <template v-else-if="app.status === 'suspended'">
                  <button @click="reinstateOperator(app)" class="opm-btn opm-btn--green">{{ t('operatorManagementView.appTable.reinstate') }}</button>
                  <button @click="openRevokeOperatorModal(app)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.license.revoke') }}</button>
                </template>
                <template v-else-if="app.status === 'revoked'">
                  <span style="font-size: 11px; color: #f87171;">{{ dayjs(app.revoked_at).fromNow() }}</span>
                </template>
                <span v-else-if="app.reviewed_by" style="font-size: 11px; color: #75859b;">Reviewed {{ dayjs(app.reviewed_at).fromNow() }}</span>
              </div>
            </td>
          </tr>
          <tr v-if="filteredApplications.length === 0">
            <td colspan="9" style="text-align: center; padding: 2rem; color: #75859b; font-size: 12px;">
              {{ appsRead === 'read' ? t('operatorManagementView.appTable.empty') : appsRead === 'unread' ? t('operatorManagementView.appTable.unread', 'The applications could not be read just now.') : t('common.loading', 'Loading…') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- SECTION 3: Cloud-Hosted Operators (f051) -->
  <div class="opm-section">
    <div class="opm-section-header">
      <h2 class="opm-section-title">{{ t('operatorManagementView.sections.cloudHosted') }}</h2>
      <span style="font-size:12px;color:var(--text-secondary);">{{ cloudRead === 'read' ? t('operatorManagementView.cloud.slots', { active: cloudActiveCount, limit: cloudBetaLimit }) : '—' }}</span>
    </div>

    <div v-if="cloudLoading" style="text-align:center;padding:20px;color:var(--text-secondary);font-size:13px;">{{ t('operatorManagementView.cloud.loading') }}</div>

    <ReadFailedNotice v-else-if="cloudOperators.length === 0 && cloudRead === 'unread'" :retry="fetchCloudOperators" data-testid="opm-cloud-unread" />
    <div v-else-if="cloudOperators.length === 0 && cloudRead === 'read'" style="text-align:center;padding:30px;color:var(--text-secondary);font-size:13px;">
      {{ t('operatorManagementView.cloud.empty') }}
    </div>

    <!-- the cloud-hosted table scrolls sideways in its own wrap like the page's other tables; unwrapped, its URL column
         ran past a phone's edge (the camera, 2026-10-13) -->
    <div v-else class="opm-table-wrap">
    <table class="opm-table">
      <thead>
        <tr>
          <th>{{ t('operatorManagementView.cloud.thStatus') }}</th>
          <th>{{ t('operatorManagementView.cloud.thName') }}</th>
          <th>{{ t('operatorManagementView.cloud.thUrl') }}</th>
          <th>{{ t('operatorManagementView.cloud.thPort') }}</th>
          <th>{{ t('operatorManagementView.cloud.thProvisioned') }}</th>
          <th>{{ t('operatorManagementView.cloud.thActions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="op in cloudOperators" :key="op.application_id">
          <td>
            <span v-if="op.active && op.healthy" style="color:#00c853;">{{ t('operatorManagementView.cloud.online') }}</span>
            <span v-else-if="op.active && op.healthy === false" style="color:#ff1744;">{{ t('operatorManagementView.cloud.down') }}</span>
            <span v-else-if="op.active" style="color:#ffab00;">{{ t('operatorManagementView.cloud.unknown') }}</span>
            <span v-else style="color:#75859b;">{{ t('operatorManagementView.cloud.tornDown') }}</span>
          </td>
          <td style="font-weight:600;">{{ op.name }}</td>
          <td><a v-if="op.cloud_url" :href="safeExternalUrl(op.cloud_url)" target="_blank" rel="noopener noreferrer" style="color:var(--cyan);text-decoration:none;">{{ op.cloud_url }}</a></td>
          <td style="font-family:monospace;font-size:12px;">{{ op.cloud_port_base }}</td>
          <td style="font-size:12px;color:var(--text-secondary);">{{ op.cloud_provisioned_at ? dayjs(op.cloud_provisioned_at).fromNow() : '-' }}</td>
          <td>
            <button
              v-if="op.active"
              @click="openLogsModal(op.application_id, op.name)"
              class="opm-btn opm-btn--blue"
              style="font-size:11px;padding:3px 8px;margin-right:4px;"
              :title="`View logs from ${op.name} (equivalent of tp-operator logs)`"
            >Logs</button>
            <button
              v-if="op.active"
              @click="restartCloud(op.application_id, op.name)"
              :disabled="restartId === op.application_id"
              class="opm-btn opm-btn--cyan"
              style="font-size:11px;padding:3px 8px;margin-right:4px;"
              :title="`Restart the registry service on ${op.name} (equivalent of tp-operator restart registry from the host shell)`"
            >
              {{ restartId === op.application_id ? 'Restarting…' : 'Restart' }}
            </button>
            <button
              v-if="op.active"
              @click="openIdentityModal(op)"
              class="opm-btn opm-btn--violet"
              style="font-size:11px;padding:3px 8px;margin-right:4px;"
              :title="`Identity: reconcile prior-rename residue, or re-slug ${op.name} (Lane B). Mainframe-only.`"
            >Identity</button>
            <button v-if="op.active" @click="teardownCloud(op.application_id)" :disabled="teardownId === op.application_id" class="opm-btn opm-btn--red" style="font-size:11px;padding:3px 8px;">
              {{ teardownId === op.application_id ? t('operatorManagementView.cloud.tearingDown') : t('operatorManagementView.cloud.teardown') }}
            </button>
            <span v-else style="font-size:11px;color:var(--text-secondary);">{{ op.cloud_torn_down_at ? dayjs(op.cloud_torn_down_at).fromNow() : '' }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    </div>

    <!-- All Federation Operators Health -->
    <div v-if="allOperatorHealth.length > 0" style="margin-top:20px;">
      <h3 style="font-size:13px;color:var(--text-secondary);margin:0 0 8px;">{{ t('operatorManagementView.cloud.healthTitle', { healthy: allOperatorHealth.filter(o => o.status === 'healthy').length, total: allOperatorHealth.length }) }}</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px;">
        <div v-for="op in allOperatorHealth" :key="op.name" style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:rgba(10,14,24,0.6);border:1px solid rgba(255,255,255,0.04);border-radius:5px;font-size:12px;" :style="{ borderLeftColor: op.status === 'healthy' ? '#00c853' : '#ff1744', borderLeftWidth: '2px' }">
          <span :style="{ color: op.status === 'healthy' ? '#00c853' : '#ff1744' }">●</span>
          <span style="flex:1;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ op.name }}</span>
          <span style="font-family:monospace;font-size:10px;color:#75859b;">{{ op.ms }}ms</span>
        </div>
      </div>
    </div>

    <!-- Provision button on activated apps that aren't cloud-hosted -->
    <div style="margin-top:16px;">
      <h3 style="font-size:13px;color:var(--text-secondary);margin:0 0 8px;">{{ t('operatorManagementView.cloud.provisionTitle') }}</h3>
      <div v-for="app in filteredApplications.filter(a => a.status !== 'rejected' && !a.cloud_hosted)" :key="'cloud-'+app.id" style="display:inline-flex;align-items:center;gap:8px;margin:4px 8px 4px 0;">
        <template v-if="app.activated_at || app.bundle_path">
          <button @click="provisionCloud(app.id)" :disabled="provisioningId === app.id || cloudActiveCount >= cloudBetaLimit" class="opm-btn opm-btn--cyan" style="font-size:11px;padding:3px 10px;">
            {{ provisioningId === app.id ? t('operatorManagementView.cloud.provisioning') : `☁ ${app.name}` }}
          </button>
          <!-- Live stage + elapsed while provisioning. A ~90s-to-several-minute
               operation with no feedback reads as a hang; this shows what it is
               actually doing and that it is still working. -->
          <span v-if="provisioningId === app.id" class="opm-prov-live">
            <span class="opm-prov-dot"></span>{{ provisionStage }} · {{ provisionElapsed }}s
          </span>
        </template>
      </div>
      <div v-if="filteredApplications.filter(a => (a.activated_at || a.bundle_path) && !a.cloud_hosted).length === 0" style="font-size:12px;color:var(--text-secondary);">{{ appsRead === 'read' ? t('operatorManagementView.cloud.noActivated') : appsRead === 'unread' ? t('operatorManagementView.appTable.unread', 'The applications could not be read just now.') : t('common.loading', 'Loading…') }}</div>
    </div>
  </div>

  <!-- SECTION 3.5 (§2026-06-16): Stale-License Recon — active license, operator not present -->
  <div class="opm-section">
    <div class="opm-section-header">
      <h2 class="opm-section-title">Stale-License Recon</h2>
      <button class="opm-btn-link" :disabled="lifecycleLoading" @click="fetchLifecycleOverview">{{ lifecycleLoading ? 'Scanning…' : 'Re-scan' }}</button>
    </div>
    <p style="font-size:11px;color:#75859b;margin:-6px 0 14px;line-height:1.5;">
      Operators whose <strong style="color:#94a3b8;">federation license is still ACTIVE</strong> but who are
      <strong style="color:#94a3b8;">not present</strong> (peer registry unreachable / INACTIVE, or operator revoked).
      Audit only — <em>Revoke license</em> opens the reason-gated confirm so revocation stays a deliberate, in-the-loop action.
      Covers Frame-A-homed operators on this registry (query frame-b / frame-c for a full-fleet sweep).
    </p>
    <div v-if="staleLicenseOps.length > 0" class="opm-table-wrap">
      <table class="opm-table">
        <thead>
          <tr>
            <th>Operator</th>
            <th>License</th>
            <th>Peer presence</th>
            <th>Last seen</th>
            <th>Drift</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in staleLicenseOps" :key="row.application.id">
            <td>
              <span style="font-weight:600;color:#e2e8f0;">{{ row.application.name }}</span>
              <span :class="['opm-pill', `opm-pill--${row.application.status}`]" style="margin-left:6px;">{{ row.application.status }}</span>
            </td>
            <td>
              <span class="opm-pill opm-pill--active">active</span>
              <span v-if="row.federation_license?.operator_did" style="display:block;font-size:10px;color:#75859b;font-family:monospace;margin-top:2px;">{{ String(row.federation_license.operator_did).slice(0, 28) }}…</span>
            </td>
            <td>
              <span v-if="!row.peer_registry" style="color:#f87171;">no peer row</span>
              <span v-else :style="{ color: row.peer_registry.status === 'ACTIVE' ? '#34d399' : '#f59e0b' }">{{ row.peer_registry.status }}</span>
            </td>
            <td style="font-size:11px;color:#94a3b8;">{{ row.federation_license?.last_seen_at ? dayjs(row.federation_license.last_seen_at).fromNow() : 'never' }}</td>
            <td>
              <span v-for="f in row.drift_flags" :key="f" :title="driftLabel(f)" class="opm-pill" style="background:rgba(245,158,11,0.12);color:#fbbf24;margin:1px;cursor:help;">{{ f }}</span>
            </td>
            <td>
              <div style="display:flex;gap:4px;flex-wrap:wrap;">
                <button class="opm-btn opm-btn--blue" @click="openLifecycleModal(row.application as any)">Lifecycle</button>
                <button class="opm-btn opm-btn--red" @click="revokeStaleLicense(row)">Revoke license</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <ReadFailedNotice v-else-if="!lifecycleLoading && lifecycleRead === 'unread'" dense :retry="fetchLifecycleOverview" data-testid="opm-stale-unread" />
    <div v-else-if="!lifecycleLoading && lifecycleRead === 'read'" class="opm-drift-clean">
      <span class="opm-drift-clean-icon" aria-hidden="true">&#10003;</span>
      No stale-license operators detected (active license + not present) on Frame-A-homed operators.
    </div>
  </div>

  <!-- SECTION 4: Federation Licenses -->
  <div class="opm-section">
    <div class="opm-section-header">
      <h2 class="opm-section-title">{{ t('operatorManagementView.sections.licenses') }}</h2>
      <button @click="showGenerateModal = true" class="opm-btn opm-btn--cyan">{{ t('operatorManagementView.license.generateBtn') }}</button>
    </div>

    <!-- Architecture banner: license is the OPERATOR ANCHOR; EventStore events use mTLS only. -->
    <div v-if="mtlsEnforced" class="opm-mtls-banner">
      <div class="opm-mtls-icon">&#x1F512;</div>
      <div>
        <h3 class="opm-mtls-title">{{ t('operatorManagementView.mtls.title') }}</h3>
        <p class="opm-mtls-text">{{ t('operatorManagementView.mtls.text1') }}</p>
        <p class="opm-mtls-text" style="margin-top: 6px;">{{ t('operatorManagementView.mtls.text2') }}</p>
      </div>
    </div>

    <!-- License content (always interactive — license management is independent of ES auth path). -->
    <div>

      <!-- License Stats -->
      <div class="opm-license-stats">
        <div class="opm-license-stat opm-license-stat--green">
          <span class="opm-license-stat-val">{{ licensesRead === 'read' ? licenses.filter(l => l.status === 'active').length : '—' }}</span>
          <span class="opm-license-stat-lbl">{{ t('operatorManagementView.license.filterActive') }}</span>
        </div>
        <div class="opm-license-stat opm-license-stat--yellow">
          <span class="opm-license-stat-val">{{ licensesRead === 'read' ? licenses.filter(l => l.status === 'suspended').length : '—' }}</span>
          <span class="opm-license-stat-lbl">{{ t('operatorManagementView.license.filterSuspended') }}</span>
        </div>
        <div class="opm-license-stat opm-license-stat--red">
          <span class="opm-license-stat-val">{{ licensesRead === 'read' ? licenses.filter(l => l.status === 'revoked').length : '—' }}</span>
          <span class="opm-license-stat-lbl">{{ t('operatorManagementView.license.filterRevoked') }}</span>
        </div>
        <div class="opm-license-stat opm-license-stat--cyan">
          <span class="opm-license-stat-val">{{ licensesRead === 'read' ? licenses.length : '—' }}</span>
          <span class="opm-license-stat-lbl">{{ t('operatorManagementView.stats.total') }}</span>
        </div>
      </div>

      <!-- License Filter -->
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
        <select v-model="licenseFilter" class="opm-filter" :aria-label="t('operatorManagementView.licenseFilterAria', 'Filter licences by status')">
          <option value="all">{{ t('operatorManagementView.license.filterAll') }}</option>
          <option value="active">{{ t('operatorManagementView.license.filterActive') }}</option>
          <option value="suspended">{{ t('operatorManagementView.license.filterSuspended') }}</option>
          <option value="revoked">{{ t('operatorManagementView.license.filterRevoked') }}</option>
        </select>
        <span v-if="licenseLoading" style="font-size: 11px; color: #75859b;">{{ t('operatorManagementView.license.loading') }}</span>
      </div>

      <!-- License Table -->
      <div class="opm-table-wrap">
        <table class="opm-table">
          <thead>
            <tr>
              <th>{{ t('operatorManagementView.license.thOperator') }}</th>
              <th>{{ t('operatorManagementView.license.thDid') }}</th>
              <th>{{ t('operatorManagementView.license.thStatus') }}</th>
              <th>{{ t('operatorManagementView.license.thTier') }}</th>
              <th>{{ t('operatorManagementView.license.thLastSeen') }}</th>
              <th>{{ t('operatorManagementView.license.thEvents') }}</th>
              <th>{{ t('operatorManagementView.license.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="license in filteredLicenses" :key="license.id">
              <tr @click="toggleLicenseExpand(license.id)" style="cursor: pointer;">
                <td>
                  <span style="font-weight: 600; color: #e2e8f0;">{{ license.operator_name }}</span>
                  <span style="display: block; font-size: 10px; color: #75859b; font-family: monospace;">{{ license.license_key_prefix }}...</span>
                </td>
                <td style="font-family: monospace; font-size: 11px;">
                  {{ license.operator_did.length > 30 ? license.operator_did.slice(0, 30) + '...' : license.operator_did }}
                </td>
                <td>
                  <span :class="['opm-pill', `opm-pill--${license.status}`]">{{ license.status }}</span>
                </td>
                <td style="font-size: 12px; color: #94a3b8;">{{ license.federation_tier }}</td>
                <td style="font-size: 11px; color: #94a3b8;">
                  {{ license.last_seen_at ? dayjs(license.last_seen_at).fromNow() : t('operatorManagementView.license.never') }}
                  <span v-if="!license.last_seen_at && license.event_count === 0" title="Internal registries on the same Docker network use API key auth instead of license keys. 0 events is expected." style="cursor: help; opacity: 0.5; margin-left: 2px;">&#9432;</span>
                </td>
                <td style="font-size: 12px; color: #94a3b8;">
                  {{ formatNumber(license.event_count) }}
                  <span v-if="!license.last_seen_at && license.event_count === 0" title="Internal registries use direct API key auth -- license verification is bypassed on the same network." style="cursor: help; opacity: 0.5; margin-left: 2px;">&#9432;</span>
                </td>
                <td @click.stop>
                  <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                    <template v-if="license.status === 'active'">
                      <button @click="suspendLicense(license)" class="opm-btn opm-btn--yellow">{{ t('operatorManagementView.license.suspend') }}</button>
                      <button @click="openRevokeLicenseModal(license)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.license.revoke') }}</button>
                    </template>
                    <template v-else-if="license.status === 'suspended'">
                      <button @click="reinstateLicense(license)" class="opm-btn opm-btn--cyan">{{ t('operatorManagementView.license.reinstate') }}</button>
                      <button @click="openRevokeLicenseModal(license)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.license.revoke') }}</button>
                    </template>
                    <template v-else-if="license.status === 'revoked'">
                      <button @click="reinstateLicense(license)" class="opm-btn opm-btn--cyan">{{ t('operatorManagementView.license.reinstate') }}</button>
                      <button @click="deleteLicense(license)" class="opm-btn opm-btn--red">{{ t('operatorManagementView.license.delete') }}</button>
                    </template>
                  </div>
                </td>
              </tr>
              <!-- Expandable detail row -->
              <tr v-show="expandedLicenseId === license.id">
                <td colspan="7" class="opm-expand-row">
                  <div class="opm-expand-grid">
                    <div>
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.fullDid') }}</span>
                      <span class="opm-expand-value" style="word-break: break-all; font-family: monospace; font-size: 11px;">{{ license.operator_did }}</span>
                    </div>
                    <div>
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.keyPrefix') }}</span>
                      <span class="opm-expand-value" style="font-family: monospace;">{{ license.license_key_prefix }}</span>
                    </div>
                    <div>
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.issued') }}</span>
                      <span class="opm-expand-value">{{ dayjs(license.issued_at).format('YYYY-MM-DD HH:mm') }}</span>
                    </div>
                    <div>
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.minVersion') }}</span>
                      <span class="opm-expand-value">{{ license.min_image_version || t('operatorManagementView.license.notSet') }}</span>
                    </div>
                    <div v-if="license.revoked_at">
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.revokedAt') }}</span>
                      <span class="opm-expand-value" style="color: #f87171;">{{ dayjs(license.revoked_at).format('YYYY-MM-DD HH:mm') }}</span>
                    </div>
                    <div v-if="license.revoked_reason">
                      <span class="opm-expand-label">{{ t('operatorManagementView.license.revokeReason') }}</span>
                      <span class="opm-expand-value" style="color: #f87171;">{{ license.revoked_reason }}</span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="filteredLicenses.length === 0">
              <td colspan="7" style="text-align: center; padding: 2rem; color: #75859b; font-size: 12px;">
                <ReadFailedNotice v-if="!licenseLoading && licensesRead === 'unread'" dense :retry="loadLicenses" data-testid="opm-lic-unread" />
                <template v-else>{{ licenseLoading || licensesRead === 'reading' ? t('operatorManagementView.license.emptyLoading') : t('operatorManagementView.license.emptyNone') }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Docker Registry Info -->
    <div class="opm-docker-info">
      <h3 class="opm-docker-title">{{ t('operatorManagementView.docker.title') }}</h3>
      <p class="opm-docker-desc">{{ t('operatorManagementView.docker.desc') }}</p>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- MODALS (Teleported to body)                              -->
  <!-- ════════════════════════════════════════════════════════ -->

  <!-- Reject Application Modal -->
  <Teleport to="body">
    <div v-if="showRejectModal && selectedApp" class="opm-overlay" @click.self="showRejectModal = false">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.rejectModal.title') }}</p>
        <p style="color: #94a3b8; font-size: 13px; margin-bottom: 12px;">
          {{ t('operatorManagementView.rejectModal.body') }} <strong style="color: #e2e8f0;">{{ selectedApp.name }}</strong> ({{ selectedApp.email }})
        </p>
        <div style="margin-bottom: 16px;">
          <label class="opm-label">{{ t('operatorManagementView.rejectModal.reasonLabel') }}</label>
          <textarea v-model="rejectReason" class="opm-input" rows="3" :placeholder="t('operatorManagementView.rejectModal.reasonPlaceholder')" style="resize: none;"></textarea>
        </div>
        <div class="opm-modal-actions">
          <button @click="showRejectModal = false; rejectReason = ''" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.rejectModal.cancel') }}</button>
          <button @click="rejectApplicationConfirm" :disabled="!rejectReason" class="opm-btn opm-btn--red" style="background: rgba(239,68,68,0.15);">{{ t('operatorManagementView.rejectModal.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass66.9 — Cloud-op Logs Viewer Modal -->
  <Teleport to="body">
    <div v-if="showLogsModal" class="opm-overlay" @click.self="showLogsModal = false">
      <div class="opm-modal" style="width: 900px; max-width: 95vw;">
        <p class="opm-modal-title">// LOGS — {{ logsOpName }}</p>
        <p style="color: #94a3b8; font-size: 12px; margin-bottom: 12px;">
          docker compose logs from this cloud-op's stack (equivalent of
          <code>tp-operator logs &lt;service&gt;</code> from the host shell).
        </p>
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px;">
          <label for="operatormanagement-sel-1480" style="font-size: 12px; color: #94a3b8;">Service</label>
          <select id="operatormanagement-sel-1480" v-model="logsService" class="opm-input" style="width: 200px;" @change="fetchLogs">
            <option value="registry">registry</option>
            <option value="teg-layer">teg-layer</option>
            <option value="nginx-federation">nginx-federation</option>
            <option value="redis">redis</option>
            <option value="db">db</option>
            <option value="teg-db">teg-db</option>
            <option value="pgbouncer">pgbouncer</option>
            <option value="spire-agent">spire-agent</option>
            <option value="cert-writer">cert-writer</option>
            <option value="all">all (interleaved)</option>
          </select>
          <label style="font-size: 12px; color: #94a3b8;">Tail</label>
          <input v-model.number="logsTail" type="number" min="10" max="2000" class="opm-input" style="width: 90px;" @change="fetchLogs" />
          <button @click="fetchLogs" :disabled="logsLoading" class="opm-btn opm-btn--cyan" style="margin-left: auto;">
            {{ logsLoading ? '⟳ Loading…' : '↻ Refresh' }}
          </button>
        </div>
        <pre v-if="logsError" style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; padding: 10px; border-radius: 4px; font-size: 11px;">{{ logsError }}</pre>
        <pre
          v-else
          style="background: #000; color: #d1fae5; padding: 12px; border-radius: 4px; font-size: 11px; line-height: 1.45; max-height: 60vh; overflow-y: auto; font-family: 'IBM Plex Mono', monospace; white-space: pre-wrap; word-break: break-word;"
        >{{ logsOutput || (logsLoading ? 'Loading…' : '(no output)') }}</pre>
        <div class="opm-modal-actions" style="margin-top: 12px;">
          <button @click="showLogsModal = false" class="opm-btn opm-btn--ghost">Close</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Suspend Operator Modal -->
  <Teleport to="body">
    <div v-if="showSuspendModal && selectedAppForAction" class="opm-overlay" @click.self="showSuspendModal = false">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.suspendModal.title') }}</p>
        <p style="color: #94a3b8; font-size: 13px; margin-bottom: 12px;">
          {{ t('operatorManagementView.suspendModal.suspending') }} <strong style="color: #e2e8f0;">{{ selectedAppForAction.name }}</strong>. {{ t('operatorManagementView.suspendModal.body') }}
        </p>
        <div style="margin-bottom: 16px;">
          <label class="opm-label">{{ t('operatorManagementView.suspendModal.reasonLabel') }}</label>
          <textarea v-model="actionReason" class="opm-input" rows="3" :placeholder="t('operatorManagementView.suspendModal.reasonPlaceholder')" style="resize: none;"></textarea>
        </div>
        <div class="opm-modal-actions">
          <button @click="showSuspendModal = false" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.suspendModal.cancel') }}</button>
          <button @click="suspendOperator" :disabled="!actionReason" class="opm-btn opm-btn--yellow" style="background: rgba(245,158,11,0.15);">{{ t('operatorManagementView.suspendModal.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Revoke Operator Access Modal -->
  <Teleport to="body">
    <div v-if="showRevokeOperatorModal && selectedAppForAction" class="opm-overlay" @click.self="showRevokeOperatorModal = false">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.revokeOpModal.title') }}</p>
        <div class="opm-warning-box">
          <p class="opm-warning-title">{{ t('operatorManagementView.revokeOpModal.warningTitle') }}</p>
          <ul class="opm-warning-list">
            <li>{{ t('operatorManagementView.revokeOpModal.warningItem1') }}</li>
            <li>{{ t('operatorManagementView.revokeOpModal.warningItem2') }}</li>
            <li>{{ t('operatorManagementView.revokeOpModal.warningItem3') }}</li>
          </ul>
        </div>
        <p style="color: #94a3b8; font-size: 13px; margin-bottom: 12px;">
          {{ t('operatorManagementView.revokeOpModal.revoking') }} <strong style="color: #e2e8f0;">{{ selectedAppForAction.name }}</strong>
        </p>
        <div style="margin-bottom: 16px;">
          <label class="opm-label">{{ t('operatorManagementView.revokeOpModal.reasonLabel') }}</label>
          <textarea v-model="actionReason" class="opm-input" rows="3" :placeholder="t('operatorManagementView.revokeOpModal.reasonPlaceholder')" style="resize: none;"></textarea>
        </div>
        <div class="opm-modal-actions">
          <button @click="showRevokeOperatorModal = false" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.revokeOpModal.cancel') }}</button>
          <button @click="revokeOperatorAccess" :disabled="!actionReason" class="opm-btn opm-btn--red" style="background: rgba(239,68,68,0.15);">{{ t('operatorManagementView.revokeOpModal.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Generate License Modal -->
  <Teleport to="body">
    <div v-if="showGenerateModal" class="opm-overlay" @click.self="showGenerateModal = false">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.generateLicenseModal.title') }}</p>
        <div class="opm-form-group">
          <label class="opm-label">{{ t('operatorManagementView.generateLicenseModal.nameLabel') }}</label>
          <input v-model="newLicense.operator_name" class="opm-input" :placeholder="t('operatorManagementView.generateLicenseModal.namePlaceholder')" />
        </div>
        <div class="opm-form-group">
          <label class="opm-label">{{ t('operatorManagementView.generateLicenseModal.didLabel') }}</label>
          <input v-model="newLicense.operator_did" class="opm-input" :placeholder="t('operatorManagementView.generateLicenseModal.didPlaceholder')" />
        </div>
        <div class="opm-form-group">
          <label for="operatormanagement-sel-1573" class="opm-label">{{ t('operatorManagementView.generateLicenseModal.tierLabel') }}</label>
          <select id="operatormanagement-sel-1573" v-model="newLicense.federation_tier" class="opm-input">
            <option value="standard">{{ t('operatorManagementView.generateLicenseModal.tierStandard') }}</option>
            <option value="enterprise">{{ t('operatorManagementView.generateLicenseModal.tierEnterprise') }}</option>
          </select>
        </div>
        <div class="opm-form-group">
          <label class="opm-label">{{ t('operatorManagementView.generateLicenseModal.minVersionLabel') }}</label>
          <input v-model="newLicense.min_image_version" class="opm-input" :placeholder="t('operatorManagementView.generateLicenseModal.minVersionPlaceholder')" />
        </div>
        <div class="opm-modal-actions" style="border-top: 1px solid rgba(255,255,255,0.06); padding-top: 16px; margin-top: 8px;">
          <button @click="showGenerateModal = false" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.generateLicenseModal.cancel') }}</button>
          <button @click="generateLicense" :disabled="!newLicense.operator_name || !newLicense.operator_did || licenseLoading" class="opm-btn opm-btn--cyan" style="background: rgba(var(--nc-primary-rgb),0.1);">
            {{ licenseLoading ? t('operatorManagementView.generateLicenseModal.generating') : t('operatorManagementView.generateLicenseModal.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Key Display Modal (shown ONCE after generation) -->
  <Teleport to="body">
    <div v-if="showKeyDisplay" class="opm-overlay">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.keyDisplayModal.title') }}</p>
        <div class="opm-warning-box" style="border-color: rgba(239,68,68,0.3);">
          <p class="opm-warning-title">{{ t('operatorManagementView.keyDisplayModal.warningTitle') }}</p>
          <p style="font-size: 12px; color: #fca5a5; margin-top: 4px;">{{ t('operatorManagementView.keyDisplayModal.warningBody') }}</p>
        </div>
        <div class="opm-key-display">
          <p style="font-family: monospace; font-size: 13px; color: #4ade80; line-height: 1.6; word-break: break-all;">{{ generatedKey }}</p>
        </div>
        <div class="opm-modal-actions">
          <button @click="copyToClipboard(generatedKey)" class="opm-btn opm-btn--cyan" style="background: rgba(var(--nc-primary-rgb),0.1);">{{ t('operatorManagementView.keyDisplayModal.copy') }}</button>
          <button @click="showKeyDisplay = false; generatedKey = ''" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.keyDisplayModal.close') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Revoke License Modal -->
  <Teleport to="body">
    <div v-if="showRevokeLicenseModal && selectedLicenseForRevoke" class="opm-overlay" @click.self="showRevokeLicenseModal = false">
      <div class="opm-modal">
        <p class="opm-modal-title">{{ t('operatorManagementView.revokeLicenseModal.title') }}</p>
        <p style="font-size: 13px; color: #d1d5db; margin-bottom: 16px;">
          {{ t('operatorManagementView.revokeLicenseModal.body') }} <strong style="color: #e2e8f0;">{{ selectedLicenseForRevoke.operator_name }}</strong>.
        </p>
        <div style="margin-bottom: 16px;">
          <label class="opm-label">{{ t('operatorManagementView.revokeLicenseModal.reasonLabel') }}</label>
          <textarea v-model="revokeReason" class="opm-input" rows="3" :placeholder="t('operatorManagementView.revokeLicenseModal.reasonPlaceholder')" style="resize: none;"></textarea>
        </div>
        <div class="opm-modal-actions" style="border-top: 1px solid rgba(255,255,255,0.06); padding-top: 16px; margin-top: 8px;">
          <button @click="showRevokeLicenseModal = false; revokeReason = ''" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.revokeLicenseModal.cancel') }}</button>
          <button @click="revokeLicenseConfirm" :disabled="!revokeReason" class="opm-btn opm-btn--red" style="background: rgba(239,68,68,0.15);">{{ t('operatorManagementView.revokeLicenseModal.confirm') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- f050: Rotated Pull Token Display Modal -->
  <Teleport to="body">
    <div v-if="showRotatedTokenModal" class="opm-overlay" @click.self="showRotatedTokenModal = false">
      <div class="opm-modal" style="max-width: 520px;">
        <p class="opm-modal-title" style="color:#f59e0b;">{{ t('operatorManagementView.rotatedTokenModal.title') }}</p>
        <p style="color:#f59e0b;font-size:0.75rem;margin-bottom:0.75rem;">{{ t('operatorManagementView.rotatedTokenModal.warning') }}</p>
        <div class="opm-key-display">
          <p style="font-family:monospace;font-size:13px;color:#4ade80;line-height:1.6;word-break:break-all;user-select:all;">{{ rotatedToken }}</p>
        </div>
        <div class="opm-modal-actions">
          <button @click="copyToClipboard(rotatedToken)" class="opm-btn opm-btn--cyan" style="background:rgba(var(--nc-primary-rgb),0.1);">{{ t('operatorManagementView.rotatedTokenModal.copy') }}</button>
          <button @click="showRotatedTokenModal = false" class="opm-btn opm-btn--ghost">{{ t('operatorManagementView.rotatedTokenModal.close') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</div>
  <!-- D5: Lifecycle Modal — 4-layer state stack + drift flags -->
  <Teleport to="body">
    <div v-if="showLifecycleModal && selectedLifecycle" class="opm-modal-backdrop" @click.self="closeLifecycleModal">
      <div class="opm-modal opm-lifecycle-modal">
        <div class="opm-modal-header">
          <h3>{{ t('operatorManagementView.lifecycleModal.title', { name: selectedLifecycle.application.name }) }}</h3>
          <button class="opm-modal-close" @click="closeLifecycleModal">&times;</button>
        </div>

        <div v-if="selectedLifecycle.drift_flags.length > 0" class="opm-lc-drift">
          <div class="opm-lc-drift-title">
            <span aria-hidden="true">&#9888;</span>
            {{ selectedLifecycle.drift_flags.length === 1 ? t('operatorManagementView.lifecycleModal.driftFlag1') : t('operatorManagementView.lifecycleModal.driftFlagN', { count: selectedLifecycle.drift_flags.length }) }}
          </div>
          <ul>
            <li v-for="flag in selectedLifecycle.drift_flags" :key="flag">
              <code>{{ flag }}</code> — {{ driftLabel(flag) }}
            </li>
          </ul>
        </div>

        <div class="opm-lc-stack">
          <!-- Layer 1: Application -->
          <div class="opm-lc-layer">
            <div class="opm-lc-layer-label">{{ t('operatorManagementView.lifecycleModal.tagApplication') }}</div>
            <div class="opm-lc-layer-body">
              <div class="opm-lc-pk">{{ selectedLifecycle.application.name }}</div>
              <div class="opm-lc-meta">
                <span>id: <code>{{ selectedLifecycle.application.id }}</code></span>
                <span>deployment: {{ selectedLifecycle.application.cloud_hosted ? t('operatorManagementView.lifecycleModal.deploymentCloud') : t('operatorManagementView.lifecycleModal.deploymentVps') }}</span>
              </div>
              <div class="opm-lc-badges">
                <span :class="['opm-pill', `opm-pill--${selectedLifecycle.application.status}`]">{{ selectedLifecycle.application.status }}</span>
                <span v-if="selectedLifecycle.application.activated_at" class="opm-lc-ts">{{ t('operatorManagementView.lifecycleModal.activated', { ago: dayjs(selectedLifecycle.application.activated_at).fromNow() }) }}</span>
                <span v-if="selectedLifecycle.application.revoked_at" class="opm-lc-ts opm-lc-ts--bad">{{ t('operatorManagementView.lifecycleModal.revoked', { ago: dayjs(selectedLifecycle.application.revoked_at).fromNow() }) }}</span>
              </div>
            </div>
          </div>

          <!-- Layer 2: Federation License -->
          <div class="opm-lc-layer">
            <div class="opm-lc-layer-label">{{ t('operatorManagementView.lifecycleModal.tagLicense') }}</div>
            <div v-if="selectedLifecycle.federation_license" class="opm-lc-layer-body">
              <div class="opm-lc-pk">{{ selectedLifecycle.federation_license.license_key_prefix }}…</div>
              <div class="opm-lc-meta">
                <span>did: <code>{{ selectedLifecycle.federation_license.operator_did }}</code></span>
                <span>tier: {{ selectedLifecycle.federation_license.federation_tier }}</span>
                <span>events: {{ selectedLifecycle.federation_license.event_count }}</span>
              </div>
              <div class="opm-lc-badges">
                <span :class="['opm-pill', `opm-pill--${selectedLifecycle.federation_license.status}`]">{{ selectedLifecycle.federation_license.status }}</span>
                <span v-if="selectedLifecycle.federation_license.last_seen_at" class="opm-lc-ts">{{ t('operatorManagementView.lifecycleModal.lastSeen', { ago: dayjs(selectedLifecycle.federation_license.last_seen_at).fromNow() }) }}</span>
                <span v-else class="opm-lc-ts opm-lc-ts--dim">{{ t('operatorManagementView.lifecycleModal.neverPresented') }}</span>
                <span v-if="selectedLifecycle.federation_license.suspended_at" class="opm-lc-ts opm-lc-ts--warn">{{ t('operatorManagementView.lifecycleModal.suspended', { ago: dayjs(selectedLifecycle.federation_license.suspended_at).fromNow() }) }}</span>
                <span v-if="selectedLifecycle.federation_license.revoked_at" class="opm-lc-ts opm-lc-ts--bad">{{ t('operatorManagementView.lifecycleModal.revoked', { ago: dayjs(selectedLifecycle.federation_license.revoked_at).fromNow() }) }}</span>
              </div>
            </div>
            <div v-else class="opm-lc-layer-empty">{{ t('operatorManagementView.lifecycleModal.noLicense') }}</div>
          </div>

          <!-- Layer 3: Peer Registry -->
          <div class="opm-lc-layer">
            <div class="opm-lc-layer-label">{{ t('operatorManagementView.lifecycleModal.tagPeer') }}</div>
            <div v-if="selectedLifecycle.peer_registry" class="opm-lc-layer-body">
              <div class="opm-lc-pk">{{ selectedLifecycle.peer_registry.name }}</div>
              <div class="opm-lc-meta">
                <span>url: <code>{{ selectedLifecycle.peer_registry.base_url }}</code></span>
              </div>
              <div class="opm-lc-badges">
                <span :class="['opm-pill', selectedLifecycle.peer_registry.status === 'ACTIVE' ? 'opm-pill--approved' : 'opm-pill--suspended']">{{ selectedLifecycle.peer_registry.status }}</span>
                <span v-if="selectedLifecycle.peer_registry.last_synced_at" class="opm-lc-ts">{{ t('operatorManagementView.lifecycleModal.lastSynced', { ago: dayjs(selectedLifecycle.peer_registry.last_synced_at).fromNow() }) }}</span>
              </div>
            </div>
            <div v-else class="opm-lc-layer-empty">{{ t('operatorManagementView.lifecycleModal.noPeer') }}</div>
          </div>

          <!-- Layer 4: Cloud -->
          <div class="opm-lc-layer">
            <div class="opm-lc-layer-label">{{ t('operatorManagementView.lifecycleModal.tagCloud') }}</div>
            <div v-if="selectedLifecycle.cloud" class="opm-lc-layer-body">
              <div class="opm-lc-pk">{{ selectedLifecycle.cloud.cloud_url || '—' }}</div>
              <div class="opm-lc-meta">
                <span v-if="selectedLifecycle.cloud.cloud_port_base">ports: {{ selectedLifecycle.cloud.cloud_port_base }}–{{ selectedLifecycle.cloud.cloud_port_base + 10 }}</span>
                <span v-if="selectedLifecycle.cloud.cloud_stack_dir">dir: <code>{{ selectedLifecycle.cloud.cloud_stack_dir }}</code></span>
              </div>
              <div class="opm-lc-badges">
                <span v-if="selectedLifecycle.cloud.cloud_torn_down_at" class="opm-pill opm-pill--revoked">{{ t('operatorManagementView.lifecycleModal.pillTornDown') }}</span>
                <span v-else class="opm-pill opm-pill--approved">{{ t('operatorManagementView.lifecycleModal.pillProvisioned') }}</span>
                <span v-if="selectedLifecycle.cloud.cloud_provisioned_at" class="opm-lc-ts">{{ t('operatorManagementView.lifecycleModal.provisioned', { ago: dayjs(selectedLifecycle.cloud.cloud_provisioned_at).fromNow() }) }}</span>
              </div>
            </div>
            <div v-else class="opm-lc-layer-empty">{{ t('operatorManagementView.lifecycleModal.notCloudHosted') }}</div>
          </div>
        </div>

        <div class="opm-modal-footer">
          <button class="opm-btn opm-btn--cyan" @click="closeLifecycleModal">{{ t('operatorManagementView.lifecycleModal.close') }}</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §2026-06-16: Operator Identity modal — reconcile prior-rename residue + Lane-B re-slug -->
  <Teleport to="body">
    <div v-if="showIdentityModal && identityOp" class="opm-modal-backdrop" @click.self="closeIdentityModal">
      <div class="opm-modal opm-identity-modal">
        <div class="opm-modal-header">
          <h3>// OPERATOR IDENTITY — {{ identityOp.name }}</h3>
          <button class="opm-modal-close" @click="closeIdentityModal">&times;</button>
        </div>

        <div class="opm-id-tabs">
          <button :class="['opm-id-tab', { 'opm-id-tab--active': idTab === 'reconcile' }]" @click="idTab = 'reconcile'">Reconcile residue</button>
          <button :class="['opm-id-tab', { 'opm-id-tab--active': idTab === 'rename' }]" @click="idTab = 'rename'">Rename (Lane B)</button>
        </div>

        <!-- RECONCILE -->
        <div v-if="idTab === 'reconcile'" class="opm-id-body">
          <p class="opm-id-help">
            Repairs residue from a <strong>prior in-place rename</strong> — ghost old-slug peer rows, stale
            federated-card <code>source_registry</code> SPIFFE, and canary master rows — fleet-wide via one
            <code>OperatorRenamed</code> event (each frame converges its own rows). Idempotent. Run a dry-run first.
          </p>
          <div class="opm-id-grid">
            <div>
              <label class="opm-label">Previous slug (renamed FROM)</label>
              <input v-model="idOldSlug" class="opm-input" placeholder="e.g. op-singapore" spellcheck="false" />
            </div>
            <div>
              <label class="opm-label">Current slug (renamed TO)</label>
              <input v-model="idNewSlug" class="opm-input" placeholder="e.g. op-losangeles" spellcheck="false" />
            </div>
          </div>
          <div class="opm-form-group" style="margin-top:10px;">
            <label class="opm-label">Type the current slug to apply a LIVE reconcile</label>
            <input v-model="idReconcileConfirm" class="opm-input" :placeholder="idNewSlug || 'current slug'" spellcheck="false" />
          </div>
          <p v-if="idReconError" class="opm-id-error">{{ idReconError }}</p>
          <div v-if="idReconResult" class="opm-id-result">
            <div class="opm-id-result-head">
              {{ idReconResult.status === 'applied' ? '✓ applied' : 'dry-run preview' }}
              <span class="opm-lc-ts">· fanout {{ idReconResult.fanout_emitted ? 'emitted' : 'skipped' }}</span>
            </div>
            <div class="opm-id-kv" v-for="(v, k) in (idReconResult.local_apply || {})" :key="k"><span>{{ k }}</span><code>{{ v }}</code></div>
          </div>
          <div class="opm-modal-actions" style="margin-top:14px;">
            <button class="opm-btn opm-btn--ghost" @click="closeIdentityModal">Close</button>
            <button class="opm-btn opm-btn--cyan" :disabled="idReconBusy" @click="runReconcile(false)">{{ idReconBusy ? 'Working…' : 'Dry-run preview' }}</button>
            <button class="opm-btn opm-btn--violet" :disabled="idReconBusy || !idOldSlug.trim() || idReconcileConfirm.trim() !== idNewSlug.trim()" @click="runReconcile(true)">Apply reconcile</button>
          </div>
        </div>

        <!-- RENAME (Lane B) -->
        <div v-else class="opm-id-body">
          <div class="opm-id-warn">
            <strong>Decommission-grade.</strong> Re-slugs the operator's load-bearing SPIFFE identity — an 8-phase
            fleet-wide cascade. For a human-facing name use the zero-downtime Lane-A self-rename instead. Dry-run runs
            quiesce + snapshot + plan only (no mutation). A real run additionally requires server env
            <code>OPERATOR_RENAME_ALLOW_MUTATING=true</code>.
          </div>
          <div class="opm-form-group" style="margin-top:10px;">
            <label class="opm-label">New slug</label>
            <input v-model="idRenameNew" class="opm-input" placeholder="new-slug [a-z0-9-], 3–40 chars" spellcheck="false" />
          </div>
          <div class="opm-form-group">
            <label class="opm-label">Type the current slug &quot;{{ identityOp.name }}&quot; to EXECUTE a real rename</label>
            <input v-model="idRenameConfirm" class="opm-input" :placeholder="identityOp.name" spellcheck="false" />
          </div>
          <p v-if="idRenameError" class="opm-id-error">{{ idRenameError }}</p>

          <div v-if="idRenameStatus && idRenameStatus.state !== 'none'" class="opm-id-result">
            <div class="opm-id-result-head">
              cascade: <span :class="['opm-pill', renameStatePill(idRenameStatus.state)]">{{ idRenameStatus.state }}</span>
              <span v-if="idRenameStatus.dry_run" class="opm-lc-ts">· dry-run</span>
              <span v-if="idRenamePollTimer" class="opm-lc-ts">· polling…</span>
            </div>
            <div v-if="idRenameStatus.note" style="font-size:11px;color:#cbd5e1;margin-top:4px;">{{ idRenameStatus.note }}</div>
            <div v-if="idRenameStatus.error" style="font-size:11px;color:#f87171;margin-top:4px;">{{ idRenameStatus.error }}</div>
            <div v-if="Array.isArray(idRenameStatus.phases) && idRenameStatus.phases.length" style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">
              <span v-for="(ph, i) in idRenameStatus.phases" :key="i" class="opm-pill" style="background:rgba(99,102,241,0.12);color:#a5b4fc;">{{ ph.state }}</span>
            </div>
          </div>

          <div class="opm-modal-actions" style="margin-top:14px;">
            <button class="opm-btn opm-btn--ghost" @click="closeIdentityModal">Close</button>
            <button class="opm-btn opm-btn--blue" :disabled="idRenameBusy" @click="refreshRenameStatus(false)">Refresh status</button>
            <button class="opm-btn opm-btn--cyan" :disabled="idRenameBusy || !idRenameNew.trim()" @click="runRename(false)">{{ idRenameBusy ? 'Working…' : 'Dry-run cascade' }}</button>
            <button class="opm-btn opm-btn--red" :disabled="idRenameBusy || !idRenameNew.trim() || idRenameConfirm.trim() !== (identityOp.name || '')" @click="runRename(true)">Execute rename</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- OPM1 (audit 2026-05-07): single themed confirm modal driven by themeConfirm() helper -->
  <ConfirmActionModal
    :show="confirmShow"
    :title="confirmOpts.title"
    :message="confirmOpts.message"
    :tone="confirmOpts.tone"
    :confirm-text="confirmOpts.confirmText"
    :cancel-text="confirmOpts.cancelText"
    :busy-text="confirmOpts.busyText"
    :busy="confirmBusy"
    :warning="confirmOpts.warning"
    :reason-required="confirmOpts.reasonRequired"
    :reason-optional="confirmOpts.reasonOptional"
    :reason-min-length="confirmOpts.reasonMinLength"
    :reason-placeholder="confirmOpts.reasonPlaceholder"
    @close="_onConfirmModalClose"
    @confirm="_onConfirmModalConfirm"
  />
</template>

<style scoped>
/* ── Page Layout ── */
.opm-page { padding: 24px 32px; max-width: 1400px; }
.opm-header { margin-bottom: 24px; }
.opm-title { font-size: 24px; font-weight: 700; color: #e2e8f0; margin: 0; }
.opm-subtitle { font-size: 13px; color: #75859b; margin-top: 4px; }  /* §FESUITE: 4.76:1 on the darkest measured row (#64748b was 3.75-4.1:1) */

/* ── Stats Grid ── */
.opm-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 24px; }
.opm-stat { background: rgba(15,15,20,0.6); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 16px; text-align: center; }
.opm-stat-val { font-size: 28px; font-weight: 700; display: block; }
.opm-stat-lbl { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #75859b; }
.opm-stat--amber .opm-stat-val { color: #f59e0b; }
.opm-stat--green .opm-stat-val { color: #10b981; }
.opm-stat--yellow .opm-stat-val { color: #fbbf24; }
.opm-stat--red .opm-stat-val { color: #ef4444; }
.opm-stat--cyan .opm-stat-val { color: var(--nc-primary); }

/* ── Sections ── */
.opm-section { background: rgba(15,15,20,0.4); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 20px; margin-bottom: 20px; }
.opm-section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.opm-section-title { font-size: 15px; font-weight: 600; color: #e2e8f0; margin: 0; }

/* ── Tables ── */
.opm-table-wrap { overflow-x: auto; }
.opm-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.opm-table th { text-align: left; padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.08); color: #75859b; font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }
.opm-table td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #94a3b8; }
.opm-table tbody tr:hover { background: rgba(255,255,255,0.02); }

/* ── Filter Select ── */
.opm-filter { background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #94a3b8; padding: 4px 8px; font-size: 11px; border-radius: 4px; }

/* ── Pills ── */
.opm-pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
.opm-pill--pending { background: rgba(245,158,11,0.15); color: #fbbf24; }
.opm-pill--approved { background: rgba(16,185,129,0.15); color: #34d399; }
.opm-pill--active { background: rgba(16,185,129,0.15); color: #34d399; }
.opm-pill--suspended { background: rgba(245,158,11,0.15); color: #f59e0b; }
.opm-pill--revoked { background: rgba(239,68,68,0.15); color: #f87171; }
.opm-pill--rejected { background: rgba(239,68,68,0.1); color: #fca5a5; }

/* ── Buttons ── */
.opm-btn { font-size: 10px; font-weight: 600; padding: 4px 10px; border-radius: 4px; border: 1px solid transparent; cursor: pointer; background: transparent; transition: all 0.15s; letter-spacing: 0.05em; text-transform: uppercase; }
.opm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.opm-btn--green { color: #10b981; border-color: rgba(16,185,129,0.3); }
.opm-btn--green:hover:not(:disabled) { background: rgba(16,185,129,0.1); }
.opm-btn--red { color: #ef4444; border-color: rgba(239,68,68,0.3); }
.opm-btn--red:hover:not(:disabled) { background: rgba(239,68,68,0.1); }
.opm-btn--yellow { color: #f59e0b; border-color: rgba(245,158,11,0.3); }
.opm-btn--yellow:hover:not(:disabled) { background: rgba(245,158,11,0.1); }
.opm-btn--blue { color: #3b82f6; border-color: rgba(59,130,246,0.3); }
.opm-btn--blue:hover:not(:disabled) { background: rgba(59,130,246,0.1); }
.opm-btn--cyan { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb),0.3); }
.opm-btn--cyan:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.1); }
.opm-btn--ghost { color: #94a3b8; border-color: rgba(255,255,255,0.1); }
.opm-btn--ghost:hover:not(:disabled) { background: rgba(255,255,255,0.05); color: #e2e8f0; }

/* ── mTLS Banner ── */
.opm-mtls-banner { display: flex; gap: 16px; padding: 16px 20px; background: rgba(59,130,246,0.06); border: 1px solid rgba(59,130,246,0.2); border-radius: 8px; margin-bottom: 16px; }
.opm-mtls-icon { font-size: 24px; }
.opm-mtls-title { font-size: 12px; font-weight: 700; letter-spacing: 0.08em; color: #3b82f6; margin: 0 0 6px 0; }
.opm-mtls-text { font-size: 12px; color: #94a3b8; line-height: 1.5; margin: 0; }
.opm-mtls-text code { background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 3px; font-size: 11px; color: #60a5fa; }

/* ── License Stats ── */
.opm-license-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.opm-license-stat { background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 10px; text-align: center; }
.opm-license-stat-val { font-size: 22px; font-weight: 700; display: block; }
.opm-license-stat-lbl { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #75859b; }
.opm-license-stat--green .opm-license-stat-val { color: #4ade80; }
.opm-license-stat--green { border-color: rgba(74,222,128,0.15); }
.opm-license-stat--yellow .opm-license-stat-val { color: #fbbf24; }
.opm-license-stat--yellow { border-color: rgba(251,191,36,0.15); }
.opm-license-stat--red .opm-license-stat-val { color: #f87171; }
.opm-license-stat--red { border-color: rgba(248,113,113,0.15); }
.opm-license-stat--cyan .opm-license-stat-val { color: var(--nc-primary); }
.opm-license-stat--cyan { border-color: rgba(var(--nc-primary-rgb),0.15); }

/* ── Expandable Row ── */
.opm-expand-row { background: rgba(var(--nc-primary-rgb),0.03); padding: 16px 20px; }
.opm-expand-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.opm-expand-label { display: block; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #75859b; margin-bottom: 2px; }
.opm-expand-value { display: block; font-size: 12px; color: #e2e8f0; }

/* ── Docker Info ── */
.opm-docker-info { margin-top: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.06); }
.opm-docker-title { font-size: 13px; font-weight: 700; color: #e2e8f0; margin: 0 0 6px 0; }
.opm-docker-desc { font-size: 12px; color: #75859b; margin: 0 0 10px 0; }
.opm-docker-code { background: rgba(0,0,0,0.3); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 11px; color: #4ade80; line-height: 1.8; }

/* ── Modal Overlay ── */
.opm-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); z-index: 9999; display: flex; align-items: center; justify-content: center; }
.opm-modal { background: #0f1015; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 24px; max-width: 520px; width: 90%; }
.opm-modal-title { font-size: 12px; font-weight: 700; letter-spacing: 0.1em; color: #75859b; margin: 0 0 16px 0; text-transform: uppercase; }
.opm-modal-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }

/* ── Modal Form Elements ── */
.opm-label { font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #75859b; display: block; margin-bottom: 4px; }
.opm-input { width: 100%; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #e2e8f0; padding: 8px 12px; font-size: 13px; border-radius: 6px; font-family: inherit; box-sizing: border-box; }
.opm-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb),0.4); }
.opm-form-group { margin-bottom: 14px; }

/* ── Warning Box ── */
.opm-warning-box { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); padding: 12px; border-radius: 6px; margin-bottom: 12px; }
.opm-warning-title { color: #f87171; font-weight: 600; font-size: 12px; margin: 0; }
.opm-warning-list { color: #fca5a5; font-size: 11px; margin: 8px 0 0 16px; padding: 0; list-style: disc; }
.opm-warning-list li { margin-bottom: 2px; }

/* ── Key Display ── */
.opm-key-display { background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.3); border-radius: 6px; padding: 16px; margin-bottom: 16px; }

/* ── Responsive ── */
@media (max-width: 1024px) {
  .opm-expand-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .opm-stats { grid-template-columns: repeat(3, 1fr); }
  .opm-license-stats { grid-template-columns: repeat(2, 1fr); }
  .opm-page { padding: 16px; }
  .opm-expand-grid { grid-template-columns: 1fr; }
}

@media (max-width: 480px) {
  .opm-stats { grid-template-columns: repeat(2, 1fr); }
}

/* ─── Option D-light Phase D5: Lifecycle drift + modal ─────────────────── */
.opm-drift-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 20px;
}
.opm-drift-banner-left { display: flex; align-items: center; gap: 14px; }
.opm-drift-icon {
  font-size: 20px;
  color: #fbbf24;
  flex-shrink: 0;
}
.opm-drift-title { font-size: 13px; font-weight: 600; color: #fbbf24; }
.opm-drift-sub { font-size: 11px; color: #cbd5e1; margin-top: 2px; }
.opm-drift-clean {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: #75859b;
  background: rgba(16, 185, 129, 0.04);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 6px;
  padding: 6px 12px;
  margin-bottom: 20px;
}
.opm-drift-clean-icon { color: #34d399; font-weight: 700; }
.opm-btn-link {
  background: none; border: none; color: #60a5fa; cursor: pointer;
  font-size: 11px; text-decoration: underline; padding: 0; margin-left: auto;
}
.opm-btn-link:disabled { color: #64748b; cursor: not-allowed; }

.opm-drift-cell {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
}
.opm-drift-cell--has {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.4);
}
.opm-drift-cell--has:hover { background: rgba(245, 158, 11, 0.2); }
.opm-drift-cell--clean {
  color: #75859b;
  font-size: 14px;
  padding: 2px 10px;
}
.opm-drift-cell--clean:hover { background: rgba(148, 163, 184, 0.08); color: #94a3b8; }

/* Modal (reuses existing modal backdrop/header/footer conventions) */
.opm-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.72);
  display: flex; align-items: center; justify-content: center;
  z-index: 9999;
  padding: 32px;
}
.opm-modal {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 25px 50px -12px rgba(0,0,0,0.9);
}
.opm-lifecycle-modal { width: 100%; max-width: 760px; }
.opm-modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.opm-modal-header h3 { margin: 0; font-size: 16px; font-weight: 600; color: #e2e8f0; }
.opm-modal-close {
  background: none; border: none; color: #75859b;
  font-size: 28px; line-height: 1; cursor: pointer; padding: 0 4px;
}
.opm-modal-close:hover { color: #e2e8f0; }
.opm-modal-footer {
  padding: 14px 24px;
  border-top: 1px solid rgba(255,255,255,0.06);
  display: flex; justify-content: flex-end;
}

.opm-lc-drift {
  background: rgba(245, 158, 11, 0.08);
  border-bottom: 1px solid rgba(245, 158, 11, 0.3);
  padding: 14px 24px;
}
.opm-lc-drift-title {
  display: flex; align-items: center; gap: 8px;
  color: #fbbf24; font-weight: 600; font-size: 13px; margin-bottom: 6px;
}
.opm-lc-drift ul {
  margin: 0; padding-left: 24px;
  font-size: 11px; color: #cbd5e1; line-height: 1.5;
}
.opm-lc-drift code {
  background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 3px;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #fde68a;
}

.opm-lc-stack {
  padding: 16px 24px;
  display: flex; flex-direction: column; gap: 12px;
}
.opm-lc-layer {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 16px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
}
.opm-lc-layer-label {
  font-size: 10px; font-weight: 700; letter-spacing: 1px;
  color: #94a3b8;
  align-self: start;
  padding-top: 3px;
}
.opm-lc-layer-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.opm-lc-layer-empty { color: #475569; font-size: 12px; font-style: italic; align-self: center; }
.opm-lc-pk { font-size: 13px; font-weight: 600; color: #e2e8f0; word-break: break-all; }
.opm-lc-meta {
  display: flex; flex-wrap: wrap; gap: 12px;
  font-size: 10px; color: #75859b;
}
.opm-lc-meta code {
  background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 3px;
  font-family: 'IBM Plex Mono', monospace; color: #94a3b8;
}
.opm-lc-badges {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-top: 2px;
}
.opm-lc-ts { font-size: 10px; color: #75859b; }
.opm-lc-ts--dim { color: #475569; font-style: italic; }
.opm-lc-ts--warn { color: #fbbf24; }
.opm-lc-ts--bad { color: #f87171; }

@media (max-width: 600px) {
  .opm-lc-layer { grid-template-columns: 1fr; gap: 6px; }
  .opm-lc-layer-label { padding-top: 0; }
}

/* ── §2026-06-16 Operator Identity modal + stale-license recon ── */
.opm-btn--violet { color: #a78bfa; border-color: rgba(167,139,250,0.35); }
.opm-btn--violet:hover:not(:disabled) { background: rgba(167,139,250,0.12); }
.opm-identity-modal { width: 100%; max-width: 720px; }
.opm-id-tabs { display: flex; gap: 6px; padding: 14px 24px 0; }
.opm-id-tab { font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: #94a3b8; background: transparent; border: 1px solid rgba(255,255,255,0.1); border-bottom: none; border-radius: 6px 6px 0 0; padding: 7px 14px; cursor: pointer; }
.opm-id-tab--active { color: #e2e8f0; border-color: rgba(var(--nc-primary-rgb),0.5); background: rgba(var(--nc-primary-rgb),0.08); }
.opm-id-body { padding: 16px 24px 4px; border-top: 1px solid rgba(255,255,255,0.06); }
.opm-id-help { font-size: 12px; color: #94a3b8; line-height: 1.55; margin: 0 0 14px; }
.opm-id-help code, .opm-id-warn code { background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 3px; font-size: 11px; color: #93c5fd; }
.opm-id-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.opm-id-warn { font-size: 12px; color: #fcd34d; line-height: 1.55; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); border-radius: 6px; padding: 10px 12px; }
.opm-id-warn code { color: #fcd34d; }
.opm-id-error { font-size: 12px; color: #f87171; margin: 10px 0 0; }
.opm-id-result { margin-top: 12px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 10px 12px; }
.opm-id-result-head { font-size: 12px; font-weight: 600; color: #e2e8f0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.opm-id-kv { display: flex; justify-content: space-between; gap: 12px; font-size: 11px; color: #94a3b8; padding: 2px 0; }
.opm-id-kv code { color: #e2e8f0; font-family: 'IBM Plex Mono', monospace; }
@media (max-width: 560px) { .opm-id-grid { grid-template-columns: 1fr; } }

/* Live provisioning indicator (§2026-07-27) */
.opm-prov-live { display: inline-flex; align-items: center; gap: 6px; font-size: 10px; font-family: 'IBM Plex Mono', monospace; color: #22d3ee; letter-spacing: 0.04em; text-transform: uppercase; }
.opm-prov-dot { width: 6px; height: 6px; border-radius: 50%; background: #22d3ee; animation: opm-prov-pulse 1.2s ease-in-out infinite; }
@keyframes opm-prov-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.25; } }
@media (prefers-reduced-motion: reduce) { .opm-prov-dot { animation: none; } }
.opm-env { margin-top: 4px; font-size: 11px; color: #75859b; max-width: 260px; }
</style>
