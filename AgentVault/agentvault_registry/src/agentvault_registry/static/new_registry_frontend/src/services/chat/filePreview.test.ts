/**
 * V0652 (ae) (order gwo_5b9de9adb052d681ca95853d): a text file read in the thread. The kind follows the registry's
 * rule (services/chat_media.preview_kind); "Open" shows the whole file: markdown rendered and sanitized, JSON
 * pretty-printed, the rest as text; a binary shows nothing. BASE (V0651): no module; a file was a download only.
 */
import { describe, expect, it } from 'vitest'
import { cleanText, fileKind, openedFile, prettyJson, previewHtml } from './filePreview'

const bytes = (s: string) => new TextEncoder().encode(s)

describe('the kind says how to show it (the registry\'s rule)', () => {
  it.each([
    ['text/markdown', 'report.md', 'markdown'],
    ['application/json', 'state.json', 'json'],
    ['text/csv', 'fills.csv', 'csv'],
    ['text/plain', 'server.log', 'log'],
    ['text/plain', 'notes.txt', 'text'],
    ['text/plain', 'report.md.txt', 'markdown'],
    ['text/plain', 'state.json.txt', 'json'],
    ['text/plain', 'README', 'text'],
  ])('%s %s is %s', (mime, name, kind) => {
    expect(fileKind(mime, name)).toBe(kind)
  })
})

describe('the whole file, opened', () => {
  it('markdown is rendered, and its HTML is text, never markup', () => {
    const o = openedFile(bytes('# Plan\n\n**ship** it\n\n<script>alert(1)</script><img src=x onerror=alert(1)>'), 'text/markdown', 'plan.md')
    expect(o.kind).toBe('markdown')
    const doc = new DOMParser().parseFromString(`<div>${o.html}</div>`, 'text/html')
    expect(doc.querySelector('h1')?.textContent).toBe('Plan')
    expect(doc.querySelector('strong')?.textContent).toBe('ship')
    expect(doc.querySelector('script, img, iframe, style')).toBe(null)
    expect(doc.body.textContent).toContain('<script>alert(1)</script>')
  })

  it('JSON is pretty-printed; JSON that does not parse is shown as it is', () => {
    expect(openedFile(bytes('{"a":1,"b":[true,null]}'), 'application/json', 'x.json').text)
      .toBe('{\n  "a": 1,\n  "b": [\n    true,\n    null\n  ]\n}')
    expect(openedFile(bytes('{"a":'), 'application/json', 'x.json').text).toBe('{"a":')
    expect(prettyJson('not json')).toBe('not json')
  })

  it('logs and text are text: one line end, no colour codes, no stray control characters, no BOM', () => {
    const o = openedFile(bytes('﻿\x1b[32mINFO\x1b[0m up\r\nnext\rlast\x07'), 'text/plain', 'run.log')
    expect(o.kind).toBe('log')
    expect(o.text).toBe('INFO up\nnext\nlast')
    expect(o.html).toBe('')
    expect(cleanText('a\r\nb')).toBe('a\nb')
  })

  it('a file that is not UTF-8 text shows nothing', () => {
    const o = openedFile(new Uint8Array([0x61, 0xff, 0xfe, 0x62]), 'text/plain', 'x.txt')
    expect(o.binary).toBe(true)
    expect(o.text).toBe('')
    expect(openedFile(bytes('a\u0000b'), 'text/plain', 'x.txt').binary).toBe(true)
  })

  it('a long file is cut at a line end and says so', () => {
    const text = Array.from({ length: 100 }, (_, i) => `line ${i}`).join('\n')
    const o = openedFile(bytes(text), 'text/plain', 'x.txt', 100)
    expect(o.cut).toBe(true)
    expect(o.text.length).toBeLessThanOrEqual(100)
    expect(text.startsWith(o.text + '\n')).toBe(true)
    expect(openedFile(bytes('short'), 'text/plain', 'x.txt', 100).cut).toBe(false)
  })
})

describe('a preview on the card', () => {
  it('markdown is sanitized HTML; the other kinds give none (they are drawn as text)', () => {
    const h = previewHtml('**hi** <b onclick="x()">there</b>', 'markdown')
    expect(h).toContain('<strong>hi</strong>')
    const doc = new DOMParser().parseFromString(`<div>${h}</div>`, 'text/html')
    expect(doc.querySelector('b')).toBe(null)                                    // the raw tag is text, not an element
    expect([...doc.querySelectorAll('*')].flatMap((e) => [...e.attributes].map((a) => a.name)).filter((n) => n.startsWith('on'))).toEqual([])
    expect(doc.body.textContent).toContain('<b onclick="x()">there</b>')
    expect(previewHtml('{"a": 1}', 'json')).toBe('')
    expect(previewHtml(null, 'markdown')).toBe('')
  })
})
