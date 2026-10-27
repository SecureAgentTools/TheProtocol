import { describe, it, expect } from 'vitest'
import { assertionsForRow, bugFindKind, bugFindTaxonomy, AXIS_DETECTOR, type Say, type AxisSummary } from '../assertions'
import type { McpTesterToolRow } from '@/services/api/mcpTester'

// the page's words are its English fallbacks here, parameters filled in as the page's tp does
const say: Say = {
  t: (_key, fallback) => fallback,
  tp: (_key, fallback, params) => fallback.replace(/\{(\w+)\}/g, (_m, n: string) => String(params[n])),
}
const ALL_RUN = { wrapper_route: true, cross_frame: true, auth_matrix: true }
const NONE_RUN = { wrapper_route: false, cross_frame: false, auth_matrix: false }
const BACKEND_KEYS = ['side_effect', 'event_emission', 'audit_log_row', 'wrong_tier_rejection', 'cross_frame_parity', 'wrapper_route_drift']

function row(over: Record<string, unknown> = {}): McpTesterToolRow {
  return { tool: 'theprotocol_getThing', tier: 'developer', status: 200, healthy: true, skipped: false, elapsed: 120, ...over } as unknown as McpTesterToolRow
}
function allAxes(state: string, detail = ''): Record<string, { state: string; detail: string }> {
  return Object.fromEntries(BACKEND_KEYS.map((k) => [k, { state, detail }]))
}
function axis(r: AxisSummary, name: string) {
  const a = r.axes.find((x) => x.name === name)
  if (!a) throw new Error(`no axis ${name}`)
  return a
}

describe('a row\'s strict-mode verdict, axis by axis', () => {
  it('grades a healthy 200 row with every backend axis passing: eleven passes, the skip axis left out of the total', () => {
    const r = assertionsForRow(row({ axes: allAxes('pass') }), ALL_RUN, say)
    expect(r.axes).toHaveLength(12)
    expect(r.axes.map((a) => a.name)).toEqual([
      'HTTP status', 'Response shape', 'Tier-set membership', 'Latency baseline', 'Eventual-consistency budget', 'Skip rationale',
      'Read-after-write side-effect', 'EventStore emission', 'Audit log row', 'Wrong-tier rejection', 'Cross-frame parity',
      'Request vs its route (wrapper↔route)'])
    expect(axis(r, 'Skip rationale')).toEqual({ name: 'Skip rationale', state: 'skip', detail: 'the tool was not skipped' })
    expect(r.pass_count).toBe(11)
    expect(r.total).toBe(11)
  })

  it('reads the HTTP status: 2xx and other non-error codes pass, each error class says what it was', () => {
    const http = (status: unknown, skipped = false) => axis(assertionsForRow(row({ status, skipped }), ALL_RUN, say), 'HTTP status')
    expect(http(201)).toMatchObject({ state: 'pass', detail: '201' })
    expect(http(302)).toMatchObject({ state: 'pass', detail: '302' })
    expect(http(401)).toMatchObject({ state: 'fail', detail: '401: the auth gate refused it' })
    expect(http(403)).toMatchObject({ state: 'fail', detail: '403: the auth gate refused it' })
    expect(http(404)).toMatchObject({ state: 'fail', detail: '404: endpoint not found' })
    expect(http(422)).toMatchObject({ state: 'fail', detail: '422: client error' })
    expect(http(503)).toMatchObject({ state: 'fail', detail: '503: server error' })
    for (const none of [0, undefined, null]) {
      expect(http(none)).toMatchObject({ state: 'unknown', detail: 'no status captured' })
      expect(http(none, true)).toMatchObject({ state: 'skip', detail: 'no status captured' })
    }
  })

  it('reads the response shape: healthy passes, an error is shown (cut at 80 characters), a skip gives its reason', () => {
    const shape = (over: Record<string, unknown>) => axis(assertionsForRow(row(over), ALL_RUN, say), 'Response shape')
    expect(shape({})).toMatchObject({ state: 'pass', detail: 'matched the expected keys and types' })
    expect(shape({ skipped: true, skip_reason: 'needs a live contract' })).toMatchObject({ state: 'skip', detail: 'needs a live contract' })
    expect(shape({ skipped: true })).toMatchObject({ state: 'skip', detail: 'skipped' })
    const long = 'missing key agent_did in the response: ' + 'x'.repeat(100)
    expect(shape({ healthy: false, error: long })).toMatchObject({ state: 'fail', detail: long.slice(0, 80) })
    expect(shape({ healthy: false, error: 'boom' })).toMatchObject({ state: 'fail', detail: 'boom' })
    expect(shape({ healthy: false })).toMatchObject({ state: 'unknown' })
  })

  it('reads the tier and the latency against the prior-3 median', () => {
    expect(axis(assertionsForRow(row(), ALL_RUN, say), 'Tier-set membership')).toMatchObject({ state: 'pass', detail: 'tier=developer' })
    expect(axis(assertionsForRow(row({ tier: '' }), ALL_RUN, say), 'Tier-set membership')).toMatchObject({ state: 'unknown', detail: 'no tier captured' })
    const lat = (over: Record<string, unknown>) => axis(assertionsForRow(row(over), ALL_RUN, say), 'Latency baseline')
    expect(lat({ latency_regression: true, elapsed: 450, latency_baseline_ms: 100 }))
      .toMatchObject({ state: 'fail', detail: '450ms = 4.5× the median of the prior 3 (100ms)' })
    expect(lat({ latency_regression: true, elapsed: 450 })).toMatchObject({ state: 'fail', detail: '450ms = ?× the median of the prior 3 (0ms)' })
    expect(lat({ latency_baseline_ms: 100 })).toMatchObject({ state: 'pass', detail: '120ms (baseline 100ms)' })
    expect(lat({})).toMatchObject({ state: 'pass', detail: '120ms' })
    expect(lat({ elapsed: 0 })).toMatchObject({ state: 'unknown' })
  })

  it('holds the eventual-consistency budget at 5 s, the boundary included as a fail', () => {
    const budget = (elapsed: unknown) => axis(assertionsForRow(row({ elapsed }), ALL_RUN, say), 'Eventual-consistency budget')
    expect(budget(4999)).toMatchObject({ state: 'pass', detail: '4999ms < 5s' })
    expect(budget(5000)).toMatchObject({ state: 'fail', detail: '5000ms exceeded the 5 s soft budget' })
    expect(budget(undefined)).toMatchObject({ state: 'unknown' })
  })

  it('asks a skip for its reason: one without counts against the pass rate', () => {
    const why = (over: Record<string, unknown>) => axis(assertionsForRow(row(over), ALL_RUN, say), 'Skip rationale')
    expect(why({ skipped: true, skip_reason: 'teardown bucket' })).toMatchObject({ state: 'pass', detail: 'teardown bucket' })
    expect(why({ skipped: true })).toMatchObject({ state: 'fail', detail: 'skipped without a reason (counts against the pass rate)' })
  })
})

