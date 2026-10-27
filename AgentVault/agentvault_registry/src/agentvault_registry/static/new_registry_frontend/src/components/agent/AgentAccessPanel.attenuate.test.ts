/**
 * SEC-11 (2026-10-17): the Access panel's attenuate form can derive a child of a token bounded on any axis.
 *
 * The registry refuses a child that is looser than its parent on any axis, and one that drops a bound the parent sets.
 * The form had no field for the phone caveats or the uses bound, and started every field blank, so a token bounded on
 * one of them (a phone token, a token with uses) could not be attenuated here at all: each try was refused, naming the
 * axis. The token list carries each token's caveats and uses bound now; the form starts from them (equal is within),
 * offers the phone and uses fields, keeps the limits it has no field for, and leaves a blank budget to the registry
 * (which gives the child what the parent has left). A token that forbids re-delegation offers no attenuate.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  authz: { catalog: vi.fn(), get: vi.fn(), denials: vi.fn(), set: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  deleg: { listGrants: vi.fn(), listCapabilities: vi.fn(), attenuate: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: h.authz }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: h.deleg }))

import AgentAccessPanel from './AgentAccessPanel.vue'
import { useAuthStore } from '@/stores/auth'

const DID = 'did:theprotocol:a1'
const TOKEN = { role: 'holder', issuer_did: 'did:theprotocol:boss', holder_did: DID, parent_token_id: null, depth: 0,
  status: 'active', expires_at: '2026-10-18T00:00:00+00:00' }
const PHONE = { ...TOKEN, id: 7, permissions: ['phone.use'], budget_remaining: 60, currency: 'ECU', max_uses: 5, uses_left: 3,
  caveats: { permissions: ['phone.use'], phone_allowed_apps: ['com.vault.bank'], phone_allowed_domains: ['bank.example'],
    phone_max_actions: 5, phone_ttl_seconds: 120, phone_no_screenshot: true, phone_no_network: true,
    counterparty_allow: ['did:theprotocol:shop'] } }
const PLAIN = { ...TOKEN, id: 8, permissions: ['teg.transfer'], budget_remaining: null, currency: null, max_uses: null,
  uses_left: null, caveats: { permissions: ['teg.transfer'] } }
const SEALED = { ...TOKEN, id: 9, permissions: ['teg.transfer'], budget_remaining: null, currency: null, max_uses: null,
  uses_left: null, caveats: { permissions: ['teg.transfer'], no_redelegate: true } }

async function panel() {
  const auth = useAuthStore() as any
  auth.activeAgent = { did: DID }; auth.agentToken = 'agent-token'   // attenuating acts as this agent
  const w = mount(AgentAccessPanel, { props: { agentDid: DID, mode: 'owner' }, global: { stubs: { AgentLineageTree: true } } })
  await flushPromises()
  return w
}
// selectors both the old and the new form have: the row's own button and the form's Derive button, by their words
const row = (w: any, id: number) => w.findAll('.aap-row').find((r: any) => r.text().includes(`#${id}`))
const attenuateIn = (r: any) => r?.findAll('button').find((b: any) => b.text() === 'attenuate')
async function open(w: any, id: number) {
  await attenuateIn(row(w, id))!.trigger('click')
}
async function derive(w: any) {
  await w.findAll('.aap-attform button').find((b: any) => b.text() === 'Derive child permit')!.trigger('click')
  await flushPromises()
  return h.deleg.attenuate.mock.calls[h.deleg.attenuate.mock.calls.length - 1]
}
const field = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the attenuate form on the Access panel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h.deleg)) f.mockReset()
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader'], mode: 'enforce', all_permissions: ['teg.transfer'],
      delegatable_permissions: { dev: ['teg.transfer'], org: ['teg.transfer'], agent: ['teg.transfer'] } })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: ['teg.transfer'], role_grants: [],
      delegate_enabled: false, spend_policy: null })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [PHONE, PLAIN, SEALED], mode: 'enforce' })
    h.deleg.attenuate.mockResolvedValue({ id: 99, token: 'att_child' })
  })

  it('a token whose own caveats forbid re-delegation offers no attenuate', async () => {
    const w = await panel()
    expect(attenuateIn(row(w, 7)), 'a phone token can be attenuated').toBeTruthy()
    expect(attenuateIn(row(w, 9)), 'the registry refuses it: the panel does not offer it').toBeUndefined()   // BASE: offered
  })

  it('a phone token\'s form starts from the token\'s own limits', async () => {
    const w = await panel()
    await open(w, 7)
    expect(field(w, 'aap-att-phone').exists(), 'the phone fields').toBe(true)   // BASE: none
    expect((field(w, 'aap-att-apps').element as HTMLInputElement).value).toBe('com.vault.bank')
    expect((field(w, 'aap-att-domains').element as HTMLInputElement).value).toBe('bank.example')
    expect((field(w, 'aap-att-actions').element as HTMLInputElement).value).toBe('5')
    expect((field(w, 'aap-att-session').element as HTMLInputElement).value).toBe('120')
    for (const box of ['aap-att-noshot', 'aap-att-nonet']) {
      const el = field(w, box).element as HTMLInputElement
      expect([el.checked, el.disabled], `${box}: the parent sets it, the child keeps it`).toEqual([true, true])
    }
    expect((field(w, 'aap-att-uses').element as HTMLInputElement).value, 'the uses it has left').toBe('3')
    expect((field(w, 'aap-att-budget').element as HTMLInputElement).value, 'a blank budget: the registry gives the rest').toBe('')
    expect(field(w, 'aap-att-budget').attributes('placeholder')).toContain('60')
    expect(field(w, 'aap-att-carried').text(), 'a limit without a field is kept, and said').toContain('did:theprotocol:shop')
  })

  it('deriving at once sends a child equal to the token on every limit', async () => {
    const w = await panel()
    await open(w, 7)
    const [id, body] = await derive(w)
    expect(id).toBe(7)
    expect(body.caveats).toEqual({   // BASE: { permissions } alone, which the registry refuses
      permissions: ['phone.use'], counterparty_allow: ['did:theprotocol:shop'],
      phone_allowed_apps: ['com.vault.bank'], phone_allowed_domains: ['bank.example'], phone_max_actions: 5,
      phone_ttl_seconds: 120, phone_no_screenshot: true, phone_no_network: true,
    })
    expect(body.max_uses).toBe(3)
    expect('budget_total' in body, 'no budget named: the registry gives the child what the parent has left').toBe(false)
    expect(w.find('.aap-once-code').text()).toBe('att_child')
  })

  it('a tightened child sends the tightened limits', async () => {
    const w = await panel()
    await open(w, 7)
    await field(w, 'aap-att-actions').setValue('2')
    await field(w, 'aap-att-session').setValue('60')
    await field(w, 'aap-att-uses').setValue('1')
    await field(w, 'aap-att-budget').setValue('10')
    const [, body] = await derive(w)
    expect([body.caveats.phone_max_actions, body.caveats.phone_ttl_seconds]).toEqual([2, 60])   // BASE: no such fields
    expect([body.max_uses, body.budget_total]).toEqual([1, 10])
  })

  it('a plain token\'s child is sent as it always was', async () => {   // control: the same on the old form
    const w = await panel()
    await open(w, 8)
    expect(w.find('[data-testid="aap-att-phone"]').exists(), 'no phone fields for a token that drives no phone').toBe(false)
    const [id, body] = await derive(w)
    expect([id, body]).toEqual([8, { caveats: { permissions: ['teg.transfer'] }, ttl_seconds: 3600 }])
  })
})
