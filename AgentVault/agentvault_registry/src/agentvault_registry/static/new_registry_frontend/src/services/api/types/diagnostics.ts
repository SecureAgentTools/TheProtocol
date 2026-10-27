// TypeScript mirror of agentvault_registry/services/diagnostics/schemas.py
// Keep in sync with the backend pydantic models.

export type CheckStatus = 'ok' | 'warn' | 'fail' | 'unknown'
export type TargetStatus = 'healthy' | 'degraded' | 'down' | 'unknown'

export interface RemediationHint {
  action_id: string
  description: string
  destructive: boolean
  requires_confirmation: boolean
}

export interface CheckResult {
  check_id: string
  target: string
  status: CheckStatus
  latency_ms: number
  summary: string
  details: Record<string, unknown>
  evidence: string
  checked_at: string
  remediation: RemediationHint | null
}

export interface CheckDescriptor {
  check_id: string
  title: string
  description: string
  cost_ms: number
  category: string
}

export interface TargetSummary {
  operator_id: string
  display_name: string
  // the frame the target belongs to: this registry's own name (or "T" for a frame-test's chained operator); the
  // retired letters' type promised a value the server stopped sending at V0521
  frame: string
  // 'frame': this registry itself when it is a frame (§MCPTEST30 V0562), measured without Docker
  role: 'mainframe' | 'operator' | 'frame'
  // this registry itself, a frame or an operator (V0562): listed first, named "this registry"
  is_self?: boolean
  cloud_url: string | null
  status: TargetStatus
  last_snapshot_at: string | null
  check_results: CheckResult[]
}

export interface RunAllResponse {
  target: string
  results: CheckResult[]
  count: number
  total_latency_ms: number
}

export interface RunResponse {
  results: CheckResult[]
  count: number
}

export interface TargetsResponse {
  targets: TargetSummary[]
  count: number
  // §MCPTEST30 (V0561): why the list holds no operator (null when it holds one). V0562: always no_operators; the two
  // container causes moved to containers_reason (operators come from the frame's own peer rows whatever they say)
  reason?: string | null
  reason_code?: 'scope_off' | 'no_socket' | 'no_operators' | null
  containers_reason?: string | null
  containers_reason_code?: 'scope_off' | 'no_socket' | null
}

export interface ChecksResponse {
  checks: CheckDescriptor[]
  count: number
}

export interface ActionDescriptor {
  action_id: string
  description: string
  destructive: boolean
  post_check: string
  requires_confirmation: boolean
}

export interface ActionsResponse {
  actions: ActionDescriptor[]
  count: number
}

export interface ActionResult {
  action_id: string
  target: string
  status: 'ok' | 'fail' | 'skipped'
  summary: string
  evidence: string
  dry_run: boolean
  triggered_check: CheckResult | null
  invoked_at: string
}

export interface ConfigResponse {
  target: string
  docker?: Record<string, unknown>
  env?: Record<string, string>
  nginx?: string | null
  spire?: Record<string, unknown>
  partner_tegs?: string[] | null
}
