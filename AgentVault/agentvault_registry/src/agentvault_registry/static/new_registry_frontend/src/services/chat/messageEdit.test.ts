import { describe, it, expect } from 'vitest'
import { EDIT_WINDOW_MS, applyMessageChange, canChange, windowLeftMs } from './messageEdit'

/** V0662 (OurChat lane): edit / take back, the console's half. BASE (1412e2858): the module does not exist. */

const T0 = Date.parse('2026-11-13T12:00:00Z')
const line = (over: Record<string, any> = {}): Record<string, any> => ({ id: 'm1', seq: 1, kind: 'text', body: 'hello', created_at: '2026-11-13T12:00:00Z', ...over })

describe('whether to offer Edit and Delete', () => {
  it('offers them on your own fresh text message', () => {
    expect(canChange(line(), true, T0 + 1000)).toBe(true)
  })
  it('not on someone else\'s line (control)', () => {
    expect(canChange(line(), false, T0 + 1000)).toBe(false)
  })
  it('not past the window, but up to and including its end', () => {
    expect(canChange(line(), true, T0 + EDIT_WINDOW_MS)).toBe(true)
    expect(canChange(line(), true, T0 + EDIT_WINDOW_MS + 1)).toBe(false)
  })
  it('not on a card, a system line or a line already taken back', () => {
    expect(canChange(line({ kind: 'card' }), true, T0)).toBe(false)
    expect(canChange(line({ kind: 'system' }), true, T0)).toBe(false)
    expect(canChange(line({ deleted: true }), true, T0)).toBe(false)
  })
  it('not on a line with no time or no id, nor on nothing', () => {
    expect(canChange(line({ created_at: null }), true, T0)).toBe(false)
    expect(canChange(line({ created_at: 'garbage' }), true, T0)).toBe(false)
    expect(canChange(line({ id: '' }), true, T0)).toBe(false)
    expect(canChange(null, true, T0)).toBe(false)
  })
  it('says how long is left, never below zero', () => {
    expect(windowLeftMs(line(), T0 + 60_000)).toBe(EDIT_WINDOW_MS - 60_000)
    expect(windowLeftMs(line(), T0 + EDIT_WINDOW_MS * 2)).toBe(0)
    expect(windowLeftMs(line({ created_at: null }), T0)).toBe(0)
  })
})

describe('folding a change into the thread', () => {
  const held = () => [line({ id: 'a', seq: 1 }), line({ id: 'b', seq: 2, body: 'second' })]

  it('an edit replaces the body and marks the line edited, in place', () => {
    const r = applyMessageChange(held(), { id: 'b', body: 'second, corrected', edited_at: '2026-11-13T12:01:00Z' })
    expect(r.changed).toBe(true)
    expect(r.messages.map((m) => m.id)).toEqual(['a', 'b'])
    expect(r.messages[1].body).toBe('second, corrected')
    expect(r.messages[1].edited_at).toBe('2026-11-13T12:01:00Z')
    expect(r.messages[0].body).toBe('hello')                              // the other line untouched
  })
  it('does not mutate what it was given', () => {
    const have = held()
    applyMessageChange(have, { id: 'b', body: 'x', edited_at: '2026-11-13T12:01:00Z' })
    expect(have[1].body).toBe('second')
  })
  it('an older or equal edit changes nothing (a late or repeated event)', () => {
    const once = applyMessageChange(held(), { id: 'b', body: 'v2', edited_at: '2026-11-13T12:02:00Z' }).messages
    expect(applyMessageChange(once, { id: 'b', body: 'v1', edited_at: '2026-11-13T12:01:00Z' }).changed).toBe(false)
    expect(applyMessageChange(once, { id: 'b', body: 'v2', edited_at: '2026-11-13T12:02:00Z' }).changed).toBe(false)
  })
  it('an edit with no time or no text changes nothing', () => {
    expect(applyMessageChange(held(), { id: 'b', body: 'x' }).changed).toBe(false)
    expect(applyMessageChange(held(), { id: 'b', edited_at: '2026-11-13T12:01:00Z' }).changed).toBe(false)
  })
  it('a take-back leaves the tombstone the registry serves', () => {
    const r = applyMessageChange(held(), { id: 'a', deleted: true })
    expect(r.changed).toBe(true)
    expect(r.messages[0]).toMatchObject({ id: 'a', seq: 1, kind: 'system', body: null, card: null, deleted: true })
  })
  it('a line taken back takes no more changes, an edit included', () => {
    const gone = applyMessageChange(held(), { id: 'a', deleted: true }).messages
    expect(applyMessageChange(gone, { id: 'a', body: 'back', edited_at: '2026-11-13T12:05:00Z' }).changed).toBe(false)
    expect(applyMessageChange(gone, { id: 'a', deleted: true }).changed).toBe(false)
  })
  it('a line the thread does not hold, and a change with no id, are none of its business', () => {
    expect(applyMessageChange(held(), { id: 'zzz', deleted: true }).changed).toBe(false)
    expect(applyMessageChange(held(), { body: 'x', edited_at: '2026-11-13T12:01:00Z' }).changed).toBe(false)
    expect(applyMessageChange(held(), null).changed).toBe(false)
  })
})

