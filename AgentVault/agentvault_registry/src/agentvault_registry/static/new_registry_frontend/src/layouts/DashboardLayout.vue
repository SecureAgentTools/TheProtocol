<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, defineAsyncComponent, watch } from 'vue'
import { readAccessToken } from '@/services/accessToken'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ReleaseChannelBanner from '@/components/admin/ReleaseChannelBanner.vue'
import { useRealtimeStore } from '@/stores/realtime'
import { useUIStore } from '@/stores/ui'
import { useWebSocket } from '@/composables/useWebSocket'
import { useViewport } from '@/composables/useViewport'
import DashboardSidebar from '@/components/DashboardSidebar.vue'
import DashboardHeader from '@/components/DashboardHeader.vue'
import PendingDeletionBanner from '@/components/common/PendingDeletionBanner.vue'
import Icon from '@/components/Icon.vue'
import NotificationToast from '@/components/common/NotificationToast.vue'
import CriticalBanner from '@/components/common/CriticalBanner.vue'
// §pass50.7 — lazy-load QuickAgentModal to avoid circular-import death on boot
const QuickAgentModal = defineAsyncComponent(() => import('@/components/common/QuickAgentModal.vue'))
import ViewAmbient from '@/components/common/ViewAmbient.vue'
import GuidedTour from '@/views/Tutorials/guided/GuidedTour.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useLogger } from '@/composables/useLogger'
import { useRouter } from 'vue-router'

const log = useLogger('DashboardLayout')

// Lazy load AgentSelectorModal to avoid circular dependency
const AgentSelectorModal = defineAsyncComponent(() =>
  import('@/components/common/AgentSelectorModal.vue')
)

const authStore = useAuthStore()
const realtimeStore = useRealtimeStore()
const notifStore = useNotificationStore()
const uiStore = useUIStore()
const route = useRoute()
const router = useRouter()
const viewport = useViewport()

const isAuthenticated = computed(() => authStore.isAuthenticated)
// 2026-05-08: routes can opt into rendering inside DashboardLayout for
// anonymous visitors via `meta.allowAnonymous: true`. Currently used by
// /leaderboard so public visitors get the regular sidebar + header chrome
// without forcing login.
const allowAnonymous = computed(() => Boolean(route.meta?.allowAnonymous))
const showShell = computed(() => isAuthenticated.value || allowAnonymous.value)
const mockDataEnabled = ref(false) // mock data removed

// §CHATPOLISH — the sidebar's live width, published to the document so chrome
// rendered ABOVE this component (App.vue's beta banner) can clear it. The shell
// that owns the sidebar is the only thing that knows how wide it is, so the
// number is derived from the SAME sidebarMode the content padding uses rather
// than copied as a magic 256. Cleared on unmount: no shell, no inset.
const shellInsetPx = computed(() => {
  if (viewport.isMobile.value) return 0
  switch (uiStore.sidebarMode) {
    case 'hidden': return 0
    case 'icons':  return 64
    default:       return 256
  }
})
watch(shellInsetPx, (px) => {
  try { document.documentElement.style.setProperty('--nc-shell-inset', `${px}px`) } catch { /* SSR-safe */ }
}, { immediate: true })
onUnmounted(() => {
  try { document.documentElement.style.removeProperty('--nc-shell-inset') } catch { /* ignore */ }
})

// Reactive content padding. On mobile (<1024px) the sidebar is an overlay
// drawer, so content takes the full viewport width (pl-0). On desktop the
// padding mirrors the user's chosen sidebar mode.
const contentPaddingClass = computed(() => {
  if (viewport.isMobile.value) return 'pl-0'
  switch (uiStore.sidebarMode) {
    case 'hidden':   return 'pl-0'
    case 'icons':    return 'pl-16'
    case 'expanded':
    default:         return 'pl-64'
  }
})

// Mobile drawer wiring. The sidebar is always rendered; on mobile its
// `transform: translateX(-100%)` keeps it off-screen unless the drawer
// state is open. We also keep a body class so global CSS can react.
const drawerOpen = computed(() => viewport.isMobile.value && uiStore.mobileDrawerOpen)
function closeDrawer() { uiStore.closeMobileDrawer() }

// Auto-close drawer when route changes (mobile pattern — feels broken
// otherwise). Watching the path instead of the route object avoids
// firing on hashchange-only updates within the same view.
watch(() => route.path, () => {
  if (uiStore.mobileDrawerOpen) uiStore.closeMobileDrawer()
})

