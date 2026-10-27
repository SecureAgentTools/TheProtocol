import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §ALERTS header strip (2026-10-06): the announcement bar, the still alternative to the LED ticker (Settings >
 * Preferences > Header strip). It reads the bell's store, opens a broadcast in the bell's modal, marks it read, rotates
 * several, says a failed read failed, and for an admin carries the alert chip.
 */
const h = vi.hoisted(() => ({
  n: null as any, auth: null as any, alerts: null as any,
  push: vi.fn(), fetchUnread: vi.fn(), markRead: vi.fn(), acquire: vi.fn(), refresh: vi.fn(),
}))
vi.mock('@/stores/notifications', async () => {
  const { reactive } = await import('vue')
  h.n = reactive({ items: [] as any[], unreadFailed: false, lastReadAt: 0, loading: false,
                   fetchUnread: h.fetchUnread, markRead: h.markRead })
  return { useNotificationStore: () => h.n }
})
vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  h.auth = reactive({ isAdmin: false, user: null as Record<string, unknown> | null })
  return { useAuthStore: () => h.auth }
})
vi.mock('@/services/header/activeAlerts', async () => {
  const { reactive } = await import('vue')
  h.alerts = reactive({ state: 'loading', alerts: [], counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 },
                        withheldSandbox: 0, reason: null, readAt: 0 })
  return { activeAlerts: h.alerts, acquireActiveAlerts: h.acquire, refreshActiveAlerts: h.refresh }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

import AnnouncementBar from './AnnouncementBar.vue'

const opts = { global: { stubs: { Icon: true } } }
const b = (id: number, type: string, created: string, title: string) => ({ id, title, body: `body ${id}`, broadcast_type: type, created_at: created })

describe('the announcement bar', () => {
  beforeEach(() => {
    h.n.items = []; h.n.unreadFailed = false; h.n.lastReadAt = 0
    h.auth.isAdmin = false
    h.auth.user = null
    Object.assign(h.alerts, { state: 'loading', reason: null, counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 } })
    h.push.mockReset(); h.fetchUnread.mockReset(); h.markRead.mockReset(); h.refresh.mockReset()
    h.acquire.mockReset().mockReturnValue(() => {})
  })
  afterEach(() => { vi.useRealTimers() })

  it("shows the most urgent unread broadcast; a press opens THAT broadcast in the bell's modal", async () => {
    h.n.lastReadAt = Date.now()
    h.n.items = [b(1, 'info', '2026-10-06T09:00:00Z', 'Newer notice'), b(2, 'critical', '2026-10-05T09:00:00Z', 'Disk filling')]
    const w = mount(AnnouncementBar, opts)
    await flushPromises()
    expect(w.find('[data-testid="ab-title"]').text()).toBe('Disk filling')
    const seen: any[] = []
    const listener = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener('theprotocol:open-notification-bell', listener)
    await w.find('[data-testid="ab-open"]').trigger('click')
    window.removeEventListener('theprotocol:open-notification-bell', listener)
    expect(seen).toEqual([{ broadcastId: 2 }])
    w.unmount()
  })

  it('the x marks the shown broadcast read', async () => {
    h.n.lastReadAt = Date.now()
    h.n.items = [b(5, 'warning', '2026-10-06T09:00:00Z', 'Maintenance tonight')]
    const w = mount(AnnouncementBar, opts)
    await w.find('[data-testid="ab-mark-read"]').trigger('click')
    expect(h.markRead).toHaveBeenCalledWith(5)
    w.unmount()
  })

  it('several rotate every 8 s and hold still while the pointer is on the bar', async () => {
    vi.useFakeTimers()
    h.n.lastReadAt = Date.now()
    h.n.items = [b(1, 'info', '2026-10-06T09:00:00Z', 'One'), b(2, 'info', '2026-10-06T08:00:00Z', 'Two')]
    const w = mount(AnnouncementBar, opts)
    expect(w.find('[data-testid="ab-count"]').text()).toBe('1/2')
    await vi.advanceTimersByTimeAsync(8000)
    expect(w.find('[data-testid="ab-count"]').text()).toBe('2/2')
    await w.find('[data-testid="announcement-bar"]').trigger('pointerenter')
    await vi.advanceTimersByTimeAsync(16000)
    expect(w.find('[data-testid="ab-count"]').text()).toBe('2/2')
    await w.find('[data-testid="announcement-bar"]').trigger('pointerleave')
    await vi.advanceTimersByTimeAsync(8000)
    expect(w.find('[data-testid="ab-count"]').text()).toBe('1/2')
    w.unmount()
  })

  it('says it is reading before the first answer, "none" after an empty one, and a failed read with a retry', async () => {
    const w = mount(AnnouncementBar, opts)
    expect(w.find('[data-testid="ab-loading"]').exists()).toBe(true)
    h.n.lastReadAt = Date.now()
    await flushPromises()
    expect(w.find('[data-testid="ab-none"]').exists()).toBe(true)
    h.n.unreadFailed = true
    await flushPromises()
    expect(w.find('[data-testid="ab-none"]').exists()).toBe(false)
    await w.find('[data-testid="ab-retry"]').trigger('click')
    expect(h.fetchUnread).toHaveBeenCalled()
    w.unmount()
  })

  it("an admin's alert chip: a count from vmalert's alerts, never 'No alerts' over a failed read; a press opens them", async () => {
    h.auth.isAdmin = true
    h.auth.user = { admin_platform: true }
    h.alerts.state = 'unreadable'
    h.alerts.reason = 'http:503'
    const w = mount(AnnouncementBar, opts)
    expect(h.acquire).toHaveBeenCalledTimes(1)
    const chip = () => w.find('[data-testid="ab-alerts"]')
    expect(chip().text()).toContain('Alerts unreadable')
    expect(chip().attributes('data-tone')).toBe('amber')
    await chip().trigger('click')
    expect(h.refresh).toHaveBeenCalled()                       // an unreadable read: the press retries it
    h.alerts.state = 'ok'
    h.alerts.counts = { firing: 2, pending: 0, page: 0, critical: 1, warning: 1, info: 0 }
    await flushPromises()
    expect(chip().text()).toContain('2 alerts firing')
    expect(chip().attributes('data-tone')).toBe('red')
    await chip().trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/health-monitor', query: { tab: 'prometheus' } })
    w.unmount()
  })

  it('D6-837: an admin without admin_platform (treasury only) is not asked the alerts the route refuses them', async () => {
    h.auth.isAdmin = true
    h.auth.user = { admin_treasury: true }
    const w = mount(AnnouncementBar, opts)
    await flushPromises()
    expect(h.acquire).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ab-alerts"]').exists()).toBe(false)
    w.unmount()
    // control: the legacy super-flag reads them
    h.auth.user = { is_admin: true }
    const w2 = mount(AnnouncementBar, opts)
    expect(h.acquire).toHaveBeenCalledTimes(1)
    w2.unmount()
  })

  it('a person who is not an admin gets no chip and no alert read', async () => {
    h.alerts.state = 'loading'
    const w = mount(AnnouncementBar, opts)
    expect(w.find('[data-testid="ab-alerts"]').exists()).toBe(false)
    expect(h.acquire).not.toHaveBeenCalled()
    w.unmount()
  })
})
