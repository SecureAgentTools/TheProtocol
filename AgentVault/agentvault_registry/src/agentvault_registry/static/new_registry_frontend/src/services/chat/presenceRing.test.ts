import { describe, it, expect } from 'vitest'
import { liveLine, mentionLabel, ringOf, safeIcon } from './presenceRing'

/**
 * V0655 (ay) (order gwo_57362aa3484807226198b8de): the ring around a member's logo in a room's side panel, which picture
 * it may draw, and how a mention names the member. BASE (V0654): none of it exists (the panel drew a dot).
 */
const NOW = Date.parse('2026-11-03T12:00:00Z')
const line = (expires_at: string, text = 'building (ay)') => ({ status: { text, expires_at } })

describe('the ring\'s four states', () => {
  it('off beats everything: nothing in the room wakes it, whatever its line says', () => {
    expect(ringOf(line('2026-11-03T13:00:00Z'), 'off', NOW)).toBe('off')
    expect(ringOf({ status: null }, 'off', NOW)).toBe('off')
  })
  it('live: a status line that has not lapsed, whether it listens or is on call', () => {
    expect(ringOf(line('2026-11-03T13:00:00Z'), 'listen', NOW)).toBe('live')
    expect(ringOf(line('2026-11-03T13:00:00Z'), 'on-call', NOW)).toBe('live')
    expect(ringOf(line('2026-11-03T13:00:00Z'), '', NOW)).toBe('live')     // an agent of the org outside the room
  })
  it('a line lapses at its expiry, even between two reads of the presence', () => {
    expect(liveLine(line('2026-11-03T11:59:59Z'), NOW)).toBe(false)
    expect(ringOf(line('2026-11-03T11:59:59Z'), 'listen', NOW)).toBe('quiet')
    expect(ringOf(line('2026-11-03T11:59:59Z'), 'on-call', NOW)).toBe('on-call')
  })
  it('on call without a live line; quiet without one otherwise; an empty line is no line', () => {
    expect(ringOf({ status: null }, 'on-call', NOW)).toBe('on-call')
    expect(ringOf({ status: null }, 'listen', NOW)).toBe('quiet')
    expect(ringOf({ status: null }, '', NOW)).toBe('quiet')
    expect(ringOf(line('2026-11-03T13:00:00Z', '  '), 'listen', NOW)).toBe('quiet')
  })
})

describe('the picture the panel may draw', () => {
  it('an https address, a path on this host and an inline image', () => {
    expect(safeIcon(' https://docs.theprotocol.cloud/agents/session-lead/logo.png ')).toBe('https://docs.theprotocol.cloud/agents/session-lead/logo.png')
    expect(safeIcon('/static/agents/a.png')).toBe('/static/agents/a.png')
    expect(safeIcon('data:image/png;base64,iVBORw0KGgo=')).toBe('data:image/png;base64,iVBORw0KGgo=')
    expect(safeIcon('data:image/svg+xml,%3Csvg%3E')).toBe('data:image/svg+xml,%3Csvg%3E')
  })
  it('nothing else: the initial is drawn instead', () => {
    for (const u of ['http://example.org/a.png', '//example.org/a.png', 'javascript:alert(1)', 'data:text/html,<b>x</b>',
      'https://', '', null, undefined, 42, { url: 'https://x.test/a.png' }, `https://x.test/${'a'.repeat(2100)}`]) {
      expect(safeIcon(u)).toBeNull()
    }
  })
})

describe('what a mention writes after "@"', () => {
  const all = [{ did: 'did:x:1', name: 'session-lead' }, { did: 'did:x:2', name: 'Scout' }, { did: 'did:x:3', name: 'scout' },
    { did: 'did:x:4', name: null }]
  it('the card name where it is unique in the list, the DID where it is not or where there is none', () => {
    expect(mentionLabel(all[0], all)).toBe('session-lead')
    expect(mentionLabel(all[1], all)).toBe('did:x:2')        // the server resolves a card name only where it is unique
    expect(mentionLabel(all[3], all)).toBe('did:x:4')
  })
})
