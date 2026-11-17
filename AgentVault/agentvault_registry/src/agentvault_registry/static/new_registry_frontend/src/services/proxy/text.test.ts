// V0664 C3: a recipe's prose carries `inline code` (the README's markdown); the console shows it as code, never as HTML.
import { describe, expect, it } from 'vitest'
import { inline } from './text'

describe('inline code in a recipe sentence', () => {
  it('splits a sentence into text and code parts, in order', () => {
    expect(inline('An agent with the `attestor` role, from `.env`.')).toEqual([
      { code: false, text: 'An agent with the ' }, { code: true, text: 'attestor' }, { code: false, text: ' role, from ' },
      { code: true, text: '.env' }, { code: false, text: '.' },
    ])
  })
  it('keeps an unmatched backtick as text, and markup as text (nothing is rendered as HTML)', () => {
    expect(inline('a ` alone')).toEqual([{ code: false, text: 'a ` alone' }])
    expect(inline('<b>x</b> `<i>`')).toEqual([{ code: false, text: '<b>x</b> ' }, { code: true, text: '<i>' }])
    expect(inline('')).toEqual([])
  })
})
