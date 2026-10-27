/** §OURSTATE-1 — the card brain's contract: closed vocabulary, honest unknown,
 *  defanging by construction, and the A2A answer extraction. */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { cardView, resultText, buildPayRequest, buildAgentCard, buildEngagementProposal, trimDecimal, displayAmount,
  APPLET_ACTIONS } from './cards'

const pay = { v: 1, type: 'pay.request', data: { amount: '12.5', currency: 'BVT', memo: 'lunch' } }

describe('cardView', () => {
  it('renders a pay.request with its fields', () => {
    const v = cardView(pay as any)
    expect(v).toMatchObject({ type: 'pay.request', amount: '12.5', currency: 'BVT', memo: 'lunch', defanged: false })
  })

  it('DEFANGS every card in a request-state thread — the flag zeroes the door here, so a renderer cannot forget', () => {
    const v = cardView(pay as any, { defang: true }) as any
    expect(v.defanged).toBe(true)
    const a = cardView({ v: 1, type: 'agent.card', data: { did: 'did:theprotocol:x' } } as any, { defang: true }) as any
    expect(a.defanged).toBe(true)
  })

  it('unknown type renders the honest fallback, never markup', () => {
    const v = cardView({ v: 1, type: 'evil.markup', data: { html: '<b>' } } as any)
    expect(v.type).toBe('unknown')
    expect((v as any).rawType).toBe('evil.markup')
  })

  it('wrong version is unknown too — v1 is the only card version this client speaks', () => {
    expect(cardView({ v: 2, type: 'pay.request', data: {} } as any).type).toBe('unknown')
    expect(cardView(null).type).toBe('unknown')
  })

  it('service.result carries the honest receipt fields', () => {
    const v = cardView({
      v: 1, type: 'service.result',
      data: {
        ok: true, stage: 'settled', summary: 'delivered',
        paid_amount: '0.60243', paid_currency: 'BVT', settlement_status: 'settled',
        result: { artifacts: [{ data: { summary: 'Berlin — 18°C, cloudy' } }] },
      },
      refs: { token_id: 'tok1', settlement_tx_id: 'tx1' },
    } as any) as any
    expect(v.ok).toBe(true)
    expect(v.paidAmount).toBe('0.60243')
    expect(v.settlementTxId).toBe('tx1')
    expect(v.resultText).toContain('Berlin')
  })
})

describe('resultText', () => {
  it('extracts artifacts[].data.summary (the §BUYSERVICE rule)', () => {
    expect(resultText({ artifacts: [{ data: { summary: 'the answer' } }] })).toBe('the answer')
  })
  it('reaches artifacts one JSON-RPC level down — the live rail shape (FE battery 5b caught the miss)', () => {
    expect(resultText({ jsonrpc: '2.0', id: 1, result: { artifacts: [{ data: { summary: 'Lisbon — 21°C' } }] } }))
      .toBe('Lisbon — 21°C')
  })
  it('falls back to message parts text', () => {
    expect(resultText({ message: { parts: [{ text: 'part answer' }] } })).toBe('part answer')
  })
  it('handles the truncated shape', () => {
    expect(resultText({ truncated: true, preview: 'long…' })).toBe('long…')
  })
  it('absence is empty, never a throw', () => {
    expect(resultText(null)).toBe('')
    expect(resultText({ artifacts: [{}] })).toBe('')
  })
})

describe('builders', () => {
  it('buildPayRequest produces the server-valid envelope', () => {
    const c = buildPayRequest('12.5', 'BVT', ' lunch ')
    expect(c).toEqual({ v: 1, type: 'pay.request', data: { amount: '12.5', currency: 'BVT', memo: 'lunch' } })
  })
  it('buildAgentCard carries the did', () => {
    expect(buildAgentCard('did:theprotocol:x', 'SYBIL').data).toEqual({ did: 'did:theprotocol:x', name: 'SYBIL' })
  })
})

