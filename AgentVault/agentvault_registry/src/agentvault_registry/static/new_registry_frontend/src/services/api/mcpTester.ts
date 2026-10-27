/**
 * MCP Tester API wrapper — frontend-facing client for the
 * `/admin/mcp-tester/*` routes.
 *
 * The MCP Tester is sandbox-only — every call here proxies into
 * sandbox-A behind the scenes (the backend enforces that via
 * API_TEST_TARGET_URL). The frontend view shows a banner if the
 * backend reports `is_sandbox=false`.
 */
import { apiClient } from './client'

export interface McpTesterSummary {
  tool_count: number
  explicit_contracts: number
  default_contracts: number
  passed: number
  /** Tools we could NOT exercise — a coverage hole, work owed. */
  skipped: number
  /**
   * §MCPTEST-MCP10 — tools the harness REFUSES to invoke under a standing
   * operating rule (provisioning, teardown, sim start/stop, canary fleet
   * pause). Declined on purpose, not a coverage hole. Optional because runs
   * recorded before MCP10 conflated it with `skipped` and cannot be split
   * retroactively.
   */
  policy_denied?: number
  failed: number
  pass_pct: number
  wall_s: number
  bug_finds: number
  hard_failures: number
  /** Phase D taxonomy — test-side drift (over-claim / stale contract). */
  contract_gap?: number
  /** Phase D taxonomy — audit.py tier-set lag (tier='unknown'). */
  tier_drift?: number
  /** Phase F.1 — wrong-tier auth probes that did NOT 401/403 (privilege-escalation regression). */
  auth_matrix_violations?: number
  /** Phase F.1 — total wrong-tier probes attempted. */
  auth_matrix_total?: number
  /** Phase F.4 — public tools whose Frame A/B response shape diverges. */
  cross_frame_drift?: number
  /** Phase F.5 — eventual-consistency assertions that timed out. */
  consistency_violations?: number
  /** Phase F.2 — tools 2x slower than prior-3 median baseline. */
  latency_regressions?: number
  /** §MCPTEST30 (V0544) — how much slower than its baselines the whole run ran; a tool is flagged beyond twice that. */
  latency_run_factor?: number | null
  /** §MCPTEST30 (V0544) — how many tools had a baseline to be compared with; 0 means the latency check measured nothing. */
  latency_baselined_tools?: number | null
  // §MCPTEST30 (V0545): mutations whose read-after-write answered 2xx without any key its check reads
  unjudged_read_backs?: string[] | null
  /** Phase F.3 — since V0547 the tools whose route refuses the request they send (the request survey, sealed on the
   *  target); before, wrappers whose documented inputSchema diverged from the route's model. */
  wrapper_drift?: number
  /** §MCPTEST30 (V0547) — the tools the survey called, the build gate's named exceptions (listed apart, not counted),
   *  why a strict run did not measure (null when it did) and the check's source. */
  wrapper_drift_surveyed?: number | null
  wrapper_drift_known?: Array<{ tool: string; reason: string }> | null
  wrapper_drift_reason?: string | null
  wrapper_drift_source?: string | null
  /** §MCPTEST30 (V0547) — tools whose route authenticates only a federation peer: no MCP caller can succeed (reported). */
  wrapper_peer_route?: Array<{ tool: string; surface: string; class?: string; detail: string }> | null
  /** §MCPTEST30 (V0549) — the passing tool rows by how deep they were checked: against a contract a person wrote or
   *  the default one, a success or a refusal (probes and federation rows are outside it). Absent before V0549. */
  pass_depth?: { success_contract: number; success_default: number; refusal_contract: number; refusal_default: number } | null
  /** §MCPTEST30 (V0636) — the tool rows whose only pass was a refusal, moved to not measured, and the counts the
   *  target itself recorded before that. Absent before V0636. */
  refusal_only?: number | null
  target_counts?: { passed?: number | null; skipped?: number | null; pass_pct?: number | null } | null
  /** §MCPTEST30 (V0550) — the switches the target reported in its registry-config, whether they could be read, and the
   *  tool rows held to a switched-off tool's refusal. Absent before V0550. */
  target_switches?: Record<string, boolean | string> | null
  target_switches_read?: boolean | null
  switched_off_rows?: string[] | null
  /** §MCPTEST30 (V0541) — which drift detectors the run measured; a count above is a reading only where its own is true. */
  detectors?: { wrapper_route?: boolean; cross_frame?: boolean; auth_matrix?: boolean }
  /** §MCPTEST30 (V0541) — the tools the A↔B walk actually compared (it counts attempts as probes). */
  cross_frame_compared?: number | null
  /** emission_integrity HONESTY flag (2026-06-26) — a sidecar verdict computed
   *  from REAL EventStore polls + an mTLS handshake that the strict pass-rate is
   *  blind to (dead cross-frame settlement, silent emission NO-OPs, expired SPIRE
   *  bundles). Advisory only — does NOT flip rows red or change run status. */
  emission_integrity?: {
    status: 'ok' | 'warn' | 'degraded'
    checks: Record<string, { status: string; detail: string }>
    summary: string
  }
  /** §pass73.3.19 — which suite produced this run. */
  flow_name?: string
  flow_label?: string
  target: string
  is_sandbox: boolean
}

export interface McpTesterRunMeta {
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: number | null
  finished_at: number | null
  developer_id?: number
  /** §pass73.3.19 — suite identity (defaults to the strict MCP tester). */
  flow_name?: string
  flow_label?: string
  summary: McpTesterSummary | null
}

