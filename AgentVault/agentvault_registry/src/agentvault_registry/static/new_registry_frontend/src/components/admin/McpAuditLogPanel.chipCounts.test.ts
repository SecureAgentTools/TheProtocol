import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the MCP call log's outcome chips counted the rows a read returned, and
 * before one answered, or when it failed with nothing shown, they said "All 0 · Success 0 · Failure 0 · Error 0" beside
 * the error: a count of rows nobody had read. They count once a read answered (an answered empty log still says 0).
 */
const h = vi.hoisted(() => ({ mine: vi.fn() }))
vi.mock('@/services/api/mcpAuditLog', () => ({ getMyMcpAuditLog: h.mine, getAdminMcpAuditLog: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { developer_id: 7 } }) }))

import McpAuditLogPanel from './McpAuditLogPanel.vue'

const opts = { props: { scope: 'me' as const, pollIntervalMs: 0, storageKey: 'test-chips' }, global: { stubs: { Icon: true } } }
const counts = (w: ReturnType<typeof mount>) => w.findAll('.mcp-chip-count').map((c) => c.text())

describe('the call log counts only rows it read', () => {
  beforeEach(() => { h.mine.mockReset() })

  it('a failed first read: no chip counts beside the error', async () => {
    h.mine.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(McpAuditLogPanel, opts)
    await flushPromises()
    expect(w.find('.mcp-status-pill--error').exists(), 'the error is said').toBe(true)
    expect(counts(w)).toEqual([])
    w.unmount()
  })

  it('an answered empty log counts 0, and rows are counted by outcome', async () => {
    h.mine.mockResolvedValueOnce({ rows: [], next_cursor: null, limit: 50 })
    const w = mount(McpAuditLogPanel, opts)
    await flushPromises()
    expect(counts(w)).toEqual(['0', '0', '0', '0'])
    w.unmount()
    h.mine.mockResolvedValueOnce({ rows: [
      { id: 1, outcome: 'success', event_type: 'mcp_tool_call', timestamp: new Date().toISOString() },
      { id: 2, outcome: 'error', event_type: 'mcp_tool_call', timestamp: new Date().toISOString() },
    ], next_cursor: null, limit: 50 })
    const w2 = mount(McpAuditLogPanel, opts)
    await flushPromises()
    expect(counts(w2)).toEqual(['2', '1', '0', '1'])
    w2.unmount()
  })
})
