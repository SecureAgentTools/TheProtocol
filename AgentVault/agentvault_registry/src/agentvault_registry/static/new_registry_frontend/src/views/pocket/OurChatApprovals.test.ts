import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0650 (l): the approvals panel pinned above the thread. Approve and Deny per request, Approve all sends exactly the
 * displayed requests that have not expired, an expired request is inert, a decided one leaves the panel, a caller who
 * may not decide sees no buttons, a failed read says so, and a 428 (the room asks for a phone confirmation) resends
 * the same decision with the approved challenge. BASE (V0649): the component does not exist.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))

import OurChatApprovals from './OurChatApprovals.vue'

const NOW = Date.parse('2026-10-31T04:00:00Z')
const item = (id: string, over: Record<string, unknown> = {}) => ({
  id, conversation_id: 'room1', status: 'pending', title: `Request ${id}`, unlocks: `step ${id}`,
  requester: { agent_did: 'did:theprotocol:eu:00000000aaaaaa', name: 'session-release' },
  created_at: '2026-10-31T03:50:00Z', expires_at: '2026-10-31T05:00:00Z', ...over,
})
const listing = (items: unknown[], canDecide = true) => ({ items, can_decide: canDecide, presence: 'off' })

const StepUpStub = {
  name: 'StepUpConfirm',
  props: ['show', 'challenge', 'busy', 'title', 'lead', 'deniedText', 'expiredText'],
  emits: ['approved', 'update:show'],
  template: '<div v-if="show" data-testid="stepup-stub" :data-challenge="challenge && challenge.challengeId"></div>',
}
const opts = { props: { conversationId: 'room1', token: 'dev-tok' }, global: { stubs: { Icon: true, StepUpConfirm: StepUpStub } } }

describe('the approvals panel pinned above the thread', () => {
  beforeEach(() => {
    h.chat = {}
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => { vi.useRealTimers() })

  it('decides one request with Approve, with the developer token, and the decided one leaves the panel', async () => {
    h.chat.listApprovals = vi.fn()
      .mockResolvedValueOnce(listing([item('apr_1'), item('apr_2')]))
      .mockResolvedValue(listing([item('apr_2')]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decided: [{ id: 'apr_1' }], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').exists()).toBe(true)
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    expect(h.chat.decideApprovals).toHaveBeenCalledWith('dev-tok', 'room1',
      expect.objectContaining({ decision: 'approve', approval_ids: ['apr_1'], surface: 'console' }))
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    expect(w.find('[data-testid="oca-item-apr_2"]').exists()).toBe(true)
  })

  it('Deny decides that one request the other way', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_d')]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decided: [{ id: 'apr_d' }], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-deny-apr_d"]').trigger('click')
    await flushPromises()
    expect(h.chat.decideApprovals.mock.calls[0][2]).toMatchObject({ decision: 'deny', approval_ids: ['apr_d'] })
  })

  it('Approve all sends exactly the displayed requests that have not expired, and an expired one is inert', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([
      item('apr_a'), item('apr_b', { created_at: '2026-10-31T03:55:00Z' }),
      item('apr_old', { expires_at: '2026-10-31T03:59:00Z' }),
    ]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decided: [], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    const all = w.find('[data-testid="oca-approve-all"]')
    expect(all.text()).toContain('2')
    expect(w.find('[data-testid="oca-item-apr_old"]').attributes('data-expired')).toBe('1')
    expect(w.find('[data-testid="oca-approve-apr_old"]').attributes('disabled')).toBeDefined()
    await all.trigger('click')
    await flushPromises()
    expect(h.chat.decideApprovals.mock.calls[0][2].approval_ids).toEqual(['apr_a', 'apr_b'])
  })

  it('a request that expires while it is on screen turns inert without a new read', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_s', { expires_at: '2026-10-31T04:00:02Z' })]))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="oca-approve-apr_s"]').attributes('disabled')).toBeUndefined()
    vi.advanceTimersByTime(3000)
    await flushPromises()
    expect(w.find('[data-testid="oca-approve-apr_s"]').attributes('disabled')).toBeDefined()
  })

  it('a member who may not decide sees the requests and no buttons', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_m'), item('apr_n')], false))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="oca-not-decider"]').exists()).toBe(true)
    expect(w.find('[data-testid="oca-approve-apr_m"]').exists()).toBe(false)
    expect(w.find('[data-testid="oca-approve-all"]').exists()).toBe(false)
  })

  it('a failed read is shown as a failed read, never as an empty panel', async () => {
    h.chat.listApprovals = vi.fn().mockRejectedValue(Object.assign(new Error('HTTP 503'), { status: 503 }))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="oca-read-failed"]').exists()).toBe(true)
  })

  it('nothing pending renders nothing at all', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([]))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').exists()).toBe(false)
  })

  it('a 428 opens the phone confirmation and resends the same decision with the approved challenge', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_p')]))
    const step = { error: 'step_up_required', step_up: { challenge_id: 'lch_9', challenge_hash: 'h', facts: {},
      expires_at: '2026-10-31T04:02:00Z', ttl_seconds: 120, methods: ['device'] } }
    h.chat.decideApprovals = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error('HTTP 428'), { status: 428, body: step }))
      .mockResolvedValue({ decided: [{ id: 'apr_p' }], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_p"]').trigger('click')
    await flushPromises()
    const dialog = w.findComponent(StepUpStub)
    expect(dialog.props('show')).toBe(true)
    expect(w.find('[data-testid="stepup-stub"]').attributes('data-challenge')).toBe('lch_9')
    dialog.vm.$emit('approved', 'lch_9')
    await flushPromises()
    expect(h.chat.decideApprovals.mock.calls[1][2]).toMatchObject({ decision: 'approve', approval_ids: ['apr_p'],
      challenge_id: 'lch_9' })
    expect(w.find('[data-testid="stepup-stub"]').exists()).toBe(false)
  })
})
