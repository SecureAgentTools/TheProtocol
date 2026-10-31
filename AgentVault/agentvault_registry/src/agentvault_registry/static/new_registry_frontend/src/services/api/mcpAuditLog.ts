/**
 * services/api/mcpAuditLog.ts — §pass68 MCP audit log query surface.
 *
 *   GET /me/mcp-audit-log              — caller's own rows (dev JWT or API key)
 *   GET /admin/mcp-audit-log?actor_id  — admin variant (admin_support flag);
 *                                        cross-developer reads emit a self-watching
 *                                        `admin_read_mcp_audit` row into the target's log
 *
 * Both endpoints are keyset-paginated via `next_cursor`. Hard caps:
 *   limit ∈ [1, 200], default 50.
 *
 * Response rows are SecurityAuditLog JSON with MCP-specific fields lifted:
 *   latency_ms, tier, is_admin_server, request_id, details (parsed JSON or null).
 *
 * The reusable McpAuditLogPanel component consumes these directly.
 */
import { apiClient } from './client'

export type McpActorType = 'developer' | 'admin' | 'agent' | 'anonymous'
export type McpOutcome = 'success' | 'failure' | 'error' | string
export type McpEventType = 'mcp_tool_invoked' | 'mcp_tool_failed' | 'admin_read_mcp_audit' | string
export type McpTier = '0' | '1' | '2' | '3' | 'admin' | number | string

export interface McpAuditDetails {
  tier?: McpTier
  is_admin_server?: boolean
  args?: Record<string, any>
  result_summary?: any
  correlation_id?: string
  opa?: {
    decision?: 'allow' | 'deny'
    match?: boolean
    latency_ms?: number
  }
  // — admin_read_mcp_audit meta-event extra fields —
  admin_email?: string
  requested_limit?: number
  cursor?: string | null
  // Anything else the writer adds — kept verbatim for the drawer JSON view.
  [k: string]: any
}

export interface McpAuditRow {
  id: string
  timestamp: string  // ISO 8601 + 'Z'
  event_type: McpEventType
  actor_type: McpActorType
  actor_id: string | null
  actor_ip: string | null
  target_type: string | null     // 'mcp_tool' on call rows, 'developer_audit_log' on admin-read meta
  target_id: string | null       // tool name (e.g. 'theprotocol_transferUnits') or developer_id
  outcome: McpOutcome
  severity: 'info' | 'warning' | 'error' | string
  latency_ms: number | null
  tier: McpTier | null
  is_admin_server: boolean | null
  request_id: string | null
  user_agent: string | null
  details: McpAuditDetails | null
  error_message: string | null
  /** V0650 (d), org scope only: the tool answered an error (a refused tool is recorded as outcome success). */
  is_error?: boolean | null
}

export interface McpAuditPage {
  rows: McpAuditRow[]
  next_cursor: string | null
  limit: number
  /** V0650 (d), org scope only: false when this registry records no MCP calls at all. */
  recording?: boolean
  agent_count?: number
}

export interface McpAuditQuery {
  limit?: number
  cursor?: string | null
}

/** V0650 (d): GET /api/v1/organizations/{org_id}/mcp-audit, the MCP calls of an organization's agents (owner or admin).
 *  Rows are an allowlist: the call's arguments, error text, address and user agent are never served. */
export async function getOrgMcpAuditLog(q: McpAuditQuery & { org_id: string }): Promise<McpAuditPage> {
  const params: Record<string, any> = { limit: q.limit ?? 50 }
  if (q.cursor) params.cursor = q.cursor
  const { data } = await apiClient.get(`/organizations/${encodeURIComponent(q.org_id)}/mcp-audit`, { params })
  return data as McpAuditPage
}

/** GET /api/v1/me/mcp-audit-log — caller's own MCP audit history.
 *  Note: apiClient already prepends /api/v1; passing the bare path avoids the
 *  /api/v1/api/v1 double-prefix 404. */
export async function getMyMcpAuditLog(q: McpAuditQuery = {}): Promise<McpAuditPage> {
  const params: Record<string, any> = { limit: q.limit ?? 50 }
  if (q.cursor) params.cursor = q.cursor
  const { data } = await apiClient.get('/me/mcp-audit-log', { params })
  return data as McpAuditPage
}

export interface AdminMcpAuditQuery extends McpAuditQuery {
  actor_id: string  // developer_id (numeric string) or agent DID
}

/**
 * GET /api/v1/admin/mcp-audit-log — admin variant.
 *
 * IMPORTANT: cross-developer reads insert an `admin_read_mcp_audit` row into the
 * TARGET developer's log. The target sees that admin viewed their MCP audit log
 * at /me/mcp-audit-log. This is the self-watching admin pattern shipped in §pass68.
 *
 * Callers should display a warning banner when actor_id !== current_developer.id.
 */
export async function getAdminMcpAuditLog(q: AdminMcpAuditQuery): Promise<McpAuditPage> {
  const params: Record<string, any> = { actor_id: q.actor_id, limit: q.limit ?? 50 }
  if (q.cursor) params.cursor = q.cursor
  // apiClient prepends /api/v1; passing the bare path avoids /api/v1/api/v1 double-prefix.
  const { data } = await apiClient.get('/admin/mcp-audit-log', { params })
  return data as McpAuditPage
}
