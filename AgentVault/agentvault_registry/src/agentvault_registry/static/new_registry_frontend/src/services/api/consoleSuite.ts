/**
 * §MCPTEST30 (V0555): the console suite's history (`/admin/console-suite/*`, routers/console_suite.py). The suite runs on
 * the host (scripts/fesuite/run.py) and records each run here; this console only reads.
 */
import { apiClient } from './client'

export interface ConsoleSuiteSummary {
  tool_count?: number
  passed?: number
  failed?: number
  skipped?: number
  policy_denied?: number
  bug_finds?: number
  hard_failures?: number
  expected_red?: number
  pass_pct?: number
  wall_s?: number
  lifecycles?: number
  lifecycles_passed?: number
  requests?: number
  console_errors?: number
  page_errors?: number
  refused_calls?: number
  allowed_refusals?: number
  env_drops?: number
  target?: string
  prefix?: string
  [k: string]: unknown
}

/** What the runner was asked to run: the whole suite, or the lifecycles a pattern picked, on which screens. */
export interface ConsoleSuiteScope {
  target?: string
  grep?: string | null
  project?: string
  full?: boolean
  dist?: string
  by?: string
  [k: string]: unknown
}

export interface ConsoleSuiteRunMeta {
  run_id: string
  flow_name: string
  flow_label?: string | null
  status: string
  error?: string | null
  started_at: number
  finished_at?: number | null
  summary: ConsoleSuiteSummary
  scope: ConsoleSuiteScope
  lifecycle_names?: string[]
  projects?: string[]
}

export interface ConsoleSuiteCapture {
  requests?: number
  refused?: number
  allowed_refusals?: number
  transport_failures?: number
  env_drops?: number
  console_errors?: number
  console_warnings?: number
  page_errors?: number
  unexpected?: string[]
  [k: string]: unknown
}

export interface ConsoleSuiteLifecycle {
  lifecycle: string
  project?: string | null
  status?: string | null
  duration_s?: number | null
  steps?: number | null
  capture?: ConsoleSuiteCapture
  a11y?: Record<string, unknown> | null
}

export interface ConsoleSuiteStep {
  tool: string
  tier?: string | null
  healthy?: boolean | null
  skipped?: boolean
  status?: string | null
  elapsed?: number | null
  error?: string | null
  skip_reason?: string | null
  response_excerpt?: string | null
  kind?: string | null
}

export interface ConsoleSuiteEntry {
  tool: string
  error?: string | null
  reason?: string | null
}

export interface ConsoleSuiteRun extends ConsoleSuiteRunMeta {
  lifecycles: ConsoleSuiteLifecycle[]
  results: ConsoleSuiteStep[]
  log_lines: { ts?: string | null; msg?: string | null }[]
  bug_finds: ConsoleSuiteEntry[]
  hard_fails: ConsoleSuiteEntry[]
  expected_reds: ConsoleSuiteEntry[]
  skipped: ConsoleSuiteEntry[]
  policy_denied: ConsoleSuiteEntry[]
}

export const consoleSuiteApi = {
  async listRuns(limit = 60): Promise<{ runs: ConsoleSuiteRunMeta[]; total: number; cap: number }> {
    const { data } = await apiClient.get('/admin/console-suite/runs', { params: { limit } })
    return data
  },

  async getRun(runId: string): Promise<ConsoleSuiteRun> {
    const { data } = await apiClient.get(`/admin/console-suite/runs/${encodeURIComponent(runId)}`)
    return data
  },
}
