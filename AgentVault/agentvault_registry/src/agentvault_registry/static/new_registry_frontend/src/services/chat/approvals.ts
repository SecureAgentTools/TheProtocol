/**
 * V0650 (l) — approvals in the chat: the pure rules the pinned panel follows (no Vue, no fetch).
 *
 * The server decides (POST /chat/conversations/{id}/approvals/decide decides only requests that are pending and
 * unexpired, and says why every other id was skipped); these rules only decide what the panel SHOWS and what
 * "Approve all" sends: exactly the requests on screen that have not expired by the time the button is pressed.
 */

export interface ApprovalItem {
  id: string
  conversation_id: string
  status: 'pending' | 'approved' | 'denied' | 'expired' | string
  title: string
  reason?: string | null
  unlocks?: string | null
  artifact_sha256?: string | null
  artifact_label?: string | null
  production_impact?: boolean
  requester?: { agent_did?: string; name?: string } | null
  created_at?: string | null
  expires_at?: string | null
  request_message_id?: string | null
}

function ms(iso: string | null | undefined): number | null {
  if (!iso) return null
  const v = Date.parse(iso)
  return Number.isFinite(v) ? v : null
}

/** Whole seconds until the request expires (0 once it has; a request with no expiry never counts down). */
export function secondsLeft(item: ApprovalItem, nowMs: number): number {
  const ex = ms(item.expires_at)
  if (ex === null) return Number.POSITIVE_INFINITY
  return Math.max(0, Math.floor((ex - nowMs) / 1000))
}

/** Expired = the server said so, or its expiry passed on this screen's clock (a button never outlives its request). */
export function isExpired(item: ApprovalItem, nowMs: number): boolean {
  return item.status === 'expired' || secondsLeft(item, nowMs) <= 0
}

/** What the panel lists: the pending requests, oldest first. An expired one stays listed (inert, "expired") until
 *  the next read drops it, so a request never vanishes under a pointer that is about to press it. */
export function pendingShown(items: ApprovalItem[], nowMs: number): ApprovalItem[] {
  void nowMs
  return items
    .filter((i) => i.status === 'pending' || i.status === 'expired')
    .slice()
    .sort((a, b) => (ms(a.created_at) ?? 0) - (ms(b.created_at) ?? 0))
}

/** The ids "Approve all" sends: the shown requests that are still pending and unexpired NOW. */
export function approveAllIds(items: ApprovalItem[], nowMs: number): string[] {
  return pendingShown(items, nowMs).filter((i) => i.status === 'pending' && !isExpired(i, nowMs)).map((i) => i.id)
}

/** "1 h 05 min", "4 min 10 s", "45 s": the countdown's parts (the component words them through i18n). */
export function leftParts(seconds: number): { h: number; m: number; s: number } {
  const t = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0))
  return { h: Math.floor(t / 3600), m: Math.floor((t % 3600) / 60), s: t % 60 }
}

/** The first 12 hex of an artifact's sha256 (the whole value goes in the title attribute). */
export function shortSha(sha: string | null | undefined): string {
  const v = String(sha || '')
  return v.length > 12 ? `${v.slice(0, 12)}…` : v
}

/** The last 6 characters of a DID: agent names are not unique, the DID is the address (OurChat law). */
export function didTail(did: string | null | undefined): string {
  const v = String(did || '')
  return v.length > 6 ? `…${v.slice(-6)}` : v
}

/** The live status of each request card in a thread: a later `approval.decided` card names the decision; otherwise a
 *  request past its expiry reads expired, and anything else pending. Read from the thread itself, no extra request. */
export function liveApprovalStatus(messages: Array<{ kind?: string; card?: any }>, nowMs: number): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of messages) {
    const c = m?.kind === 'card' ? m.card : null
    if (!c || c.v !== 1) continue
    const id = String(c.data?.approval_id || '')
    if (!id) continue
    if (c.type === 'approval.decided') out[id] = c.data?.decision === 'approved' ? 'approved' : 'denied'
    else if (c.type === 'approval.request' && !(id in out)) {
      const ex = ms(c.data?.expires_at)
      out[id] = ex !== null && ex <= nowMs ? 'expired' : 'pending'
    }
  }
  return out
}

/** Is this message one the panel must hear about (a request posted, or one decided)? */
export function touchesApprovals(m: { kind?: string; card?: any } | null | undefined): boolean {
  const t = m?.kind === 'card' ? m?.card?.type : null
  return t === 'approval.request' || t === 'approval.decided'
}
