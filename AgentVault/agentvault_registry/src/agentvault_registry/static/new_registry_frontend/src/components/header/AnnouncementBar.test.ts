import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §ALERTS header strip (2026-10-06): the announcement bar, the still alternative to the LED ticker (Settings >
 * Preferences > Header strip). It reads the bell's store, opens a broadcast in the bell's modal, marks it read, rotates
 * several, says a failed read failed, and for an admin carries the alert chip.
 */
const h = vi.hoisted(() => ({
  n: null as any, auth: null as any, alerts: null as any,
  push: vi.fn(), fetchUnread: vi.fn(), markRead: vi.fn(), acquire: vi.fn(), refresh: vi.fn(), publicRead: vi.fn(),
}))
vi.mock('@/stores/notifications', async () => {
  const { reactive } = await import('vue')
  h.n = reactive({ items: [] as any[], unreadFailed: false, lastReadAt: 0, loading: false,
                   fetchUnread: h.fetchUnread, markRead: h.markRead })
  return { useNotificationStore: () => h.n }
})
vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  h.auth = reactive({ isAdmin: false, isAuthenticated: true, user: null as Record<string, unknown> | null })
  return { useAuthStore: () => h.auth }
})
vi.mock('@/services/header/activeAlerts', async () => {
  const { reactive } = await import('vue')
  h.alerts = reactive({ state: 'loading', alerts: [], counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 },
                        withheldSandbox: 0, reason: null, readAt: 0 })
  return { activeAlerts: h.alerts, acquireActiveAlerts: h.acquire, refreshActiveAlerts: h.refresh }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
// V0664: a guest's bar reads the public announcements (GET /public/announcements); a member's never does
vi.mock('@/services/announcements/publicAnnouncements', () => ({ fetchPublicAnnouncements: h.publicRead }))

import AnnouncementBar from './AnnouncementBar.vue'

const opts = { global: { stubs: { Icon: true } } }
const b = (id: number, type: string, created: string, title: string) => ({ id, title, body: `body ${id}`, broadcast_type: type, created_at: created })

describe('the announcement bar', () => {
  beforeEach(() => {
    h.n.items = []; h.n.unreadFailed = false; h.n.lastReadAt = 0
    h.auth.isAdmin = false
    h.auth.isAuthenticated = true
    h.auth.user = null
    Object.assign(h.alerts, { state: 'loading', reason: null, counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 } })
    h.push.mockReset(); h.fetchUnread.mockReset(); h.markRead.mockReset(); h.refresh.mockReset()
    h.publicRead.mockReset().mockResolvedValue([])
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

  // V0662 console polish, item 1: a guest has no unread read, so the bar said "Reading broadcasts..." forever
  // (V0664: with none public that still holds; with some, see below)
  it('a guest with nothing public sees no bar at all: no "reading", no broadcast cached from another session', async () => {
    h.auth.isAuthenticated = false
    h.n.items = [b(2, 'critical', '2026-10-06T08:00:00Z', 'Disk')]
    const w = mount(AnnouncementBar, opts)
    try {                                                    // a failed assertion must not leave it mounted for the next test
      await flushPromises()
      expect(w.find('[data-testid="announcement-bar"]').exists()).toBe(false)
      expect(w.text()).not.toMatch(/Reading|Disk/)
    } finally { w.unmount() }
  })

  // V0664 (gwo_1b3e2cc74c1afec6c6cedc3d, session-lead seq 3706): the bar's guest branch showed nothing "because none is public";
  // some can be now, and the bar shows a guest the public announcements as it shows a member theirs
  const pub = (id: number, type: string, created: string, title: string) =>
    ({ id, title, body: `public body ${id}`, type, createdAt: created, cta: null })

  it('a guest sees the public announcements, the most urgent first, and never what a member had cached', async () => {
    h.auth.isAuthenticated = false
    h.n.items = [b(9, 'critical', '2026-10-06T08:00:00Z', 'Member only')]
    h.publicRead.mockResolvedValue([pub(1, 'info', '2026-10-06T09:00:00Z', 'Release V0664'), pub(2, 'maintenance', '2026-10-05T09:00:00Z', 'Window on Saturday')])
    const w = mount(AnnouncementBar, opts)
    try {
      await flushPromises()
      expect(h.publicRead).toHaveBeenCalledTimes(1)
      expect(w.find('[data-testid="announcement-bar"]').exists()).toBe(true)
      expect(w.find('[data-testid="ab-title"]').text()).toBe('Window on Saturday')
      expect(w.find('[data-testid="ab-count"]').text()).toBe('1/2')
      expect(w.text()).not.toMatch(/Member only|Reading/)
    } finally { w.unmount() }
  })

  it('a press on a guest\'s announcement opens the Announcements page, not the bell; a guest has nothing to mark read', async () => {
    h.auth.isAuthenticated = false
    h.publicRead.mockResolvedValue([pub(1, 'info', '2026-10-06T09:00:00Z', 'Release V0664')])
    const w = mount(AnnouncementBar, opts)
    try {
      await flushPromises()
      const seen: unknown[] = []
      const listener = (e: Event) => seen.push((e as CustomEvent).detail)
      window.addEventListener('theprotocol:open-notification-bell', listener)
      await w.find('[data-testid="ab-open"]').trigger('click')
      window.removeEventListener('theprotocol:open-notification-bell', listener)
      expect(seen).toEqual([])
      expect(h.push).toHaveBeenCalledWith('/announcements')
      expect(w.find('[data-testid="ab-mark-read"]').exists()).toBe(false)
    } finally { w.unmount() }
  })

  it('a guest whose read failed sees no bar, and a signed-in person never asks for the public ones', async () => {
    h.auth.isAuthenticated = false
    h.publicRead.mockRejectedValue(new Error('down'))
    const g = mount(AnnouncementBar, opts)
    try {
      await flushPromises()
      expect(g.find('[data-testid="announcement-bar"]').exists()).toBe(false)
    } finally { g.unmount() }
    h.publicRead.mockReset().mockResolvedValue([pub(1, 'info', '2026-10-06T09:00:00Z', 'Release V0664')])
    h.auth.isAuthenticated = true
    h.n.lastReadAt = Date.now()
    const m = mount(AnnouncementBar, opts)
    try {
      await flushPromises()
      expect(h.publicRead).not.toHaveBeenCalled()
      expect(m.text()).not.toContain('Release V0664')
    } finally { m.unmount() }
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
