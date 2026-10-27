/**
 * §FESUITE (2026-10-10, the operator batch) — the Federation Test page reads the sandbox through /sandbox/a. On every
 * cloud operator the proxy dialed registry-test (a tier torn down at §BATCH3) and answered 502, which the console
 * counted as a broken sandbox; then the page put this registry's own production health in its place, and its sync
 * button would fall back to this registry's own federation sync. Where the registry says its proxy reaches no sandbox
 * registry A (registry-config `sandbox_proxy`), the page asks nothing there, starts no poll, and says so.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ cfg: {} as Record<string, unknown>, get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post } }))
vi.mock('@/composables/useRegistryConfig', () => ({ registryConfigWithin: async () => h.cfg }))

import FederationTestDashboard from './FederationTestDashboard.vue'

describe('the Federation Test page without a sandbox', () => {
  beforeEach(() => {
    h.get.mockReset().mockResolvedValue({ data: { services: [{ name: 'sandbox-op', group: 'operator', status: 'healthy', ms: 4 }] } })
    h.post.mockReset().mockResolvedValue({ data: {} })
  })

  it('no sandbox registry A here: nothing asked, no stand-in, the sync closed, and it says so', async () => {
    h.cfg = { sandbox_proxy: [] }
    const w = mount(FederationTestDashboard, { global: { stubs: { Icon: true } } })
    await flushPromises()
    expect(h.get).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ft-no-sandbox"]').exists()).toBe(true)
    const sync = w.findAll('button').find((b) => b.classes().includes('ft-btn-sync'))!
    expect(sync.attributes('disabled')).toBeDefined()
    await sync.trigger('click')
    await flushPromises()
    expect(h.post).not.toHaveBeenCalled()
    w.unmount()
  })

  it('with a sandbox (or an older registry that says nothing): asked as before', async () => {
    for (const cfg of [{ sandbox_proxy: ['a', 'b'] }, {}]) {
      h.cfg = cfg
      h.get.mockClear()
      const w = mount(FederationTestDashboard, { global: { stubs: { Icon: true } } })
      await flushPromises()
      expect(h.get).toHaveBeenCalledWith('/sandbox/a/api/v1/stack-health')
      expect(w.find('[data-testid="ft-no-sandbox"]').exists()).toBe(false)
      w.unmount()
    }
  })
})
