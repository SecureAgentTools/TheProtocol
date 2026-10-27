import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the FX desk's swap feed by frame. A slow read of a peer frame's feed (it
 * goes through the peer proxy) could answer after the frame picked next and land its swaps under that frame's chip.
 * Only the newest pick's answer is drawn now; an answered pick still shows its own swaps (the control).
 */
const h = vi.hoisted(() => ({ get: vi.fn(), peerGet: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), put: vi.fn() } }))
vi.mock('@/services/api/peer', () => ({ peerGet: h.peerGet }))
vi.mock('@/services/api/fx', async (orig) => ({ ...(await orig<Record<string, unknown>>()), fetchFxConfig: vi.fn().mockResolvedValue(null) }))
vi.mock('@/composables/useFrames', async () => {
  const { ref } = await import('vue')
  return { useFrames: () => ({ localFx: ref(null), localCurrency: ref('ECU'), currencyForTrustDomain: () => 'ECU', knownCurrencyForTrustDomain: () => null }) }
})
vi.mock('@/stores/multiFrameSession', () => ({ useMultiFrameSession: () => ({ adminTokenFor: (k: string) => (k === 'asia' ? 'peer-tok' : null) }) }))
vi.mock('@/composables/useAdminFrames', async () => {
  const { ref } = await import('vue')
  const opts = [{ key: 'local', label: 'This frame', isLocal: true }, { key: 'asia', label: 'ASIA', isLocal: false }]
  return { useAdminFrames: () => ({ selectableFrames: ref(opts), resolveOption: (k: string) => opts.find((o) => o.key === k) || opts[0] }) }
})

import AdminFx from './AdminFx.vue'

const opts = { global: { stubs: { Icon: true, JsonViewer: true, Teleport: true, teleport: true, RouterLink: true } } }
const swap = (ccy: string, amt: number) => ({ event_type: 'FxSwapSettled', event_id: `${ccy}-${amt}`, timestamp: '2026-10-05T12:00:00Z',
  data: { transaction_id: `${ccy}-${amt}`, source_currency: ccy, dest_currency: 'XCU', amount_in: amt, rate: 1, fee: 0 } })

function localAnswers(rows: unknown[]) {
  h.get.mockImplementation(async (url: string, cfg?: any) => {
    if (url === '/admin/events/search') return { data: { events: cfg?.params?.event_type === 'FxSwapSettled' ? rows : [] } }
    if (url === '/teg/fx/rate') return { data: { available: true, local_currency: 'ECU', peer_currency: 'ACU', rate: 1 } }
    if (url === '/teg/fx/dead-letters') return { data: { rows: [] } }
    if (url === '/teg/fx/router-keeper' || url === '/teg/fx/reserve-keeper' || url === '/teg/fx/route/status')
      throw Object.assign(new Error('404'), { response: { status: 404 } })   // absent here: those panels stay hidden
    return { data: {} }
  })
}
const chip = (w: ReturnType<typeof mount>, label: string) => w.findAll('button.fx-fchip').find((b) => b.text().includes(label))!

describe('the FX feed draws only the frame picked last', () => {
  beforeEach(() => { h.get.mockReset(); h.peerGet.mockReset() })

  it("a late answer for a frame already left does not land under the frame picked after it", async () => {
    localAnswers([swap('ECU', 11)])
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(w.text()).toContain('ECU→XCU')
    let release: (v: unknown) => void = () => {}
    h.peerGet.mockImplementation((_f: string, _p: string, _t: string, params: any) =>
      params?.event_type === 'FxSwapSettled' ? new Promise((res) => { release = res }) : Promise.resolve({ events: [] }))
    await chip(w, 'ASIA').trigger('click')           // ASIA's read is out
    await chip(w, 'This frame').trigger('click')     // back to this frame, which answers at once
    await flushPromises()
    release({ events: [swap('ACU', 22)] })           // ASIA answers late
    await flushPromises()
    expect(w.text()).toContain('ECU→XCU')
    expect(w.text(), "ASIA's late swaps under this frame's chip").not.toContain('ACU→XCU')
    w.unmount()
  })

  it('control: a picked frame that answers shows its own swaps', async () => {
    localAnswers([swap('ECU', 11)])
    h.peerGet.mockImplementation(async (_f: string, _p: string, _t: string, params: any) =>
      ({ events: params?.event_type === 'FxSwapSettled' ? [swap('ACU', 22)] : [] }))
    const w = mount(AdminFx, opts)
    await flushPromises()
    await chip(w, 'ASIA').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('ACU→XCU')
    w.unmount()
  })
})
