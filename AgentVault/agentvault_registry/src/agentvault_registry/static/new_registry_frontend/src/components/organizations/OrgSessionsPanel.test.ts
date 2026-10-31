import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0650 (d): the SESSIONS tab. It reads only once open, draws each agent's live status line (or says there is none),
 * shows a failed read as a failed read, opens the existing room or points to the ROOM tab (never creates one), and
 * lists the agents' MCP calls through the shared panel in its org scope. BASE (V0649): the component does not exist.
 */
const h = vi.hoisted(() => ({
  presence: vi.fn(), rooms: vi.fn(), openOrgRoom: vi.fn(), calls: vi.fn(), push: vi.fn(),
}))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: h.presence } }))
vi.mock('@/services/api/chat', () => ({ chatApi: { orgRooms: h.rooms, openOrgRoom: h.openOrgRoom } }))
vi.mock('@/services/api/mcpAuditLog', () => ({
  getOrgMcpAuditLog: h.calls, getMyMcpAuditLog: vi.fn(), getAdminMcpAuditLog: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 } }) }))
vi.mock('@/stores/organizations', () => ({
  useOrganizationStore: () => ({ members: [{ developer_id: 6, developer_name: 'Commander' }] }),
}))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/ourchat') }) }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

import OrgSessionsPanel from './OrgSessionsPanel.vue'

const PRESENCE = {
  organization_id: 'org-s', as_of: '2026-10-31T05:00:00Z', count: 2, agents: [
    { did: 'did:x:a1', name: 'session-release', owner_developer_id: 6, last_active_at: '2026-10-31T04:59:00Z',
      account_status: 'active', status: { text: 'role=session-release host=srv1', set_at: null,
        expires_at: '2026-10-31T05:05:00Z', expires_in_seconds: 300 } },
    { did: 'did:x:a2', name: null, owner_developer_id: 7, last_active_at: null, account_status: 'active', status: null },
  ],
}
const CALLS = { rows: [{ id: 'r1', timestamp: '2026-10-31T04:58:00Z', event_type: 'mcp_tool_invoked', actor_type: 'agent',
  actor_id: 'did:x:a1', target_id: 'theprotocol_getMyBalance', tier: '2', outcome: 'success', severity: 'info',
  latency_ms: 12, is_admin_server: false, is_error: false, actor_ip: null, user_agent: null, request_id: null,
  details: null, error_message: null, target_type: null }], next_cursor: null, limit: 25, recording: true, agent_count: 2 }

const opts = { global: { stubs: { Icon: true } } }

describe('the SESSIONS tab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h)) f.mockReset()
    h.presence.mockResolvedValue(PRESENCE)
    h.rooms.mockResolvedValue({ rooms: [{ org_id: 'org-s', conversation_id: 'room-1' }], enableable: [] })
    h.calls.mockResolvedValue(CALLS)
    try { localStorage.clear() } catch { /* no storage */ }
  })

  it('reads nothing while closed, and each read once when opened', async () => {
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: false } })
    await flushPromises()
    expect(h.presence).not.toHaveBeenCalled()
    expect(h.rooms).not.toHaveBeenCalled()
    await w.setProps({ active: true })
    await flushPromises()
    expect(h.presence).toHaveBeenCalledTimes(1)
    expect(h.rooms).toHaveBeenCalledTimes(1)
    expect(h.calls).toHaveBeenCalledWith(expect.objectContaining({ org_id: 'org-s', cursor: null, limit: 25 }))
  })

  it('draws each agent with its live line, or says it has none, with its activity and owner', async () => {
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: true } })
    await flushPromises()
    const a1 = w.find('[data-testid="osp-agent-did:x:a1"]').text()
    expect(a1).toContain('session-release')
    expect(a1).toContain('role=session-release host=srv1')
    expect(a1).toContain('Commander')
    const a2 = w.find('[data-testid="osp-agent-did:x:a2"]').text()
    expect(a2).toContain('no live status')
    expect(a2).toContain('never active')
    expect(a2).toContain('owner #7')
  })

  it('a failed presence read is said as one, never as "no agents", and can be tried again', async () => {
    h.presence.mockRejectedValueOnce(new Error('HTTP 503'))
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: true } })
    await flushPromises()
    expect(w.find('[data-testid="osp-presence-failed"]').exists()).toBe(true)
    expect(w.find('[data-testid="osp-no-agents"]').exists()).toBe(false)
    await w.find('[data-testid="osp-presence-failed"] button').trigger('click')
    await flushPromises()
    expect(h.presence).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="osp-agent-did:x:a1"]').exists()).toBe(true)
  })

  it('opens the existing room and never creates one', async () => {
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: true } })
    await flushPromises()
    await w.find('[data-testid="osp-room-open"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith('/ourchat/room-1')
    expect(h.openOrgRoom).not.toHaveBeenCalled()
  })

  it('without a room it says so and points to the ROOM tab', async () => {
    h.rooms.mockResolvedValue({ rooms: [], enableable: [{ org_id: 'org-s' }] })
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: true } })
    await flushPromises()
    expect(w.find('[data-testid="osp-room-none"]').exists()).toBe(true)
    await w.find('[data-testid="osp-room-tab"]').trigger('click')
    expect(w.emitted('go')?.[0]).toEqual(['room'])
    expect(h.openOrgRoom).not.toHaveBeenCalled()
  })

  it('names the calling agent by its card name in the calls list', async () => {
    const w = mount(OrgSessionsPanel, { ...opts, props: { orgId: 'org-s', active: true } })
    await flushPromises()
    const row = w.find('.mcp-row').text()
    expect(row).toContain('session-release')
    expect(row).toContain('theprotocol_getMyBalance')
    expect(row).toContain('T2')
  })
})
