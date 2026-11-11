import { describe, it, expect } from 'vitest'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'
import {
  COMPLETE_EDGE_CAP, LATTICE_NODE_CAP, ageOf, backendTimeKind, asDiscoverFacets, asFacets, emptyQuantumFilters, latticeFor, percent,
  quantumFiltersActive, quantumParams, quantumQuery, quantumServed, receiptFacts, rungRows, shortDigest,
} from './quantumCard'

/**
 * V0660 (e): the quantum card's brain. The fixtures are V0660 (a)'s schema example (the same bytes the registry, the
 * spec and the SDK carry), its read route's answer and V0660 (d)'s registry-config block.
 */
const [statevector, heavyHex] = fx.extension.params.backends

describe('the frame serves quantum workloads only where its block says shadow or on', () => {
  it('on and shadow serve; off, a missing block, an unknown status and a failed read do not', () => {
    expect(quantumServed({ status: 'on' })).toBe(true)
    expect(quantumServed({ status: 'shadow' })).toBe(true)
    expect(quantumServed({ status: 'off' })).toBe(false)
    expect(quantumServed(undefined)).toBe(false)
    expect(quantumServed(null)).toBe(false)
    expect(quantumServed({ status: 'enforce' })).toBe(false)
    expect(quantumServed({})).toBe(false)
  })
})

describe('the extension is read from the card\'s top-level extensions[] only', () => {
  it('finds the params beside the payment extension', () => {
    expect(quantumParams(fx.cardData)).toEqual(fx.extension.params)
  })
  it('a card with none, or one only under capabilities.extensions, has none', () => {
    expect(quantumParams({ extensions: [] })).toBeNull()
    expect(quantumParams({ capabilities: { extensions: [fx.extension] } })).toBeNull()
    expect(quantumParams(null)).toBeNull()
  })
})

describe('the lattice draws only the couplings the card states', () => {
  it('all-to-all: every pair of the 32 qubits is coupled; past the cap the pairs are not drawn, and it says so', () => {
    const l = latticeFor(statevector)
    expect(l.source).toBe('complete')
    expect(l.qubits).toBe(32)
    expect(l.edgeCount).toBe(496)
    expect(32).toBeGreaterThan(COMPLETE_EDGE_CAP)
    expect(l.edgesDrawn).toBe(false)
    expect(l.edges).toEqual([])
    expect(l.nodes).toHaveLength(32)
  })
  it('all-to-all with few qubits draws n(n-1)/2 lines, each pair once', () => {
    const l = latticeFor({ ...statevector, qubits: { physical: 5 } })
    expect(l.edgesDrawn).toBe(true)
    expect(l.edges).toHaveLength(10)
    expect(new Set(l.edges.map(([a, b]) => `${a}-${b}`)).size).toBe(10)
    expect(l.edges.every(([a, b]) => a < b && b < 5)).toBe(true)
  })
  it('a coupling map published as a digest gives no edge at all: heavy-hex is never guessed from its name', () => {
    const l = latticeFor(heavyHex)
    expect(l.source).toBe('digest')
    expect(l.topology).toBe('heavy-hex')
    expect(l.edges).toEqual([])
    expect(l.edgesDrawn).toBe(false)
    expect(l.edgeCount).toBe(28)
    expect(l.digest).toBe(heavyHex.connectivity.coupling_map?.digest)
    expect(l.nodes).toHaveLength(27)
  })
  it('a named topology with no coupling map draws points only', () => {
    const l = latticeFor({ qubits: { physical: 8 }, connectivity: { topology: 'linear' } })
    expect(l.source).toBe('none')
    expect(l.edges).toEqual([])
  })
  it('draws at most the cap of points and keeps the stated count', () => {
    const l = latticeFor({ qubits: { physical: 1000 }, connectivity: { topology: 'square', coupling_map: { digest: 'sha256:' + 'a'.repeat(64), url: 'https://x.example/c' } } })
    expect(l.qubits).toBe(1000)
    expect(l.drawn).toBe(LATTICE_NODE_CAP)
    expect(l.nodes).toHaveLength(LATTICE_NODE_CAP)
    expect(l.nodes.every((p) => p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1)).toBe(true)
  })
  it('a value of the wrong type is left out, never guessed', () => {
    const l = latticeFor({ qubits: { physical: '27' }, connectivity: { topology: 'all-to-all' } })
    expect(l.qubits).toBe(0)
    expect(l.nodes).toEqual([])
    expect(l.edges).toEqual([])
  })
})

