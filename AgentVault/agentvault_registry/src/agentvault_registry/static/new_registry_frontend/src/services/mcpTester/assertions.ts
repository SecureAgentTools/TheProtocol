/**
 * §MCPTEST30: a row's strict-mode verdict, axis by axis, and the BUG-FIND taxonomy (moved out of AdminMcpTester.vue so
 * they are unit-tested; the page passes its own words in as `say`).
 *
 * Six axes are read from the row's own fields: HTTP status, response shape (healthy or the error names a key, a type or
 * a missing field), tier-set membership, latency against the prior-3 median, the 5 s eventual-consistency budget, and a
 * skip's rationale. Six come from the backend per row (`row.axes`, since pass73.3.19): the read-after-write side effect,
 * the EventStore emission, the audit row, the wrong-tier rejection, the cross-frame parity and the request against its
 * route. A backend axis whose detector the run did not measure reads "not measured" (a run before V0541 graded it pass),
 * except a fail; a run that carries no axes says "not recorded". `total` leaves the skipped axes out.
 */
import type { McpTesterToolRow } from '@/services/api/mcpTester'
import type { DetectorKey } from './runReading'

export type AxisState = 'pass' | 'fail' | 'skip' | 'unknown'
export interface AxisResult { name: string; state: AxisState; detail?: string }
export interface AxisSummary { axes: AxisResult[]; pass_count: number; total: number }

/** How the page says a key: its translate function and its parameterised one. */
export interface Say {
  t: (key: string, fallback: string) => string
  tp: (key: string, fallback: string, params: Record<string, unknown>) => string
}

/** the row axis each detector grades */
export const AXIS_DETECTOR: Record<string, DetectorKey> = {
  wrong_tier_rejection: 'auth_matrix', cross_frame_parity: 'cross_frame', wrapper_route_drift: 'wrapper_route',
}