describe('the backend\'s six axes of a row', () => {
  it('passes the backend\'s state and detail through; "na" reads as not applicable', () => {
    const axes = { ...allAxes('pass'), side_effect: { state: 'fail', detail: 'read-after-write: field did not persist' }, audit_log_row: { state: 'na', detail: '' } }
    const r = assertionsForRow(row({ axes }), ALL_RUN, say)
    expect(axis(r, 'Read-after-write side-effect')).toMatchObject({ state: 'fail', detail: 'read-after-write: field did not persist' })
    expect(axis(r, 'Audit log row')).toMatchObject({ state: 'skip', detail: 'not applicable for this tool' })
  })

  it('reads a detector\'s axis as not measured where the run did not run that detector, but never hides a fail', () => {
    const axes = { ...allAxes('pass'), cross_frame_parity: { state: 'fail', detail: 'keys differ' } }
    const r = assertionsForRow(row({ axes }), NONE_RUN, say)
    const notRun = 'not measured: this run\'s suite does not run this check'
    expect(axis(r, 'Wrong-tier rejection')).toMatchObject({ state: 'skip', detail: notRun })
    expect(axis(r, 'Request vs its route (wrapper↔route)')).toMatchObject({ state: 'skip', detail: notRun })
    expect(axis(r, 'Cross-frame parity')).toMatchObject({ state: 'fail', detail: 'keys differ' })
    // an axis no detector grades stands as the backend said
    expect(axis(r, 'EventStore emission')).toMatchObject({ state: 'pass' })
  })

  it('says "not recorded" for a run whose rows carry no axes (a console run, or one before the axes existed)', () => {
    const r = assertionsForRow(row(), ALL_RUN, say)
    for (const name of ['Read-after-write side-effect', 'EventStore emission', 'Audit log row', 'Wrong-tier rejection', 'Cross-frame parity']) {
      expect(axis(r, name)).toMatchObject({ state: 'unknown', detail: 'not recorded for this run' })
    }
    // unknown axes count in the total and not as passes: five own passes (status, shape, tier, latency, budget) of eleven
    expect(r.pass_count).toBe(5)
    expect(r.total).toBe(11)
  })

  it('names the detector behind each of the three graded axes', () => {
    expect(AXIS_DETECTOR).toEqual({ wrong_tier_rejection: 'auth_matrix', cross_frame_parity: 'cross_frame', wrapper_route_drift: 'wrapper_route' })
  })
})

describe('what a run\'s BUG-FINDs caught', () => {
  it('reads the kind of each from its error text, case-insensitively, first match winning', () => {
    expect(bugFindKind('read-after-write: field did NOT PERSIST')).toBe('silentNoop')
    expect(bugFindKind('silent no-op on the update')).toBe('silentNoop')
    expect(bugFindKind('missing_event TokensTransferred')).toBe('missingEvent')
    expect(bugFindKind('expected event AgentSuspended within 5 s')).toBe('missingEvent')
    expect(bugFindKind('missing audit row for adminRevoke')).toBe('missingAudit')
    expect(bugFindKind('no audit row written')).toBe('missingAudit')
    expect(bugFindKind('response shape: expect_keys [agent_did]')).toBe('shapeDrift')
    expect(bugFindKind('did not persist; shape drifted too')).toBe('silentNoop')
    expect(bugFindKind('a 2xx that lied')).toBe('contract')
    expect(bugFindKind(null)).toBe('contract')
  })

  it('lists the distinct kinds in the order first seen, and says the generic phrase when there is nothing to read', () => {
    const finds = [{ error: 'expected event X' }, { error: 'did not persist' }, { error: 'expected event Y' }, { error: 'odd' }]
    expect(bugFindTaxonomy(finds, say)).toBe('missing event emission, silent NO-OP, contract violation')
    expect(bugFindTaxonomy([], say)).toBe('a wrapper or endpoint defect')
  })
})
