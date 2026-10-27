/**
 * The run record (§FESUITE): one JSON object in the MCP tester's run shape, so a console run can be imported into the
 * tester's history beside the MCP runs (flow_playwright_console_lifecycles), plus a short summary for a human.
 *
 * Every row comes from a lifecycle's own steps (support/steps.ts). A test that failed outside any step still gets a row,
 * so a run can never look greener than it was.
 */
import fs from 'node:fs'
import path from 'node:path'
import type { FullConfig, FullResult, Reporter, Suite, TestCase, TestResult } from '@playwright/test/reporter'
import type { StepRow } from './steps'
import { STEPS_ATTACHMENT, CAPTURE_ATTACHMENT } from './names'
import { OUT_DIR, RUN_ID, FRAME_LABEL, PREFIX } from './env'

export const FLOW_NAME = 'flow_playwright_console_lifecycles'
export const FLOW_LABEL = 'Console lifecycles (Playwright)'
/** The one source of a red-by-design row (kind 'expected'): the accessibility ratchet's baseline (support/fixtures.ts). */
const EXPECTED_RED = "within the accessibility ratchet's baseline (e2e/suite/a11y-baseline.json)"
/** Failures that are the host's or the toolchain's, never the product's: counted apart from product failures. */
const ENV_ERROR = /browserType\.launch|Executable doesn't exist|net::ERR_NETWORK_CHANGED|net::ERR_NETWORK_IO_SUSPENDED|Target page, context or browser has been closed|ECONNREFUSED 127\.0\.0\.1/

interface LifecycleRecord {
  lifecycle: string
  project: string
  status: string
  duration_s: number
  steps: number
  capture: Record<string, unknown> | null
  a11y?: unknown
}

function readAttachment(result: TestResult, name: string): unknown {
  const a = result.attachments.find((x) => x.name === name)
  if (!a) return null
  try {
    const body = a.body ? a.body.toString('utf8') : a.path ? fs.readFileSync(a.path, 'utf8') : ''
    return body ? JSON.parse(body) : null
  } catch {
    return null
  }
}

function clip(s: string, n = 400): string {
  const one = s.replace(/\u001b\[[0-9;]*m/g, '').replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n) + '…' : one
}

class FesuiteReporter implements Reporter {
  private started = new Date()
  private rows: StepRow[] = []
  private lifecycles: LifecycleRecord[] = []
  private log: Array<{ ts: string; msg: string }> = []
  /** An earlier attempt that failed, by test id: what it said and whether the host dropped calls under it. */
  private earlier = new Map<string, { error: string; env: boolean }>()

  private note(msg: string): void {
    this.log.push({ ts: new Date().toISOString(), msg: clip(msg, 600) })
  }

