/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), on the desktop Guild board.
 *
 * (1) The chat's order card on a desktop now opens /guild?order=<id> (services/uiMode orderDoor): the board opens the
 *     order that address names, on arrival and on a query-only navigation while it is open (the view is not remounted),
 *     and then clears the address so a second door to the same order opens it again.
 * (2) Reading follows ownership: an order of the developer's agent shows in full whichever agent is selected, and says
 *     which agent may act on it (the acting agent still decides every action); My work lists the orders of all his
 *     agents and organizations (GET /guild/owned, his own token), each naming his agent, with or without an acting
 *     agent. The delivered work shows, read only, to whoever the registry returns it to.
 * BASE (origin/v0657/cut 553347408): the board reads no ?order=, says nothing of the owner, and My work is the acting
 * agent's /guild/mine (asked only with an acting agent).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const POSTER = 'did:theprotocol:eu.test:session-lead'
const SHELDON = 'did:theprotocol:eu.test:shadowban-sheldon'

const h = vi.hoisted(() => ({
  route: null as any,
  replace: null as any,
  auth: null as any,
  guild: {} as Record<string, any>,
}))
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ path: '/guild', query: {} as Record<string, string>, params: {} })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ replace: (...a: any[]) => h.replace(...a), push: vi.fn().mockResolvedValue(undefined) }),
  }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))
