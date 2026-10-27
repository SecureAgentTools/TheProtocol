/**
 * A chunk the console cannot load: the answer the router gives a view's stale chunk after a deploy, here so the error
 * boundary gives a component's the same one (§FESUITE 2026-10-10: the quick-create sheet's failed import kept the
 * boundary's panel, "Failed to fetch dynamically imported module", until the person reloaded; the router had always
 * reloaded for a view's). Moved from router/index.ts unchanged, with the decision as one function.
 */
// Stale-chunk failures after a deploy.
// When the SPA already in memory references a chunk hash that no longer
// exists on the server (because a fresh build replaced it), the dynamic
// import throws. Browsers each throw differently, so we match broadly.
//   Chrome:  "Failed to fetch dynamically imported module: <url>"
//   Firefox: 'Loading module from "<url>" was blocked because of a
//            disallowed MIME type ("text/html").'
//            or "error loading dynamically imported module"
//   Safari:  "Importing a module script failed."
//   Webpack-style fallback: "Loading chunk N failed"
export const STALE_CHUNK_PATTERNS = [
  /Failed to fetch dynamically imported module/i,
  /Loading (chunk|module) .*? failed/i,
  /error loading dynamically imported module/i,
  /Importing a module script failed/i,
  /disallowed MIME type/i,
]
export const RELOAD_GUARD_KEY = 'cc_chunk_reload_n'
export const RELOAD_GUARD_MAX = 2   // clear-cache + reload at most twice, then show a manual prompt

// Drop the service-worker's CacheFirst '/assets/' store (cacheName 'tp-assets', see
// vite.config.ts) so the reload re-fetches the CURRENT content-hashed chunks. Without
// this, a returning client whose SW cached a now-deleted chunk hash 404s the dynamic
// import on every navigation and the route renders blank — the "blank page that
// resurfaces after every deploy" failure. (Push subscriptions live in PushManager, not
// the Cache API, so clearing caches does NOT disturb web-push.)
export async function clearAppCaches(): Promise<void> {
  try {
    if (typeof caches !== 'undefined') {
      const keys = await caches.keys()
      await Promise.all(keys.map(k => caches.delete(k)))
    }
  } catch { /* Cache API unavailable — proceed to reload anyway */ }
}

// Absolute last resort: a visible, always-on-top "new version — reload" bar so a stale
// bundle can NEVER leave the user staring at a blank screen. Injected via raw DOM so it
// works even when the Vue app itself failed to mount the route.
export function showUpdateBanner(): void {
  try {
    if (document.getElementById('cc-update-banner')) return
    const bar = document.createElement('div')
    bar.id = 'cc-update-banner'
    bar.setAttribute('role', 'alert')
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;display:flex;gap:14px;align-items:center;justify-content:center;padding:14px 18px;background:#0b1220;color:#e2e8f0;border-top:2px solid #06b6d4;font:600 14px/1.4 system-ui,-apple-system,sans-serif'
    const span = document.createElement('span')
    span.textContent = 'A new version of the app is available.'
    const btn = document.createElement('button')
    btn.textContent = 'Reload'
    btn.style.cssText = 'padding:8px 18px;background:#06b6d4;color:#001018;border:0;border-radius:6px;font-weight:800;letter-spacing:.02em;cursor:pointer'
    btn.onclick = async () => { await clearAppCaches(); try { sessionStorage.removeItem(RELOAD_GUARD_KEY) } catch { /* ignore */ } ; window.location.reload() }
    bar.appendChild(span); bar.appendChild(btn)
    document.body.appendChild(bar)
  } catch { /* DOM unavailable — fall back to a plain reload */ window.location.reload() }
}

/** Whether an error is a chunk that could not be loaded (any browser's words for it). */
export function isStaleChunkError(err: unknown): boolean {
  const msg = (err as { message?: string } | null)?.message || String(err ?? '')
  return STALE_CHUNK_PATTERNS.some((re) => re.test(msg))
}

/** Clear the asset cache and reload for a fresh bundle, at most RELOAD_GUARD_MAX times in a row this session; after that
 *  the visible reload banner, never a blank screen. Says which it did. */
export function recoverFromStaleChunk(log?: { warn: (...args: unknown[]) => void }): 'reloading' | 'banner' {
  let n = 0
  try { n = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) || 0) } catch { /* ignore */ }
  if (n >= RELOAD_GUARD_MAX) {
    // Two cache-clears + reloads did not resolve it — surface a visible reload prompt
    // instead of a blank route. Never leave the user on a blank screen.
    log?.warn('Stale-chunk auto-recovery exhausted; showing manual reload banner')
    showUpdateBanner()
    return 'banner'
  }
  try { sessionStorage.setItem(RELOAD_GUARD_KEY, String(n + 1)) } catch { /* ignore */ }
  log?.warn('Stale chunk detected — clearing asset cache and hard-reloading for a fresh bundle')
  clearAppCaches().finally(() => window.location.reload())
  return 'reloading'
}

/** A clean navigation: the fresh bundle loaded, so a later deploy gets its full retry budget. */
export function staleChunkRecovered(): void {
  try { sessionStorage.removeItem(RELOAD_GUARD_KEY) } catch { /* ignore */ }
}
