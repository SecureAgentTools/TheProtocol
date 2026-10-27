<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §DISCPUBLIC (2026-09-06, his word: "i want the discovery to be public … i want to display it in a showcase
// later on when deploying new frames to prod") — Agent Discovery without a session.
//
// It is the SAME view, not a copy: every endpoint Discovery reads is already public (the discover rail, the
// facets, the federation strip, the registry cards, and the federated index), and the view holds no session
// state of its own — measured, not assumed. What a visitor loses is the ability to ACT: the engage button
// asks for a sign-in instead of opening a contract. One view, two audiences, no second implementation to
// drift.
//
// The shell here is deliberately thin: brand, the frame's own name, and the two doors in. The landing-page
// announcement is his, later.
// ─────────────────────────────────────────────────────────────────────────────
import { computed, onMounted, ref } from 'vue'
import Discovery from '@/views/Discovery.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
// §BRANDEXPLORE (2026-09-08, his word: "add protocol logo and background to /explore, logo top left
// replacement for existing random logo"). The mark was a 10px rounded square drawn in CSS — a shape,
// not a brand. This is the real one, and it is the SAME FILE the frames serve as their registry-card
// icon (md5-identical to `scripts/hetzner_demo/assets/protocol-mark-neural.png`), so the public page
// and the signed card cannot drift apart.
//
// ⚠ IMPORTED, not referenced by path. `public/` files are NOT served at the root here — measured:
// `/pwa-192.png` 404s and `/ui/pwa-192.png` answers 200 with `text/html`, which is the SPA fallback
// pretending to be a file (the standing "a wrong path 200s the SPA fallback" trap). Importing lets
// Vite emit it into the hashed `/assets/` bundle, which is the one path that is actually served.
import markNeural from '@/assets/images/protocol-mark-neural.png'
import markSovereign from '@/assets/images/protocol-mark-sovereign.png'

const { t } = useI18n()
const { config, load } = useRegistryConfig()
onMounted(() => {
  void load()
  try { isSovereign.value = document.body.classList.contains('theme-sovereign') } catch { /* SSR-safe */ }
})

/** Each frame's own mark: EU wears the neural one, ASIA the sovereign one.
 *
 * (Before §FEFRAME W2 `/public/registry-config` carried no theme field — measured on ASIA, whose twelve keys were
 * all flags and names — so the body class was the only signal; it remains the fallback below.) The brand palette is applied as
 * `theme-neural` / `theme-sovereign` on `<body>` (the existing mechanism, §BRIDGE R11), which is
 * also what colours `--nc-primary-rgb` under this mark, so reading it keeps the glow and the glyph
 * from disagreeing. `isSovereign` is a ref updated on mount rather than a computed over the DOM,
 * because a computed whose only dependency is a non-reactive read is evaluated once and cached
 * for ever (the standing gotcha, §BRIDGE R9). */
const isSovereign = ref(false)
// §FEFRAME W2 (2026-10-01): the registry-config now carries the frame manifest, whose `self` names this frame's own
// card icon (absolute, on its public host) and theme. The frame's icon stands for "this registry" when it has one;
// else the bundled mark of the FRAME's theme (the body class is the viewer's palette, which a person may change).
const mark = computed(() => {
  const me: any = (config.value as any)?.self
  if (me?.icon_url) return String(me.icon_url)
  const theme = me?.theme || (isSovereign.value ? 'sovereign' : 'neural')
  return theme === 'sovereign' ? markSovereign : markNeural
})
</script>

<template>
  <div class="pub-shell">
    <!-- §BRANDEXPLORE — the ground the public page stands on. Two fixed radial washes in the frame's
         own primary colour plus a faint grid, all painted on the SHELL and pointer-events:none, so
         nothing below it changes behaviour and no card has to opt in. Cheap by construction: no
         animation, no blur, no canvas — §TICKERLAG's lesson is that a backdrop-filter over anything
         that repaints re-runs every frame, and this page repaints on every search keystroke. -->
    <div class="pub-bg" aria-hidden="true"></div>
    <header class="pub-bar">
      <a class="pub-brand" href="#/" :aria-label="t('publicExplore.home', 'Home')">
        <img class="pub-mark" :src="mark" alt="" width="26" height="26" decoding="async" />
        <span class="pub-name">{{ config.registry_name || 'TheProtocol' }}</span>
        <span class="pub-sub">{{ t('publicExplore.registry', 'registry') }}</span>
      </a>
      <div class="pub-actions">
        <a class="pub-link" href="#/login">{{ t('publicExplore.signIn', 'Sign in') }}</a>
        <a class="pub-cta" href="#/register">{{ t('publicExplore.join', 'Create an account') }}</a>
      </div>
    </header>

    <main id="main-content" class="pub-main app-main" tabindex="-1" data-testid="public-explore">
      <Discovery />
    </main>

    <footer class="pub-foot">
      {{ t('publicExplore.foot', 'Public view. Anyone can browse what this registry and its federation publish; signing in is what lets you engage an agent.') }}
    </footer>
  </div>
</template>

<style scoped>
.pub-shell { min-height: 100vh; background: var(--nc-void, #070b12); color: var(--nc-text-primary, #e7eef7); position: relative; }
/* §BRANDEXPLORE — the background. Fixed so it does not scroll with 56 cards, behind everything
   (z-index 0 against the bar's 30 and the main content's own stacking), and inert to the pointer. */
.pub-bg {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(1100px 620px at 12% -8%, rgba(var(--nc-primary-rgb), 0.13), transparent 62%),
    radial-gradient(900px 520px at 92% 4%, rgba(var(--nc-primary-rgb), 0.08), transparent 58%),
    linear-gradient(rgba(var(--nc-primary-rgb), 0.028) 1px, transparent 1px) 0 0 / 100% 46px,
    linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.028) 1px, transparent 1px) 0 0 / 46px 100%;
}
.pub-bar, .pub-main, .pub-foot { position: relative; z-index: 1; }
.pub-bar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 20px; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  background: rgba(var(--nc-primary-rgb), 0.03); position: sticky; top: 0; z-index: 30;
  backdrop-filter: blur(9px) saturate(1.05); -webkit-backdrop-filter: blur(9px) saturate(1.05);
}
.pub-brand { display: inline-flex; align-items: baseline; gap: 8px; text-decoration: none; color: inherit; }
/* the mark replaces a 10px CSS square. `display:block` so it does not sit on the text baseline the
   brand row aligns to, and a soft glow in the frame's own colour rather than a hard border. */
