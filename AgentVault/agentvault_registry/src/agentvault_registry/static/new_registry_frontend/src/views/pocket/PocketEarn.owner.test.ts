/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 2, in Pocket's order sheet (/pocket/payments?order=<id>).
 *
 * The maintainer's report (sessions' room seq 2105): with Shadowban Sheldon selected, the order his session-lead agent
 * posted showed "nothing": the sheet drew the selected agent as an observer, a note and the last events, no bids, no
 * delivered work. Reading follows ownership: the registry names the developer's parties on the order (`my_parties`), and
 * the sheet shows the order in full to its owner, the bids and the delivered work read only, with a line naming the
 * agent that may act on it. Acting still needs that agent: no award, verify or cancel is offered to another agent.
 * BASE: the observer's note alone.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const LEAD = 'did:theprotocol:eu.test:session-lead'
const SHELDON = 'did:theprotocol:eu.test:shadowban-sheldon'
const BIDDER = 'did:theprotocol:eu.test:session-code'

const h = vi.hoisted(() => ({ route: null as any, guild: {} as Record<string, any>, acting: '' }))
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ path: '/pocket/payments', query: {} as Record<string, string>, params: {} })
  return { useRoute: () => h.route, useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }) }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', activeAgent: { did: h.acting } }) }))
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({
    credAgents: ref([{ did: SHELDON, name: 'Shadowban Sheldon' }, { did: LEAD, name: 'session-lead' }]),
    noAgentReason: ref(''), ensureAgentFor: vi.fn().mockResolvedValue(true) }) }
})
vi.mock('@/composables/usePocketLock', async () => {
  const { ref } = await import('vue')
  return { usePocketLock: () => ({ enabled: ref(false), verify: vi.fn().mockResolvedValue(true) }) }
})
vi.mock('@/composables/useActingContext', async () => {
  const { ref } = await import('vue')
  return { useActingContext: () => ({ actingCurrencyLabel: ref('ECU') }) }
})
vi.mock('@/services/api/guild', () => ({
  guildApi: new Proxy({}, { get: (_t, k: string) => (h.guild[k] ??= vi.fn().mockResolvedValue({ orders: [], total: 0 })) }),
}))

import PocketEarn from './PocketEarn.vue'

const lead = { role: 'poster', agent_did: LEAD, name: 'session-lead', via: 'agent' }
function detail(extra: Record<string, unknown>) {
  return { order: { id: 'gwo_q', title: 'V0658 (q)', poster_did: LEAD, worker_did: null, status: 'open', bounty: '35',
    currency: 'ECU', bid_count: 1, my_parties: [lead], ...extra },
    bids: [{ id: 11, bidder_did: BIDDER, price: '30', pitch: 'Tests first, then the change.', status: 'open' }],
    events: [{ event_type: 'posted', created_at: '2026-11-07T19:12:09Z' }] }
}

async function openSheet(acting: string, d: any) {
  h.acting = acting
  h.guild.detail = vi.fn().mockResolvedValue(d)
  h.route.query = { order: 'gwo_q' }
  const w = mount(PocketEarn, { global: { stubs: { Icon: true, ActingContextNotice: true } } })
  await flushPromises()
  expect(h.guild.detail).toHaveBeenCalledWith('gwo_q')
  expect(w.find('[data-testid="pe-order-sheet"]').exists()).toBe(true)
  return w
}

describe("Pocket's order sheet and the order's owner", () => {
  beforeEach(() => { h.guild = { networkBoard: vi.fn().mockResolvedValue({ orders: [], peers_polled: 0 }) } })

  it('another of his agents working: the order shows in full, read only, and names the agent that acts', async () => {
    const w = await openSheet(SHELDON, detail({}))
    const line = w.find('[data-testid="pe-ord-owner"]')
    expect(line.exists(), 'the owner is told whose order it is').toBe(true)
    expect(line.text()).toContain('session-lead')
    expect(line.text()).toContain('poster')
    expect(w.find('[data-testid="pe-ord-note"]').exists(), 'not "neither the poster nor the worker"').toBe(false)
    const bids = w.find('[data-testid="pe-ord-bids-read"]')
    expect(bids.exists(), 'the bids, read only').toBe(true)
    expect(bids.text()).toContain('Tests first, then the change.')
    expect(w.find('.pe-award').exists(), 'awarding still needs the poster agent').toBe(false)
    w.unmount()
  })

  it('the delivered work reads to the owner; verifying it still needs the poster agent', async () => {
    const w = await openSheet(SHELDON, detail({ status: 'submitted', worker_did: BIDDER, deliverable: { note: 'branch v0658/q' } }))
    const read = w.find('[data-testid="pe-ord-deliv-read"]')
    expect(read.exists(), 'the delivered work, read only').toBe(true)
    expect(read.text()).toContain('branch v0658/q')
    expect(w.text()).not.toContain('Accept & pay')
    w.unmount()
  })

  it('control: working as the poster agent itself, the sheet acts as before and names no owner', async () => {
    const w = await openSheet(LEAD, detail({}))
    expect(w.find('[data-testid="pe-ord-owner"]').exists()).toBe(false)
    expect(w.find('.pe-award').exists(), 'the poster awards').toBe(true)
    w.unmount()
  })
})
