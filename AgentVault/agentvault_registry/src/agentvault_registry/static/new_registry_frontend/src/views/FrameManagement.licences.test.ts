import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): Frame Management's licence and invitation tables over a failed read.
 *  - licences: the banner named EVERY active federated frame as holding no licence, with an "Issue for …" button (a
 *    licence for a frame that may well hold one), and the table said "No frame licences." under its own error;
 *  - invitations: "No invitations match the current filter." under the error banner, and before any answer.
 * The banner waits for the licences to be read, each table says its read failed (Try again), and none is claimed
 * before an answer. Answered tables keep their words (the control).
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { developer_id: 1 } }) }))
vi.mock('@/composables/usePermissions', async () => {
  const { ref } = await import('vue')
  return { usePermissions: () => ({ canPlatform: ref(false) }) }
})
vi.mock('@/composables/useRegistryConfig', async () => {
  const { ref } = await import('vue')
  return { useRegistryConfig: () => ({ frameKitEnabled: ref(false) }) }
})
vi.mock('@/services/api/frameRequests', () => ({
  frameRequestService: { list: vi.fn().mockResolvedValue([]), review: vi.fn() },
  FRAME_FEATURE_SWITCHES: [],
}))

import FrameManagement from './FrameManagement.vue'

const NotificationSystem = { name: 'NotificationSystem', template: '<div />', methods: { success() {}, error() {} } }
const opts = { global: { stubs: { Icon: true, NotificationSystem, Teleport: true, teleport: true, RouterLink: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const FRAMES = { frames: [{ name: 'asia', status: 'ACTIVE', trust_domain: 'asia.example', peer_type: 'frame' }] }

function routes(licences: 'fail' | 'none' | 'held', invitations: 'fail' | 'none') {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/admin/federation/licenses') {
      if (licences === 'fail') throw failure()
      return { data: licences === 'held' ? [{ id: 1, operator_name: 'asia', operator_did: 'spiffe://asia.example', status: 'active' }] : [] }
    }
    if (url === '/admin/federation/frame-invitations') {
      if (invitations === 'fail') throw failure()
      return { data: { invitations: [] } }
    }
    if (url === '/admin/federation/topology-overview') return { data: FRAMES }
    if (url === '/admin/federation/frames/spire-status') {
      return { data: { spire_trust_domains: [], spire_error: null, in_both: [], in_spire_only: [], in_db_only: [], local_trust_domain: 'eu.example' } }
    }
    return { data: [] }
  })
}

describe('Frame Management says what its licence and invitation reads answered', () => {
  beforeEach(() => { h.get.mockReset() })

  it('failed reads: no unlicensed-frame alarm, no "No frame licences.", no "No invitations"; each table says it failed', async () => {
    routes('fail', 'fail')
    const w = mount(FrameManagement, opts)
    await flushPromises()
    expect(w.find('[data-testid="frm-lic-unlicensed"]').exists(), 'an alarm about licences nobody read').toBe(false)
    expect(w.text()).not.toContain('No frame licences.')
    expect(w.text()).not.toContain('No invitations match the current filter.')
    expect(w.find('[data-testid="frm-lic-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="frm-inv-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered: a frame with no licence is named; empty tables say none', async () => {
    routes('none', 'none')
    const w = mount(FrameManagement, opts)
    await flushPromises()
    expect(w.find('[data-testid="frm-lic-unlicensed"]').text()).toContain('asia')
    expect(w.text()).toContain('No frame licences.')
    expect(w.text()).toContain('No invitations match the current filter.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })

  it('answered: a licensed frame raises no alarm', async () => {
    routes('held', 'none')
    const w = mount(FrameManagement, opts)
    await flushPromises()
    expect(w.find('[data-testid="frm-lic-unlicensed"]').exists()).toBe(false)
    w.unmount()
  })
})
