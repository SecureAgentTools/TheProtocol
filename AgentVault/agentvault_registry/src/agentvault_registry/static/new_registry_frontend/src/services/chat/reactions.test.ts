import { describe, it, expect } from 'vitest'
import { REACTION_WORDS, applyReactionEvent, cleanReactions, nextAction } from './reactions'

/** V0662 (OurChat lane): reactions, the console's rules. BASE (d44776a2c): the module does not exist. */

describe('the words', () => {
  it('are the registry\'s closed list, plain words and no emoji', () => {
    expect([...REACTION_WORDS]).toEqual(['ack', 'agree', 'thanks', 'done', 'question', 'look'])
    expect(REACTION_WORDS.every((w) => /^[a-z]+$/.test(w))).toBe(true)
  })
})

describe('reading what the registry sent', () => {
  it('keeps the known words in the registry\'s order and drops the rest', () => {
    const got = cleanReactions([{ key: 'thanks', count: 2, mine: false }, { key: 'bogus', count: 4 }, { key: 'ack', count: 1, mine: true },
      { key: 'done', count: 0 }, null, 'x'])
    expect(got).toEqual([{ key: 'ack', count: 1, mine: true }, { key: 'thanks', count: 2, mine: false }])
  })
  it('takes anything but a list as none', () => {
    expect(cleanReactions(undefined)).toEqual([])
    expect(cleanReactions({ a: 1 })).toEqual([])
  })
})

describe('what pressing a word does', () => {
  const chips = [{ key: 'ack', count: 2, mine: true }, { key: 'look', count: 1, mine: false }]
  it('takes your own off and puts another on', () => {
    expect(nextAction(chips, 'ack')).toBe('remove')
    expect(nextAction(chips, 'look')).toBe('add')
    expect(nextAction(chips, 'done')).toBe('add')
    expect(nextAction(undefined, 'ack')).toBe('add')
  })
})

describe('folding the socket\'s counts into the thread', () => {
  const held = () => [{ id: 'a', reactions: [{ key: 'ack', count: 1, mine: true }, { key: 'look', count: 1, mine: false }] }, { id: 'b' }]

  it('my own new word is mine, the others\' marks stay', () => {
    const r = applyReactionEvent(held(), { id: 'a', word: 'done', reactions: [{ key: 'ack', count: 1 }, { key: 'done', count: 1 }, { key: 'look', count: 1 }] }, true)
    expect(r.changed).toBe(true)
    expect(r.messages[0].reactions).toEqual([{ key: 'ack', count: 1, mine: true }, { key: 'done', count: 1, mine: true }, { key: 'look', count: 1, mine: false }])
  })
  it('someone else\'s word raises the count and is not mine', () => {
    const r = applyReactionEvent(held(), { id: 'a', word: 'look', reactions: [{ key: 'ack', count: 1 }, { key: 'look', count: 2 }] }, false)
    expect(r.messages[0].reactions).toEqual([{ key: 'ack', count: 1, mine: true }, { key: 'look', count: 2, mine: false }])
  })
  it('my own take-off clears the mark and drops an emptied chip', () => {
    const r = applyReactionEvent(held(), { id: 'a', word: 'ack', reactions: [{ key: 'look', count: 1 }] }, true)
    expect(r.messages[0].reactions).toEqual([{ key: 'look', count: 1, mine: false }])
  })
  it('my take-off from a shared word keeps the chip, no longer mine', () => {
    const have = [{ id: 'a', reactions: [{ key: 'ack', count: 2, mine: true }] }]
    const r = applyReactionEvent(have, { id: 'a', word: 'ack', reactions: [{ key: 'ack', count: 1 }] }, true)
    expect(r.messages[0].reactions).toEqual([{ key: 'ack', count: 1, mine: false }])
  })
  it('a message with no reactions yet takes the first one', () => {
    const r = applyReactionEvent(held(), { id: 'b', word: 'thanks', reactions: [{ key: 'thanks', count: 1 }] }, false)
    expect(r.messages[1].reactions).toEqual([{ key: 'thanks', count: 1, mine: false }])
  })
  it('a repeated event changes nothing, nor does one for a message not held or with no id', () => {
    const once = applyReactionEvent(held(), { id: 'b', word: 'thanks', reactions: [{ key: 'thanks', count: 1 }] }, false).messages
    expect(applyReactionEvent(once, { id: 'b', word: 'thanks', reactions: [{ key: 'thanks', count: 1 }] }, false).changed).toBe(false)
    expect(applyReactionEvent(held(), { id: 'zzz', word: 'ack', reactions: [] }, false).changed).toBe(false)
    expect(applyReactionEvent(held(), { word: 'ack', reactions: [] }, false).changed).toBe(false)
    expect(applyReactionEvent(held(), null, false).changed).toBe(false)
  })
  it('does not mutate what it was given', () => {
    const have = held()
    applyReactionEvent(have, { id: 'a', word: 'ack', reactions: [] }, true)
    expect(have[0].reactions).toHaveLength(2)
  })
})
