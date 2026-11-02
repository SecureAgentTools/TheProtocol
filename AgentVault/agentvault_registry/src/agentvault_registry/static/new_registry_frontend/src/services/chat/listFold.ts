/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc): the conversation list beside an open thread folds away, pure.
 *
 * The maintainer (the sessions' room, seq 686): the chat list on the console's OurChat "is not collapsable", and the
 * arrow over the chat "just leave[s] the chat and says pick a conversation ... on a basically empty side. i dont like
 * this. i want it refined and the sidebar collapsable". With two panes (the shell's wide layout: the console's #/ourchat
 * and Pocket wide) the list folds to a narrow rail that keeps the unread count and the way back, the choice kept per
 * person on this device, and the thread header's arrow folds and opens the list instead of leaving the thread. With one
 * pane (a phone) the arrow leaves the thread for the list, as before. While no thread is open the list always shows:
 * there is nothing else to show, and "pick a conversation" is only ever the pane beside it.
 */
import type { ComputedRef, InjectionKey, Ref } from 'vue'

/** The rail's width when the list is folded. */
export const LIST_RAIL_PX = 56

const KEY = (viewer: string) => `ourchat.list.v1.${viewer || 'anon'}`

/** Whether this person folded the list on this device (open until they fold it). V0654 (session-lead, the sessions' room
 *  seq 943): read only for a KNOWN viewer. Read under 'anon' while the viewer was still loading, someone else's choice on
 *  this device could fold the list at the open and the viewer's own unfold it a moment later, after the thread had
 *  scrolled to its NEW line: the pane changes width under it. With no viewer the list is open, and nothing is read. */
export function listFolded(viewer: string): boolean {
  if (!viewer) return false
  try { return localStorage.getItem(KEY(viewer)) === 'folded' } catch { return false }
}

/** Keeps this person's choice; with no viewer known yet it keeps nothing (the choice lasts this visit). */
export function saveListFolded(viewer: string, folded: boolean): void {
  if (!viewer) return
  try {
    if (folded) localStorage.setItem(KEY(viewer), 'folded')
    else localStorage.removeItem(KEY(viewer))
  } catch { /* storage full or blocked: the choice lasts this visit */ }
}

/** The rail stands in for the list: two panes, the list folded, and a thread open beside it. */
export function listAsRail(twoPane: boolean, folded: boolean, threadOpen: boolean): boolean {
  return twoPane && folded && threadOpen
}

export type HeaderArrow = 'fold-list' | 'open-list' | 'leave'

/** What the thread header's arrow does: with two panes it folds or opens the list, with one it leaves the thread. */
export function headerArrow(twoPane: boolean, folded: boolean): HeaderArrow {
  if (!twoPane) return 'leave'
  return folded ? 'open-list' : 'fold-list'
}

/** What the shell hands the list and the thread (provide/inject): one state, three controls (the list's header, the
 *  rail and the thread's arrow). */
export interface OurChatListFold {
  /** two panes side by side (the shell's wide layout) */
  twoPane: ComputedRef<boolean> | Ref<boolean>
  /** this person's choice */
  folded: Ref<boolean>
  /** the list may fold now: two panes and a thread open */
  canFold: ComputedRef<boolean> | Ref<boolean>
  toggle: () => void
  /** the list's unread count for the rail (null until the list has read its threads) */
  setUnread: (n: number | null) => void
}

export const OURCHAT_LIST_FOLD: InjectionKey<OurChatListFold> = Symbol('ourchat.listFold')
