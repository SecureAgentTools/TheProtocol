import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from './__fixtures__/quantumWorkload.json'

/**
 * V0660 (e): the quantum card. It renders only where the frame serves quantum workloads (the registry-config's
 * quantum_workloads block), reads the agent's extension through GET /api/v1/quantum/agents/{did}, and draws only the
 * couplings the card states. Under off it renders nothing and asks nothing.
 */
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { ref, computed } = await import('vue')
  const cfg = ref<Record<string, any>>({})
  return { ...(await importOriginal<object>()), useRegistryConfig: () => ({ config: computed(() => cfg.value) }), __cfg: cfg }
})

import * as rc from '@/composables/useRegistryConfig'
import QuantumCard from './QuantumCard.vue'
import QuantumFilters from './QuantumFilters.vue'
import { _resetQuantumReads } from '@/services/api/quantum'
import { emptyQuantumFilters } from '@/services/quantum/quantumCard'

const cfg = (rc as any).__cfg
const fetchMock = vi.fn()

function answer(status: number, body: unknown) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) })
}

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset()
  ;(globalThis as any).fetch = fetchMock
  cfg.value = {}
})
afterEach(() => { cfg.value = {} })

describe('under off the card is not there and nothing is asked', () => {
  it('no block in the registry-config: no element, no request (every variant)', async () => {
    for (const variant of ['full', 'tile', 'chat'] as const) {
      const w = mount(QuantumCard, { props: { did: fx.did, variant, facets: fx.discoverItemFacets as any, params: fx.extension.params } })
      await flushPromises()
      expect(w.find('[data-testid="qc-card"]').exists(), variant).toBe(false)
      expect(w.html(), variant).toBe('<!--v-if-->')
      w.unmount()
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('a block that says off is off too (an older or a wrong value is not served)', async () => {
    cfg.value = { quantum_workloads: { status: 'off' } }
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('the filters are not there either', () => {
    const w = mount(QuantumFilters, { props: { modelValue: emptyQuantumFilters(), facets: fx.discoverFacets as any } })
    expect(w.find('[data-testid="disc-quantum-filters"]').exists()).toBe(false)
  })
})

describe('where the frame serves the extension', () => {
  beforeEach(() => { cfg.value = { quantum_workloads: fx.registryBlock } })

  it('the agent page reads the route once and shows the lattice, the device facts, the rungs and the receipts', async () => {
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/api/v1/quantum/agents/${encodeURIComponent(fx.did)}`)
    const card = w.find('[data-testid="qc-card"]')
    expect(card.attributes('data-variant')).toBe('full')
    expect(w.find('[data-testid="qc-check"]').attributes('data-check')).toBe('ok')
    // the first backend: all-to-all, 32 qubits; the pairs are past the drawing cap, and the note says so
    expect(w.find('[data-testid="qc-lattice"]').attributes('data-source')).toBe('complete')
    expect(w.find('[data-testid="qc-lattice-note"]').text()).toContain('every pair is coupled')
    const facts = w.findAll('[data-testid="qc-fact"]').map((f) => f.attributes('data-fact'))
    expect(facts).toEqual(expect.arrayContaining(['kind', 'operator', 'location', 'qubits', 'topology', 'gates', 'formats', 'limits', 'queue']))
    expect(w.find('[data-fact="kind"]').text()).toContain('read 3 h ago')
    const rungs = w.findAll('[data-testid="qc-rung"]').map((r) => [r.attributes('data-rung'), r.attributes('data-state')])
    expect(rungs).toEqual([['1', 'settles_here'], ['2', 'settles_here'], ['3', 'claims_only']])
    expect(w.find('[data-testid="qc-rungs"]').text()).toContain('false accept 1%')
    expect(w.find('[data-testid="qc-receipt"]').text()).toContain('Ed25519')
    expect(w.find('[data-testid="qc-receipts"]').text()).toContain('accurateResourceUsagePolicy/v2.0.0')
  })

  it('the receipts line states what the registry\'s block names, and claims no settlement of a receipt', async () => {
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    const text = w.find('[data-testid="qc-receipts"]').text()
    expect(text).toContain('This registry names receipts of schema 1.0, signed with EdDSA.')
    expect(text).not.toMatch(/settles receipts/)
  })

  it('a price per second on simulators says simulator second, never QPU second', async () => {
    const params = { ...fx.extension.params, pricing: { ...fx.extension.params.pricing, model: 'per_second', unit: 'second' } }
    fetchMock.mockImplementation(() => answer(200, { ...fx.read, params }))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params } })
    await flushPromises()
    const text = w.find('[data-testid="qc-receipts"]').text()
    expect(text).toContain('Priced per simulator second.')
    expect(text).not.toContain('QPU')
  })

  it('the heavy-hex backend: a coupling map published only as a digest is said so, and no coupling is drawn', async () => {
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    const tabs = w.findAll('[data-testid="qc-backend-tab"]')
    expect(tabs).toHaveLength(2)
    await tabs[1].trigger('click')
    const svg = w.find('[data-testid="qc-lattice"]')
    expect(svg.attributes('data-source')).toBe('digest')
    expect(svg.attributes('data-edges')).toBe('0')
    expect(svg.findAll('line')).toHaveLength(0)
    expect(svg.findAll('path')).toHaveLength(27)
    const note = w.find('[data-testid="qc-lattice-note"]').text()
    expect(note).toContain('published only as a digest')
    expect(note).toContain('no coupling is drawn')
    expect(note).toContain('28 couplings')
    expect(w.find('[data-fact="calibration"]').text()).toContain('2q error 0.8%')
  })

  it('a registry check with problems says how many, and shadow says shadow', async () => {
    fetchMock.mockImplementation(() => answer(200, { ...fx.read, check: { valid: false, problems: ['a', 'b'], mode: 'shadow' } }))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    const c = w.find('[data-testid="qc-check"]')
    expect(c.attributes('data-check')).toBe('bad')
    expect(c.text()).toContain('2 problems')
    expect(c.text()).toContain('(shadow)')
  })

  it('a failed read keeps the card\'s own facts and says it was not checked; the next mount reads again', async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new Error('down')))
    const w = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    expect(w.find('[data-testid="qc-check"]').attributes('data-check')).toBe('unread')
    expect(w.find('[data-testid="qc-lattice"]').exists()).toBe(true)
    w.unmount()
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const w2 = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(w2.find('[data-testid="qc-check"]').attributes('data-check')).toBe('ok')
  })

  it('a chat card stays an ordinary agent card for an agent without the extension (404), and shows the quantum card for one with it', async () => {
    fetchMock.mockImplementationOnce(() => answer(404, { detail: 'no_quantum_workload' }))
    const none = mount(QuantumCard, { props: { did: 'did:theprotocol:plain', variant: 'chat' } })
    await flushPromises()
    expect(none.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(none.emitted('state')?.slice(-1)[0]).toEqual(['none'])
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const q = mount(QuantumCard, { props: { did: fx.did, variant: 'chat' } })
    await flushPromises()
    expect(q.find('[data-testid="qc-card"]').attributes('data-variant')).toBe('chat')
    expect(q.find('[data-testid="qc-summary"]').text()).toContain('up to 32 qubits')
    expect(q.findAll('[data-testid="qc-rung"]')).toHaveLength(3)
  })

  it('the same agent in a grid, on its page and in a thread costs one request', async () => {
    fetchMock.mockImplementation(() => answer(200, fx.read))
    const a = mount(QuantumCard, { props: { did: fx.did, variant: 'full', params: fx.extension.params } })
    const b = mount(QuantumCard, { props: { did: fx.did, variant: 'chat' } })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    a.unmount(); b.unmount()
  })

  it('the filters: one group with the registry\'s facets, each choice sent up as a change', async () => {
    const w = mount(QuantumFilters, { props: { modelValue: emptyQuantumFilters(), facets: fx.discoverFacets as any } })
    expect(w.find('[data-testid="disc-quantum-filters"]').exists()).toBe(true)
    const modality = w.find('[data-testid="qf-modality"]')
    expect(modality.findAll('option').map((o) => o.attributes('value'))).toEqual(['', 'simulator', 'superconducting'])
    await modality.setValue('superconducting')
    expect(w.emitted('update:modelValue')?.slice(-1)[0]?.[0]).toMatchObject({ modality: 'superconducting' })
    expect(w.emitted('change')).toHaveLength(1)
    for (const k of ['kind', 'format', 'jurisdiction', 'rung', 'role', 'min_qubits', 'only']) {
      expect(w.find(`[data-testid="qf-${k}"]`).exists(), k).toBe(true)
    }
  })
})
