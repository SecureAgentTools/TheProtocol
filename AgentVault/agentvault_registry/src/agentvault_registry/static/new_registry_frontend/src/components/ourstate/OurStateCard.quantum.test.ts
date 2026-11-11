import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'

/**
 * V0660 (e): a shared agent card in a chat thread shows the quantum card when the agent's card carries the quantum
 * workload extension and the frame serves it. Under off the chat card is what it was and nothing is asked; an agent
 * without the extension stays an ordinary agent card.
 */
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { ref, computed } = await import('vue')
  const cfg = ref<Record<string, any>>({})
  // the chat path reads the mode passively (V0660 (e) fix 4): here the config is the one already loaded
  return { ...(await importOriginal<object>()), useRegistryConfig: () => ({ config: computed(() => cfg.value) }),
    peekRegistryConfig: () => ({ config: computed(() => cfg.value) }), __cfg: cfg }
})
import * as rc from '@/composables/useRegistryConfig'
import { _resetQuantumReads } from '@/services/api/quantum'
import OurStateCard from './OurStateCard.vue'

const cfg = (rc as any).__cfg
const fetchMock = vi.fn()
const card = (did: string) => ({ v: 1, type: 'agent.card', data: { did, name: 'Lattice Works' } })
const served = () => fetchMock.mockImplementation(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fx.read) }))
const stubs = { Icon: true, OurStateIdentity: { template: '<div class="ident" />' } }
const quantumCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/v1/quantum/'))

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset()
  ;(globalThis as any).fetch = fetchMock
  cfg.value = {}
})

describe('the chat agent card and the quantum card', () => {
  it('under off: the agent card as before, no quantum request', async () => {
    const w = mount(OurStateCard, { props: { card: card(fx.did) }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="osc-agent.card"]').exists()).toBe(true)
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
  })

  it('served: a quantum agent shows its chat quantum card; a plain agent (404) does not', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    fetchMock.mockImplementation((u: string) => Promise.resolve(String(u).includes(encodeURIComponent(fx.did))
      ? { ok: true, status: 200, json: () => Promise.resolve(fx.read) }
      : { ok: false, status: 404, json: () => Promise.resolve({ detail: 'no_quantum_workload' }) }))
    const q = mount(OurStateCard, { props: { card: card(fx.did) }, global: { stubs } })
    const p = mount(OurStateCard, { props: { card: card('did:theprotocol:plain') }, global: { stubs } })
    await flushPromises()
    expect(q.find('[data-testid="qc-card"]').attributes('data-variant')).toBe('chat')
    expect(p.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(2)
  })

  it('a card not yet accepted (defanged): no quantum read and no quantum card; once the thread is accepted, the card', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    served()
    const w = mount(OurStateCard, { props: { card: card(fx.did), defang: true }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="osc-defanged"]').exists()).toBe(true)
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
    await w.setProps({ defang: false })
    await flushPromises()
    expect(w.find('[data-testid="qc-card"]').attributes('data-variant')).toBe('chat')
    expect(quantumCalls()).toHaveLength(1)
  })
})
