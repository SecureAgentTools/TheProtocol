/**
 * §FESUITE V0595 (his word 2026-10-11 "also close console gaps"): cross-registry delegation in the agent's Access panel.
 * The rail (POST/GET/DELETE /agents/delegate-cross-registry) acted AS the agent and had no console surface at all: API and
 * MCP only. It acts as THIS agent (its token), so it waits for the agent switcher; it lists what this agent delegated,
 * issues, says whether the other registry took it (signed here is not delivered there), and revokes at their registry.
 * A registry that runs the rail off says so, never "nothing delegated".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  authz: { catalog: vi.fn(), get: vi.fn(), denials: vi.fn(), set: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  deleg: { listGrants: vi.fn(), listCapabilities: vi.fn(), listXreg: vi.fn(), issueXreg: vi.fn(), revokeXreg: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: h.authz }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: h.deleg }))

import AgentAccessPanel from './AgentAccessPanel.vue'
import { useAuthStore } from '@/stores/auth'

const DID = 'did:theprotocol:a1'
const ROW = {
  credential_id: 'c1', delegate_did: 'did:theprotocol:farfaraway0000beef', delegate_registry: 'https://sandbox-a.theprotocol.cloud',
  permissions: ['transfer.local'], caveats: {}, expires_at: '2026-10-12T08:00:00+00:00', issued_at: '2026-10-11T08:00:00+00:00',
  delivered: true, revoked_at: null, revoke_delivered: null, state: 'active',
}

async function panel(active: boolean) {
  const auth = useAuthStore() as any
  if (active) { auth.activeAgent = { did: DID }; auth.agentToken = 'agent-token' }
  const w = mount(AgentAccessPanel, { props: { agentDid: DID, mode: 'owner' }, global: { stubs: { AgentLineageTree: true } } })
  await flushPromises()
  return w
}

describe('cross-registry delegation on the Access panel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h.deleg)) f.mockReset()
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader'], mode: 'enforce', all_permissions: ['transfer.local'] })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: ['transfer.local'], role_grants: [],
      delegate_enabled: true, spend_policy: null })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
  })

  it('waits for this agent to be selected: it acts as the agent', async () => {
    const w = await panel(false)
    expect(w.find('[data-testid="aap-xreg-needs-agent"]').exists()).toBe(true)
    expect(h.deleg.listXreg).not.toHaveBeenCalled()
  })

  it('lists what this agent delegated, issues, and says whether their registry took it', async () => {
    h.deleg.listXreg.mockResolvedValueOnce({ issuer_did: DID, delegations: [ROW] }).mockResolvedValue({ issuer_did: DID, delegations: [ROW] })
    h.deleg.issueXreg.mockResolvedValueOnce({ ok: false, credential_id: 'c2', expires_at: '', peer_response: { status: 401 } })
    const w = await panel(true)
    expect(w.find('[data-testid="aap-xreg-state-c1"]').text()).toBe('active')
    await w.find('[data-testid="aap-xreg-did"]').setValue('did:theprotocol:remote1')
    await w.find('[data-testid="aap-xreg-registry"]').setValue('https://sandbox-a.theprotocol.cloud')
    await w.find('[data-testid="aap-xreg"] .aap-permopt').trigger('click')
    await w.find('[data-testid="aap-xreg-issue"]').trigger('click')
    await flushPromises()
    expect(h.deleg.issueXreg).toHaveBeenCalledWith(expect.objectContaining({
      delegate_did: 'did:theprotocol:remote1', delegate_registry_url: 'https://sandbox-a.theprotocol.cloud', permissions: ['transfer.local'], ttl_hours: 24 }))
    expect(w.find('[data-testid="aap-xreg-note"]').text(), 'a credential their registry did not take is not "delegated"')
      .toMatch(/did not take it/)
  })

  it('a registry that runs the rail off says so, and offers no form', async () => {
    h.deleg.listXreg.mockRejectedValue(Object.assign(new Error('Request failed with status code 403'),
      { response: { status: 403, data: { detail: 'Cross-registry delegation is disabled (AGENT_XREG_DELEGATION_ENABLED)' } } }))
    const w = await panel(true)
    expect(w.find('[data-testid="aap-xreg-off"]').exists()).toBe(true)
    expect(w.find('[data-testid="aap-xreg-none"]').exists(), 'said "nothing delegated" for a rail that is off').toBe(false)
    expect(w.find('[data-testid="aap-xreg-issue"]').exists()).toBe(false)
  })

  it('revokes at their registry', async () => {
    h.deleg.listXreg.mockResolvedValue({ issuer_did: DID, delegations: [ROW] })
    h.deleg.revokeXreg.mockResolvedValueOnce({ ok: true, peer_status: 200 })
    const w = await panel(true)
    await w.find('[data-testid="aap-xreg-row-c1"] .aap-row-x').trigger('click')
    await flushPromises()
    expect(h.deleg.revokeXreg).toHaveBeenCalledWith('c1', 'https://sandbox-a.theprotocol.cloud')
    expect(w.find('[data-testid="aap-xreg-note"]').text()).toMatch(/Revoked at their registry/)
  })

  // D6-272 (2026-10-17): a revoke is recorded here whatever their registry answered, and its message is sent again
  it('a revoke their registry has not taken yet is said as revoked here, sent again', async () => {
    h.deleg.listXreg.mockResolvedValue({ issuer_did: DID, delegations: [ROW] })
    h.deleg.revokeXreg.mockResolvedValueOnce({ ok: false, peer_status: null,
      delivery: { state: 'retrying', attempts: 1, next_attempt_at: '2026-10-17T10:01:00+00:00', last_status: null, last_error: 'ConnectError' } })
    const w = await panel(true)
    await w.find('[data-testid="aap-xreg-row-c1"] .aap-row-x').trigger('click')
    await flushPromises()
    const note = w.find('[data-testid="aap-xreg-note"]').text()
    expect(note).toMatch(/Revoked here/)
    expect(note, 'the old note said it may still be honoured until it expires').not.toMatch(/until it expires/)
  })

  it("a revoked row says how its message stands, and offers to send it again only once it is no longer sent", async () => {
    const delivery = (state: string) => ({ state, attempts: 3, next_attempt_at: null, last_status: 503, last_error: 'HTTP 503' })
    h.deleg.listXreg.mockResolvedValue({ issuer_did: DID, delegations: [
      { ...ROW, credential_id: 'r1', state: 'revoked', revoked_at: '2026-10-17T09:00:00+00:00', revoke_delivered: false,
        revoke_delivery: delivery('retrying') },
      { ...ROW, credential_id: 'r2', state: 'revoked', revoked_at: '2026-10-17T09:00:00+00:00', revoke_delivered: false,
        revoke_delivery: delivery('given_up') },
      { ...ROW, credential_id: 'r3', state: 'revoked', revoked_at: '2026-10-17T09:00:00+00:00', revoke_delivered: true,
        revoke_delivery: delivery('delivered') },
    ] })
    h.deleg.revokeXreg.mockResolvedValueOnce({ ok: true, peer_status: 200, delivery: delivery('delivered') })
    const w = await panel(true)
    expect(w.find('[data-testid="aap-xreg-state-r1"]').text()).toBe('revoked')
    expect(w.find('[data-testid="aap-xreg-delivery-r1"]').text()).toMatch(/sent again/)
    expect(w.find('[data-testid="aap-xreg-resend-r1"]').exists(), 'still being sent: nothing to press').toBe(false)
    expect(w.find('[data-testid="aap-xreg-delivery-r2"]').text()).toMatch(/no longer sent/)
    expect(w.find('[data-testid="aap-xreg-delivery-r3"]').exists(), 'a delivered revoke needs no note').toBe(false)
    await w.find('[data-testid="aap-xreg-resend-r2"]').trigger('click')
    await flushPromises()
    expect(h.deleg.revokeXreg).toHaveBeenCalledWith('r2', 'https://sandbox-a.theprotocol.cloud')
  })
})
