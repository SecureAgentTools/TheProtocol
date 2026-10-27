import { describe, it, expect } from 'vitest'
import {
  splitStep, titleAndTags, stepOutcome, groupRun, runVerdict, readScope, filterRuns, captureTotals,
} from '../reading'
import type { ConsoleSuiteRunMeta } from '@/services/api/consoleSuite'

describe('§MCPTEST30 V0555: a step row names its lifecycle, its step and its screen', () => {
  it('splits at the first dot after ui:, and reads @phone off the step', () => {
    expect(splitStep('ui:console_smoke.login-page-renders')).toEqual(
      { lifecycle: 'console_smoke', step: 'login-page-renders', phone: false })
    expect(splitStep('ui:route_sweep_admin.page/galactic-command')).toEqual(
      { lifecycle: 'route_sweep_admin', step: 'page/galactic-command', phone: false })
    expect(splitStep('ui:phone_onboarding @phone-only @first-visit.register-form-fits-the-phone@phone')).toEqual(
      { lifecycle: 'phone_onboarding @phone-only @first-visit', step: 'register-form-fits-the-phone', phone: true })
    // a row outside the pattern keeps its whole name as the step
    expect(splitStep('mcp-tester-page')).toEqual({ lifecycle: '', step: 'mcp-tester-page', phone: false })
  })

  it('takes the tags off a lifecycle title', () => {
    expect(titleAndTags('onboarding_register_login_logout @first-visit')).toEqual(
      { title: 'onboarding_register_login_logout', tags: ['first-visit'] })
    expect(titleAndTags('console_smoke')).toEqual({ title: 'console_smoke', tags: [] })
  })

  it('reads the outcome from the row status first, then its flags', () => {
    expect(stepOutcome({ tool: 'a', status: 'ok', healthy: true })).toBe('pass')
    expect(stepOutcome({ tool: 'a', status: 'known', healthy: false, kind: 'expected' })).toBe('known')
    expect(stepOutcome({ tool: 'a', status: 'skip', skipped: true })).toBe('skip')
    expect(stepOutcome({ tool: 'a', status: 'fail', healthy: false, kind: 'bug' })).toBe('fail')
    expect(stepOutcome({ tool: 'a', skipped: true })).toBe('skip')
    expect(stepOutcome({ tool: 'a', healthy: false })).toBe('fail')
  })
})

