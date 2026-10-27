/**
 * §MCPTEST30 (V0555): how the console-suite page reads a run (pure, unit-tested in __tests__/reading.spec.ts).
 *
 * The suite reports one row per step a lifecycle takes, named `ui:<lifecycle>.<step>`; a lifecycle's title can carry
 * tags (`onboarding_register_login_logout @first-visit`) and never a dot, and a step taken on the phone project ends in
 * `@phone`. Its `lifecycles` list says how each lifecycle went as a whole (status, time, what the browser captured).
 */
import type {
  ConsoleSuiteCapture, ConsoleSuiteLifecycle, ConsoleSuiteRun, ConsoleSuiteRunMeta, ConsoleSuiteStep,
} from '@/services/api/consoleSuite'

export type StepOutcome = 'pass' | 'fail' | 'skip' | 'known'

export interface StepView {
  tool: string
  step: string
  outcome: StepOutcome
  tier: string
  elapsed: number | null
  /** what the step observed, or why it failed or was not measured */
  said: string
}

export interface LifecycleView {
  key: string
  name: string
  title: string
  tags: string[]
  project: string
  status: string
  duration_s: number | null
  capture: ConsoleSuiteCapture | null
  steps: StepView[]
  counts: Record<StepOutcome, number>
  /** failed (a step or the lifecycle), known (an expected red), clean, or skipped (nothing measured) */
  verdict: 'failed' | 'known' | 'clean' | 'skipped'
}

/** `ui:<lifecycle>.<step>[@phone]` into its parts; a row that does not follow the pattern keeps its name as the step. */
export function splitStep(tool: string): { lifecycle: string; step: string; phone: boolean } {
  const body = tool.startsWith('ui:') ? tool.slice(3) : tool
  const dot = body.indexOf('.')
  const lifecycle = dot > 0 ? body.slice(0, dot) : ''
  let step = dot > 0 ? body.slice(dot + 1) : body
  const phone = step.endsWith('@phone')
  if (phone) step = step.slice(0, -'@phone'.length)
  return { lifecycle, step, phone }
}

/** The title without its tags, and the tags (`@first-visit` reads first-visit). */
export function titleAndTags(name: string): { title: string; tags: string[] } {
  const parts = name.split(/\s+/).filter(Boolean)
  const tags = parts.filter((p) => p.startsWith('@')).map((p) => p.slice(1))
  const title = parts.filter((p) => !p.startsWith('@')).join(' ')
  return { title: title || name, tags }
}

export function stepOutcome(row: ConsoleSuiteStep): StepOutcome {
  const s = (row.status || '').toLowerCase()
  if (s === 'ok') return 'pass'
  if (s === 'fail') return 'fail'
  if (s === 'skip') return 'skip'
  if (s === 'known') return 'known'
  if (row.skipped) return 'skip'
  if (row.kind === 'expected') return 'known'
  return row.healthy ? 'pass' : 'fail'
}

function said(row: ConsoleSuiteStep, outcome: StepOutcome): string {
  if (outcome === 'skip') return row.skip_reason || row.error || ''
  if (outcome === 'fail' || outcome === 'known') return row.error || row.response_excerpt || ''
  return row.response_excerpt || ''
}

const ORDER: Record<LifecycleView['verdict'], number> = { failed: 0, known: 1, skipped: 2, clean: 3 }

/**
 * The run's lifecycles, each with its own steps, the ones that need reading first (a failure, then an expected red), in
 * the run's own order within each group. A step whose lifecycle is missing from the run's `lifecycles` list still shows,
 * under a lifecycle made for it, so nothing the run recorded is left off the page.
 */
