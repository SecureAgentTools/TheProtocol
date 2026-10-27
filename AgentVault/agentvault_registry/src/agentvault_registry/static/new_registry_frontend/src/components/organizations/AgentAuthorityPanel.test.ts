/**
 * §FESUITE (V0577): the org's Agent Authority panel turned a failed grants read into {} and drew every agent as "no org
 * authority granted", with a Grant button over grants that may exist. It now says the read failed, and Try again reads it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  org: { getOrgAuthzCatalog: vi.fn(), getOrgAuthorityGrants: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/organizationService', () => ({ organizationService: h.org }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: {} }))

import AgentAuthorityPanel from './AgentAuthorityPanel.vue'

const agents = [{ did: 'did:theprotocol:a1', name: 'Ledger clerk' }]

describe('the Agent Authority panel over a grants read that failed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.org.getOrgAuthzCatalog.mockResolvedValue({ roles: [], never_included: [] })
  })

  it('says the read failed (no "no org authority granted"), and Try again reads the grants', async () => {
    h.org.getOrgAuthorityGrants.mockRejectedValue(new Error('Failed to load org authority grants'))
    const w = mount(AgentAuthorityPanel, { props: { orgId: 'org-1', orgSlug: 'acme', agents, canEdit: true } })
    await flushPromises()
    expect(w.find('[data-read-failed]').exists(), 'the panel says its read failed').toBe(true)
    expect(w.text()).not.toContain('no org authority granted')

    h.org.getOrgAuthorityGrants.mockResolvedValue({ org_id: 'org-1', org_slug: 'acme', grants: [
      { grant_id: 1, agent_did: 'did:theprotocol:a1', agent_name: 'Ledger clerk', permissions: ['spend.small'], expires_at: null, granted_by_dev_id: 1, org_linked: true },
    ] })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text(), 'the grant that was read is drawn').toContain('spend.small')
  })
})
