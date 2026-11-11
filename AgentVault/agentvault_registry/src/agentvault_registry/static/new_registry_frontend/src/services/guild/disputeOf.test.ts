// V0658 (d), polish 16: Pocket's "View the dispute record" opens that order's dispute, not the dispute list.
import { describe, expect, it } from 'vitest'
import { disputeIdOf, disputeDoorQuery } from './disputeOf'
import earn from '../../views/pocket/PocketEarn.vue?raw'

describe('disputeIdOf', () => {
  it("reads the dispute the order's own 'disputed' event filed", () => {
    expect(disputeIdOf([
      { seq: 1, event_type: 'posted', payload: {} },
      { seq: 5, event_type: 'disputed', payload: { reason: 'empty', ddr_dispute: 41 } },
    ])).toBe('41')
  })

  it('takes the latest when an order was disputed twice, and reads a JSON-text payload too', () => {
    expect(disputeIdOf([
      { seq: 5, event_type: 'disputed', payload: '{"ddr_dispute": 41}' },
      { seq: 9, event_type: 'disputed', payload: { ddr_dispute: 57 } },
    ])).toBe('57')
  })

  it('no dispute id: null (an older order, or a dispute the reaper opened without one)', () => {
    expect(disputeIdOf([{ seq: 5, event_type: 'disputed', payload: { reason: 'deadline' } }])).toBeNull()
    expect(disputeIdOf([])).toBeNull()
    expect(disputeIdOf(undefined)).toBeNull()
  })
})

describe('the order names its dispute', () => {
  it("prefers the order's own dispute_id: the deadline sweep sets it and writes no ddr_dispute in its event", () => {
    expect(disputeIdOf([{ seq: 5, event_type: 'disputed', payload: { reason: 'deadline_missed' } }], { dispute_id: '63' }))
      .toBe('63')
    expect(disputeDoorQuery({}, [], { dispute_id: 63 })).toEqual({ dispute: '63' })
  })
  it('an order without one falls back to its events', () => {
    expect(disputeIdOf([{ seq: 2, event_type: 'disputed', payload: { ddr_dispute: 7 } }], { dispute_id: null })).toBe('7')
  })
})

describe('disputeDoorQuery', () => {
  it('opens the dispute itself when its id is known, else the dispute list as before', () => {
    expect(disputeDoorQuery({ tab: 'earn' }, [{ seq: 2, event_type: 'disputed', payload: { ddr_dispute: 7 } }]))
      .toEqual({ tab: 'earn', dispute: '7' })
    expect(disputeDoorQuery({ tab: 'earn' }, [])).toEqual({ tab: 'earn', work: 'disputes' })
  })
})

describe('PocketEarn', () => {
  it("the door reads the order's events", () => {
    expect(earn).toMatch(/function goDisputeRecord\(\)[^\n]*disputeDoorQuery\(route\.query, det\.value\?\.events, det\.value\?\.order\)/)
  })
})
