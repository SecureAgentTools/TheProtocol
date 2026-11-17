import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  mine: vi.fn(), get: vi.fn(), create: vi.fn(), advance: vi.fn(), cancel: vi.fn(), candidates: vi.fn(),
}))
vi.mock('@/services/api/workflows', () => ({ workflowsApi: api }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (_k: string, f?: string) => f ?? _k, tp: (_k: string, f?: string) => f ?? _k }) }))

import WorkflowsView from './WorkflowsView.vue'
import { useAuthStore } from '@/stores/auth'

const link = { step: 'build', output_hash: 'aa', prev: '0'.repeat(64), receipt: 'bb'.repeat(32) }
const view = (over: any = {}) => ({
  id: 'wf_1', owner_did: 'did:x', title: 'Release chain', status: 'running', ruleset: { bonded_only: true },
  ruleset_hash: 'ab'.repeat(32), total_budget: '30', currency: 'ECU', escrow_note: '', chain: [], chain_ok: true,
  steps: [
    { key: 'build', position: 0, role: 'builder', budget: '10', ruleset: {}, order_id: 'gwo_1', order_status: 'open', needs_attention: false },
    { key: 'verify', position: 1, role: 'verifier', budget: '10', ruleset: { independent_of: ['build'] }, order_id: null, needs_attention: false },
  ], ...over,
})

function signIn(withAgent = true) {
  const auth: any = useAuthStore()
  auth.token = 'dev-token'
  auth.agentToken = withAgent ? 'agent-token' : null
  auth.activeAgent = withAgent ? { did: 'did:x', name: 'Owner' } : null
}

const stubs = { Icon: true, 'router-link': { template: '<a><slot /></a>' } }

