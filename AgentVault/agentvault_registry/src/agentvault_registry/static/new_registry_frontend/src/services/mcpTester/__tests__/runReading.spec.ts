import { describe, it, expect } from 'vitest'
import {
  foldHeartbeats, isHeartbeat, runWallSeconds, fmtDuration, suiteTrend, flowOf, notRunKind, groupNotRun,
  sandboxRefusalSentence, barSegments, acceptStreamedLine, silentSince, NOT_RUN_ORDER,
  readPassRate, rowOutcome, tallyOutcomes, trendPct, previousOfSuite, suiteDelta, historyStatus, passFraction,
  namedEntries, readDetectors, awaitsRun, DETECTOR_KEYS, tileReading, latencyMeasured,
} from '../runReading'

describe('§MCPTEST30 V0535: a stream that replays the log adds no line twice', () => {
  it('skips the lines the page loaded and appends only what is new, stamped on arrival', () => {
    const lines = [{ ts: 100, msg: 'Spawning sweep' }, { ts: 106, msg: 'Sweep in flight · elapsed 0m06s' }]
    // the stream replays from the run's first line
    expect(acceptStreamedLine(lines, 0, 'Spawning sweep', 500)).toBe(false)
    expect(acceptStreamedLine(lines, 1, 'Sweep in flight · elapsed 0m06s', 500)).toBe(false)
    expect(acceptStreamedLine(lines, 2, 'Sweep in flight · elapsed 0m12s', 500)).toBe(true)
    expect(lines.map((l) => [l.ts, l.msg])).toEqual([
      [100, 'Spawning sweep'], [106, 'Sweep in flight · elapsed 0m06s'], [500, 'Sweep in flight · elapsed 0m12s']])
  })

  it('appends everything on a fresh run (the page held no lines)', () => {
    const lines: { ts: number; msg: string }[] = []
    expect(acceptStreamedLine(lines, 0, 'a', 1)).toBe(true)
    expect(acceptStreamedLine(lines, 1, 'b', 2)).toBe(true)
    expect(lines.length).toBe(2)
  })
})

describe('§MCPTEST30 V0535: a run that stopped reporting is told apart from one in flight', () => {
  it('names the newest line\'s time once the heartbeat has been quiet past the threshold', () => {
    const lines = [{ ts: 1000, msg: 'x' }, { ts: 1600, msg: 'Sweep in flight · elapsed 10m07s' }]
    expect(silentSince(lines, 1700)).toBeNull()
    expect(silentSince(lines, 1781)).toBe(1600)
    expect(silentSince([], 99999)).toBeNull()
    expect(silentSince(lines, 1700, 60)).toBe(1600)
  })
})

describe('§MCPTEST30 V0535: the live log folds the sweep\'s heartbeat', () => {
  it('folds consecutive heartbeats into the latest one and keeps every other line', () => {
    const lines = [
      { ts: 1, msg: 'Target: http://sbx-alpha-registry:8000 (sandbox=True)' },
      { ts: 2, msg: 'Sweep in flight · elapsed 0m06s' },
      { ts: 3, msg: 'Sweep in flight · elapsed 0m12s' },
      { ts: 4, msg: 'Sweep in flight · elapsed 0m18s' },
      { ts: 5, msg: "Spawning sweep 'Cloud-op MCP — sandboxalpha'" },
      { ts: 6, msg: 'Sweep in flight · elapsed 0m24s' },
    ]
    const shown = foldHeartbeats(lines)
    expect(shown.map((l) => [l.msg, l.folded])).toEqual([
      ['Target: http://sbx-alpha-registry:8000 (sandbox=True)', 0],
      ['Sweep in flight · elapsed 0m18s', 3],
      ["Spawning sweep 'Cloud-op MCP — sandboxalpha'", 0],
      ['Sweep in flight · elapsed 0m24s', 1],
    ])
    expect(shown[1].ts).toBe(4)
  })

  it('folds only the exact heartbeat, never a line that merely mentions a sweep', () => {
    expect(isHeartbeat('Sweep in flight · elapsed 12m05s')).toBe(true)
    expect(isHeartbeat('Sweep in flight · elapsed 0m06s · 3 errors')).toBe(false)
    expect(isHeartbeat('sweep completed in 900s')).toBe(false)
    expect(foldHeartbeats([])).toEqual([])
  })

  it('does not change the lines it was given', () => {
    const lines = [{ ts: 1, msg: 'Sweep in flight · elapsed 0m06s' }, { ts: 2, msg: 'Sweep in flight · elapsed 0m12s' }]
    foldHeartbeats(lines)
    expect(lines[0].msg).toBe('Sweep in flight · elapsed 0m06s')
  })
})

