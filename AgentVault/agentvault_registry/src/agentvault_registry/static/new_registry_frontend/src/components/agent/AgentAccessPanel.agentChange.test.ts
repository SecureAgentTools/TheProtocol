/**
 * §COCKPITDESK (2026-10-15): the Access panel is reused when the page's agent changes (/agent-profile/A to
 * /agent-profile/B: the router keeps the view). It merged each answer's spend policy into the form, so an agent with no
 * policy kept the previous agent's limits on screen and Save wrote them to it; an answer for the previous agent landing
 * late filled the form Save writes to the new one; and a role expiry typed for A stayed for B.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  authz: { catalog: vi.fn(), get: vi.fn(), denials: vi.fn(), set: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  deleg: { listGrants: vi.fn(), listCapabilities: vi.fn(), createGrant: vi.fn(), revokeGrant: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: h.authz }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: h.deleg }))

import AgentAccessPanel from './AgentAccessPanel.vue'

const A = 'did:theprotocol:agent-a'
const B = 'did:theprotocol:agent-b'
const answer = (roles: string[], spend: Record<string, unknown> | null) => ({ mode: 'enforce', roles, effective_permissions: [],
  role_grants: [], delegate_enabled: false, spend_policy: spend })
const A_SPEND = { max_per_tx: 50, max_per_day: 500, allowed_currencies: null, counterparty_mode: 'any',
  counterparty_allow: null, require_approval_above: null, rate_per_hour: null, geo_allow: null }
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const perTx = (w: ReturnType<typeof mount>) =>
  w.findAll('input.aap-in[type="number"]').find((i) => i.attributes('placeholder') === 'uncapped')!
async function saveBody(w: ReturnType<typeof mount>) {
  h.authz.set.mockResolvedValue(answer(['client'], null))
  await w.find('.aap-actions .aap-btn--primary').trigger('click')
  await flushPromises()
  return h.authz.set.mock.calls[h.authz.set.mock.calls.length - 1]
}

describe("the Access panel shows and saves the agent it shows, never the previous one's", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of [...Object.values(h.authz), ...Object.values(h.deleg)]) f.mockReset()
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader', 'client', 'governor'], mode: 'enforce', all_permissions: [] })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
  })

  it("an agent with no spend policy does not inherit the previous agent's limits, and Save sends none", async () => {
    h.authz.get.mockImplementation(async (did: string) => did === A ? answer(['trader'], A_SPEND) : answer(['client'], null))
    const w = mount(AgentAccessPanel, { props: { agentDid: A, mode: 'owner' }, global: { stubs: { AgentLineageTree: true } } })
    await flushPromises()
    expect((perTx(w).element as HTMLInputElement).value).toBe('50')
    await w.find('input.aap-in[type="datetime-local"]').setValue('2027-01-01T00:00')   // an expiry typed for A
    await w.setProps({ agentDid: B })
    await flushPromises()
    expect((perTx(w).element as HTMLInputElement).value, "B shows no limit of A's").toBe('')
    const [did, body] = await saveBody(w)
    expect(did).toBe(B)
    expect(body.spend_policy.max_per_tx).toBeNull()
    expect(body.spend_policy.max_per_day).toBeNull()
    expect(body.roles).toEqual(['client'])
    expect(body.roles_expires_at, "A's typed expiry is not B's").toBeNull()
    w.unmount()
  })

  it("A's answer landing after the page moved to B is dropped; Save sends B's", async () => {
    const slowA = deferred<unknown>()
    h.authz.get.mockImplementation((did: string) => did === A ? slowA.promise : Promise.resolve(answer(['client'], null)))
    const w = mount(AgentAccessPanel, { props: { agentDid: A, mode: 'owner' }, global: { stubs: { AgentLineageTree: true } } })
    await w.setProps({ agentDid: B })
    await flushPromises()
    slowA.resolve(answer(['trader', 'governor'], A_SPEND))
    await flushPromises()
    expect(w.findAll('.aap-role-opt--on').map((b) => b.text())).toEqual(['client'])
    expect((perTx(w).element as HTMLInputElement).value).toBe('')
    const [did, body] = await saveBody(w)
    expect(did).toBe(B)
    expect(body.roles).toEqual(['client'])
    expect(body.spend_policy.max_per_tx).toBeNull()
    w.unmount()
  })
})
