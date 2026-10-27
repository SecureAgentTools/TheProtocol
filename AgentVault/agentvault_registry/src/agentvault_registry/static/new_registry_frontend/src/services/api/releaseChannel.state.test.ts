import { describe, it, expect, vi, beforeEach } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { releaseChannelApi, releaseChannelState } from './releaseChannel'

// The banner above every admin page and the release page show ONE status: the page's own check is the banner's answer
// too (agentvault2-56, 2026-10-23: the banner read the status once per session and still announced a newer release
// after the page's check said up to date).
describe('one release status for the page and the banner', () => {
  beforeEach(() => { releaseChannelState.value = null; vi.clearAllMocks() })

  it("the page's check replaces what the banner shows", async () => {
    ;(apiClient.get as any).mockResolvedValueOnce({ data: { enabled: true, update_available: true, latest: { version: '1.0.0-beta.23' }, newer: [{ version: '1.0.0-beta.23' }] } })
    await releaseChannelApi.status()
    expect(releaseChannelState.value?.update_available).toBe(true)
    ;(apiClient.post as any).mockResolvedValueOnce({ data: { enabled: true, update_available: false, latest: { version: '1.0.0-beta.23' }, newer: [] } })
    await releaseChannelApi.checkNow()
    expect(releaseChannelState.value?.update_available).toBe(false)
    expect(releaseChannelState.value?.newer).toEqual([])
  })

  it('a scheduled window and its removal reach the shared status too', async () => {
    ;(apiClient.put as any).mockResolvedValueOnce({ data: { enabled: true, update_available: true, newer: [{ version: '1.0.0-beta.24' }], schedule: { version: '1.0.0-beta.24', at: '2026-10-24T02:00:00Z' } } })
    await releaseChannelApi.schedule({ version: '1.0.0-beta.24', at: '2026-10-24T02:00:00Z' })
    expect(releaseChannelState.value?.schedule?.version).toBe('1.0.0-beta.24')
    ;(apiClient.delete as any).mockResolvedValueOnce({ data: { enabled: true, update_available: true, newer: [{ version: '1.0.0-beta.24' }], schedule: null } })
    await releaseChannelApi.unschedule()
    expect(releaseChannelState.value?.schedule).toBeNull()
  })

  it('a failed read leaves the status as it was (the control)', async () => {
    releaseChannelState.value = { enabled: true, update_available: false } as any
    ;(apiClient.get as any).mockRejectedValueOnce(new Error('502'))
    await expect(releaseChannelApi.status()).rejects.toThrow('502')
    expect(releaseChannelState.value?.update_available).toBe(false)
  })
})
