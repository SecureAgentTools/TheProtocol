import { describe, expect, it } from 'vitest'
import { failedSendOutcome, SendKey } from './sendOutcome'
import { LEDGER_SENTENCE, ROUTE_CAME_BACK, routeCameBackSentence } from '@/services/api/ledgerRefusal'

/**
 * §FESUITE (2026-10-05): a send that got no answer, or a 5xx, may have moved the value: it is unknown, never "failed", and
 * pressing again keeps the request's key (the server answers a repeat from its claim instead of paying twice).
 */
const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('a failed send', () => {
  it('a 4xx is the server refusing: nothing moved', () => {
    for (const s of [400, 401, 402, 403, 404, 409, 422, 429]) expect(failedSendOutcome(answered(s)), String(s)).toBe('refused')
  })
  it('no answer, or a 5xx, is unknown: the value may have moved', () => {
    expect(failedSendOutcome(Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }))).toBe('unknown')
    expect(failedSendOutcome(Object.assign(new Error('timeout of 30000ms exceeded'), { code: 'ECONNABORTED' }))).toBe('unknown')
    for (const s of [500, 502, 503, 504]) expect(failedSendOutcome(answered(s)), String(s)).toBe('unknown')
    expect(failedSendOutcome(null)).toBe('unknown')
  })
  it('the ledger gate refusal passed on whole is a refusal: the TEG says nothing moved (V0597)', () => {
    const gate = Object.assign(new Error('x'), { response: { status: 503, data: { detail: `ledger_unavailable: ${LEDGER_SENTENCE}` } } })
    expect(failedSendOutcome(gate)).toBe('refused')
    // a path that wrapped the words in its own may have moved something first: still unknown
    const wrapped = Object.assign(new Error('x'), { response: { status: 502, data: { detail: `order deposit failed: exchange mover 503: ledger_unavailable: ${LEDGER_SENTENCE}` } } })
    expect(failedSendOutcome(wrapped)).toBe('unknown')
    const other = Object.assign(new Error('x'), { response: { status: 503, data: { detail: 'Service temporarily unavailable' } } })
    expect(failedSendOutcome(other)).toBe('unknown')
  })
})

describe('the route that returned the payment (V0605)', () => {
  const said = (status: number, detail: unknown) => Object.assign(new Error('x'), { response: { status, data: { detail } } })
  it('the came-back sentence passed on whole is a refusal: the payment came back, the next press is a new request', () => {
    expect(failedSendOutcome(said(503, ROUTE_CAME_BACK))).toBe('refused')
    expect(routeCameBackSentence(said(503, ROUTE_CAME_BACK))).toBe(ROUTE_CAME_BACK)
  })
  it('anything else stays unknown: wrapped by an older registry, another status, a sentence that only quotes it', () => {
    const wrapped = JSON.stringify({ smart_send_method: 'fx', via: '/api/v1/teg/cross-registry-transfer', inner: ROUTE_CAME_BACK })
    for (const e of [said(503, wrapped), said(502, ROUTE_CAME_BACK), said(503, `${ROUTE_CAME_BACK} (and more)`),
                     said(503, 'Your payment came back to you.')]) {
      expect(failedSendOutcome(e)).toBe('unknown')
      expect(routeCameBackSentence(e)).toBeNull()
    }
  })
})

describe('an answer below 500 that may be the payment (V0606)', () => {
  const said = (status: number, detail: unknown) => Object.assign(new Error('x'), { response: { status, data: { detail } } })
  it('a 4xx that says the outcome is not known, or that money moved, keeps the key', () => {
    const held = 'FX route egress (outcome not known): nothing refunded, held for a ledger read (route_id=r, transfer_id=t)'
    const wrapped = { smart_send_method: 'fx', via: '/api/v1/teg/cross-registry-transfer', inner: held }
    for (const e of [said(409, held), said(409, wrapped), said(409, 'route r: the ingress is parked at the gateway'),
                     said(400, 'FX route failed post-conversion'), said(400, 'partial commit on the target'),
                     said(409, "Idempotency-Key 'k': an earlier request under this key ended without an answer (outcome not known)")]) {
      expect(failedSendOutcome(e)).toBe('unknown')
    }
  })
  it('a 422 for a key an earlier send still holds keeps the key', () => {
    expect(failedSendOutcome(said(422, "Idempotency-Key 'k' is claimed on this endpoint by an earlier request that is still in progress."))).toBe('unknown')
  })
  it('every other 4xx is still a refusal, its detail a string, an object or absent', () => {
    for (const e of [said(400, 'Insufficient balance'), said(402, { message: 'Insufficient balance' }), said(403, 'not allowed'),
                     said(409, 'FX route ingress refused (no funds moved)'), answered(404)]) {
      expect(failedSendOutcome(e)).toBe('refused')
    }
  })
})

describe('the send key', () => {
  it('stays for the same request until the server answered, and is new for another request', () => {
    let n = 0
    const k = new SendKey(() => `k${++n}`)
    expect(k.for('did:a|5|')).toBe('k1')
    expect(k.for('did:a|5|'), 'pressed again after an unknown outcome: the same key').toBe('k1')
    expect(k.for('did:a|6|'), 'another amount: another request').toBe('k2')
    k.answered()
    expect(k.for('did:a|6|'), 'after an answer, the next press is a new request').toBe('k3')
  })
})
