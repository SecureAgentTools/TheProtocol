<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useViewport } from '@/composables/useViewport'
import { useI18n } from '@/composables/useI18n'
// §pass66 (2026-05-22) — replace hardcoded "//SOVEREIGN·NODE" brand text
// with the actual registry name from /federation/info. Cloud-ops show their
// own subdomain (e.g. "CLOUD-OP-OP-QATEST14"); mainframes show "REGISTRY-A"
// or "FRAME-B"; sandboxes show their own name. registryInfo store loads
// once at app boot + caches forever (tier doesn't change at runtime).
import { useRegistryInfoStore } from '@/stores/registryInfo'
import AgentSwitcher from '@/components/common/AgentSwitcher.vue'
import NotificationBell from '@/components/common/NotificationBell.vue'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import LedMatrixTicker from '@/components/header/LedMatrixTicker.vue'
import AnnouncementBar from '@/components/header/AnnouncementBar.vue'
import { apiClient } from '@/services/api/client'
import { useCurrency } from '@/composables/useCurrency'
import { useFrames } from '@/composables/useFrames'

const router = useRouter()
const authStore = useAuthStore()
const uiStore = useUIStore()
const viewport = useViewport()
const { t, locale: i18nLocale, availableLocales } = useI18n()
// §pass66 — registry name display. registryInfo.load() is idempotent +
// cached; safe to call from every component that needs the name. We
// uppercase for the LED-matrix-style brand aesthetic.
const registryInfo = useRegistryInfoStore()
registryInfo.load()
const brandName = computed(() =>
  (registryInfo.registryName || 'REGISTRY').toUpperCase()
)

// Frame / settlement-currency chip (FX multi-currency, 2026-06-02).
// Reflects which sovereign frame + currency this registry runs (AVT on
// Frame A/B, BVT on Frame C). Card-derived (public) → shows for anonymous
// visitors too. Strategy §17.1 G-ARCH-1 (the missing global currency context).
const { localCurrency, describe } = useCurrency()
const { localFrame } = useFrames()
const curDesc = computed(() => describe(localCurrency.value))
const frameChipTitle = computed(() => {
  const f = localFrame.value
  const where = f ? `${f.label} · ${f.trustDomain}` : 'This registry'
  return `${where} — settlement currency ${localCurrency.value}`
})

// Language picker open/close + click-outside teardown
const langOpen = ref(false)
const langRef = ref<HTMLElement | null>(null)
function selectLocale(code: string) {
  i18nLocale.value = code as typeof i18nLocale.value
  langOpen.value = false
}
function onDocClickForLang(e: MouseEvent) {
  if (!langOpen.value) return
  if (langRef.value && !langRef.value.contains(e.target as Node)) {
    langOpen.value = false
  }
}

const currentUser = computed(() => authStore.user)

// Fetch avatar from /developers/me (same as sidebar)
const avatarUrl = ref('')
const displayName = ref('')

onMounted(async () => {
  document.addEventListener('click', onDocClickForLang)
  // Skip /developers/me for anonymous visitors (Leaderboard public route).
  // Without this guard, anonymous would 401 on every header mount.
  if (!authStore.isAuthenticated) return
  try {
    const res = await apiClient.get('/developers/me')
    avatarUrl.value = res.data.avatar_url || ''
    displayName.value = res.data.display_name || ''
  } catch { /* non-blocking */ }
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClickForLang)
})

// 2026-05-08: anonymous-visitor support for /leaderboard et al.
const isAuthenticated = computed(() => authStore.isAuthenticated)

function goToSettings() {
  router.push('/settings')
}
</script>

