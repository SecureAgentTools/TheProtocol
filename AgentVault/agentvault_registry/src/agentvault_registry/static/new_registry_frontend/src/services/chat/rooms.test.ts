// V0659 (f): the console's room helpers (services/chat/rooms.ts).
import { describe, expect, it } from 'vitest'
import { actsOn, joinAddressFromQuery, parseRoomAddress, roomJoinLink, type RoomMember } from './rooms'

const ADDR = 'room:5ffc6863-675a-40fb-8fc0-ad68be73d642@https://Sandbox-A.TheProtocol.cloud'

describe('a room address', () => {
  it('names its room and its host (the host as an origin)', () => {
    expect(parseRoomAddress(ADDR)).toEqual({ id: '5ffc6863-675a-40fb-8fc0-ad68be73d642',
                                             host: 'https://sandbox-a.theprotocol.cloud' })
  })
  it('anything else is no address', () => {
    for (const bad of ['', 'room:', 'room:abc', 'dm:abc@https://a.example', 'room:@https://a.example', 'room:abc@nohost', null]) {
      expect(parseRoomAddress(bad)).toBeNull()
    }
  })
  it('its link is relative, so it opens on the joiner own console, and the query gives it back', () => {
    const link = roomJoinLink(ADDR)
    expect(link.startsWith('#/ourchat?join=')).toBe(true)
    const q = Object.fromEntries(new URLSearchParams(link.split('?')[1]))
    expect(joinAddressFromQuery(q)).toBe(ADDR)
    expect(joinAddressFromQuery({ join: 'not-a-room' })).toBeNull()
    expect(joinAddressFromQuery({})).toBeNull()
  })
})

const m = (over: Partial<RoomMember>): RoomMember =>
  ({ key: 'k', name: 'n', remote: true, role: 'member', state: 'active', can_post: true, ...over })

describe('what an operator may do to a member', () => {
  it('the owner mutes, removes, bans and names a moderator', () => {
    expect(actsOn(m({}), 'owner', 'dev:1')).toEqual(['mute', 'remove', 'ban', 'moderator'])
    expect(actsOn(m({ can_post: false }), 'owner', 'dev:1')[0]).toBe('unmute')
    expect(actsOn(m({ role: 'moderator' }), 'owner', 'dev:1')).toContain('unmoderator')
  })
  it('a request is accepted or refused', () => {
    expect(actsOn(m({ state: 'pending' }), 'moderator', 'dev:2')).toEqual(['accept', 'remove', 'ban'])
  })
  it('a moderator never acts on another moderator, the owner or itself; a member acts on nobody', () => {
    expect(actsOn(m({ role: 'moderator' }), 'moderator', 'dev:2')).toEqual([])
    expect(actsOn(m({ role: 'owner' }), 'owner', 'dev:1')).toEqual([])
    expect(actsOn(m({ key: 'dev:2' }), 'moderator', 'dev:2')).toEqual([])
    expect(actsOn(m({}), 'member', 'dev:3')).toEqual([])
  })
})
