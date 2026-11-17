// V0666 the Flare view reworked: the real manager over mocked services. Who wears it (you, then the agents), the two categories (Unlocked by contributing, Bought), wearing an
// unlocked ring or badge on the chosen bearer through the right route, the bought flares for an agent, and the page reading the registry again after a press.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), listMyAgents: vi.fn(), mine: vi.fn(), equip: vi.fn(), wear: vi.fn(), onAgent: vi.fn(),
  me: { flare_tier: null as string | null }, status: null as any, agents: [] as any[], items: [] as any[], title: null as string | null,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: true, user: { name: 'Ada Lovelace', email: 'ada@example.test', flare_tier: h.me.flare_tier }, setFlare: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: (...a: any[]) => h.get(...a), post: (...a: any[]) => h.post(...a), patch: (...a: any[]) => h.patch(...a) } }))
vi.mock('@/services/api/developer', () => ({ developerApi: { listMyAgents: (...a: any[]) => h.listMyAgents(...a) } }))
vi.mock('@/services/api/fiatOnramp', () => ({ fiatOnrampService: {} }))
vi.mock('@/composables/useRegistryConfig', () => ({ loadRegistryConfig: vi.fn().mockResolvedValue({ fiat_onramp_enabled: false }) }))
vi.mock('@/services/api/contributorTrack', () => ({ getMyTrack: (...a: any[]) => h.mine(...a), equipTitle: (...a: any[]) => h.equip(...a), wearEarned: (...a: any[]) => h.wear(...a), wearEarnedOnAgent: (...a: any[]) => h.onAgent(...a) }))

import FlareManager from './FlareManager.vue'