vi.mock('@/composables/useCurrency', async () => {
  const { computed } = await import('vue')
  return { useCurrency: () => ({ localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/services/api/guild', () => ({
  guildApi: new Proxy({}, { get: (_t, k: string) => (h.guild[k] ??= vi.fn().mockResolvedValue({ orders: [], total: 0 })) }),
}))

import GuildBoard from './GuildBoard.vue'

const order = (id: string, extra: Record<string, unknown> = {}) => ({
  order: { id, title: `Order ${id}`, status: 'open', bounty: '35', currency: 'ECU', poster_did: POSTER, worker_did: null,
    ...extra },
  bids: [], events: [],
})

function signIn(acting: string | null) {
  h.auth = { token: 'dev-tok', user: { id: 6, is_admin: false }, isAdmin: false,
    agentToken: acting ? 'agent-tok' : null, activeAgent: acting ? { did: acting, name: 'Shadowban Sheldon' } : null }
}

const opts = { global: { stubs: { Icon: true, ReadFailedNotice: true } } }

describe('the desktop Guild board and the order door', () => {
  beforeEach(() => {
    h.guild = {}
    h.replace = vi.fn(async (to: any) => { h.route.query = { ...(to?.query || {}) } })
    h.route.query = {}
    signIn(SHELDON)
  })

  it('?order=<id> opens that order on arrival, then clears the address', async () => {
    h.guild.detail = vi.fn(async (id: string) => order(id))
    h.route.query = { order: 'gwo_1' }
    const w = mount(GuildBoard, opts)
    await flushPromises()
    expect(h.guild.detail).toHaveBeenCalledWith('gwo_1')
    expect(w.find('.gld-d-head h2').text()).toBe('Order gwo_1')
    expect(h.replace).toHaveBeenCalled()
    expect(h.replace.mock.calls.at(-1)[0].query.order, 'the address no longer names the order').toBeUndefined()
    w.unmount()
  })

  it('a door to another order while the board is open opens it (a query-only navigation)', async () => {
    h.guild.detail = vi.fn(async (id: string) => order(id))
    const w = mount(GuildBoard, opts)
    await flushPromises()
    expect(h.guild.detail).not.toHaveBeenCalled()
    h.route.query = { order: 'gwo_2' }
    await flushPromises()
    expect(h.guild.detail).toHaveBeenCalledWith('gwo_2')
    expect(w.find('.gld-d-head h2').text()).toBe('Order gwo_2')
    w.unmount()
  })
})

/** Mount the board with one order on the tab that lists its status, and open it from the list (a click, as a person
 *  does; these cases are about what the detail shows, not about the door). */
async function openFromTheBoard(id: string, status: 'open' | 'awarded') {
  h.guild.board = vi.fn(async (st: string) => ({ total: 1, orders: st === status
    ? [{ id, title: `Order ${id}`, status: st, bounty: '35', currency: 'ECU', poster_did: POSTER, bid_count: 0 }] : [] }))
  const w = mount(GuildBoard, opts)
  await flushPromises()
  if (status !== 'open') {
    await w.findAll('button.gld-tab').find((b) => b.text() === 'In progress')!.trigger('click')
    await flushPromises()
  }
  await w.find(`[data-testid="gld-open-${id}"]`).trigger('click')
  await flushPromises()
  expect(w.find('.gld-d-head h2').text()).toBe(`Order ${id}`)
  return w
}

describe('reading follows ownership on the desktop Guild board', () => {
  beforeEach(() => {
    h.guild = { mine: vi.fn().mockResolvedValue({ orders: [], total: 0 }) }
    h.replace = vi.fn(async (to: any) => { h.route.query = { ...(to?.query || {}) } })
    h.route.query = {}
  })

  it('his agent posted the order: it shows in full with another agent selected, and names the agent that acts', async () => {
    signIn(SHELDON)
    h.guild.detail = vi.fn(async (id: string) => order(id, {
      status: 'submitted', worker_did: 'did:theprotocol:eu.test:worker', deliverable: { report: 'the work' },
      my_parties: [{ role: 'poster', agent_did: POSTER, name: 'session-lead', via: 'agent' }],
    }))
    const w = await openFromTheBoard('gwo_3', 'awarded')
    const line = w.find('[data-testid="gld-owner-line"]')
    expect(line.exists(), 'the owner is told whose order it is').toBe(true)
    expect(line.text()).toContain('session-lead')
    expect(line.text()).toContain('poster')
    const delivered = w.find('[data-testid="gld-deliverable"]')
    expect(delivered.exists(), 'the delivered work, read only').toBe(true)
    expect(delivered.text()).toContain('the work')
    expect(w.find('.gld-act-verify').exists(), 'acting still needs the poster agent').toBe(false)
    w.unmount()
  })

  it('control: with the poster agent itself selected, it acts as before and nothing is said of an owner', async () => {
    signIn(POSTER)
    h.guild.detail = vi.fn(async (id: string) => order(id, {
      my_parties: [{ role: 'poster', agent_did: POSTER, name: 'session-lead', via: 'agent' }],
    }))
    const w = await openFromTheBoard('gwo_4', 'open')
    expect(w.find('[data-testid="gld-owner-line"]').exists()).toBe(false)
    expect(w.text()).toContain('Cancel & refund')
    w.unmount()
  })

  it('My work lists the orders of all his agents on his own token, each naming his agent, with no agent acting', async () => {
    signIn(null)
    h.guild.owned = vi.fn().mockResolvedValue({ total: 1, orders: [{ id: 'gwo_5', title: 'Posted by the lead',
      status: 'open', bounty: '35', currency: 'ECU', poster_did: POSTER, worker_did: null,
      my_parties: [{ role: 'poster', agent_did: POSTER, name: 'session-lead', via: 'agent' }] }] })
    const w = mount(GuildBoard, opts)
    await flushPromises()
    const mine = w.findAll('button.gld-tab').find((b) => b.text() === 'My work')!
    await mine.trigger('click')
    await flushPromises()
    expect(h.guild.owned).toHaveBeenCalled()
    expect(h.guild.mine, 'not the acting agent\'s list').not.toHaveBeenCalled()
    expect(w.text()).toContain('Posted by the lead')
    expect(w.find('[data-testid="gld-mine-parties"]').text()).toContain('session-lead · poster')
    w.unmount()
  })

  it('the 10 s poll asks the owner list only while My work is the open tab', async () => {
    // HEAD 2862d4121: every poll of every tab asked GET /guild/owned for every signed-in viewer
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      signIn(SHELDON)
      h.guild.owned = vi.fn().mockResolvedValue({ total: 0, orders: [] })
      const w = mount(GuildBoard, opts)
      await flushPromises()
      vi.advanceTimersByTime(10_000)
      await flushPromises()
      expect(h.guild.owned, 'the Open tab does not read My work').not.toHaveBeenCalled()
      await w.findAll('button.gld-tab').find((b) => b.text() === 'My work')!.trigger('click')
      await flushPromises()
      expect(h.guild.owned).toHaveBeenCalledTimes(1)
      vi.advanceTimersByTime(10_000)
      await flushPromises()
      expect(h.guild.owned, 'the poll refreshes My work while it is open').toHaveBeenCalledTimes(2)
      await w.findAll('button.gld-tab').find((b) => b.text() === 'Open')!.trigger('click')
      await flushPromises()
      vi.advanceTimersByTime(10_000)
      await flushPromises()
      expect(h.guild.owned, 'and stops asking once another tab is open').toHaveBeenCalledTimes(2)
      w.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
