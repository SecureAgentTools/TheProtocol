<template>
  <!--
    ViewAmbient — unified app-wide background ambient (2026-05-08 polish).
    Drop-in component: include at the top of any view's template, and
    content automatically sits above it (z-index 0, fixed positioning).

    Layers (back-to-front):
      .va-grid   — subtle 60×60 grid with slow drift animation
      .va-scan   — CRT-style horizontal scan-line overlay (the static "beam")
      .va-beam   — animated traveling-beam line (top→bottom, 8s cycle) — opt-in
      .va-glow-* — two radial glows (corner accents)

    Tones (--va-glow-1 / --va-glow-2 colors):
      default   — Federation pattern: violet (top-right) + theme accent (bottom-left)
      admin     — amber + theme accent (matches Canaries energy)
      security  — red + theme accent
      cyan      — pure theme-accent on both corners (subtler)
      sovereign — deep violet + crimson (sovereign-signature aesthetic) [§pass41, 2026-05-18]

    Theme-aware: all CSS uses `var(--nc-primary*)` so the Theme Studio's
    custom theme cycles correctly. No view-local color literals.

    Usage:
      <template>
        <div class="my-view">
          <ViewAmbient :beam="true" tone="default" />
          ...rest of view content (sits naturally above the ambient)...
        </div>
      </template>
  -->
  <div
    v-if="ui.ambientMode !== 'off'"
    class="va-ambient"
    :data-tone="tone || 'default'"
    :data-level="ui.ambientMode"
    aria-hidden="true"
  >
    <div class="va-grid"></div>
    <div class="va-scan"></div>
    <div v-if="beam !== false && ui.ambientMode === 'full'" class="va-beam"></div>
    <div class="va-glow va-glow-1"></div>
    <div class="va-glow va-glow-2"></div>
  </div>
</template>

<script setup lang="ts">
// §SETPOLISH (2026-07-27): the ambient layer is now governed by a single user
// preference (Settings → Preferences → Background & surfaces). 'off' unmounts
// the layer, 'subtle' drops the beam and halves the layer strength.
import { useUIStore } from '@/stores/ui'
const ui = useUIStore()

defineProps<{
  /** 'default' (violet+cyan, matches Federation) | 'admin' (amber+cyan,
   *  matches Canaries) | 'security' (red+cyan) | 'cyan' (cyan-only)
   *  | 'sovereign' (violet+crimson, matches sovereign-signature flares;
   *  §pass41 2026-05-18). */
  tone?: 'default' | 'admin' | 'security' | 'cyan' | 'sovereign'
  /** When true (default), renders the animated traveling beam. Set to
   *  false to disable on perf-sensitive views. */
  beam?: boolean
}>()
</script>

<style scoped>
.va-ambient {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}

/* Static grid — 60×60, theme-aware. §DESKCHROME (2026-08-28): the grid NEVER
   drifts — the perpetual background-position animation read as "the background
   is moving all the time" on every desktop view (Commander). Motion budget for
   'full' mode is the traveling beam only. */
.va-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(var(--nc-primary-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}

/* CRT-style horizontal scan-line overlay (every 3-4px) */
.va-scan {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0,
    transparent 3px,
    rgba(var(--nc-primary-rgb), 0.025) 3px,
    rgba(var(--nc-primary-rgb), 0.025) 4px
  );
}

/* Animated traveling beam — single horizontal line, top→bottom every 8s.
   The "beam traveling from top to bottom" Commander asked to keep. */
.va-beam {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb), 0.6) 50%,
    transparent 100%
  );
  filter: blur(1px);
  animation: va-beam-sweep 8s ease-in-out infinite;
}
@keyframes va-beam-sweep {
  0%   { top: -2%; opacity: 0; }
  10%  { opacity: 0.55; }
  50%  { opacity: 0.9; }
  90%  { opacity: 0.55; }
  100% { top: 102%; opacity: 0; }
}

/* Radial glows */
.va-glow {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  filter: blur(120px);
  opacity: 0.15;
}

