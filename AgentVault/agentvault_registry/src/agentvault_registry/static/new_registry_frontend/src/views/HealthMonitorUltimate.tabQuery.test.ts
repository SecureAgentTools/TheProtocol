/**
 * §ALERTS (2026-10-06): the header strip's alert chip opens /health-monitor?tab=prometheus. The tab is read at the first
 * arrival AND when only the query changes while the page is open (vue-router reuses the component then).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn(), route: null as any }))
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ query: {} as Record<string, unknown> })
  return { useRoute: () => h.route, useRouter: () => ({ push: vi.fn() }) }
})
vi.mock('@/services/api/client', () => ({ apiClient: { get: (...a: unknown[]) => h.get(...a) } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ agentToken: null, isAdmin: true }) }))
vi.mock('@/stores/realtime', () => ({ useRealtimeStore: () => ({}) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn() }) }))
vi.mock('chart.js', () => ({ Chart: class { static register() {} destroy() {} }, registerables: [] }))

import HealthMonitorUltimate from './HealthMonitorUltimate.vue'

let w: VueWrapper | null = null
const activeTab = () => w!.find('.hm-tab.active').text()

describe('the Health Monitor opens the tab its address names', () => {
  afterEach(() => { w?.unmount(); w = null; h.route.query = {} })

  it('on the first arrival, and on a query-only change while it is open; an unknown tab changes nothing', async () => {
    h.get.mockRejectedValue(new Error('no backend in this test'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    h.route.query = { tab: 'prometheus' }
    w = mount(HealthMonitorUltimate, { global: { stubs: { Icon: true, Teleport: true } }, attachTo: document.body })
    await flushPromises()
    expect(activeTab()).toContain('Prometheus')
    h.route.query = { tab: 'activity' }
    await flushPromises()
    expect(activeTab()).toContain('Activity')
    h.route.query = { tab: 'nonsense' }
    await flushPromises()
    expect(activeTab()).toContain('Activity')
  })
})