describe('§MCPTEST30 V0535: a run\'s wall time is its own clock', () => {
  it('reads finish minus start, not the summary\'s summed test time (round 10\'s federation run)', () => {
    const fed = { started_at: 1790883166.37, finished_at: 1790884019.33, summary: { wall_s: 8494.2 } }
    expect(Math.round(runWallSeconds(fed)!)).toBe(853)
    expect(fmtDuration(runWallSeconds(fed))).toBe('14m 13s')
  })

  it('falls back to the summary for a run with no finish, and says nothing for a run with neither', () => {
    expect(runWallSeconds({ started_at: 10, finished_at: null, summary: { wall_s: 42 } })).toBe(42)
    expect(runWallSeconds({ started_at: null, finished_at: null, summary: null })).toBeNull()
    expect(fmtDuration(null)).toBe('—')
  })

  it('formats seconds, minutes and hours', () => {
    expect(fmtDuration(42)).toBe('42s')
    expect(fmtDuration(900)).toBe('15m 00s')
    expect(fmtDuration(8494.2)).toBe('2h 21m')
  })
})

describe('§MCPTEST30 V0535: the trend is one suite\'s', () => {
  const runs = [
    { run_id: 'c', started_at: 30, flow_name: 'flow_mcp_lifecycle_cloudop_sandboxalpha_complete', summary: { pass_pct: 87.45 } },
    { run_id: 'b', started_at: 20, flow_name: 'flow_federation_suite_complete', summary: { pass_pct: 99.49 } },
    { run_id: 'a', started_at: 10, flow_name: 'flow_mcp_lifecycle_complete', summary: { pass_pct: 97.72 } },
    { run_id: 'd', started_at: 40, summary: { pass_pct: 96.9 } },
    { run_id: 'e', started_at: 50, flow_name: 'flow_mcp_lifecycle_complete', summary: null },
  ]

  it('keeps only the asked suite\'s finished runs, oldest first, and a run with no flow is the MCP tester\'s', () => {
    expect(suiteTrend(runs, 'flow_mcp_lifecycle_complete')).toEqual([{ id: 'a', pct: 97.72 }, { id: 'd', pct: 96.9 }])
    expect(suiteTrend(runs, 'flow_federation_suite_complete')).toEqual([{ id: 'b', pct: 99.49 }])
    expect(flowOf(runs[3])).toBe('flow_mcp_lifecycle_complete')
  })

  it('caps the trend at the newest runs', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ run_id: `r${i}`, started_at: i, summary: { pass_pct: i } }))
    const t = suiteTrend(many, 'flow_mcp_lifecycle_complete', 12)
    expect(t.length).toBe(12)
    expect(t[0].id).toBe('r8')
    expect(t[11].id).toBe('r19')
  })
})

