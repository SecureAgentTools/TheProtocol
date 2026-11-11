import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'

/**
 * V0660 (e), fix 4: a chat card must not add a registry-config read where its host would not make one (a Pocket thread
 * under off). The chat path reads the quantum mode only where the registry-config is already loaded, or where the
 * shared card itself names the quantum workload extension. This file uses the real useRegistryConfig (its module state
 * carries from one test to the next, in order).
 */
import { _resetQuantumReads } from '@/services/api/quantum'
import OurStateCard from './OurStateCard.vue'

const URI = 'https://theprotocol.cloud/extensions/v1/quantum/workload'
const fetchMock = vi.fn()
const stubs = { Icon: true, OurStateIdentity: { template: '<div class="ident" />' } }
const card = (did: string, extra: Record<string, any> = {}) => ({ v: 1, type: 'agent.card', data: { did, name: 'Lattice Works', ...extra } })
const configCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/v1/public/registry-config'))
const quantumCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/v1/quantum/'))

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset().mockImplementation((u: string) => {
    const url = String(u)
    if (url.includes('/api/v1/public/registry-config')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ quantum_workloads: fx.registryBlock }) })
    }
    if (url.includes(encodeURIComponent(fx.did))) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fx.read) })
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: 'no_quantum_workload' }) })
  })
  ;(globalThis as any).fetch = fetchMock
})

describe('the chat card asks for the quantum mode only where it is already known or the card names it', () => {
  it('nothing has read the registry-config (a Pocket thread): an ordinary agent card makes no request at all', async () => {
    const w = mount(OurStateCard, { props: { card: card(fx.did) }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="osc-agent.card"]').exists()).toBe(true)
    expect(configCalls()).toHaveLength(0)
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
  })

  it('a shared card that names the quantum extension reads the mode once, and where it is served shows the card', async () => {
    const w = mount(OurStateCard, { props: { card: card(fx.did, { extensions: [URI] }) }, global: { stubs } })
    await flushPromises()
    expect(configCalls()).toHaveLength(1)
    expect(w.find('[data-testid="qc-card"]').attributes('data-variant')).toBe('chat')
    expect(quantumCalls()).toHaveLength(1)
  })

  it('once the registry-config is loaded, any shared agent card asks the registry (no second config read)', async () => {
    const q = mount(OurStateCard, { props: { card: card(fx.did) }, global: { stubs } })
    const p = mount(OurStateCard, { props: { card: card('did:theprotocol:plain') }, global: { stubs } })
    await flushPromises()
    expect(configCalls()).toHaveLength(0)
    expect(q.find('[data-testid="qc-card"]').exists()).toBe(true)
    expect(p.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(2)
  })
})