describe('the rungs a buyer can get', () => {
  it('rung 1 and 2 settle here through the rails the registry names; rung 3 is signed claims only', () => {
    const rows = rungRows(fx.extension.params, fx.registryBlock)
    expect(rows.map((r) => [r.rung, r.state])).toEqual([[1, 'settles_here'], [2, 'settles_here'], [3, 'claims_only']])
    expect(rows[0].rails).toEqual(['guild_work_order', 'contract_milestone'])
    expect(rows[1].tests).toEqual([{ template: 'test-circuits/v1.0', method: 'test_circuits', falseAccept: '1%', falseReject: '5%' }])
  })
  it('where the registry settles no rung (no rail), the agent still offers it, and the card says this registry settles none', () => {
    const rows = rungRows(fx.extension.params, { status: 'shadow', acceptance_tests: { rungs: [], settled_through: [] } })
    expect(rows.map((r) => r.state)).toEqual(['offered', 'offered', 'claims_only'])
    expect(rows.every((r) => r.rails.length === 0)).toBe(true)
  })
  it('a rung the card does not list is not a row, whatever the registry settles', () => {
    const p = { evidence: { verification_rungs: [1], acceptance_tests: [{ template: 'answer-check/v1.0', rung: 1, method: 'answer_check' }] } }
    expect(rungRows(p, fx.registryBlock).map((r) => r.rung)).toEqual([1])
  })
})

describe('the discovery filters', () => {
  it('none set asks nothing: the request is the one before V0660', () => {
    expect(quantumQuery(emptyQuantumFilters())).toEqual({})
    expect(quantumQuery(undefined)).toEqual({})
    expect(quantumFiltersActive(emptyQuantumFilters())).toBe(false)
  })
  it('each set filter becomes its discover parameter, as the registry reads them', () => {
    const q = quantumQuery({ only: true, role: 'provider', kind: 'emulator', modality: 'superconducting', min_qubits: '20',
      format: 'qir', jurisdiction: 'de', rung: '2' })
    expect(q).toEqual({ quantum_only: 'true', quantum_role: 'provider', quantum_kind: 'emulator',
      quantum_modality: 'superconducting', quantum_min_qubits: '20', quantum_format: 'qir',
      quantum_jurisdiction: 'DE', quantum_rung: '2' })
  })
  it('a qubit count that is not a whole number of at least 1, and a rung outside 1 to 3, are not sent', () => {
    expect(quantumQuery({ ...emptyQuantumFilters(), min_qubits: '0' })).toEqual({})
    expect(quantumQuery({ ...emptyQuantumFilters(), min_qubits: '2.5' })).toEqual({})
    expect(quantumQuery({ ...emptyQuantumFilters(), rung: '4' })).toEqual({})
  })
})

describe('the facets and the evidence, read defensively', () => {
  it('the discover item\'s facets and the page\'s facets keep their shape', () => {
    expect(asFacets(fx.discoverItemFacets)).toEqual(fx.discoverItemFacets)
    const d = asDiscoverFacets(fx.discoverFacets)!
    expect(d.total).toBe(1)
    expect(d.rungs.map((r) => r.name)).toEqual(['1', '2', '3'])
    expect(asFacets(null)).toBeNull()
    expect(asDiscoverFacets('x')).toBeNull()
  })
  it('the receipts: the agent\'s signing algorithm, the registry\'s schema, the metering circuit and the data terms', () => {
    const r = receiptFacts(fx.extension.params, fx.registryBlock)
    expect(r).toMatchObject({ schemaVersion: '1.0', signingAlgorithm: 'Ed25519', registrySchema: '1.0',
      registryAlgorithms: ['EdDSA'], meteringCircuit: 'accurateResourceUsagePolicy/v2.0.0', ledgerKeeps: ['hashes', 'verdicts'],
      residency: ['DE'], circuitsDays: 0, resultsDays: 30, pricingModel: 'per_shot', pricingUnit: 'shot' })
  })
  it('numbers read as people read them', () => {
    expect(percent(0.0003)).toBe('0.03%')
    expect(percent(0.008)).toBe('0.8%')
    expect(percent(1.5)).toBeNull()
    expect(ageOf(10800)).toEqual({ n: 3, unit: 'h' })
    expect(ageOf(-5)).toBeNull()
    expect(shortDigest('sha256:5173ee745091c28a0ab35005f6bf560c89f264bc63c0bed892832343712a6a82')).toBe('sha256:5173ee74…2a6a82')
  })
})

describe('a price per second names whose second it is', () => {
  it('every backend a simulator (an emulator is one too): a simulator second, never a QPU second', () => {
    expect(backendTimeKind(fx.extension.params.backends)).toBe('simulator')
    expect(backendTimeKind([{ kind: 'simulator' }])).toBe('simulator')
  })
  it('every backend a QPU: a QPU second', () => {
    expect(backendTimeKind([{ kind: 'qpu' }, { kind: 'qpu' }])).toBe('qpu')
  })
  it('a mix, an unknown kind or no backend at all: a neutral second of backend time', () => {
    expect(backendTimeKind([{ kind: 'qpu' }, { kind: 'simulator' }])).toBe('backend')
    expect(backendTimeKind([{ kind: 'annealer-ish' }])).toBe('backend')
    expect(backendTimeKind([])).toBe('backend')
    expect(backendTimeKind(null)).toBe('backend')
  })
})
