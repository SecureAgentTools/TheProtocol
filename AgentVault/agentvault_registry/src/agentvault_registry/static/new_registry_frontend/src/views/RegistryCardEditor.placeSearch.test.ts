/**
 * §FESUITE (V0578): the registry card editor's place search (the authoritative globe location) showed nothing for a
 * failed search: the 502 body reached .map, threw inside the catch and became [], which is also what an answered search
 * with no place shows. A failed search now says it failed (with Try again), a switched-off one says so, and an answered
 * empty one says "No place found".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

vi.mock('@/services/api/registryCardAdmin', () => ({
  FLARE_ENCIRCLEMENT_VARIANTS: [], FLARE_ENCIRCLEMENT_OVERLAYS: [], FLARE_CORNER_VARIANTS: [],
  registryCardAdminApi: {
    get: async () => ({
      identity: { display_name: 'EU', registry_name: 'eu', tier: 'frame', spiffe_id: 'spiffe://eu/registry', trust_domain: 'eu', public_url: 'https://eu.example', founded_at: '2026-09-07' },
      description: 'A frame.', tags: [],
      operator: { bio: '', company: '', url: '', developer_id: 1, display_name: 'op' },
      visual: { orb_color: '#00d2d2', orb_glow_color: '#00ffff', orb_pulse_speed_hz: 1.4, orb_size_px: 16, halo_enabled: true, halo_thickness: 1.4, theme: 'neural', icon_url: null },
      economic: { supply_invariant_status: 'OK', supply_invariant_delta: 0 },
      fees: { intra_registry: { base_rate_percent: 0.5 }, cross_registry: { base_rate_percent: 0.5, fee_recipient: 'receiver' }, hosting: { enabled: false, rate_percent_of_agent_service_fee: 0 }, fee_waterfall_policy: 'x', fee_collector_address: 'did:x' },
      signature: null, policy: {}, federation: {}, links: {}, commitments: {}, lifecycle: { card_etag: 'abc' },
    }),
  },
}))

import RegistryCardEditor from './RegistryCardEditor.vue'

const answer = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body })
let w: VueWrapper | null = null
async function searchWith(fetchAnswer: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fetchAnswer))
  w = mount(RegistryCardEditor, { global: { stubs: { Icon: true, FlareEncirclement: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('.rc-loc-search input').setValue('Brussels')
  await w.find('.rc-loc-search-btn').trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
  return w.find('.rc-loc').text()
}

describe("the registry card editor's place search", () => {
  beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })
  afterEach(() => { w?.unmount(); w = null; vi.unstubAllGlobals() })

  it('a failed search does not look like an answered search that found no place', async () => {
    const failed = await searchWith(answer(502, { detail: 'geocoding upstream unreachable' }))
    w!.unmount(); w = null
    const none = await searchWith(answer(200, []))
    expect(failed, 'a failed search drew exactly what "no place found" draws').not.toBe(none)
    expect(none).toContain('No place found')
  })

  it('a failed search says it failed, and Try again searches again', async () => {
    await searchWith(answer(502, { detail: 'geocoding upstream unreachable' }))
    expect(w!.find('[data-testid="rc-geo-failed"]').exists()).toBe(true)
    expect(w!.find('.rc-loc').text()).not.toContain('No place found')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, [{ display_name: 'Brussels, Belgium', lat: '50.8467', lon: '4.3525' }])))
    await w!.find('[data-testid="rc-geo-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w!.findAll('.rc-loc-result')).toHaveLength(1)
    expect(w!.find('[data-testid="rc-geo-failed"]').exists()).toBe(false)
  })

  it('a frame whose place search is switched off says so, never "No place found"', async () => {
    const text = await searchWith(answer(404, { detail: 'geocode relay disabled on this frame' }))
    expect(text).not.toContain('No place found')
    expect(w!.find('[data-testid="rc-geo-off"]').exists()).toBe(true)
  })
})
