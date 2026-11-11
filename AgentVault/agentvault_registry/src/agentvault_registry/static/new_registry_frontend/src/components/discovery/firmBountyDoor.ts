/**
 * V0658 (v), item 3 (the maintainer's review, sessions' room seq 2181): where "Post a bounty to this firm" goes.
 *
 * The door stays in the shell it is pressed in (services/uiMode.ts resolveDoor, session-lead's decision, the
 * sessions' room seq 2389): in the desktop console's Agent Discovery it opens the Guild board's post form, in Pocket
 * Pocket's post sheet, whatever is saved and however wide the window. Only on the public Explore page, where no shell
 * is mounted, does the landing decision pick (a saved choice first, else the width), the rule the quick-create modal's
 * doors follow. Both carry the firm (`for_org`), and both forms reserve the bounty for that organization's agents, so
 * the door never turns a firm bounty into an open one.
 */
import { resolveDoor, UI_MODE_KEY, type UiShell } from '@/services/uiMode'

export interface FirmRef { org_id: string; name: string }
export interface FirmBountyDoor { path: '/guild' | '/pocket/payments'; query: { post: '1'; for_org: string; title: string } }

/** The door for a firm, given what is saved, the viewport's width and the shell the press is in (unnamed: the shell
 *  of the route on screen, as resolveDoor reads it). */
export function resolveFirmBountyDoor(firm: FirmRef, saved: string | null, viewportWidth: number, shell?: UiShell): FirmBountyDoor {
  const query = { post: '1' as const, for_org: String(firm.org_id), title: `For ${firm.name}: ` }
  return { path: resolveDoor('guild', saved, viewportWidth, shell) as FirmBountyDoor['path'], query }
}

/** The browser binding: the saved choice in this browser and the window's width (the shell: the route on screen). */
export function firmBountyDoor(firm: FirmRef): FirmBountyDoor {
  let saved: string | null = null
  try { saved = localStorage.getItem(UI_MODE_KEY) } catch { saved = null }
  return resolveFirmBountyDoor(firm, saved, typeof window !== 'undefined' ? window.innerWidth : 1280)
}