describe('WorkflowsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(api).forEach(f => f.mockReset())
    api.mine.mockResolvedValue({ workflows: [] })
  })

  it('asks a visitor to sign in and calls nothing', async () => {
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid=wfl-signin]').exists()).toBe(true)
    expect(api.mine).not.toHaveBeenCalled()
  })

  it('says why the list is empty and offers a new workflow', async () => {
    signIn()
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid=wfl-empty]').text()).toMatch(/several agents in order/)
    expect(w.find('[data-testid=wfl-new]').exists()).toBe(true)
  })

  it('the builder holds Save until the draft is valid, then sends the body', async () => {
    signIn()
    api.create.mockResolvedValue(view({ status: 'draft' }))
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-new]').trigger('click')
    const save = () => w.find('[data-testid=wfl-save]')
    expect(save().attributes('disabled')).toBeDefined()
    await w.find('[data-testid=wfl-f-title]').setValue('Release chain')
    await w.find('[data-testid=wfl-f-total]').setValue('10')
    await w.find('[data-testid=wfl-s-role-0]').setValue('builder')
    await w.find('[data-testid=wfl-s-budget-0]').setValue('10')
    expect(w.find('[data-testid=wfl-problems]').exists()).toBe(false)
    await save().trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledTimes(1)
    expect(api.create.mock.calls[0][0]).toMatchObject({ title: 'Release chain', total_budget: 10, steps: [{ key: 'step1', role: 'builder', budget: 10 }] })
    expect(w.find('[data-testid=wfl-detail]').exists()).toBe(true)
  })

  it('a budget above the total is named in the problems and cannot be saved', async () => {
    signIn()
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-new]').trigger('click')
    await w.find('[data-testid=wfl-f-title]').setValue('t')
    await w.find('[data-testid=wfl-f-total]').setValue('5')
    await w.find('[data-testid=wfl-s-role-0]').setValue('r')
    await w.find('[data-testid=wfl-s-budget-0]').setValue('9')
    expect(w.find('[data-testid=wfl-problems]').text()).toMatch(/above the total budget/)
    expect(w.find('[data-testid=wfl-save]').attributes('disabled')).toBeDefined()
  })

  it('shows the steps, the funds-lock note, and advances on the button', async () => {
    signIn()
    api.mine.mockResolvedValue({ workflows: [{ id: 'wf_1', title: 'Release chain', status: 'running', total_budget: '30', currency: 'ECU', created_at: '' }] })
    api.get.mockResolvedValue(view())
    api.advance.mockResolvedValue(view({ chain: [link], steps: [{ ...view().steps[0], receipt: 'bb'.repeat(32), output_hash: 'aa' }, view().steps[1]] }))
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=wfl-escrow-note]').text()).toMatch(/step by step/)
    expect(w.find('[data-testid=wfl-step-state-build]').text()).toMatch(/gwo_1/)
    expect(w.find('[data-testid=wfl-step-state-verify]').text()).toMatch(/Not posted yet/)
    await w.find('[data-testid=wfl-advance]').trigger('click')
    await flushPromises()
    expect(api.advance).toHaveBeenCalledWith('wf_1')
    expect(w.find('[data-testid=wfl-step-state-build]').text()).toMatch(/Settled/)
  })

  it('a workflow made from a template names it and links to its page; one made by hand says nothing (V0664)', async () => {
    signIn()
    const linkStubs = { Icon: true, 'router-link': { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
    api.mine.mockResolvedValue({ workflows: [{ id: 'wf_1', title: 'Release chain', status: 'running', total_budget: '30', currency: 'ECU', created_at: '' }] })
    api.get.mockResolvedValue(view({ template: { id: 'wtpl_abc', version: 2, content_hash: 'cd'.repeat(32), title: 'CRM to Postgres' } }))
    const w = mount(WorkflowsView, { global: { stubs: linkStubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    const line = w.find('[data-testid=wfl-from-template-line]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toMatch(/From template\s+CRM to Postgres\s+v2/)
    expect(JSON.parse(line.find('a').attributes('data-to') as string)).toEqual({ name: 'migrate-template', params: { id: 'wtpl_abc' } })
    api.get.mockResolvedValue(view({ template: null }))
    const w2 = mount(WorkflowsView, { global: { stubs: linkStubs } })
    await flushPromises()
    await w2.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    expect(w2.find('[data-testid=wfl-detail]').exists()).toBe(true)
    expect(w2.find('[data-testid=wfl-from-template-line]').exists()).toBe(false)
  })

  it('a step whose order ended unsettled is flagged and nothing offers to repost it', async () => {
    signIn()
    api.mine.mockResolvedValue({ workflows: [{ id: 'wf_1', title: 'T', status: 'running', total_budget: '1', currency: 'ECU', created_at: '' }] })
    api.get.mockResolvedValue(view({ steps: [{ ...view().steps[0], order_status: 'expired', needs_attention: true }] }))
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=wfl-step-state-build]').text()).toMatch(/Nothing reposts it/)
  })

  it('shows the server refusal sentence on a failed advance', async () => {
    signIn()
    api.mine.mockResolvedValue({ workflows: [{ id: 'wf_1', title: 'T', status: 'draft', total_budget: '1', currency: 'ECU', created_at: '' }] })
    api.get.mockResolvedValue(view({ status: 'draft' }))
    api.advance.mockRejectedValue({ response: { data: { detail: 'Posting this step would exceed the workflow\'s total budget' } } })
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    await w.find('[data-testid=wfl-advance]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=wfl-error]').text()).toMatch(/exceed the workflow/)
  })

  it('shows who passes a step, and where the reading stops', async () => {
    signIn()
    api.mine.mockResolvedValue({ workflows: [{ id: 'wf_1', title: 'T', status: 'draft', total_budget: '1', currency: 'ECU', created_at: '' }] })
    api.get.mockResolvedValue(view())
    api.candidates.mockResolvedValue({ step: 'build', rules: {}, scope: 'agents of this registry only', passing: ['did:a', 'did:b'], refused: 1, considered: 3 })
    const w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=wfl-open-wf_1]').trigger('click')
    await flushPromises()
    await w.find('[data-testid=wfl-cand-build]').trigger('click')
    await flushPromises()
    const txt = w.find('[data-testid=wfl-cands-build]').text()
    expect(txt).toMatch(/2 of 3 agents of this registry pass/); expect(txt).toMatch(/other registries are not read yet/)
  })
})