export function assertionsForRow(row: McpTesterToolRow, detectorsRun: Partial<Record<DetectorKey, boolean>>, say: Say): AxisSummary {
  const axes: AxisResult[] = []

  // 1. HTTP status
  if (row.status === 0 || row.status === undefined || row.status === null) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: row.skipped ? 'skip' : 'unknown', detail: say.t('mcpTester.axes.noStatus', 'no status captured') })
  } else if (row.status >= 200 && row.status < 300) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'pass', detail: `${row.status}` })
  } else if (row.status === 401 || row.status === 403) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'fail', detail: say.tp('mcpTester.axes.authRejected', '{status}: the auth gate refused it', { status: row.status }) })
  } else if (row.status === 404) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'fail', detail: say.tp('mcpTester.axes.notFound', '{status}: endpoint not found', { status: row.status }) })
  } else if (row.status >= 400 && row.status < 500) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'fail', detail: say.tp('mcpTester.axes.clientError', '{status}: client error', { status: row.status }) })
  } else if (row.status >= 500) {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'fail', detail: say.tp('mcpTester.axes.serverError', '{status}: server error', { status: row.status }) })
  } else {
    axes.push({ name: say.t('mcpTester.detail.httpStatus', 'HTTP status'), state: 'pass', detail: `${row.status}` })
  }

  // 2. Response shape
  if (row.skipped) {
    axes.push({ name: say.t('mcpTester.axes.shape', 'Response shape'), state: 'skip', detail: row.skip_reason || say.t('mcpTester.axes.skipped', 'skipped') })
  } else if (row.healthy) {
    axes.push({ name: say.t('mcpTester.axes.shape', 'Response shape'), state: 'pass', detail: say.t('mcpTester.axes.shapeMatched', 'matched the expected keys and types') })
  } else if (row.error && /shape|key|missing|type|expected/i.test(row.error)) {
    axes.push({ name: say.t('mcpTester.axes.shape', 'Response shape'), state: 'fail', detail: row.error.slice(0, 80) })
  } else {
    axes.push({ name: say.t('mcpTester.axes.shape', 'Response shape'), state: row.error ? 'fail' : 'unknown', detail: row.error?.slice(0, 80) })
  }

  // 3. Tier-set membership
  if (row.tier) {
    axes.push({ name: say.t('mcpTester.axes.tierSet', 'Tier-set membership'), state: 'pass', detail: `tier=${row.tier}` })
  } else {
    axes.push({ name: say.t('mcpTester.axes.tierSet', 'Tier-set membership'), state: 'unknown', detail: say.t('mcpTester.axes.noTier', 'no tier captured') })
  }

  // 4. Latency baseline
  if (row.latency_regression) {
    const mult = row.latency_baseline_ms ? (row.elapsed / row.latency_baseline_ms).toFixed(1) : '?'
    axes.push({
      name: say.t('mcpTester.axes.latency', 'Latency baseline'),
      state: 'fail',
      detail: say.tp('mcpTester.axes.latencyFail', '{ms}ms = {factor}× the median of the prior 3 ({baseline}ms)', { ms: row.elapsed, factor: mult, baseline: row.latency_baseline_ms || 0 }),
    })
  } else if (typeof row.elapsed === 'number' && row.elapsed > 0) {
    axes.push({
      name: say.t('mcpTester.axes.latency', 'Latency baseline'),
      state: 'pass',
      detail: row.latency_baseline_ms ? say.tp('mcpTester.axes.latencyPass', '{ms}ms (baseline {baseline}ms)', { ms: row.elapsed, baseline: row.latency_baseline_ms }) : `${row.elapsed}ms`,
    })
  } else {
    axes.push({ name: say.t('mcpTester.axes.latency', 'Latency baseline'), state: 'unknown' })
  }

  // 5. Eventual-consistency budget (5s soft default)
  if (typeof row.elapsed === 'number' && row.elapsed > 0) {
    if (row.elapsed < 5000) {
      axes.push({ name: say.t('mcpTester.axes.budget', 'Eventual-consistency budget'), state: 'pass', detail: `${row.elapsed}ms < 5s` })
    } else {
      axes.push({ name: say.t('mcpTester.axes.budget', 'Eventual-consistency budget'), state: 'fail', detail: say.tp('mcpTester.axes.budgetFail', '{ms}ms exceeded the 5 s soft budget', { ms: row.elapsed }) })
    }
  } else {
    axes.push({ name: say.t('mcpTester.axes.budget', 'Eventual-consistency budget'), state: 'unknown' })
  }

  // 6. Skip rationale
  if (row.skipped) {
    if (row.skip_reason) {
      axes.push({ name: say.t('mcpTester.detail.skipRationale', 'Skip rationale'), state: 'pass', detail: row.skip_reason.slice(0, 80) })
    } else {
      axes.push({ name: say.t('mcpTester.detail.skipRationale', 'Skip rationale'), state: 'fail', detail: say.t('mcpTester.axes.skipNoReason', 'skipped without a reason (counts against the pass rate)') })
    }
  } else {
    axes.push({ name: say.t('mcpTester.detail.skipRationale', 'Skip rationale'), state: 'skip', detail: say.t('mcpTester.axes.notSkipped', 'the tool was not skipped') })
  }

  // pass73.3.19 (2026-05-28) — Backend-side axes now plumbed via `row.axes`.
  // Backend computes per-tool pass/fail/skip/na for 6 axes (mcp_tester.py
  // post-processes summary aggregates into per-row dict). FE reads them
  // verbatim. Falls back to "unknown" if row.axes missing (older runs).
  const rowAxes: any = (row as any).axes || {}
  const axisDefs: Array<{ key: string; name: string }> = [
    { key: 'side_effect',           name: say.t('mcpTester.axes.sideEffect', 'Read-after-write side-effect') },
    { key: 'event_emission',        name: say.t('mcpTester.axes.eventEmission', 'EventStore emission') },
    { key: 'audit_log_row',         name: say.t('mcpTester.axes.auditRow', 'Audit log row') },
    { key: 'wrong_tier_rejection',  name: say.t('mcpTester.axes.wrongTier', 'Wrong-tier rejection') },
    { key: 'cross_frame_parity',    name: say.t('mcpTester.axes.crossFrame', 'Cross-frame parity') },
    { key: 'wrapper_route_drift',   name: say.t('mcpTester.axes.wrapperRoute', 'Request vs its route (wrapper↔route)') },
  ]
  for (const def of axisDefs) {
    const ax = rowAxes[def.key]
    if (ax && typeof ax === 'object') {
      // 'na' = not applicable (read-only tool can't have side-effect, etc.). §MCPTEST30 (V0539): the backend's word,
      // read as a string: cast to AxisState first, the comparison with 'na' had no overlap for the type checker
      const raw = String(ax.state)
      // §MCPTEST30 (V0541): a run recorded before the axes said "not measured" graded a detector's axis "pass" even
      // where the detector never ran (the suite's own record says which ran); it reads as not measured here
      const det = AXIS_DETECTOR[def.key]
      const unmeasured = !!det && raw !== 'fail' && !detectorsRun[det]
      const normalizedState: AxisState = raw === 'na' || unmeasured ? 'skip' : (raw as AxisState)
      axes.push({
        name:   def.name,
        state:  normalizedState,
        detail: unmeasured
          ? say.t('mcpTester.drift.axisNotRun', 'not measured: this run\'s suite does not run this check')
          : ax.detail || (raw === 'na' ? say.t('mcpTester.axes.notApplicable', 'not applicable for this tool') : ''),
      })
    } else {
      // §MCPTEST30 (V0541): a console run's steps, or a run recorded before the axes existed, carry none
      axes.push({
        name:   def.name,
        state:  'unknown',
        detail: say.t('mcpTester.drift.axisNotRecorded', 'not recorded for this run'),
      })
    }
  }

  return {
    axes,
    pass_count: axes.filter(a => a.state === 'pass').length,
    total: axes.filter(a => a.state !== 'skip').length,
  }
}

