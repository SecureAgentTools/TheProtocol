import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

/**
 * §MEMBERSHIP phase C (2026-10-02) — "this agent is not allowed to vote yet", and the press that allows it: the governor
 * role, added after a second press through the additive rail (POST /agents/{did}/authz/roles) with every other grant as
 * it is. On an image without the rail, the whole-set PUT, read again right before the write and never over a time limit.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn(), addRole: vi.fn() }))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: { get: h.get, set: h.set, addRole: h.addRole } }))

import VotePermissionNotice from './VotePermissionNotice.vue'

const LIMITED = [{ role: 'trader', expires_at: '2026-12-01T00:00:00Z' }, { role: 'client', expires_at: null }]
const ENFORCE = (over: Record<string, unknown> = {}) => ({ agent_did: 'did:a', mode: 'enforce', roles: ['trader', 'client'],
  effective_permissions: ['teg.transfer'], role_grants: [{ role: 'trader', expires_at: null }, { role: 'client', expires_at: null }], ...over })
const ALLOWED = ENFORCE({ roles: ['trader', 'client', 'governor'], effective_permissions: ['teg.transfer', 'gov.vote'] })
const ADDED = { agent_did: 'did:a', role: 'governor', changed: true, roles: ['trader', 'client', 'governor'], effective_permissions: ['teg.transfer', 'gov.vote'] }
const sel = (id: string) => `[data-testid="${id}"]`
function mountIt(props: Record<string, unknown> = {}) {
  return mount(VotePermissionNotice, { props: { did: 'did:a', ...props }, global: { stubs: { RouterLink: { props: ['to'], template: '<a :data-to="to"><slot /></a>' } } } })
}
const stateOf = (w: VueWrapper) => w.find(sel('vote-permission')).attributes('data-state')
async function press(w: VueWrapper) {
  await w.find(sel('vote-permission-allow')).trigger('click')
  await w.find(sel('vote-permission-confirm')).trigger('click'); await flushPromises()
}

beforeEach(() => { h.get.mockReset(); h.set.mockReset(); h.addRole.mockReset() })

describe('the vote permission notice', () => {
  it('says nothing where the agent may vote', async () => {
    h.get.mockResolvedValue(ALLOWED)
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('vote-permission')).exists()).toBe(false)
    expect(h.addRole).not.toHaveBeenCalled()
  })

  it('allows the agent after a second press: one governor role through the additive rail, nothing else written', async () => {
    h.get.mockResolvedValue(ENFORCE())
    h.addRole.mockResolvedValue(ADDED)
    const w = mountIt(); await flushPromises()
    expect(stateOf(w)).toBe('grantable')
    expect(w.find(sel('vote-permission-limits')).exists()).toBe(false)   // nothing carries a time limit: nothing to say about one
    await w.find(sel('vote-permission-allow')).trigger('click')
    expect(h.addRole).not.toHaveBeenCalled()                              // one press asks, it does not act
    await w.find(sel('vote-permission-confirm')).trigger('click'); await flushPromises()
    expect(h.addRole).toHaveBeenCalledWith('did:a', 'governor')
    expect(h.set).not.toHaveBeenCalled()
    expect(w.emitted('allowed')).toHaveLength(1)
    expect(w.find(sel('vote-permission')).exists()).toBe(false)
  })

  it('an agent whose roles carry a time limit is allowed through the rail too, and the notice says the limits stay', async () => {
    h.get.mockResolvedValue(ENFORCE({ role_grants: LIMITED }))
    h.addRole.mockResolvedValue(ADDED)
    const w = mountIt(); await flushPromises()
    expect(stateOf(w)).toBe('time_boxed')
    expect(w.find(sel('vote-permission-limits')).exists()).toBe(true)
    await press(w)
    expect(h.addRole).toHaveBeenCalledWith('did:a', 'governor')
    expect(h.set).not.toHaveBeenCalled()
    expect(w.emitted('allowed')).toHaveLength(1)
  })

  it('an image without the rail: its roles plus governor through the PUT, read again right before the write', async () => {
    h.get.mockResolvedValueOnce(ENFORCE()).mockResolvedValueOnce(ENFORCE()).mockResolvedValueOnce(ALLOWED)
    h.addRole.mockResolvedValue(null)
    h.set.mockResolvedValue({})
    const w = mountIt(); await flushPromises()
    await press(w)
    expect(h.addRole).toHaveBeenCalledTimes(1)
    expect(h.set).toHaveBeenCalledWith('did:a', { roles: ['trader', 'client', 'governor'] })
    expect(h.get).toHaveBeenCalledTimes(3)
    expect(w.emitted('allowed')).toHaveLength(1)
  })

  it('an image without the rail never writes over a time limit: the owner is sent to My Agents', async () => {
    h.get.mockResolvedValue(ENFORCE({ role_grants: LIMITED }))
    h.addRole.mockResolvedValue(null)
    const w = mountIt(); await flushPromises()
    await press(w)
    expect(h.set).not.toHaveBeenCalled()
    expect(w.emitted('allowed')).toBeUndefined()
    expect(stateOf(w)).toBe('panel_only')
    expect(w.find(sel('vote-permission-link')).attributes('data-to')).toBe('/my-agents')
    expect(w.find(sel('vote-permission-allow')).exists()).toBe(false)
  })

  it('control: without the rail, a time limit that appeared since the first look stops the write at the second read', async () => {
    h.get.mockResolvedValueOnce(ENFORCE()).mockResolvedValueOnce(ENFORCE({ role_grants: LIMITED }))
    h.addRole.mockResolvedValue(null)
    const w = mountIt(); await flushPromises()
    expect(stateOf(w)).toBe('grantable')
    await press(w)
    expect(h.set).not.toHaveBeenCalled()
    expect(w.emitted('allowed')).toBeUndefined()
    expect(stateOf(w)).toBe('panel_only')
  })

  it('a press that fails keeps the notice and its button and says why, writes nothing else, and can be pressed again', async () => {
    h.get.mockResolvedValue(ENFORCE())
    h.addRole.mockRejectedValueOnce(Object.assign(new Error('HTTP 403'), { response: { status: 403, data: { detail: 'Legacy-full agents keep their own authority' } } }))
      .mockResolvedValueOnce(ADDED)
    const w = mountIt(); await flushPromises()
    await press(w)
    expect(stateOf(w)).toBe('grantable')
    expect(w.find(sel('vote-permission-error')).text()).toContain('This agent could not be allowed to vote.')
    expect(w.find(sel('vote-permission-error')).text()).toContain('Legacy-full agents keep their own authority')
    expect(w.emitted('allowed')).toBeUndefined()
    expect(h.set).not.toHaveBeenCalled()                                  // the rail's refusal is not "no rail": no PUT behind it
    await press(w)
    expect(w.emitted('allowed')).toHaveLength(1)
    expect(w.find(sel('vote-permission')).exists()).toBe(false)
  })

  it('an unreadable permission is said only when a vote was just refused, never invented as a refusal', async () => {
    h.get.mockRejectedValue(Object.assign(new Error('403'), { response: { status: 403, data: { detail: 'not your agent' } } }))
    const quiet = mountIt(); await flushPromises()
    expect(quiet.find(sel('vote-permission')).exists()).toBe(false)
    const loud = mountIt({ refused: true }); await flushPromises()
    expect(stateOf(loud)).toBe('failed')
    expect(loud.find(sel('vote-permission-error')).text()).toContain('not your agent')
    expect(loud.find(sel('vote-permission-error')).text()).not.toContain('could not be allowed')   // a failed check is not a failed press
  })
})
