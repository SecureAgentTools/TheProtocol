/**
 * V0654 (ap) (order gwo_03a846cb91b37628c3c6710a): the assistant in OurChat, as the console keeps it.
 *
 * His words (the sessions' room, seq 1091): "I want to activate the assistant in our chat. So it is pickable. Ai
 * assistant active or not. Additional option in the choosing of the identity to send with. ... I want the button to
 * maybe turn yellow or whatever when ai assistant for this identity is activated. It should create a little thing that
 * states my prompt visible for myself ... and then when Claude assistant is ready sending the answer it appears below."
 *
 * - The switch is per identity ("you", or one of your agents by DID) and per room, kept on THIS device (localStorage),
 *   like the speaker choice (speakAs.ts). Off unless switched on.
 * - What you asked stays on this device too: the requests shown in a room, kept for this browser session only
 *   (sessionStorage), never sent to the room. The registry posts the assistant's answer; the request is yours alone.
 */

const ON_PREFIX = 'ourchat.assist.'
const ASKS_PREFIX = 'ourchat.assistAsks.'
const ASKS_KEPT = 20

/** The identity key for "you" (an agent's is its DID). */
export const YOU = 'you'

type KV = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function local(s?: KV | null): KV | null {
  if (s) return s
  try { return typeof localStorage !== 'undefined' ? localStorage : null } catch { return null }
}

function session(s?: KV | null): KV | null {
  if (s) return s
  try { return typeof sessionStorage !== 'undefined' ? sessionStorage : null } catch { return null }
}

function validWho(who: string): boolean {
  return who === YOU || who.startsWith('did:')
}

/** The identities whose assistant is on in this room, on this device. */
export function assistantIds(conversationId: string, s?: KV | null): string[] {
  const kv = local(s)
  if (!kv || !conversationId) return []
  try {
    const v = JSON.parse(kv.getItem(ON_PREFIX + conversationId) || '[]')
    return Array.isArray(v) ? v.filter((x: unknown) => typeof x === 'string' && validWho(x)) : []
  } catch { return [] }
}

/** Switch the assistant on or off for one identity in this room; off for all of them leaves nothing stored. */
export function rememberAssistant(conversationId: string, who: string, on: boolean, s?: KV | null): string[] {
  const kv = local(s)
  if (!kv || !conversationId || !validWho(who)) return assistantIds(conversationId, s)
  const ids = new Set(assistantIds(conversationId, kv))
  if (on) ids.add(who)
  else ids.delete(who)
  try {
    if (ids.size) kv.setItem(ON_PREFIX + conversationId, JSON.stringify([...ids]))
    else kv.removeItem(ON_PREFIX + conversationId)
  } catch { /* a full or blocked storage: the switch holds for this page only */ }
  return [...ids]
}

/** One request to the assistant, as this device shows it. */
export interface AssistAsk {
  /** the client_ref the answer is posted with: asking again with it returns that answer, never a second one */
  ref: string
  conversationId: string
  prompt: string
  /** the name of the identity the answer is posted as, the agent's; empty for you */
  who: string
  /** that identity's key (YOU or a DID): asking again goes out as it, never as another */
  whoKey?: string
  /** the message the answer replies to (it folds under it) */
  replyTo?: string
  /** the seq of the room's latest line when it was asked: the request shows after that line, the answer comes below */
  afterSeq: number
  state: 'waiting' | 'answered' | 'failed'
  error?: string
  answerSeq?: number
}

/** The requests kept for this room in this browser session. One still waiting when the page went away is read back as
 *  failed: its answer may have been posted, and asking again with its ref returns it without asking twice. */
export function readAsks(conversationId: string, reloadedNote: string, s?: KV | null): AssistAsk[] {
  const kv = session(s)
  if (!kv || !conversationId) return []
  try {
    const v = JSON.parse(kv.getItem(ASKS_PREFIX + conversationId) || '[]')
    if (!Array.isArray(v)) return []
    return v.filter((a: any) => a && typeof a.ref === 'string' && typeof a.prompt === 'string')
      .map((a: any): AssistAsk => (a.state === 'waiting' ? { ...a, state: 'failed', error: reloadedNote } : a))
  } catch { return [] }
}

/** Keep this room's requests for the browser session (the newest ASKS_KEPT). */
export function writeAsks(conversationId: string, asks: AssistAsk[], s?: KV | null): void {
  const kv = session(s)
  if (!kv || !conversationId) return
  try {
    const mine = asks.filter(a => a.conversationId === conversationId).slice(-ASKS_KEPT)
    if (mine.length) kv.setItem(ASKS_PREFIX + conversationId, JSON.stringify(mine))
    else kv.removeItem(ASKS_PREFIX + conversationId)
  } catch { /* a full or blocked storage: they stay for this page only */ }
}