// Body scroll-lock + body class while drawer open (prevents touch scroll
// on the underlying page so the drawer feels modal). Also adds an
// `is-mobile` body class so global CSS can reference it.
watch([() => viewport.isMobile.value, () => uiStore.mobileDrawerOpen], ([mobile, open]) => {
  if (typeof document === 'undefined') return
  document.body.classList.toggle('is-mobile', mobile)
  document.body.classList.toggle('body-scroll-lock', mobile && open)
}, { immediate: true })

// When viewport crosses back to desktop, ensure the drawer state is reset
// (prevents the drawer being "open" but invisible after a resize).
watch(() => viewport.isMobile.value, (mobile) => {
  if (!mobile && uiStore.mobileDrawerOpen) uiStore.closeMobileDrawer()
})

// Esc key closes the drawer (matches modal-style UX).
function onEscClose(e: KeyboardEvent) {
  if (e.key === 'Escape' && uiStore.mobileDrawerOpen) {
    e.preventDefault()
    uiStore.closeMobileDrawer()
  }
}

// Global keyboard shortcut: backslash cycles sidebar mode. Useful for live
// demos where you want to clean up chrome without leaving the keyboard.
// Skips when typing into form fields so it doesn't intercept legitimate input.
function onSidebarKey(e: KeyboardEvent) {
  if (e.key !== '\\') return
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  e.preventDefault()
  uiStore.cycleSidebar()
}

// Initialize WebSocket and connect it to realtime store
let websocket: ReturnType<typeof useWebSocket> | null = null

// Listen for mock data toggle and initialize WebSocket
// §FINDFIX F2 — measured main min-height (the OurChatShell pattern). The body
// ResizeObserver catches chrome changes window resize cannot see (beta banner
// dismissal shifts main's top without a viewport resize).
const mainEl = ref<HTMLElement | null>(null)
const shellEl = ref<HTMLElement | null>(null)
const mainTopPx = ref(64)
const shellTopPx = ref(0)
const measureMain = () => {
  try {
    if (mainEl.value) mainTopPx.value = Math.max(0, Math.round(mainEl.value.getBoundingClientRect().top + (window.scrollY || 0)))
    if (shellEl.value) shellTopPx.value = Math.max(0, Math.round(shellEl.value.getBoundingClientRect().top + (window.scrollY || 0)))
  } catch { /* noop */ }
}
const mainStyle = computed(() => ({ minHeight: `calc(100vh - ${mainTopPx.value}px)` }))
const shellStyle = computed(() => ({ minHeight: `calc(100vh - ${shellTopPx.value}px)` }))
let bodyRO: ResizeObserver | null = null

