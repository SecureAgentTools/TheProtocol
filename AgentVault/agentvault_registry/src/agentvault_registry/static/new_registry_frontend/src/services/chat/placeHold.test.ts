import { describe, it, expect } from 'vitest'
import { NO_NEW_BELOW, NEAR_BOTTOM_PX, atBottom, distanceFromBottom, holdDistance, nearBottomOf, noteArrival, placeFor } from './placeHold'

/** V0665 (his report, room seq 4218): a thread holds the reader's place; the pill counts what came in below. */
const box = (scrollHeight: number, scrollTop: number, clientHeight = 500) => ({ scrollHeight, scrollTop, clientHeight })

describe('where the reader is', () => {
  it('is zero at the end and counts the pixels above it', () => {
    expect(distanceFromBottom(box(2000, 1500))).toBe(0)
    expect(distanceFromBottom(box(2000, 1000))).toBe(500)
    expect(distanceFromBottom(box(400, 0))).toBe(0)                 // a short thread: nothing to scroll
  })
  it('is near the bottom within 80 px, not at 80', () => {
    expect(NEAR_BOTTOM_PX).toBe(80)
    expect(nearBottomOf(box(2000, 1421))).toBe(true)                // 79 px up
    expect(nearBottomOf(box(2000, 1420))).toBe(false)               // exactly 80 px up
    expect(nearBottomOf(box(2000, 200))).toBe(false)
  })
  it('counts a thread with no layout yet as at the end (it always did)', () => {
    expect(nearBottomOf(null)).toBe(true)
    expect(nearBottomOf(undefined)).toBe(true)
  })
})

describe('does an arriving message take the reader down?', () => {
  it('someone else\'s does when the reader was near the bottom, and does not when they were reading further up', () => {
    expect(placeFor({ wasNearBottom: true, mine: false })).toBe('scroll')
    expect(placeFor({ wasNearBottom: false, mine: false })).toBe('hold')
  })
  it('the reader\'s own message always does', () => {
    expect(placeFor({ wasNearBottom: false, mine: true })).toBe('scroll')
    expect(placeFor({ wasNearBottom: true, mine: true })).toBe('scroll')
  })
})

describe('the count of what came in below', () => {
  it('counts only messages that arrived while the reader was away from the bottom, and remembers the first', () => {
    let s = NO_NEW_BELOW
    let r = noteArrival(s, { seq: 11, wasNearBottom: false, mine: false }); s = r.below
    expect(r.place).toBe('hold'); expect(s).toEqual({ count: 1, firstSeq: 11 })
    r = noteArrival(s, { seq: 12, wasNearBottom: false, mine: false }); s = r.below
    r = noteArrival(s, { seq: 13, wasNearBottom: false, mine: false }); s = r.below
    expect(s).toEqual({ count: 3, firstSeq: 11 })
  })
  it('counts nothing for a message that takes the reader down, and clears what was counted (they are at the end now)', () => {
    const held = { count: 2, firstSeq: 11 }
    const own = noteArrival(held, { seq: 14, wasNearBottom: false, mine: true })
    expect(own.place).toBe('scroll'); expect(own.below).toEqual(NO_NEW_BELOW)
    const near = noteArrival(held, { seq: 14, wasNearBottom: true, mine: false })
    expect(near.place).toBe('scroll'); expect(near.below).toEqual(NO_NEW_BELOW)
  })
  it('keeps the lowest seq as the first even when messages are handed over out of order', () => {
    let s = noteArrival(NO_NEW_BELOW, { seq: 22, wasNearBottom: false, mine: false }).below
    s = noteArrival(s, { seq: 21, wasNearBottom: false, mine: false }).below
    expect(s).toEqual({ count: 2, firstSeq: 21 })
  })
  it('clears when the reader reaches the end by hand, and not before', () => {
    const held = { count: 3, firstSeq: 11 }
    expect(atBottom(held, false)).toBe(held)
    expect(atBottom(held, true)).toEqual(NO_NEW_BELOW)
    expect(atBottom(NO_NEW_BELOW, true)).toBe(NO_NEW_BELOW)         // nothing held: the same value, no new object
  })
})

describe('a picture above the view loads and the thread grows', () => {
  it('puts the reader back at the same distance from the bottom when the browser jumped', () => {
    // read 600 px up; a picture above grows the thread by 300 px and the scroll position stayed (so the text slid down)
    expect(holdDistance({ before: 600, box: box(2300, 900), nearBottom: false, aboveView: true })).toBe(1200)   // 2300 - 500 - 600
  })
  it('does nothing when the browser already held the place (the distance is the same)', () => {
    expect(holdDistance({ before: 600, box: box(2300, 1200), nearBottom: false, aboveView: true })).toBeNull()
  })
  it('does nothing for a reader at the end (they follow the end) and for a picture in or below the view', () => {
    expect(holdDistance({ before: 10, box: box(2300, 1700), nearBottom: true, aboveView: true })).toBeNull()
    expect(holdDistance({ before: 600, box: box(2300, 900), nearBottom: false, aboveView: false })).toBeNull()
  })
  it('leaves growth the picture cannot account for alone (a card opened, a message came in below)', () => {
    // the thread grew by 300 px but the picture is 120 px tall: only part of it can be the picture's
    expect(holdDistance({ before: 600, box: box(2300, 900), nearBottom: false, aboveView: true, maxGrowth: 120 })).toBeNull()
    expect(holdDistance({ before: 600, box: box(2100, 900), nearBottom: false, aboveView: true, maxGrowth: 120 })).toBe(1000)   // 100 px of growth: the picture's
  })
  it('never asks for a negative position', () => {
    expect(holdDistance({ before: 5000, box: box(1000, 100), nearBottom: false, aboveView: true })).toBe(0)
  })
})
