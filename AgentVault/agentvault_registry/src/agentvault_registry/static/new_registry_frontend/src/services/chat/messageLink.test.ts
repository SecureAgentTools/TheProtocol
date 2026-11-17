import { describe, it, expect } from 'vitest'
import { messageFromQuery, messageLink } from './messageLink'

/** V0662 (OurChat lane): a link to one message. BASE (0f0977fb4): the module does not exist. */

describe('the link', () => {
  const id = '4f545f88-7d97-4531-9901-7e5f3918663d'
  it('is the thread\'s stable address with the message id, on the apex', () => {
    expect(messageLink({ origin: 'https://theprotocol.cloud', pathname: '/', conversationId: 'c-1', messageId: id }))
      .toBe(`https://theprotocol.cloud/#/pocket/ourchat/c-1?m=${id}`)
  })
  it('keeps the registry\'s /ui/ path', () => {
    expect(messageLink({ origin: 'https://eu.theprotocol.cloud', pathname: '/ui/', conversationId: 'c-1', messageId: id }))
      .toBe(`https://eu.theprotocol.cloud/ui/#/pocket/ourchat/c-1?m=${id}`)
  })
  it('adds the slash a path lacks, and a missing path is the root', () => {
    expect(messageLink({ origin: 'https://x.test', pathname: '/ui', conversationId: 'c', messageId: id })).toContain('x.test/ui/#/pocket')
    expect(messageLink({ origin: 'https://x.test', pathname: '', conversationId: 'c', messageId: id })).toContain('x.test/#/pocket')
  })
  it('encodes what is not plain, so an id can never add a second parameter or a path', () => {
    const l = messageLink({ origin: 'https://x.test', pathname: '/', conversationId: 'a/b?c', messageId: 'm&n=1#x' })
    expect(l).toBe('https://x.test/#/pocket/ourchat/a%2Fb%3Fc?m=m%26n%3D1%23x')
  })
})

describe('the message a thread was opened at', () => {
  it('is a plain id', () => {
    expect(messageFromQuery('4f545f88-7d97-4531-9901-7e5f3918663d')).toBe('4f545f88-7d97-4531-9901-7e5f3918663d')
    expect(messageFromQuery(['abcdef12', 'zzzzzzzz'])).toBe('abcdef12')
    expect(messageFromQuery('  abcdef12  ')).toBe('abcdef12')
  })
  it('is none for anything else: markup, quotes, paths, too short or too long, not a string', () => {
    for (const bad of ['<script>', 'a"b"c"d"e"f', '../../x', 'abc', 'x'.repeat(65), '', undefined, null, 7, {}, []]) {
      expect(messageFromQuery(bad), String(bad)).toBeNull()
    }
  })
})
