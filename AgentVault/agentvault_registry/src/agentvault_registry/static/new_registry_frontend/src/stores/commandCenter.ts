import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { diagnosticsApi } from '@/services/api/diagnosticsApi'
import type {
  ActionDescriptor,
  ActionResult,
  CheckDescriptor,
  CheckResult,
  ConfigResponse,
  TargetStatus,
  TargetSummary,
} from '@/services/api/types/diagnostics'

const POLL_INTERVAL_MS = 10_000

function aggregateStatus(results: CheckResult[]): TargetStatus {
  if (!results.length) return 'unknown'
  if (results.some(r => r.status === 'fail')) return 'down'
  if (results.some(r => r.status === 'warn')) return 'degraded'
  if (results.every(r => r.status === 'ok' || r.status === 'unknown')) return 'healthy'
  return 'unknown'
}

/**
 * §CCFIX (2026-07-27) — ADVISORY TARGETS.
 * The sandbox tier is off by default (documented: auditor sandbox probes read ERROR while it is
 * down, and that is expected). Its failures were being folded into the fleet health number, so
 * the Command Center could never show green no matter how healthy production was — which trains
 * you to ignore the number. Advisory targets are still RUN and still DISPLAYED with their real
 * status; they are simply excluded from the fleet rollup, and counted separately so nothing is
 * hidden. Prefix-based so a new sandbox target inherits the behaviour automatically.
 */
// §MCPTEST30 (V0562): EMPTY. The prefix named the retired Frame-A-era sandbox tier (registry-test, seen from
// registry-a); every console now diagnoses its own frame, and on the sandbox pair its own target is "sandbox-alpha" /
// "sandbox-beta", which the prefix would have dropped from the very rollup it is the subject of. Kept as the mechanism.
const ADVISORY_TARGET_PREFIXES: string[] = []

export function isAdvisoryTarget(operatorId: string): boolean {
  const id = (operatorId || '').toLowerCase()
  return ADVISORY_TARGET_PREFIXES.some(p => id.startsWith(p))
}

