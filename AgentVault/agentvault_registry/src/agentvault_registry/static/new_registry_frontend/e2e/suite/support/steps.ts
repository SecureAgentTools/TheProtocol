/**
 * Step rows in the MCP tester's own shape (§FESUITE), so a console run can sit in the tester's history beside the
 * MCP runs: one row per step a lifecycle takes, named `ui:<lifecycle>.<step>` and tiered by the principal that took it.
 *
 * A step is HEALTHY only when its action ran AND its read-back agreed. A step the run could not measure is SKIPPED with
 * the reason, never quietly passed (§FANCLAIM): "not measured" and "passed" must never share a row.
 */
import { test, type TestInfo } from '@playwright/test'
import { STEPS_ATTACHMENT } from './names'

export type Tier = 'ui:public' | 'ui:developer' | 'ui:agent' | 'ui:admin'

export interface StepRow {
  tool: string
  tier: Tier
  healthy: boolean
  skipped: boolean
  status: number | string
  elapsed: number
  error: string | null
  skip_reason: string | null
  response_excerpt: string | null
  /** bug = a product defect this step found · env = the host, not the product · expected = a known red with a reason */
  kind: 'bug' | 'env' | 'expected' | null
}

function clip(s: string, n = 400): string {
  const one = s.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n) + '…' : one
}

/** A failure message without the noise Playwright appends (call logs, ANSI colour). */
export function cleanError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  const noAnsi = raw.replace(/\u001b\[[0-9;]*m/g, '')
  const head = noAnsi.split(/\n\s*Call log:/)[0]
  return clip(head)
}

export class Steps {
  readonly rows: StepRow[] = []

  constructor(private readonly lifecycle: string, private readonly info: TestInfo) {}

  /**
   * Run one step. `fn` returns what the step observed (a status, a count, a sentence): it becomes the row's excerpt.
   * A thrown error marks the row unhealthy and stops the lifecycle, like a failed MCP step stops its runner.
   */
  async run<T>(name: string, tier: Tier, fn: () => Promise<T>): Promise<T> {
    const t0 = Date.now()
    const tool = `ui:${this.lifecycle}.${name}`
    try {
      const out = await test.step(name, fn)
      this.rows.push({
        tool, tier, healthy: true, skipped: false, status: 'ok', elapsed: (Date.now() - t0) / 1000,
        error: null, skip_reason: null,
        response_excerpt: out === undefined || out === null ? null : clip(typeof out === 'string' ? out : JSON.stringify(out)),
        kind: null,
      })
      return out
    } catch (e) {
      this.rows.push({
        tool, tier, healthy: false, skipped: false, status: 'fail', elapsed: (Date.now() - t0) / 1000,
        error: cleanError(e), skip_reason: null, response_excerpt: null, kind: 'bug',
      })
      throw e
    }
  }

  private failedChecks: string[] = []

  /**
   * A check that records its row and lets the lifecycle go on: a sweep visits every page even when one fails. Call
   * assertChecks() at the end so a failed check still fails the test.
   */
  async check<T>(name: string, tier: Tier, fn: () => Promise<T>): Promise<boolean> {
    try {
      await this.run(name, tier, fn)
      return true
    } catch {
      this.failedChecks.push(name)
      return false
    }
  }

  assertChecks(): void {
    if (this.failedChecks.length) {
      throw new Error(`${this.failedChecks.length} check(s) failed: ${this.failedChecks.slice(0, 12).join(', ')}`)
    }
  }

  /** A step the run did not measure, with the reason. Never a pass. */
  notMeasured(name: string, tier: Tier, reason: string): void {
    this.rows.push({
      tool: `ui:${this.lifecycle}.${name}`, tier, healthy: false, skipped: true, status: 'skip', elapsed: 0,
      error: null, skip_reason: clip(reason), response_excerpt: null, kind: null,
    })
  }

  /** Mark the last failed row as the environment's (the host dropped a call), not the product's. */
  markLastAsEnv(note: string): void {
    const last = [...this.rows].reverse().find((r) => !r.healthy && !r.skipped)
    if (last) { last.kind = 'env'; last.error = clip(`${note}: ${last.error || ''}`) }
  }

  async flush(): Promise<void> {
    await this.info.attach(STEPS_ATTACHMENT, { body: JSON.stringify(this.rows), contentType: 'application/json' })
  }
}