describe('§OURSTATE-5e/5f — media pointers and declarative applets', () => {
  const view = (type: string, data: any, ctx: any = {}) =>
    cardView({ v: 1, type, data } as any, ctx)

  it('renders a media POINTER with no bytes and no url', () => {
    const v: any = view('media', {
      attachment_id: 'att-1', name: 'plan.pdf', mime: 'application/pdf', bytes: 2048 })
    expect(v.type).toBe('media')
    expect(v.attachmentId).toBe('att-1')
    expect(v.human).toBe('2.0 KB')
    // The view cannot carry a link: the download is a fetch by id.
    expect(JSON.stringify(v)).not.toMatch(/https?:\/\//)
  })

  it('drops applet fields whose kind is not in the closed set', () => {
    const v: any = view('applet', {
      title: 'Book', action: { kind: 'open_work' },
      fields: [
        { kind: 'text', key: 'a', label: 'A' },
        { kind: 'file', key: 'b', label: 'Upload' },     // not in the set
        { kind: 'iframe', key: 'c', label: 'Embed' },    // not in the set
      ] })
    expect(v.fields.map((f: any) => f.key)).toEqual(['a'])
  })

  it('renders NO action when the action kind is unknown', () => {
    const v: any = view('applet', {
      title: 'Sneaky', action: { kind: 'POST /teg/transfer', label: 'Send' } })
    expect(v.action.kind).toBe('')
  })

  it('drops a prefilled amount that has no currency', () => {
    const bare: any = view('applet', { title: 'Pay', action: { kind: 'open_pay', amount: '20' } })
    expect(bare.action.amount).toBeNull()
    expect(bare.action.currency).toBeNull()
    const full: any = view('applet', {
      title: 'Pay', action: { kind: 'open_pay', amount: '20', currency: 'BVT' } })
    expect(full.action.amount).toBe('20')
    expect(full.action.currency).toBe('BVT')
  })

  it('keeps open_trade, the order ticket the server accepts and the Pocket thread opens (D6-553)', () => {
    const v: any = view('applet', {
      title: 'Trade BLD0', action: { kind: 'open_trade', label: 'Open the ticket' },
      fields: [{ kind: 'text', key: 'symbol', label: 'Symbol' }] })
    expect(v.action.kind).toBe('open_trade')
    expect(v.action.label).toBe('Open the ticket')
  })

  it("re-applies exactly the server's closed list of doors (services/chat_applet.py ACTIONS)", () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../../../../services/chat_applet.py'), 'utf8')
    const at = src.indexOf('ACTIONS = {')
    const server = [...src.slice(at, src.indexOf('}', at)).matchAll(/^\s*"(\w+)":/gm)].map((m) => m[1])
    expect(server.length).toBeGreaterThanOrEqual(5)   // a scan over nothing passes loudest
    expect([...APPLET_ACTIONS].sort()).toEqual(server.sort())
  })

  it('bounds what an applet can render', () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ kind: 'text', key: `k${i}`, label: 'x' }))
    const v: any = view('applet', { title: 'x'.repeat(500), action: { kind: 'open_work' }, fields: many })
    expect(v.fields.length).toBe(8)
    expect(v.title.length).toBe(120)
  })
})

/* §OURSTATE-6 — the payload behind a tap, and the receipt that must not freeze. */
describe('§OURSTATE-6 service.result payload', () => {
  const envelope = (data: any) => ({
    jsonrpc: '2.0', id: '1',
    result: { id: 'task-1', state: 'TASK_STATE_COMPLETED',
              artifacts: [{ type: 'application/json', name: 'r', data: { summary: 'Ash: Δ 0 — OK.', data } }] },
  })
  const card = (extra: any = {}) => ({
    v: 1 as const, type: 'service.result',
    data: { ok: true, stage: 'settled', summary: 'delivered',
            paid_amount: '2.000000', paid_currency: 'BVT', settlement_status: 'settling',
            result: envelope({ delta: '0', scope_note: 'what it does not cover' }),
            result_truncated: false, error: '', ...extra },
    refs: { token_id: 'tok-1' },
  })

  it('extracts the agent’s own object, not the JSON-RPC envelope', () => {
    const v: any = cardView(card() as any)
    expect(v.payload).toEqual({ delta: '0', scope_note: 'what it does not cover' })
    // …and the one-line summary is still what the card leads with.
    expect(v.resultText).toBe('Ash: Δ 0 — OK.')
  })

  it('offers NO payload when the answer was truncated — half an answer is not the answer', () => {
    const v: any = cardView(card({ result_truncated: true }) as any)
    expect(v.payload).toBeNull()
  })

  it('carries the stored settlement word verbatim; the card decides what to show', () => {
    const v: any = cardView(card() as any)
    expect(v.settlementStatus).toBe('settling')
    expect(v.stage).toBe('settled')
  })
})

// ── §OURCHAT-ORG: a price a person can read ─────────────────────────────────
describe('trimDecimal', () => {
  it('strips insignificant trailing zeros without rounding', () => {
    expect(trimDecimal('1.500000000000000000')).toBe('1.5')
    expect(trimDecimal('20.00')).toBe('20')
    expect(trimDecimal('51.000000000000000000')).toBe('51')
  })
  it('never touches significant digits', () => {
    expect(trimDecimal('0.000001')).toBe('0.000001')
    expect(trimDecimal('100')).toBe('100')
    expect(trimDecimal('1000')).toBe('1000')   // trailing zeros BEFORE the point stay
    expect(trimDecimal('-2.50')).toBe('-2.5')
  })
  it('returns anything that is not a plain decimal unchanged', () => {
    expect(trimDecimal('1e18')).toBe('1e18')
    expect(trimDecimal('abc')).toBe('abc')
    expect(trimDecimal('')).toBe('')
  })
})

describe('exchange.listing view', () => {
  it('is a pointer with a readable price', () => {
    const v: any = cardView({ v: 1, type: 'exchange.listing',
      data: { symbol: 'weyl', display_name: 'Weyland-Yutani',
              last_price: '1.500000000000000000', currency: 'BVT' } })
    expect(v.type).toBe('exchange.listing')
    expect(v.symbol).toBe('WEYL')          // the address is normalised
    expect(v.lastPrice).toBe('1.5')
    expect(v.currency).toBe('BVT')
    // and it carries nothing that could act
    expect((v as any).side).toBeUndefined()
    expect((v as any).qty).toBeUndefined()
  })
})

