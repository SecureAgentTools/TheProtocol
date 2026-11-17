import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from './__fixtures__/quantumWorkload.json'

/**
 * V0662 console polish, item 6: the agent page's quantum card shows when each backend is available, its windows in UTC
 * and when they were read, beside the other facts. Red on f569f6a6e: no availability fact.
 */
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { ref, computed } = await import('vue')
  const cfg = ref<Record<string, any>>({})
  return { ...(await importOriginal<object>()), useRegistryConfig: () => ({ config: computed(() => cfg.value) }), __cfg: cfg }
})

import * as rc from '@/composables/useRegistryConfig'
import QuantumCard from './QuantumCard.vue'
import { _resetQuantumReads } from '@/services/api/quantum'

const cfg = (rc as any).__cfg
const fetchMock = vi.fn()
const answer = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset()
  ;(globalThis as any).fetch = fetchMock
  cfg.value = { quantum_workloads: fx.registryBlock }
})
afterEach(() => { cfg.value = {} })

describe('the quantum card\'s availability', () => {
  it('the backend\'s windows in UTC, with when they were read', async () => {
    fetchMock.mockImplementation(() => answer(fx.read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    const f = w.find('[data-fact="availability"]')
    expect(f.exists()).toBe(true)
    expect(f.text()).toContain('every day 00:00–23:59 UTC')
    expect(f.text()).toContain('read 3 h ago')
  })

  it('an overnight window says it runs into the next day; several windows are all shown', async () => {
    const read = JSON.parse(JSON.stringify(fx.read))
    read.params.backends[0].availability.windows = [
      { days: 'weekdays', start_utc: '22:00', end_utc: '06:00' },
      { days: 'saturday', start_utc: '09:00', end_utc: '12:30' },
    ]
    fetchMock.mockImplementation(() => answer(read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: read.params } })
    await flushPromises()
    const text = w.find('[data-fact="availability"]').text()
    expect(text).toContain('weekdays 22:00–06:00 UTC (into the next day)')
    expect(text).toContain('Saturday 09:00–12:30 UTC')
  })

  it('a backend whose card states no availability shows no such fact', async () => {
    const read = JSON.parse(JSON.stringify(fx.read))
    delete read.params.backends[0].availability
    fetchMock.mockImplementation(() => answer(read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: read.params } })
    await flushPromises()
    expect(w.find('[data-testid="qc-facts"]').exists()).toBe(true)
    expect(w.find('[data-fact="availability"]').exists()).toBe(false)
  })
})
