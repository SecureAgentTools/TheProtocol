/**
 * §FESUITE (V0577): the agent's Access panel turned three failed reads into answers: the denials feed into its all-clear
 * ("No denials recorded. … operating inside its authority"), the delegation grants into "No delegation grants.", and
 * the capability tokens into "No capability tokens." with the delegation mode "off". Each now says its read failed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  authz: { catalog: vi.fn(), get: vi.fn(), denials: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  deleg: { listGrants: vi.fn(), listCapabilities: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: h.authz }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: h.deleg }))

import AgentAccessPanel from './AgentAccessPanel.vue'

const fail = () => Promise.reject(new Error('Request failed with status code 502'))

async function panel() {
  const w = mount(AgentAccessPanel, {
    props: { agentDid: 'did:theprotocol:a1', mode: 'owner' },
    global: { stubs: { AgentLineageTree: true } },
  })
  await flushPromises()
  return w
}

describe("the agent Access panel over reads that failed", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.authz.catalog.mockResolvedValue({ assignable_roles: [], mode: 'enforce', all_permissions: [] })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: [], effective_permissions: [], role_grants: [], delegate_enabled: false })
  })

  it('says the denials, grants and tokens could not be read; the mode is not "off"', async () => {
    h.authz.denials.mockImplementation(fail)
    h.deleg.listGrants.mockImplementation(fail)
    h.deleg.listCapabilities.mockImplementation(fail)
    const w = await panel()
    expect(w.find('[data-testid="aap-denials-failed"]').exists(), 'the denials say their read failed').toBe(true)
    expect(w.text()).not.toContain('No denials recorded')
    expect(w.find('[data-testid="aap-grants-failed"]').exists()).toBe(true)
    expect(w.text()).not.toContain('No delegation grants.')
    expect(w.find('[data-testid="aap-caps-failed"]').exists()).toBe(true)
    expect(w.text()).not.toContain('No capability permits.')
    expect(w.text()).not.toContain('(L3/L4 · off)')
  })

  it('reads that answered draw their answers', async () => {
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
    const w = await panel()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text()).toContain('No denials recorded')
    expect(w.text()).toContain('No delegation grants.')
    expect(w.text()).toContain('(L3/L4 · enforce)')
  })
})