export const useCommandCenterStore = defineStore('commandCenter', () => {
  const targets = ref<TargetSummary[]>([])
  /** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
  const targetsRead = ref(false)
  const checks = ref<CheckDescriptor[]>([])
  const actions = ref<ActionDescriptor[]>([])
  /** §FESUITE V0577: the remediation-action catalog's read failed (the drawer's Actions tab said "No remediation actions
   *  registered." under it, and the shared error line that named the failure was cleared by the next targets read) */
  const actionsFailed = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastRunAt = ref<string | null>(null)
  const autoRefresh = ref(false)
  const inflightTargets = ref<Set<string>>(new Set())
  const runningActions = ref<Set<string>>(new Set())
  const configByTarget = ref<Record<string, ConfigResponse>>({})
  const lastActionResult = ref<ActionResult | null>(null)

  let pollHandle: ReturnType<typeof setInterval> | null = null

  // §CCFIX — the rollup counts PRODUCTION targets only; advisory (sandbox) targets are
  // tallied separately by `advisoryIssueCount` so they stay visible without blocking green.
  const scoredTargets = computed(() =>
    targets.value.filter(t => !isAdvisoryTarget(t.operator_id)),
  )
  const fleetCheckCount = computed(() =>
    scoredTargets.value.reduce((acc, t) => acc + t.check_results.length, 0),
  )
  const fleetOkCount = computed(() =>
    scoredTargets.value.reduce(
      (acc, t) => acc + t.check_results.filter(r => r.status === 'ok').length,
      0,
    ),
  )
  const fleetFailCount = computed(() =>
    scoredTargets.value.reduce(
      (acc, t) => acc + t.check_results.filter(r => r.status === 'fail').length,
      0,
    ),
  )
  const fleetWarnCount = computed(() =>
    scoredTargets.value.reduce(
      (acc, t) => acc + t.check_results.filter(r => r.status === 'warn').length,
      0,
    ),
  )
  /** Non-OK checks on advisory targets — surfaced, never scored. */
  const advisoryIssueCount = computed(() =>
    targets.value
      .filter(t => isAdvisoryTarget(t.operator_id))
      .reduce((acc, t) => acc + t.check_results.filter(r => r.status !== 'ok').length, 0),
  )
  // §MCPTEST30 (V0561): null when nothing was measured; 0 drew a red ring over an empty fleet
  const targetsReason = ref<string | null>(null)
  const targetsReasonCode = ref<string | null>(null)
  const containersReasonCode = ref<string | null>(null)
  const fleetHealthPct = computed<number | null>(() => {
    const total = fleetCheckCount.value
    if (!total) return null
    return Math.round((fleetOkCount.value / total) * 100)
  })

  const failingChecks = computed(() => {
    const out: { target: TargetSummary; result: CheckResult }[] = []
    for (const t of targets.value) {
      for (const r of t.check_results) {
        if (r.status === 'fail' || r.status === 'warn') {
          out.push({ target: t, result: r })
        }
      }
    }
    return out.sort((a, b) => (a.result.status === 'fail' ? -1 : 1))
  })

  async function loadTargets() {
    try {
      loading.value = true
      error.value = null
      const data = await diagnosticsApi.listTargets()
      targets.value = data.targets
      targetsRead.value = true
      targetsReason.value = data.reason ?? null
      targetsReasonCode.value = data.reason_code ?? null
      containersReasonCode.value = data.containers_reason_code ?? null
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? e?.message ?? 'failed to load targets'
    } finally {
      loading.value = false
    }
  }

  async function loadChecks() {
    if (checks.value.length) return
    try {
      const data = await diagnosticsApi.listChecks()
      checks.value = data.checks
    } catch (e) {
      // non-fatal (the drawer still lists results by id), but said: an empty catch hid a broken route
      error.value = `could not load the check list: ${(e as any)?.response?.data?.detail ?? (e as any)?.message ?? e}`
    }
  }

  async function loadActions() {
    if (actions.value.length) return
    try {
      const data = await diagnosticsApi.listActions()
      actions.value = data.actions
      actionsFailed.value = false
    } catch (e) {
      // non-fatal: said here, and the Actions tab says its read failed (actionsFailed), not that there are none
      actionsFailed.value = true
      error.value = `could not load the remediation actions: ${(e as any)?.response?.data?.detail ?? (e as any)?.message ?? e}`
    }
  }

  async function loadConfig(targetId: string, force = false) {
    if (!force && configByTarget.value[targetId]) return configByTarget.value[targetId]
    try {
      const data = await diagnosticsApi.getConfig(targetId)
      configByTarget.value = { ...configByTarget.value, [targetId]: data }
      return data
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? e?.message ?? 'config load failed'
      return null
    }
  }

  function _replaceCheckResult(targetId: string, result: CheckResult) {
    const idx = targets.value.findIndex(t => t.operator_id === targetId)
    if (idx < 0) return
    const updated = { ...targets.value[idx] }
    const existing = updated.check_results.findIndex(r => r.check_id === result.check_id)
    if (existing >= 0) updated.check_results.splice(existing, 1, result)
    else updated.check_results = [...updated.check_results, result]
    targets.value.splice(idx, 1, updated)
  }

  async function runAction(actionId: string, targetId: string, dryRun = false) {
    const key = `${actionId}@${targetId}`
    if (runningActions.value.has(key)) return null
    try {
      runningActions.value = new Set([...runningActions.value, key])
      const result = await diagnosticsApi.runAction(actionId, targetId, dryRun)
      lastActionResult.value = result
      if (result.triggered_check) {
        _replaceCheckResult(targetId, result.triggered_check)
      }
      return result
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? e?.message ?? 'action invocation failed'
      return null
    } finally {
      const next = new Set(runningActions.value)
      next.delete(key)
      runningActions.value = next
    }
  }

  function isActionRunning(actionId: string, targetId: string): boolean {
    return runningActions.value.has(`${actionId}@${targetId}`)
  }

  async function runAllForTarget(targetId: string, force = false) {
    if (inflightTargets.value.has(targetId)) return
    try {
      inflightTargets.value.add(targetId)
      const data = await diagnosticsApi.runAll(targetId, force)
      const idx = targets.value.findIndex(t => t.operator_id === targetId)
      if (idx >= 0) {
        const updated = { ...targets.value[idx] }
        updated.check_results = data.results
        updated.status = aggregateStatus(data.results)
        updated.last_snapshot_at = new Date().toISOString()
        targets.value.splice(idx, 1, updated)
      }
      lastRunAt.value = new Date().toISOString()
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? e?.message ?? 'run-all failed'
    } finally {
      inflightTargets.value.delete(targetId)
    }
  }

  // §MCPTEST30 (V0562): the header's Run button reads this; a fleet run set no busy flag, so it stayed pressable mid-run
  const runningFleet = ref(false)
  async function runFleet(force = false) {
    if (runningFleet.value) return
    runningFleet.value = true
    try {
      await Promise.all(
        targets.value.map(t => runAllForTarget(t.operator_id, force)),
      )
    } finally {
      runningFleet.value = false
    }
  }

  function startAutoRefresh() {
    if (pollHandle) return
    autoRefresh.value = true
    // CC1 (audit 2026-05-07): visibility guard — pause fleet polling when tab
    // is hidden. Each cycle fans out to N target check-runs, so hidden-tab
    // wake-ups are expensive. Matches HealthMonitorUltimate / FrameManagement /
    // EigenTrustCommand pattern.
    pollHandle = setInterval(() => {
      if (document.visibilityState === 'hidden') return
      runFleet(false).catch(() => {})
    }, POLL_INTERVAL_MS)
  }

  function stopAutoRefresh() {
    autoRefresh.value = false
    if (pollHandle) {
      clearInterval(pollHandle)
      pollHandle = null
    }
  }

  function toggleAutoRefresh() {
    if (autoRefresh.value) stopAutoRefresh()
    else startAutoRefresh()
  }

  // ── Snapshot export ───────────────────────────────────────────────────
  // Bundles every diagnostic + config slice for every target into a single
  // JSON blob and triggers a download. Uses existing endpoints — no backend
  // change. Refuses to overwrite a download in-flight.
  const exporting = ref(false)
  const exportProgress = ref<{ done: number; total: number } | null>(null)

  async function downloadSnapshot() {
    if (exporting.value) return
    exporting.value = true
    exportProgress.value = { done: 0, total: 0 }
    try {
      // 1) Ensure catalogs loaded
      await Promise.all([loadTargets(), loadChecks(), loadActions()])

      const targetList = [...targets.value]
      exportProgress.value = { done: 0, total: targetList.length * 2 }

      // 2) Per-target: parallel fetch run-all + config (use force=false so we
      //    use cached results when fresh — saves time and API cost).
      const perTarget = await Promise.all(targetList.map(async (t) => {
        const [runRes, cfgRes] = await Promise.all([
          diagnosticsApi.runAll(t.operator_id, false).catch(e => ({ _error: String(e) })),
          diagnosticsApi.getConfig(t.operator_id).catch(e => ({ _error: String(e) })),
        ])
        exportProgress.value = { done: (exportProgress.value?.done ?? 0) + 2, total: targetList.length * 2 }
        // §CCFIX — derive status FROM THE RUN WE JUST FETCHED, not from store state.
        // `loadTargets()` above resets every target to status='unknown'/check_results=[], and
        // the fetched run was only ever attached as `run` — so the exported file said
        // "unknown / 0 checks / 0% health" while carrying 130 real results inline. A snapshot
        // must be internally consistent: its summary has to describe its own contents.
        const runResults: CheckResult[] = Array.isArray((runRes as any)?.results)
          ? (runRes as any).results
          : []
        return {
          operator_id: t.operator_id,
          display_name: t.display_name,
          frame: t.frame,
          role: t.role,
          cloud_url: t.cloud_url,
          advisory: isAdvisoryTarget(t.operator_id),
          status: runResults.length ? aggregateStatus(runResults) : t.status,
          last_snapshot_at: runResults.length
            ? new Date().toISOString()
            : t.last_snapshot_at,
          run: runRes,
          config: cfgRes,
        }
      }))

      // Roll the summary up from the exported runs themselves (production targets only —
      // advisory/sandbox issues are reported in their own field so nothing is hidden).
      const tally = (pred: (t: any) => boolean, status?: string) =>
        perTarget.filter(pred).reduce((acc, t) => {
          const rs: CheckResult[] = Array.isArray((t.run as any)?.results) ? (t.run as any).results : []
          return acc + (status ? rs.filter(r => r.status === status).length : rs.length)
        }, 0)
      const isProd = (t: any) => !t.advisory
      const snapChecks = tally(isProd)
      const snapOk = tally(isProd, 'ok')

      // 3) Build snapshot
      const snapshot = {
        snapshot_at: new Date().toISOString(),
        snapshot_kind: 'theprotocol-command-center-v1',
        registry_origin: window.location.origin,
        fleet_summary: {
          total_targets: targetList.length,
          scored_targets: perTarget.filter(isProd).length,
          total_checks: snapChecks,
          ok: snapOk,
          warn: tally(isProd, 'warn'),
          fail: tally(isProd, 'fail'),
          unknown: tally(isProd, 'unknown'),
          health_pct: snapChecks ? Math.round((snapOk / snapChecks) * 100) : 0,
          advisory_targets: perTarget.filter(t => t.advisory).map(t => t.operator_id),
          advisory_non_ok: tally((t: any) => t.advisory) - tally((t: any) => t.advisory, 'ok'),
          note: 'health_pct covers production targets only; advisory (sandbox) targets are run and reported but not scored.',
        },
        checks_catalog: checks.value,
        actions_catalog: actions.value,
        targets: perTarget,
      }

      // 4) Trigger download
      const json = JSON.stringify(snapshot, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      const a = document.createElement('a')
      a.href = url
      a.download = `command-center-snapshot-${stamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      // Defer revoke so the browser can read the blob first
      setTimeout(() => URL.revokeObjectURL(url), 4000)
    } catch (e: any) {
      error.value = e?.message ?? 'snapshot export failed'
    } finally {
      exporting.value = false
      exportProgress.value = null
    }
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout.
  function $reset() {
    targets.value = []
    targetsRead.value = false
    checks.value = []
    actions.value = []
    actionsFailed.value = false
    loading.value = false
    error.value = null
    lastRunAt.value = null
    autoRefresh.value = false
    inflightTargets.value = new Set()
    runningActions.value = new Set()
    configByTarget.value = {}
    lastActionResult.value = null
  }

  return {
    targets,
    targetsRead,
    checks,
    actions,
    actionsFailed,
    loading,
    error,
    lastRunAt,
    autoRefresh,
    inflightTargets,
    runningActions,
    configByTarget,
    lastActionResult,
    $reset,
    fleetCheckCount,
    fleetOkCount,
    fleetFailCount,
    fleetWarnCount,
    advisoryIssueCount,
    scoredTargets,
    fleetHealthPct,
    targetsReason,
    targetsReasonCode,
    containersReasonCode,
    failingChecks,
    loadTargets,
    loadChecks,
    loadActions,
    loadConfig,
    runAllForTarget,
    runFleet,
    runningFleet,
    runAction,
    isActionRunning,
    startAutoRefresh,
    stopAutoRefresh,
    toggleAutoRefresh,
    exporting,
    exportProgress,
    downloadSnapshot,
  }
})