describe('§MCPTEST30 V0555: a run reads as its lifecycles, the ones to read first on top', () => {
  const run = {
    lifecycles: [
      { lifecycle: 'console_smoke', project: 'desktop', status: 'passed', duration_s: 1.9, steps: 2 },
      { lifecycle: 'mcp_tester_page_reads_a_run', project: 'desktop', status: 'failed', duration_s: 40, steps: 2,
        capture: { requests: 90, console_errors: 1, refused: 3, allowed_refusals: 1, unexpected: ['GET /x answered 500'] } },
      { lifecycle: 'browser_storage @first-visit', project: 'desktop', status: 'passed', steps: 1 },
      { lifecycle: 'browser_storage @first-visit', project: 'phone', status: 'passed', steps: 1 },
      { lifecycle: 'tours', project: 'desktop', status: 'passed', steps: 1 },
    ],
    results: [
      { tool: 'ui:console_smoke.login-page-renders', status: 'ok', healthy: true, elapsed: 0.4, response_excerpt: 'title' },
      { tool: 'ui:console_smoke.shell-renders', status: 'ok', healthy: true },
      { tool: 'ui:mcp_tester_page_reads_a_run.tester-page-opens', status: 'ok', healthy: true },
      { tool: 'ui:mcp_tester_page_reads_a_run.tiles-match-the-run', status: 'fail', healthy: false, kind: 'bug',
        error: 'Expected 35, received 0' },
      { tool: 'ui:browser_storage @first-visit.page-clean', status: 'ok', healthy: true },
      { tool: 'ui:browser_storage @first-visit.page-clean@phone', status: 'known', kind: 'expected', error: 'redoc logo' },
      { tool: 'ui:tours.tour-cockpit', status: 'skip', skipped: true, skip_reason: 'not offered on this registry' },
      { tool: 'ui:orphan_lifecycle.only-step', status: 'ok', healthy: true },
    ],
  }

  it('puts every step under its lifecycle and screen, and orders failed, known, skipped, clean', () => {
    const v = groupRun(run as any)
    expect(v.map((x) => [x.name, x.project, x.verdict])).toEqual([
      ['mcp_tester_page_reads_a_run', 'desktop', 'failed'],
      ['browser_storage @first-visit', 'phone', 'known'],
      ['tours', 'desktop', 'skipped'],
      ['console_smoke', 'desktop', 'clean'],
      ['browser_storage @first-visit', 'desktop', 'clean'],
      ['orphan_lifecycle', 'desktop', 'clean'],
    ])
    const failed = v[0]
    expect(failed.counts).toEqual({ pass: 1, fail: 1, skip: 0, known: 0 })
    expect(failed.steps[1]).toMatchObject({ step: 'tiles-match-the-run', outcome: 'fail', said: 'Expected 35, received 0' })
    expect(v[2].steps[0].said).toBe('not offered on this registry')
    expect(v[1].title).toBe('browser_storage')
    expect(v[1].tags).toEqual(['first-visit'])
    // every row the run recorded is on the page, once
    expect(v.reduce((n, x) => n + x.steps.length, 0)).toBe(run.results.length)
  })

  it('totals what the browser captured, counting only the refusals nobody allowed', () => {
    const t = captureTotals(run.lifecycles as any)
    expect(t).toEqual({ requests: 90, consoleErrors: 1, pageErrors: 0, refused: 2,
      unexpected: ['mcp_tester_page_reads_a_run: GET /x answered 500'] })
  })
})

describe('§MCPTEST30 V0555: a run in one word, and what it was asked to run', () => {
  const meta = (over: Partial<ConsoleSuiteRunMeta>): ConsoleSuiteRunMeta => ({
    run_id: 'fes-1', flow_name: 'flow_playwright_console_lifecycles', status: 'completed', started_at: 1,
    summary: { failed: 0, expected_red: 0, lifecycles: 48 }, scope: {}, ...over,
  })

  it('reads red for a failed step or a hard failure, amber for an expected red alone', () => {
    expect(runVerdict(meta({}))).toBe('clean')
    expect(runVerdict(meta({ summary: { failed: 2 } }))).toBe('failed')
    expect(runVerdict(meta({ summary: { failed: 0, hard_failures: 1 } }))).toBe('failed')
    expect(runVerdict(meta({ summary: { expected_red: 1 } }))).toBe('known')
    expect(runVerdict(meta({ status: 'running' }))).toBe('running')
    expect(runVerdict(meta({ status: 'error', error: 'browser died' }))).toBe('error')
  })

  it('says whether the whole suite ran, and says nothing it was not told', () => {
    expect(readScope(meta({ scope: { full: true, project: 'all', by: 'nightly' } }))).toEqual(
      { whole: true, lifecycles: 48, pattern: null, project: 'all', by: 'nightly' })
    expect(readScope(meta({ scope: { full: false, grep: 'wording' }, summary: { lifecycles: 1 } }))).toMatchObject(
      { whole: false, lifecycles: 1, pattern: 'wording' })
    expect(readScope(meta({}))).toMatchObject({ whole: null, pattern: null, by: null })
  })

  it('filters the list the way its chips say', () => {
    const runs = [meta({ run_id: 'a', scope: { full: true } }), meta({ run_id: 'b', summary: { failed: 1 } }),
      meta({ run_id: 'c' })]
    expect(filterRuns(runs, 'all').map((r) => r.run_id)).toEqual(['a', 'b', 'c'])
    expect(filterRuns(runs, 'whole').map((r) => r.run_id)).toEqual(['a'])
    expect(filterRuns(runs, 'failed').map((r) => r.run_id)).toEqual(['b'])
  })
})
