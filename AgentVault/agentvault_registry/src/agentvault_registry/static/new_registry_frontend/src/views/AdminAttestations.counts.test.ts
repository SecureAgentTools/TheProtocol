import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): Admin Attestations counted a list it never read: "Loaded 0 of 0 total",
 * Verified 0, Expired 0, Revoked 0, Failed 0 and "0 shown" beside "Failed to load". The counts read "—" until a read
 * answers; a failed refresh keeps what was read. An answered empty list still counts 0.
 */
const h = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/services', () => ({ attestationsApi: { listAttestations: h.list, adminRevokeAttestation: vi.fn() } }))

import AdminAttestations from './AdminAttestations.vue'

const opts = { global: { stubs: { Icon: true, Teleport: true, teleport: true } } }
const values = (w: ReturnType<typeof mount>) => w.findAll('.adm-att-stat-value').map((e) => e.text())

describe('Admin Attestations counts only what it read', () => {
  beforeEach(() => { h.list.mockReset() })

  it('a failed read: no 0 counts beside the error', async () => {
    h.list.mockRejectedValueOnce(new Error('Request failed with status code 502'))
    const w = mount(AdminAttestations, opts)
    await flushPromises()
    expect(w.text()).toContain('Failed to load')
    expect(values(w)).toEqual(['—', '—', '—', '—', '—'])
    expect(w.text()).not.toMatch(/\b0 shown\b/)
    w.unmount()
  })

  it('an answered empty list counts 0', async () => {
    h.list.mockResolvedValueOnce({ items: [], count: 0 })
    const w = mount(AdminAttestations, opts)
    await flushPromises()
    expect(values(w)).toEqual(['0', '0', '0', '0', '0'])
    expect(w.text()).toContain('No attestations match the current filters.')
    w.unmount()
  })
})
