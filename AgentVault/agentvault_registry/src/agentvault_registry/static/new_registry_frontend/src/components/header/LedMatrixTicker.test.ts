import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import tickerSource from './LedMatrixTicker.vue?raw'

/**
 * §ALERTS header strip (2026-10-06): the LED ticker, polished. Its ALERTS mode asked a path that does not exist (a 404
 * per scroll loop, each a global "Not Found" toast, under "NO ALERTS // MONITORING ACTIVE"); its broadcasts came from a
 * second fetch whose failure read "<node> // ONLINE". The board is a canvas, so the text it carries is checked on the
 * live region beside it (led-text), the same words a screen reader gets.
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
vi.mock('@/stores/registryInfo', () => ({ useRegistryInfoStore: () => ({ registryName: 'EU', load: () => Promise.resolve() }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ brandTheme: 'neural' }) }))
vi.mock('@/services/header/activeAlerts', async () => {
  const { reactive } = await import('vue')
  h.alerts = reactive({ state: 'loading', alerts: [] as any[], counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 },
                        withheldSandbox: 0, reason: null, readAt: 0 })
  return { activeAlerts: h.alerts, acquireActiveAlerts: h.acquire, refreshActiveAlerts: h.refresh }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

import LedMatrixTicker from './LedMatrixTicker.vue'

const text = (w: any) => w.find('[data-testid="led-text"]').text()
const broadcast = (id: number, type: string, title: string, body = '') =>
  ({ id, title, body, broadcast_type: type, created_at: '2026-10-06T09:00:00Z' })
const disk = { alertname: 'DiskSpaceCritical', title: 'Disk space critical', severity: 'critical', state: 'firing',
               labels: { device: '/dev/md2' }, active_since: null }

describe('the LED ticker', () => {
  beforeEach(() => {
    try { localStorage.removeItem('theprotocol:ledTickerMode') } catch { /* ignore */ }
    h.n.items = []; h.n.unreadFailed = false; h.n.lastReadAt = 0
    h.auth.isAdmin = false
    h.auth.user = null
    Object.assign(h.alerts, { state: 'loading', alerts: [], reason: null,
                              counts: { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 } })
    h.push.mockReset(); h.fetchUnread.mockReset(); h.refresh.mockReset()
    h.acquire.mockReset().mockReturnValue(() => {})
  })

  it('carries the broadcasts the bell holds, the most urgent first', async () => {
    h.n.lastReadAt = Date.now()
    h.n.items = [broadcast(1, 'info', 'Hello'), broadcast(2, 'critical', 'Disk', 'Free space now')]
    const w = mount(LedMatrixTicker)
    await flushPromises()
    expect(text(w)).toBe('CRITICAL: Disk - Free space now. Hello')
    expect(w.find('[data-testid="led-badge"]').text()).toBe('BROADCASTS 2')
    w.unmount()
  })

  it('says it is reading until the first answer, and a failed read as a failed read (never "<node> // ONLINE")', async () => {
    const w = mount(LedMatrixTicker)
    expect(text(w)).toMatch(/LOADING BROADCASTS/)
    h.n.unreadFailed = true
    await flushPromises()
    expect(text(w)).toMatch(/BROADCASTS COULD NOT BE READ/)
    expect(text(w)).not.toMatch(/ONLINE/)
    await w.find('[data-testid="led-board"]').trigger('keydown', { key: 'Enter' })
    expect(h.fetchUnread).toHaveBeenCalled()                   // a press on the failure retries the read
    w.unmount()
  })

  it('a press on a broadcast opens THAT broadcast in the bell', async () => {
    h.n.lastReadAt = Date.now()
    h.n.items = [broadcast(9, 'warning', 'Maintenance')]
    const w = mount(LedMatrixTicker)
    await flushPromises()
    const seen: any[] = []
    const listener = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener('theprotocol:open-notification-bell', listener)
    await w.find('[data-testid="led-board"]').trigger('keydown', { key: 'Enter' })
    window.removeEventListener('theprotocol:open-notification-bell', listener)
    expect(seen).toEqual([{ broadcastId: 9 }])
    w.unmount()
  })

  it('someone who is not an admin has no alerts mode, no switch and no alert read', async () => {
    try { localStorage.setItem('theprotocol:ledTickerMode', 'alerts') } catch { /* ignore */ }
    h.n.lastReadAt = Date.now()
    const w = mount(LedMatrixTicker)
    await flushPromises()
    expect(w.find('[data-testid="led-ticker"]').attributes('data-mode')).toBe('broadcasts')
    expect(w.find('[data-testid="led-badge"]').element.tagName).toBe('SPAN')
    expect(h.acquire).not.toHaveBeenCalled()
    w.unmount()
  })

  it("an admin switches to the alerts with the badge: vmalert's alerts, counted", async () => {
    h.auth.isAdmin = true
    h.auth.user = { admin_platform: true }
    h.n.lastReadAt = Date.now()
    h.alerts.state = 'ok'
    h.alerts.alerts = [disk]
    h.alerts.counts = { firing: 1, pending: 0, page: 0, critical: 1, warning: 0, info: 0 }
    const w = mount(LedMatrixTicker)
    await flushPromises()
    expect(h.acquire).toHaveBeenCalledTimes(1)
    // broadcasts mode, but alerts are firing: a red dot on the badge says so
    expect(w.find('[data-testid="led-alert-dot"]').classes()).toContain('led-badge-dot-red')
    await w.find('[data-testid="led-badge"]').trigger('click')
    expect(w.find('[data-testid="led-ticker"]').attributes('data-mode')).toBe('alerts')
    expect(text(w)).toBe('CRITICAL: Disk space critical (/dev/md2)')
    expect(w.find('[data-testid="led-badge"]').text()).toBe('ALERTS 1')
    expect(w.find('[data-testid="led-alert-dot"]').exists()).toBe(false)
    await w.find('[data-testid="led-board"]').trigger('keydown', { key: 'Enter' })
    expect(h.push).toHaveBeenCalledWith({ path: '/health-monitor', query: { tab: 'prometheus' } })
    w.unmount()
  })

  it('D6-837: an admin without admin_platform keeps the broadcasts and is not asked the alerts', async () => {
    h.auth.isAdmin = true
    h.auth.user = { admin_support: true }
    try { localStorage.setItem('theprotocol:ledTickerMode', 'alerts') } catch { /* ignore */ }
    h.n.lastReadAt = Date.now()
    const w = mount(LedMatrixTicker)
    await flushPromises()
    expect(h.acquire).not.toHaveBeenCalled()
    expect(w.find('[data-testid="led-ticker"]').attributes('data-mode')).toBe('broadcasts')
    w.unmount()
  })

  it('an alert read that failed says so, and a press retries it', async () => {
    h.auth.isAdmin = true
    h.auth.user = { is_admin: true }
    try { localStorage.setItem('theprotocol:ledTickerMode', 'alerts') } catch { /* ignore */ }
    h.alerts.state = 'unreadable'
    const w = mount(LedMatrixTicker)
    await flushPromises()
    expect(text(w)).toMatch(/ALERTS COULD NOT BE READ/)
    expect(text(w)).not.toMatch(/NO ALERTS/)
    await w.find('[data-testid="led-board"]').trigger('keydown', { key: 'Enter' })
    expect(h.refresh).toHaveBeenCalled()
    w.unmount()
  })

  it('never asks the api client again (the 404 that raised a global toast every loop)', () => {
    expect(tickerSource).not.toMatch(/apiClient/)
    expect(tickerSource).not.toMatch(/fetch\(\s*['"`]\/api\/v1\/admin\/health/)
  })
})
