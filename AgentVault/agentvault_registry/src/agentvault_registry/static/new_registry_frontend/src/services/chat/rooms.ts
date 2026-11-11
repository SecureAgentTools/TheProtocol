// V0659 (f): cross-frame rooms in the console (the server: services/chat_rooms.py; the design:
// sessionlogs2026/DESIGN_2026-11-07_XFRAME_ROOMS.md). A room is hosted by the registry it was opened on; a member on
// another registry joins it by its ADDRESS, room:<id>@https://its.registry, through its own registry's console. The
// address is what one shares; the link form, #/ourchat?join=<address>, opens it in whichever console it is pasted into.

import type { RoomJoinRule } from '@/services/api/chat'

export const JOIN_RULES: RoomJoinRule[] = ['invited', 'request', 'anyone']

/** 'room:<id>@https://host' -> { id, host } (the host's origin), or null. */
export function parseRoomAddress(raw: unknown): { id: string; host: string } | null {
  const s = String(raw ?? '').trim()
  if (!/^room:/i.test(s)) return null
  const at = s.lastIndexOf('@')
  if (at < 0) return null
  const id = s.slice(5, at).trim()
  const host = s.slice(at + 1).trim()
  if (!id || !/^https?:\/\/[^\s/]+/i.test(host)) return null
  try {
    const u = new URL(host)
    return { id, host: `${u.protocol}//${u.host}`.toLowerCase() }
  } catch {
    return null
  }
}

/** The link that opens a room's join in a console: relative, so it works on the joiner's own registry. */
export function roomJoinLink(address: string): string {
  return `#/ourchat?join=${encodeURIComponent(address)}`
}

/** The address a ?join= query carries, when it is one. */
export function joinAddressFromQuery(query: Record<string, unknown>): string | null {
  const v = Array.isArray(query?.join) ? query.join[0] : query?.join
  return parseRoomAddress(v) ? String(v).trim() : null
}

export interface RoomMember {
  key: string
  name: string
  remote: boolean
  role: string
  state: string
  can_post: boolean
}

/** The acts an operator may take on `m` (the owner names moderators; nobody acts on the owner or on themselves). */
export function actsOn(m: RoomMember, myRole: string, myKey: string | null): string[] {
  if (m.key === myKey || m.role === 'owner') return []
  if (myRole !== 'owner' && myRole !== 'moderator') return []
  if (m.role === 'moderator' && myRole !== 'owner') return []
  if (m.state === 'pending') return ['accept', 'remove', 'ban']
  const out = [m.can_post ? 'mute' : 'unmute', 'remove', 'ban']
  if (myRole === 'owner') out.push(m.role === 'moderator' ? 'unmoderator' : 'moderator')
  return out
}
