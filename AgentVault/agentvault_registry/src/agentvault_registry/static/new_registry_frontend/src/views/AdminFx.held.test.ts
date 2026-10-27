import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §REPATLANE-2 (V0603, agentvault2-45): a parked route whose paying leg's outcome is not known (phase egress_unknown or
 * swap_unknown) is HELD: nothing refunds it on its own, because the leg may have paid. The FX desk names it "held",
 * never "local" (which would read as refundable here) nor "far frame"; counts it apart; and a row the keeper gave up on
 * (failed) reads as a warning, not as settled. Mocked at the HTTP layer, so the service and the view are both tested.
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
const row = (id: string, phase: string, status: string, flags: { locally_refundable: boolean, held?: boolean }) => ({
  id, route_id: `${id}-route-0000-0000`, origin_did: 'did:theprotocol:payer', amount: '1.99', currency: 'ECU',
  parked_at_did: 'did:theprotocol:fx-router', phase, status, retries: 0, last_error: null, resolution_tx: null,
  created_at: '2026-10-12T12:00:00Z', resolved_at: null, ...flags,
})

// the other panels answer a refusal, which hides them (AdminFx.panelsRead.test.ts): only the parked routes render here
const refused = () => Object.assign(new Error('Request failed with status code 403'), { response: { status: 403 } })
const PANELS = ['/admin/supply-auditor/cross-frame-audit', '/teg/fx/route/status', '/teg/fx/router-keeper', '/teg/fx/reserve-keeper']

function routes(rows: unknown[]) {
  h.get.mockImplementation(async (url: string) => {
    if (PANELS.includes(url)) throw refused()
    if (url === '/teg/fx/dead-letters') return { data: { rows } }
    if (url === '/teg/fx/rate') return { data: { available: true, local_currency: 'ECU', peer_currency: 'ACU', rate: 1 } }
    if (url === '/admin/events/search') return { data: { events: [] } }
    return { data: {} }
  })
}
const phases = (w: ReturnType<typeof mount>) => w.findAll('[data-testid="fx-dl-phase"]').map(x => x.text())

describe('the FX desk names a held route for what it is', () => {
  beforeEach(() => { h.get.mockReset() })

  it('a held row reads "held", is counted apart, and the note says nothing refunds it', async () => {
    routes([
      row('a', 'egress_unknown', 'pending', { locally_refundable: false, held: true }),
      row('b', 'swap_unknown', 'failed', { locally_refundable: false, held: true }),
      row('c', 'pre_conversion', 'pending', { locally_refundable: true, held: false }),
      row('d', 'post_conversion_remote', 'pending', { locally_refundable: false, held: false }),
    ])
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(phases(w)).toEqual(['held', 'held', 'local', 'far frame'])
    expect(w.find('[data-testid="fx-dl-held-note"]').exists()).toBe(true)
    expect(w.find('[data-testid="fx-dl-held-count"]').text()).toContain('2')
    // the far-frame count is the one post_conversion_remote row, never the held ones
    expect(w.text()).toMatch(/Awaiting far frame\s*1/)
    const st = w.findAll('[data-testid="fx-dl-status"]')
    expect(st[1].text()).toBe('failed')
    expect(st[1].classes()).toContain('fx-warn')
    w.unmount()
  })

  it('control: without a held row there is no held note and no held count', async () => {
    routes([row('c', 'pre_conversion', 'refunded', { locally_refundable: true, held: false })])
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(phases(w)).toEqual(['local'])
    expect(w.find('[data-testid="fx-dl-held-note"]').exists()).toBe(false)
    expect(w.find('[data-testid="fx-dl-held-count"]').exists()).toBe(false)
    expect(w.find('[data-testid="fx-dl-status"]').classes()).toContain('fx-ok')
    w.unmount()
  })
})
