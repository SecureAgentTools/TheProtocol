import { describe, it, expect } from 'vitest'
import {
  BODY_MAX_BYTES, COUNTER_FROM_BYTES, SUMMARY_LIMIT,
  documentFor, documentName, lengthState, postedLine, summaryLine, utf8Bytes,
} from './longMessage'

/** V0662 (OurChat lane): a message past the cap goes as a document. BASE (f569f6a6e): longMessage.ts does not exist; the
 *  composer has no counter and no attachment path, so a person past the cap meets the registry's refusal after pressing
 *  Send. The cap is chat_service.BODY_MAX_BYTES = 4096, in UTF-8 BYTES. */

describe('the byte count', () => {
  it('counts the UTF-8 encoding, the way the registry does', () => {
    expect(utf8Bytes('')).toBe(0)
    expect(utf8Bytes('abc')).toBe(3)
    expect(utf8Bytes('ä')).toBe(2)
    expect(utf8Bytes('€')).toBe(3)
    expect(utf8Bytes('😀')).toBe(4)
    // G 1, r 1, ü 2, ß 2, e 1, space 1, 😀 4
    expect(utf8Bytes('Grüße 😀')).toBe(12)
  })
})

describe('where the composer stands against the cap', () => {
  it('passes exactly the cap and refuses one byte more', () => {
    const at = lengthState('a'.repeat(BODY_MAX_BYTES))
    expect(at.bytes).toBe(4096)
    expect(at.remaining).toBe(0)
    expect(at.over).toBe(false)
    const past = lengthState('a'.repeat(BODY_MAX_BYTES + 1))
    expect(past.remaining).toBe(-1)
    expect(past.over).toBe(true)
  })

  it('trips on BYTES: 2,100 letters "ä" are fewer characters than the cap and more bytes', () => {
    const s = lengthState('ä'.repeat(2100))
    expect(s.bytes).toBe(4200)
    expect(s.over).toBe(true)
    expect('ä'.repeat(2100).length).toBeLessThan(BODY_MAX_BYTES)
  })

  it('shows the counter from 3,500 bytes and not before', () => {
    expect(lengthState('a'.repeat(COUNTER_FROM_BYTES - 1)).showCounter).toBe(false)
    expect(lengthState('a'.repeat(COUNTER_FROM_BYTES)).showCounter).toBe(true)
    expect(lengthState('').showCounter).toBe(false)
  })

  it('measures what send() posts: the trimmed text', () => {
    const s = lengthState('   ' + 'a'.repeat(BODY_MAX_BYTES) + '\n\n  ')
    expect(s.bytes).toBe(4096)
    expect(s.over).toBe(false)
  })

  it('takes an empty or missing value as nothing', () => {
    expect(lengthState('').bytes).toBe(0)
    expect(lengthState(undefined as unknown as string).bytes).toBe(0)
  })
})

describe('the one line the room keeps', () => {
  it('is the first non-empty line, trimmed', () => {
    expect(summaryLine('\n\n   The plan  \nsecond line')).toBe('The plan')
    expect(summaryLine('one\r\ntwo')).toBe('one')
  })

  it('leaves a short line alone and cuts a long one at the limit with an ellipsis', () => {
    expect(summaryLine('x'.repeat(SUMMARY_LIMIT))).toBe('x'.repeat(SUMMARY_LIMIT))
    const cut = summaryLine('x'.repeat(SUMMARY_LIMIT + 50))
    expect(cut).toBe('x'.repeat(SUMMARY_LIMIT - 1) + '…')
    expect(Array.from(cut)).toHaveLength(SUMMARY_LIMIT)
  })

  it('never splits an emoji when it cuts', () => {
    const cut = summaryLine('😀'.repeat(400))
    expect(Array.from(cut)).toHaveLength(SUMMARY_LIMIT)
    expect(cut.endsWith('…')).toBe(true)
    // a lone surrogate would show here: every code point must be a whole one
    expect(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/.test(cut)).toBe(false)
  })

  it('is empty for text with no words', () => {
    expect(summaryLine('')).toBe('')
    expect(summaryLine('  \n \n')).toBe('')
  })
})

describe('the document', () => {
  it('is named by the UTC instant, the same on every machine', () => {
    expect(documentName(new Date(Date.UTC(2026, 10, 13, 14, 30, 55)))).toBe('message-20261113-143055.md')
    expect(documentName(new Date(Date.UTC(2026, 0, 2, 3, 4, 5)))).toBe('message-20260102-030405.md')
  })

  it('is a markdown file holding the trimmed text, sized in bytes', async () => {
    const d = documentFor('\n  # Plan\n\nÄrger mit 😀\n  ', new Date(Date.UTC(2026, 10, 13, 14, 30, 55)))
    expect(d.name).toBe('message-20261113-143055.md')
    expect(d.file.name).toBe(d.name)
    expect(d.file.type).toBe('text/markdown')
    expect(await d.file.text()).toBe('# Plan\n\nÄrger mit 😀')
    expect(d.bytes).toBe(utf8Bytes('# Plan\n\nÄrger mit 😀'))
    expect(d.summary).toBe('# Plan')
  })
})

describe('the line posted after the file', () => {
  it('names the file and its size, and not the attachment id the card already carries', () => {
    const line = postedLine('# Plan', 'message-20261113-143055.md', 5321)
    expect(line).toBe('# Plan (the whole message: message-20261113-143055.md, 5321 bytes)')
    expect(line).not.toContain('attachment')
  })

  it('always fits the cap itself, even for the widest possible summary', () => {
    const widest = summaryLine('😀'.repeat(2000))
    const line = postedLine(widest, 'message-20261113-143055.md', 999999)
    expect(utf8Bytes(line)).toBeLessThan(BODY_MAX_BYTES)
  })
})
