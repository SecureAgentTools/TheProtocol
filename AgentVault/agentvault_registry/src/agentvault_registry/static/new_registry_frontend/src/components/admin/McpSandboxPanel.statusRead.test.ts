import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the MCP tester's Sandbox panel turned EVERY failed status read into "this
 * frame has no runner" and hid itself, so a 502 on a production frame took away the place its sandbox is stood up, with
 * nothing on screen saying why. Only a refusal (401/403) or a registry without the route (404) hides it now; no answer
 * or the registry's own failure says the read failed, with Try again, and a retry that answers shows the panel.
 */
const h = vi.hoisted(() => ({ status: vi.fn() }))
vi.mock('@/services/api/mcpTesterSandbox', () => ({
  mcpTesterSandboxApi: { status: h.status, events: vi.fn(), provision: vi.fn(), teardown: vi.fn(), reveal: vi.fn() },
}))

import McpSandboxPanel from './McpSandboxPanel.vue'

const opts = { global: { stubs: { Icon: true } } }
const failed = (status?: number) => Object.assign(new Error(status ? `Request failed with status code ${status}` : 'Network Error'),
  status ? { response: { status, data: { detail: 'x' } } } : {})
const lastRole = (w: ReturnType<typeof mount>) => { const r = w.emitted('role'); return r ? r[r.length - 1] : undefined }
const PARENT = { available: true, frame: 'eu', sandboxes: [], job: null, topologies: [],
  host: { problems: [], mem_available_gib: 40, busy: null } }

describe('the Sandbox panel says a failed status read failed', () => {
  beforeEach(() => { h.status.mockReset() })

  for (const [what, err] of [['a 502', failed(502)], ['no answer', failed()]] as const) {
    it(`${what}: the panel stays, says the read failed, and Try again reads it`, async () => {
      h.status.mockRejectedValueOnce(err).mockResolvedValueOnce(PARENT)
      const w = mount(McpSandboxPanel, opts)
      await flushPromises()
      expect(w.find('[data-testid="mcp-sandbox"]').exists(), 'the panel is shown').toBe(true)
      expect(w.find('[data-read-failed]').exists(), 'it says the read failed').toBe(true)
      expect(w.emitted('role'), 'no role is claimed from a failed read').toBeUndefined()
      await w.find('[data-testid="read-failed-retry"]').trigger('click')
      await flushPromises()
      expect(w.find('[data-read-failed]').exists()).toBe(false)
      expect(lastRole(w)).toEqual(['parent'])
      w.unmount()
    })
  }

  for (const code of [401, 403, 404]) {
    it(`a ${code} still means no sandbox here: the panel stays hidden`, async () => {
      h.status.mockRejectedValueOnce(failed(code))
      const w = mount(McpSandboxPanel, opts)
      await flushPromises()
      expect(w.find('[data-testid="mcp-sandbox"]').exists()).toBe(false)
      expect(lastRole(w)).toEqual(['none'])
      w.unmount()
    })
  }
})