describe('§MCPTEST30 V0535: what a run left out, by why', () => {
  it('tells a coverage hole from nothing-to-measure from left-out-on-purpose (reasons as round 10 wrote them)', () => {
    expect(notRunKind("lifecycle recorded a 401 as healthy — the step ran under expect_status='any' while this tool's contract expects SUCCESS, so the success path was not measured.")).toBe('unmeasured')
    expect(notRunKind("contract says: EVTYPES2: not probed - PROVISIONING - HIS word — the contract requires expect_status='success', so this row is NOT MEASURED, not a pass (§FANCLAIM).")).toBe('by_design')
    expect(notRunKind("lifecycle recorded a 403 as healthy — the step ran under expect_status='any' while this tool's contract expects SUCCESS, so the success path was not measured. The body says: Error: HTTP 403: You are not an active operator.")).toBe('unmeasured')
    expect(notRunKind('NOT MEASURED: 0 row(s), no second page of 3 to compare')).toBe('nothing')
    expect(notRunKind('recursive — admin endpoint that re-invokes the API tester itself; would loop')).toBe('by_design')
    expect(notRunKind('EVTYPES2: not probed - moves value: it unlocks the caller\'s matured bond share')).toBe('by_design')
    expect(notRunKind('§MCPSWEEP V0464: the tool now POSTs {service, input} as its route takes')).toBe('other')
    expect(notRunKind(null)).toBe('other')
  })

  it('puts an answer the tester never received in its own group, ahead of nothing-to-decide (V0546)', () => {
    // reasons as V0545's lifecycle step and overdraft probe write them, and the federation suite's own words
    expect(notRunKind('NOT MEASURED: no HTTP status came back for theprotocol_getArenaMatchMap (the answer was lost in transit; the server may have answered)')).toBe('lost')
    expect(notRunKind('NOT MEASURED: no HTTP status came back for theprotocol_transferUnits (curl reached no server: 000)')).toBe('lost')
    expect(notRunKind("NOT MEASURED: the throwaway spender's token could not be had (no HTTP status came back, 2 time(s): exec)")).toBe('lost')
    expect(notRunKind('transport lost: 1 probe answer(s) were lost in transit during this test (an exec returned rc 0 with no HTTP status marker), so its passed verdict cannot be told from the transport.')).toBe('lost')
    expect(notRunKind('NOT MEASURED: the list is empty (0 rows), so no detail can be asked')).toBe('nothing')
    expect(NOT_RUN_ORDER.indexOf('lost')).toBeLessThan(NOT_RUN_ORDER.indexOf('nothing'))
    expect(groupNotRun([{ skip_reason: 'NOT MEASURED: no HTTP status came back for x (curl reached no server: 000)' },
                        { skip_reason: 'NOT MEASURED: 0 row(s), no second page of 3 to compare' }]).map((g) => g.kind))
      .toEqual(['lost', 'nothing'])
  })

  it('tells a feature switched off on the node and a subject the run never made apart from the rest (V0538)', () => {
    // reasons as round 10's cloud-op alpha run (9b5d52c12a3048ea) wrote them
    expect(notRunKind("cloud-op flag-gated: the operator says 'not currently enabled on this registry' (HTTP 503): the feature is off on this node, so its success path is not measured here")).toBe('switched_off')
    expect(notRunKind("cloud-op fixture missing: ['payment_token'] — the cloud-op sweep runs no phase-3 entity setup")).toBe('fixture')
    expect(notRunKind("fixture missing on this operator: ['scratch_listing']: it has no such row, so the tool was not called")).toBe('fixture')
    expect(notRunKind('EVTYPES2: takes no entity argument, so there is nothing non-existent to aim at - MEASURED succeeding on sandboxdelta')).toBe('by_design')
    expect(notRunKind('Creates a new developer row — leaves DB debris. Cover in destructive bucket.')).toBe('by_design')
    // V0541: the role group sits after the run's own holes (its own spec below)
    expect(NOT_RUN_ORDER.filter((k) => k !== 'role' && k !== 'lost')).toEqual(['unmeasured', 'fixture', 'nothing', 'switched_off', 'by_design', 'other'])
  })

  it('groups rows in a fixed order and drops empty groups', () => {
    const g = groupNotRun([
      { tool: 'x', reason: 'NOT MEASURED: the list returned no row carrying an id' },
      { tool: 'y', reason: 'recursive — would loop' },
      { tool: 'z', skip_reason: 'NOT MEASURED: 0 row(s)' },
    ])
    expect(g.map((x) => [x.kind, x.rows.length])).toEqual([['nothing', 2], ['by_design', 1]])
  })
})

describe('§MCPTEST30 V0535: small readings', () => {
  it('says what a runner that hosts no sandboxes means for this page, and leaves other refusals to their words', () => {
    const s = sandboxRefusalSentence(`op 'sandbox_status': this runner's policy does not offer sandboxes ("sandboxes": true is a kit host's)`)
    expect(s?.key).toBe('mcpTester.sandbox.notOffered')
    expect(sandboxRefusalSentence('op refused: the runner is busy')).toBeNull()
  })

  it('splits a category bar into what passed, what was not measured and what failed', () => {
    expect(barSegments(2, 3, 0)).toEqual({ pass: 40, byRule: 0, skip: 60, fail: 0 })
    expect(barSegments(28, 2, 0)).toEqual({ pass: 93.3, byRule: 0, skip: 6.7, fail: 0 })
    expect(barSegments(0, 0, 0)).toEqual({ pass: 0, byRule: 0, skip: 0, fail: 0 })
  })

  it('V0539: gives the rows a standing rule kept from being called a segment of their own', () => {
    expect(barSegments(6, 1, 0, 3)).toEqual({ pass: 60, byRule: 30, skip: 10, fail: 0 })
  })
})