// ── §DEALTHREADS (O-D) — the engagement family ──────────────────────────────
describe('engagement cards', () => {
  it('proposal renders terms; a stated total travels with its currency or not at all', () => {
    const v: any = cardView({ v: 1, type: 'engagement.proposal',
      data: { title: 'Digitize the ledger', total: '2.50', currency: 'BVT', note: 'scope note',
              milestones: [{ title: 'Scan', amount: '1.0' }, { title: 'Index' }] } })
    expect(v.type).toBe('engagement.proposal')
    expect(v.title).toBe('Digitize the ledger')
    expect(v.total).toBe('2.5')
    expect(v.currency).toBe('BVT')
    expect(v.milestones.length).toBe(2)
    // §FOREIGNACT — total WITHOUT currency is dropped whole, never half-rendered
    const half: any = cardView({ v: 1, type: 'engagement.proposal',
      data: { title: 'x', total: '2.50' } })
    expect(half.total).toBeNull()
    expect(half.currency).toBeNull()
  })
  it('counter carries what it supersedes', () => {
    const v: any = cardView({ v: 1, type: 'engagement.counter',
      data: { title: 'Cheaper' }, refs: { supersedes: 'msg-123' } })
    expect(v.type).toBe('engagement.counter')
    expect(v.supersedes).toBe('msg-123')
  })
  it('proposal defangs in request-state threads (doors suppressed, terms readable)', () => {
    const v: any = cardView({ v: 1, type: 'engagement.proposal',
      data: { title: 'From a stranger' } }, { defang: true })
    expect(v.defanged).toBe(true)
    expect(v.title).toBe('From a stranger')
  })
  it('offer carries contract id, TTL and the provider home when cross-frame', () => {
    const v: any = cardView({ v: 1, type: 'engagement.offer',
      data: { contract_id: 'ctr_abc', title: 'Job', total: '2.000000', currency: 'BVT',
              provider_did: 'did:x', provider_home: 'frame-b',
              offer_expires_at: '2026-09-01T00:00:00Z' } })
    expect(v.type).toBe('engagement.offer')
    expect(v.contractId).toBe('ctr_abc')
    expect(v.total).toBe('2')
    expect(v.providerHome).toBe('frame-b')
    expect(v.offerExpiresAt).toContain('2026-09-01')
  })
  it('settled is a terminal receipt with amount+currency whole', () => {
    const v: any = cardView({ v: 1, type: 'engagement.settled',
      data: { contract_id: 'ctr_abc', seq: 1, amount: '1.95', currency: 'BVT', completed: true } })
    expect(v.type).toBe('engagement.settled')
    expect(v.completed).toBe(true)
    expect(v.amount).toBe('1.95')
  })
})

describe('buildEngagementProposal', () => {
  it('builds a proposal, and a counter when supersedes is given', () => {
    const p = buildEngagementProposal({ title: 'T', total: '2', currency: 'BVT' })
    expect(p.type).toBe('engagement.proposal')
    expect(p.data.total).toBe('2')
    const c = buildEngagementProposal({ title: 'T2', supersedes: 'msg-9' })
    expect(c.type).toBe('engagement.counter')
    expect(c.refs?.supersedes).toBe('msg-9')
    // no currency → the total is not smuggled in half
    const h = buildEngagementProposal({ title: 'T3', total: '5' })
    expect(h.data.total).toBeUndefined()
  })
})

/* §CHATCOHERE (2026-09-01) — `displayAmount`, the rule that keeps a ledger
   balance readable. The confirm sheet printed `You hold 0E-18 BVT.` because
   `trimDecimal` passes non-plain-decimals through untouched and the TEG answers
   in scientific notation. Twenty green browser assertions passed over it: every
   one asked whether a number was PRESENT, none asked whether it was readable. */
describe('displayAmount', () => {
  it('renders the ledger zero as a zero, not as an exponent', () => {
    expect(displayAmount('0E-18')).toBe('0')
  })
  it('expands a positive exponent', () => {
    expect(displayAmount('1E+3')).toBe('1000')
  })
  it('leaves a plain decimal exactly as trimDecimal would', () => {
    expect(displayAmount('2.5000000000')).toBe('2.5')
    expect(displayAmount('0.000001')).toBe('0.000001')
    expect(displayAmount('100')).toBe('100')
  })
  it('never invents a value it cannot read', () => {
    expect(displayAmount(null)).toBe('')
    expect(displayAmount('')).toBe('')
    expect(displayAmount('not-a-number')).toBe('not-a-number')  // verbatim, never reshaped
  })
  it('keeps full precision for a plain decimal (the lossy path is exponent-only)', () => {
    expect(displayAmount('123.456789012345678901')).toBe('123.456789012345678901')
  })
})
