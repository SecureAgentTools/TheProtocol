import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

/**
 * §LANDINGTRUTH (30, with agentvault2-45's read state, fe/failed-read-2): an unread registry config reads as lock mode
 * (governanceMode: an absent switch is today's lock), which is false on a member-mode registry, the production frames
 * included. The public pages that state the voting mode say neither mode until the registry has answered, and say the
 * read failed (with Try again) when it did. The landing page's membership block follows the same rule; it is not
 * mounted here (the landing page stays out of every browser and mount harness: CLAUDE.md PART 1).
 */
const h = vi.hoisted(() => ({ cfg: null as any, reload: vi.fn() }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => h.cfg }))

import TokenEconomyDocs from './TokenEconomyDocs.vue'
import NetworkArchitecture from './NetworkArchitecture.vue'
import GovernanceDocs from './GovernanceDocs.vue'

type Kind = 'loading' | 'failed' | 'lock' | 'member'
function state(kind: Kind) {
  const config = ref<Record<string, unknown>>(
    kind === 'lock' ? { registry_name: 'x', governance_weight_mode: 'lock' }
      : kind === 'member' ? { registry_name: 'x', governance_weight_mode: 'member' } : {})
  const loaded = ref(kind !== 'loading')
  const readOk = ref(kind === 'lock' || kind === 'member')
  return {
    config, loaded, readOk, readFailed: computed(() => loaded.value && !readOk.value), reload: h.reload,
    localCurrency: ref(''), trustDomain: ref(''),
  }
}
const stubs = { RouterLink: { template: '<a><slot /></a>' }, 'router-link': { template: '<a><slot /></a>' } }
const LOCK = 'Locks give voting weight only'
const LOCK_SECTION = 'Lock units for voting weight.'
const MEMBER = 'Voting weight comes from membership'

beforeEach(() => {
  h.reload.mockReset()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }))
})
afterEach(() => { vi.unstubAllGlobals() })

describe('/units-and-fees states the voting mode only once the registry has answered', () => {
  it('while the read is in flight: neither mode, and no failure notice', async () => {
    h.cfg = state('loading')
    const w = mount(TokenEconomyDocs, { global: { stubs } }); await flushPromises()
    expect(w.text()).not.toContain(LOCK)
    expect(w.text()).not.toContain(LOCK_SECTION)
    expect(w.text()).not.toContain(MEMBER)
    expect(w.find('[data-testid="read-failed"]').exists()).toBe(false)
  })

  it('after a failed read: neither mode, the read says it failed, and Try again reads again', async () => {
    h.cfg = state('failed')
    const w = mount(TokenEconomyDocs, { global: { stubs } }); await flushPromises()
    expect(w.text()).not.toContain(LOCK)
    expect(w.text()).not.toContain(LOCK_SECTION)
    expect(w.text()).not.toContain(MEMBER)
    expect(w.find('[data-testid="read-failed"]').exists()).toBe(true)
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    expect(h.reload).toHaveBeenCalledTimes(1)
  })

  it('control: a lock-mode answer shows the lock sentences (the letter\'s wording), never the member ones', async () => {
    h.cfg = state('lock')
    const w = mount(TokenEconomyDocs, { global: { stubs } }); await flushPromises()
    expect(w.text()).toContain(LOCK)
    expect(w.text()).toContain('Nothing is paid for a lock.')
    expect(w.text()).toContain(LOCK_SECTION)
    expect(w.text()).not.toContain(MEMBER)
  })

  it('control: a member-mode answer shows membership, and no lock section', async () => {
    h.cfg = state('member')
    const w = mount(TokenEconomyDocs, { global: { stubs } }); await flushPromises()
    expect(w.text()).toContain(MEMBER)
    expect(w.text()).not.toContain(LOCK)
    expect(w.text()).not.toContain(LOCK_SECTION)
  })

  it('a read that answers later moves the page from neither mode to the answer, in place', async () => {
    h.cfg = state('failed')
    const w = mount(TokenEconomyDocs, { global: { stubs } }); await flushPromises()
    expect(w.text()).not.toContain(MEMBER)
    h.cfg.config.value = { registry_name: 'x', governance_weight_mode: 'member' }
    h.cfg.readOk.value = true
    await flushPromises()
    expect(w.text()).toContain(MEMBER)
    expect(w.find('[data-testid="read-failed"]').exists()).toBe(false)
  })
})

describe('/architecture names the governance only once the registry has answered', () => {
  const NEUTRAL = 'TEG Layer / Frame Currency / Governance'
  it.each([
    ['failed', NEUTRAL, ['Membership Governance', 'Locks / Weighted Governance', 'weighted by locked units', 'one vote per member']],
    ['lock', 'TEG Layer / Frame Currency / Locks / Weighted Governance', ['Membership Governance', 'one vote per member']],
    ['member', 'TEG Layer / Frame Currency / Membership Governance', ['Locks / Weighted Governance', 'weighted by locked units']],
  ] as const)('%s: the layer reads %s', async (kind, here, gone) => {
    h.cfg = state(kind as Kind)
    const w = mount(NetworkArchitecture, { global: { stubs } }); await flushPromises()
    expect(w.text()).toContain(here)
    for (const g of gone) expect(w.text()).not.toContain(g)
  })
})

describe('/governance-docs asks for its membership figures once the registry has answered', () => {
  // §LANDINGTRUTH (31): the figures were asked for on `loaded`, which turns true once, on a failed first read too; a read
  // that answered later never asked, and the member card kept "the software's defaults" (agentvault2-45's recovery sweep)
  const statsBody = { members: 2, joined_30d: 0, left_30d: 0, min_bond_age_days: 21, tenure_full_days: 365, max_weight: 2,
    points_per_weight: 100, presence_mode: 'conditional', requires_matured_bond: false }
  const statsCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => String(u).includes('/membership/stats')).length

  it('a failed first read asks for nothing; the answer that follows asks once, and the card says the figures are its own', async () => {
    const f = vi.fn(async (u: string) => (String(u).includes('/membership/stats')
      ? { ok: true, status: 200, json: async () => statsBody } : { ok: false, status: 503, json: async () => ({}) }))
    vi.stubGlobal('fetch', f)
    h.cfg = state('failed')
    const w = mount(GovernanceDocs, { global: { stubs } }); await flushPromises()
    expect(statsCalls(f)).toBe(0)
    expect(w.text()).toContain("The figures in this card are the software's defaults")
    h.cfg.config.value = { registry_name: 'x', governance_weight_mode: 'member' }
    h.cfg.readOk.value = true
    await flushPromises()
    expect(statsCalls(f)).toBe(1)
    expect(w.text()).toContain("The figures in this card are this registry's own.")
    expect(w.text()).toContain('21')                       // the registry's own bond age, not the default 30
  })

  it('control: an answer at mount asks once and never again on a later re-render', async () => {
    const f = vi.fn(async (u: string) => (String(u).includes('/membership/stats')
      ? { ok: true, status: 200, json: async () => statsBody } : { ok: false, status: 503, json: async () => ({}) }))
    vi.stubGlobal('fetch', f)
    h.cfg = state('member')
    const w = mount(GovernanceDocs, { global: { stubs } }); await flushPromises()
    expect(statsCalls(f)).toBe(1)
    h.cfg.config.value = { ...h.cfg.config.value, commons_enabled: true }
    await flushPromises()
    expect(statsCalls(f)).toBe(1)
    expect(w.text()).toContain("The figures in this card are this registry's own.")
  })
})