export function groupRun(run: Pick<ConsoleSuiteRun, 'lifecycles' | 'results'>): LifecycleView[] {
  const views = new Map<string, LifecycleView>()
  const make = (lc: ConsoleSuiteLifecycle | null, name: string, project: string): LifecycleView => {
    const { title, tags } = titleAndTags(name)
    return {
      key: `${name}|${project}`, name, title, tags, project,
      status: lc?.status || '', duration_s: lc?.duration_s ?? null, capture: lc?.capture ?? null,
      steps: [], counts: { pass: 0, fail: 0, skip: 0, known: 0 }, verdict: 'clean',
    }
  }
  for (const lc of run.lifecycles || []) {
    const project = lc.project || 'desktop'
    const v = make(lc, lc.lifecycle, project)
    if (!views.has(v.key)) views.set(v.key, v)
  }
  for (const row of run.results || []) {
    const { lifecycle, step, phone } = splitStep(row.tool)
    const name = lifecycle || '(unnamed)'
    // a phone step belongs to the phone run of its lifecycle; any other to the lifecycle's first non-phone run
    let v: LifecycleView | undefined = phone ? views.get(`${name}|phone`) : undefined
    if (!v && !phone) v = [...views.values()].find((x) => x.name === name && x.project !== 'phone')
    if (!v) v = [...views.values()].find((x) => x.name === name)
    if (!v) {
      v = make(null, name, phone ? 'phone' : 'desktop')
      views.set(v.key, v)
    }
    const outcome = stepOutcome(row)
    v.counts[outcome] += 1
    v.steps.push({
      tool: row.tool, step, outcome, tier: (row.tier || '').replace(/^ui:/, ''),
      elapsed: typeof row.elapsed === 'number' ? row.elapsed : null, said: said(row, outcome),
    })
  }
  const out = [...views.values()]
  for (const v of out) {
    const st = v.status.toLowerCase()
    v.verdict = v.counts.fail > 0 || st === 'failed' || st === 'timedout' || st === 'interrupted' ? 'failed'
      : v.counts.known > 0 ? 'known'
        : v.steps.length > 0 && v.counts.skip === v.steps.length ? 'skipped'
          : st === 'skipped' && v.steps.length === 0 ? 'skipped' : 'clean'
  }
  return out
    .map((v, i) => ({ v, i }))
    .sort((a, b) => ORDER[a.v.verdict] - ORDER[b.v.verdict] || a.i - b.i)
    .map(({ v }) => v)
}

export type RunVerdict = 'failed' | 'known' | 'clean' | 'error' | 'running'

/** One word for a run, from its own counts: a failed step or a hard failure is red; an expected red alone is amber. */
export function runVerdict(m: Pick<ConsoleSuiteRunMeta, 'status' | 'summary' | 'error'>): RunVerdict {
  const st = (m.status || '').toLowerCase()
  if (st === 'running' || st === 'queued') return 'running'
  const s = m.summary || {}
  if (Number(s.failed || 0) > 0 || Number(s.hard_failures || 0) > 0) return 'failed'
  if (st && st !== 'completed') return 'error'
  if (Number(s.expected_red || 0) > 0) return 'known'
  return 'clean'
}

export interface ScopeReading {
  /** the runner was asked for the whole suite (true), for some of it (false), or did not say (null: an older record) */
  whole: boolean | null
  lifecycles: number
  pattern: string | null
  project: string | null
  by: string | null
}

export function readScope(m: Pick<ConsoleSuiteRunMeta, 'scope' | 'summary' | 'lifecycle_names'>): ScopeReading {
  const sc = m.scope || {}
  const pattern = typeof sc.grep === 'string' && sc.grep ? sc.grep : null
  const whole = typeof sc.full === 'boolean' ? sc.full : null
  const n = Number(m.summary?.lifecycles ?? m.lifecycle_names?.length ?? 0)
  return {
    whole, lifecycles: Number.isFinite(n) ? n : 0, pattern,
    project: typeof sc.project === 'string' && sc.project ? sc.project : null,
    by: typeof sc.by === 'string' && sc.by ? sc.by : null,
  }
}

/** Runs filtered the way the page's chips ask: every run, whole-suite runs only, or runs with a failure. */
export function filterRuns<T extends ConsoleSuiteRunMeta>(runs: T[], f: 'all' | 'whole' | 'failed'): T[] {
  if (f === 'whole') return runs.filter((r) => readScope(r).whole === true)
  if (f === 'failed') return runs.filter((r) => runVerdict(r) === 'failed')
  return runs
}

/** The browser's own complaints across a run's lifecycles (console errors, page errors, refused calls nobody allowed). */
export function captureTotals(lcs: ConsoleSuiteLifecycle[]): {
  requests: number; consoleErrors: number; pageErrors: number; refused: number; unexpected: string[]
} {
  let requests = 0, consoleErrors = 0, pageErrors = 0, refused = 0
  const unexpected: string[] = []
  for (const lc of lcs || []) {
    const c = lc.capture || {}
    requests += Number(c.requests || 0)
    consoleErrors += Number(c.console_errors || 0)
    pageErrors += Number(c.page_errors || 0)
    refused += Math.max(0, Number(c.refused || 0) - Number(c.allowed_refusals || 0))
    for (const u of c.unexpected || []) if (u && unexpected.length < 50) unexpected.push(`${lc.lifecycle}: ${u}`)
  }
  return { requests, consoleErrors, pageErrors, refused, unexpected }
}
