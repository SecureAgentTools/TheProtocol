import { describe, it, expect } from 'vitest'
import { canOfferPin, pinSummary, pinnedIds } from './pins'

/** V0662 (OurChat lane): pinned messages, the console's rules. BASE (b4591d1af): the module does not exist. */

describe('which lines are pinned', () => {
  it('is the set of the pins\' message ids', () => {
    expect([...pinnedIds([{ message: { id: 'a' } }, { message: { id: 'b' } }])]).toEqual(['a', 'b'])
  })
  it('takes anything else as none', () => {
    expect(pinnedIds(undefined).size).toBe(0)
    expect(pinnedIds([{ message: {} }, null as any, { message: { id: '' } }]).size).toBe(0)
  })
})

describe('what a pin shows', () => {
  it('is the line\'s words with whitespace folded', () => {
    expect(pinSummary({ kind: 'text', body: 'the plan:\n  ship   Friday' })).toBe('the plan: ship Friday')
  })
  it('is cut with an ellipsis past the limit', () => {
    expect(pinSummary({ kind: 'text', body: 'x'.repeat(200) }, 20)).toBe(`${'x'.repeat(19)}…`)
    expect(pinSummary({ kind: 'text', body: 'x'.repeat(20) }, 20)).toBe('x'.repeat(20))
  })
  it('is a card\'s title, else its name, else its type', () => {
    expect(pinSummary({ kind: 'card', card: { type: 'progress', data: { title: 'V0662 proof' } } })).toBe('V0662 proof')
    expect(pinSummary({ kind: 'card', card: { type: 'agent.card', data: { name: 'Mira' } } })).toBe('Mira')
    expect(pinSummary({ kind: 'card', card: { type: 'media' } })).toBe('media')
  })
  it('is empty for nothing', () => {
    expect(pinSummary(null)).toBe('')
    expect(pinSummary({ kind: 'text' })).toBe('')
  })
})

describe('whether Pin is offered on a line', () => {
  it('only where the registry lets this reader pin, and on a real line', () => {
    expect(canOfferPin({ id: 'a', kind: 'text' }, true)).toBe(true)
    expect(canOfferPin({ id: 'a', kind: 'text' }, false)).toBe(false)
    expect(canOfferPin({ id: 'a', kind: 'system' }, true)).toBe(false)
    expect(canOfferPin({ id: 'a', kind: 'text', deleted: true }, true)).toBe(false)
    expect(canOfferPin({ kind: 'text' }, true)).toBe(false)
    expect(canOfferPin(null, true)).toBe(false)
  })
})
