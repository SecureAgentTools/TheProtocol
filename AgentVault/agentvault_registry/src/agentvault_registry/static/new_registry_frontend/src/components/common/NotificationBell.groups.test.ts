import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (his suggestion 3): the bell groups the account's feed by kind, marks a kind (or all) read, and mutes a kind. A muted kind
 * is one quiet line that still counts what it holds and shows it again on a press; the choice is kept on this device. Security
 * cannot be muted and the Mentions group has no mute at all. The harness is NotificationBell.mentions.test.ts's.
 */
const h = vi.hoisted(() => ({ n: null as any, push: vi.fn() }))
vi.mock('@/stores/notifications', async () => {
  const { reactive } = await import('vue')
  h.n = reactive({
    items: [] as any[], feed: [] as any[], unreadFailed: false, feedFailed: false, unreadCount: 0, loading: false,
    mentionItems: [] as any[], mentionTotal: 0, mentionsFailed: false,
    fetchUnread: vi.fn().mockResolvedValue(undefined), fetchFeed: vi.fn().mockResolvedValue(undefined), fetchMentions: vi.fn().mockResolvedValue(undefined),
    markRead: vi.fn(), markFeedRead: vi.fn(), markAllRead: vi.fn(), markFeedReadMany: vi.fn(), markAllFeedRead: vi.fn(),
  })
  return { useNotificationStore: () => h.n }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push.mockResolvedValue(undefined) }) }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: { value: false } }) }))

import NotificationBell from './NotificationBell.vue'

let n = 0
const e = (category: string) => ({ id: ++n, type_key: `${category}.x`, category, severity: 'info', title: `${category} ${n}`, body: 'b', click: null,
  created_at: new Date(Date.UTC(2026, 10, 14, 0, n)).toISOString(), read: false })
const opts = { attachTo: document.body, global: { stubs: { Icon: true, ReadFailedNotice: true, Teleport: true, teleport: true } } }
const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
async function opened() {
  const w = mount(NotificationBell, opts)
  await flushPromises()
  await w.find('button').trigger('click')
  await flushPromises()
  return w
}

describe('the grouped bell', () => {
  beforeEach(() => {
    n = 0
    h.n.items = []; h.n.mentionItems = []; h.n.mentionTotal = 0; h.n.mentionsFailed = false
    h.n.feed = [e('chat'), e('chat'), e('chat'), e('money'), e('security')]
    for (const f of ['markFeedRead', 'markFeedReadMany', 'markAllFeedRead']) h.n[f].mockClear()
    localStorage.clear(); document.body.innerHTML = ''
  })

  it('shows one group per kind with its count, newest kind first', async () => {
    const w = await opened()
    expect(q('nb-group-chat')!.textContent).toContain('Chat · 3')
    expect(q('nb-group-money')!.textContent).toContain('Money · 1')
    const order = [...document.querySelectorAll('.nb-group')].map((g) => g.getAttribute('data-testid'))
    expect(order).toEqual(['nb-group-security', 'nb-group-money', 'nb-group-chat'])
    w.unmount()
  })

  it('marks one kind read with the ids of its entries, and all read through the store', async () => {
    const w = await opened()
    q('nb-group-read-chat')!.click()
    expect(h.n.markFeedReadMany).toHaveBeenCalledWith([3, 2, 1])
    q('nb-feed-read-all')!.click()
    expect(h.n.markAllFeedRead).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('mutes a kind into one quiet line that counts it, keeps the choice, and shows it again on a press', async () => {
    const w = await opened()
    q('nb-group-mute-chat')!.click()
    await flushPromises()
    expect(q('nb-group-chat')).toBeNull()
    expect(q('nb-quiet-count')!.textContent).toBe('3 muted')
    expect(JSON.parse(localStorage.getItem('bell.mutedKinds')!)).toEqual(['chat'])
    expect(h.n.markFeedRead).not.toHaveBeenCalled()                       // muting reads nothing: nothing is lost
    expect(h.n.markFeedReadMany).not.toHaveBeenCalled()
    q('nb-unmute-chat')!.click()
    await flushPromises()
    expect(q('nb-group-chat')!.textContent).toContain('Chat · 3')
    expect(q('nb-quiet')).toBeNull()
    expect(JSON.parse(localStorage.getItem('bell.mutedKinds')!)).toEqual([])
    w.unmount()
  })

  it('opens already muted when this device chose so earlier', async () => {
    localStorage.setItem('bell.mutedKinds', '["money"]')
    const w = await opened()
    expect(q('nb-group-money')).toBeNull()
    expect(q('nb-quiet-count')!.textContent).toBe('1 muted')
    w.unmount()
  })

  it('offers no mute on security, even when storage names it, and none on the Mentions group', async () => {
    localStorage.setItem('bell.mutedKinds', '["security"]')
    h.n.mentionItems = [{ id: 'm1', conversation_id: 'c1', title: 'Room', seq: 4, sender: 'Mira', preview: 'hi', created_at: new Date().toISOString() }]
    const w = await opened()
    expect(q('nb-group-security')).not.toBeNull()
    expect(q('nb-group-mute-security')).toBeNull()
    expect(q('nb-group-mute-chat')).not.toBeNull()
    // mentions: no mute, ever. V0664 (his report, seq 4032): the group has a Mark all read, which moves read marks and hides nothing
    expect(q('nb-mentions')!.querySelector('[data-testid^="nb-group-mute"]')).toBeNull()
    expect([...q('nb-mentions')!.querySelectorAll('.nb-link')].map((b) => b.textContent)).toEqual(['Mark all read'])
    w.unmount()
  })
})
