/**
 * V0662 console polish, item 7: the panel's liveness row shows the service line in words, never the checker's raw
 * outcome. Red on f569f6a6e: "endpoint probe: unreachable" for an agent whose card declares no live service.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ fetchTrackRecord: vi.fn(), fetchReceipt: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/composables/useEngageDoors', () => ({ useEngageDoors: () => ({ doors: ref([]), draft: ref(null) }) }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/services/api/trackRecord', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api/trackRecord')>()),
  fetchTrackRecord: h.fetchTrackRecord,
  fetchReceipt: h.fetchReceipt,
}))

import TrackRecordPanel from './TrackRecordPanel.vue'

const record = (liveness: Record<string, unknown>) => ({
  summary: { avg_stars: 5, cross_registry_jobs: 0, disputes: { total: 0 }, jobs_verified: 1, on_time: { met: 1, of: 1 }, repeat_poster_jobs: 0, volume: [] },
  attested_by: { registry: 'sbx-beta' },
  liveness,
  recent: [],
})

async function panel(liveness: Record<string, unknown>) {
  h.fetchTrackRecord.mockResolvedValue(record(liveness))
  const w = mount(TrackRecordPanel, { props: { did: 'did:theprotocol:a1' } })
  await flushPromises()
  return w
}

describe('the track record\'s service line', () => {
  beforeEach(() => { h.fetchTrackRecord.mockReset() })

  it('no live service declared: said in words, the probe outcome only on the hover', async () => {
    const w = await panel({ probe: 'unreachable', last_seen: null, live_24h: false, service_declared: false })
    try {
      const line = w.find('[data-testid="trp-service"]')
      expect(line.text()).toContain('no live service declared')
      expect(line.attributes('data-service')).toBe('none')
      expect(w.find('[data-testid="trp-liveness"]').text()).not.toContain('unreachable')
    } finally { w.unmount() }
  })

  it('a declared service that does not answer', async () => {
    const w = await panel({ probe: 'unreachable', last_seen: null, live_24h: false, service_declared: true })
    try {
      const line = w.find('[data-testid="trp-service"]')
      expect(line.text()).toContain('service not answering')
      expect(line.attributes('data-service')).toBe('down')
      expect(line.attributes('title')).toContain('unreachable')
    } finally { w.unmount() }
  })
})
