/**
 * A URL change the router could not see yet, carried out once it can.
 *
 * vue-router starts listening to the address bar only when its FIRST navigation finalizes, and that navigation then
 * REPLACES the URL with its own target (vue-router 5.3.1: `setupListeners` runs in `markAsReady`, and
 * `finalizeNavigation` replaces on the first navigation). This console's first navigation waits for the frame manifest
 * and the session restore (2.5-2.9 s on a loaded sandbox), so a URL changed inside that window (Back or Forward, a typed
 * hash, any raw "#/..." link) was dropped and overwritten without a word. An admin opening an admin page right after a
 * load landed back on the page the console loaded, with no toast (§FESUITE, run fes-20261001T235648Z-aa14: the route
 * log held the hash change and then only the first navigation, "/ -> /mission-control").
 *
 * A router.push (every RouterLink) never needed this: the router sees it, and it cancels the first navigation.
 */
import type { Router } from 'vue-router'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('router')

/** Install once, before the router's first navigation can finish (where the router is created). */
export function replayLocationMissedBeforeReady(router: Router, win: Window = window): void {
  let missed: string | null = null
  const note = () => { missed = win.location.hash.replace(/^#/, '') || '/' }
  win.addEventListener('popstate', note)
  win.addEventListener('hashchange', note)
  void router.isReady().catch(() => undefined).finally(() => {
    win.removeEventListener('popstate', note)
    win.removeEventListener('hashchange', note)
    // the newest change wins, as it would have in a router that was listening; one the first navigation already
    // reached needs nothing
    if (missed !== null && missed !== router.currentRoute.value.fullPath) {
      log.info('carrying out an address-bar change made while the first navigation waited:', missed)
      void router.replace(missed).catch(() => undefined)
    }
  })
}
