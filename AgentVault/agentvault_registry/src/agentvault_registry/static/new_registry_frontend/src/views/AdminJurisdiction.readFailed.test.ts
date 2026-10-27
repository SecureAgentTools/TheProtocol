import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): over a failed read the page drew its error banner AND "No jurisdiction profile is declared",
 * "No regulated actions declared. Nothing parks; the rail is inert." and "Nothing on file yet": an all-clear on the
 * compliance page that it never read. Each section says its read failed; an answered empty state still says none.
 */
const svc = vi.hoisted(() => ({ getProfile: vi.fn(), listAuthorizations: vi.fn(), listAttestationCandidates: vi.fn() }))
vi.mock('@/services/api/jurisdictionAdmin', () => ({ jurisdictionAdminService: svc }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: () => null, getAllCredentials: () => ({}) } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ agentToken: null, activeAgent: null, availableAgents: [] }) }))

import AdminJurisdiction from './AdminJurisdiction.vue'

const opts = { global: { stubs: { Icon: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

describe('the jurisdiction admin says what it read', () => {
  beforeEach(() => {
    for (const f of Object.values(svc)) f.mockReset()
    svc.listAttestationCandidates.mockResolvedValue([])
  })

  it('failed reads draw no all-clear, and each section says its read failed', async () => {
    svc.getProfile.mockRejectedValue(failure())
    svc.listAuthorizations.mockRejectedValue(failure())
    const w = mount(AdminJurisdiction, opts)
    await flushPromises()
    expect(w.text()).not.toContain('No jurisdiction profile is declared')
    expect(w.text()).not.toContain('the rail is inert')
    expect(w.text()).not.toContain('Nothing on file yet')
    expect(w.find('[data-testid="juri-profile-failed"]').exists()).toBe(true)
    expect(w.find('[data-testid="juri-entries-failed"]').exists()).toBe(true)
    expect(w.find('[data-testid="juri-auths-failed"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered empty reads still say none', async () => {
    svc.getProfile.mockResolvedValue({ declared: false, profile: null, mode: 'shadow', features_denied: [] })
    svc.listAuthorizations.mockResolvedValue({ authorizations: [], actions: [], display_only_actions: [] })
    const w = mount(AdminJurisdiction, opts)
    await flushPromises()
    expect(w.text()).toContain('No jurisdiction profile is declared')
    expect(w.text()).toContain('the rail is inert')
    expect(w.text()).toContain('Nothing on file yet')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
