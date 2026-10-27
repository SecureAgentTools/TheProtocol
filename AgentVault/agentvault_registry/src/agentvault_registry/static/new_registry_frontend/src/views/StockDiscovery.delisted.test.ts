/**
 * §COCKPITDESK (2026-10-15): a delisted listing is no market. sbx-alpha lists 171 delisted test listings among 179; the
 * page drew each as a live card ("Trade on the Desk", a launch) and counted them in its totals. They are left out by
 * default, counted aside, and shown on request with DELISTED and nothing to press.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ get: vi.fn(), index: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: { index: h.index } }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, name: 'stocks' }),
  useRouter: () => ({ push: vi.fn(async () => {}), replace: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ availableAgents: [], activeAgent: null, fetchAvailableAgents: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))
vi.mock('@/composables/useWatchAlerts', async () => {
  const { ref } = await import('vue')
  return {
    // the page reads firedBanner, starred and watchSyncNote as refs (wa.x.value in the template)
    useWatchAlerts: () => ({
      loadWatch: vi.fn(async () => {}), loadAlerts: vi.fn(async () => {}), sweep: vi.fn(), toggleStar: vi.fn(),
      isStarred: () => false, watchKey: () => '', starred: ref([]), firedBanner: ref([]), dismissFired: vi.fn(), watchSyncNote: ref(''),
    }),
  }
})

import StockDiscovery from './StockDiscovery.vue'

const L = (symbol: string, status: string) => ({ symbol, display_name: symbol, status, market_cap: '1000', volume_24h_notional: '0' })
const VENUES = [{ venue: 'alpha', currency: 'SBXA', listings: [L('LIVE1', 'trading'), L('DEAD1', 'delisted'), L('DEAD2', 'delisted')] },
                { venue: 'beta', currency: 'SBXB', listings: [L('LIVE2', 'trading'), L('DEAD3', 'delisted')] }]

async function page() {
  const w = mount(StockDiscovery, { global: { stubs: { Sparkline: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const symbols = (w: any) => w.findAll('.sd-card .sd-sym').map((e: any) => e.text().replace(/^\$/, ''))

describe('delisted listings on the AGORA listings page', () => {
  beforeEach(() => {
    h.get.mockReset(); h.index.mockReset()
    h.index.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    h.get.mockImplementation(async (url: string) => {
      if (url === '/agora/federation-tickers') return { data: { venues: VENUES } }
      if (url === '/agora/network-listings' || url === '/agora/listings') return { data: { listings: [] } }
      throw new AxiosError('Network Error', 'ERR_NETWORK')
    })
  })

  it('counts and shows only the live ones, and says how many it left out', async () => {
    const w = await page()
    expect(w.find('[data-testid="sd-listings-count"]').text()).toBe('2')
    expect(w.text()).toContain('3 delisted not counted')
    expect(symbols(w).sort()).toEqual(['LIVE1', 'LIVE2'])
    expect(w.find('[data-testid="sd-show-delisted"]').text()).toBe('Show 3 delisted')
    w.unmount()
  })

  it('shows them on request, each DELISTED with nothing to trade', async () => {
    const w = await page()
    await w.find('[data-testid="sd-show-delisted"]').trigger('click')
    expect(symbols(w).sort()).toEqual(['DEAD1', 'DEAD2', 'DEAD3', 'LIVE1', 'LIVE2'])
    const dead = w.findAll('.sd-card').filter((c: any) => c.find('[data-testid="sd-delisted"]').exists())
    expect(dead).toHaveLength(3)
    for (const c of dead) {
      expect(c.text()).not.toContain('Trade on the Desk')
      expect(c.text()).not.toContain('Passport Buy')
      expect(c.find('.sd-ipo-meta').exists()).toBe(false)
    }
    expect(w.find('[data-testid="sd-listings-count"]').text(), 'the count stays the live one').toBe('2')
    w.unmount()
  })
})
