import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the FX desk over failed reads, on a money page.
 *  - Integrity: "Cross-frame audit not exposed on this frame (non-FX frame, or admin sign-in required)" over ANY failed
 *    read, a claim about the frame's configuration the read never made;
 *  - Route Operations (the @fx_router's residue and its sweep) and Keepers vanished over a failed read.
 * Each says its read failed now, with Try again. Answers keep their words: the frame's own "available: false" is "not
 * exposed", and a refusal (403) or a registry without the route (404) still hides the panel (the control).
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
const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })
const noAnswer = () => new Error('Network Error')
const PANELS = ['/admin/supply-auditor/cross-frame-audit', '/teg/fx/route/status', '/teg/fx/router-keeper', '/teg/fx/reserve-keeper']
const ROUTER_KEEPER = {
  active: false, env_gate_enabled: false, currency: 'ECU', router_liquid: '0',
  config: { enabled: false, target_float: '100', min_float: '10', source: 'treasury', check_interval_sec: 60,
    dead_letter_refund_enabled: false, dead_letter_max_retries: 3, updated_at: null, updated_by: null },
}

function routes(panel: (url: string) => unknown) {
  h.get.mockImplementation(async (url: string) => {
    if (PANELS.includes(url)) {
      const r = panel(url)
      if (r instanceof Error) throw r
      return { data: r }
    }
    if (url === '/teg/fx/rate') return { data: { available: true, local_currency: 'ECU', peer_currency: 'ACU', rate: 1 } }
    if (url === '/admin/events/search') return { data: { events: [] } }
    if (url === '/teg/fx/dead-letters') return { data: { rows: [] } }
    return { data: {} }
  })
}
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()

describe('the FX desk says what its integrity, route and keeper reads answered', () => {
  beforeEach(() => { h.get.mockReset() })

  for (const [what, err] of [['a 502', () => answered(502)], ['no answer', noAnswer]] as const) {
    it(`${what}: each panel says its read failed, never "not exposed on this frame" and never a vanished panel`, async () => {
      routes(() => err())
      const w = mount(AdminFx, opts)
      await flushPromises()
      expect(w.text()).not.toContain('not exposed on this frame')
      expect(has(w, 'fx-audit-unread'), 'the integrity panel says its read failed').toBe(true)
      expect(has(w, 'fx-routeops-unread'), 'Route Operations stays and says its read failed').toBe(true)
      expect(has(w, 'fx-keepers-unread'), 'Keepers stays and says its read failed').toBe(true)
      w.unmount()
    })
  }

  it('Try again reads the audit again and an answer replaces the notice', async () => {
    let fail = true
    routes((url) => (url.includes('cross-frame-audit') && !fail ? { available: false } : answered(502)))
    const w = mount(AdminFx, opts)
    await flushPromises()
    fail = false
    await w.find('[data-testid="fx-audit-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(has(w, 'fx-audit-unread')).toBe(false)
    expect(w.text()).toContain('not exposed on this frame')
    w.unmount()
  })

  it('one keeper answered and the other failed: the answered one shows, beside the notice', async () => {
    routes((url) => (url === '/teg/fx/router-keeper' ? ROUTER_KEEPER : url === '/teg/fx/reserve-keeper' ? answered(503) : answered(404)))
    const w = mount(AdminFx, opts)
    await flushPromises()
    expect(has(w, 'fx-keepers-unread')).toBe(true)
    expect(w.find('[data-tour="fx-keepers"]').text()).toContain('100')
    w.unmount()
  })

  for (const code of [403, 404]) {
    it(`control: the frame's own "available: false" is "not exposed"; a ${code} hides Route Operations and Keepers, with no notice`, async () => {
      routes((url) => (url.includes('cross-frame-audit') ? { available: false } : answered(code)))
      const w = mount(AdminFx, opts)
      await flushPromises()
      expect(w.text()).toContain('not exposed on this frame')
      expect(w.find('.fx-routeops').exists()).toBe(false)
      expect(w.find('[data-tour="fx-keepers"]').exists()).toBe(false)
      expect(w.find('[data-read-failed]').exists(), 'no read failed').toBe(false)
      w.unmount()
    })
  }
})
