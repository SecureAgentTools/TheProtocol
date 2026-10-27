/**
 * services/uiMode.ts — §POCKETBRIDGE #PK23 (D2, ratified 2026-08-22).
 *
 * WHERE A SIGNED-IN USER LANDS. Until this module, `tp_ui_mode` was written in
 * three places and read in NONE (F3) — the public docs claimed phones open in
 * Pocket mode while every phone browser login landed on the WebGL desktop
 * bridge (F4/F8). This is the single reader, and the rule is the LITEBRIDGE
 * rule verbatim: a saved MANUAL choice always beats the heuristic; the
 * heuristic acts only on a fact (viewport width), and acting on it never
 * records a choice the user did not make.
 */

export const UI_MODE_KEY = 'tp_ui_mode'
/** Below this width the shell heuristic says "phone" (useViewport's BP.md). */
export const PHONE_MAX_WIDTH = 768

export type UiMode = 'pocket' | 'advanced'

/**
 * Pure resolver — the whole decision, testable without a browser.
 * `saved` is whatever localStorage holds (unknown strings are ignored, not
 * guessed at); `viewportWidth` is the fact the heuristic may act on.
 */
export function resolveHomeRoute(saved: string | null, viewportWidth: number): '/pocket/home' | '/mission-control' {
  if (saved === 'pocket') return '/pocket/home'
  if (saved === 'advanced') return '/mission-control'
  return viewportWidth < PHONE_MAX_WIDTH ? '/pocket/home' : '/mission-control'
}

/** The browser binding used by the router and the login view. */
export function homeRoute(): '/pocket/home' | '/mission-control' {
  let saved: string | null = null
  try { saved = localStorage.getItem(UI_MODE_KEY) } catch { saved = null }
  const width = typeof window !== 'undefined' ? window.innerWidth : 1280
  return resolveHomeRoute(saved, width)
}

/** Record a DELIBERATE choice (a tapped control, never an automatic redirect
 *  and never a mere navigation — §POCKETBRIDGE2 P0.2: a visit is not a choice). */
export function rememberUiMode(mode: UiMode): void {
  try { localStorage.setItem(UI_MODE_KEY, mode) } catch { /* storage unavailable */ }
}

/** What is currently saved, or null when the heuristic decides. */
export function savedUiMode(): UiMode | null {
  try {
    const v = localStorage.getItem(UI_MODE_KEY)
    return v === 'pocket' || v === 'advanced' ? v : null
  } catch { return null }
}

/** Drop the saved choice — back to the heuristic (phone=Pocket, desktop=bridge). */
export function clearUiMode(): void {
  try { localStorage.removeItem(UI_MODE_KEY) } catch { /* storage unavailable */ }
}

/**
 * §PHONESTART (2026-09-02) — the DOORS a first-run surface points at obey the SAME rule
 * as the landing: a phone (or a saved Pocket choice) is sent to Pocket's own surfaces,
 * never to a desktop view it cannot use. Measured before this: the quick-create modal's
 * "Request {ccy}" and "My Agents" links pointed every phone at `/my-agents`, a
 * DashboardLayout view the Pocket shell never renders.
 */
export type DoorKind = 'funding' | 'agents'
export function resolveDoor(kind: DoorKind, saved: string | null, viewportWidth: number): string {
  const pocket = resolveHomeRoute(saved, viewportWidth) === '/pocket/home'
  if (kind === 'funding') return pocket ? '/pocket/home?fund=1' : '/my-agents?fund=1'
  return pocket ? '/pocket/agents' : '/my-agents'
}
function _door(kind: DoorKind): string {
  let saved: string | null = null
  try { saved = localStorage.getItem(UI_MODE_KEY) } catch { saved = null }
  return resolveDoor(kind, saved, typeof window !== 'undefined' ? window.innerWidth : 1280)
}
/** Where "fund this agent" goes: Pocket home's REQUEST action, or My Agents' request modal. */
export function fundingDoor(): string { return _door('funding') }
/** Where "my agents" goes: Pocket's agents tab, or the desktop My Agents view. */
export function agentsDoor(): string { return _door('agents') }

/** §PHONEWORDS (2026-09-03) — the same decision the doors make (saved mode, else viewport width), so a
 *  sentence about "where things are" agrees with where the doors lead. */
export function isPocketMode(saved: UiMode | null = savedUiMode(), viewportWidth: number = typeof window !== 'undefined' ? window.innerWidth : 1024): boolean {
  return resolveHomeRoute(saved, viewportWidth) === '/pocket/home'
}

