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
 * V0658 (v): the shell a press happens in. A /pocket route renders in Pocket, a route inside DashboardLayout in the
 * desktop console; each shell's own route record says so (router/index.ts, meta.shell) and its children inherit it.
 * Anything else (the landing page, Explore, sign-in, the legal pages) renders in no shell.
 */
export type UiShell = 'pocket' | 'desktop' | 'none'

/** The shell a route renders in, as its shell's record declares it; an unknown value is ignored, never guessed at. */
export function shellOf(route: { meta?: { shell?: unknown } } | null | undefined): UiShell {
  const shell = route?.meta?.shell
  return shell === 'pocket' || shell === 'desktop' ? shell : 'none'
}

/** What a door reads of the app's router: the route on screen. */
export interface DoorRouter { currentRoute: { value: { meta?: { shell?: unknown } } } }
let doorRouter: DoorRouter | null = null

/** router/index.ts hands its router over once, when it creates it: a door then reads the route on screen at the
 *  press, and no caller passes it by hand. */
export function bindDoorRouter(router: DoorRouter | null): void { doorRouter = router }

/** The shell of the route on screen; none before a router is handed over (a unit test, a page before the router). */
export function currentShell(): UiShell { return shellOf(doorRouter?.currentRoute.value) }

/**
 * §PHONESTART (2026-09-02) — the DOORS a first-run surface points at obey the SAME rule
 * as the landing: a phone (or a saved Pocket choice) is sent to Pocket's own surfaces,
 * never to a desktop view it cannot use. Measured before this: the quick-create modal's
 * "Request {ccy}" and "My Agents" links pointed every phone at `/my-agents`, a
 * DashboardLayout view the Pocket shell never renders.
 *
 * V0658 (v) (session-lead's decision, the sessions' room seq 2389): A PRESS INSIDE A SHELL STAYS IN THAT SHELL. The
 * saved choice, else the width, decides where a person ARRIVES from outside (homeRoute: the root address, a login, a
 * notification, a mailed link) and never moves him out of the shell he is working in: in the desktop console with
 * Pocket saved, "Post a bounty to this firm" opened Pocket's Payments (his report). §PHONESTART's rule seen from the
 * other side, so it lives here: inside a shell the door follows that shell; where none is mounted (the public pages),
 * the saved choice, else the width. A caller that names no shell gets the shell of the route on screen (currentShell).
 */
export type DoorKind = 'funding' | 'agents' | 'guild' | 'pay'
export function resolveDoor(kind: DoorKind, saved: string | null, viewportWidth: number, shell: UiShell = currentShell()): string {
  const pocket = shell === 'pocket' || (shell !== 'desktop' && resolveHomeRoute(saved, viewportWidth) === '/pocket/home')
  if (kind === 'funding') return pocket ? '/pocket/home?fund=1' : '/my-agents?fund=1'
  // V0658 (v): the Guild, where a firm's bounty is posted: Pocket's Payments tab, or the desktop Guild board
  if (kind === 'guild') return pocket ? '/pocket/payments' : '/guild'
  // V0658 (v), seq 2419: where value is sent from an owned agent: Pocket's Pay, or the desktop Forex Desk
  if (kind === 'pay') return pocket ? '/pocket/pay' : '/forex'
  return pocket ? '/pocket/agents' : '/my-agents'
}
/**
 * V0658 (q): where one Guild order opens. The desktop chat's order card opened Pocket's order sheet (the maintainer's
 * report, sessions' room seq 2105): its door named /pocket/payments in every mode. Both surfaces open the order that
 * `?order=` names.
 */
export function resolveOrderDoor(orderId: string, saved: string | null, viewportWidth: number): string {
  return `${resolveDoor('guild', saved, viewportWidth)}?order=${encodeURIComponent(orderId)}`
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
/** Where a Guild order opens: Pocket's order sheet, or the order on the desktop Guild board (V0658 (q)). */
export function orderDoor(orderId: string): string {
  let saved: string | null = null
  try { saved = localStorage.getItem(UI_MODE_KEY) } catch { saved = null }
  return resolveOrderDoor(orderId, saved, typeof window !== 'undefined' ? window.innerWidth : 1280)
}
/** Where "send from an owned agent" goes: Pocket's Pay, or the desktop console's Forex Desk. */
export function payDoor(): string { return _door('pay') }

/** §PHONEWORDS (2026-09-03): the same decision the doors make, so a sentence about "where things are" agrees with
 *  where the doors lead. V0658 (v): the doors follow the shell the press is in first (then the saved mode, else the
 *  viewport width), so this asks resolveDoor itself. */
export function isPocketMode(saved: UiMode | null = savedUiMode(), viewportWidth: number = typeof window !== 'undefined' ? window.innerWidth : 1024, shell: UiShell = currentShell()): boolean {
  return resolveDoor('agents', saved, viewportWidth, shell) === '/pocket/agents'
}

