import { describe, expect, it } from 'vitest'
import { AxiosHeaders, type AxiosInstance } from 'axios'
import { answeredAgain, markReplayed, REPLAYED_HEADER, sendReference } from './sendOutcome'
import { TegApi } from '@/services/api/teg'

/**
 * §REPATLANE-7 (after V0606): journal 51's figures (Sandbox Alpha, 2026-10-12 22:18Z) showed Pocket's sheet saying
 * "Sent — confirmed" for a payment it had a reference for. /teg/send answers the reference as transfer_id (routers/
 * teg_send.py SmartSendResponse; tests/test_kept_replay_mark.py pins that side) and the console read transaction_id,
 * which that answer never carries, so a receipt had no reference: a priced contact opens its thread with it, and paying
 * one from Pocket moved the money and then said it "returned no reference". The registry's mark on an answer it gives
 * again under the same key (the first press's payment) reached no screen either.
 */
const TX = '4e56d624-b776-460f-9dbc-83b64efdacd7'
const SMART = { ok: true, method: 'local', status: 'completed', transfer_id: TX, detail: { transaction_id: TX, status: 'completed' } }

describe('the reference of a sent payment', () => {
  it('is the smart send answer\'s transfer_id', () => {
    expect(sendReference(SMART)).toBe(TX)
  })
  it('falls back to a transaction_id, then to the inner answer', () => {
    expect(sendReference({ transaction_id: 'tx-2' })).toBe('tx-2')
    expect(sendReference({ transfer_id: '', detail: { transaction_id: 'tx-3' } })).toBe('tx-3')
    expect(sendReference({ detail: { swap_id: 'swap-4' } })).toBe('swap-4')
  })
  it('is empty when the answer names none', () => {
    for (const a of [null, undefined, 'tx', 7, {}, { transfer_id: '  ' }, { detail: 'x' }]) expect(sendReference(a), String(a)).toBe('')
  })
})

describe('an answer the registry gave again', () => {
  it('is marked from axios headers and from a plain object', () => {
    expect(answeredAgain(markReplayed(SMART, new AxiosHeaders({ 'Idempotent-Replayed': 'true' })))).toBe(true)
    expect(answeredAgain(markReplayed(SMART, { [REPLAYED_HEADER]: 'true' }))).toBe(true)
    expect(answeredAgain(markReplayed(SMART, { 'Idempotent-Replayed': 'TRUE' }))).toBe(true)
  })
  it('control: a first answer is not marked, and the answer itself is untouched', () => {
    expect(answeredAgain(markReplayed(SMART, new AxiosHeaders({})))).toBe(false)
    expect(answeredAgain(markReplayed(SMART, { [REPLAYED_HEADER]: 'false' }))).toBe(false)
    expect(answeredAgain(markReplayed(SMART, undefined))).toBe(false)
    const marked = markReplayed(SMART, { [REPLAYED_HEADER]: 'true' })
    expect(marked).not.toBe(SMART)
    expect('replayed' in SMART).toBe(false)
    expect(sendReference(marked)).toBe(TX)
  })
  it('the smart send marks an answer that came with the header', async () => {
    const seen: unknown[] = []
    const client = {
      post: async (url: string, body: unknown, cfg: { headers: Record<string, string> }) => {
        seen.push([url, cfg.headers['Idempotency-Key']])
        return { data: { ...SMART }, headers: new AxiosHeaders(seen.length > 1 ? { 'Idempotent-Replayed': 'true' } : {}) }
      },
    } as unknown as AxiosInstance
    const api = new TegApi(client)
    const first = await api.smartSend({ receiver_did: 'did:theprotocol:r', amount: '0.5' }, { idempotencyKey: 'k1' })
    const again = await api.smartSend({ receiver_did: 'did:theprotocol:r', amount: '0.5' }, { idempotencyKey: 'k1' })
    expect(answeredAgain(first)).toBe(false)
    expect(answeredAgain(again)).toBe(true)
    expect(sendReference(again)).toBe(TX)
    expect(seen).toEqual([['/teg/send', 'k1'], ['/teg/send', 'k1']])
  })
})
