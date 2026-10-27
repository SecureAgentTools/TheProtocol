/**
 * Whether a notice keyed `key` should be shown now: true the first time in this browser session, false after.
 *
 * A notice that repeats on every page load trains people to ignore notices: "Agent Credentials Missing" showed on
 * EVERY load for an account whose agents' credentials live elsewhere (every admin; every page of the console suite,
 * §FESUITE 2026-10-02). When storage is unavailable it answers yes: a notice shown twice beats one never shown.
 */
export function firstTimeThisSession(key: string, store: Storage | null = sessionStore()): boolean {
  if (!store) return true
  try {
    if (store.getItem(key) === '1') return false
    store.setItem(key, '1')
    return true
  } catch {
    return true
  }
}

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}