describe('§MCPTEST30 V0539: a pass is a row that was called and held', () => {
  // EU's history, 2026-10-01: the strict run and the cloud operator run recorded before the flows partitioned their rows
  const strict = { tool_count: 1184, passed: 1157, skipped: 26, failed: 0, policy_denied: 20, pass_pct: 97.72 }
  const delta = { tool_count: 750, passed: 656, skipped: 93, failed: 0, policy_denied: 20, pass_pct: 87.47 }

  it('reads the never-called rows a run counted as passes out of its pass rate, and keeps what it recorded', () => {
    const r = readPassRate(strict)
    expect(r).toMatchObject({ total: 1184, measured: 1138, byRule: 20, skipped: 26, failed: 0, overlap: 19 })
    expect(r.pct).toBe(96.11)
    expect(r.recordedPct).toBe(97.72)
    // the four classes add up to the run's rows
    expect(r.measured + r.byRule + r.skipped + r.failed).toBe(1184)
    const d = readPassRate(delta)
    expect(d).toMatchObject({ measured: 637, overlap: 19, pct: 84.93 })
    expect(d.measured + d.byRule + d.skipped + d.failed).toBe(750)
  })

  it('takes a run whose counts partition its rows as it recorded it, whatever its suite divides by', () => {
    // since V0539 the flows count four disjoint classes
    expect(readPassRate({ tool_count: 750, passed: 637, skipped: 93, failed: 0, policy_denied: 20, pass_pct: 84.93 }))
      .toMatchObject({ measured: 637, overlap: 0, pct: 84.93, recordedPct: null })
    // the console suite's figure is over the steps it measured (591 of 607), not its 634 rows: it stands
    expect(readPassRate({ tool_count: 634, passed: 591, skipped: 27, failed: 16, pass_pct: 97.36 }))
      .toMatchObject({ measured: 591, overlap: 0, pct: 97.36, recordedPct: null })
    // a federation run (no rule refuses a test)
    expect(readPassRate({ tool_count: 586, passed: 583, skipped: 1, failed: 2, policy_denied: 0, pass_pct: 99.49 }).pct).toBe(99.49)
  })

  it('reads a run from before the split (refusals inside skipped, no policy_denied) the same way', () => {
    const r = readPassRate({ tool_count: 763, passed: 734, skipped: 29, failed: 0, pass_pct: 96.2 })
    expect(r).toMatchObject({ measured: 734, overlap: 0 })
    const old = readPassRate({ tool_count: 742, passed: 734, skipped: 29, failed: 0, pass_pct: 98.92 })
    expect(old).toMatchObject({ measured: 713, overlap: 21, byRule: 0, pct: 96.09, recordedPct: 98.92 })
  })

  it('computes a rate for a summary that carries none, and never a negative count', () => {
    expect(readPassRate({ tool_count: 4, passed: 3, skipped: 0, failed: 1 }).pct).toBe(75)
    expect(readPassRate({ tool_count: 0, passed: 0, skipped: 0, failed: 0 })).toMatchObject({ pct: 0, measured: 0, overlap: 0 })
    expect(readPassRate({ tool_count: 2, passed: 1, skipped: 9, failed: 0 }).measured).toBe(0)
  })

  it('names the fraction behind a rate: every row, or the rows measured, or none it can reproduce', () => {
    expect(passFraction(readPassRate(strict))).toEqual({ num: 1138, den: 1184, over: 'rows' })
    // the console suite: 591 of the 607 steps it measured, not of its 634 rows
    expect(passFraction(readPassRate({ tool_count: 634, passed: 591, skipped: 27, failed: 16, pass_pct: 97.36 })))
      .toEqual({ num: 591, den: 607, over: 'measured' })
    expect(passFraction(readPassRate({ tool_count: 10, passed: 5, skipped: 1, failed: 0, pass_pct: 77.7 }))).toBeNull()
  })

  it('gives every row one outcome, a rule\'s refusal first whatever its other flags say', () => {
    const byRule = new Set(['theprotocol_startSimulation', 'theprotocol_operatorPortalSelfRestart'])
    expect(rowOutcome({ tool: 'theprotocol_startSimulation', healthy: true, skipped: true }, byRule)).toBe('by_rule')
    expect(rowOutcome({ tool: 'theprotocol_operatorPortalSelfRestart', healthy: false, skipped: true }, byRule)).toBe('by_rule')
    expect(rowOutcome({ tool: 'theprotocol_verifyPayment', healthy: false, skipped: true }, byRule)).toBe('skip')
    expect(rowOutcome({ tool: 'theprotocol_getMyAgents', healthy: true, skipped: false }, byRule)).toBe('pass')
    expect(rowOutcome({ tool: 'theprotocol_x', healthy: false, skipped: false }, byRule)).toBe('fail')
    const rows = [
      { tool: 'theprotocol_startSimulation', healthy: true, skipped: true },
      { tool: 'theprotocol_operatorPortalSelfRestart', healthy: false, skipped: true },
      { tool: 'theprotocol_verifyPayment', healthy: false, skipped: true },
      { tool: 'theprotocol_getMyAgents', healthy: true, skipped: false },
    ]
    expect(tallyOutcomes(rows, byRule)).toEqual({ pass: 1, by_rule: 2, skip: 1, fail: 0 })
    expect(tallyOutcomes(rows, new Set())).toEqual({ pass: 1, by_rule: 0, skip: 3, fail: 0 })
  })
})

