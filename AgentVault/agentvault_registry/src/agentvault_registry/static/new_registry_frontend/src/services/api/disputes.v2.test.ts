/**
 * V0657 (a), disputes v2: what the console sends and reads.
 *  - item 5: the ruler's reason was asked for and never sent (updateRuling sent only `ruling`); it travels in the body
 *    now, with the ruling (also as the query parameter an older registry reads) and a Guild order's worker share;
 *  - item 6: any of the three rulings (the console could send only two);
 *  - item 2: the amount claimed is the filing's own field (amount_claimed), never a key in the first evidence;
 *  - item 10: "Contract dispute" labelled every dispute that carried no evidence; the record's reason_text says why;
 *  - the preview, the correction and the ruler's queue have their calls.
 * RED on origin/v0656/cut: updateRuling(id, notes, resolution) sends no body, the reason is the evidence's, and the
 * other calls do not exist.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const h = vi.hoisted(() => ({ put: vi.fn(), get: vi.fn(), post: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { put: h.put, get: h.get, post: h.post } }))

import { disputesApi } from './disputes'

const raw = (over: Record<string, any> = {}) => ({
  id: 12, status: 'OPEN', ruling: null, complainant_did: 'did:theprotocol:eu:poster', defendant_did: 'did:theprotocol:eu:worker',
  evidence: [], created_at: '2026-11-06T10:00:00Z', updated_at: '2026-11-06T10:00:00Z', ...over,
})

describe('disputes v2 in the console', () => {
  beforeEach(() => { h.put.mockReset(); h.get.mockReset(); h.post.mockReset() })

  it('a ruling carries the reason and the worker share in its body, the ruling also as the query', async () => {
    h.put.mockResolvedValue({ data: raw({ status: 'CLOSED', ruling: 'IN_FAVOR_OF_DEFENDANT', outcome: { money: null } }) })
    const out = await disputesApi.updateRuling('12', 'IN_FAVOR_OF_DEFENDANT', 'It delivered on time.', 1)
    expect(h.put).toHaveBeenCalledWith('/admin/disputes/12/ruling',
      { ruling: 'IN_FAVOR_OF_DEFENDANT', note: 'It delivered on time.', worker_share: 1 }, { params: { ruling: 'IN_FAVOR_OF_DEFENDANT' } })
    expect(out.outcome).toEqual({ money: null })
  })

  it('no worker share is sent unless one was set', async () => {
    h.put.mockResolvedValue({ data: raw() })
    await disputesApi.updateRuling('12', 'DISMISSED', 'No case.')
    expect(h.put.mock.calls[0][1]).toEqual({ ruling: 'DISMISSED', note: 'No case.' })
  })

  it('the preview, the correction and the queue ask the routes they name', async () => {
    h.get.mockResolvedValue({ data: { items: [] } })
    h.post.mockResolvedValue({ data: { dispute_id: 31 } })
    await disputesApi.previewRuling('12', 'IN_FAVOR_OF_COMPLAINANT', 0.25)
    expect(h.get).toHaveBeenLastCalledWith('/admin/disputes/12/preview', { params: { ruling: 'IN_FAVOR_OF_COMPLAINANT', worker_share: 0.25 } })
    await disputesApi.previewCorrection('1', 'IN_FAVOR_OF_DEFENDANT')
    expect(h.get).toHaveBeenLastCalledWith('/admin/disputes/1/correction-preview', { params: { ruling: 'IN_FAVOR_OF_DEFENDANT' } })
    await disputesApi.correctRuling('1', 'IN_FAVOR_OF_DEFENDANT', 'It delivered and was paid.')
    expect(h.post).toHaveBeenLastCalledWith('/admin/disputes/1/correct', { ruling: 'IN_FAVOR_OF_DEFENDANT', note: 'It delivered and was paid.' })
    await disputesApi.rulerQueue()
    expect(h.get).toHaveBeenLastCalledWith('/admin/disputes/queue')
    expect(await disputesApi.fileQueueRecord('guild', 'gwo_x')).toEqual({ dispute_id: 31 })
    expect(h.post).toHaveBeenLastCalledWith('/admin/disputes/queue/guild/gwo_x/record')
  })

  it('a correction a failure left applying is finished on its own route (session-lead, room seq 1597)', async () => {
    h.post.mockResolvedValue({ data: { status: 'applied', correction_id: 3 } })
    expect(await disputesApi.finishCorrection('1', 3)).toEqual({ status: 'applied', correction_id: 3 })
    expect(h.post).toHaveBeenLastCalledWith('/admin/disputes/1/corrections/3/finish')
  })

  it('a filing claims its amount in its own field, and its first evidence carries none', async () => {
    h.post.mockImplementation(async (url: string, body: any) => (url === '/disputes/' ? { data: raw() } : { data: { id: 1, dispute_id: 12, submitter_did: 'x', evidence_data: body.evidence_data, created_at: 'now' } }))
    await disputesApi.createDispute({ complainant_did: 'did:a', defendant_did: 'did:b', category: 'other', description: 'Paid, not delivered', amount_disputed: 40 })
    expect(h.post.mock.calls[0][1]).toMatchObject({ amount_claimed: 40 })
    const evidence = h.post.mock.calls[1][1].evidence_data
    expect(evidence.amount_disputed, 'the amount travels with the filing, never in evidence').toBeUndefined()
  })

  it('the record says why it opened, who filed it and who is who', async () => {
    h.get.mockResolvedValue({ data: raw({ reason: 'deadline_missed', reason_text: 'The worker handed nothing in by the deadline',
      filed_by: 'system', guild_order_id: 'gwo_x', complainant_name: 'session-lead', defendant_name: 'session-tester',
      ruling_note: 'n', guild_order: { id: 'gwo_x', handed_in: false } }) })
    const d = await disputesApi.getDispute('12')
    expect(d.reason).toBe('The worker handed nothing in by the deadline')
    expect([d.reason_code, d.filed_by, d.guild_order_id]).toEqual(['deadline_missed', 'system', 'gwo_x'])
    expect([d.claimant_name, d.respondent_name]).toEqual(['session-lead', 'session-tester'])
    expect(d.guild_order?.handed_in).toBe(false)
  })

  it('a dispute without a reason is no longer labelled a contract dispute', async () => {
    h.get.mockResolvedValue({ data: raw() })
    const d = await disputesApi.getDispute('12')
    expect(d.reason).not.toBe('Contract dispute')
  })
})
