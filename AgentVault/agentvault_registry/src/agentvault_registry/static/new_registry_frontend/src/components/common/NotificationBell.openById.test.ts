import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §ALERTS header strip (2026-10-06): "theprotocol:open-notification-bell" carries the broadcast to open (the critical
 * banner's "Show full", a press on a header strip). The bell ignored it and opened its dropdown, so "Show full" never
 * showed the full broadcast; a broadcast the bell holds now opens in its modal, and an event that names none (or one it
 * does not hold) still opens the dropdown.
 */
const h = vi.hoisted(() => ({ n: null as any }))
vi.mock('@/stores/notifications', async () => {
  const { reactive } = await import('vue')
  h.n = reactive({
    items: [] as any[], feed: [] as any[], unreadFailed: false, feedFailed: false, unreadCount: 0, loading: false,
    fetchUnread: vi.fn().mockResolvedValue(undefined), fetchFeed: vi.fn().mockResolvedValue(undefined),
    markRead: vi.fn(), markFeedRead: vi.fn(), markAllRead: vi.fn(),
  })
  return { useNotificationStore: () => h.n }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: { value: false } }) }))

import NotificationBell from './NotificationBell.vue'

const opts = { attachTo: document.body, global: { stubs: { Icon: true, ReadFailedNotice: true, Teleport: true, teleport: true } } }
const item = { id: 42, title: 'Disk filling', body: 'Free space now', broadcast_type: 'critical', created_at: '2026-10-06T09:00:00Z' }

describe('the bell opens the broadcast an event names', () => {
  beforeEach(() => { h.n.items = [item]; document.body.innerHTML = '' })

  it('a named broadcast it holds opens in the modal', async () => {
    const w = mount(NotificationBell, opts)
    await flushPromises()
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell', { detail: { broadcastId: 42 } }))
    await flushPromises()
    const modal = document.querySelector('.nb-modal')
    expect(modal, 'the modal is open').not.toBeNull()
    expect(modal!.getAttribute('aria-label')).toBe('Disk filling')
    w.unmount()
  })

  it('control: no name (or one it does not hold) opens the dropdown, not a modal', async () => {
    const w = mount(NotificationBell, opts)
    await flushPromises()
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell', { detail: { broadcastId: 999 } }))
    await flushPromises()
    expect(document.querySelector('.nb-modal')).toBeNull()
    w.unmount()
  })
})
