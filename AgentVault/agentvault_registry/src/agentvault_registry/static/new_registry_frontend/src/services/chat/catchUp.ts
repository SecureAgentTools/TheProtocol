/**
 * V0652 (ag) (order gwo_647f50fd40c19f6f685d0c8e): the thread never goes stale silently, and it opens where you left.
 *
 * The maintainer's report (the sessions' room, seq 297): "my browser didnt auto refresh the messages (desktop, maybe
 * due to focus switch other tabs ...)". session-lead's seq 290 was stored and readable; his open thread showed it only
 * after a reload. And from his phone (seq 313): "when I reopen a chat it starts from the whole top of the loaded
 * messages and not at last unread message". The rules, pure and tested here; the thread wires them
 * (composables/useThreadCatchUp.ts, views/pocket/PocketOurStateThread.vue).
 */
export type LiveState = 'live' | 'catching_up' | 'offline'

export interface SeqMsg { id: string; seq: number; [k: string]: any }

/** The marker's word: a catch-up in flight says so, else the socket's state. */
export function liveState(o: { connected: boolean; catching: boolean }): LiveState {
  if (o.catching) return 'catching_up'
  return o.connected ? 'live' : 'offline'
}

/**
 * Merge an answer into what the thread holds: by id (never twice), ordered by seq. `gap` is true when the answer
 * starts after the next seq the thread expects: messages were missed in between (more than a page arrived while
 * away), and only a full reload of the page can say what they were. V0652 (aa): a message the thread holds whose card
 * was updated in place since (a higher card_rev in the answer) takes the newer card (`updated` counts them); an older
 * or equal rev changes nothing.
 */
export function mergeBySeq(have: SeqMsg[], incoming: SeqMsg[]): { messages: SeqMsg[]; gap: boolean; added: number; updated: number } {
  const ids = new Set(have.map((m) => m.id))
  const fresh = (incoming || []).filter((m) => m && m.id && !ids.has(m.id))
  const newer = new Map((incoming || []).filter((m) => m && m.id && ids.has(m.id)).map((m) => [m.id, m]))
  let updated = 0
  const kept = have.map((m) => {
    const n = newer.get(m.id)
    if (!n || (Number(n.card_rev) || 0) <= (Number(m.card_rev) || 0)) return m
    updated++
    return { ...m, card: n.card, card_rev: Number(n.card_rev) || 0, card_updated_at: n.card_updated_at ?? null }
  })
  const top = have.reduce((s, m) => Math.max(s, Number(m.seq) || 0), 0)
  const low = fresh.reduce((s, m) => Math.min(s, Number(m.seq) || Infinity), Infinity)
  const gap = have.length > 0 && fresh.length > 0 && low > top + 1
  const messages = [...kept, ...fresh].sort((a, b) => (Number(a.seq) || 0) - (Number(b.seq) || 0))
  return { messages, gap, added: fresh.length, updated }
}

/**
 * Where the thread opens: the first message after what this person has read that someone else wrote, or -1 (open at
 * the end) when nothing new waits. Their own sends are read by definition.
 */
export function firstUnreadIndex(messages: SeqMsg[], lastReadSeq: number, isMine: (m: SeqMsg) => boolean): number {
  const floor = Number(lastReadSeq) || 0
  return messages.findIndex((m) => (Number(m.seq) || 0) > floor && !isMine(m))
}

/**
 * What the long-poll does after a failed call (session-lead's review of (ag), the sessions' room seq 381). A 401 or a
 * 403 ends it: the token died (it expired, or a sign-out elsewhere bumped it), signing in again is the app's, and a tab
 * left open must not send a refused call every few seconds all day (CrowdSec reads that as a password attack and bans
 * the address). A 429 or a 503 waits as long as its Retry-After says. Anything else backs off 5, 10, 20, 40 and then
 * 60 s, each within 20% either way so many tabs do not call in step. `random` is injectable for the tests.
 */
export const POLL_BACKOFF_MS = [5000, 10000, 20000, 40000, 60000]
export function pollRetry(err: { status?: number; retryAfterS?: number } | null | undefined, attempt: number,
                          random: () => number = Math.random): { stop: true } | { stop: false; delayMs: number } {
  const status = Number(err?.status) || 0
  if (status === 401 || status === 403) return { stop: true }
  const ra = Number(err?.retryAfterS)
  if ((status === 429 || status === 503) && Number.isFinite(ra) && ra > 0) {
    return { stop: false, delayMs: Math.min(Math.max(ra * 1000, 1000), 300000) }
  }
  const base = POLL_BACKOFF_MS[Math.min(Math.max(0, attempt), POLL_BACKOFF_MS.length - 1)]
  return { stop: false, delayMs: Math.round(base * (0.8 + 0.4 * random())) }
}

/** Why a catch-up is due now, or null: the tab came back, the window got focus, the socket came back. */
export type CatchUpCause = 'visible' | 'focus' | 'reconnect'
export function catchUpCause(ev: { type: string; visibilityState?: string }): CatchUpCause | null {
  if (ev.type === 'visibilitychange') return ev.visibilityState === 'visible' ? 'visible' : null
  if (ev.type === 'focus') return 'focus'
  if (ev.type === 'reconnected') return 'reconnect'
  return null
}
