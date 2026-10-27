/**
 * §FESUITE (V0577): the Operator Portal's tabs turned failed reads into answers:
 *  - Account: a failed eligibility read said "Free for testing … Apply" and hid the provisioning form from an operator
 *    whose provisioning is granted; a failed status read said "You haven't provisioned a cloud operator yet.";
 *  - Health: a failed lifecycle read said "No operator application linked to this account";
 *  - Federation: a failed peers read said "No peers federated yet.".
 * Each now says its read failed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  get: vi.fn(),
  prov: { getMyProvisioningEligibility: vi.fn(), selfProvisionCloudOperator: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  op: {
    getMyLifecycle: vi.fn(), getFederationPeers: vi.fn(), getFederationSyncStatus: vi.fn(),
    getPolicyCompliance: vi.fn(), triggerFederationSync: vi.fn(),
  } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))
vi.mock('@/services/api/provisioning', () => h.prov)
vi.mock('@/services/api/operator', () => h.op)
// §FESUITE (the operator batch): the Account tab reads the registry's config first (a cloud operator asks nothing there);
// these tabs run on a frame, whose config says nothing of the kind
vi.mock('@/composables/useRegistryConfig', () => ({
  registryConfigWithin: async () => ({}),
  useRegistryConfig: () => ({ config: { value: {} } }),
}))
vi.mock('@/composables/useFrameManifest', () => ({ useFrameManifest: () => ({ ownFrame: { value: null } }) }))

import OPAccountTab from './OPAccountTab.vue'
import OPHealthTab from './OPHealthTab.vue'
import OPFederationTab from './OPFederationTab.vue'

const failed = () => Promise.reject(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
const stubs = { 'router-link': { template: '<a><slot /></a>' }, RouterLink: { template: '<a><slot /></a>' }, OPProvisionAdvancedFields: true, LocalCommand: true }

describe("the Operator Portal's tabs over reads that failed", () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('Account: no "Free for testing" over a failed eligibility read, no "none provisioned" over a failed status read', async () => {
    h.prov.getMyProvisioningEligibility.mockImplementation(failed)
    h.get.mockImplementation(failed)
    const w = mount(OPAccountTab, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="op-elig-failed"]').exists(), 'the eligibility says its read failed').toBe(true)
    expect(w.text()).not.toContain('Free for testing')
    expect(w.find('[data-testid="op-ops-failed"]').exists(), 'the operator list says its read failed').toBe(true)
    expect(w.text()).not.toContain("You haven't provisioned a cloud operator yet")
  })

  it('Account: a 404 from the status read is still "none provisioned" (the server\'s answer)', async () => {
    h.prov.getMyProvisioningEligibility.mockResolvedValue({ is_unlocked: false, months_total_purchased: 0 })
    h.get.mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } }))
    const w = mount(OPAccountTab, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text()).toContain("You haven't provisioned a cloud operator yet")
  })

  it('Health: a failed lifecycle read is not "No operator application linked"', async () => {
    h.op.getMyLifecycle.mockImplementation(failed)
    const w = mount(OPHealthTab, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('could not be read')
    expect(w.text()).not.toContain('No operator application linked to this account')
  })

  it('Federation: a failed peers read is not "No peers federated yet."', async () => {
    h.op.getFederationPeers.mockImplementation(failed)
    h.op.getFederationSyncStatus.mockImplementation(failed)
    h.op.getPolicyCompliance.mockImplementation(failed)
    const w = mount(OPFederationTab, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="op-peers-failed"]').exists(), 'the peers say their read failed').toBe(true)
    expect(w.text()).not.toContain('No peers federated yet.')
  })
})
