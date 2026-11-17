import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (order gwo_7dd5a9be91eede9c2cc35376, his request seq 3349): the bell keeps mentions as their own group, read on its own,
 * above the account's feed. A mention opens the console's thread at the line; the feed notice the group already shows is not
 * listed twice (an @all notice, which the group does not hold, stays); a read that could not be taken says so.
 */
const h = vi.hoisted(() => ({ n: null as any, push: vi.fn() }))
vi.mock('@/stores/notifications', async () => {
  const { reactive } = await import('vue')
  h.n = reactive({
    items: [] as any[], feed: [] as any[], unreadFailed: false, feedFailed: false, unreadCount: 0, loading: false,
    mentionItems: [] as any[], mentionTotal: 0, mentionsFailed: false, mentionsMarking: false, mentionsMarkFailed: false,
    markMentionsRead: vi.fn().mockResolvedValue(undefined),
    fetchUnread: vi.fn().mockResolvedValue(undefined), fetchFeed: vi.fn().mockResolvedValue(undefined), fetchMentions: vi.fn().mockResolvedValue(undefined),
    markRead: vi.fn(), markFeedRead: vi.fn(), markAllRead: vi.fn(),
  })
  return { useNotificationStore: () => h.n }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push.mockResolvedValue(undefined) }) }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: { value: false } }) }))

import NotificationBell from './NotificationBell.vue'

const ROOM = '269dd5af-93d1-4fe2-96b0-43c4039f7009'
const OTHER = '11111111-2222-3333-4444-555555555555'
const mention = { id: 'm1', conversation_id: ROOM, kind: 'org', title: 'Sessions', seq: 7, sender: 'Mira', preview: 'ping @him', created_at: new Date().toISOString() }
const opts = { attachTo: document.body, global: { stubs: { Icon: true, ReadFailedNotice: true, Teleport: true, teleport: true } } }
async function opened() {
  const w = mount(NotificationBell, opts)
  await flushPromises()
  await w.find('button').trigger('click')                 // the bell
  await flushPromises()
  return w
}

describe('the bell Mentions group', () => {
  beforeEach(() => {
    h.n.items = []; h.n.feed = []; h.n.mentionItems = []; h.n.mentionTotal = 0; h.n.mentionsFailed = false
    h.push.mockClear(); h.n.fetchMentions.mockClear(); document.body.innerHTML = ''
  })

  it('reads on mount and on every open, and shows its own group above the account feed', async () => {
    h.n.mentionItems = [mention]; h.n.mentionTotal = 4
    h.n.feed = [{ id: 1, type_key: 'guild.bid_received', title: 'New bid', body: 'b', click: null, created_at: '2026-11-13T09:00:00Z', read: false }]
    const w = await opened()
    expect(h.n.fetchMentions).toHaveBeenCalledTimes(2)
    const group = document.querySelector('[data-testid="nb-mentions"]')!
    expect(group).not.toBeNull()
    expect(group.textContent).toContain('MENTIONS')
    expect(document.querySelector('[data-testid="nb-mentions-total"]')!.textContent).toContain('4')
    expect(group.textContent).toContain('Mira · Sessions')
    const all = document.body.innerHTML
    expect(all.indexOf('nb-mentions')).toBeLessThan(all.indexOf('data-testid="nb-feed"'))      // above the feed
    w.unmount()
  })

  it('opens the console thread at the line', async () => {
    h.n.mentionItems = [mention]
    const w = await opened()
    ;(document.querySelector('[data-testid="nb-mention-7"]') as HTMLElement).click()
    expect(h.push).toHaveBeenCalledWith({ path: `/ourchat/${ROOM}`, query: { m: 'm1' } })
    w.unmount()
  })

  it('does not list a chat.mention notice for a room the group shows, but keeps an @all room and every other type', async () => {
    h.n.mentionItems = [mention]
    h.n.feed = [
      { id: 1, type_key: 'chat.mention', title: 'Mira', body: 'ping @him', click: `/ui#/pocket/ourchat/${ROOM}`, created_at: '2026-11-13T09:00:00Z', read: false },
      { id: 2, type_key: 'chat.mention', title: 'Kit', body: '@all lunch', click: `/ui#/pocket/ourchat/${OTHER}`, created_at: '2026-11-13T09:01:00Z', read: false },
      { id: 3, type_key: 'guild.bid_received', title: 'New bid', body: 'b', click: `/ui#/pocket/ourchat/${ROOM}`, created_at: '2026-11-13T09:02:00Z', read: false },
    ]
    const w = await opened()
    const ids = [...document.querySelectorAll('[data-feed-id]')].map((e) => e.getAttribute('data-feed-id'))
    expect([...ids].sort()).toEqual(['2', '3'])
    w.unmount()
  })

  it('says so, with Try again, when the mentions could not be read, and is not "All clear"', async () => {
    h.n.mentionsFailed = true
    const w = await opened()
    expect(document.querySelector('[data-testid="nb-mentions-failed"]')).not.toBeNull()
    expect(document.body.textContent).not.toContain('All clear.')
    ;(document.querySelector('[data-testid="nb-mentions-failed"] button') as HTMLElement).click()
    expect(h.n.fetchMentions).toHaveBeenCalled()
    w.unmount()
  })

  it('control: with nothing unread and nothing failed there is no group', async () => {
    const w = await opened()
    expect(document.querySelector('[data-testid="nb-mentions"]')).toBeNull()
    expect(document.body.textContent).toContain('All clear.')
    w.unmount()
  })

  it('has a Mark all read that asks the store to clear the group, waits while it works, and says when it could not', async () => {
    h.n.mentionItems = [mention]; h.n.mentionTotal = 4
    const w = await opened()
    const btn = document.querySelector('[data-testid="nb-mentions-markall"]') as HTMLButtonElement
    expect(btn).not.toBeNull()
    btn.click(); await flushPromises()
    expect(h.n.markMentionsRead).toHaveBeenCalledTimes(1)
    h.n.mentionsMarking = true; await flushPromises()
    expect((document.querySelector('[data-testid="nb-mentions-markall"]') as HTMLButtonElement).disabled).toBe(true)
    h.n.mentionsMarking = false; h.n.mentionsMarkFailed = true; await flushPromises()
    expect(document.querySelector('[data-testid="nb-mentions-mark-failed"]')).not.toBeNull()
    h.n.mentionsMarkFailed = false
    w.unmount()
  })

  it('draws the mention token of a preview in the mention colour', async () => {
    h.n.mentionItems = [{ ...mention, preview: 'Please look @Commander and @Mira' }]
    const w = await opened()
    const ats = [...document.querySelectorAll('[data-testid="nb-mentions"] .nb-at')].map((e) => e.textContent)
    expect(ats).toEqual(['@Commander', '@Mira'])
    w.unmount()
  })
})