<template>
  <header class="dh-header">
    <div class="dh-inner">
      <!-- Mobile-pass 2026-05-08: hamburger button (44×44 tap target).
           Visible only at <1024px via .mobile-hamburger CSS, replacing the
           desktop sidebar reveal tab. Opens the mobile drawer in uiStore. -->
      <button
        class="mobile-hamburger"
        @click="uiStore.toggleMobileDrawer()"
        :aria-label="uiStore.mobileDrawerOpen ? 'Close menu' : 'Open menu'"
        :aria-expanded="uiStore.mobileDrawerOpen"
      >
        <Icon :icon="uiStore.mobileDrawerOpen ? 'mdi:close' : 'mdi:menu'" class="w-5 h-5" />
      </button>

      <!-- Left: Brand — §pass66 (2026-05-22) — dynamic registry name.
           Each registry's frontend brands itself: Frame A says "REGISTRY-A",
           Frame B says "FRAME-B", cloud-ops say "CLOUD-OP-OP-QATEST14", etc.
           Replaces the prior hardcoded "//SOVEREIGN·NODE" i18n pair which
           was visually wrong for cloud-ops (they're not sovereign). -->
      <div class="dh-brand" @click="router.push('/mission-control')" role="button">
        <span class="dh-brand-slash">//</span>
        <span class="dh-brand-word">{{ brandName }}</span>
      </div>

      <!-- Center: the header strip (takes all available space): the LED ticker, or the announcement bar when
           Settings > Preferences > Header strip says so (§ALERTS, 2026-10-06; the LED stays the default) -->
      <div class="dh-ticker-area" :data-strip="uiStore.headerStrip">
        <AnnouncementBar v-if="uiStore.headerStrip === 'bar'" />
        <LedMatrixTicker v-else />
      </div>

      <!-- Right: Controls -->
      <div class="dh-controls">
        <!-- Language picker (always visible — anonymous visitors on /enterprise,
             /leaderboard, /founders-wall also need to switch language). -->
        <div class="dh-lang" ref="langRef">
          <button
            class="dh-lang-btn"
            :aria-label="`Language: ${availableLocales[i18nLocale]}`"
            :aria-haspopup="true"
            :aria-expanded="langOpen"
            @click="langOpen = !langOpen"
          >
            <Icon icon="mdi:translate" class="dh-lang-icon" />
            <span class="dh-lang-code">{{ i18nLocale.toUpperCase() }}</span>
          </button>
          <ul v-if="langOpen" class="dh-lang-menu" role="menu">
            <li v-for="(name, code) in availableLocales" :key="code" role="none">
              <button
                role="menuitem"
                class="dh-lang-item"
                :class="{ 'dh-lang-item--active': i18nLocale === code }"
                @click="selectLocale(code)"
              >
                <span class="dh-lang-item-code">{{ code.toUpperCase() }}</span>
                <span class="dh-lang-item-name">{{ name }}</span>
                <span v-if="i18nLocale === code" class="dh-lang-item-check" aria-hidden="true">✓</span>
              </button>
            </li>
          </ul>
        </div>

        <!-- Frame / settlement-currency chip (FX multi-currency, 2026-06-02).
             Card-derived → visible for anonymous visitors too. -->
        <div class="dh-frame-chip" :title="frameChipTitle" :aria-label="frameChipTitle" data-test="frame-currency-chip">
          <span class="dh-frame-chip-glyph" :style="{ color: curDesc.accent }" aria-hidden="true">{{ curDesc.glyph }}</span>
          <span class="dh-frame-chip-code">{{ localCurrency }}</span>
          <span v-if="localFrame?.shortLabel" class="dh-frame-chip-frame">{{ localFrame.shortLabel }}</span>
        </div>

        <!-- Authenticated controls -->
        <template v-if="isAuthenticated">
          <NotificationBell />
          <AgentSwitcher />

          <!-- User Avatar — single composition wrapper handles dual-slot flare.
               UserAvatar resolves selected_corner_flare + selected_encirclement_flare,
               wraps the avatar in FlareEncirclement (when encirclement-class) and
               stamps FlareBadge corner pip. One component, used identically across
               header / sidebar / settings / agent-switcher. See UserAvatar.vue. -->
          <UserAvatar
            class="dh-avatar"
            :user="currentUser"
            :avatar-url="avatarUrl || null"
            :display-name="displayName || currentUser?.name || currentUser?.email || null"
            :granted-at="currentUser?.flare_granted_at || null"
            size="md"
            clickable
            @click="goToSettings"
          />
        </template>

        <!-- Anonymous-visitor CTA (P2.1, 2026-05-08) — replaces the bell +
             agent switcher + avatar block when no logged-in user.
             2026-05-11: button labels migrated to cta.signUp / cta.signIn. -->
        <template v-else>
          <button class="dh-anon-btn dh-anon-btn--ghost" @click="router.push('/register')">
            {{ t('cta.signUp') }}
          </button>
          <button class="dh-anon-btn dh-anon-btn--primary" @click="router.push('/login')">
            {{ t('cta.signIn') }}
          </button>
        </template>
      </div>
    </div>
  </header>
</template>

<style scoped>
.dh-header {
  height: 48px;
  background: rgba(8, 10, 15, 0.95);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  /* §TICKERLAG (2026-08-30, his report: "the head ticker ... is lagging all
     across the site. on every view") — `backdrop-filter: blur(12px)` REMOVED.
     This bar contains LedMatrixTicker, a canvas that repaints on every
     requestAnimationFrame, and a backdrop-filter must recompute whenever its
     backdrop changes: the §BRIDGE P2 lesson ("backdrop-filter over a repainting
     canvas re-blurred EVERY FRAME"), recurring in the header.
     MEASURED, interleaved A/B, six alternating rounds on one page load: with
     the blur OFF the page sat at exactly 16.6-16.7ms (vsync, 60fps) in 6 of 6
     samples; with it ON it never once reached that floor (16.6-18.7ms).
     The visual cost of removing it is near zero on purpose — the plate above is
     already 95% opaque, so at most 5% of what you see was ever the blur. */
  position: relative;
  z-index: 30;
  /* §15.1: must be visible — the Sauron eye on md avatars renders ABOVE
     the avatar bbox, extending slightly above the header band. */
  overflow: visible;
}

.dh-inner {
  height: 100%;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 16px;
}

/* ─── Brand ─── */
.dh-brand {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  flex-shrink: 0;
  padding: 4px 8px 4px 0;
  transition: opacity 0.2s;
}
.dh-brand:hover { opacity: 0.8; }
.dh-brand-slash {
  color: rgba(var(--nc-primary-rgb), 0.3);
  font-weight: 300;
  font-size: 0.85rem;
  font-family: 'Fira Code', monospace;
}
.dh-brand-word {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'Fira Code', monospace;
}
.dh-brand-sep {
  color: rgba(var(--nc-primary-rgb), 0.15);
  font-size: 0.75rem;
}
.dh-brand-dim {
  color: rgba(255, 255, 255, 0.25);
  font-weight: 300;
}

/* ─── Ticker area ─── */
.dh-ticker-area {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  /* the strip measures the room it is given: in a signed-in phone header that is ~45 px, where the LED ticker showed a
     cut "CASTS" of its BROADCASTS badge (the camera, 2026-10-13); under 110 px it steps aside (the bell carries notices) */
  container-type: inline-size;
}
@container (max-width: 110px) {
  .dh-ticker-area > * { display: none; }
}

/* ─── Controls ─── */
.dh-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ─── Anonymous-visitor CTA buttons (P2.1, 2026-05-08) ─── */
.dh-anon-btn {
  padding: 6px 14px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-radius: 6px;
  cursor: pointer;
  transition: all 150ms ease;
  border: 1px solid;
  font-family: inherit;
  white-space: nowrap;
}
.dh-anon-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.95);
  border-color: rgba(var(--nc-primary-rgb), 1);
  color: #06141a;
}
.dh-anon-btn--primary:hover {
  background: var(--nc-primary-bright, rgba(var(--nc-primary-rgb), 1));
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.5);
}
.dh-anon-btn--ghost {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.75);
}
.dh-anon-btn--ghost:hover {
  border-color: rgba(255, 255, 255, 0.45);
  color: rgba(255, 255, 255, 1);
}

