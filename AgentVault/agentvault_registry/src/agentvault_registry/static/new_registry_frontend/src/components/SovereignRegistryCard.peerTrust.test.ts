import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * The registry card modal's "our trust" row (§TRUSTWIRE) reads OUR peer row through the ADMIN topology rail
 * (/admin/federation/topology-overview, admin_federation); the public topology carries none of the trust evidence
 * (measured on sbx-alpha 2026-09-28: tier buckets without trust / total_interactions / bayesian_discount). The modal asked
 * the admin rail for every viewer, so opening any card on the public Discovery page was a 401 for a visitor, and a
 * signed-in non-admin was refused 403, fell back to a public row with no evidence, and read it as "unmeasured": a claim
 * the data never made. These tests mount the real modal, record every request, and hold both halves: only a viewer
 * holding the flag asks, and a row without the evidence is not graded. An admin sees what an admin always saw.
 */
const h = vi.hoisted(() => ({
  auth: { user: null as Record<string, unknown> | null },
  calls: [] as string[],
  adminStatus: 200,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

const PEER = 'Sandbox Beta'
const refused = (status: number) =>
  Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn(async (url: string) => {
      h.calls.push(url)
      if (url === '/admin/federation/topology-overview') {
        if (h.adminStatus !== 200) throw refused(h.adminStatus)
        return {
          data: {
            frames: [{
              name: PEER, total_interactions: 12, disputes_lost_with: 0, bayesian_discount: 0.9,
              trust: { state: 'ok', reason: 'within this frame\'s policy', enforced: false },
            }],
            direct_peers: [], discovered: [], cloud_operators: [], summary: {},
          },
        }
      }
      if (url === '/public/topology') {
        return {
          data: {
            frames: [{ name: PEER, peer_type: 'frame', status: 'ACTIVE' }],
            direct_peers: [], discovered: [], cloud_operators: [], registries: [], edges: [],
          },
        }
      }
      throw refused(404)
    }),
  },
}))

vi.mock('@/services/api/registryCardView', () => ({
  registryCardView: {
    fetchSource: vi.fn(async () => ({
      is_self: false, name: PEER, base_url: 'https://sandbox-b.example.test', card_etag: 'e1',
      card_signature_verified: true, card_last_pulled_at: null, public_card_url: null,
      licence_state: null, licence_reason: null, licence_checked_at: null,
      card: { identity: { display_name: PEER, registry_name: 'sandbox-b' }, federation: {} },
    })),
  },
}))

import SovereignRegistryCard from './SovereignRegistryCard.vue'

async function openCard(user: Record<string, unknown> | null, adminStatus = 200) {
  h.auth.user = user
  h.adminStatus = adminStatus
  h.calls.length = 0
  const w = mount(SovereignRegistryCard, {
    props: { show: false, peerName: PEER },
    global: { stubs: { teleport: true, FlareEncirclement: true, UserAvatar: true, ContractAttestationModal: true } },
  })
  await w.setProps({ show: true })
  await flushPromises()
  const trust = w.find('[data-testid="rcm-peer-trust"]')
  return { calls: [...h.calls], trust: trust.exists() ? trust.text() : null, w }
}

const adminCalls = (calls: string[]) => calls.filter(u => u.startsWith('/admin/'))

describe('the registry card modal reads our peer trust only for a viewer who may read it', () => {
  it('a visitor opening a peer card asks nothing of the admin rail, and sees no trust row', async () => {
    const r = await openCard(null, 401)
    expect(adminCalls(r.calls)).toEqual([])
    expect(r.calls).toEqual([])
    expect(r.trust).toBeNull()
  })

  it('a signed-in developer without admin_federation asks nothing of it either, and is not told "unmeasured"', async () => {
    const r = await openCard({ id: 7, is_admin: false }, 403)
    expect(adminCalls(r.calls)).toEqual([])
    expect(r.trust).toBeNull()
  })

  it('an admin holding only a different flag (admin_platform) does not ask the federation rail', async () => {
    const r = await openCard({ id: 8, is_admin: false, admin_platform: true }, 403)
    expect(adminCalls(r.calls)).toEqual([])
    expect(r.trust).toBeNull()
  })

  it('control: an admin with admin_federation reads the rail and sees our verdict, as before', async () => {
    const r = await openCard({ id: 9, is_admin: false, admin_federation: true })
    expect(adminCalls(r.calls)).toEqual(['/admin/federation/topology-overview'])
    expect(r.trust).toBe('90%')
  })

  it('control: a legacy is_admin passes every flag and sees our verdict, as before', async () => {
    const r = await openCard({ id: 10, is_admin: true })
    expect(adminCalls(r.calls)).toEqual(['/admin/federation/topology-overview'])
    expect(r.trust).toBe('90%')
  })

  it('a row the rail refused and the public topology filled carries no evidence, so it is not graded', async () => {
    // the FE flag and the backend guard disagree: the composable falls back to the public row on 403
    const r = await openCard({ id: 11, is_admin: false, admin_federation: true }, 403)
    expect(r.calls).toContain('/public/topology')
    expect(r.trust).toBeNull()
  })
})
