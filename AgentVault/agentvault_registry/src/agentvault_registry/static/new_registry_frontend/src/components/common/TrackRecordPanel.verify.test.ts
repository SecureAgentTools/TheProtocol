/**
 * §FESUITE (V0577): "could not verify is not invalid" (CLAUDE.md PART 1). The Track Record's in-browser receipt check
 * read FAILED ("verification error", in the late colour) when the receipt could not even be fetched. A receipt read
 * that got no answer, or a server error, now leaves the receipt unchecked and offers the check again; the registry's
 * own refusal of the receipt (a 4xx) is still a failure.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

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

const record = {
  summary: { avg_stars: 5, cross_registry_jobs: 0, disputes: { total: 0 }, jobs_verified: 1, on_time: { met: 1, of: 1 }, repeat_poster_jobs: 0, volume: [] },
  attested_by: { registry: 'sbx-beta' },
  liveness: null,
  recent: [{ order_id: 'o1', kind: 'local', contract_id: 'ctr-0001-abcdefgh', title: 'Index the ledger', stars: 5, bounty: '1', currency: 'ECU', on_time: true, settled_at: '2026-10-01T00:00:00Z' }],
}

async function verifyOnce(receiptAnswer: () => Promise<unknown>) {
  h.fetchTrackRecord.mockResolvedValue(record)
  h.fetchReceipt.mockImplementation(receiptAnswer)
  const w = mount(TrackRecordPanel, { props: { did: 'did:theprotocol:a1' } })
  await flushPromises()
  await w.find('[data-testid="trp-verify-o1"]').trigger('click')
  await flushPromises()
  return w
}

describe('the Track Record receipt check when the receipt cannot be fetched', () => {
  beforeEach(() => { h.fetchTrackRecord.mockReset(); h.fetchReceipt.mockReset() })

  it('no answer: the receipt is unchecked (no FAILED), and the check is offered again', async () => {
    const w = await verifyOnce(() => Promise.reject(new AxiosError('Network Error', 'ERR_NETWORK')))
    const btn = w.find('[data-testid="trp-verify-o1"]')
    expect(btn.text()).not.toContain('FAILED')
    expect(btn.text()).toContain('Verify receipt')
    expect(w.text()).toContain('could not be read')
  })

  it('a server error: unchecked too', async () => {
    const w = await verifyOnce(() => Promise.reject(new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
      { status: 502, data: '', statusText: '', headers: {}, config: {} as any })))
    expect(w.find('[data-testid="trp-verify-o1"]').text()).not.toContain('FAILED')
  })

  it("the registry's own refusal of the receipt (404) is still a failure", async () => {
    const w = await verifyOnce(() => Promise.reject(new AxiosError('Request failed with status code 404', 'ERR_BAD_REQUEST', undefined, undefined,
      { status: 404, data: { detail: 'no receipt' }, statusText: '', headers: {}, config: {} as any })))
    expect(w.find('[data-testid="trp-verify-o1"]').text()).toContain('FAILED')
  })
})