describe('§MCPTEST30 V0539: History reads each run against its own suite', () => {
  const runs = [
    { run_id: 'd2', started_at: 400, flow_name: 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete',
      summary: { tool_count: 750, passed: 637, skipped: 93, failed: 0, policy_denied: 20, pass_pct: 84.93 } },
    { run_id: 'fed', started_at: 300, flow_name: 'flow_federation_suite_complete', summary: { pass_pct: 99.49 } },
    { run_id: 'd1', started_at: 200, flow_name: 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete',
      summary: { tool_count: 750, passed: 656, skipped: 93, failed: 0, policy_denied: 20, pass_pct: 87.47 } },
    { run_id: 'live', started_at: 100, flow_name: 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete', summary: null },
    { run_id: 'd0', started_at: 50, flow_name: 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete',
      summary: { tool_count: 750, passed: 655, skipped: 94, failed: 0, policy_denied: 20, pass_pct: 87.33 } },
  ]

  it('finds the newest earlier run of the same suite that has a pass rate', () => {
    expect(previousOfSuite(runs, runs[0])?.run_id).toBe('d1')
    expect(previousOfSuite(runs, runs[2])?.run_id).toBe('d0')   // the run without a summary is passed over
    expect(previousOfSuite(runs, runs[4])).toBeNull()
    expect(previousOfSuite(runs, runs[1])).toBeNull()
  })

  it('measures the change on the page\'s reading, so a run recorded before V0539 is no false drop', () => {
    expect(trendPct(runs[2].summary)).toBe(84.93)
    expect(suiteDelta(runs, runs[0])).toEqual({ delta: 0, prevId: 'd1' })
    expect(suiteDelta(runs, runs[2])).toEqual({ delta: 0.13, prevId: 'd0' })
    expect(suiteDelta(runs, runs[3])).toBeNull()
    expect(suiteTrend(runs, 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete').map((p) => p.pct)).toEqual([84.8, 84.93, 84.93])
  })

  it('calls a record still reading running past two hours unfinished, and leaves a live one alone', () => {
    expect(historyStatus('running', 1000, 1000 + 7201)).toBe('unfinished')
    expect(historyStatus('queued', 1000, 1000 + 9000)).toBe('unfinished')
    expect(historyStatus('running', 1000, 1000 + 600)).toBe('running')
    expect(historyStatus('completed', 1000, 1000 + 99999)).toBe('completed')
    expect(historyStatus('running', null, 99999)).toBe('running')
  })
})

describe('§MCPTEST30 V0539: a run\'s named lists are read through one shape', () => {
  it('reads the console suite\'s "name: text" strings (the Not run list threw on them and blanked the page)', () => {
    expect(namedEntries(['ui:guided_tours_walk_clean.tour-cockpit-desk: not offered on this registry: cockpit_desk_enabled is off']))
      .toEqual([{ tool: 'ui:guided_tours_walk_clean.tour-cockpit-desk',
        reason: 'not offered on this registry: cockpit_desk_enabled is off',
        error: 'not offered on this registry: cockpit_desk_enabled is off' }])
    expect(namedEntries(['no separator'])).toEqual([{ tool: 'no separator', reason: '', error: '' }])
  })

  it('keeps the flows\' objects, and never yields a field that is not a string', () => {
    expect(namedEntries([{ tool: 'theprotocol_x', reason: 'fixture missing' }]))
      .toEqual([{ tool: 'theprotocol_x', reason: 'fixture missing', error: 'fixture missing' }])
    expect(namedEntries([{ tool: 'theprotocol_y', error: 'HTTP 500' }]))
      .toEqual([{ tool: 'theprotocol_y', reason: 'HTTP 500', error: 'HTTP 500' }])
    expect(namedEntries([{ name: 'z', skip_reason: null }, null, 7])).toEqual([
      { tool: 'z', reason: '', error: '' }, { tool: '', reason: '', error: '' }, { tool: '7', reason: '', error: '' }])
    expect(namedEntries(undefined)).toEqual([])
    expect(namedEntries({ tool: 'x' })).toEqual([])
  })
})

describe('§MCPTEST30 V0539: a console suite step switched off on the registry joins its group', () => {
  it('reads "not offered on this registry" as switched off', () => {
    expect(notRunKind('not offered on this registry: cockpit_desk_enabled is off (the hub shows no card for it)')).toBe('switched_off')
    // V0541 gave the step the run's account cannot open a group of its own
    expect(notRunKind('an operator-series tour: locked for a member (the hub shows it locked)')).toBe('role')
  })
})

describe('§MCPTEST30 V0541: a console suite run\'s not-run steps join their groups', () => {
  it('reads the reasons the console suite writes', () => {
    expect(notRunKind('an operator-series tour: locked for a member (the hub shows it locked)')).toBe('role')
    expect(notRunKind('not opened headless: three.js (WebGL)')).toBe('by_design')
    expect(notRunKind('leads into a WebGL view the suite never drives headless (/bridge)')).toBe('by_design')
    expect(notRunKind('FLARE_LOCAL_PURCHASE_ENABLED is off on this frame: nothing can be bought here')).toBe('switched_off')
    expect(notRunKind('this frame runs NOTIFY_V2_MODE=shadow: the server writes in-app feed entries only in mode on')).toBe('switched_off')
    expect(notRunKind('no service agent this frame can reach (The showcase is disabled on this deployment.)')).toBe('fixture')
    expect(notRunKind('the registry answers 503 for an agent with no relay (it should say "no relay" in a 200)')).toBe('other')
  })

  it('orders the role group after the run\'s own holes and before the decisions', () => {
    expect(NOT_RUN_ORDER).toEqual(['unmeasured', 'lost', 'fixture', 'role', 'nothing', 'switched_off', 'by_design', 'other'])
  })
})

describe('§MCPTEST30 V0541: a drift detector a suite did not run reads as not measured', () => {
  const graded = (state: string) => [{ axes: { wrong_tier_rejection: { state }, cross_frame_parity: { state }, wrapper_route_drift: { state } } }]

  it('takes a run recorded since V0541 at its word', () => {
    const s = { detectors: { wrapper_route: false, cross_frame: false, auth_matrix: true }, auth_matrix_total: 396, wrapper_drift: 0 }
    expect(readDetectors(s, graded('pass'), 'flow_mcp_lifecycle_cloudop_sandboxdelta_complete'))
      .toEqual({ wrapper_route: false, cross_frame: false, auth_matrix: true })
  })

  it('reads an older strict sweep as having run all three (its rows graded them, its matrix probed)', () => {
    expect(readDetectors({ auth_matrix_total: 396, wrapper_drift: 0, cross_frame_drift: 0 }, graded('pass'), 'flow_mcp_lifecycle_complete'))
      .toEqual({ wrapper_route: true, cross_frame: true, auth_matrix: true })
  })

  it('reads an older cloud-op sweep as the matrix alone (its A↔B axis read n/a; only the strict sweep checks wrappers)', () => {
    const rows = [{ axes: { cross_frame_parity: { state: 'na' }, wrapper_route_drift: { state: 'pass' } } }]
    expect(readDetectors({ auth_matrix_total: 396, wrapper_drift: 0, cross_frame_drift: 0 }, rows,
      'flow_mcp_lifecycle_cloudop_sandboxdelta_complete')).toEqual({ wrapper_route: false, cross_frame: false, auth_matrix: true })
  })

  it('reads the federation suite (0 of 0 probes) and a console run (no axes at all) as measuring none', () => {
    const fedRows = [{ axes: { cross_frame_parity: { state: 'na' }, wrapper_route_drift: { state: 'pass' } } }]
    expect(readDetectors({ auth_matrix_total: 0, wrapper_drift: 0 }, fedRows, 'flow_federation_suite_complete'))
      .toEqual({ wrapper_route: false, cross_frame: false, auth_matrix: false })
    expect(readDetectors({ passed: 601 }, [{}], 'flow_playwright_console_lifecycles'))
      .toEqual({ wrapper_route: false, cross_frame: false, auth_matrix: false })
  })

  it('reads no run as no detector, and names three of them in a fixed order', () => {
    expect(readDetectors(null, [], null)).toEqual({ wrapper_route: false, cross_frame: false, auth_matrix: false })
    expect(DETECTOR_KEYS).toEqual(['wrapper_route', 'cross_frame', 'auth_matrix'])
  })
})

describe('§MCPTEST30 V0541: a result tab with no run loaded waits for one', () => {
  const none = { rows: 0, bugFinds: 0, hardFails: 0, notRun: 0, hasSummary: false }

  it('waits on every result tab while nothing is loaded (the clean verdicts read over zero rows)', () => {
    for (const tab of ['results', 'bugfind', 'fails', 'probes', 'notrun', 'phasef']) expect(awaitsRun(tab, none)).toBe(true)
    // the control: the live log and History never wait for a run
    expect(awaitsRun('log', none)).toBe(false)
    expect(awaitsRun('history', none)).toBe(false)
  })

  it('shows a loaded run, and findings a run carries without rows', () => {
    const loaded = { rows: 1184, bugFinds: 0, hardFails: 0, notRun: 0, hasSummary: true }
    for (const tab of ['results', 'bugfind', 'fails', 'probes', 'notrun', 'phasef']) expect(awaitsRun(tab, loaded)).toBe(false)
    expect(awaitsRun('bugfind', { ...none, bugFinds: 2 })).toBe(false)
    expect(awaitsRun('fails', { ...none, hardFails: 1 })).toBe(false)
    expect(awaitsRun('notrun', { ...none, notRun: 3 })).toBe(false)
    expect(awaitsRun('phasef', { ...none, hasSummary: true })).toBe(false)
  })
})

describe('§MCPTEST30 V0547: a stat tile reads a count only where its own check ran', () => {
  it('prints a measured zero and a dash for a check the run never ran or a key it never wrote', () => {
    expect(tileReading(0, true)).toEqual({ text: '0', measured: true })
    expect(tileReading(6, true)).toEqual({ text: '6', measured: true })
    // round 14's strict run: wrapper_drift 0 with detectors.wrapper_route false; a console run carries no key at all
    expect(tileReading(0, false)).toEqual({ text: '—', measured: false })
    expect(tileReading(undefined, true)).toEqual({ text: '—', measured: false })
    expect(tileReading(null, true)).toEqual({ text: '—', measured: false })
    expect(tileReading(Number.NaN, true)).toEqual({ text: '—', measured: false })
    expect(tileReading('3', true)).toEqual({ text: '—', measured: false })
  })
})

describe('latencyMeasured (V0548)', () => {
  it('a run that compared no tool with a baseline measured nothing', () => {
    expect(latencyMeasured(0)).toBe(false)
    expect(latencyMeasured(37)).toBe(true)
  })
  it('a run recorded before V0544 names no count and keeps its old reading', () => {
    expect(latencyMeasured(undefined)).toBe(true)
    expect(latencyMeasured(null)).toBe(true)
    expect(latencyMeasured(Number.NaN)).toBe(true)
  })
})
