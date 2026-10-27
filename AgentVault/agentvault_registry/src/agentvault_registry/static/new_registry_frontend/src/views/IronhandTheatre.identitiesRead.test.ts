import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the IRONHAND theatre kept its identities read quiet and starts at zeros,
 * so a failed read said "SPIRE FABRIC NOMINAL" in green over "enrolled 0", "revoked 0", "SPIRE entries 0/0" and "No
 * enrolled mTLS identities.". Until an answer the fabric and the counts read "—", and the list says its read failed.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))
vi.mock('@/services/api/canaryIronhand', () => ({
  getCanaryIronhandStatus: vi.fn().mockRejectedValue(new Error('x')),
  getCanaryIronhandEvents: vi.fn().mockRejectedValue(new Error('x')),
}))
vi.mock('@/composables/useFrameManifest', () => ({ currentOwnCurrency: () => 'ECU' }))
// the embedded WebGL map is not this test's subject (and its template does not compile under the test compiler)
vi.mock('@/views/GalacticMap.vue', () => ({ default: { name: 'GalacticMap', render: () => null } }))

import IronhandTheatre from './IronhandTheatre.vue'

const opts = { global: { stubs: { Icon: true, GalacticMap: true, UserAvatar: true, GlitchOverlay: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
// the first pill is the fabric's (a selector the view had before this change too, so the control reads the same place)
const fabric = (w: ReturnType<typeof mount>) => w.findAll('.iht-pill')[0].text()

describe('the IRONHAND theatre says what its identities read answered', () => {
  beforeEach(() => { h.get.mockReset() })

  it('a failed read: no NOMINAL, no 0 counts, no "No enrolled mTLS identities."', async () => {
    h.get.mockRejectedValue(failure())
    const w = mount(IronhandTheatre, opts)
    await flushPromises()
    expect(fabric(w)).not.toMatch(/NOMINAL|DEGRADED/)
    expect(w.text()).not.toContain('No enrolled mTLS identities.')
    expect(w.text()).not.toMatch(/SPIRE entries\s*0\/0/)
    expect(w.find('[data-testid="iht-identities-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('an answered empty fabric: NOMINAL and none', async () => {
    h.get.mockImplementation(async (url: string) => {
      if (url === '/admin/ironhand/identities') {
        return { data: { summary: { db_enrolled: 0, db_revoked: 0, agent_entries: 0, total_spire_entries: 3, orphan_entries: 0, missing_entries: 0 },
          enrolled: [], revoked: [], orphans: [] } }
      }
      throw failure()
    })
    const w = mount(IronhandTheatre, opts)
    await flushPromises()
    expect(fabric(w)).toContain('NOMINAL')
    expect(w.text()).toContain('No enrolled mTLS identities.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