  onBegin(config: FullConfig, suite: Suite): void {
    this.started = new Date()
    const n = suite.allTests().length
    this.note(`run ${RUN_ID} begins: ${n} lifecycle(s), prefix ${PREFIX}${FRAME_LABEL ? `, target ${FRAME_LABEL}` : ''}`)
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    const project = test.parent.project()?.name || ''
    const lifecycle = test.title
    const willRetry = result.status !== test.expectedStatus && result.retry < test.retries
    if (willRetry) {
      const cap = readAttachment(result, CAPTURE_ATTACHMENT) as Record<string, number> | null
      const error = result.errors.map((e) => e.message || '').join(' | ') || result.status
      const env = ENV_ERROR.test(error) || Number(cap?.env_drops || 0) > 0
      this.earlier.set(test.id, { error: clip(error, 300), env })
      this.note(`${lifecycle}: attempt ${result.retry + 1} ${result.status}${env ? ' (the host dropped calls)' : ''}: ${clip(error, 200)}; retrying`)
      return
    }
    let rows = (readAttachment(result, STEPS_ATTACHMENT) as StepRow[] | null) || []
    const capture = readAttachment(result, CAPTURE_ATTACHMENT) as Record<string, unknown> | null
    const tag = project && project !== 'desktop' ? `@${project}` : ''
    if (test.expectedStatus === 'failed') {
      // A control: the suite's own gate must refuse what the control plants. Refusing is the healthy outcome.
      const held = result.status === 'failed'
      const why = result.errors.map((e) => e.message || '').join(' | ')
      rows = [{
        tool: `ui:${lifecycle}.control`, tier: 'ui:public', healthy: held, skipped: false, status: held ? 'ok' : 'fail',
        elapsed: result.duration / 1000, error: held ? null : 'the control was NOT refused: the gate cannot fail',
        skip_reason: null, response_excerpt: held ? clip(`refused as designed: ${why}`, 300) : null, kind: held ? null : 'bug',
      }]
      for (const r of rows) this.rows.push(tag ? { ...r, tool: `${r.tool}${tag}` } : r)
      this.lifecycles.push({ lifecycle, project, status: held ? 'passed' : 'failed', duration_s: result.duration / 1000, steps: 1, capture })
      this.note(`${lifecycle}${tag}: control ${held ? 'held' : 'DID NOT HOLD'}`)
      return
    }
    for (const r of rows) this.rows.push(tag ? { ...r, tool: `${r.tool}${tag}` } : r)
    const failedInStep = rows.some((r) => !r.healthy && !r.skipped)
    if ((result.status === 'failed' || result.status === 'timedOut') && !failedInStep) {
      // The test failed outside any recorded step (setup, the capture verdict, a timeout): it still gets a row.
      const err = result.errors.map((e) => e.message || '').join(' | ') || result.status
      this.rows.push({
        tool: `ui:${lifecycle}.unrecorded${tag}`, tier: 'ui:developer', healthy: false, skipped: false,
        status: result.status === 'timedOut' ? 'timeout' : 'fail', elapsed: result.duration / 1000,
        error: clip(err), skip_reason: null, response_excerpt: null, kind: ENV_ERROR.test(err) ? 'env' : 'bug',
      })
    }
    if (result.status === 'skipped') {
      this.rows.push({
        tool: `ui:${lifecycle}${tag}`, tier: 'ui:developer', healthy: false, skipped: true, status: 'skip',
        elapsed: 0, error: null, skip_reason: clip(test.annotations.map((a) => a.description || a.type).join('; ') || 'skipped'),
        response_excerpt: null, kind: null,
      })
    }
    const before = this.earlier.get(test.id)
    if (before && result.status === 'passed' && !before.env) {
      // It failed once with no help from the host, then passed: the product is flaky here, which is a finding.
      this.rows.push({
        tool: `ui:${lifecycle}.flaky${tag}`, tier: 'ui:developer', healthy: false, skipped: false, status: 'flaky',
        elapsed: 0, error: `failed once, then passed on retry: ${before.error}`, skip_reason: null, response_excerpt: null,
        kind: 'bug',
      })
    }
    this.lifecycles.push({
      lifecycle, project, status: result.status, duration_s: result.duration / 1000, steps: rows.length, capture,
      a11y: readAttachment(result, 'fesuite-a11y'),
    })
    this.note(`${lifecycle}${tag}: ${result.status} in ${(result.duration / 1000).toFixed(1)} s, ${rows.length} step(s)`)
  }