export interface McpTesterToolRow {
  tool: string
  tier: string
  healthy: boolean
  /** §MCPTEST30 (V0550) — the switch this row was held to (`staking_enabled=false`), or absent */
  switched_off?: string | null
  skipped: boolean
  status: number
  elapsed: number
  error: string | null
  skip_reason: string | null
  /** §MCPTEST30 (V0636) — its only pass was a refusal: moved to not measured (`skipped` is true with it) */
  refusal_only?: boolean | null
  /** Phase F.2 — flagged when current elapsed_ms > 2x median(prior-3). */
  latency_regression?: boolean
  /** Phase F.2 — the median(prior-3) value the regression is measured against. */
  latency_baseline_ms?: number
  /** pass73.3.19 — the backend's per-row axes ('pass' | 'fail' | 'skip' | 'unknown' | 'na'), keyed by axis. */
  axes?: Record<string, { state: string; detail?: string }>
}

export interface McpTesterRun extends McpTesterRunMeta {
  log_lines: { ts: number; msg: string }[]
  bug_finds: { tool: string; error: string }[]
  hard_fails: { tool: string; error: string }[]
  skipped: { tool: string; reason: string }[]
  /** §MCPTEST-MCP10 — refused-by-standing-order, kept apart from `skipped`. */
  policy_denied?: { tool: string; reason: string }[]
  results?: McpTesterToolRow[]
  error: string | null
}

export interface RunStartResponse {
  run_id: string
  started_at: number
  target: string
  is_sandbox: boolean
  flow_name: string
  flow_label?: string
  supported_flows?: Record<string, string>
  status: string
}

export const mcpTesterApi = {
  /** Kick off a new sweep. Returns immediately with run_id.
   *  §pass73.3.19: optional flowName selects which suite (MCP tester /
   *  federation suite / cloud-op sweeps); omitted = strict MCP tester. */
  async startRun(flowName?: string): Promise<RunStartResponse> {
    const body = flowName ? { flow_name: flowName } : {}
    const { data } = await apiClient.post('/admin/mcp-tester/run', body)
    return data
  },

  /** §pass73.3.19 — list the suites runnable from this view (for the selector). */
  // §MCPTEST30 (V0541): `target` and `is_sandbox` are this console's own posture (absent from a backend before V0541)
  async listFlows(): Promise<{ flows: { flow_name: string; label: string }[]; default: string; target?: string; is_sandbox?: boolean }> {
    const { data } = await apiClient.get('/admin/mcp-tester/flows')
    return data
  },

  /** List the most recent runs (history). */
  async listRuns(): Promise<{ runs: McpTesterRunMeta[]; total: number }> {
    const { data } = await apiClient.get('/admin/mcp-tester/runs')
    return data
  },

  /** Get the latest run's full state. */
  async latest(): Promise<{ run: McpTesterRun | null }> {
    const { data } = await apiClient.get('/admin/mcp-tester/latest')
    return data
  },

  /** Poll a specific run. Pass include_results=true to get the per-tool table. */
  async getRun(runId: string, includeResults = false): Promise<McpTesterRun> {
    const { data } = await apiClient.get(`/admin/mcp-tester/runs/${runId}`, {
      params: { include_results: includeResults },
    })
    return data
  },

  /** pass73.3.19 (2026-05-28) — Re-fire one tool instantly. Returns slim result row. */
  async refireSingle(tool: string, args: Record<string, any> = {}, tier: string = ''): Promise<any> {
    const { data } = await apiClient.post('/admin/mcp-tester/refire-single', { tool, args, tier })
    return data
  },

  /** pass73.3.19 — diff two completed runs by id. Returns delta categorized
   * into newly_failing, newly_passing, latency_regressed, latency_improved.
   * Client-side computation (FE-only — no backend round trip). */
  diffRuns(runA: any, runB: any): {
    newly_failing: any[]
    newly_passing: any[]
    latency_regressed: any[]
    latency_improved: any[]
    unchanged_count: number
  } {
    const byTool = (rs: any[]) => Object.fromEntries((rs || []).map(r => [r.tool, r]))
    const a = byTool(runA?.results || [])
    const b = byTool(runB?.results || [])
    const out = { newly_failing: [] as any[], newly_passing: [] as any[],
                  latency_regressed: [] as any[], latency_improved: [] as any[],
                  unchanged_count: 0 }
    for (const tool of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const ra = a[tool]; const rb = b[tool]
      if (!ra || !rb) continue
      const aHealthy = ra.healthy && !ra.skipped
      const bHealthy = rb.healthy && !rb.skipped
      if (aHealthy && !bHealthy) out.newly_failing.push({ tool, a: ra, b: rb })
      else if (!aHealthy && bHealthy) out.newly_passing.push({ tool, a: ra, b: rb })
      else {
        const dt = (Number(rb.elapsed) || 0) - (Number(ra.elapsed) || 0)
        const factor = (Number(ra.elapsed) || 1) > 0 ? (Number(rb.elapsed) / Number(ra.elapsed)) : 1
        if (dt > 200 && factor > 1.5) out.latency_regressed.push({ tool, a_ms: ra.elapsed, b_ms: rb.elapsed, factor: factor.toFixed(2) })
        else if (dt < -200 && factor < 0.67) out.latency_improved.push({ tool, a_ms: ra.elapsed, b_ms: rb.elapsed, factor: factor.toFixed(2) })
        else out.unchanged_count++
      }
    }
    return out
  },

  /** The run-log SSE stream URL. Opened with `openSse` (services/sse.ts), which sends the JWT in the
   *  Authorization header: §RELEASEHARDEN D2 (2026-09-14) took the token out of the URL, where the
   *  access log recorded it, and this route had never read a query token anyway. */
  streamUrl(runId: string): string {
    const base = apiClient.defaults.baseURL || ''
    return `${base}/admin/mcp-tester/runs/${runId}/stream`
  },
}
