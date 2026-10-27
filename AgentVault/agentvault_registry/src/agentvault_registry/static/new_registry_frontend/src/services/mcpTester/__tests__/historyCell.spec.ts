import { describe, it, expect } from 'vitest'
import { historyCell, suiteDelta, suiteTrend, sameSuite, type TrendRun } from '../runReading'

// §SUITES1018 (2026-10-19): his report on EU's History, "operators are green with 87% ... how its displayed bothers me"
// and "the console suites red with 99+% is also not very accurate"; then, on V0627's History, "i dont like the 1 as
// documented stuff. just leave this out of the view. 1 failed as red is fine." The counts below are the runs on that
// screen, read from EU's history the same morning.

const CONSOLE = 'flow_playwright_console_lifecycles'
// e3eeebcb87fe4a73, Cloud-op δ: nothing failed; 77 rows not measured and 20 refused by rule on an operator
const OPERATOR = {
  tool_count: 766, passed: 669, skipped: 77, failed: 0, policy_denied: 20, pass_pct: 87.34,
  bug_finds: 0, hard_failures: 0, expected_red: 0,
}
// fes-20261019T054109Z-84fe, Console on Sandbox Alpha: one failed step (a red by design)
const CONSOLE_ALPHA = {
  tool_count: 578, passed: 544, skipped: 33, failed: 1, policy_denied: 0, pass_pct: 99.82,
  bug_finds: 0, hard_failures: 0, expected_red: 1, target: 'Sandbox Alpha',
}
// fes-20261019T032007Z-41ea, Console on Sandbox Beta (the whole suite)
const CONSOLE_BETA = {
  tool_count: 2514, passed: 2377, skipped: 135, failed: 2, policy_denied: 0, pass_pct: 99.92,
  bug_finds: 0, hard_failures: 0, expected_red: 2, target: 'Sandbox Beta',
}

describe('§SUITES1018: a History row says what its figure is made of', () => {
  it('an operator run keeps its figure, is not red, and names the rows it did not run', () => {
    const c = historyCell(OPERATOR)
    expect(c.reading.pct).toBe(87.34)
    expect(c.fraction).toEqual({ num: 669, den: 766, over: 'rows' })
    // the green part is the figure; the rest is not run, not failed
    expect(c.bar).toEqual({ pass: 87.3, byRule: 2.6, skip: 10.1, fail: 0 })
    expect([c.notMeasured, c.byRule, c.failed]).toEqual([77, 20, 0])
    expect(c.bad).toBe(false)
  })

  it('a console run with a failed step is red and says "failed", a red by design included', () => {
    const c = historyCell(CONSOLE_ALPHA)
    expect(c.reading.pct).toBe(99.82)
    expect(c.fraction).toEqual({ num: 544, den: 545, over: 'measured' })
    // the console suite divides by the steps it measured: so does its bar
    expect(c.bar).toEqual({ pass: 99.8, byRule: 0, skip: 0, fail: 0.2 })
    expect([c.failed, c.notMeasured]).toEqual([1, 33])
    expect(c.bad).toBe(true)
    expect(historyCell(CONSOLE_BETA).failed).toBe(2)
  })

  it('a bug-find is red, and a clean run is not (control)', () => {
    // 7a9f2654d7cf494e, MCP: one failed row, a BUG-FIND
    const c = historyCell({ tool_count: 1244, passed: 1202, skipped: 21, failed: 1, policy_denied: 20, pass_pct: 96.62,
      bug_finds: 1 })
    expect(c.bad).toBe(true)
    expect(c.bar.fail).toBe(0.1)
    // 897e967e4bf4484f, Federation: 587 of 587
    expect(historyCell({ tool_count: 587, passed: 587, skipped: 0, failed: 0, policy_denied: 0, pass_pct: 100, bug_finds: 0 }).bad)
      .toBe(false)
  })
})

describe('§SUITES1018: one suite is one flow on one target', () => {
  const run = (id: string, at: number, s: Record<string, unknown>): TrendRun =>
    ({ run_id: id, started_at: at, flow_name: CONSOLE, summary: s as TrendRun['summary'] })
  const runs = [
    run('beta-1', 1000, CONSOLE_BETA), run('alpha-1', 2000, CONSOLE_ALPHA),
    run('beta-2', 3000, CONSOLE_BETA), run('alpha-2', 4000, CONSOLE_ALPHA),
  ]

  it('compares the console alpha pass with the alpha pass before it, never with the beta pass between', () => {
    expect(suiteDelta(runs, runs[3])).toEqual({ delta: 0, prevId: 'alpha-1' })
    expect(suiteDelta(runs, runs[2])).toEqual({ delta: 0, prevId: 'beta-1' })
    expect(suiteTrend(runs, CONSOLE, 12, 'Sandbox Alpha').map((p) => p.id)).toEqual(['alpha-1', 'alpha-2'])
    expect(sameSuite(runs[0], runs[1])).toBe(false)
  })

  it('a run that names no target still reads against its flow (control)', () => {
    const old = [run('b', 1000, { ...CONSOLE_BETA, target: undefined }), run('a', 2000, { ...CONSOLE_ALPHA, target: undefined })]
    expect(suiteDelta(old, old[1])).toEqual({ delta: -0.1, prevId: 'b' })
    expect(suiteTrend(old, CONSOLE).map((p) => p.id)).toEqual(['b', 'a'])
  })
})
