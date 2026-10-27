import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useBundlesStore } from './bundles'
import { useDisputesStore } from './disputes'
import { useCommandCenterStore } from './commandCenter'

/**
 * §FESUITE (the loading sweep, 2026-10-03): a figure says "0" only after its own read came back. The stores behind such
 * figures carry a flag that a successful read sets and a failed one does not; a later failed refresh does not clear it
 * (the page keeps showing what it showed). The pages render a dash while the flag is unset. (The contracts store's
 * `loaded` is pinned beside its retirement tests, in contracts.retired.test.ts.)
 */
const api = vi.hoisted(() => ({
  bundlesList: vi.fn(),
  disputeStats: vi.fn(),
  listTargets: vi.fn(),
}))
vi.mock('@/services/api/bundles', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  bundlesApi: { list: api.bundlesList, featured: vi.fn() },
}))
vi.mock('@/services/api/disputes', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  disputesApi: { getStats: api.disputeStats },
}))
vi.mock('@/services/api/diagnosticsApi', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  diagnosticsApi: { listTargets: api.listTargets },
}))
vi.mock('./ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('./auth', () => ({ useAuthStore: () => ({ activeAgent: null }) }))

const failed = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

describe('a store says it has read only after a read succeeded', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(api)) f.mockReset()
  })

  it('bundles: a failed first load leaves `loaded` unset, a success sets it, a later failure keeps it and the list', async () => {
    const s = useBundlesStore()
    expect(s.loaded).toBe(false)
    api.bundlesList.mockRejectedValueOnce(failed())
    await s.load()
    expect(s.loaded).toBe(false)
    api.bundlesList.mockResolvedValueOnce({ bundles: [{ id: 'b1' }] })
    await s.load()
    expect(s.loaded).toBe(true)
    api.bundlesList.mockRejectedValueOnce(failed())
    await s.load()
    expect(s.loaded).toBe(true)
    expect(s.bundles.map((b: { id: string }) => b.id)).toEqual(['b1'])
  })

  it('disputes: the stats count as read only once fetchStats answered', async () => {
    const s = useDisputesStore()
    expect(s.statsRead).toBe(false)
    api.disputeStats.mockRejectedValueOnce(failed())
    await s.fetchStats()
    expect(s.statsRead).toBe(false)
    expect(s.stats.total_disputes).toBe(0) // the zero-filled default the page must not show as "none"
    api.disputeStats.mockResolvedValueOnce({ total_disputes: 3, open_disputes: 1, resolved_disputes: 2, resolution_rate: 66.7, average_resolution_time: 4 })
    await s.fetchStats()
    expect(s.statsRead).toBe(true)
    expect(s.stats.total_disputes).toBe(3)
  })

  it('the command center: the targets count as read once loadTargets answered, and a sign-out forgets it', async () => {
    const s = useCommandCenterStore()
    expect(s.targetsRead).toBe(false)
    api.listTargets.mockRejectedValueOnce(failed())
    await s.loadTargets()
    expect(s.targetsRead).toBe(false)
    api.listTargets.mockResolvedValueOnce({ targets: [{ name: 'eu' }] })
    await s.loadTargets()
    expect(s.targetsRead).toBe(true)
    s.$reset()
    expect(s.targetsRead).toBe(false)
  })
})