.pub-mark {
  width: 26px; height: 26px; display: block; align-self: center; border-radius: 6px;
  filter: drop-shadow(0 0 7px rgba(var(--nc-primary-rgb), 0.45));
}
.pub-name { font-weight: 800; letter-spacing: .02em; }
.pub-sub { font-size: 10px; text-transform: uppercase; letter-spacing: .12em; opacity: .55; }
.pub-actions { display: flex; align-items: center; gap: 10px; }
.pub-link { font-size: 12px; opacity: .8; text-decoration: none; color: inherit; }
.pub-link:hover { opacity: 1; }
.pub-cta {
  font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; text-decoration: none;
  color: var(--nc-primary, #22d3ee); background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
}
.pub-cta:hover { background: rgba(var(--nc-primary-rgb), 0.2); }
.pub-main { padding: 18px 20px 8px; max-width: 1600px; margin: 0 auto; }
/* §COCKPITDESK (2026-10-15), the phone camera: a two-line frame name beside "Sign in" and "Create an account" each broken
   over two lines. The doors keep one line each; the brand takes what is left, and its "registry" tag gives way first. */
.pub-link, .pub-cta { white-space: nowrap; }
.pub-brand { min-width: 0; }
.pub-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
@media (max-width: 420px) {
  .pub-bar { padding: 10px 12px; gap: 8px; }
  .pub-sub { display: none; }
  .pub-actions { gap: 8px; flex: 0 0 auto; }
}
.pub-foot { padding: 14px 20px 28px; font-size: 11px; opacity: .55; max-width: 1600px; margin: 0 auto; }
</style>
