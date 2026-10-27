<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { onMounted, ref, computed, defineAsyncComponent } from 'vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import NotificationSystem from '@/components/common/NotificationSystem.vue'
import CommandPalette from '@/components/common/CommandPalette.vue'
import ConsoleMovesBanner from '@/components/common/ConsoleMovesBanner.vue'
import LegalReconsentModal from '@/components/common/LegalReconsentModal.vue'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { loadFrameManifest } from '@/composables/useFrameManifest'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

// §FEFRAME W4: off the entry chunk, and mounted only for a signed-in person (a visitor never downloads it)
const FlareCelebrationModal = defineAsyncComponent(() => import('@/components/common/FlareCelebrationModal.vue'))
const authStore = useAuthStore()

// Refs
const notificationSystemRef = ref<InstanceType<typeof NotificationSystem>>()
const betaDismissed = ref(false)
const route = useRoute()
const ui = useUIStore()

// Hide banner on landing page and showcase (they have their own branding)
const showBetaBanner = computed(() => {
  if (betaDismissed.value) return false
  const path = route.path
  return path !== '/' && path !== '/showcase' && path !== '/login' && path !== '/register'
})

function dismissBeta() {
  betaDismissed.value = true
  try { localStorage.setItem('beta_banner_dismissed', '1') } catch { /* expected */ }
}

// Simple initialization
onMounted(() => {
  import.meta.env.DEV && console.log('App mounted')
  // §FESUITE: the one place the ui store learns where toasts go (it never did: every show* call was dropped).
  ui.setNotificationSystem(notificationSystemRef.value ?? null)
  // Idempotent — main.ts applied the body class pre-mount to avoid flash; this
  // syncs the Pinia store state with what's already on the body.
  try { ui.initializeBrandTheme() } catch { /* non-fatal */ }
  // §FEFRAME W2: where the server-rendered head carried no frame theme, the manifest's arrives a moment later
  void loadFrameManifest().then((m) => { try { ui.applyFrameTheme(m?.self?.theme) } catch { /* non-fatal */ } })
  try {
    betaDismissed.value = localStorage.getItem('beta_banner_dismissed') === '1'
  } catch { /* expected */ }
})
</script>

<template>
  <div id="app" class="nc-app min-h-screen nc-bg-deep">
    <!-- G (2026-05-08): Skip-to-content link for keyboard users (WCAG 2.4.1).
         Visible only when focused; bypasses the sidebar + header chrome. -->
    <a href="#main-content" class="skip-to-content">{{ t('app.skipToContent') }}</a>

    <!-- Beta disclaimer banner: a labelled region (named by its badge), so every page's content sits in a landmark -->
    <div v-if="showBetaBanner" class="beta-banner" role="region" aria-labelledby="beta-badge-label">
      <div class="beta-banner-inner">
        <span id="beta-badge-label" class="beta-badge">BETA</span>
        <span class="beta-text beta-text--long">{{ t('app.betaNotice') }}</span><span class="beta-text beta-text--short">{{ t('app.betaNoticeShort', 'Pre-release software. Units have no monetary value.') }}</span>
        <button class="beta-dismiss" data-testid="beta-dismiss" @click="dismissBeta" :title="t('app.dismiss')" :aria-label="t('app.dismiss')">&times;</button>
      </div>
    </div>

    <!-- §FEFRAME W4: on a host that is not this frame's console address, say so (one console host per frame) -->
    <ConsoleMovesBanner />

    <!-- Global error boundary -->
    <ErrorBoundary>
      <!-- Notification system -->
      <NotificationSystem ref="notificationSystemRef" />

      <!-- Global command palette (Cmd-K / Ctrl-K / `/` to open). Build #16. -->
      <CommandPalette />

      <!-- §15 — Shadow Chancellor unlock celebration modal. Mounts globally
           so it can fire on any page after the cumulative-€500 threshold
           is crossed. Self-gated: silent when conditions don't apply. -->
      <FlareCelebrationModal v-if="authStore.isAuthenticated" />

      <!-- §LEGALKIT: renewed acceptance after a material change of the Terms (§ 10.2); self-gated, dismissable -->
      <LegalReconsentModal />

      <!-- Main router outlet. §LANDINGTRUTH (28): the main landmark and the skip link's target for every page that does
           not render its own (DashboardLayout, PocketShell and the routes with meta.ownsMain do) -->
      <main v-if="!route.meta?.ownsMain" id="main-content" class="app-main" tabindex="-1">
        <RouterView />
      </main>
      <RouterView v-else />
    </ErrorBoundary>
  </div>
</template>

<style>
/* These two imports look redundant (main.ts imports both files too, and the build keeps one copy) but they set the
   ORDER: main.ts imports this component before its own stylesheets, so without them the rules below, and every
   element selector in them, would land before Tailwind's preflight instead of after it. */
@import '@/assets/styles/main.css';
@import '@/assets/styles/neural-command.css';

/* ── Beta Banner ── */
.beta-banner {
  position: sticky;
  top: 0;
  z-index: 9999;
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.12), rgba(245, 158, 11, 0.06));
  border-bottom: 1px solid rgba(245, 158, 11, 0.25);
  backdrop-filter: blur(8px);
}
.beta-banner-inner {
  max-width: 1200px;
  /* §CHATPOLISH (2026-08-30) — this box was centred on the VIEWPORT while the
     dashboard sidebar is deliberately stacked ABOVE the banner (z-index 9999,
     see DashboardLayout). At 1440px the content began at x=120 and the sidebar
     covers 256, so the BETA badge and the first ~10 characters were hidden on
     EVERY desktop page: the banner read "e-release software…". The shell that
     owns the sidebar publishes its width as `--nc-shell-inset`; where there is
     no shell (login, landing, Pocket) the variable is undefined and `auto`
     keeps the banner centred exactly as before. */
  margin: 0 auto 0 var(--nc-shell-inset, auto);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.78rem;
}
.beta-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 4px;
  color: #f59e0b;
  font-weight: 700;
  font-size: 0.68rem;
  letter-spacing: 1.5px;
}
.beta-text {
  color: #d4a04a;
  line-height: 1.4;
}
.beta-dismiss {
  flex-shrink: 0;
  margin-left: auto;
  background: none;
  border: none;
  color: #8b7033;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 4px;
  min-width: 44px;
  min-height: 44px;
  line-height: 1;
}
.beta-dismiss:hover {
  color: #f59e0b;
}

/* Neural Command App Styles */
.nc-app {
  position: relative;
  color: var(--nc-text-primary);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* §LANDINGTRUTH (28): the skip link focuses a main landmark; it needs no ring of its own */
.app-main:focus { outline: none; }

/* G (2026-05-08): Skip-to-content link. Hidden offscreen until focused.
   Keyboard users can Tab to this as the first stop on the page. */
.skip-to-content {
  position: absolute;
  top: -100px;
  left: 8px;
  z-index: 100100;  /* above everything including modals */
  padding: 8px 16px;
  background: var(--nc-primary, #00d2d2);
  color: #06141a;
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: 6px;
  text-decoration: none;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  transition: top 200ms ease;
}
.skip-to-content:focus {
  top: 8px;
  outline: 2px solid white;
  outline-offset: 2px;
}
</style>
