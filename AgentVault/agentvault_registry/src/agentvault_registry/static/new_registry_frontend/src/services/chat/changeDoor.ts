// V0666 D3 (order gwo_542285271416c653ca39af3f): the /change door, pure. In an organization's room, /change <title> opens the
// Code changes proposal for that organization's release line (its code distribution, never a payout), announced in this
// room (its live card and state lines); several active lines offer a picker; otherwise one sentence says why nothing opens.
// The registry decides again at the proposal (D1's member and path rules, D3's room rule).
type Tr = (key: string, fallback: string, params?: Record<string, unknown>) => string
export interface DoorLine { slug: string; title?: string; release_name?: string; state?: string }
export interface Target { name: 'code-changes-new' | 'content-changes-new'; query: Record<string, string> }
export type ChangeDoor =
  | { kind: 'refuse'; sentence: string }
  | { kind: 'go'; to: Target }
  | { kind: 'pick'; lines: DoorLine[]; to: (slug: string) => Target }

/** V0667 D5: "/change content <title>" proposes a CONTENT change (the fast lane) to the room's line instead of a code change; anything else is the code door as before. */
export function splitContent(title: string): { content: boolean; title: string } {
  const m = /^content(?:\s+|$)/i.exec(title.trim())
  return m ? { content: true, title: title.trim().slice(m[0].length).trim() } : { content: false, title: title.trim() }
}

export function changeDoor(ctx: { enabled: boolean; orgId: string; convId: string; title: string; lines: DoorLine[] }, tr: Tr): ChangeDoor {
  const asked = splitContent(ctx.title)
  if (!ctx.enabled) return { kind: 'refuse', sentence: tr('contributions.off', 'Code distributions are off on this registry.') }
  if (!ctx.orgId) {
    return { kind: 'refuse', sentence: tr('contributions.chat.notOrgRoom', '/change works in a room of an organization: it proposes a change to that organization\'s release line.') }
  }
  if (!ctx.lines.length) {
    return { kind: 'refuse', sentence: tr('contributions.chat.noLine', 'This organization has no release line yet; its owners and admins create one under Contributions.') }
  }
  const open = ctx.lines.filter((l) => l.state !== 'paused')
  if (!open.length) return { kind: 'refuse', sentence: tr('contributions.chat.allPaused', 'Every release line of this organization is paused: no change is proposed until one resumes.') }
  const to = (slug: string): Target => {
    const query: Record<string, string> = { line: slug, room: ctx.convId }
    if (asked.title) query.title = asked.title
    return { name: asked.content ? 'content-changes-new' : 'code-changes-new', query }
  }
  return open.length === 1 ? { kind: 'go', to: to(open[0].slug) } : { kind: 'pick', lines: open, to }
}