const item = (o: Record<string, any>) => ({ kind: 'corner', key: 'initiate', tier: 1, side: false, condition: 'Propose your first change.', unlocked: false, progress: { n: 0, of: 1 }, later: null, ...o })
const stubs = { Icon: true, UserAvatar: true, FlareBadge: true, FlareEncirclement: true, EarnedRing: true, EarnedBadge: true, TitleEmblem: true, ReadFailedNotice: { template: '<div data-read-failed />' }, RouterLink: { template: '<a><slot /></a>' } }
const mountIt = () => mount(FlareManager, { global: { stubs } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the reworked flare view', () => {
  beforeEach(() => {
    h.me.flare_tier = null
    h.status = { flare_tier: null, selected_corner_flare: null, selected_encirclement_flare: null, unlocked_corner_flares: [], unlocked_encirclement_flares: [], flare_encirclement_variant: null, flare_corner_variant: null }
    h.agents = [{ agent_did: 'did:a', name: 'Agent A', status: 'active' }, { agent_did: 'did:b', name: 'Agent B', status: 'active', flare_encirclement_variant: 'ember' }]
    h.items = [item({ kind: 'encirclement', key: 'lantern', tier: 2, unlocked: true, progress: { n: 1, of: 1 } }), item({ kind: 'corner', key: 'initiate', tier: 1, unlocked: true, progress: { n: 1, of: 1 } }),
      item({ kind: 'encirclement', key: 'ember', tier: 4, unlocked: true, progress: { n: 3, of: 3 } }), item({ kind: 'title', key: 'first-light', tier: 3, unlocked: true, progress: { n: 1, of: 1 } })]
    h.title = null
    h.get.mockReset().mockImplementation(async (url: string) => (url === '/developers/me' ? { data: { ...h.me } } : url === '/fiat/flare/status' ? { data: h.status } : { data: {} }))
    h.post.mockReset().mockResolvedValue({ data: {} })
    h.patch.mockReset().mockResolvedValue({ data: {} })
    h.listMyAgents.mockReset().mockImplementation(async () => h.agents)
    h.mine.mockReset().mockImplementation(async () => ({ items: h.items, equipped_title: h.title, season_wins: [], counts: {} }))
    h.equip.mockReset().mockResolvedValue({ title: 'first-light' })
    h.wear.mockReset().mockResolvedValue({})
    h.onAgent.mockReset().mockResolvedValue({})
  })

  it('opens on what you unlocked, for you, with the bearers rail above', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'flare-rail').exists()).toBe(true)
    expect(tid(w, 'bearer-me').attributes('aria-pressed')).toBe('true')
    expect(tid(w, 'bearer-did:a').exists()).toBe(true)
    expect(tid(w, 'earned-wear').attributes('data-bearer')).toBe('developer')
    expect(tid(w, 'tab-earned').attributes('aria-selected')).toBe('true')
    expect(tid(w, 'earned-titles').exists()).toBe(true)
  })

  it('shows what the agent that wears an unlocked ring wears, at a glance', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'bearer-did:b-ring').text()).toBe('Ring Ember')
    expect(tid(w, 'bearer-did:a-worn').text()).toBe('Wears nothing yet')
  })

  it('wears an unlocked ring on the chosen agent through the agent route and reads the registry again', async () => {
    const w = mountIt(); await flushPromises()
    await tid(w, 'bearer-did:a').trigger('click')
    expect(tid(w, 'earned-wear').attributes('data-bearer')).toBe('agent')
    expect(tid(w, 'earned-titles').exists()).toBe(false)
    const reads = h.listMyAgents.mock.calls.length
    await tid(w, 'track-wear-lantern').trigger('click'); await flushPromises()
    expect(h.onAgent).toHaveBeenCalledWith('did:a', 'encirclement', 'lantern')
    expect(h.wear).not.toHaveBeenCalled()
    expect(h.listMyAgents.mock.calls.length).toBeGreaterThan(reads)
  })

  it('says a copy another bearer wears moves on a press', async () => {
    const w = mountIt(); await flushPromises()
    await tid(w, 'bearer-did:a').trigger('click')
    expect(tid(w, 'earned-held-ember').text()).toContain('Worn by Agent B')
  })

  it('wears for you through your own route, and a title only for you', async () => {
    const w = mountIt(); await flushPromises()
    await tid(w, 'track-wear-initiate').trigger('click'); await flushPromises()
    expect(h.wear).toHaveBeenCalledWith('corner', 'initiate')
    await tid(w, 'track-wear-first-light').trigger('click'); await flushPromises()
    expect(h.equip).toHaveBeenCalledWith('first-light')
  })

  it("shows the registry's sentence where the press was made", async () => {
    h.onAgent.mockRejectedValue({ response: { data: { detail: 'This agent wears a bought ring. Take it off first, then give it the unlocked one.' } } })
    const w = mountIt(); await flushPromises()
    await tid(w, 'bearer-did:a').trigger('click')
    await tid(w, 'track-wear-lantern').trigger('click'); await flushPromises()
    expect(tid(w, 'track-err-lantern').text()).toContain('bought ring')
  })

  it('works with no flare tier: the unlocked items are there, and Bought says there is no flare yet', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'earned-wear').exists()).toBe(true)
    await tid(w, 'tab-bought').trigger('click')
    expect(tid(w, 'earned-wear').exists()).toBe(false)
    expect(w.text()).toContain('No flare yet')
  })

  it('shows the COMMANDER plate for the commander tier and takes the chosen title off to wear it', async () => {
    h.me.flare_tier = 'commander'
    h.status = { ...h.status, flare_tier: 'commander' }
    h.title = 'first-light'
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'earned-commander').exists()).toBe(true)
    h.equip.mockResolvedValue({ title: null })
    await tid(w, 'earned-commander-wear').trigger('click'); await flushPromises()
    expect(h.equip).toHaveBeenCalledWith(null)
  })

  it('opens on Bought when nothing is unlocked and the person holds a flare', async () => {
    h.me.flare_tier = 'founder'
    h.items = h.items.map((i) => ({ ...i, unlocked: false }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'tab-bought').attributes('aria-selected')).toBe('true')
    expect(tid(w, 'earned-wear').exists()).toBe(false)
  })

  it('shows the bought flares for the chosen agent and wears one on it through the equip route', async () => {
    h.me.flare_tier = 'founder'
    h.status = { ...h.status, flare_tier: 'founder', selected_corner_flare: 'founder', unlocked_corner_flares: ['founder'] }
    const w = mountIt(); await flushPromises()
    await tid(w, 'bearer-did:a').trigger('click')
    await tid(w, 'tab-bought').trigger('click')
    expect(tid(w, 'bought-on-agent').exists()).toBe(true)
    expect(tid(w, 'bought-corner-what').text()).toBe('Founder')
    await tid(w, 'bought-corner-on').trigger('click'); await flushPromises()
    expect(h.post).toHaveBeenCalledWith('/fiat/flare/equip/corner/did%3Aa')
  })

  it('says a failed read of the agents failed, and keeps you usable', async () => {
    h.listMyAgents.mockRejectedValue(new Error('down'))
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    expect(tid(w, 'earned-wear').exists()).toBe(true)
  })

  it('says the unlocked items could not be read, without saying there are none', async () => {
    h.mine.mockRejectedValue(new Error('down'))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'earned-failed').exists()).toBe(true)
    expect(tid(w, 'earned-none').exists()).toBe(false)
  })
})
