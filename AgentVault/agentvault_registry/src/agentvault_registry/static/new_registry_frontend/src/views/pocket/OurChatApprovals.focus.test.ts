import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0651 (y): a link names one request (a push opens /pocket/ourchat/<room>?approval=<id>, so does Pocket's Approvals).
 * The pinned panel shows that request highlighted, reads again when the named request changes (a push can name one this
 * screen has not read yet), and says so when it no longer waits instead of showing nothing. BASE (V0650): no focus.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))

import OurChatApprovals from './OurChatApprovals.vue'

const item = (id: string) => ({
  id, conversation_id: 'room1', status: 'pending', title: `Request ${id}`,
  requester: { agent_did: 'did:theprotocol:eu:00000000aaaaaa', name: 'session-release' },
  created_at: '2026-10-31T03:50:00Z', expires_at: new Date(Date.now() + 3600e3).toISOString(),
})
const listing = (items: unknown[]) => ({ items, can_decide: true, presence: 'off' })
const mountWith = (focusId: string) => mount(OurChatApprovals, {
  props: { conversationId: 'room1', token: 'dev-tok', focusId },
  global: { stubs: { Icon: true, StepUpConfirm: true } },
})

describe('the pinned panel opens on the request a link names', () => {
  beforeEach(() => { h.chat = {} })

  it('highlights the named request and no other', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_aa11'), item('apr_bb22')]))
    const w = mountWith('apr_bb22')
    await flushPromises()
    expect(w.find('[data-testid="oca-item-apr_bb22"]').classes()).toContain('oca-focus')
    expect(w.find('[data-testid="oca-item-apr_aa11"]').classes()).not.toContain('oca-focus')
    expect(w.find('[data-testid="oca-gone"]').exists()).toBe(false)
  })

  it('says the request no longer waits when it is not pending any more', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([]))
    const w = mountWith('apr_cc33')
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').exists()).toBe(true)
    expect(w.find('[data-testid="oca-gone"]').exists()).toBe(true)
    // control: without a named request an empty list shows no panel at all (V0650's behaviour)
    const plain = mountWith('')
    await flushPromises()
    expect(plain.find('[data-testid="ost-approvals"]').exists()).toBe(false)
  })

  it('reads again when the named request changes on the same screen', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_aa11')]))
      .mockResolvedValue(listing([item('apr_aa11'), item('apr_dd44')]))
    const w = mountWith('apr_aa11')
    await flushPromises()
    const before = h.chat.listApprovals.mock.calls.length
    await w.setProps({ focusId: 'apr_dd44' })
    await flushPromises()
    expect(h.chat.listApprovals.mock.calls.length).toBe(before + 1)
    expect(w.find('[data-testid="oca-item-apr_dd44"]').classes()).toContain('oca-focus')
  })
})