onMounted(async () => {
  // Sidebar shortcut binding (\ cycles expanded → icons → hidden → expanded)
  window.addEventListener('keydown', onSidebarKey)
  measureMain()
  window.addEventListener('resize', measureMain, { passive: true })
  try {
    bodyRO = new ResizeObserver(() => measureMain())
    bodyRO.observe(document.body)
  } catch { /* noop */ }
  // Mobile-pass: Esc closes drawer
  window.addEventListener('keydown', onEscClose)

  // Initialize WebSocket connection when authenticated
  // Direct execution with async IIFE - avoids minification issues
  // Fetch unread notifications on every mount (login or page refresh)
  notifStore.fetchUnread()
  // §bc1 T1.3 — cross-tab read/retract/update sync (idempotent).
  notifStore.startCrossTabSync()

  // continue with WebSocket bootstrap
  if (authStore.isAuthenticated) {
    // Immediately invoked async function
    ;(async () => {
      const token = authStore.token || readAccessToken()
      if (token) {
        log.info('Creating WebSocket instance…')
        try {
          // Create WebSocket instance
          websocket = useWebSocket({
            autoConnect: false, // We'll connect manually
            reconnect: true,
            enabled: true
          })

          // Connect WebSocket to realtime store
          realtimeStore.setWebSocketInstance(websocket)

          // Now connect
          await websocket.connect()
          log.info('WebSocket connected successfully')

          // Route live WS notification messages into the notification store
          websocket.on('notification', (data: any) => {
            notifStore.addLiveNotification(data)
            // §bc1 T1.2 — nudge the LED ticker to refresh immediately.
            try { window.dispatchEvent(new CustomEvent('theprotocol:notification-changed')) } catch (_) { /* ignore */ }
          })

          // §bc1 T1.4 — backend retract/update events
          websocket.on('broadcast.retracted', (data: any) => {
            if (data?.broadcast_id != null) {
              notifStore.retract(Number(data.broadcast_id))
              try { window.dispatchEvent(new CustomEvent('theprotocol:notification-changed')) } catch (_) { /* ignore */ }
            }
          })
          websocket.on('broadcast.updated', (data: any) => {
            if (data?.broadcast_id != null) {
              notifStore.patchItem({
                broadcast_id: Number(data.broadcast_id),
                title: data.title,
                body: data.body,
                broadcast_type: data.broadcast_type,
              })
              try { window.dispatchEvent(new CustomEvent('theprotocol:notification-changed')) } catch (_) { /* ignore */ }
            }
          })

          // §bc1 T1.2 — reconnected after a partition: re-hydrate unread
          // notifications (server may have queued/created items we missed).
          websocket.on('reconnected', () => {
            log.info('WS reconnected → fetchUnread()')
            notifStore.fetchUnread()
          })

          // §bc3 T3.8 — cross-device read sync. Another tab/device of THIS
          // same developer marked a broadcast read; mirror locally without
          // calling /read again.
          websocket.on('developer.notification_read', (data: any) => {
            if (data?.broadcast_id != null) {
              notifStore.applyRemoteRead(Number(data.broadcast_id))
              try { window.dispatchEvent(new CustomEvent('theprotocol:notification-changed')) } catch (_) { /* ignore */ }
            }
          })

          // §bc4 T4.2 — org membership changed; re-fetch is a no-op for now
          // (frontend stores org list elsewhere). Reserved for future.
          websocket.on('developer.orgs.updated', (_data: any) => {
            log.info('developer.orgs.updated received')
          })

          // §bc1 T1.8 — server forcibly closed with policy violation (expired
          // JWT). Surface the reason + redirect to login. Don't retry into a
          // 1008 loop; the WS service already disabled reconnect for us.
          websocket.on('auth_expired', (data: any) => {
            log.warn('WS auth_expired', data)
            notifStore.addLiveNotification({
              broadcast_id: -1,
              title: 'Session expired',
              message: 'Your session has expired. Please sign in again.',
              type: 'warning',
            })
            try {
              // §FEFRAME W1: local only; the socket's expiry is not the person pressing Log out on every device
              void authStore.endLocalSession?.('the event socket said auth_expired')
            } catch (_) { /* ignore */ }
            router.push({ name: 'login' }).catch(() => { /* ignore */ })
          })
        } catch (error) {
          console.error('[DashboardLayout] Failed to initialize WebSocket:', error)
          // Don't throw - WebSocket is optional
        }
      } else {
        log.warn('Skipping WebSocket - no token available')
      }
    })()
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onSidebarKey)
  window.removeEventListener('keydown', onEscClose)
  window.removeEventListener('resize', measureMain)
  try { bodyRO?.disconnect() } catch { /* noop */ }
  bodyRO = null
  if (typeof document !== 'undefined') {
    document.body.classList.remove('body-scroll-lock')
    document.body.classList.remove('is-mobile')
  }
})
</script>

