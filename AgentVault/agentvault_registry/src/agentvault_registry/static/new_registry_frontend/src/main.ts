// §POCKETBRIDGE4 WS-H — must run BEFORE the router import: createWebHashHistory
// rewrites a hashless URL to #/ at module-eval time, eating the share query.
import './bootShareTarget'
// §POCKETI18N B — same rule: consume ?lang= before router/i18n evaluate.
import './bootLocale'
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n, { bootstrapI18n } from './i18n'
import { setupErrorHandler } from './utils/errorHandler'

// Import test credentials helper for development
import './services/testAgentCredentials'
// Import agent credentials store and its initializer
import { initializeTestCredentials } from './services/agentCredentialsStore'

// Import global styles
import './assets/styles/main.css'
import './assets/styles/neural-command.css'
import './assets/styles/showcase.css'
// import './assets/styles/theme.css' // Replaced by neural-command.css

// Apply saved brand theme BEFORE Vue mounts to avoid flash-of-wrong-theme.
// Pinia's initializeBrandTheme() re-applies this idempotently on app start.
//
// 'custom' is special: we inject inline CSS variables derived from the user's
// saved primary hex. The math is duplicated (lightweight) here so we don't
// pull in the whole ui store before mount.
;(() => {
  const safeHex = (h: string | null) => h && /^#[0-9a-fA-F]{6}$/.test(h) ? h.toUpperCase() : null
  const parseRgb = (h: string): [number, number, number] => [
    parseInt(h.slice(1, 3), 16),
    parseInt(h.slice(3, 5), 16),
    parseInt(h.slice(5, 7), 16),
  ]
  const hexToHsl = (h: string): [number, number, number] => {
    const [r0, g0, b0] = parseRgb(h)
    const r = r0 / 255, g = g0 / 255, b = b0 / 255
    const max = Math.max(r, g, b), min = Math.min(r, g, b)
    const l = (max + min) / 2
    if (max === min) return [0, 0, l * 100]
    const d = max - min
    const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    let hh = 0
    if (max === r) hh = (g - b) / d + (g < b ? 6 : 0)
    else if (max === g) hh = (b - r) / d + 2
    else hh = (r - g) / d + 4
    return [(hh / 6) * 360, s * 100, l * 100]
  }
  const hslToHex = (h: number, s: number, l: number) => {
    s /= 100; l /= 100
    const k = (n: number) => (n + h / 30) % 12
    const a = s * Math.min(l, 1 - l)
    const f = (n: number) => 255 * (l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))))
    const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0').toUpperCase()
    return '#' + c(f(0)) + c(f(8)) + c(f(4))
  }
  try {
    // §FEFRAME W2: a theme the person CHOSE wins; otherwise the frame's own (the server renders it into
    // <meta name="tp-frame-theme">), so ASIA opens sovereign with no flash. The old code saved `neural` for every
    // visitor as if chosen; a saved value without the chosen marker is that default, not a choice.
    const chosen = localStorage.getItem('theprotocol:brandThemeChosen') === '1'
    const frameTheme = document.querySelector('meta[name="tp-frame-theme"]')?.getAttribute('content') || ''
    const saved = (chosen && localStorage.getItem('brandTheme'))
      || (frameTheme === 'sovereign' || frameTheme === 'neural' ? frameTheme : 'neural')
    const customHex = safeHex(localStorage.getItem('theprotocol:customTheme'))
    if (saved === 'custom' && customHex) {
      const [hh, ss, ll] = hexToHsl(customHex)
      const bright = hslToHex(hh, ss, Math.min(ll + 8, 72))
      const dim    = hslToHex(hh, ss, Math.max(ll - 12, 22))
      const dark   = hslToHex(hh, ss, Math.max(ll - 30, 10))
      const rgbStr = (h: string) => parseRgb(h).join(', ')
      const body = document.body
      body.classList.add('theme-custom')
      body.style.setProperty('--nc-primary',           customHex)
      body.style.setProperty('--nc-primary-rgb',       rgbStr(customHex))
      body.style.setProperty('--nc-primary-bright',    bright)
      body.style.setProperty('--nc-primary-bright-rgb', rgbStr(bright))
      body.style.setProperty('--nc-primary-dim',       dim)
      body.style.setProperty('--nc-primary-dim-rgb',   rgbStr(dim))
      body.style.setProperty('--nc-primary-dark',      dark)
      body.style.setProperty('--nc-primary-dark-rgb',  rgbStr(dark))
      body.style.setProperty('--nc-primary-glow',      `rgba(${rgbStr(customHex)}, 0.4)`)
      body.style.setProperty('--nc-primary-subtle',    `rgba(${rgbStr(customHex)}, 0.1)`)
    } else {
      const valid = saved === 'neural' || saved === 'sovereign'
      document.body.classList.add(`theme-${valid ? saved : 'neural'}`)
    }
  } catch { document.body.classList.add('theme-neural') }
})()

// Create Vue app
// (§POCKETBRIDGE4 share-target shim moved to bootShareTarget.ts — it must run
// before the router IMPORT, and imports hoist above any statement here.)
const app = createApp(App)

// Register global components
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import NeuralCard from '@/components/ui/NeuralCard.vue'
app.component('NeuralIcon', NeuralIcon)
app.component('NeuralCard', NeuralCard)

// Add Pinia state management
app.use(createPinia())

// Add Vue Router
app.use(router)

// Add i18n
app.use(i18n)

// Set up global error handling
setupErrorHandler(app)

// Ensure the initial (saved/browser) locale's messages + dayjs locale are loaded
// BEFORE mount so non-English users don't flash English on first paint. English
// is bundled; other locales lazy-load. Mount regardless on failure (en fallback).
bootstrapI18n().catch(() => { /* fall back to en */ }).then(() => {
  // Mount app
  app.mount('#app')

  // After app is mounted, initialize test credentials (avoids circular dependency)
  if (import.meta.env.DEV || window.location.hostname === 'localhost') {
    // Direct execution with error handling - avoids minification issues
    try {
      initializeTestCredentials()
    } catch (error) {
      console.warn('Failed to initialize test credentials:', error)
      // Non-critical, continue anyway
    }

    // Expose for testing/debugging
    ;(window as any).__VUE_APP__ = app
    import.meta.env.DEV && console.log('Vue app exposed for testing at window.__VUE_APP__')
  }
})