/* Default tone — Federation pattern: violet top-right + theme-accent bottom-left */
.va-ambient[data-tone='default'] .va-glow-1 {
  top: -100px; right: -200px;
  background: radial-gradient(circle, #a855f7 0%, transparent 70%);
}
.va-ambient[data-tone='default'] .va-glow-2 {
  bottom: -200px; left: -200px;
  background: radial-gradient(circle, rgb(var(--nc-primary-rgb)) 0%, transparent 70%);
}

/* Admin tone — amber + accent (matches AdminCanaries energy) */
.va-ambient[data-tone='admin'] .va-glow-1 {
  top: -100px; right: -100px;
  width: 480px; height: 480px;
  background: radial-gradient(circle, rgb(var(--nc-primary-rgb)) 0%, transparent 70%);
  opacity: 0.18;
}
.va-ambient[data-tone='admin'] .va-glow-2 {
  bottom: -80px; left: -80px;
  width: 360px; height: 360px;
  background: radial-gradient(circle, rgba(255, 51, 102, 0.4) 0%, transparent 70%);
  opacity: 0.18;
}

/* Security tone — red + accent */
.va-ambient[data-tone='security'] .va-glow-1 {
  top: -100px; right: -200px;
  background: radial-gradient(circle, #ef4444 0%, transparent 70%);
}
.va-ambient[data-tone='security'] .va-glow-2 {
  bottom: -200px; left: -200px;
  background: radial-gradient(circle, rgb(var(--nc-primary-rgb)) 0%, transparent 70%);
}

/* Cyan tone — pure theme-accent on both corners */
.va-ambient[data-tone='cyan'] .va-glow-1 {
  top: -100px; right: -200px;
  background: radial-gradient(circle, rgb(var(--nc-primary-rgb)) 0%, transparent 70%);
}
.va-ambient[data-tone='cyan'] .va-glow-2 {
  bottom: -200px; left: -200px;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.5) 0%, transparent 70%);
}

/* §pass42 (2026-05-18) — Sovereign tone — deep violet (#7c3aed) + crimson
   (#ff3366) glow. Matches the sovereign-signature flare aesthetic
   (panopticon/weave/vellum). For frame/operator/sovereign-identity views.
   The corner glows + the underlying grid/scan are all violet-locked so the
   tone reads as violet+crimson, NOT "sovereign glows over cyan grid". The
   beam still cycles with --nc-primary-rgb (theme signal). */
.va-ambient[data-tone='sovereign'] {
  --va-line-rgb: 124, 58, 237;
}
.va-ambient[data-tone='sovereign'] .va-grid {
  background-image:
    linear-gradient(rgba(var(--va-line-rgb), 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--va-line-rgb), 0.04) 1px, transparent 1px);
}
.va-ambient[data-tone='sovereign'] .va-scan {
  background: repeating-linear-gradient(
    180deg,
    transparent 0,
    transparent 3px,
    rgba(var(--va-line-rgb), 0.03) 3px,
    rgba(var(--va-line-rgb), 0.03) 4px
  );
}
.va-ambient[data-tone='sovereign'] .va-glow-1 {
  top: -100px; right: -200px;
  background: radial-gradient(circle, #7c3aed 0%, transparent 70%);
  opacity: 0.28;
}
.va-ambient[data-tone='sovereign'] .va-glow-2 {
  bottom: -200px; left: -200px;
  background: radial-gradient(circle, #ff3366 0%, transparent 70%);
  opacity: 0.22;
}

/* Subtle level (§SETPOLISH) — half-strength layer, beam already unmounted.
   (Grid is static everywhere since §DESKCHROME, so no animation override needed.) */
.va-ambient[data-level='subtle'] { opacity: 0.5; }

/* Reduced-motion: disable beam animation (WCAG 2.3.3) */
@media (prefers-reduced-motion: reduce) {
  .va-beam { animation: none; opacity: 0.4; top: 50%; }
}
</style>