<template>
  <!-- §FINDFIX F2 — the shell's floor is measured too: min-h-screen (100vh)
       under the 61px in-flow banner made body scroll banner+100vh on EVERY
       page. Same measure as main; falls back to 100vh when nothing sits above. -->
  <div v-if="showShell" ref="shellEl" class="layout-shell" :style="shellStyle">
    <!-- Unified app-wide ambient (2026-05-08 polish): grid + scan + traveling
         beam + radial glows. Single source of truth for ALL views; replaces
         the ad-hoc layout-ambient block that only some pages had. Views
         that previously rendered their OWN ambient (Federation, AdminCanaries,
         AdminReactors, AdminTreasury) stack their view-local accents on top
         of this global layer (their z-index 0 elements sit ABOVE this since
         this is global-fixed at the layout root).
         §pass41 (2026-05-18) — Tone now driven by route meta. Admin views
         render `admin` (amber), security/monitor views render `security`
         (red), sovereign-themed views render `sovereign` (violet+crimson),
         all others fall back to `default` (federation violet+cyan). View-
         local <ViewAmbient> imports are no longer needed — set the meta in
         router/index.ts instead. -->
    <ViewAmbient :tone="(route.meta.viewAmbientTone as 'default'|'admin'|'security'|'cyan'|'sovereign') || 'default'" />
    <!-- Demo Mode Banner -->
    <div v-if="mockDataEnabled" class="bg-yellow-400 dark:bg-yellow-600 text-yellow-900 dark:text-yellow-100">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between py-2">
          <div class="flex items-center">
            <Icon icon="mdi:test-tube" class="w-5 h-5 mr-2" />
            <span class="font-medium text-sm">
              Demo Mode Active - All data is simulated for demonstration purposes
            </span>
          </div>
          <RouterLink 
            to="/developer" 
            class="text-sm underline hover:no-underline"
          >
            Manage in Developer Tools
          </RouterLink>
        </div>
      </div>
    </div>
    
    <!-- Live notification toasts (f034) -->
    <NotificationToast />

    <!-- Mobile drawer backdrop (mobile-pass 2026-05-08).
         Rendered only when isMobile && drawer open. Click anywhere on
         the dimmed page to close the drawer. -->
    <Transition name="mobile-backdrop">
      <div
        v-if="drawerOpen"
        class="mobile-drawer-backdrop"
        aria-hidden="true"
        @click="closeDrawer"
      />
    </Transition>

    <!-- Sidebar -->
    <DashboardSidebar />

    <!-- Floating reveal tab — desktop only. On mobile the hamburger button
         in DashboardHeader takes over (44×44 tap target, always visible).
         Visible in 'hidden' AND 'icons' modes (user-feedback 2026-05-07).
         Click cycles forward (icons → hidden, hidden → expanded). -->
    <button
      v-if="!viewport.isMobile.value && (uiStore.sidebarMode === 'hidden' || uiStore.sidebarMode === 'icons')"
      @click="uiStore.sidebarMode === 'hidden' ? uiStore.setSidebarMode('expanded') : uiStore.cycleSidebar()"
      :class="[
        'sidebar-reveal-tab',
        uiStore.sidebarMode === 'icons' && 'sidebar-reveal-tab--icons',
      ]"
      :title="uiStore.sidebarMode === 'hidden' ? 'Show sidebar (press \\ to toggle)' : 'Hide sidebar (press \\ to cycle)'"
      :aria-label="uiStore.sidebarMode === 'hidden' ? 'Show sidebar' : 'Hide sidebar'"
    >
      <Icon icon="mdi:menu" class="w-4 h-4" />
    </button>

    <!-- Main Content Area -->
    <div :class="[contentPaddingClass, 'transition-all duration-300']">
      <!-- Header -->
      <DashboardHeader />

      <!-- §bc1 T1.1 — pinned full-width red banner for unread critical
           broadcasts. Renders nothing when there are no critical items
           (so existing layout is unchanged for the 99% case). -->
      <CriticalBanner />

      <!-- W2 (2026-05-09) — Pending-deletion banner. Shown across the whole
           app when the user has a deletion scheduled, until cancelled or
           anonymized. Click → /settings?tab=security to cancel. -->
      <PendingDeletionBanner />

      <!-- Page Content. G (2026-05-08): #main-content target for the
           skip-to-content link in App.vue (WCAG 2.4.1). -->
      <!-- §FINDFIX F2 — min-height is MEASURED from the element's own top, never
           an assumed chrome height: the old min-h-[calc(100vh-64px)] under-counted
           the real chrome (~125px with the beta banner up), leaving ~61px of dead
           scroll on every page (the --nc-header-h class, doctrine PART 1). -->
      <main id="main-content" ref="mainEl" tabindex="-1" :style="mainStyle">
        <ReleaseChannelBanner />
        <RouterView />
      </main>
    </div>
  </div>
  
  <!-- Non-authenticated routes. §FESUITE: never a page that needs a session. The moment a sign-out clears the token,
       this branch used to mount the member page the person was on again, as a visitor, and it fired its loads with no
       session (five refused calls on every sign-out from mission control) before the push to /login moved on. -->
  <main v-else id="main-content" class="min-h-screen app-main" tabindex="-1" style="background:#0a0d16;">
    <RouterView v-if="route.meta?.requiresAuth !== true" />
  </main>
  
  <!-- Agent Selector Modal (always available) -->
  <AgentSelectorModal />

  <!-- §pass50.7 — Quick onboarding modal (30s agent creation, global teleport) -->
  <QuickAgentModal />

  <!-- §2026-06-26 — Guided Tours overlay (spotlight walkthroughs of AGORA/Orgs/CICD) -->
  <GuidedTour />
