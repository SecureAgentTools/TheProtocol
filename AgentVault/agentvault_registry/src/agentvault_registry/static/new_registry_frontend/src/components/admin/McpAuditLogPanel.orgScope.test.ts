import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0650 (d): the shared MCP audit panel's org scope. It reads the organization's route (never the caller's own log),
 * says when the registry records nothing, marks a call the tool answered with an error, names the agent, and hides
 * the server filter (agents never use the admin server). BASE (V0649): the panel has no org scope; it reads the
 * caller's own log instead.
 */
const h = vi.hoisted(() => ({ org: vi.fn(), me: vi.fn(), admin: vi.fn() }))
vi.mock('@/services/api/mcpAuditLog', () => ({
  getOrgMcpAuditLog: h.org, getMyMcpAuditLog: h.me, getAdminMcpAuditLog: h.admin,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 't', user: { developer_id: 6 } }) }))

import McpAuditLogPanel from './McpAuditLogPanel.vue'

const row = (over: Record<string, unknown> = {}) => ({
  id: 'r1', timestamp: '2026-10-31T04:58:00Z', event_type: 'mcp_tool_invoked', actor_type: 'agent',
  actor_id: 'did:x:a1', target_id: 'theprotocol_transferUnits', tier: '2', outcome: 'success', severity: 'info',
  latency_ms: 30, is_admin_server: false, is_error: true, actor_ip: null, user_agent: null, request_id: null,
  details: null, error_message: null, target_type: null, ...over,
})

describe('the MCP audit panel in its org scope', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.org.mockReset(); h.me.mockReset(); h.admin.mockReset()
    try { localStorage.clear() } catch { /* no storage */ }
  })

  it('reads the organization route, marks a tool error and names the agent', async () => {
    h.org.mockResolvedValue({ rows: [row()], next_cursor: null, limit: 25, recording: true, agent_count: 1 })
    const w = mount(McpAuditLogPanel, {
      props: { scope: 'org', orgId: 'org-s', actorNames: { 'did:x:a1': 'session-release' }, pageSize: 25, pollIntervalMs: 0 },
      global: { stubs: { Icon: true } },
    })
    await flushPromises()
    expect(h.org).toHaveBeenCalledWith({ org_id: 'org-s', cursor: null, limit: 25 })
    expect(h.me).not.toHaveBeenCalled()
    expect(w.find('[data-testid="mcp-tool-error"]').exists()).toBe(true)
    expect(w.find('.mcp-actor-id').text()).toBe('session-release')
    expect(w.text()).not.toContain('SERVER')
  })

  it('says when this registry records no MCP calls, and gives an org sentence when there are none', async () => {
    h.org.mockResolvedValue({ rows: [], next_cursor: null, limit: 25, recording: false, agent_count: 3 })
    const w = mount(McpAuditLogPanel, {
      props: { scope: 'org', orgId: 'org-s', pollIntervalMs: 0 }, global: { stubs: { Icon: true } },
    })
    await flushPromises()
    expect(w.find('[data-testid="mcp-org-not-recording"]').exists()).toBe(true)
    expect(w.find('[data-testid="mcp-org-empty"]').exists()).toBe(true)
  })

  it('the caller-scoped panel is unchanged', async () => {
    // control: passes on both trees
    h.me.mockResolvedValue({ rows: [row({ is_error: undefined })], next_cursor: null, limit: 50 })
    const w = mount(McpAuditLogPanel, { props: { scope: 'me', pollIntervalMs: 0 }, global: { stubs: { Icon: true } } })
    await flushPromises()
    expect(h.me).toHaveBeenCalled()
    expect(h.org).not.toHaveBeenCalled()
    expect(w.text()).toContain('SERVER')
  })
})
