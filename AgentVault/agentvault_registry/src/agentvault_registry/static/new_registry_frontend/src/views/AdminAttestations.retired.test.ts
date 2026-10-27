import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §ZKV2 (2026-10-13): Admin Attestations marks a retired (v1.0.0) circuit and shows why a proof failed (the
 * registry stores the verifier's reason in failure_reason); a verified v2 row carries neither.
 */
const h = vi.hoisted(() => ({ list: vi.fn(), circuits: vi.fn() }))
vi.mock('@/services', () => ({ attestationsApi: { listAttestations: h.list, listCircuits: h.circuits, adminRevokeAttestation: vi.fn() } }))
vi.mock('@/services/api/client', () => ({ apiClient: {} }))

import AdminAttestations from './AdminAttestations.vue'

const row = (over: Record<string, unknown>) => ({
  id: String(over.id), agent_did: 'did:theprotocol:abc', circuit_id: 'fairMarkupPolicy/v2.0.0', circuit_version: 'v2.0.0',
  public_inputs: {}, proof_hash: 'h', policy_parameters_hash: null, verified: true, failure_reason: null,
  submitted_at: '2026-10-13T10:00:00Z', verified_at: null, event_id: null, expires_at: null, revoked_at: null,
  revoked_by: null, revoked_reason: null, expired_emitted_at: null, ...over,
})

describe('Admin Attestations: retired circuits and failure reasons', () => {
  beforeEach(() => { h.list.mockReset(); h.circuits.mockReset() })

  it('marks the v1 row retired and shows the failed row\'s reason', async () => {
    h.circuits.mockResolvedValue([
      { circuit_id: 'fairMarkupPolicy/v2.0.0', name: 'fair_markup', status: 'active', acir_url: '', source_url: '', nargo_toml_url: '' },
      { circuit_id: 'fairMarkupPolicy/v1.0.0', name: 'fair_markup', status: 'retired', superseded_by: 'fairMarkupPolicy/v2.0.0', acir_url: '', source_url: '', nargo_toml_url: '' },
    ])
    h.list.mockResolvedValue({ items: [
      row({ id: 1 }),
      row({ id: 2, circuit_id: 'fairMarkupPolicy/v1.0.0', circuit_version: 'v1.0.0' }),
      row({ id: 3, verified: false, failure_reason: "max_markup_bps=3500 is looser than this registry's policy (3000)" }),
    ], count: 3 })
    const w = mount(AdminAttestations, { global: { stubs: { Icon: true, Teleport: true, teleport: true } } })
    await flushPromises()
    const rows = w.findAll('tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows[0].find('[data-test="circuit-retired"]').exists()).toBe(false)
    expect(rows[0].find('[data-test="failure-reason"]').exists()).toBe(false)
    expect(rows[1].find('[data-test="circuit-retired"]').exists()).toBe(true)
    expect(rows[1].find('[data-test="circuit-retired"]').attributes('title')).toContain('fairMarkupPolicy/v2.0.0')
    expect(rows[2].find('[data-test="failure-reason"]').text()).toContain('looser than this registry')
    expect(w.find('[data-test="circuit-filter"]').text()).toContain('fairMarkupPolicy/v1.0.0 (retired)')
    w.unmount()
  })
})
