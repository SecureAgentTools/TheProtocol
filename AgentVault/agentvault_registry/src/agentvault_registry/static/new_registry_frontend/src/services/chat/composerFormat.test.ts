import { describe, it, expect } from 'vitest'
import { applyFormat, shortcutFormat } from './composerFormat'
import { renderMarkdown } from './messageText'

/** V0662 (OurChat lane): the composer's formatting. BASE (f569f6a6e): composerFormat.ts does not exist; the composer is a
 *  bare textarea and the markdown is typed by hand. Every kind toggles, and the markers are the ones the thread's own
 *  renderer reads. */

const ed = (text: string, a: number, b: number, kind: Parameters<typeof applyFormat>[3]) => applyFormat(text, a, b, kind)

describe('bold', () => {
  it('wraps the selection and keeps it selected', () => {
    expect(ed('hello world', 6, 11, 'bold')).toEqual({ text: 'hello **world**', selStart: 8, selEnd: 13 })
  })

  it('puts the caret between the markers when nothing is selected', () => {
    expect(ed('hello', 5, 5, 'bold')).toEqual({ text: 'hello****', selStart: 7, selEnd: 7 })
  })

  it('comes off again, whether the markers sit around the selection or inside it', () => {
    expect(ed('**world**', 2, 7, 'bold')).toEqual({ text: 'world', selStart: 0, selEnd: 5 })
    expect(ed('**world**', 0, 9, 'bold')).toEqual({ text: 'world', selStart: 0, selEnd: 5 })
  })

  it('goes round italic text without undoing it', () => {
    expect(ed('*world*', 1, 6, 'bold')).toEqual({ text: '***world***', selStart: 3, selEnd: 8 })
  })
})

describe('italic', () => {
  it('wraps with one asterisk and comes off again', () => {
    expect(ed('hello world', 6, 11, 'italic')).toEqual({ text: 'hello *world*', selStart: 7, selEnd: 12 })
    expect(ed('*world*', 1, 6, 'italic')).toEqual({ text: 'world', selStart: 0, selEnd: 5 })
  })

  it('does not take the two asterisks of bold for its own', () => {
    expect(ed('**world**', 2, 7, 'italic')).toEqual({ text: '***world***', selStart: 3, selEnd: 8 })
  })

  it('takes one asterisk off bold-italic, and bold takes two', () => {
    expect(ed('***world***', 3, 8, 'italic')).toEqual({ text: '**world**', selStart: 2, selEnd: 7 })
    expect(ed('***world***', 3, 8, 'bold')).toEqual({ text: '*world*', selStart: 1, selEnd: 6 })
  })
})

describe('code', () => {
  it('wraps a line of text in backticks and unwraps it', () => {
    expect(ed('run ls now', 4, 6, 'code')).toEqual({ text: 'run `ls` now', selStart: 5, selEnd: 7 })
    expect(ed('run `ls` now', 5, 7, 'code')).toEqual({ text: 'run ls now', selStart: 4, selEnd: 6 })
    expect(ed('`ls`', 0, 4, 'code')).toEqual({ text: 'ls', selStart: 0, selEnd: 2 })
  })

  it('makes a fenced block of a selection over several lines, and takes the fence off', () => {
    expect(ed('a\nb', 0, 3, 'code')).toEqual({ text: '```\na\nb\n```', selStart: 4, selEnd: 7 })
    expect(ed('```\na\nb\n```', 0, 11, 'code')).toEqual({ text: 'a\nb', selStart: 0, selEnd: 3 })
  })

  it('puts the caret between two backticks for an empty selection', () => {
    expect(ed('x', 1, 1, 'code')).toEqual({ text: 'x``', selStart: 2, selEnd: 2 })
  })
})

