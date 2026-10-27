import { describe, it, expect } from 'vitest'
import { stopActingState } from '../stopActing'

describe('stopActingState — the STOP pane\'s claim about the header selection', () => {
  it('says nothing is selected when nothing is (his ORIGINAL report)', () => {
    expect(stopActingState(null, false)).toBe('unselected')
    expect(stopActingState(undefined, false)).toBe('unselected')
    expect(stopActingState('', false)).toBe('unselected')
  })

  // ⚠ A blank-name agent is still not something to name at the reader. `' '` is truthy, so
  // an untrimmed check would print "You are acting as   " — a sentence with a hole in it.
  it('treats a whitespace-only name as no selection', () => {
    expect(stopActingState('   ', false)).toBe('unselected')
    expect(stopActingState('\t', true)).toBe('unselected')
  })

  it('names the agent and says it has no mandate (his SECOND report: SYBIL)', () => {
    expect(stopActingState('SYBIL', false)).toBe('selected-no-mandate')
  })

  it('names the agent and points at its mandate when it has one', () => {
    expect(stopActingState('forge-a-gen-2', true)).toBe('selected-with-mandate')
  })

  // The bug this replaced: `hasMandate` alone decided nothing, because the whole block was
  // gated on the name being present. Selection and mandate-holding are independent.
  it('mandate-holding never implies a selection', () => {
    expect(stopActingState(null, true)).toBe('unselected')
  })
})
