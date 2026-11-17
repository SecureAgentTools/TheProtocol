import { describe, it, expect } from 'vitest'
import { QUOTE_MAX_CHARS, QUOTE_MAX_LINES, quoteBlock, withQuote } from './quote'

/** V0662 (OurChat lane): Quote copies a few lines into the composer as a markdown quote. BASE (f52a8b256): no module. */

describe('the quote block', () => {
  it('is the sender and the line as a markdown quote, then a blank line', () => {
    expect(quoteBlock('Mira', 'we ship on Friday')).toBe('> Mira: we ship on Friday\n\n')
  })
  it('puts the name on the first line only and quotes every line', () => {
    expect(quoteBlock('Mira', 'one\ntwo\nthree')).toBe('> Mira: one\n> two\n> three\n\n')
  })
  it('without a name is just the quote', () => {
    expect(quoteBlock(null, 'hello')).toBe('> hello\n\n')
    expect(quoteBlock('   ', 'hello')).toBe('> hello\n\n')
  })
  it('keeps a line that is already a quote quoted (a quote of a quote)', () => {
    expect(quoteBlock('Lead', '> Mira: x\nreply')).toBe('> Lead: > Mira: x\n> reply\n\n')
  })
  it('cuts to six lines and says so', () => {
    const body = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`).join('\n')
    const out = quoteBlock('A', body)
    expect(out.trim().split('\n')).toHaveLength(QUOTE_MAX_LINES)
    expect(out).toContain('> line 6 …')
    expect(out).not.toContain('line 7')
  })
  it('cuts a long text at a word and says so', () => {
    const out = quoteBlock('A', `${'word '.repeat(200)}`)
    expect(out.length).toBeLessThanOrEqual(QUOTE_MAX_CHARS + 30)
    expect(out.trim().endsWith('…')).toBe(true)
  })
  it('is empty for no words', () => {
    expect(quoteBlock('A', '')).toBe('')
    expect(quoteBlock('A', '   \n ')).toBe('')
    expect(quoteBlock('A', null)).toBe('')
  })
  it('does not let a name break the quote: its line breaks become spaces', () => {
    expect(quoteBlock('Mi\nra', 'x')).toBe('> Mi ra: x\n\n')
  })
})

describe('what the composer holds after Quote', () => {
  it('is the block alone when the composer is empty', () => {
    expect(withQuote('', '> A: x\n\n')).toBe('> A: x\n\n')
  })
  it('puts the block after what is already written, a blank line between', () => {
    expect(withQuote('I think', '> A: x\n\n')).toBe('I think\n\n> A: x\n\n')
    expect(withQuote('I think\n\n', '> A: x\n\n')).toBe('I think\n\n> A: x\n\n')
  })
  it('changes nothing for an empty block', () => {
    expect(withQuote('keep me', '')).toBe('keep me')
  })
})