/* ─── Avatar ─── */
/* UserAvatar handles ring + encirclement + corner internally. We only
   reserve the slot here — sizing is the component's. */
.dh-avatar {
  /* No additional positioning needed — UserAvatar is inline-flex with
     its own sizing. The corner pip lives inside the component. */
}

/* ─── Language picker (8 locales, 2026-05-11) ─── */
.dh-lang {
  position: relative;
  flex-shrink: 0;
}
.dh-lang-btn {
  height: 32px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 6px;
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  cursor: pointer;
  font-family: 'Fira Code', monospace;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.dh-lang-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.14);
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  color: rgba(var(--nc-primary-rgb), 1);
}
.dh-lang-icon {
  width: 14px;
  height: 14px;
  display: inline-flex;
}
.dh-lang-code {
  font-feature-settings: 'tnum' 1;
}
.dh-lang-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 220px;
  background: rgba(10, 14, 22, 0.98);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 8px;
  padding: 4px;
  list-style: none;
  margin: 0;
  z-index: 100;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6),
              0 0 0 1px rgba(var(--nc-primary-rgb), 0.04) inset;
  backdrop-filter: blur(10px);
}
.dh-lang-item {
  width: 100%;
  display: grid;
  grid-template-columns: 38px 1fr 18px;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: none;
  background: transparent;
  color: rgba(230, 249, 255, 0.85);
  cursor: pointer;
  font-size: 0.8rem;
  text-align: left;
  border-radius: 6px;
  font-family: inherit;
  transition: background 0.1s, color 0.1s;
}
.dh-lang-item:hover {
  background: rgba(var(--nc-primary-rgb), 0.14);
  color: #ffffff;
}
.dh-lang-item--active {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.10);
}
.dh-lang-item-code {
  font-family: 'Fira Code', monospace;
  font-weight: 700;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  opacity: 0.75;
}
.dh-lang-item-name {
  font-weight: 500;
}
.dh-lang-item-check {
  text-align: right;
  font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 1);
}