  onEnd(result: FullResult): void {
    const finished = new Date()
    const measured = this.rows.filter((r) => !r.skipped)
    const passed = measured.filter((r) => r.healthy).length
    const failed = measured.length - passed
    const skipped = this.rows.filter((r) => r.skipped)
    const bugs = this.rows.filter((r) => !r.healthy && !r.skipped && r.kind === 'bug')
    const env = this.rows.filter((r) => !r.healthy && !r.skipped && r.kind === 'env')
    const expected = this.rows.filter((r) => !r.healthy && !r.skipped && r.kind === 'expected')
    const sum = (k: string) => this.lifecycles.reduce((a, l) => a + Number((l.capture as Record<string, number> | null)?.[k] || 0), 0)
    const run = {
      run_id: RUN_ID,
      status: result.status === 'interrupted' ? 'error' : 'completed',
      started_at: this.started.toISOString(),
      finished_at: finished.toISOString(),
      flow_name: FLOW_NAME,
      flow_label: FLOW_LABEL,
      summary: {
        tool_count: this.rows.length,
        passed,
        failed,
        skipped: skipped.length,
        policy_denied: 0,
        bug_finds: bugs.length,
        hard_failures: bugs.length + env.length,
        expected_red: expected.length,
        pass_pct: measured.length ? Math.round((passed / measured.length) * 10000) / 100 : 0,
        wall_s: Math.round((finished.getTime() - this.started.getTime()) / 100) / 10,
        lifecycles: this.lifecycles.length,
        lifecycles_passed: this.lifecycles.filter((l) => l.status === 'passed').length,
        env_drops: sum('env_drops'),
        requests: sum('requests'),
        console_errors: sum('console_errors'),
        page_errors: sum('page_errors'),
        refused_calls: sum('refused'),
        allowed_refusals: sum('allowed_refusals'),
        target: FRAME_LABEL || null,
        prefix: PREFIX,
      },
      error: result.status === 'interrupted' ? 'the run was interrupted' : null,
      // The MCP tester's own forms, one object per row (agentvault2-32's finding, 2026-10-01): its page reads `.tool` of
      // each entry and labels a result row by `name`; a "tool: text" string threw there, and the error boundary blanked
      // the whole page (EU's V0520 too) whenever a run in the old shape was loaded.
      results: this.rows.map((r) => ({ ...r, name: r.tool })),
      bug_finds: bugs.map((r) => ({ tool: r.tool, error: r.error || '' })),
      hard_fails: [...bugs, ...env].map((r) => ({ tool: r.tool, error: r.error || '' })),
      expected_reds: expected.map((r) => ({ tool: r.tool, error: r.error || '', expected_red: EXPECTED_RED })),
      skipped: skipped.map((r) => ({ tool: r.tool, reason: r.skip_reason || '' })),
      policy_denied: [] as Array<{ tool: string; reason: string }>,
      log_lines: this.log,
    }
    fs.mkdirSync(OUT_DIR, { recursive: true })
    fs.writeFileSync(path.join(OUT_DIR, 'run.json'), JSON.stringify(run, null, 2))
    // Every lifecycle's full capture (each unexpected console line and refused call), for the person reading a red row.
    fs.writeFileSync(path.join(OUT_DIR, 'lifecycles.json'), JSON.stringify(this.lifecycles, null, 2))
    const lines = [
      `# ${FLOW_LABEL}: run ${RUN_ID}`,
      '',
      `${run.status}: ${passed} of ${measured.length} measured steps healthy, ${failed} failed (${bugs.length} product, ${env.length} environment${expected.length ? `, ${expected.length} within a ratchet baseline` : ''}), ${skipped.length} not measured; ${run.summary.lifecycles_passed} of ${run.summary.lifecycles} lifecycles passed in ${run.summary.wall_s} s.`,
      '',
      '| lifecycle | project | status | steps | s |',
      '|---|---|---|---|---|',
      ...this.lifecycles.map((l) => `| ${l.lifecycle} | ${l.project} | ${l.status} | ${l.steps} | ${l.duration_s.toFixed(1)} |`),
      '',
      ...(bugs.length ? ['## Failed steps', '', ...bugs.map((r) => `- ${r.tool}: ${r.error}`), ''] : []),
      ...(env.length ? ['## Environment drops', '', ...env.map((r) => `- ${r.tool}: ${r.error}`), ''] : []),
      ...(expected.length ? ['## Red by design', '', ...expected.map((r) => `- ${r.tool}: ${r.error}`), ''] : []),
      ...(skipped.length ? ['## Not measured', '', ...skipped.map((r) => `- ${r.tool}: ${r.skip_reason}`), ''] : []),
    ]
    fs.writeFileSync(path.join(OUT_DIR, 'summary.md'), lines.join('\n'))
    process.stdout.write(`\n[fesuite] ${lines[2]}\n[fesuite] record: ${path.join(OUT_DIR, 'run.json')}\n`)
  }
}

export default FesuiteReporter
