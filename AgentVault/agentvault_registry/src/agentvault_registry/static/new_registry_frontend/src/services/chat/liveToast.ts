/**
 * V0653 (ak) (order gwo_8c69cc0fd1f3033a35f47969; the design's defect 14, DESIGN_2026-11-01_OURCHAT_SETTINGS.md § 4):
 * the "Connected" toast does not show on a chat route. The thread's own live mark says it (V0652 (ag): filled, half or
 * hollow, with a word), and on a phone the toast covered the chat's header and its settings (session-lead, the
 * sessions' room seq 685, seen in (aa)'s 393 px screen). Every other page keeps the toast as it was.
 */

/** The console's OurChat (/ourchat) and Pocket's (/pocket/ourchat, and its permanent alias /pocket/ourstate). */
export function isChatPath(path: string): boolean {
  return /^\/(?:pocket\/)?(?:ourchat|ourstate)(?:[/?#]|$)/.test(String(path || ''))
}

/** The route path the console's hash router is on (it routes by hash: /ui#/ourchat/<id>). */
export function hashPath(hash: string): string {
  return String(hash || '').replace(/^#/, '') || '/'
}

/** Whether the socket's "Connected" toast shows on the page this hash names. */
export function connectedToastWanted(hash: string): boolean {
  return !isChatPath(hashPath(hash))
}
