/**
 * §FESUITE (2026-10-10): a refused action on the agent's Access panel is said where the action is, and the panel stays as
 * the person left it. Every action wrote the panel's one error state, which replaces the whole panel with "error + Retry":
 * a refused save threw away the roles and limits just set, and FastAPI's list of refused fields drew as JSON.
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

// the body the registry answers (errors.py, validation_exception_handler): the message as `detail`, the field in `error`
const refused422 = () => Promise.reject(Object.assign(new Error('Request failed with status code 422'), {
  response: { status: 422, data: {
    error: { detail: 'Input should be greater than or equal to 1', type: 'validation_error', code: 'VALIDATION_FAILED',
      field: 'body -> spend_policy -> rate_per_hour' },
    type: 'https://docs.theprotocol.cloud/errors/validation_error', title: 'Validation Error', status: 422,
    detail: 'Input should be greater than or equal to 1' } },
}))

async function panel() {
  const w = mount(AgentAccessPanel, {
    props: { agentDid: 'did:theprotocol:a1', mode: 'owner' },
    global: { stubs: { AgentLineageTree: true } },
  })
  await flushPromises()
  return w
}

describe('a refused action on the agent Access panel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader', 'governor'], mode: 'enforce', all_permissions: ['transfer.local'],
      delegatable_permissions: { dev: ['transfer.local'], org: ['transfer.local'], agent: ['transfer.local'] } })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: ['transfer.local'], role_grants: [],
      delegate_enabled: false, spend_policy: null })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
  })

  it('a refused save keeps the panel and the edits, and says the refused field in words', async () => {
    h.authz.set.mockImplementation(refused422)
    const w = await panel()
    await w.findAll('.aap-role-opt').find((b) => b.text() === 'governor')!.trigger('click')
    const fields = w.findAll('input.aap-in[type="number"]')
    const rate = fields.find((i) => i.attributes('placeholder') === 'unlimited')!
    await rate.setValue('0')
    await w.find('.aap-actions .aap-btn--primary').trigger('click')
    await flushPromises()
    expect(w.find('.aap-error').exists(), 'the whole panel replaced by the error box').toBe(false)
    expect(w.text()).toContain('Roles')
    const said = w.find('.aap-actions [data-testid="aap-refused"]')
    expect(said.exists(), 'the refusal is said beside Save').toBe(true)
    expect(said.text()).toBe('rate per hour: Input should be greater than or equal to 1')
    expect(said.text()).not.toMatch(/[{}[\]]/)
    expect(w.findAll('.aap-role-opt--on').map((b) => b.text()), 'the role just chosen is still chosen').toContain('governor')
    expect((rate.element as HTMLInputElement).value, 'the value just typed is still there').toBe('0')
  })

  it('a refused grant is said in the delegation section, and the panel stays', async () => {
    h.deleg.createGrant.mockRejectedValue(Object.assign(new Error('Request failed with status code 403'),
      { response: { status: 403, data: { detail: 'authz.delegate is required to delegate' } } }))
    const w = await panel()
    await w.find('.aap-grantform input.aap-in--sm').setValue('12')
    await w.find('.aap-permpick .aap-permopt').trigger('click')
    await w.find('.aap-grantform .aap-btn--sm').trigger('click')
    await flushPromises()
    expect(w.find('.aap-error').exists()).toBe(false)
    const said = w.findAll('[data-testid="aap-refused"]')
    expect(said).toHaveLength(1)
    expect(said[0].text()).toBe('authz.delegate is required to delegate')
    expect(w.find('.aap-actions [data-testid="aap-refused"]').exists(), 'said beside Save instead of the grant').toBe(false)
  })

  it('a cap the person emptied is sent as none (it was "", which the server refuses as not a number)', async () => {
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: [], role_grants: [],
      delegate_enabled: false, spend_policy: { max_per_tx: 2, max_per_day: null, allowed_currencies: null,
        counterparty_mode: 'any', counterparty_allow: null, require_approval_above: 1, rate_per_hour: null, geo_allow: null } })
    h.authz.set.mockResolvedValue({ roles: ['trader'], effective_permissions: [], role_grants: [], spend_policy: null })
    const w = await panel()
    const caps = w.findAll('input.aap-in[type="number"]')
    await caps[0].setValue('')                                   // Max per transaction, emptied
    await caps.find((i) => i.attributes('placeholder') === 'none')!.setValue('')   // Require approval above, emptied
    await w.find('.aap-actions .aap-btn--primary').trigger('click')
    await flushPromises()
    const body = h.authz.set.mock.calls[h.authz.set.mock.calls.length - 1]?.[1]
    expect(body?.spend_policy?.max_per_tx).toBeNull()
    expect(body?.spend_policy?.require_approval_above).toBeNull()
    expect(body?.spend_policy?.max_per_day).toBeNull()
    expect(w.find('.aap-actions .aap-ok').exists(), 'Saved').toBe(true)
  })

  it('the panel\'s own read failing is still the error box with Retry', async () => {
    h.authz.get.mockRejectedValue(new Error('Request failed with status code 502'))
    const w = await panel()
    expect(w.find('.aap-error').exists()).toBe(true)
  })
})
