<template>
  <div class="app-shell">
    <div class="app-base-glow" aria-hidden="true"></div>
    <div class="app-aurora" aria-hidden="true"></div>
    <div class="app-grid-overlay" aria-hidden="true"></div>
    <div class="app-grain" aria-hidden="true"></div>
    <div class="app-vignette" aria-hidden="true"></div>
    <router-view />
  </div>
</template>

<script setup lang="ts">
</script>

<style>
.app-shell {
  position: relative;
  min-height: 100vh;
  overflow-x: hidden;
}

/* All atmosphere lives in fixed, GPU-composited layers so the body never
   repaints on number count-ups or state changes (was the source of flicker). */

/* Static observatory glow — crown (green) + counter (cyan), viewport-anchored. */
.app-base-glow {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(120% 80% at 50% -12%, rgba(0, 200, 83, 0.07) 0%, transparent 46%),
    radial-gradient(90% 70% at 100% 112%, rgba(0, 176, 255, 0.05) 0%, transparent 52%);
}

/* Gentle aurora drift — transform-ONLY (no blur, no opacity keyframes, own layer)
   so it composites cheaply and never flickers. */
.app-aurora {
  position: fixed;
  inset: -25%;
  pointer-events: none;
  z-index: 0;
  opacity: 0.9;
  background:
    radial-gradient(32% 26% at 24% 20%, rgba(0, 200, 83, 0.10) 0%, transparent 72%),
    radial-gradient(30% 24% at 80% 30%, rgba(0, 176, 255, 0.07) 0%, transparent 72%),
    radial-gradient(40% 30% at 60% 86%, rgba(0, 200, 83, 0.045) 0%, transparent 74%);
  transform: translateZ(0);
  will-change: transform;
  animation: auroraDrift 46s ease-in-out infinite alternate;
}

@keyframes auroraDrift {
  0%   { transform: translate3d(-1.5%, -1%, 0); }
  100% { transform: translate3d(1.5%, 1.5%, 0); }
}

.app-grid-overlay {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    linear-gradient(rgba(0, 200, 83, 0.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 200, 83, 0.018) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse 78% 64% at 50% 28%, rgba(0,0,0,0.7) 0%, transparent 100%);
  -webkit-mask-image: radial-gradient(ellipse 78% 64% at 50% 28%, rgba(0,0,0,0.7) 0%, transparent 100%);
}

/* Fine grain — static, plain opacity (no blend mode) so it never re-composites. */
.app-grain {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  opacity: 0.05;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-size: 160px 160px;
}

.app-vignette {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: radial-gradient(130% 110% at 50% 40%, transparent 58%, rgba(0,0,0,0.42) 100%);
}

@media (prefers-reduced-motion: reduce) {
  .app-aurora { animation: none; }
}
</style>
