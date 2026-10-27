/**
 * §FESUITE (2026-10-09): the AGORA listings page (/agora/listings) drew its header, "N MARKETS LIVE" with a green pulsing
 * dot, whenever it was not loading: over a federation-tickers read that failed it said "0 MARKETS LIVE" right above its own
 * "The markets could not be read just now." (met reading the recovery sweep on V0587). A count over a read that never
 * answered is not a count. The page, the registry's answers given per test.
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

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const venue = (name: string) => ({ venue: name, currency: 'SBXB', listings: [{ symbol: `${name}X`, display_name: name, status: 'trading' }] })

async function page() {
  const w = mount(StockDiscovery, { global: { stubs: { Sparkline: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe('the AGORA listings header counts only markets it read', () => {
  beforeEach(() => {
    h.get.mockReset()
    h.index.mockReset()
    h.index.mockRejectedValue(noAnswer())
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says no count over a failed read (it said "0 MARKETS LIVE" above "could not be read")', async () => {
    h.get.mockRejectedValue(noAnswer())
    const w = await page()
    expect(w.find('[data-testid="read-failed"]').exists(), 'the page says its read failed').toBe(true)
    // the header element itself (the page's text runs "...LIVEThe markets could not be read", so a word boundary on the
    // whole text cannot see it)
    expect(w.find('.sd-live').exists(), `a count over a read that never answered: "${w.find('.sd-live').exists() ? w.find('.sd-live').text() : ''}"`).toBe(false)
    w.unmount()
  })

  it('counts the markets a read answered, an answered empty network included', async () => {
    h.get.mockImplementation(async (url: string) => {
      if (url === '/agora/federation-tickers') return { data: { venues: [venue('alpha'), venue('beta')] } }
      if (url === '/agora/network-listings') return { data: { listings: [] } }
      if (url === '/agora/listings') return { data: { listings: [] } }
      throw noAnswer()
    })
    const w = await page()
    expect(w.find('.sd-live').text()).toBe('2 MARKETS LIVE')
    w.unmount()

    h.get.mockImplementation(async (url: string) => {
      if (url === '/agora/federation-tickers') return { data: { venues: [] } }
      if (url === '/agora/network-listings' || url === '/agora/listings') return { data: { listings: [] } }
      throw noAnswer()
    })
    const w2 = await page()
    expect(w2.find('.sd-live').text(), 'an answered empty network is an honest zero').toBe('0 MARKETS LIVE')
    w2.unmount()
  })
})