/** The kinds of defect a BUG-FIND names, read from its error text. */
export type BugFindKind = 'silentNoop' | 'missingEvent' | 'missingAudit' | 'shapeDrift' | 'contract'

export const BUG_FIND_TEXT: Record<BugFindKind | 'unknown', { key: string; fallback: string }> = {
  silentNoop: { key: 'mcpTester.banner.catSilentNoop', fallback: 'silent NO-OP' },
  missingEvent: { key: 'mcpTester.banner.catMissingEvent', fallback: 'missing event emission' },
  missingAudit: { key: 'mcpTester.banner.catMissingAudit', fallback: 'missing audit row' },
  shapeDrift: { key: 'mcpTester.banner.catShapeDrift', fallback: 'response-shape drift' },
  contract: { key: 'mcpTester.banner.catContract', fallback: 'contract violation' },
  unknown: { key: 'mcpTester.banner.catUnknown', fallback: 'a wrapper or endpoint defect' },
}

/** The kind of one BUG-FIND (first match wins: a write that did not persist is a silent NO-OP before anything else). */
export function bugFindKind(error: string | null | undefined): BugFindKind {
  const err = (error || '').toLowerCase()
  if (err.includes('did not persist') || err.includes('silent no-op')) return 'silentNoop'
  if (err.includes('missing_event') || err.includes('expected event')) return 'missingEvent'
  if (err.includes('missing audit') || err.includes('audit row')) return 'missingAudit'
  if (err.includes('shape') || err.includes('expect_keys')) return 'shapeDrift'
  return 'contract'
}

/** What a run's BUG-FINDs caught, as the banner says it: the distinct kinds in first-seen order, or the generic phrase. */
export function bugFindTaxonomy(finds: Array<{ error?: string | null }>, say: Say): string {
  const kinds: BugFindKind[] = []
  for (const f of finds) {
    const k = bugFindKind(f.error)
    if (!kinds.includes(k)) kinds.push(k)
  }
  if (kinds.length === 0) return say.t(BUG_FIND_TEXT.unknown.key, BUG_FIND_TEXT.unknown.fallback)
  return kinds.map((k) => say.t(BUG_FIND_TEXT[k].key, BUG_FIND_TEXT[k].fallback)).join(', ')
}
