/**
 * Overlays a REAL account can meet in the middle of a lifecycle, and the suite's guard against them (V0666, session-lead room seq 4954 item 4).
 *
 * The contributor track's unlock celebration (V0665, components/contributor/UnlockCelebration.vue) opens once, over the whole page, the first
 * time a signed-in person has an unlock this device has not shown. A lifecycle on an account that holds unlocks (his Sandbox Beta Admin
 * account holds 44) met it in the middle of V0665's sandbox pass and every click behind it was blocked. It is a real overlay a real person
 * dismisses with Close; the suite does the same, so an unlock can never block a proof.
 *
 * HOW: a self-contained script injected into every page (addInitScript). A MutationObserver presses the celebration's own Close button the moment
 * the overlay is in the DOM, so it works whatever the lifecycle is doing (a click, an assertion, a plain read: Playwright's locator handlers
 * only run at an action). Pressing Close is the product's own path: it remembers what it showed (the device's seen set) and does not open the track.
 *
 * NEVER SILENT: each dismissal calls the page binding (`__suiteOverlayDismissed`), which the fixture turns into a test annotation and a word in
 * the run's page-clean row ("1 overlay dismissed (unlock-celebration)"), so a run that hit one says so.
 *
 * OPT-OUT: a lifecycle ABOUT the celebration puts OPT_OUT_TAG in its title and meets the overlay like a person does (as `@first-visit` does for
 * the banner and the tour).
 *
 * The script is a plain function with no imports so Playwright can serialize it; src/components/contributor/UnlockCelebration.suiteGuard.test.ts
 * runs it against the real component.
 */
import type { BrowserContext } from '@playwright/test'

export const BINDING = '__suiteOverlayDismissed'
export const OPT_OUT_TAG = '@unlock-celebration'

/**
 * Runs IN THE PAGE (serialized by addInitScript): closes the unlock celebration whenever it is present, and reports it through the binding.
 * Returns a function that stops it (for the unit test; the page never calls it).
 */
export function overlayGuardScript(binding: string): () => void {
  const tick = () => {
    const overlay = document.querySelector('[data-testid="unlock-celebration"]')
    if (!overlay) return
    const close = overlay.querySelector('[data-testid="unlock-close"]') as HTMLElement | null
    if (!close) return
    close.click()
    try { (window as any)[binding]?.('unlock-celebration') } catch { /* the report is best effort; the overlay is closed */ }
  }
  const observer = new MutationObserver(tick)
  observer.observe(document, { childList: true, subtree: true })
  tick()
  return () => observer.disconnect()
}

/** Install the guard in a context (every page of it, every navigation): `onDismiss` is told what was closed, once per dismissal. */
export async function guardOverlays(context: BrowserContext, onDismiss: (what: string) => void): Promise<void> {
  await context.exposeBinding(BINDING, (_source, what: unknown) => { onDismiss(String(what)) })
  await context.addInitScript(overlayGuardScript, BINDING)
}

/** The words a run's record carries for what the guard closed ('' when it closed nothing). */
export function overlayNote(dismissed: string[]): string {
  if (!dismissed.length) return ''
  const counts = new Map<string, number>()
  for (const d of dismissed) counts.set(d, (counts.get(d) || 0) + 1)
  const what = [...counts].map(([k, n]) => (n > 1 ? `${k} x${n}` : k)).join(', ')
  return `, ${dismissed.length} overlay${dismissed.length > 1 ? 's' : ''} dismissed (${what})`
}
