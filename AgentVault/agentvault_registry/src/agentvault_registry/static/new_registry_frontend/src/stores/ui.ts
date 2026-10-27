import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { Notification } from '@/components/common/NotificationSystem.vue'
import { wholeLedgerMessage } from '@/services/api/ledgerRefusal'

// Brand themes — the accent palette applied via body class.
// Built-ins ('neural', 'sovereign') match a `body.theme-X` block in
// neural-command.css. 'custom' is special: the user picks a primary hex,
// derived variants are written as inline CSS variables on body.style,
// overriding any CSS-class palette (inline style trumps stylesheet).
export type BrandTheme = 'neural' | 'sovereign' | 'custom'
export const BUILTIN_BRAND_THEMES: BrandTheme[] = ['neural', 'sovereign']
export const ALL_BRAND_THEMES: BrandTheme[] = ['neural', 'sovereign', 'custom']
const DEFAULT_BRAND_THEME: BrandTheme = 'neural'

// Backwards compat — kept for callers (none in production but type-stable).
export const AVAILABLE_BRAND_THEMES: BrandTheme[] = BUILTIN_BRAND_THEMES

const CUSTOM_THEME_KEY = 'theprotocol:customTheme'

// ── Custom-theme color math (no deps) ─────────────────────────────────────

/** Hex (#RRGGBB or RRGGBB) → [r,g,b] 0-255, or null if invalid. */
function parseHex(hex: string): [number, number, number] | null {
  const m = hex.trim().replace(/^#/, '')
  if (!/^[0-9a-fA-F]{6}$/.test(m)) return null
  return [
    parseInt(m.slice(0, 2), 16),
    parseInt(m.slice(2, 4), 16),
    parseInt(m.slice(4, 6), 16),
  ]
}

/** RGB 0-255 → '#RRGGBB' uppercase. */
function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0').toUpperCase()
  return '#' + c(r) + c(g) + c(b)
}

/** Hex → [h 0-360, s 0-100, l 0-100]. Caller guarantees valid hex. */
function hexToHsl(hex: string): [number, number, number] {
  const [r0, g0, b0] = parseHex(hex)!
  const r = r0 / 255, g = g0 / 255, b = b0 / 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l * 100]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h = 0
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0)
  else if (max === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return [(h / 6) * 360, s * 100, l * 100]
}

/** [h s l] → '#RRGGBB'. */
function hslToHex(h: number, s: number, l: number): string {
  const sN = Math.max(0, Math.min(100, s)) / 100
  const lN = Math.max(0, Math.min(100, l)) / 100
  const k = (n: number) => (n + h / 30) % 12
  const a = sN * Math.min(lN, 1 - lN)
  const f = (n: number) => 255 * (lN - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))))
  return rgbToHex(f(0), f(8), f(4))
}

interface CustomVariants {
  primary: string;       primaryRgb: string
  bright: string;        brightRgb: string
  dim: string;           dimRgb: string
  dark: string;          darkRgb: string
}

/** Derive the 4 brightness variants from a primary hex via HSL math.
 *  Mirrors the relationships used in neural-command.css's built-in themes:
 *  bright = +8L, dim = -12L, dark = -30L; lightness clamped to safe ranges. */
function deriveVariants(primaryHex: string): CustomVariants | null {
  const rgb = parseHex(primaryHex)
  if (!rgb) return null
  const [h, s, l] = hexToHsl(primaryHex)
  const bright = hslToHex(h, s, Math.min(l + 8, 72))
  const dim    = hslToHex(h, s, Math.max(l - 12, 22))
  const dark   = hslToHex(h, s, Math.max(l - 30, 10))
  const rgbStr = (hex: string) => parseHex(hex)!.join(', ')
  return {
    primary: primaryHex,       primaryRgb: rgb.join(', '),
    bright,                    brightRgb: rgbStr(bright),
    dim,                       dimRgb:    rgbStr(dim),
    dark,                      darkRgb:   rgbStr(dark),
  }
}

