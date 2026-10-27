/**
 * §FESUITE (V0577): discoveryService.searchAgents (its one caller is the bridge terminal's DISCOVERY lane, which says
 * "Nothing matched. The network is searched whole, so this is a real zero.") read the whole list through
 * fetchAllAgents, which answers [] for a failed read as well as for an empty network. A search that got no answer was
 * therefore an answer of none, and the terminal's own failed-read notice could never show. searchAgents now throws when
 * the list could not be read; an empty network still answers no results.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'

vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn() } }))

// Each test imports the service fresh (vi.resetModules), so its first import is transformed inside the test's own time:
// under a loaded full run that alone passed the default 5 s (a timeout, 3/3 green alone; 2026-10-09). The budget below is
// for that import, not for the code under test.
const FRESH_IMPORT_MS = 30_000

describe('discoveryService.searchAgents when the agent list cannot be read', () => {
  beforeEach(() => { vi.resetModules() })

  async function freshService() {
    const { apiClient } = await import('@/services/api/client')
    ;(apiClient.get as any).mockReset()
    const { discoveryService } = await import('./discovery')
    return { get: apiClient.get as any, discoveryService }
  }

  it('rejects, so the caller can say the search failed (never "a real zero")', async () => {
    const { get, discoveryService } = await freshService()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    get.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    await expect(discoveryService.searchAgents('anything')).rejects.toThrow('could not be read')
  }, FRESH_IMPORT_MS)

  it('an empty network that answered is still no results', async () => {
    const { get, discoveryService } = await freshService()
    get.mockResolvedValue({ data: { items: [] } })
    await expect(discoveryService.searchAgents('anything')).resolves.toMatchObject({ results: [], total: 0 })
  }, FRESH_IMPORT_MS)
})
