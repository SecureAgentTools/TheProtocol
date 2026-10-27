/**
 * §FESUITE (V0577): Discovery's Firms lane renders only when it has firms. A failed firms read emptied the list, so the
 * lane vanished, which reads as "no firms on this registry", and a voice ask ("hire the firm X", ?firm=X) went silent.
 * The lane now says the read failed and offers it again; a voice ask is matched only against a list that answered, so
 * "No firm here matched" is never said over a failed read. An answered empty list still renders no lane, as before.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ get: vi.fn(), route: { query: {} as Record<string, string> }, replace: vi.fn(async () => {}) }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ push: vi.fn(), replace: h.replace }) }))

import FirmsLane from './FirmsLane.vue'

const FIRM = { org_id: 'o1', slug: 'meridian', name: 'Meridian Ledger Works', verified_jobs: 3, commissioned: 1, stars_n: 0,
  engage_available: false, engage_reason: 'no intake agent' }

async function lane() {
  const w = mount(FirmsLane)
  await flushPromises()
  return w
}

describe("Discovery's Firms lane when the firms read fails", () => {
  beforeEach(() => { h.get.mockReset(); h.replace.mockClear(); h.route = reactive({ query: {} }) })

  it('says the read failed instead of vanishing, and reads again', async () => {
    h.get.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await lane()
    expect(w.find('[data-testid="firms-lane"]').exists(), 'the lane vanished over a failed read').toBe(true)
    const notice = w.find('[data-testid="fl-failed"]')
    expect(notice.exists()).toBe(true)

    h.get.mockResolvedValue({ data: { firms: [FIRM] } })
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="fl-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="fl-firm-meridian"]').exists()).toBe(true)
  })

  it('a voice ask over a failed read is not "No firm here matched"', async () => {
    h.route = reactive({ query: { firm: 'meridian' } })
    h.get.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await lane()
    expect(w.find('[data-testid="fl-firm-miss"]').exists()).toBe(false)
    expect(h.replace, 'the ask was scrubbed from the address before any list answered').not.toHaveBeenCalled()
  })

  it('an answered empty list still renders no lane', async () => {
    h.get.mockResolvedValue({ data: { firms: [] } })
    const w = await lane()
    expect(w.find('[data-testid="firms-lane"]').exists()).toBe(false)
  })
})