</template>

<style scoped>
/* ─── Shell ─── */
.layout-shell {
  background: #0a0d16;
  position: relative;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* Floating reveal tab — only rendered when sidebar.mode === 'hidden'.
   Vertically centred on the left edge so it never overlaps page-level HUD
   panels that sit at top: 16px (AgentWorld controls, CONSUL drawers, etc.).
   Pulses softly so users in showcase mode notice the way back. */
.sidebar-reveal-tab {
  position: fixed;
  top: 50%;
  left: 0;
  transform: translateY(-50%);
  /* Above the sidebar shell (z-index 10000) so it's clickable when sidebar
     is in icons mode. Above the beta banner (z-index 9999) too. */
  z-index: 10001;
  width: 26px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--nc-primary-rgb), 0.12);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  border-left: none;
  border-top-right-radius: 6px;
  border-bottom-right-radius: 6px;
  color: rgba(var(--nc-primary-rgb), 0.95);
  cursor: pointer;
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.18);
  animation: sidebar-reveal-pulse 2.4s ease-in-out infinite;
  transition: background 0.2s, box-shadow 0.2s, left 0.3s;
}
/* Icons mode: anchor the tab to the right edge of the 4rem icon column
   so it pokes out as a fold-tab without overlapping the icon buttons.
   The 0.3s left transition matches the sidebar's width transition so
   the tab slides in sync as the user cycles through modes. */
.sidebar-reveal-tab--icons {
  left: 4rem;
}
.sidebar-reveal-tab:hover {
  background: rgba(var(--nc-primary-rgb), 0.22);
  box-shadow: 0 0 18px rgba(var(--nc-primary-rgb), 0.32);
  animation: none;
  transform: translateY(-50%);
}
@keyframes sidebar-reveal-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.18); }
  50%      { box-shadow: 0 0 16px rgba(var(--nc-primary-rgb), 0.32); }
}

/* ─── Ambient layer ─── */
.layout-ambient {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

/* Dot grid */
.layout-grid {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.10) 1px, transparent 1px);
  background-size: 32px 32px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}

/* Scan beam */
.layout-scan {
  position: absolute;
  left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.35), transparent);
  box-shadow: 0 0 14px 3px rgba(var(--nc-primary-rgb), 0.12);
  animation: layout-scan-beam 16s linear infinite;
}
@keyframes layout-scan-beam {
  0%   { top: -2px;  opacity: 0; }
  5%   { opacity: 1; }
  95%  { opacity: 1; }
  100% { top: 100vh; opacity: 0; }
}

/* Radial glows */
.layout-glow {
  position: absolute;
  border-radius: 50%;
  opacity: 0.13;
}
.layout-glow-1 {
  width: 700px; height: 700px;
  top: -180px; left: -180px;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.5), transparent 70%);
  animation: layout-glow-pulse 10s ease-in-out infinite alternate;
}
.layout-glow-2 {
  width: 500px; height: 500px;
  bottom: 5%; right: -100px;
  background: radial-gradient(circle, rgba(0, 100, 180, 0.4), transparent 70%);
  animation: layout-glow-pulse 14s ease-in-out infinite alternate-reverse;
}
@keyframes layout-glow-pulse {
  0%   { opacity: 0.10; }
  100% { opacity: 0.18; }
}

/* Ensure sidebar, header, and content sit above ambient.
   Sidebar is 10000 so its toggle buttons remain clickable above the
   sticky beta banner (z-index 9999 in App.vue). */
:global(.sidebar-shell)  { z-index: 10000 !important; }
:global(header)          { position: relative; z-index: 30; }
:global(.pl-64 > *)      { position: relative; z-index: 1; }

/* Mobile-pass 2026-05-08: drawer backdrop transition. Component-scoped
   wrapper so it only fades in/out the .mobile-drawer-backdrop element. */
.mobile-backdrop-enter-active,
.mobile-backdrop-leave-active { transition: opacity 180ms ease; }
.mobile-backdrop-enter-from,
.mobile-backdrop-leave-to     { opacity: 0; }
</style>