describe('quote and list', () => {
  it('prefix the line the caret is on and leave the caret at its end', () => {
    expect(ed('one', 1, 1, 'quote')).toEqual({ text: '> one', selStart: 5, selEnd: 5 })
    expect(ed('a\nb\nc', 3, 3, 'list')).toEqual({ text: 'a\n- b\nc', selStart: 5, selEnd: 5 })
  })

  it('prefix every line a selection touches, and the block stays selected', () => {
    expect(ed('one\ntwo', 0, 7, 'quote')).toEqual({ text: '> one\n> two', selStart: 0, selEnd: 11 })
    expect(ed('one\ntwo', 0, 7, 'list')).toEqual({ text: '- one\n- two', selStart: 0, selEnd: 11 })
  })

  it('take the prefix off lines that all carry it', () => {
    expect(ed('> one\n> two', 0, 11, 'quote')).toEqual({ text: 'one\ntwo', selStart: 0, selEnd: 7 })
    expect(ed('- one\n- two', 0, 11, 'list')).toEqual({ text: 'one\ntwo', selStart: 0, selEnd: 7 })
  })

  it('give a mix the prefix only where it is missing, never a quote inside a quote', () => {
    expect(ed('> one\ntwo', 0, 9, 'quote')).toEqual({ text: '> one\n> two', selStart: 0, selEnd: 11 })
  })

  it('do not take the next line when the selection ends just after a line break', () => {
    expect(ed('a\nb', 0, 2, 'quote')).toEqual({ text: '> a\nb', selStart: 0, selEnd: 3 })
  })

  it('keep a blank line between two lines blank', () => {
    expect(ed('a\n\nb', 0, 4, 'list')).toEqual({ text: '- a\n\n- b', selStart: 0, selEnd: 8 })
  })

  it('let a caret on an empty composer start a list', () => {
    expect(ed('', 0, 0, 'list')).toEqual({ text: '- ', selStart: 2, selEnd: 2 })
  })
})

describe('link', () => {
  it('makes [text](https://) of the selection and selects the address to type over', () => {
    const r = ed('see docs', 4, 8, 'link')
    expect(r.text).toBe('see [docs](https://)')
    expect(r.text.slice(r.selStart, r.selEnd)).toBe('https://')
  })

  it('turns a selected address into the target of an empty label and puts the caret in the label', () => {
    expect(ed('go https://x.io now', 3, 15, 'link')).toEqual({ text: 'go [](https://x.io) now', selStart: 4, selEnd: 4 })
  })

  it('starts an empty link with the caret in its label', () => {
    expect(ed('', 0, 0, 'link')).toEqual({ text: '[](https://)', selStart: 1, selEnd: 1 })
  })
})

describe('whatever the selection is', () => {
  it('takes a reversed selection as the same one', () => {
    expect(ed('hello world', 11, 6, 'bold')).toEqual(ed('hello world', 6, 11, 'bold'))
  })

  it('holds an out-of-range or missing selection to the text', () => {
    expect(ed('hi', 99, 99, 'bold')).toEqual({ text: 'hi****', selStart: 4, selEnd: 4 })
    expect(ed('hi', NaN, NaN, 'bold').text).toBe('****hi')
    expect(ed(undefined as unknown as string, 0, 0, 'bold').text).toBe('****')
  })
})

describe('what it writes is what the thread renders', () => {
  it('bold, italic, code, quote, list and link all come out as their elements', () => {
    const html = (t: string) => renderMarkdown(t)
    expect(html(ed('x', 0, 1, 'bold').text)).toContain('<strong>x</strong>')
    expect(html(ed('x', 0, 1, 'italic').text)).toContain('<em>x</em>')
    expect(html(ed('x', 0, 1, 'code').text)).toContain('<code>x</code>')
    expect(html(ed('x', 0, 1, 'quote').text)).toContain('<blockquote>')
    expect(html(ed('x', 0, 1, 'list').text)).toContain('<li>x</li>')
    expect(html('[docs](https://example.org)')).toContain('href="https://example.org"')
  })
})

describe('the shortcuts', () => {
  it('ask for bold, italic and a link with Ctrl or Cmd', () => {
    expect(shortcutFormat({ key: 'b', ctrlKey: true })).toBe('bold')
    expect(shortcutFormat({ key: 'I', metaKey: true })).toBe('italic')
    expect(shortcutFormat({ key: 'k', ctrlKey: true })).toBe('link')
  })

  it('ask for nothing without Ctrl or Cmd, with Shift or Alt, or for another key', () => {
    expect(shortcutFormat({ key: 'b' })).toBeNull()
    expect(shortcutFormat({ key: 'b', ctrlKey: true, shiftKey: true })).toBeNull()
    expect(shortcutFormat({ key: 'b', ctrlKey: true, altKey: true })).toBeNull()
    expect(shortcutFormat({ key: 'x', ctrlKey: true })).toBeNull()
  })
})
