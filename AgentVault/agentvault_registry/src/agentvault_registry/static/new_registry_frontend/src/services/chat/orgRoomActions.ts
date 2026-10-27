/**
 * services/chat/orgRoomActions.ts — §OURSTATE-2, the ONE room-operator brain.
 *
 * The chat is the org's admin panel, but authority never lives here: every op
 * is EXECUTED by the server against the LIVE organization_members table, and
 * this module only decides what the current human may be OFFERED — and says
 * WHY when the answer is nothing (the guildActions S5 rule, same file shape).
 *
 * Two laws it encodes:
 *  - /kick targets the ROOM. Org removal is the org rail's own explicit,
 *    separately-named action — offered here only as a DOOR (`door:
 *    'org-rail'`) so the chat surface structurally cannot express an org
 *    mutation (strategy v3: "this schema cannot express an org mutation by
 *    construction").
 *  - Destructive acts (kick, mode flips) are hold-to-execute: `destructive`
 *    is the flag the FE binds the hold gesture to.
 *
 * Rank rule mirrors services/chat_service.py::can_act_on EXACTLY: an operator
 * acts on a STRICTLY lower org rank, or on a role-less principal (a
 * room-joined agent holds no org role). Never upward, never lateral.
 */

export type OrgRole = 'owner' | 'admin' | 'member' | 'guest' | null

export const ROOM_ROLE_RANK: Record<string, number> = { owner: 3, admin: 2, member: 1, guest: 0 }
export const ROOM_OPS_ROLES = ['owner', 'admin'] as const

export interface RoomCtx {
  myOrgRole: OrgRole
  myCanPost: boolean
  mode: 'open' | 'announce'
  myState?: string           // 'active' | 'pending' | 'left'
}

export interface RoomMemberView {
  ptype: 'developer' | 'agent'
  id: string                 // developer_id as string, or agent_did
  name?: string
  orgRole: OrgRole           // null = room-joined principal with no org role
  canPost: boolean
  isMe: boolean
}

export interface RoomActionOffer {
  key: 'kick' | 'mute' | 'unmute' | 'mode' | 'topic' | 'motd' | 'orgRemove'
  label: string              // English fallback; callers translate off `key`
  destructive: boolean       // true = hold-to-execute in the FE
  door?: 'org-rail'          // set = this is NOT a chat op; route to the org rail
  value?: string             // for `mode`: the mode this offer flips TO
}

export function isOperator(role: OrgRole): boolean {
  return role === 'owner' || role === 'admin'
}

/** Mirror of the server rule — for OFFERING only; the server re-checks live. */
export function canActOn(myRole: OrgRole, targetRole: OrgRole): boolean {
  if (!isOperator(myRole)) return false
  if (targetRole === null || targetRole === undefined) return true
  return (ROOM_ROLE_RANK[myRole as string] ?? 0) > (ROOM_ROLE_RANK[targetRole] ?? 0)
}

/**
 * The composer's state in this room: may I type here, and if not, why —
 * a blocked composer that does not say why is a defect, not a design.
 */
export function composerCan(ctx: RoomCtx): { canPost: boolean; note: string; noteKey: string } {
  if (ctx.myState && ctx.myState !== 'active') {
    return { canPost: false, note: 'You are not in this room.', noteKey: 'notMember' }
  }
  if (!ctx.myCanPost) {
    return { canPost: false, note: 'A room operator muted you here — you can read, not post.', noteKey: 'muted' }
  }
  if (ctx.mode === 'announce' && !isOperator(ctx.myOrgRole)) {
    return { canPost: false, note: 'Announce-only — org owners and admins post here.', noteKey: 'announceOnly' }
  }
  return { canPost: true, note: '', noteKey: '' }
}

/** Room-level operations (topic / motd / mode). Empty for non-operators. */
export function roomOps(ctx: RoomCtx): RoomActionOffer[] {
  if (!isOperator(ctx.myOrgRole)) return []
  const flipTo = ctx.mode === 'announce' ? 'open' : 'announce'
  return [
    { key: 'topic', label: 'Set topic', destructive: false },
    { key: 'motd', label: 'Edit room genesis', destructive: false },
    {
      key: 'mode',
      label: flipTo === 'announce' ? 'Switch to announce-only' : 'Open the room',
      destructive: true,
      value: flipTo,
    },
  ]
}

/**
 * Per-member operations. The rank rule gates everything; `orgRemove` is the
 * one DOOR out of chat (the org rail's own removal, its own confirm, its own
 * audit) and is offered only for developers an operator outranks — an agent's
 * org assignment is managed on the agent, not here.
 */
export function memberOps(ctx: RoomCtx, member: RoomMemberView): RoomActionOffer[] {
  if (member.isMe) return []
  if (!canActOn(ctx.myOrgRole, member.orgRole)) return []
  const out: RoomActionOffer[] = []
  out.push(member.canPost
    ? { key: 'mute', label: 'Mute in this room', destructive: false }
    : { key: 'unmute', label: 'Unmute', destructive: false })
  out.push({ key: 'kick', label: 'Remove from room', destructive: true })
  if (member.ptype === 'developer') {
    out.push({ key: 'orgRemove', label: 'Remove from organization…', destructive: true, door: 'org-rail' })
  }
  return out
}

/**
 * Render a server system row (`body: 'room.<action>'`) as one honest line.
 * Returns the assembled English (`text`, the fallback), a `template` with
 * placeholders, and the `params` — so callers localize via
 * tp('ourstate.rooms.row.' + key, template, params) and a locale keeps its own
 * word order (the §POCKETI18N concatenation rule; names live OUTSIDE the tail).
 */
export function systemRowText(body: string, card: any):
  { key: string; text: string; template: string; params: Record<string, string> } {
  const action = String(body || '').replace(/^room\./, '')
  const by = String(card?.by_name || card?.by || 'An operator')
  const target = card?.target_name ? String(card.target_name) : 'a member'
  const value = card?.value != null ? String(card.value) : ''
  const mk = (key: string, template: string, params: Record<string, string>) => ({
    key, template, params,
    text: template.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? ''),
  })
  switch (action) {
    case 'kick': return mk('kick', '{by} removed {target} from the room', { by, target })
    case 'mute': return mk('mute', '{by} muted {target}', { by, target })
    case 'unmute': return mk('unmute', '{by} unmuted {target}', { by, target })
    case 'mode': return value === 'announce'
      ? mk('modeAnnounce', '{by} set the room to announce-only', { by })
      : mk('modeOpen', '{by} opened the room', { by })
    case 'topic': return value
      ? mk('topic', '{by} set the topic: {value}', { by, value })
      : mk('topicClear', '{by} cleared the topic', { by })
    case 'motd': return mk('motd', '{by} updated the room genesis', { by })
    // §ROOMBRAIN — presence changes are VISIBLE rows both ways (the law)
    case 'assistant_on': return mk('assistantOn',
      '{by} added @assistant to this room — it answers when addressed, reading only this organization\'s records', { by })
    case 'assistant_off': return mk('assistantOff', '{by} removed @assistant from this room', { by })
    default: return mk('unknown', '{by} performed a room action', { by })
  }
}
