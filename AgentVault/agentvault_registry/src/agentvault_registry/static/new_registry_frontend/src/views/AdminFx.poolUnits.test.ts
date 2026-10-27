import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * D6-058 (agentvault2-d6, 2026-10-25): the pool card labels each figure with the unit the registry names for it.
 * The pool keys keep the AVT/BVT pool's order, so on a frame whose unit is not AVT x is the PEER frame's reserve: EU's
 * desk showed ASIA's 1000 ACU as "1000 ECU", its own 900 ECU as "900 ACU", and the spot's unit inverted (ECU/ACU for an
 * ACU-per-ECU figure). The registry names x_currency, y_currency and mtm_currency since V0642; a registry that names
 * none keeps the frame's pair (the control).
 * RED control: against V0640's AdminFx.vue the legs carry no data-testid and the x leg says ECU.
 * Mocked at the HTTP layer, so the service and the view are both under test.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), put: vi.fn() } }))
vi.mock('@/services/api/fx', async (orig) => ({ ...(await orig<Record<string, unknown>>()), fetchFxConfig: vi.fn().mockResolvedValue(null) }))
vi.mock('@/composables/useFrames', async () => {
  const { ref } = await import('vue')
  return { useFrames: () => ({ localFx: ref(null), localCurrency: ref('ECU'), currencyForTrustDomain: () => 'ECU', knownCurrencyForTrustDomain: () => null }) }
})
vi.mock('@/stores/multiFrameSession', () => ({ useMultiFrameSession: () => ({ adminTokenFor: () => null }) }))
vi.mock('@/composables/useAdminFrames', async () => {
  const { ref } = await import('vue')
  return { useAdminFrames: () => ({ selectableFrames: ref([{ key: 'local', label: 'This frame' }]), resolveOption: (k: string) => ({ key: k, label: 'This frame' }) }) }
})

import AdminFx from './AdminFx.vue'

const opts = { global: { stubs: { Icon: true, JsonViewer: true, Teleport: true, teleport: true, RouterLink: true } } }
// EU (ECU) beside ASIA (ACU): x = ASIA's 1000 ACU, y = EU's own 900 ECU, spot = x/y ACU per ECU, MtM in ACU
const POOL = { available: true, currency_pair: 'ECU/ACU', rate_mode: 'pool', x: 1000, y: 900, spot_P: 1000 / 900, k: 900000, mtm_avt: 2000 }
const UNITS = { x_currency: 'ACU', y_currency: 'ECU', mtm_currency: 'ACU' }

// the integrity, route and keeper panels answer 404 (a registry without them: each panel hides), so the pool card is
// the only thing the drive reads
const PANELS = ['/admin/supply-auditor/cross-frame-audit', '/teg/fx/route/status', '/teg/fx/router-keeper', '/teg/fx/reserve-keeper']
const absent = () => Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } })

function routes(pool: Record<string, unknown>) {
  h.get.mockImplementation(async (url: string) => {
    if (PANELS.includes(url)) throw absent()
    if (url === '/teg/fx/pool/admin') return { data: pool }
    if (url === '/teg/fx/rate') return { data: { available: true, local_currency: 'ECU', peer_currency: 'ACU', rate: 1 } }
    if (url === '/admin/events/search') return { data: { events: [] } }
    if (url === '/teg/fx/dead-letters') return { data: { rows: [] } }
    return { data: {} }
  })
}
const text = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).text()

describe('the FX desk labels each pool figure with the unit the registry names for it', () => {
  beforeEach(() => { h.get.mockReset() })

  it('x is the peer frame\'s ACU reserve and says so; y, the spot and the MtM name theirs', async () => {
    routes({ ...POOL, ...UNITS })
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(text(w, 'fx-pool-x')).toContain('ACU')
    expect(text(w, 'fx-pool-x')).not.toContain('ECU')
    expect(text(w, 'fx-pool-y')).toContain('ECU')
    expect(text(w, 'fx-pool-y')).not.toContain('ACU')
    expect(text(w, 'fx-pool-spot')).toContain('ACU/ECU')
    expect(text(w, 'fx-pool-mtm')).toContain('ACU')
    w.unmount()
  })

  it('control: a registry that names no unit keeps the frame\'s pair (this frame\'s unit on x, the peer\'s on y)', async () => {
    routes(POOL)
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(text(w, 'fx-pool-x')).toContain('ECU')
    expect(text(w, 'fx-pool-y')).toContain('ACU')
    expect(text(w, 'fx-pool-spot')).toContain('ECU/ACU')
    w.unmount()
  })
})
