import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

/**
 * §FESUITE (2026-10-05): both component groups said "Nothing probed yet." before the status read answered and over a
 * failed one, under a header that said the rail did not answer. The groups say nothing they did not read; an answered
 * read with an empty group still says so.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: http.get } }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ journalEnabled: ref(false) }) }))

import StatusPage from './StatusPage.vue'

const opts = { global: { stubs: { RouterLink: true, ProtocolMark: true } } }

describe('the status page says what it read', () => {
  beforeEach(() => { http.get.mockReset() })

  it('a failed read says the rail did not answer, and no group says nothing was probed', async () => {
    http.get.mockRejectedValue(new Error('Request failed with status code 502'))
    const w = mount(StatusPage, opts)
    await flushPromises()
    expect(w.find('[data-testid="status-error"]').exists()).toBe(true)
    expect(w.text()).not.toContain('Nothing probed yet.')
    w.unmount()
  })

  it('an answered read with an empty federation group says so', async () => {
    http.get.mockResolvedValue({ data: { components: [{ key: 'registry', name: 'Registry', group: 'core', status: 'up', latency_ms: 12,
      public_url: null, job: 'registry', availability: 1, days_known: 1, days: [] }], incidents: [], measured_dips: [], overall: 'operational',
      checked_at: '2026-10-05T11:00:00Z' } })
    const w = mount(StatusPage, opts)
    await flushPromises()
    expect(w.find('[data-testid="status-none-operator"]').exists()).toBe(true)
    expect(w.find('[data-testid="status-none-core"]').exists()).toBe(false)
    w.unmount()
  })
})
