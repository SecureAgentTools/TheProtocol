/**
 * D6-679 (2026-10-16): the evals.completed notification opens #/leaderboard?mode=evals (it opened #/evals, a route the
 * console does not have). The Evals tab opens on the first arrival AND when only the query changes while the page is
 * open (vue-router reuses the component then); a value the page does not know changes nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = await vi.hoisted(async () => {
  const { reactive } = await import('vue')
  return { route: reactive({ query: {} as Record<string, unknown> }), board: vi.fn(), rankings: vi.fn() }
})
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/api/leaderboard', () => ({
  leaderboardService: { getRankings: (...a: unknown[]) => h.rankings(...a), getProfile: vi.fn().mockResolvedValue(null) },
}))
vi.mock('@/services/api/evals', () => ({ evalsApi: { getLeaderboard: (...a: unknown[]) => h.board(...a) } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn() }) }))
vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU') }) }
})

import Leaderboard from './Leaderboard.vue'

let w: VueWrapper | null = null
const activeTab = () => w!.find('.lb-modetab--active').text()
const open = () => mount(Leaderboard, { global: { stubs: { Icon: true, UserAvatar: true, ReadFailedNotice: true, Teleport: true } } })

describe('the leaderboard opens the tab its address names', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.rankings.mockReset().mockResolvedValue({ rankings: [], total_agents: 0, timestamp: '' })
    h.board.mockReset().mockResolvedValue([{ agent_did: 'did:theprotocol:scored', mean_score: 0.9, runs: 3, last_at: null }])
  })
  afterEach(() => { w?.unmount(); w = null; h.route.query = {} })

  it('on the first arrival, and on a query-only change while it is open', async () => {
    h.route.query = { mode: 'evals' }
    w = open()
    await flushPromises()
    expect(activeTab()).toContain('Evals')
    expect(w.text()).toContain('did:theprotocol:scored')
    h.route.query = { mode: 'reputation' }
    await flushPromises()
    expect(activeTab()).toContain('Reputation')
    h.route.query = { mode: 'nonsense' }
    await flushPromises()
    expect(activeTab()).toContain('Reputation')
    h.route.query = { mode: 'evals' }
    await flushPromises()
    expect(activeTab()).toContain('Evals')
    expect(h.board).toHaveBeenCalledTimes(1)   // the scores read once, then kept
  })

  it('without a mode it opens on the reputation ranking, as before, and reads no eval scores', async () => {
    w = open()
    await flushPromises()
    expect(activeTab()).toContain('Reputation')
    expect(h.board).not.toHaveBeenCalled()
  })
})
