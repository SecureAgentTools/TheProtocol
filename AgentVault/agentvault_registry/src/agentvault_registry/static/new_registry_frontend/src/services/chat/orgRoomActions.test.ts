// §OURSTATE-2 — the room-operator brain, asserted deep (the guildActions way).
import { describe, it, expect } from 'vitest'
import {
  canActOn, composerCan, roomOps, memberOps, systemRowText, isOperator,
  type RoomCtx, type RoomMemberView,
} from './orgRoomActions'

const ctx = (over: Partial<RoomCtx> = {}): RoomCtx => ({
  myOrgRole: 'member', myCanPost: true, mode: 'open', myState: 'active', ...over,
})
const member = (over: Partial<RoomMemberView> = {}): RoomMemberView => ({
  ptype: 'developer', id: '7', name: 'Dana', orgRole: 'member', canPost: true, isMe: false, ...over,
})

describe('canActOn (mirror of the server rule)', () => {
  it('acts strictly downward', () => {
    expect(canActOn('owner', 'admin')).toBe(true)
    expect(canActOn('admin', 'member')).toBe(true)
    expect(canActOn('admin', 'guest')).toBe(true)
  })
  it('never upward or lateral', () => {
    expect(canActOn('admin', 'owner')).toBe(false)
    expect(canActOn('admin', 'admin')).toBe(false)
    expect(canActOn('owner', 'owner')).toBe(false)
  })
  it('non-operators act on nobody; role-less targets are actionable', () => {
    expect(canActOn('member', 'guest')).toBe(false)
    expect(canActOn(null, 'member')).toBe(false)
    expect(canActOn('owner', null)).toBe(true)
    expect(canActOn('admin', null)).toBe(true)
  })
})

describe('composerCan (blocked surfaces say why)', () => {
  it('open room, active, unmuted: post', () => {
    expect(composerCan(ctx())).toEqual({ canPost: true, note: '', noteKey: '' })
  })
  it('muted row reads but does not post — and says so', () => {
    const r = composerCan(ctx({ myCanPost: false }))
    expect(r.canPost).toBe(false)
    expect(r.noteKey).toBe('muted')
  })
  it('announce mode blocks members and names the mode', () => {
    const r = composerCan(ctx({ mode: 'announce' }))
    expect(r.canPost).toBe(false)
    expect(r.noteKey).toBe('announceOnly')
  })
  it('announce mode admits operators', () => {
    expect(composerCan(ctx({ mode: 'announce', myOrgRole: 'admin' })).canPost).toBe(true)
    expect(composerCan(ctx({ mode: 'announce', myOrgRole: 'owner' })).canPost).toBe(true)
  })
  it('left/pending rows are not members', () => {
    expect(composerCan(ctx({ myState: 'left' })).noteKey).toBe('notMember')
  })
  it('mute outranks announce in the reason (most personal first)', () => {
    const r = composerCan(ctx({ mode: 'announce', myOrgRole: 'admin', myCanPost: false }))
    expect(r.noteKey).toBe('muted')
  })
})

describe('roomOps', () => {
  it('members get nothing', () => {
    expect(roomOps(ctx())).toEqual([])
    expect(roomOps(ctx({ myOrgRole: 'guest' }))).toEqual([])
    expect(roomOps(ctx({ myOrgRole: null }))).toEqual([])
  })
  it('operators get topic/motd/mode; mode is destructive and flips', () => {
    const ops = roomOps(ctx({ myOrgRole: 'admin' }))
    expect(ops.map(o => o.key)).toEqual(['topic', 'motd', 'mode'])
    const mode = ops.find(o => o.key === 'mode')!
    expect(mode.destructive).toBe(true)
    expect(mode.value).toBe('announce')
    const back = roomOps(ctx({ myOrgRole: 'admin', mode: 'announce' })).find(o => o.key === 'mode')!
    expect(back.value).toBe('open')
  })
})

describe('memberOps', () => {
  it('never on yourself', () => {
    expect(memberOps(ctx({ myOrgRole: 'owner' }), member({ isMe: true }))).toEqual([])
  })
  it('rank rule gates the whole set', () => {
    expect(memberOps(ctx({ myOrgRole: 'admin' }), member({ orgRole: 'owner' }))).toEqual([])
    expect(memberOps(ctx({ myOrgRole: 'admin' }), member({ orgRole: 'admin' }))).toEqual([])
    expect(memberOps(ctx({ myOrgRole: 'member' }), member())).toEqual([])
  })
  it('operator over a member: mute + kick(hold) + the org-rail DOOR', () => {
    const ops = memberOps(ctx({ myOrgRole: 'owner' }), member())
    expect(ops.map(o => o.key)).toEqual(['mute', 'kick', 'orgRemove'])
    expect(ops.find(o => o.key === 'kick')!.destructive).toBe(true)
    const door = ops.find(o => o.key === 'orgRemove')!
    expect(door.door).toBe('org-rail')
    expect(door.destructive).toBe(true)
  })
  it('a muted member is offered unmute instead', () => {
    const ops = memberOps(ctx({ myOrgRole: 'admin' }), member({ canPost: false }))
    expect(ops[0].key).toBe('unmute')
  })
  it('agents (role-less) are moderatable but carry NO org-removal door', () => {
    const ops = memberOps(ctx({ myOrgRole: 'admin' }),
      member({ ptype: 'agent', id: 'did:theprotocol:x', orgRole: null }))
    expect(ops.map(o => o.key)).toEqual(['mute', 'kick'])
  })
})

describe('systemRowText', () => {
  it('renders each action off the server-authored card', () => {
    expect(systemRowText('room.kick', { by_name: 'Ada', target_name: 'Bob' }).text)
      .toBe('Ada removed Bob from the room')
    expect(systemRowText('room.mode', { by_name: 'Ada', value: 'announce' }).text)
      .toBe('Ada set the room to announce-only')
    expect(systemRowText('room.mode', { by_name: 'Ada', value: 'open' }).text)
      .toBe('Ada opened the room')
    expect(systemRowText('room.topic', { by_name: 'Ada', value: 'Q3' }).text)
      .toBe('Ada set the topic: Q3')
    expect(systemRowText('room.motd', { by_name: 'Ada' }).key).toBe('motd')
  })
  it('degrades honestly on a malformed card', () => {
    const r = systemRowText('room.whatnot', null)
    expect(r.key).toBe('unknown')
    expect(r.text).toContain('An operator')
  })
})

describe('isOperator', () => {
  it('exactly owner|admin', () => {
    expect(isOperator('owner')).toBe(true)
    expect(isOperator('admin')).toBe(true)
    expect(isOperator('member')).toBe(false)
    expect(isOperator(null)).toBe(false)
  })
})
