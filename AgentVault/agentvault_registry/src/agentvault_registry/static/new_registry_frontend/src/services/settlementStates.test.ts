/**
 * V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: a cross-registry settlement that was never delivered, that every
 * peer refused, or that an administrator closed says so in plain words, and Close is offered only where the registry
 * takes it: a settlement no peer holds (no defendant registry recorded) that has not moved and is not moving money.
 * The module is imported in each test, so on 4b79322d7 (no module) each fails by itself.
 */
import { describe, expect, it } from 'vitest'

const load = () => import('./settlementStates')
const row = (status: string, held = '', closable?: boolean) =>
  ({ status, defendant_registry_url: held, ...(closable === undefined ? {} : { closable }) })

describe('a settlement says its state in plain words', () => {
  it('names the three end states a person reads', async () => {
    const m = await load()
    expect(m.stateLabel('NOT_DELIVERED')).toBe('Not delivered')
    expect(m.stateLabel('REFUSED')).toBe('Refused by every peer')
    expect(m.stateLabel('CLOSED')).toBe('Closed')
    expect(m.stateNote('NOT_DELIVERED')).toMatch(/no slash request was sent.*Nothing moved/i)
    expect(m.stateNote('REFUSED')).toMatch(/every peer registry refused.*Nothing moved/i)
    expect(m.stateNote('CLOSED')).toMatch(/closed by an administrator/i)
    expect(m.stateNote('SETTLED')).toBe('')
    expect([...m.ENDED_STATES].sort()).toEqual(['CLOSED', 'NOT_DELIVERED', 'REFUSED'])
  })

  it('an unknown status reads as itself', async () => {
    const m = await load()
    expect(m.stateLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })
})

describe('Close is offered only where the registry takes it', () => {
  it('a settlement no peer holds and nothing moved on can be closed', async () => {
    const m = await load()
    for (const st of ['NOT_DELIVERED', 'REFUSED', 'PENDING_SLASH', 'EXPIRED', 'FAILED']) {
      expect(m.canClose(row(st)), st).toBe(true)
    }
  })

  it('a settlement a peer holds, one that moved or is moving money, or one already closed cannot', async () => {
    const m = await load()
    expect(m.canClose(row('PENDING_SLASH', 'https://sandbox-a.theprotocol.cloud:8443'))).toBe(false)
    for (const st of ['SETTLED', 'COMPENSATING', 'SLASHED', 'SLASHING', 'CLOSED']) {
      expect(m.canClose(row(st)), st).toBe(false)
    }
  })

  it("the registry's own answer wins when it sends one", async () => {
    const m = await load()
    expect(m.canClose(row('REFUSED', '', false))).toBe(false)
    expect(m.canClose(row('PENDING_SLASH', 'https://x', true))).toBe(true)
  })

  it("a refusal is shown in the registry's words", async () => {
    const m = await load()
    const e = { message: 'Request failed with status code 409',
      response: { status: 409, data: { detail: 'Settlement 24ca7222 is SETTLED: a settlement that moved money is not closed' } } }
    expect(m.refusalWords(e)).toBe('Settlement 24ca7222 is SETTLED: a settlement that moved money is not closed')
    expect(m.refusalWords({ message: 'Network Error' })).toBe('Network Error')
  })
})
