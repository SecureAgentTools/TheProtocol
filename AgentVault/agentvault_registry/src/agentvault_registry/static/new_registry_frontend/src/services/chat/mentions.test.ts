import { describe, expect, it } from 'vitest'
import { bellTarget, inView, mentionsOfYou, namesYou, pillState, pillText, showAtMark, supersededByGroup, unreadMentions } from './mentions'

const you = (id: string, seq: number, extra: any = {}) => ({ id, seq, body: 'hi', mentions: [{ key: 'dev:6' }], ...extra })

describe('namesYou: the narrow mention', () => {
  it('is your stored key and nothing else', () => {
    expect(namesYou(you('a', 1), 'dev:6')).toBe(true)
    expect(namesYou(you('a', 1), 'dev:7')).toBe(false)
    expect(namesYou({ id: 'b', seq: 2, body: '@all hello', mentions: null }, 'dev:6')).toBe(false)       // @all names nobody
    expect(namesYou({ id: 'c', seq: 3, body: '@everyone' }, 'dev:6')).toBe(false)
    expect(namesYou(you('d', 4, { deleted: true }), 'dev:6')).toBe(false)
    expect(namesYou(you('e', 5, { deleted_at: '2026-11-13T00:00:00Z' }), 'dev:6')).toBe(false)
    expect(namesYou(you('f', 6), null)).toBe(false)
  })
})

describe('mentionsOfYou', () => {
  it('merges the page and the server read, each line once, oldest first, never your own line', () => {
    const page = [you('m3', 3), you('m1', 1, { body: 'short' })]
    const server = [you('m1', 1, { body: 'full text' }), you('m9', 9, { sender_name: 'Me' })]
    const out = mentionsOfYou([page, server, null], 'dev:6', (m) => m.id === 'm9')
    expect(out.map((m) => m.id)).toEqual(['m1', 'm3'])
    expect(out[0].body).toBe('full text')           // the later source fills in
  })
})

describe('the pill', () => {
  const rows = [you('a', 4), you('b', 7), you('c', 12)]
  it('counts the unread, above the mark and not yet seen, and points at the oldest', () => {
    const unread = unreadMentions(rows, 5, new Set([12]))
    expect(unread.map((m) => m.id)).toEqual(['b'])
    expect(pillState(unread)).toEqual({ count: 1, oldestSeq: 7 })
    expect(pillState(unreadMentions(rows, 0, new Set()))).toEqual({ count: 3, oldestSeq: 4 })
  })
  it('is absent when nothing is unread', () => {
    expect(pillState(unreadMentions(rows, 99, new Set()))).toEqual({ count: 0, oldestSeq: null })
  })
  it('reads "Mentioned you" for one and "Mentioned you, 2" for more', () => {
    expect(pillText('Mentioned you', 1)).toBe('Mentioned you')
    expect(pillText('Mentioned you', 2)).toBe('Mentioned you, 2')
  })
})

describe('inView', () => {
  it('is a box overlapping the container, and false for a container with no height', () => {
    const view = { top: 100, bottom: 500 }
    expect(inView({ top: 120, bottom: 160 }, view)).toBe(true)
    expect(inView({ top: 480, bottom: 540 }, view)).toBe(true)      // in part
    expect(inView({ top: 520, bottom: 560 }, view)).toBe(false)
    expect(inView({ top: 20, bottom: 100 }, view)).toBe(false)
    expect(inView({ top: 0, bottom: 0 }, { top: 0, bottom: 0 })).toBe(false)
  })
})

describe('the room list mark', () => {
  it('shows for a counted mention and says nothing for none or for a count that could not be taken', () => {
    expect(showAtMark(2)).toBe(true)
    expect(showAtMark(0)).toBe(false)
    expect(showAtMark(null)).toBe(false)
    expect(showAtMark(undefined)).toBe(false)
  })
})

describe('the bell', () => {
  const room = '269dd5af-93d1-4fe2-96b0-43c4039f7009'
  it('hides a chat.mention notice for a room the Mentions group shows, and keeps every other entry', () => {
    const g = new Set([room])
    expect(supersededByGroup({ type_key: 'chat.mention', click: `/ui#/pocket/ourchat/${room}` }, g)).toBe(true)
    expect(supersededByGroup({ type_key: 'chat.mention', click: '/ui#/pocket/ourchat/11111111-2222-3333-4444-555555555555' }, g)).toBe(false)   // an @all room
    expect(supersededByGroup({ type_key: 'guild.bid_received', click: `/ui#/pocket/ourchat/${room}` }, g)).toBe(false)
    expect(supersededByGroup({ type_key: 'chat.mention', click: null }, g)).toBe(false)
  })
  it('opens the thread at the line', () => {
    expect(bellTarget({ conversation_id: room, id: 'm1' })).toEqual({ path: `/ourchat/${room}`, query: { m: 'm1' } })
  })
})

import { splitMentions } from './mentions'
describe('splitMentions (the bell\'s preview: the mention token in the mention colour)', () => {
  it('splits a line into text and @tokens, in order, losing nothing', () => {
    const parts = splitMentions('Please look, @Commander and @mira_2 now')
    expect(parts.map((p) => p.text).join('')).toBe('Please look, @Commander and @mira_2 now')
    expect(parts.filter((p) => p.at).map((p) => p.text)).toEqual(['@Commander', '@mira_2'])
  })
  it('marks the viewer\'s own mention (by name, any case) apart from the others', () => {
    const parts = splitMentions('@commander and @Mira', ['Commander'])
    expect(parts.filter((p) => p.at).map((p) => [p.text, p.me])).toEqual([['@commander', true], ['@Mira', false]])
  })
  it('does not take an e-mail address or a bare @ for a mention', () => {
    expect(splitMentions('mail me a@b.example or @ alone').some((p) => p.at)).toBe(false)
    expect(splitMentions('')).toEqual([])
  })
})
