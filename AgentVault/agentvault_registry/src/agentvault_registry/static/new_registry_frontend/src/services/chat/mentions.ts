// V0663 (order 418, his request seq 3349): mentions you cannot miss. Pure rules, no network, no DOM.
//
// "A mention" here is the narrow one lead settled (seq 3391): YOUR name, handle or DID, as the registry resolved and
// stored it in a message's `mentions` (services/chat_mentions.py). @all and @everyone are not a mention of you in the pill,
// the @ mark or the bell's Mentions group (they still wake and push as before; messageText.namesViewer, which also
// counts them, keeps drawing the room's "for me" tint).

export interface MentionRow {
  id: string
  seq: number
  kind?: string
  body?: string | null
  deleted?: boolean
  deleted_at?: string | null
  created_at?: string | null
  sender_name?: string | null
  mentions?: Array<{ key?: string }> | null
}

/** Does this message name the viewer by name (the stored mention key)? Never for @all/@everyone, never for a deleted line. */
export function namesYou(m: MentionRow | null | undefined, myKey: string | null | undefined): boolean {
  if (!m || !myKey || m.deleted || m.deleted_at) return false
  return Array.isArray(m.mentions) && m.mentions.some((x) => x?.key === myKey)
}

/** The mentions of the viewer from every source (the page of the thread already read, the server's own `mentions=me` read),
 *  each once, oldest first. A line you wrote is never a mention of you. */
export function mentionsOfYou(sources: Array<MentionRow[] | null | undefined>, myKey: string | null | undefined,
                              isMine: (m: MentionRow) => boolean): MentionRow[] {
  const byId = new Map<string, MentionRow>()
  for (const list of sources) {
    for (const m of list || []) {
      if (!m?.id || !namesYou(m, myKey) || isMine(m)) continue
      byId.set(String(m.id), { ...(byId.get(String(m.id)) || {}), ...m })
    }
  }
  return [...byId.values()].sort((a, b) => Number(a.seq) - Number(b.seq))
}

/** Of the viewer's mentions, the ones not read yet: above the read mark the thread opened with, and not seen since. */
export function unreadMentions(rows: MentionRow[], readFloor: number, seen: ReadonlySet<number>): MentionRow[] {
  return rows.filter((m) => Number(m.seq) > Number(readFloor || 0) && !seen.has(Number(m.seq)))
}

export interface Pill { count: number; oldestSeq: number | null }

/** The pill: how many unread mentions there are, and the oldest one (where it jumps to). Count 0: no pill. */
export function pillState(unread: MentionRow[]): Pill {
  if (!unread.length) return { count: 0, oldestSeq: null }
  return { count: unread.length, oldestSeq: Math.min(...unread.map((m) => Number(m.seq))) }
}

/** "Mentioned you" for one, "Mentioned you, 2" for more. */
export function pillText(base: string, count: number): string {
  return count > 1 ? `${base}, ${count}` : base
}

/** Is a line's box inside the scroll container's box, even in part? (numbers, so a test needs no layout) */
export function inView(box: { top: number; bottom: number }, view: { top: number; bottom: number }): boolean {
  if (!(view.bottom > view.top)) return false      // a container with no height shows nothing
  return box.bottom > view.top && box.top < view.bottom
}

/** The room list's @ mark: the registry counted a mention of you above your read mark (null: it could not count). */
export function showAtMark(unreadMentions: number | null | undefined): boolean {
  return typeof unreadMentions === 'number' && unreadMentions > 0
}

/** A feed entry of the bell that the Mentions group already shows: a chat.mention notice for a room whose newest unread
 *  mention is in the group (the notice names the room, not the line). Other entries, an @all notice among them, stay. */
export function supersededByGroup(entry: { type_key?: string; click?: string | null }, groupRoomIds: ReadonlySet<string>): boolean {
  if (entry?.type_key !== 'chat.mention') return false
  const m = /\/ourchat\/([0-9a-f-]{8,})/i.exec(String(entry.click || ''))
  return !!m && groupRoomIds.has(m[1].toLowerCase())
}

export interface BellMention {
  id: string; conversation_id: string; kind?: string | null; title?: string | null; seq: number
  sender?: string | null; preview?: string | null; created_at?: string | null
}

/** Where a bell mention opens: the console's thread, at the line (the thread reads ?m= and jumps, loading older pages;
 *  the bell's other doors open the console's `/ourchat/<id>` too, services/notificationDoors.desktopRoute). */
export function bellTarget(m: Pick<BellMention, 'conversation_id' | 'id'>): { path: string; query: { m: string } } {
  return { path: `/ourchat/${m.conversation_id}`, query: { m: String(m.id) } }
}

export interface TextPart { text: string; at: boolean; me: boolean }

/** A plain line split into text and @tokens, for the places that show a preview as text (the bell): the token is drawn in the mention
 *  colour, and a token that is one of the viewer's own names (any case) is marked apart. An address ("a@b.example") and a bare "@" are not
 *  mentions. Nothing is lost: the parts joined are the line. */
export function splitMentions(text: string, myNames: readonly string[] = []): TextPart[] {
  const line = String(text || '')
  if (!line) return []
  const mine = new Set(myNames.map((n) => String(n).toLowerCase()).filter(Boolean))
  const out: TextPart[] = []
  const re = /(^|[^A-Za-z0-9_.])@([A-Za-z0-9_][A-Za-z0-9_.-]*)/g
  let last = 0
  for (let m = re.exec(line); m; m = re.exec(line)) {
    const start = m.index + m[1].length
    const tokenEnd = start + 1 + m[2].replace(/[.-]+$/, '').length
    if (start > last) out.push({ text: line.slice(last, start), at: false, me: false })
    const token = line.slice(start, tokenEnd)
    out.push({ text: token, at: true, me: mine.has(token.slice(1).toLowerCase()) })
    last = tokenEnd
    re.lastIndex = tokenEnd
  }
  if (last < line.length) out.push({ text: line.slice(last), at: false, me: false })
  return out
}
