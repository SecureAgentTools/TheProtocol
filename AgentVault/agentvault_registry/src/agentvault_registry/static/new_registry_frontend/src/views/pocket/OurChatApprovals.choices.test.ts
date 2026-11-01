import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0652 (ab) (order gwo_dfa5e1d0ce56a8ceb0d1f61b): choice cards. A choice is one tap on one of its options in the pinned
 * panel (or "None of these"), on desktop and in Pocket (the same panel); "Approve all" never decides one; the thread's
 * card shows the options, then the one chosen. BASE (V0651): no options, an Approve button on every request.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))

import OurChatApprovals from './OurChatApprovals.vue'
import OurStateCard from '@/components/ourstate/OurStateCard.vue'
import { approveAllIds, isChoice, liveApprovalStatus } from '@/services/chat/approvals'
import { cardView } from '@/services/chat/cards'

const OPTS = ['Roll now', 'Wait for V0652', 'Roll the sandbox only']
const later = () => new Date(Date.now() + 3600e3).toISOString()
const item = (id: string, options?: string[]) => ({
  id, conversation_id: 'room1', status: 'pending', title: `Request ${id}`, ...(options ? { options } : {}),
  requester: { agent_did: 'did:theprotocol:eu:00000000aaaaaa', name: 'session-release' },
  created_at: '2026-10-31T03:50:00Z', expires_at: later(),
})
const listing = (items: unknown[], canDecide = true) => ({ items, can_decide: canDecide, presence: 'off' })
const panel = () => mount(OurChatApprovals, {
  props: { conversationId: 'room1', token: 'dev-tok' }, global: { stubs: { Icon: true, StepUpConfirm: true } },
})

describe('a choice is one tap on one of its options', () => {
  beforeEach(() => { h.chat = {} })

  it('shows each option as a button and sends the one tapped', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_c1', OPTS), item('apr_a1')]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decision: 'chosen', decided: [] })
    const w = panel()
    await flushPromises()
    const buttons = w.findAll('[data-testid^="oca-option-apr_c1-"]')
    expect(buttons.map((b) => b.text())).toEqual(OPTS)
    expect(w.find('[data-testid="oca-approve-apr_c1"]').exists()).toBe(false)   // a choice is never approved
    expect(w.find('[data-testid="oca-approve-apr_a1"]').exists()).toBe(true)    // an approval still is
    await w.find('[data-testid="oca-option-apr_c1-1"]').trigger('click')
    await flushPromises()
    expect(h.chat.decideApprovals).toHaveBeenCalledWith('dev-tok', 'room1',
      expect.objectContaining({ decision: 'choose', approval_ids: ['apr_c1'], option: 1 }))
  })

  it('"None of these" declines it', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_c2', OPTS)]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decision: 'denied', decided: [] })
    const w = panel()
    await flushPromises()
    await w.find('[data-testid="oca-deny-apr_c2"]').trigger('click')
    await flushPromises()
    const body = h.chat.decideApprovals.mock.calls[0][2]
    expect(body.decision).toBe('deny')
    expect('option' in body).toBe(false)
  })

  it('a member who cannot decide sees the options, and no buttons', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_c3', OPTS)], false))
    const w = panel()
    await flushPromises()
    expect(w.find('[data-testid="oca-option-list"]').text()).toContain('Wait for V0652')
    expect(w.findAll('[data-testid^="oca-option-apr_c3-"]').length).toBe(0)
  })
})

describe('the rules the panel and the thread follow', () => {
  it('"Approve all" sends the approvals and never a choice', () => {
    const items = [item('apr_a1'), item('apr_c1', OPTS), item('apr_a2')] as any[]
    expect(approveAllIds(items, Date.now())).toEqual(['apr_a1', 'apr_a2'])
    expect(isChoice(items[1])).toBe(true)
    expect(isChoice(items[0])).toBe(false)
  })

  it("the thread reads a choice's status from its cards", () => {
    const req = { kind: 'card', card: { v: 1, type: 'choice.request', data: { approval_id: 'apr_c1', title: 'x',
      options: OPTS, expires_at: later() } } }
    const done = { kind: 'card', card: { v: 1, type: 'choice.decided', data: { approval_id: 'apr_c1', decision: 'chosen',
      options: OPTS, chosen: { index: 0, label: 'Roll now' } } } }
    expect(liveApprovalStatus([req], Date.now())).toEqual({ apr_c1: 'pending' })
    expect(liveApprovalStatus([req, done], Date.now())).toEqual({ apr_c1: 'chosen' })
  })

  it('the card shows the options, then the one chosen', () => {
    const request = mount(OurStateCard, { props: { card: { v: 1, type: 'choice.request', data: {
      approval_id: 'apr_c1', title: 'V0651 tonight?', options: OPTS, expires_at: later() } } },
      global: { stubs: { Icon: true } } })
    expect(request.find('[data-testid="osc-choice-request"]').exists()).toBe(true)
    expect(request.find('[data-testid="osc-choice-options"]').findAll('li').map((l) => l.text())).toEqual(OPTS)
    const decided = mount(OurStateCard, { props: { card: { v: 1, type: 'choice.decided', data: {
      approval_id: 'apr_c1', title: 'V0651 tonight?', options: OPTS, decision: 'chosen',
      chosen: { index: 1, label: 'Wait for V0652' }, decided_by_developer_id: 6, decided_by_name: 'maintainer',
      role: 'owner' } } }, global: { stubs: { Icon: true } } })
    expect(decided.find('[data-testid="osc-choice-chosen"]').text()).toContain('Wait for V0652')
    // a chosen label that is not one of the options is shown as no choice at all
    const v = cardView({ v: 1, type: 'choice.decided', data: { approval_id: 'apr_c1', title: 'x', options: OPTS,
      decision: 'chosen', chosen: { index: 0, label: 'Something else' } } } as any) as any
    expect(v.decision).toBe('denied')
    expect(v.chosen).toBe(null)
  })
})
