// V0664 (order gwo_874694de65551c5c1488641c): what a sender's own line says while the cross-frame relay limit holds it back.
//
// A message to a room another registry hosts goes to that host, which is the only writer of its seq. Its limit (per thread, per
// calling registry, tighter for an agent) answers 429; the line is never lost (the host takes a line once, whatever the retries, because
// the retry carries the SAME client_ref). The sender's line is shown here in one of three states until the host's own copy comes back:
//   waiting  the limit holds it: "sends in about N s", counting down, then the same send again
//   sent     the host took it: waiting for its copy to arrive (it replaces this line)
//   failed   given up (the last try, or a refusal that is not a limit): the host's words, and Send again
// Pure, so it is tested without a browser. The wait is the limit's own number (a 429's Retry-After, read by the chat client as
// retryAfterS); an older host that names none gets one fixed fallback, and a bad number is bounded.

export const MAX_HELD_TRIES = 4
export const FALLBACK_WAIT_S = 15
export const MAX_WAIT_S = 120

export type HoldState = 'waiting' | 'sent' | 'failed'

export interface PendingLine {
  clientRef: string
  body: string
  replyTo: string | null
  state: HoldState
  tries: number
  secondsLeft: number
  error?: string
}

export function newLine(o: { clientRef: string; body: string; replyTo?: string | null }): PendingLine {
  return { clientRef: o.clientRef, body: o.body, replyTo: o.replyTo ?? null, state: 'waiting', tries: 0, secondsLeft: 0 }
}

/** Seconds to wait: the limit's own number rounded up and bounded, else the fallback. */
export function waitSeconds(err: { retryAfterS?: number } | null | undefined): number {
  const n = Number(err?.retryAfterS)
  if (!Number.isFinite(n) || n <= 0) return FALLBACK_WAIT_S
  return Math.min(Math.ceil(n), MAX_WAIT_S)
}

/** The limit held the line (one more try spent): waiting again, or given up after the last. */
export function held(l: PendingLine, err: { retryAfterS?: number; detail?: string } | null | undefined): PendingLine {
  const tries = l.tries + 1
  if (tries >= MAX_HELD_TRIES) return { ...l, tries, state: 'failed', secondsLeft: 0, error: String(err?.detail || '') || undefined }
  return { ...l, tries, state: 'waiting', secondsLeft: waitSeconds(err), error: undefined }
}

export function tick(l: PendingLine): PendingLine {
  if (l.state !== 'waiting' || l.secondsLeft <= 0) return l
  return { ...l, secondsLeft: l.secondsLeft - 1 }
}

export function dueRetry(l: PendingLine): boolean {
  return l.state === 'waiting' && l.tries > 0 && l.secondsLeft <= 0
}

export function sentLine(l: PendingLine): PendingLine {
  return { ...l, state: 'sent', secondsLeft: 0, error: undefined }
}

export function failedLine(l: PendingLine, err: { detail?: string } | null | undefined): PendingLine {
  return { ...l, state: 'failed', secondsLeft: 0, error: String(err?.detail || '') || undefined }
}

/** Drop every line whose copy has arrived from the host (its client_ref is on a message of the thread). */
export function settle(lines: PendingLine[], messages: Array<{ client_ref?: string | null }>): PendingLine[] {
  if (!lines.length) return lines
  const seen = new Set(messages.map((m) => String(m?.client_ref || '')).filter(Boolean))
  const rest = lines.filter((l) => !seen.has(l.clientRef))
  return rest.length === lines.length ? lines : rest
}
