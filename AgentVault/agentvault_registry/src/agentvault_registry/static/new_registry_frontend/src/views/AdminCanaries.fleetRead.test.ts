/**
 * §FESUITE (V0578): the canary page's fleet bar (FLEET SCHEDULER: PAUSED / SCHEDULING and the fleet kill switch) came
 * from /admin/canary/fleet/status, whose failure was swallowed as if the endpoint were absent: the bar vanished, the look
 * of a registry with no fleet cockpit, so an operator could not see that the canary fleet (which moves real currency) was
 * paused; a later failed read kept the old PAUSED or SCHEDULING as if it were current. Only a 404 (a build without the
 * endpoint) means "no cockpit" now; any other failure says the fleet state could not be read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ fleet: vi.fn(), refetch: null as null | (() => Promise<void>) }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: (url: string) => (url === '/admin/canary/fleet/status' ? h.fleet() : Promise.resolve({ data: {
      summary: { active_paths: 2, total_paths: 3, pass_rate_24h: 100, passes_24h: 40, failures_24h: 0, pending_count: 0, tests_per_minute_5m: 0.5 },
      paths: [], agents: [], recent_failures: [],
    } })),
    post: vi.fn(),
  },
}))
vi.mock('@/composables/usePolledData', async () => {
  const { ref } = await import('vue')
  return {
    // the fetcher runs once, as `immediate` does; no timers
    usePolledData: (fn: () => Promise<unknown>) => {
      const data = ref<unknown>(null); const loading = ref(false); const lastFetchAt = ref<Date | null>(null)
      const run = async () => { loading.value = true; try { data.value = await fn(); lastFetchAt.value = new Date() } catch { /* the page's error */ } finally { loading.value = false } }
      void run()
      h.refetch = run   // the page's next refresh, run by the test
      return { data, loading, lastFetchAt, refetch: run, pause() {}, resume() {} }
    },
  }
})
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))

import AdminCanaries from './AdminCanaries.vue'

const fleet = (paused: boolean) => ({
  mode: 'master', fleet_paused: paused, paused_at: null, local_paths: { active: 2, total: 3 },
  remote_paths: [{ path_id: 'r1', home_registry: 'asia', interval_sec: 1800, is_active: true, notes: null, last_dispatch: null }],
  dispatch_24h_by_home: {},
})
const status = (code: number) => new AxiosError(`Request failed with status code ${code}`, code >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST',
  undefined, undefined, { status: code, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper
async function page() {
  w = mount(AdminCanaries, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 6; i++) await flushPromises()
  return w
}

describe("the canary page's fleet scheduler state", () => {
  beforeEach(() => { h.fleet.mockReset() })

  it('a failed fleet read is said, never the page of a registry without a fleet cockpit', async () => {
    h.fleet.mockRejectedValue(status(502))
    await page()
    expect(w.find('.cn-stats-row').exists(), 'the status read should have answered').toBe(true)
    expect(w.find('[data-testid="cn-fleet-unread"]').exists(),
      'a failed fleet read drew the page of a registry with no fleet cockpit').toBe(true)
  })

  it('a later failed fleet read says the PAUSED shown is from the last read', async () => {
    h.fleet.mockResolvedValueOnce({ data: fleet(true) })
    await page()
    expect(w.find('[data-testid="cn-fleet-cockpit"]').text()).toContain('PAUSED')
    expect(w.find('[data-testid="cn-fleet-unread"]').exists()).toBe(false)
    // the fleet is read again on the page's next refresh, and that read fails
    h.fleet.mockRejectedValueOnce(status(503))
    await h.refetch!()
    for (let i = 0; i < 6; i++) await flushPromises()
    expect(w.find('[data-testid="cn-fleet-unread"]').exists(), 'a failed re-read kept PAUSED as current, saying nothing').toBe(true)
  })

  it('a 404 (a build without the endpoint) shows neither the bar nor a notice', async () => {
    h.fleet.mockRejectedValue(status(404))
    await page()
    expect(w.find('[data-testid="cn-fleet-cockpit"]').exists()).toBe(false)
    expect(w.find('[data-testid="cn-fleet-unread"]').exists()).toBe(false)
  })
})
