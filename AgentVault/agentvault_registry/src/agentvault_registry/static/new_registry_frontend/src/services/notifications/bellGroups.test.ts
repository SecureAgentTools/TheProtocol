import { describe, expect, it } from 'vitest'
import type { FeedItem } from '@/stores/notifications'
import { canMute, groupFeed, kindLabel, kindOf, loadMuted, MUTED_KEY, parseMuted, quietLine, saveMuted, toggleMuted } from './bellGroups'

let n = 0
const e = (category: string, over: Partial<FeedItem> = {}): FeedItem => ({
  id: ++n, type_key: `${category}.x`, category, severity: 'info', title: 't', body: 'b', click: null,
  created_at: new Date(Date.UTC(2026, 10, 14, 0, n)).toISOString(), read: false, ...over,
})

describe('kinds', () => {
  it('is the category, else the type key prefix, else other; labelled in words', () => {
    expect(kindOf({ category: 'Money', type_key: 'x.y' })).toBe('money')
    expect(kindOf({ category: '', type_key: 'guild.bid_received' })).toBe('guild')
    expect(kindOf({ category: '', type_key: '' })).toBe('other')
    expect(kindLabel('chat')).toBe('Chat'); expect(kindLabel('widgets')).toBe('Widgets')
  })
  it('security can never be muted', () => { expect(canMute('security')).toBe(false); expect(canMute('chat')).toBe(true) })
})

describe('groupFeed', () => {
  it('groups unread entries by kind, newest kind first and each group newest first, and drops read ones', () => {
    const feed = [e('chat'), e('money'), e('chat'), e('money', { read: true }), e('ops')]
    const g = groupFeed(feed, new Set())
    expect(g.groups.map((x) => x.kind)).toEqual(['ops', 'chat', 'money'])
    const chat = g.groups.find((x) => x.kind === 'chat')!
    expect(chat.entries.map((x) => x.id)).toEqual([feed[2].id, feed[0].id])
    expect(g.groups.find((x) => x.kind === 'money')!.entries).toHaveLength(1)
    expect(g.quiet).toEqual({ count: 0, kinds: [] })
  })
  it('folds a muted kind into the quiet line and counts it, so nothing vanishes unseen', () => {
    const g = groupFeed([e('chat'), e('chat'), e('chat'), e('money')], new Set(['chat']))
    expect(g.groups.map((x) => x.kind)).toEqual(['money'])
    expect(g.quiet.count).toBe(3)
    expect(g.quiet.kinds).toEqual([{ kind: 'chat', label: 'Chat', count: 3 }])
    expect(quietLine(g.quiet.count)).toBe('3 muted')
  })
  it('keeps a kind that cannot be muted in view, whatever the set says', () => {
    const g = groupFeed([e('security'), e('chat')], new Set(['security', 'chat']))
    expect(g.groups.map((x) => x.kind)).toEqual(['security'])
    expect(g.groups[0].canMute).toBe(false)
    expect(g.quiet.count).toBe(1)
  })
  it('is empty and honest for an empty feed', () => {
    expect(groupFeed([], new Set(['chat']))).toEqual({ groups: [], quiet: { count: 0, kinds: [] } })
  })
})

describe('the muted set', () => {
  it('reads back only kinds that can be muted and never throws on bad data', () => {
    expect(parseMuted('["chat","security",3,"", "money"]')).toEqual(new Set(['chat', 'money']))
    for (const bad of [null, undefined, '', '{', '{"a":1}', '"chat"']) expect(parseMuted(bad as any)).toEqual(new Set())
  })
  it('toggles, and refuses to mute what must not be muted', () => {
    const a = toggleMuted(new Set(), 'chat', true)
    expect(a).toEqual(new Set(['chat']))
    expect(toggleMuted(a, 'chat', false)).toEqual(new Set())
    expect(toggleMuted(new Set(), 'security', true)).toEqual(new Set())
  })
  it('round-trips through a storage and survives one that throws', () => {
    const mem: Record<string, string> = {}
    const store = { getItem: (k: string) => mem[k] ?? null, setItem: (k: string, v: string) => { mem[k] = v } }
    saveMuted(new Set(['money', 'chat']), store)
    expect(mem[MUTED_KEY]).toBe('["chat","money"]')
    expect(loadMuted(store)).toEqual(new Set(['chat', 'money']))
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('full') } }
    expect(loadMuted(broken)).toEqual(new Set())
    expect(() => saveMuted(new Set(['chat']), broken)).not.toThrow()
  })
})
