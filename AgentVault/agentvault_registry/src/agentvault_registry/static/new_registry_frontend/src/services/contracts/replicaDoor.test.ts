import { describe, expect, it } from 'vitest'
import { doorFor, nextDeliverable, paidMilestones } from './replicaDoor'

describe('the provider door onto a replica (§TWOAGENT V0437)', () => {
  it('names the paid milestones the home stated, in order, once each', () => {
    expect(paidMilestones([2, 1, 2, '3'])).toEqual([1, 2, 3])
    expect(paidMilestones(null)).toEqual([])
    expect(paidMilestones(undefined)).toEqual([])
    expect(paidMilestones([0, -1, 'x', 1.5])).toEqual([])
  })
  it('delivers the lowest milestone the home has not paid', () => {
    expect(nextDeliverable([])).toBe(1)
    expect(nextDeliverable(null)).toBe(1)
    expect(nextDeliverable([1])).toBe(2)
    expect(nextDeliverable([1, 2])).toBe(3)
    expect(nextDeliverable([2])).toBe(1)
  })
  it('keeps working after the first delivery (in_progress was a dead end)', () => {
    expect(doorFor('in_progress')).toBe('work')
    expect(doorFor('agreed')).toBe('work')
  })
  it('offers accept only on an open offer, and nothing on a closed contract', () => {
    expect(doorFor('offered')).toBe('accept')
    for (const st of ['completed', 'cancelled', 'disputed', 'expired', 'draft', undefined]) expect(doorFor(st)).toBe('none')
  })
  it('control: right after an accept the mirror still says offered, and the work door must show', () => {
    expect(doorFor('offered', true)).toBe('work')
  })
})
