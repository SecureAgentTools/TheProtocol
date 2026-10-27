/**
 * §ZKV2 (2026-10-13): the v1.0.0 policy circuits are retired (their policy limits were private inputs nothing bound);
 * GET /circuits/ lists them with status "retired" and superseded_by. The views mark them from the list, and by rule
 * when the list was not read.
 */
import { describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: {} }))

import { circuitSuccessor, isRetiredCircuit, type CircuitInfo } from './attestations'

const listed: CircuitInfo[] = [
  { circuit_id: 'fairMarkupPolicy/v2.0.0', name: 'fair_markup', status: 'active', acir_url: '', source_url: '', nargo_toml_url: '',
    vk_url: '/api/v1/circuits/fairMarkupPolicy/v2.0.0/vk', public_inputs: ['max_markup_bps', 'offered_price', 'context'],
    public_outputs: ['cost_commitment'], policy: { max_markup_bps: { rule: 'at_most', limit: 3000 } } },
  { circuit_id: 'fairMarkupPolicy/v1.0.0', name: 'fair_markup', status: 'retired', acir_url: '', source_url: '', nargo_toml_url: '',
    superseded_by: 'fairMarkupPolicy/v2.0.0' },
]

describe('retired circuits', () => {
  it('reads the status the list gives', () => {
    expect(isRetiredCircuit('fairMarkupPolicy/v1.0.0', listed)).toBe(true)
    expect(isRetiredCircuit('fairMarkupPolicy/v2.0.0', listed)).toBe(false)
    expect(circuitSuccessor('fairMarkupPolicy/v1.0.0', listed)).toBe('fairMarkupPolicy/v2.0.0')
    expect(circuitSuccessor('fairMarkupPolicy/v2.0.0', listed)).toBeNull()
  })

  it('without the list: a v1.0.0 policy circuit is retired by rule, everything else is not', () => {
    expect(isRetiredCircuit('contentSafetyAttestation/v1.0.0')).toBe(true)
    expect(circuitSuccessor('contentSafetyAttestation/v1.0.0')).toBe('contentSafetyAttestation/v2.0.0')
    expect(isRetiredCircuit('accurateResourceUsagePolicy/v2.0.0')).toBe(false)
    // proof_of_reputation is not a proof, but it is not a retired v1.0.0 circuit either
    expect(isRetiredCircuit('proof_of_reputation/v1.0')).toBe(false)
    expect(isRetiredCircuit('')).toBe(false)
  })

  it('an entry the list marks active wins over the rule', () => {
    const odd: CircuitInfo[] = [{ circuit_id: 'x/v1.0.0', name: 'x', status: 'active', acir_url: '', source_url: '', nargo_toml_url: '' }]
    expect(isRetiredCircuit('x/v1.0.0', odd)).toBe(false)
  })
})
