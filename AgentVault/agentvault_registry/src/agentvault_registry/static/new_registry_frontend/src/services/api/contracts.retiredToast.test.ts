/**
 * §COCKPITDESK (2026-10-15) — his report: /contracts "threw not found notification on opening". On EU and ASIA the legacy
 * list is retired (D8) and answers 404; the store reads that as "retired" (stores/contracts.retired.test.ts) and the
 * global error toast must not say "Not Found" over it. Both legacy reads therefore declare 404 as an answer.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: api, default: api }))

import { getAgentContracts, listAvailableContracts } from './contracts'

beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue({ data: [] }) })

describe('the retired legacy contract reads', () => {
  it('declare a 404 as an answer, so no global toast says "Not Found"', async () => {
    await listAvailableContracts(100)
    expect(api.get).toHaveBeenLastCalledWith('/contracts/', expect.objectContaining({ params: { limit: 100 }, expectedStatuses: [404] }))
    await getAgentContracts('did:theprotocol:x', 'client')
    expect(api.get).toHaveBeenLastCalledWith('/contracts/agent/did%3Atheprotocol%3Ax',
      expect.objectContaining({ params: { role: 'client' }, expectedStatuses: [404] }))
  })

  it('still rejects on the 404, for the store to decide', async () => {
    const notFound = Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } })
    api.get.mockRejectedValueOnce(notFound)
    await expect(listAvailableContracts()).rejects.toBe(notFound)
  })
})
