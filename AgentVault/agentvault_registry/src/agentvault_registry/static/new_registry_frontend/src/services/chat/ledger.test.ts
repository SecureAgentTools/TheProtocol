// §OURSTATE-2 /ledger — local-only, currency-honest, bounds-stating.
import { describe, it, expect } from 'vitest'
import { buildLedger, type LedgerMessageLike } from './ledger'

const card = (type: string, data: any, seq: number, mine: boolean): LedgerMessageLike & { _mine: boolean } =>
  ({ seq, kind: 'card', card: { v: 1, type, data }, _mine: mine } as any)
const mineOf = (m: any) => !!m._mine

describe('buildLedger', () => {
  it('an empty thread is EMPTY, not a row of zeroes', () => {
    const l = buildLedger([{ seq: 1, kind: 'text' }], mineOf)
    expect(l.empty).toBe(true)
    expect(l.lines).toEqual([])
    expect(l.counted).toBe(0)
  })

  it('receipts net out per direction', () => {
    const l = buildLedger([
      card('pay.receipt', { amount: '10', currency: 'BVT' }, 1, true),
      card('pay.receipt', { amount: '4', currency: 'BVT' }, 2, false),
    ], mineOf)
    const bvt = l.lines[0]
    expect(bvt.paidByYou).toBe(10)
    expect(bvt.paidToYou).toBe(4)
    expect(bvt.net).toBe(-6)     // you are 6 ahead in their favour
  })

  it('NEVER sums across currencies — one line each', () => {
    const l = buildLedger([
      card('pay.receipt', { amount: '10', currency: 'BVT' }, 1, true),
      card('pay.receipt', { amount: '3', currency: 'AVT' }, 2, true),
    ], mineOf)
    expect(l.lines.map(x => x.currency)).toEqual(['AVT', 'BVT'])
    expect(l.lines.find(x => x.currency === 'AVT')!.paidByYou).toBe(3)
    expect(l.lines.find(x => x.currency === 'BVT')!.paidByYou).toBe(10)
  })

  it('requests are OPEN items and are never counted as paid', () => {
    const l = buildLedger([card('pay.request', { amount: '7', currency: 'BVT', memo: 'invoice' }, 1, false)], mineOf)
    const line = l.lines[0]
    expect(line.paidByYou).toBe(0)
    expect(line.requestedOfYou).toBe(7)
    expect(l.open[0]).toMatchObject({ kind: 'pay.request', amount: '7', currency: 'BVT', mine: false })
  })

  it('a delivered-but-unsettled call is OPEN, never counted as paid', () => {
    const l = buildLedger([
      card('service.result', { ok: true, paid_amount: '0.6', paid_currency: 'BVT', settlement_status: 'failed' }, 1, true),
    ], mineOf)
    expect(l.lines).toEqual([])
    expect(l.open[0]).toMatchObject({ kind: 'service.call', amount: '0.6', currency: 'BVT' })
  })

  it('a SETTLED call counts', () => {
    const l = buildLedger([
      card('service.result', { ok: true, paid_amount: '0.6', paid_currency: 'BVT', settlement_status: 'settled' }, 1, true),
    ], mineOf)
    expect(l.lines[0].paidByYou).toBeCloseTo(0.6)
    expect(l.open).toEqual([])
  })

  it('WORK pointers land as open items carrying their ref', () => {
    const l = buildLedger([
      card('guild.order', { ref: 'ord_1', title: 'Translate the handbook', amount: '5', currency: 'BVT' }, 1, true),
      card('contract.offer', { ref: 'ctr_9', title: 'Quarterly audit' }, 2, false),
    ], mineOf)
    expect(l.open.map(o => o.ref)).toEqual(['ord_1', 'ctr_9'])
    expect(l.open[0].mine).toBe(true)
  })

  it('burned/deleted rows are excluded outright', () => {
    const del = { ...card('pay.receipt', { amount: '99', currency: 'BVT' }, 1, true), deleted: true }
    const l = buildLedger([del as any], mineOf)
    expect(l.empty).toBe(true)
  })

  it('STATES ITS BOUND — a full page is clipped', () => {
    const msgs = Array.from({ length: 40 }, (_, i) => card('pay.receipt', { amount: '1', currency: 'BVT' }, i + 1, true))
    const l = buildLedger(msgs, mineOf, 40)
    expect(l.bounds.messages).toBe(40)
    expect(l.bounds.clipped).toBe(true)
    expect(l.bounds.firstSeq).toBe(1)
    expect(l.bounds.lastSeq).toBe(40)
  })

  it('…and a gap in seq numbers (burn) also reads as clipped', () => {
    const l = buildLedger([
      card('pay.receipt', { amount: '1', currency: 'BVT' }, 1, true),
      card('pay.receipt', { amount: '1', currency: 'BVT' }, 9, true),
    ], mineOf, 40)
    expect(l.bounds.clipped).toBe(true)
  })

  it('a short intact page is NOT clipped (the honest positive case)', () => {
    const l = buildLedger([
      card('pay.receipt', { amount: '1', currency: 'BVT' }, 1, true),
      card('pay.receipt', { amount: '1', currency: 'BVT' }, 2, true),
    ], mineOf, 40)
    expect(l.bounds.clipped).toBe(false)
  })

  it('a receipt without a currency is skipped, never assigned one', () => {
    const l = buildLedger([card('pay.receipt', { amount: '5' }, 1, true)], mineOf)
    expect(l.lines).toEqual([])
  })
})