const CUSTOM_THEME_VARS = [
  '--nc-primary', '--nc-primary-rgb',
  '--nc-primary-bright', '--nc-primary-bright-rgb',
  '--nc-primary-dim', '--nc-primary-dim-rgb',
  '--nc-primary-dark', '--nc-primary-dark-rgb',
  '--nc-primary-glow', '--nc-primary-subtle',
] as const

function applyCustomThemeInline(primaryHex: string): boolean {
  const v = deriveVariants(primaryHex)
  if (!v) return false
  const body = document.body
  body.style.setProperty('--nc-primary',           v.primary)
  body.style.setProperty('--nc-primary-rgb',       v.primaryRgb)
  body.style.setProperty('--nc-primary-bright',    v.bright)
  body.style.setProperty('--nc-primary-bright-rgb', v.brightRgb)
  body.style.setProperty('--nc-primary-dim',       v.dim)
  body.style.setProperty('--nc-primary-dim-rgb',   v.dimRgb)
  body.style.setProperty('--nc-primary-dark',      v.dark)
  body.style.setProperty('--nc-primary-dark-rgb',  v.darkRgb)
  body.style.setProperty('--nc-primary-glow',      `rgba(${v.primaryRgb}, 0.4)`)
  body.style.setProperty('--nc-primary-subtle',    `rgba(${v.primaryRgb}, 0.1)`)
  return true
}

function clearCustomThemeInline() {
  const body = document.body
  CUSTOM_THEME_VARS.forEach(p => body.style.removeProperty(p))
}

// Exported so the Theme Studio component can preview without persisting.
export const themeMath = { parseHex, rgbToHex, hexToHsl, hslToHex, deriveVariants, applyCustomThemeInline, clearCustomThemeInline }

// Tri-state sidebar visibility:
//   expanded → 256px with full labels
//   icons    → 64px icon-strip
//   hidden   → fully off-screen (showcase mode)
// Persisted across reloads in localStorage('theprotocol:sidebar-mode').
export type SidebarMode = 'expanded' | 'icons' | 'hidden'
const SIDEBAR_MODE_KEY = 'theprotocol:sidebar-mode'

// Ambient background level (§SETPOLISH 2026-07-27) — consumed by ViewAmbient,
// so one preference governs the grid/scan/beam/glow layer on every view.
//   full   — grid + scan + traveling beam + glows (the shipped default)
//   subtle — beam off, layer at half strength
//   off    — ViewAmbient renders nothing
export type AmbientMode = 'full' | 'subtle' | 'off'
const AMBIENT_MODE_KEY = 'theprotocol:ambient-mode'

// The strip at the top of every page (§ALERTS header strip, 2026-10-06; his words "can we make the new announcement
// bar optional in the settings? i really like the led"):
//   led — the dot-matrix ticker (the default)
//   bar — the announcement bar: one broadcast at a time, still, with open / mark-read and the alert chip
export type HeaderStrip = 'led' | 'bar'
const HEADER_STRIP_KEY = 'theprotocol:header-strip'

