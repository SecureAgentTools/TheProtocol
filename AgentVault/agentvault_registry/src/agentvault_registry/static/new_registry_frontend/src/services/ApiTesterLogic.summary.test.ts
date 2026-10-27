/**
 * §SUITES1018 (2026-10-18): the API tester's run summary counts a row the server did not call as NOT MEASURED.
 *
 * The server used to answer every skipped row (a destructive or cross-frame action, a manual-only route) with
 * healthy:true, status 200, in 1 ms, so 92 uncalled rows of the 2026-10-18 sweep counted as passes. It now answers
 * not_measured:true with the reason, and unmeasured:true so an older console still leaves the row out of the rate.
 * This summary keeps the two apart: unmeasured (no answer reached us) and not_measured (deliberately not called).
 */
import { describe, expect, it } from 'vitest'
import { ApiTestEngine } from './ApiTesterLogic'

function engineWith(results: any[]) {
  const engine = new ApiTestEngine()
  engine.endpointsData.value = {
    cat: results.map((r, i) => ({ method: 'POST', path: `/p/${i}`, auth: 'developer', description: '', result: r })),
  } as any
  return engine
}

describe('the API tester run summary', () => {
  it('counts a row the server did not call as not measured, out of the rate', () => {
    const s = engineWith([
      { healthy: true },                                                     // a pass
      { healthy: false },                                                    // a failure
      { healthy: true, expected_failure: true },                             // an expected failure (counted first)
      { healthy: false, not_measured: true, unmeasured: true, not_measured_reason: 'destructive' },
      { healthy: false, unmeasured: true, transport_error: true },           // no answer reached us
    ]).runSummary()
    expect(s.passed).toBe(1)
    expect(s.failed).toBe(1)
    expect(s.expected_failures).toBe(1)
    expect(s.not_measured).toBe(1)
    expect(s.unmeasured).toBe(1)
    expect(s.total_measured).toBe(3)
    expect(s.real_pass_rate).toBe(50)
  })
})
