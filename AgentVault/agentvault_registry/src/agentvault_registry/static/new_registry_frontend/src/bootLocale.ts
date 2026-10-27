/**
 * §POCKETI18N B — the ?lang= override, honored from ANYWHERE incl. /login.
 *
 * When auto-detection guesses wrong, the user is stuck reading a language
 * they may not read, hunting for a switcher labeled in it. A link can carry
 * the fix: `…/ui?lang=de` or `…/ui#/pocket/home?lang=de` switches the app
 * and records it as an EXPLICIT choice before a single word is read.
 *
 * MUST be imported before ./router AND ./i18n in main.ts:
 *  - createWebHashHistory rewrites a hashless URL to #/ at module-eval time
 *    and eats the search query (the §POCKETBRIDGE4 bootShareTarget lesson);
 *  - i18n/index.ts resolves its initial locale at import time, so the saved
 *    key has to be written before that module evaluates.
 *
 * The param is consumed (stripped from search AND hash query) either way; an
 * unsupported value changes nothing and still disappears.
 */
import { SUPPORTED_LOCALES } from './i18n/locales'

try {
  const url = new URL(window.location.href)
  const hash = url.hash || ''
  const hq = hash.includes('?') ? new URLSearchParams(hash.slice(hash.indexOf('?') + 1)) : null
  const raw = url.searchParams.get('lang') || hq?.get('lang') || null
  if (raw !== null) {
    const lang = raw.toLowerCase().split('-')[0]
    if (lang in SUPPORTED_LOCALES) {
      try { localStorage.setItem('locale', lang) } catch { /* boots with detection */ }
    }
    url.searchParams.delete('lang')
    if (hq) {
      hq.delete('lang')
      const base = hash.slice(0, hash.indexOf('?'))
      url.hash = hq.toString() ? `${base}?${hq.toString()}` : base
    }
    history.replaceState(history.state, '', url.toString())
  }
} catch { /* no URL/history (tests): detection carries the boot */ }

export {}