/* ─── Frame / settlement-currency chip (FX multi-currency, 2026-06-02) ─── */
.dh-frame-chip {
  height: 32px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 6px;
  font-family: 'Fira Code', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  flex-shrink: 0;
  cursor: default;
}
.dh-frame-chip-glyph { font-size: 0.9rem; line-height: 1; }
.dh-frame-chip-code { color: rgba(230, 249, 255, 0.92); }
.dh-frame-chip-frame {
  color: rgba(var(--nc-primary-rgb), 0.7);
  border-left: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  padding-left: 6px;
}
@media (max-width: 639.98px) {
  .dh-frame-chip { padding: 0 8px; }
  .dh-frame-chip-frame { display: none; }
}

/* ─── Mobile pass (2026-05-08) ─── */
@media (max-width: 1023.98px) {
  .dh-inner { gap: 10px; padding: 0 10px; }
}
@media (max-width: 639.98px) {
  /* On small phones drop the brand text — the hamburger + ticker + bell + avatar
     are the priorities. Keeping the brand pushes everything off-screen. */
  .dh-brand { display: none; }
  .dh-controls { gap: 4px; }
  .dh-anon-btn { padding: 6px 10px; font-size: 0.62rem; }
  .dh-inner { gap: 6px; padding: 0 8px; }
  /* Language picker on phones: just the icon, no code label */
  .dh-lang-btn { padding: 0 8px; }
  .dh-lang-code { display: none; }
  .dh-lang-menu { right: -4px; min-width: 200px; }
}
</style>
