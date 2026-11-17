import { describe, it, expect, vi, beforeEach } from 'vitest'
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { distributionRows, distributionNote, releaseChannelApi, releaseChannelState } from './releaseChannel'

// V0667 D6 part 3 (gwo_fa3b8d7611f2573a2e63ac1c): the release view shows a frame its own distribution channel beside the public one.
// The governing registry serves a line only to the registries its signed index names; this frame's registry asks it for them.
const LINE = {
  name: 'V0667_lyceum', release: 'V0667', generated_at: '2026-11-16T19:05:00Z', published_at: '2026-11-16T19:06:00Z',
  images: { prefix: 'images.theprotocol.cloud/distributions/dist-v0667_lyceum', tag: 'V0667_lyceum',
            digests: { registry: 'sha256:' + '9'.repeat(64) } },
}

describe("a frame's own distribution channel", () => {
  beforeEach(() => { releaseChannelState.value = null; vi.clearAllMocks() })

  it('reads the frame-side route and leaves the public status alone', async () => {
    ;(apiClient.get as any).mockResolvedValueOnce({ data: { governing: 'EU', here: false, lines: [LINE], reason: null } })
    const ch = await releaseChannelApi.distributions()
    expect(apiClient.get).toHaveBeenCalledWith('/admin/release-channel/distributions')
    expect(ch.lines).toHaveLength(1)
    expect(releaseChannelState.value).toBeNull()
  })

  it('one row per line: its name, its release, when it was published, its image and a short digest', () => {
    const rows = distributionRows({ governing: 'EU', here: false, lines: [LINE], reason: null })
    expect(rows).toEqual([{ name: 'V0667_lyceum', release: 'V0667', publishedAt: '2026-11-16T19:06:00Z',
                            image: 'images.theprotocol.cloud/distributions/dist-v0667_lyceum', digest: 'sha256:999999999999' }])
    expect(distributionRows(null)).toEqual([])
    expect(distributionRows({ governing: 'EU', here: false, lines: [{ name: 'V0667_x' } as any], reason: null })[0])
      .toEqual({ name: 'V0667_x', release: '', publishedAt: null, image: '', digest: '' })
  })

  it('says why the list is empty, and nothing when it is not', () => {
    expect(distributionNote({ governing: 'EU', here: false, lines: [LINE], reason: null })).toBeNull()
    expect(distributionNote({ governing: 'EU', here: false, lines: [], reason: null })).toEqual({ kind: 'none', governing: 'EU' })
    expect(distributionNote({ governing: 'EU', here: false, lines: [], reason: 'EU could not be asked: timeout' }))
      .toEqual({ kind: 'reason', governing: 'EU', reason: 'EU could not be asked: timeout' })
    expect(distributionNote({ governing: null, here: false, lines: [], reason: 'no registry governs code on this network' }))
      .toEqual({ kind: 'reason', governing: null, reason: 'no registry governs code on this network' })
    expect(distributionNote(null)).toBeNull()
  })
})