export const useUIStore = defineStore('ui', () => {
  // State
  const initialSidebarMode: SidebarMode = (() => {
    try {
      const v = localStorage.getItem(SIDEBAR_MODE_KEY)
      if (v === 'expanded' || v === 'icons' || v === 'hidden') return v
    } catch { /* SSR/private mode — fall through */ }
    return 'expanded'
  })()
  const sidebarMode = ref<SidebarMode>(initialSidebarMode)
  // Legacy boolean kept in sync so any consumer still reading sidebarOpen
  // continues to work: open = !hidden.
  const sidebarOpen = ref(initialSidebarMode !== 'hidden')
  const loading = ref(false)
  const globalError = ref<Error | null>(null)
  const theme = ref<'light' | 'dark'>('light')
  const brandTheme = ref<BrandTheme>(DEFAULT_BRAND_THEME)
  // Single named slot for the user's custom palette. null = no custom defined yet.
  // Persisted via CUSTOM_THEME_KEY ('theprotocol:customTheme') as '#RRGGBB'.
  const customThemeHex = ref<string | null>(null)
  /** §FEFRAME W2: '1' once a person picked a theme; until then the frame's own theme is the default. */
  const THEME_CHOSEN_KEY = 'theprotocol:brandThemeChosen'

  // Active frame across views (the admin Event Ledger + Treasury frame pickers), persisted across navigation so a
  // choice on one view follows the operator to its siblings; URL ?frame= still wins on direct navigation.
  // §FEFRAME W2: a frame KEY from the frame manifest ('' = this registry's own frame), never a letter. A remembered
  // letter of the retired frames (A/B/C) reads as '' (local).
  const ACTIVE_FRAME_KEY = 'theprotocol:activeFrame'
  const activeFrame = ref<string>(((): string => {
    try {
      const v = (localStorage.getItem(ACTIVE_FRAME_KEY) || '').trim()
      if (v && v.length > 1) return v
    } catch { /* SSR/private mode */ }
    return ''
  })())
  function setActiveFrame(f: string) {
    activeFrame.value = f || ''
    try { localStorage.setItem(ACTIVE_FRAME_KEY, activeFrame.value) } catch { /* non-fatal */ }
  }

  // Ambient background level (§SETPOLISH) — read by ViewAmbient on every view.
  const ambientMode = ref<AmbientMode>(((): AmbientMode => {
    try {
      const v = localStorage.getItem(AMBIENT_MODE_KEY)
      if (v === 'full' || v === 'subtle' || v === 'off') return v
    } catch { /* SSR/private mode */ }
    return 'full'
  })())
  function setAmbientMode(m: AmbientMode) {
    ambientMode.value = m
    try { localStorage.setItem(AMBIENT_MODE_KEY, m) } catch { /* non-fatal */ }
  }

  // The header strip (§ALERTS): per browser, like the background level; an unknown stored value reads as the default.
  const headerStrip = ref<HeaderStrip>(((): HeaderStrip => {
    try {
      const v = localStorage.getItem(HEADER_STRIP_KEY)
      if (v === 'led' || v === 'bar') return v
    } catch { /* SSR/private mode */ }
    return 'led'
  })())
  function setHeaderStrip(m: HeaderStrip) {
    headerStrip.value = m === 'bar' ? 'bar' : 'led'
    try { localStorage.setItem(HEADER_STRIP_KEY, headerStrip.value) } catch { /* non-fatal */ }
  }

  // Mobile drawer (2026-05-08, mobile pass).
  // Independent from sidebarMode (which is the user's *desktop* preference).
  // At <1024px the sidebar renders as an overlay drawer regardless of
  // sidebarMode; this ref tracks whether that drawer is currently visible.
  // Always starts closed — opening is an explicit hamburger tap. Auto-closes
  // on route change inside DashboardSidebar.
  const mobileDrawerOpen = ref(false)
  function openMobileDrawer()   { mobileDrawerOpen.value = true }
  function closeMobileDrawer()  { mobileDrawerOpen.value = false }
  function toggleMobileDrawer() { mobileDrawerOpen.value = !mobileDrawerOpen.value }

  // §pass50.7 — Quick-onboard modal. Opens from any "0 agents / need an agent
  // for this" hook point (AgentSelectorModal empty state, MyAgents empty,
  // MissionControl CTA, etc.) instead of routing to the full AgentForge view.
  // 30-second flow: name → create → auto-authenticate → setActive → close.
  const showQuickAgentModal = ref(false)
  function openQuickAgentModal()   { showQuickAgentModal.value = true }
  function closeQuickAgentModal()  { showQuickAgentModal.value = false }

  // §ONBOARDQOL P1 (2026-09-02) — a tick the quick-onboard modal bumps the moment an agent
  // is CREATED, so surfaces rendered against "0 agents" (the dashboard's first-run CTA and
  // its fleet card) can refresh without a reload. MEASURED before this existed: the modal
  // said "is live" while the dashboard behind it still showed the CTA, and F5 was the only
  // refresh. A tick, not the agent object — consumers own their fetch rails and must read
  // the SERVER, never a copy handed over the store.
  const agentCreatedTick = ref(0)
  function noteAgentCreated() { agentCreatedTick.value++ }

  // Agent picker attention — two mechanisms (RBAC §66.1 refactor 2026-05-08):
  //
  //   1. agentSwitcherAttention (continuous, hover-driven)
  //      Set true while the user is hovering a locked agent-required item.
  //      AgentSwitcher.vue applies a continuous gentle glow ring as long as
  //      this is true. Mirrors the locked-tooltip's "while hovering" UX —
  //      Commander explicitly asked for the blinking to be hover-driven.
  //
  //   2. agentSwitcherPulseToken + agentSwitcherPulseAutoOpen (one-shot)
  //      Used when there's NO hover (router guard navigation block) — bumps
  //      a counter that triggers a one-shot 2.4s pulse + auto-open.
  //
  //   Click on a locked agent-required item just opens the dropdown via the
  //   pulse-token mechanism (autoOpen=true, no extra blinking — user already
  //   saw the hover-glow before they clicked).
  const agentSwitcherAttention = ref(false)
  function setAgentSwitcherAttention(on: boolean) {
    agentSwitcherAttention.value = on
  }

  const agentSwitcherPulseToken = ref(0)
  const agentSwitcherPulseAutoOpen = ref(true)
  function pulseAgentSwitcher(opts: { autoOpen?: boolean } = {}) {
    agentSwitcherPulseAutoOpen.value = opts.autoOpen !== false
    agentSwitcherPulseToken.value++
  }

  // Notification system reference. §FESUITE: nothing ever registered the app's NotificationSystem here, so every
  // show* call below was a silent no-op (564 call sites: no success and no error toast anywhere in the console, at
  // least since the 2026-08-05 reality sync). App.vue registers it on mount now; a toast raised before that waits.
  const notificationSystem = shallowRef<any>(null)
  const pendingNotifications: Array<Omit<Notification, 'id'>> = []

  // Actions
  function setSidebarMode(mode: SidebarMode) {
    sidebarMode.value = mode
    sidebarOpen.value = mode !== 'hidden'
    try { localStorage.setItem(SIDEBAR_MODE_KEY, mode) } catch { /* non-fatal */ }
  }

  // Cycle: expanded → icons → hidden → expanded.
  function cycleSidebar() {
    const next: SidebarMode =
      sidebarMode.value === 'expanded' ? 'icons' :
      sidebarMode.value === 'icons'    ? 'hidden' : 'expanded'
    setSidebarMode(next)
  }

  // Legacy two-state toggle preserved for any caller still using it.
  // Maps to: hidden ↔ expanded.
  function toggleSidebar() {
    setSidebarMode(sidebarMode.value === 'hidden' ? 'expanded' : 'hidden')
  }
  
  function setLoading(value: boolean) {
    loading.value = value
  }
  
  function setGlobalError(error: Error | null) {
    globalError.value = error
  }
  
  function setTheme(newTheme: 'light' | 'dark') {
    theme.value = newTheme
    // Apply theme to document
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    // Save to localStorage
    localStorage.setItem('theme', newTheme)
  }
  
  function toggleTheme() {
    setTheme(theme.value === 'light' ? 'dark' : 'light')
  }
  
  // Initialize theme from localStorage
  function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') as 'light' | 'dark' | null
    if (savedTheme) {
      setTheme(savedTheme)
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      setTheme('dark')
    }
  }

  // Brand theme (accent palette).
  // Built-ins ('neural', 'sovereign'): swap body class, clear any inline override.
  // 'custom': apply inline CSS variables from the user's saved hex (falls back
  //           to neural if no custom hex is defined — graceful degradation).
  function setBrandTheme(t: BrandTheme) {
    const body = document.body
    ALL_BRAND_THEMES.forEach(name => body.classList.remove(`theme-${name}`))
    if (t === 'custom') {
      if (customThemeHex.value && applyCustomThemeInline(customThemeHex.value)) {
        body.classList.add('theme-custom')
        brandTheme.value = 'custom'
      } else {
        // No custom defined or invalid — silently fall back so the UI never
        // ends up unstyled. Caller intent is "I want custom" so we still
        // record the intent in localStorage; once they pick a color it'll apply.
        clearCustomThemeInline()
        body.classList.add('theme-neural')
        brandTheme.value = 'neural'
      }
    } else {
      // Built-in: ensure no stale inline override hangs around from a previous
      // 'custom' session.
      clearCustomThemeInline()
      body.classList.add(`theme-${t}`)
      brandTheme.value = t
    }
    try {
      localStorage.setItem('brandTheme', brandTheme.value)
      // §FEFRAME W2: an explicit choice (every caller of setBrandTheme is a person's click) outranks the frame's own
      // theme from now on; see initializeBrandTheme.
      localStorage.setItem(THEME_CHOSEN_KEY, '1')
    } catch { /* non-fatal */ }
  }

  // Same DOM swap as setBrandTheme but intentionally skips localStorage.
  // Used by cinematic effects (landing-page glitch) that should not overwrite
  // the user's explicit preference.
  function setBrandThemeEphemeral(t: BrandTheme) {
    const body = document.body
    ALL_BRAND_THEMES.forEach(name => body.classList.remove(`theme-${name}`))
    if (t === 'custom' && customThemeHex.value && applyCustomThemeInline(customThemeHex.value)) {
      body.classList.add('theme-custom')
      brandTheme.value = 'custom'
    } else {
      clearCustomThemeInline()
      body.classList.add(`theme-${t === 'custom' ? 'neural' : t}`)
      brandTheme.value = t === 'custom' ? 'neural' : t
    }
  }

  // Cycle includes 'custom' only when a custom palette is defined.
  function cycleBrandTheme() {
    const order: BrandTheme[] = customThemeHex.value
      ? ['neural', 'sovereign', 'custom']
      : ['neural', 'sovereign']
    const i = order.indexOf(brandTheme.value)
    const next = order[(i + 1) % order.length]
    setBrandTheme(next)
  }

  /** Set or update the user's custom palette by primary hex.
   *  Validates + persists. If 'custom' is the active theme, applies live. */
  function setCustomThemeHex(hex: string): boolean {
    const rgb = parseHex(hex)
    if (!rgb) return false
    const normalized = '#' + rgb.map(n => n.toString(16).padStart(2, '0').toUpperCase()).join('')
    customThemeHex.value = normalized
    try { localStorage.setItem(CUSTOM_THEME_KEY, normalized) } catch { /* non-fatal */ }
    if (brandTheme.value === 'custom') applyCustomThemeInline(normalized)
    return true
  }

  /** Forget the custom palette. If currently active, fall back to neural. */
  function clearCustomTheme() {
    customThemeHex.value = null
    try { localStorage.removeItem(CUSTOM_THEME_KEY) } catch { /* non-fatal */ }
    if (brandTheme.value === 'custom') setBrandTheme('neural')
  }

  /**
   * §FEFRAME W2 (2026-10-01): THE FRAME'S OWN THEME IS THE DEFAULT; A PERSON'S OWN CHOICE STILL WINS.
   * Before W2 every console opened `neural` and saved it as if the visitor had chosen it, so ASIA (a sovereign frame)
   * opened cyan for everyone and could never open red. Now: a theme the person picked (THEME_CHOSEN_KEY) is applied;
   * otherwise the frame's theme is, from the server-rendered `<meta name="tp-frame-theme">` (no flash) or the frame
   * manifest when it lands, applied WITHOUT saving (a frame that changes its theme is followed).
   */
  function frameDefaultTheme(): BrandTheme | null {
    try {
      const v = document.querySelector('meta[name="tp-frame-theme"]')?.getAttribute('content') as BrandTheme | null
      return v === 'neural' || v === 'sovereign' ? v : null
    } catch { return null }
  }
  function themeWasChosen(): boolean {
    try { return localStorage.getItem(THEME_CHOSEN_KEY) === '1' } catch { return false }
  }
  function applyFrameTheme(theme: string | null | undefined) {
    if (themeWasChosen()) return
    const t = theme === 'neural' || theme === 'sovereign' ? theme : null
    if (t && t !== brandTheme.value) setBrandThemeEphemeral(t)
  }

  function initializeBrandTheme() {
    // Restore custom hex BEFORE applying brandTheme, so that if the saved
    // brandTheme is 'custom', the apply below finds the hex ready.
    try {
      const savedHex = localStorage.getItem(CUSTOM_THEME_KEY)
      if (savedHex && parseHex(savedHex)) customThemeHex.value = savedHex.toUpperCase()
    } catch { /* non-fatal */ }

    const saved = localStorage.getItem('brandTheme') as BrandTheme | null
    if (themeWasChosen() && saved && ALL_BRAND_THEMES.includes(saved)) {
      setBrandThemeEphemeral(saved)     // the person's choice, already saved
      return
    }
    setBrandThemeEphemeral(frameDefaultTheme() || DEFAULT_BRAND_THEME)
  }

  // Notification methods
  function setNotificationSystem(system: any) {
    notificationSystem.value = system
    if (!system) return
    for (const n of pendingNotifications.splice(0)) system.addNotification(n)
  }

  // §LEDGERGATE (V0599): the ledger gate's refusal is said ONCE, as the sentence. The client says it when a call meets it
  // whole (showLedgerRefusal, from client.ts); a component that then shows the error's raw detail would print the gate's
  // code word and say it a second time (V0598's AGORA desk: "Ledger busy" and "Order rejected ledger_unavailable: ...").
  // Such a toast is dropped while the client's is fresh, and says the sentence alone otherwise.
  let ledgerSaidAt = 0
  const LEDGER_SAID_FRESH_MS = 5_000

  function showLedgerRefusal(sentence: string) {
    ledgerSaidAt = Date.now()
    return showNotification({ type: 'warning', title: 'Ledger busy', message: sentence })
  }

  function showNotification(notification: Omit<Notification, 'id'>) {
    const sentence = wholeLedgerMessage(notification.message)
    if (sentence !== null) {
      if (Date.now() - ledgerSaidAt < LEDGER_SAID_FRESH_MS) return
      ledgerSaidAt = Date.now()
      notification = { ...notification, message: sentence }
    }
    if (notificationSystem.value) {
      return notificationSystem.value.addNotification(notification)
    }
    // Before the app has mounted (a router guard, a boot-time failure): keep it for the moment it can be shown, and
    // keep only the newest few so a loop at boot cannot queue without bound.
    pendingNotifications.push(notification)
    if (pendingNotifications.length > 5) pendingNotifications.shift()
  }
  
  function showSuccess(title: string, message?: string) {
    return showNotification({ type: 'success', title, message })
  }
  
  function showError(title: string, message?: string) {
    return showNotification({ type: 'error', title, message })
  }
  
  function showWarning(title: string, message?: string) {
    return showNotification({ type: 'warning', title, message })
  }
  
  function showInfo(title: string, message?: string) {
    return showNotification({ type: 'info', title, message })
  }
  
  return {
    // State
    sidebarMode,
    sidebarOpen,
    mobileDrawerOpen,
    showQuickAgentModal,
    agentSwitcherAttention,
    agentSwitcherPulseToken,
    agentSwitcherPulseAutoOpen,
    loading,
    globalError,
    theme,
    brandTheme,
    customThemeHex,

    // Actions
    setSidebarMode,
    cycleSidebar,
    toggleSidebar,
    openMobileDrawer,
    closeMobileDrawer,
    toggleMobileDrawer,
    openQuickAgentModal,
    closeQuickAgentModal,
    agentCreatedTick,
    noteAgentCreated,
    setAgentSwitcherAttention,
    pulseAgentSwitcher,
    setLoading,
    setGlobalError,
    setTheme,
    toggleTheme,
    initializeTheme,
    setBrandTheme,
    setBrandThemeEphemeral,
    cycleBrandTheme,
    initializeBrandTheme,
    applyFrameTheme,
    setCustomThemeHex,
    clearCustomTheme,
    activeFrame,
    setActiveFrame,
    ambientMode,
    setAmbientMode,
    headerStrip,
    setHeaderStrip,

    // Notifications
    setNotificationSystem,
    showNotification,
    showSuccess,
    showError,
    showWarning,
    showLedgerRefusal,
    showInfo
  }
})
