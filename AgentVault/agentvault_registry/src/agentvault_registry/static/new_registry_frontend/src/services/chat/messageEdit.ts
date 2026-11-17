/**
 * V0662 (OurChat lane): editing and taking back a message, the console's half (the registry's: services/chat_edits.py,
 * PUT/DELETE /chat/conversations/{id}/messages/{mid}, GET .../history).
 *
 * The registry decides, and says why in a sentence when it refuses. This only decides whether to OFFER the controls:
 * your own text message, not taken back, inside the window the registry's default sets (15 minutes; a registry may set
 * another, so a late press can still be refused and the sentence is shown). It also folds a change a thread hears
 * (`chat.message_edited`, `chat.message_deleted`) into the messages the thread holds.
 */

/** The registry's default window (CHAT_EDIT_WINDOW_S). */
export const EDIT_WINDOW_MS = 900_000

export interface ChangeMsg {
  id?: string
  kind?: string
  body?: string | null
  deleted?: boolean
  created_at?: string | null
  edited_at?: string | null
  [k: string]: any
}

/** Whether to offer Edit and Delete on a line: yours, a text message, still standing, inside the window. */
export function canChange(m: ChangeMsg | null | undefined, mine: boolean, nowMs: number): boolean {
  if (!m || !m.id || !mine || m.deleted || m.kind !== 'text') return false
  const at = Date.parse(String(m.created_at || ''))
  return Number.isFinite(at) && nowMs - at <= EDIT_WINDOW_MS
}

/** Milliseconds left to change a line (0 when none, or when it is not one that can be changed). */
export function windowLeftMs(m: ChangeMsg | null | undefined, nowMs: number): number {
  const at = Date.parse(String(m?.created_at || ''))
  return Number.isFinite(at) ? Math.max(0, at + EDIT_WINDOW_MS - nowMs) : 0
}

/**
 * Fold one change into what the thread holds, by id. An edit takes the newer body and its edited_at (an older or equal
 * edited_at, or a line already taken back, changes nothing); a take-back turns the line into the tombstone the registry
 * serves (no body, no card, deleted). A message the thread does not hold is none of its business (a reload reads it).
 */
export function applyMessageChange<T extends ChangeMsg>(have: T[], change: ChangeMsg | null | undefined): { messages: T[]; changed: boolean } {
  if (!change || !change.id) return { messages: have, changed: false }
  const i = have.findIndex((m) => m.id === change.id)
  if (i < 0) return { messages: have, changed: false }
  const cur = have[i]
  if (cur.deleted) return { messages: have, changed: false }
  let next: T
  if (change.deleted) {
    next = { ...cur, kind: 'system', body: null, card: null, mentions: [], deleted: true, reply_to: null }
  } else {
    const was = Date.parse(String(cur.edited_at || '')) || 0
    const now = Date.parse(String(change.edited_at || '')) || 0
    if (!change.edited_at || now <= was || typeof change.body !== 'string') return { messages: have, changed: false }
    next = { ...cur, body: change.body, edited_at: change.edited_at }
  }
  const messages = have.slice()
  messages[i] = next
  return { messages, changed: true }
}

/**
 * The long-poll's `updates` lane carries edits and take-backs beside card updates (registry: services/chat_service.py::
 * _message_changes_since): `{id, conversation_id, change: 'edit'|'delete', body, edited_at, deleted_at}`. These are the
 * ones for this thread, as the changes applyMessageChange takes, oldest first; a card update (no `change`) is not here.
 */
export function changesFromUpdates(updates: any, conversationId: string): ChangeMsg[] {
  const out: ChangeMsg[] = []
  for (const u of Array.isArray(updates) ? updates : []) {
    if (!u || u.conversation_id !== conversationId || !u.id) continue
    if (u.change === 'delete') out.push({ id: u.id, deleted: true })
    else if (u.change === 'edit') out.push({ id: u.id, body: u.body, edited_at: u.edited_at })
  }
  return out
}
