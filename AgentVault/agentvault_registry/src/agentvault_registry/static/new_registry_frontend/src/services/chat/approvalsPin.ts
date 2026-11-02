/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc): the requests pinned above a room's history, compact, pure.
 *
 * The maintainer (the sessions' room, seq 686): on the console's OurChat a new approval "only appeared on the side bar
 * on the right ... this approval ask to the right of the chat small at the tp caught me off guard ... the pinned
 * version was way more clear to spot". So a request that waits is pinned above the history again at every width, as
 * V0650 (l) drew it but compact: one card (the title, what it unlocks, Approve, Deny, Why), and "n more" when several
 * wait, which opens the whole list (V0650's panel, with Approve all). On a phone-width pane it starts as the design's
 * one-line strip under the header, which opens the same card. The side panel's WAITING ON YOU keeps the count, and the
 * request's own card in the thread stays the record.
 */
import { isExpired, type ApprovalItem } from '@/services/chat/approvals'

/** strip: one line (a phone) · card: the one request · list: every request, with Approve all */
export type PinView = 'strip' | 'card' | 'list'

/** Where the pinned requests start: the one-line strip on a phone-width pane, the card at every other width. */
export function pinStart(narrow: boolean): PinView {
  return narrow ? 'strip' : 'card'
}

/** The request the card shows: the one a link opened (?approval=), else the NEWEST that can still be decided (the one
 *  that just arrived is the one a person looks for; the older ones are one tap away), else the newest shown (an
 *  expired one stays readable until it leaves). `shown` is in the list's order, oldest first (pendingShown). */
export function pinnedFirst(shown: ApprovalItem[], nowMs: number, focusId = ''): ApprovalItem | null {
  if (focusId) {
    const f = shown.find((a) => a.id === focusId)
    if (f) return f
  }
  const newestFirst = shown.slice().reverse()
  return newestFirst.find((a) => a.status === 'pending' && !isExpired(a, nowMs)) ?? newestFirst[0] ?? null
}

/** How many wait besides the one the card shows ("n more"). */
export function pinMore(shownCount: number): number {
  return Math.max(0, (Number(shownCount) || 0) - 1)
}
