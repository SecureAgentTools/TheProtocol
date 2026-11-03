/**
 * V0654 (ap) (order gwo_03a846cb91b37628c3c6710a): the assistant in OurChat, as the console keeps it.
 *
 * The assistant in the chat is pickable, on or off, as an option in the choice of the identity to send with; the
 * button turns amber while it is on for that identity; the prompt shows to its author alone, and the assistant's
 * answer appears below it.
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

/** Where each request is drawn among the lines a thread shows (their seqs). V0655 (av), order
 *  gwo_ce52bf8dc39e7202817f16c7: a request belongs with its answer, not with the chat box. An answered request sits
 *  directly above its answer, wherever the answer is drawn (the main list, or inside the thread its reply folds it into),
 *  and scrolls away with it; while its answer is not drawn (its thread folded, or older than the loaded lines) the
 *  request is not drawn either. A waiting or refused request, or an answered one whose answer has no seq, keeps V0654's
 *  place: after the line it followed, or at the bottom while that line is not drawn. Before V0655 an answered request
 *  kept that place too, so one asked after a line that then sat inside a folded thread stayed above the chat box for
 *  good.
 */
export interface AskPlaces {
  /** answered requests, by the seq of the answer they sit above */
  before: Map<number, AssistAsk[]>
  /** the others, by the seq of the line they follow */
  after: Map<number, AssistAsk[]>
  /** the others whose line is not drawn */
  bottom: AssistAsk[]
}

export function placeAsks(asks: AssistAsk[], shown: Set<number>): AskPlaces {
  const places: AskPlaces = { before: new Map(), after: new Map(), bottom: [] }
  const put = (m: Map<number, AssistAsk[]>, seq: number, a: AssistAsk) => m.set(seq, [...(m.get(seq) ?? []), a])
  for (const a of asks) {
    const answer = a.state === 'answered' ? Number(a.answerSeq) || 0 : 0
    if (answer) {
      if (shown.has(answer)) put(places.before, answer, a)
      continue
    }
    const line = Number(a.afterSeq) || 0
    if (shown.has(line)) put(places.after, line, a)
    else places.bottom.push(a)
  }
  return places
}