import { changesFromUpdates } from './messageEdit'
import { mergeBySeq } from './catchUp'

describe('the long-poll\'s updates lane', () => {
  const ups = [
    { id: 'a', conversation_id: 'c1', change: 'edit', body: 'new', edited_at: '2026-11-13T12:05:00Z', deleted_at: null },
    { id: 'b', conversation_id: 'c1', change: 'delete', body: null, deleted_at: '2026-11-13T12:06:00Z' },
    { id: 'c', conversation_id: 'c2', change: 'edit', body: 'elsewhere', edited_at: '2026-11-13T12:07:00Z' },
    { id: 'd', conversation_id: 'c1', card: { type: 'progress' }, card_rev: 2 },                  // a card update: not a change
    { conversation_id: 'c1', change: 'edit', body: 'no id', edited_at: '2026-11-13T12:08:00Z' },
  ]
  it('maps this thread\'s edits and take-backs, in order, and nothing else', () => {
    expect(changesFromUpdates(ups, 'c1')).toEqual([
      { id: 'a', body: 'new', edited_at: '2026-11-13T12:05:00Z' }, { id: 'b', deleted: true }])
  })
  it('takes anything that is not a list as none', () => {
    expect(changesFromUpdates(undefined, 'c1')).toEqual([])
    expect(changesFromUpdates({ x: 1 }, 'c1')).toEqual([])
    expect(changesFromUpdates([null, 7], 'c1')).toEqual([])
  })
})

describe('a catch-up read that shows a line changed since the thread held it', () => {
  const held = [{ id: 'a', seq: 1, kind: 'text', body: 'old', created_at: '2026-11-13T12:00:00Z' }, { id: 'b', seq: 2, kind: 'text', body: 'keep' }]
  it('takes the newer text of an edited line and counts it', () => {
    const r = mergeBySeq(held as any, [{ id: 'a', seq: 1, kind: 'text', body: 'fixed', edited_at: '2026-11-13T12:03:00Z' }] as any)
    expect(r.messages[0]).toMatchObject({ id: 'a', body: 'fixed', edited_at: '2026-11-13T12:03:00Z' })
    expect(r.messages[1].body).toBe('keep')
    expect(r.updated).toBe(1)
  })
  it('turns a line the answer shows taken back into the tombstone', () => {
    const r = mergeBySeq(held as any, [{ id: 'b', seq: 2, kind: 'system', body: null, deleted: true }] as any)
    expect(r.messages[1]).toMatchObject({ id: 'b', deleted: true, body: null })
    expect(r.updated).toBe(1)
  })
  it('an answer no newer than what is held changes nothing (control)', () => {
    const edited = [{ ...held[0], body: 'fixed', edited_at: '2026-11-13T12:03:00Z' }, held[1]]
    const r = mergeBySeq(edited as any, [{ id: 'a', seq: 1, kind: 'text', body: 'fixed', edited_at: '2026-11-13T12:03:00Z' },
      { id: 'b', seq: 2, kind: 'text', body: 'keep' }] as any)
    expect(r.updated).toBe(0)
    expect(r.messages).toEqual(edited)
  })
})
