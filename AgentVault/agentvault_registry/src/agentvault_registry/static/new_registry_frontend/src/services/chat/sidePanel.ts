/**
 * V0652 (ad) (order gwo_e5e9ad061d6e5be9605a3067): an organization room's side panel on a wide screen, pure. It shows
 * on the console's chat (the /ourchat mount; Pocket keeps its own layout) in an organization's room, once the thread
 * pane is wide enough for the panel AND a column no narrower than V0651's (760 px): the width is measured from the pane
 * itself, never guessed from the window, because the console's sidebar and the conversation list take their own share.
 * Each section's fold is kept per person on this device.
 */
export type SideSection = 'approvals' | 'board' | 'live' | 'present'
export const SIDE_SECTIONS: readonly SideSection[] = ['approvals', 'board', 'live', 'present']

/** V0651's message column: the panel never makes the column narrower than it was. */
export const COLUMN_KEEP_PX = 760
/** The panel's own width, and the space between the column and the panel. */
export const SIDE_PANEL_PX = 300
export const SIDE_GUTTER_PX = 24
/** The thread pane's width from which the side panel shows. */
export const SIDE_PANEL_MIN_PX = COLUMN_KEEP_PX + SIDE_PANEL_PX + SIDE_GUTTER_PX

export type ChatSurface = 'desk' | 'pocket'
/** Which mount the thread is on: the console's /ourchat, or Pocket's /pocket/ourchat (same rule as useOurChatBase). */
export function chatSurfaceFor(base: string): ChatSurface {
  return String(base || '').startsWith('/pocket') ? 'pocket' : 'desk'
}

export function showSidePanel(paneWidth: number, kind: string | null | undefined, orgId: string | null | undefined,
                              surface: ChatSurface): boolean {
  return surface === 'desk' && kind === 'org' && !!orgId && Number(paneWidth) >= SIDE_PANEL_MIN_PX
}

/** V0652 (aj): under this width (a phone) the composer's speaker chip drops its "as" and tightens, so the message field
 *  keeps room for its one-line placeholder (at 393 px the chip took 85 px and the placeholder wrapped). */
export const NARROW_PANE_PX = 480
/** A pane measured (0 = not yet) and narrower than NARROW_PANE_PX. */
export function narrowPane(paneWidth: number): boolean {
  const w = Number(paneWidth) || 0
  return w > 0 && w < NARROW_PANE_PX
}

const KEY = (viewer: string) => `ourchat.side.v1.${viewer || 'anon'}`

/** The sections' fold state for this person: every section open until they fold it. */
export function sidePanelOpen(viewer: string): Record<SideSection, boolean> {
  const out = Object.fromEntries(SIDE_SECTIONS.map((s) => [s, true])) as Record<SideSection, boolean>
  try {
    const raw = JSON.parse(localStorage.getItem(KEY(viewer)) || 'null')
    if (raw && typeof raw === 'object') for (const s of SIDE_SECTIONS) out[s] = raw[s] !== false
  } catch { /* a value nobody can read is no state */ }
  return out
}

export function saveSidePanelOpen(viewer: string, state: Partial<Record<SideSection, boolean>>): void {
  const out: Record<string, boolean> = {}
  for (const s of SIDE_SECTIONS) out[s] = state[s] !== false
  try { localStorage.setItem(KEY(viewer), JSON.stringify(out)) } catch { /* full or blocked */ }
}
