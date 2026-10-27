/**
 * §FESUITE (2026-10-10, the operator batch) — a cloud operator provisions no operators: its server answers the
 * provisioning rails 503 ("This feature runs on sovereign mainframes only"). Measured on both sandbox operators: the
 * Operator Portal's Account tab asked me/provisioning-eligibility and operators/my-status on every visit and showed
 * them as failed reads. On an operator it now asks nothing and says where an operator is applied for: its frame.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  cfg: {} as Record<string, unknown>,
  frame: null as null | Record<string, unknown>,
  get: vi.fn(),
  elig: vi.fn(),
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))
vi.mock('@/services/api/provisioning', () => ({ getMyProvisioningEligibility: h.elig, selfProvisionCloudOperator: vi.fn() }))
// real computeds, as the composables give (a template unwraps refs only); each mount reads this test's values
vi.mock('@/composables/useRegistryConfig', async () => {
  const { computed } = await import('vue')
  return { registryConfigWithin: async () => h.cfg, useRegistryConfig: () => ({ config: computed(() => h.cfg) }) }
})
vi.mock('@/composables/useFrameManifest', async () => {
  const { computed } = await import('vue')
  return { useFrameManifest: () => ({ ownFrame: computed(() => h.frame) }) }
})

import OPAccountTab from './OPAccountTab.vue'

const stubs = { 'router-link': { template: '<a><slot /></a>' }, RouterLink: { template: '<a><slot /></a>' }, OPProvisionAdvancedFields: true, LocalCommand: true }

describe('the Account tab on a cloud operator', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.get.mockReset().mockResolvedValue({ data: { application: null, cloud_ops: [] } })
    h.elig.mockReset().mockResolvedValue({ is_unlocked: false, months_total_purchased: 0 })
  })

  it('asks no frame-only rail, and points to the frame where operators are applied for', async () => {
    h.cfg = { is_federated_operator: true }
    h.frame = { key: 'sandbox-alpha', name: 'Sandbox Alpha', display_name: 'Sandbox Alpha', role: 'frame', console_url: 'https://sandbox-a.theprotocol.cloud/' }
    const w = mount(OPAccountTab, { global: { stubs } })
    await flushPromises()
    expect(h.elig).not.toHaveBeenCalled()
    expect(h.get).not.toHaveBeenCalled()
    expect(w.find('[data-testid="op-on-operator"]').text()).toContain('cloud operator of Sandbox Alpha')
    expect(w.find('[data-testid="op-on-operator-frame"]').attributes('href')).toBe('https://sandbox-a.theprotocol.cloud/#/operator?tab=cloud')
    expect(w.find('[data-testid="op-elig-failed"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Free for testing')
  })

  it('on a frame it asks as before', async () => {
    h.cfg = { is_federated_operator: false }
    h.frame = null
    const w = mount(OPAccountTab, { global: { stubs } })
    await flushPromises()
    expect(h.elig).toHaveBeenCalled()
    expect(h.get).toHaveBeenCalledWith('/operators/my-status')
    expect(w.find('[data-testid="op-on-operator"]').exists()).toBe(false)
  })
})
