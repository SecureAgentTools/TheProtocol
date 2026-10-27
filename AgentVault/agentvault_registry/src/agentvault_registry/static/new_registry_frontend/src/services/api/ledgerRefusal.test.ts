import { describe, it, expect } from 'vitest'
import { isLedgerRefusalAsItCame, ledgerRefusalSentence, LEDGER_SENTENCE, wholeLedgerRefusalSentence } from './ledgerRefusal'

/**
 * §LEDGERGATE (2026-10-11): the TEG's ledger refusal is recognised wherever the registry kept its words, and nothing
 * else is (a 503 from a TEG that is down claims nothing about what moved).
 */
const err = (status: number, data: unknown) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } })
const DETAIL = `ledger_unavailable: ${LEDGER_SENTENCE}`

describe('ledgerRefusalSentence', () => {
  it('reads the sentence the registry passed on as it came', () => {
    expect(ledgerRefusalSentence(err(503, { detail: DETAIL }))).toBe(LEDGER_SENTENCE)
  })
  it('finds it inside the words of a path that wraps the TEG text (the AGORA order deposit)', () => {
    const wrapped = `order deposit failed: exchange mover 503: ${DETAIL}`
    expect(ledgerRefusalSentence(err(502, { detail: wrapped }))).toBe(LEDGER_SENTENCE)
  })
  it('falls back to the sentence when only the code says so', () => {
    expect(ledgerRefusalSentence(err(503, { detail: { x: 1 }, code: 'ledger_unavailable' }))).toBe(LEDGER_SENTENCE)
  })
  it('is null for every other failure', () => {
    expect(ledgerRefusalSentence(err(503, { detail: 'Service temporarily unavailable' }))).toBeNull()
    expect(ledgerRefusalSentence(err(500, { detail: 'Internal Server Error' }))).toBeNull()
    expect(ledgerRefusalSentence(err(503, '<html>bad gateway</html>'))).toBeNull()
    expect(ledgerRefusalSentence(new Error('network'))).toBeNull()
    expect(ledgerRefusalSentence(null)).toBeNull()
  })
  it('cuts the sentence clean out of a detail a route wrapped in its own JSON (V0597; V0596 read the quote and brace)', () => {
    // V0596's /teg/send: the error layer JSON-dumps the smart send's dict
    const smartSend = JSON.stringify({ smart_send_method: 'local', via: '/api/v1/teg/transfer', inner: DETAIL })
    expect(ledgerRefusalSentence(err(503, { detail: smartSend }))).toBe(LEDGER_SENTENCE)
    expect(ledgerRefusalSentence(err(503, { detail: `{'inner': '${DETAIL}'}` }))).toBe(LEDGER_SENTENCE)
    expect(ledgerRefusalSentence(err(503, { detail: JSON.stringify({ a: [DETAIL] }) }))).toBe(LEDGER_SENTENCE)
  })
})

describe('isLedgerRefusalAsItCame', () => {
  it('is the gate refusal passed on whole: a 503 whose detail starts with the marker, or the gate code', () => {
    expect(isLedgerRefusalAsItCame(err(503, { detail: DETAIL }))).toBe(true)
    expect(isLedgerRefusalAsItCame(err(503, { detail: `  ${DETAIL}` }))).toBe(true)
    expect(isLedgerRefusalAsItCame(err(503, { detail: 'x', code: 'ledger_unavailable' }))).toBe(true)
  })
  it('is not a path that wrapped the words in its own (something else may have moved), nor any other failure', () => {
    expect(isLedgerRefusalAsItCame(err(502, { detail: `order deposit failed: exchange mover 503: ${DETAIL}` }))).toBe(false)
    expect(isLedgerRefusalAsItCame(err(503, { detail: JSON.stringify({ inner: DETAIL }) }))).toBe(false)
    expect(isLedgerRefusalAsItCame(err(409, { detail: DETAIL }))).toBe(false)
    expect(isLedgerRefusalAsItCame(err(503, { detail: 'Service temporarily unavailable' }))).toBe(false)
    expect(isLedgerRefusalAsItCame(new Error('network'))).toBe(false)
    expect(isLedgerRefusalAsItCame(null)).toBe(false)
  })
})

describe('wholeLedgerRefusalSentence (V0598)', () => {
  it('says the sentence for a refusal passed on whole, the only case where "Nothing was moved" is known', () => {
    expect(wholeLedgerRefusalSentence(err(503, { detail: DETAIL }))).toBe(LEDGER_SENTENCE)
    expect(wholeLedgerRefusalSentence(err(503, { detail: 'x', code: 'ledger_unavailable' }))).toBe(LEDGER_SENTENCE)
  })
  it('leaves a refusal inside a route\'s own words to those words (a leg may have moved before it)', () => {
    expect(wholeLedgerRefusalSentence(err(409, { detail: `FX route core swap failed: 2pc leg 503: ${DETAIL} (uncompensated)` }))).toBeNull()
    expect(wholeLedgerRefusalSentence(err(502, { detail: `order deposit failed: exchange mover 503: ${DETAIL}` }))).toBeNull()
    expect(wholeLedgerRefusalSentence(err(503, { detail: 'Service temporarily unavailable' }))).toBeNull()
    expect(wholeLedgerRefusalSentence(null)).toBeNull()
  })
})
