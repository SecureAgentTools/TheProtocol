/**
 * §FESUITE (2026-10-10): the Access panel's on-behalf-of grant form asks only for what the registry takes. A dev grant
 * delegates the authority of the developer it names, and the registry takes only the caller's own ("Can only delegate
 * your own dev authority"); an agent principal is admin-only in v1. The form asked for any developer's id and offered
 * "agent" to everyone, so the console suite's lifecycle 78 made a grant to a second developer and was refused.
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

import { useAuthStore } from '@/stores/auth'
import AgentAccessPanel from './AgentAccessPanel.vue'

async function panelAs(user: Record<string, unknown>) {
  ;(useAuthStore() as any).user = user
  const w = mount(AgentAccessPanel, {
    props: { agentDid: 'did:theprotocol:a1', mode: 'owner' },
    global: { stubs: { AgentLineageTree: true } },
  })
  await flushPromises()
  return w
}
const ref = (w: any) => w.find('[data-testid="aap-grant-ref"]')
const offered = (w: any) => w.findAll('.aap-grantform select option').map((o: any) => o.attributes('value'))

describe('the on-behalf-of grant form', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader'], mode: 'enforce', all_permissions: ['transfer.local'],
      delegatable_permissions: { dev: ['transfer.local'], org: ['transfer.local'], agent: ['transfer.local'] } })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: ['transfer.local'], role_grants: [],
      delegate_enabled: false, spend_policy: null })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
    h.deleg.createGrant.mockReset()
  })

  it('names the member, fixed, and offers no agent principal', async () => {
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    expect((ref(w).element as HTMLInputElement).value, 'the dev grant names the viewer').toBe('77')
    expect(ref(w).attributes('readonly'), 'a member cannot name another developer').toBeDefined()
    expect(offered(w)).toEqual(['dev', 'org'])
  })

  it('the grant it sends names the member, and the form names them again after it', async () => {
    h.deleg.createGrant.mockResolvedValue({ id: 'g1' })
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    await w.find('.aap-permpick .aap-permopt').trigger('click')
    await w.find('.aap-grantform > button.aap-btn--sm').trigger('click')
    await flushPromises()
    expect(h.deleg.createGrant).toHaveBeenCalledTimes(1)
    expect(h.deleg.createGrant.mock.calls[0][1]).toMatchObject({ principal_type: 'dev', principal_ref: '77' })
    expect((ref(w).element as HTMLInputElement).value).toBe('77')
  })

  it('an org grant asks for the org, and dev again names the member', async () => {
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    await w.find('.aap-grantform select').setValue('org')
    expect((ref(w).element as HTMLInputElement).value).toBe('')
    expect(ref(w).attributes('readonly')).toBeUndefined()
    expect(ref(w).attributes('placeholder')).toMatch(/org slug/)
    await ref(w).setValue('acme')
    await w.find('.aap-grantform select').setValue('dev')
    expect((ref(w).element as HTMLInputElement).value).toBe('77')
  })

  it('a super admin is offered the agent principal and may name another developer', async () => {
    const w = await panelAs({ id: '1', role: 'admin', is_admin: true })
    expect(offered(w)).toEqual(['dev', 'org', 'agent'])
    expect((ref(w).element as HTMLInputElement).value).toBe('1')
    expect(ref(w).attributes('readonly')).toBeUndefined()
  })
})

/**
 * SEC-11 (2026-10-17): the grant form offers only what the registry takes from the chosen principal. It listed every
 * catalogue permission, and POST /agents/{did}/delegations refuses what a developer or an organization may not hand
 * out (D6-270). The form reads the sets the registry serves (the catalog's delegatable_permissions, the ones the grant
 * route applies); the mocks above held one permission, which no principal is refused, so they could never see it.
 */
describe('the grant form offers what the registry takes', () => {
  const ALL = ['authz.delegate', 'gov.vote', 'guild.bid_for_org', 'phone.use', 'teg.system_transfer']
  const chips = (w: any) => w.findAll('.aap-grantform .aap-permopt').map((b: any) => b.text())
  const choose = async (w: any, p: string) => {
    await w.findAll('.aap-grantform .aap-permopt').find((b: any) => b.text() === p)!.trigger('click')
  }
  beforeEach(() => {
    setActivePinia(createPinia())
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader'], mode: 'enforce', all_permissions: ALL,
      delegatable_permissions: { dev: ['authz.delegate', 'gov.vote'], org: ['gov.vote', 'guild.bid_for_org'], agent: ALL } })
    h.authz.get.mockResolvedValue({ mode: 'enforce', roles: ['trader'], effective_permissions: ['gov.vote'], role_grants: [],
      delegate_enabled: false, spend_policy: null })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
    h.deleg.createGrant.mockReset()
  })

  it('a dev grant offers what a developer may hand out, never a reserved permission', async () => {
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    expect(chips(w)).toEqual(['authz.delegate', 'gov.vote'])   // BASE: every catalogue permission
    expect(chips(w)).not.toContain('phone.use')
    expect(chips(w)).not.toContain('teg.system_transfer')
  })

  it('an org grant offers the org set, and a choice the next principal may not carry is dropped', async () => {
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    await w.find('.aap-grantform select').setValue('org')
    expect(chips(w)).toEqual(['gov.vote', 'guild.bid_for_org'])
    await choose(w, 'gov.vote'); await choose(w, 'guild.bid_for_org')
    await w.find('.aap-grantform select').setValue('dev')
    await ref(w).setValue('77')
    h.deleg.createGrant.mockResolvedValue({ id: 'g1' })
    await w.find('.aap-grantform > button.aap-btn--sm').trigger('click')
    await flushPromises()
    expect(h.deleg.createGrant.mock.calls[0]?.[1]?.permissions, 'only what a dev grant may carry is sent').toEqual(['gov.vote'])
  })

  it('a super admin naming an agent principal is offered every permission', async () => {
    const w = await panelAs({ id: '1', role: 'admin', is_admin: true })
    await w.find('.aap-grantform select').setValue('agent')
    expect(chips(w)).toEqual(ALL)
  })

  it('a catalog that serves no set offers nothing to delegate', async () => {
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader'], mode: 'enforce', all_permissions: ALL })
    const w = await panelAs({ id: '77', role: 'developer', is_admin: false })
    expect(chips(w)).toEqual([])   // BASE: every catalogue permission
    expect(w.find('.aap-grantform > button.aap-btn--sm').attributes('disabled')).toBeDefined()
  })
})
