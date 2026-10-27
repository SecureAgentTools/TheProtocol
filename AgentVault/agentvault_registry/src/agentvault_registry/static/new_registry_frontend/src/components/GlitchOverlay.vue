<!--
  GlitchOverlay.vue — §GLITCH2 (2026-09-02) — the landing page's on-load distortion, rebuilt.

  His word: "much more realistic distortion, like joining a hostile website; the overall length is good;
  just the visual on load; make it glorious." The TIMELINE is untouched (`useThemeFlash`: three anomaly
  blips, an accelerating neural↔sovereign oscillation, a lock at peak, a decay — ~4.7 s). What this
  component draws changed:

    · a live NOISE field (a 192×108 buffer refilled every frame, scaled up pixelated) with horizontal
      TEAR bands sliced out and shifted while the signal fights
    · the whole page JITTERS and SKEWS in held bursts (2–3 frames per tear, not a vibration) and its
      chromatic split widens to 10 px with a random sign, plus a contrast/saturation push
    · a VHS TRACKING BAR rolls down the screen on every blip (mix-blend difference: it INVERTS what it
      crosses instead of painting over it)
    · the LOCK is a one-frame full inversion followed by a 120 ms blackout — the moment the hostile
      signal wins — then the decay
    · the hero heading and lead TEAR (clip-path band animations on the real elements; the text is never
      touched, nothing joins the text run — PART 1)
    · a corner READOUT flickers hex during the fight (`aria-hidden`)

  Cost: the noise buffer is 20k pixels a frame; the page transform rides the layer the existing filter
  already promotes. `prefers-reduced-motion` switches the whole thing off (the composable short-circuits
  before the first step, and the CSS below is a second guard). Every layer is `pointer-events: none`
  and `aria-hidden`.
-->
<template>
  <div class="gx" aria-hidden="true" :data-phase="phase" :class="{ 'gx-on': intensity > 0 }">
    <canvas ref="noiseEl" class="gx-noise" width="320" height="180" :style="{ opacity: noiseOpacity }"></canvas>
    <div class="glitch-scanlines" :class="{ 'glitch-visible': intensity > 0 }" :style="scanStyle"></div>
    <div class="gx-track" :class="{ 'gx-track--roll': trackRolling }" :style="{ opacity: trackOpacity }"></div>
    <div class="gx-flash" :class="{ 'gx-flash--invert': flashStage === 'invert', 'gx-flash--black': flashStage === 'black' }"></div>
    <div class="gx-readout" v-if="readout" :style="{ opacity: readoutOpacity }">{{ readout }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import type { GlitchPhase } from '@/composables/useThemeFlash'

const props = withDefaults(defineProps<{ intensity: number; phase?: GlitchPhase }>(), { phase: 'idle' })

const CHROMATIC_CLASS = 'glitch-chromatic'
const ACTIVE_CLASS = 'gx-active'
const MAX_CHROMA_OFFSET_PX = 10
const MAX_JITTER_PX = 9
const MAX_SKEW_DEG = 1.4

const noiseEl = ref<HTMLCanvasElement | null>(null)
const trackRolling = ref(false)
const flashStage = ref<'none' | 'invert' | 'black'>('none')
const readout = ref('')

function getAppRoot(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  return document.getElementById('app')
}
function clamp01(v: number): number { return Math.max(0, Math.min(1, v)) }
function rnd(a: number, b: number): number { return a + Math.random() * (b - a) }
function sign(): number { return Math.random() < 0.5 ? -1 : 1 }

// ── noise + tears (one buffer, refilled per frame while active) ──
let raf: number | null = null
let holdFrames = 0
let heldDx = 0, heldDy = 0, heldSkew = 0
let noiseBuf: ImageData | null = null
let noiseCtx: CanvasRenderingContext2D | null = null

function fillNoise(v: number, tearing: boolean): void {
  const c = noiseEl.value
  if (!c) return
  if (!noiseCtx) { noiseCtx = c.getContext('2d', { alpha: true }); if (!noiseCtx) return }
  if (!noiseBuf) noiseBuf = noiseCtx.createImageData(c.width, c.height)
  const d = new Uint32Array(noiseBuf.data.buffer)
  const w = c.width, h = c.height
  // grain: mostly dark, a few hot pixels; the alpha follows intensity so the field fades with the signal
  // sparse grain: most cells stay dark (transparent), ~22% carry a gray, a few burn white — so the page
  // shows THROUGH the static; the tear bands below are what reads as a hostile signal
  const a = Math.round(110 + 120 * v)
  for (let i = 0; i < d.length; i++) {
    const r = Math.random()
    if (r < 0.78) { d[i] = 0; continue }
    const g = r > 0.985 ? 255 : (60 + ((Math.random() * 150) | 0))
    d[i] = (a << 24) | (g << 16) | (g << 8) | g
  }
  noiseCtx.putImageData(noiseBuf, 0, 0)
  if (tearing) {
    // slice 2–7 horizontal bands and shift them: the classic torn-sync look, drawn on the noise so it
    // reads as the SIGNAL tearing, not the page's layout breaking (the page shift is separate, below)
    const bands = 2 + ((Math.random() * 6) | 0)
    for (let b = 0; b < bands; b++) {
      const y = (Math.random() * h) | 0
      const bh = 1 + ((Math.random() * (3 + v * 9)) | 0)
      const dx = Math.round(sign() * rnd(2, 4 + v * 18))
      try { noiseCtx.drawImage(c, 0, y, w, bh, dx, y, w, bh) } catch { /* a detached canvas */ }
      // a bright seam on the tear line
      noiseCtx.fillStyle = `rgba(255,255,255,${(0.25 + v * 0.5).toFixed(2)})`
      noiseCtx.fillRect(0, y, w, 1)
    }
  }
}

function driveFrame(): void {
  raf = null
  const v = clamp01(props.intensity)
  const root = getAppRoot()
  if (v <= 0 || !root) { resetRoot(); return }
  const fighting = props.phase === 'rapid' || props.phase === 'lock'
  fillNoise(v, fighting || props.phase === 'blip')
  // page jitter/skew in HELD bursts: 2–3 frames per tear so it reads as tearing, not vibration
  if (fighting) {
    if (holdFrames <= 0) {
      holdFrames = 2 + ((Math.random() * 2) | 0)
      heldDx = Math.random() < 0.35 ? 0 : sign() * rnd(1, MAX_JITTER_PX * v)
      heldDy = Math.random() < 0.6 ? 0 : sign() * rnd(0.5, 3 * v)
      heldSkew = Math.random() < 0.5 ? 0 : sign() * rnd(0.2, MAX_SKEW_DEG * v)
    }
    holdFrames--
  } else { heldDx = 0; heldDy = 0; heldSkew = 0; holdFrames = 0 }
  const chroma = (props.phase === 'idle' ? 0 : rnd(0.4, 1) * MAX_CHROMA_OFFSET_PX * v) * (fighting && Math.random() < 0.3 ? -1 : 1)
  root.style.setProperty('--chroma-offset', `${chroma.toFixed(2)}px`)
  root.style.setProperty('--chroma-opacity', v.toFixed(3))
  root.style.setProperty('--gx-dx', `${heldDx.toFixed(2)}px`)
  root.style.setProperty('--gx-dy', `${heldDy.toFixed(2)}px`)
  root.style.setProperty('--gx-skew', `${heldSkew.toFixed(2)}deg`)
  root.style.setProperty('--gx-contrast', (1 + 0.18 * v).toFixed(3))
  root.style.setProperty('--gx-saturate', (1 + 0.35 * v).toFixed(3))
  if (!root.classList.contains(CHROMATIC_CLASS)) root.classList.add(CHROMATIC_CLASS)
  root.classList.toggle(ACTIVE_CLASS, v > 0.3)
  if (fighting) readout.value = `SIGNAL // RESYNC 0x${((Math.random() * 0xffff) | 0).toString(16).toUpperCase().padStart(4, '0')}  ${(v * 100).toFixed(0)}%`
  else if (props.phase === 'decay') readout.value = 'SIGNAL // LOCKED'
  else readout.value = ''
  raf = requestAnimationFrame(driveFrame)
}

function resetRoot(): void {
  const root = getAppRoot()
  if (!root) return
  root.classList.remove(CHROMATIC_CLASS, ACTIVE_CLASS)
  for (const k of ['--chroma-offset', '--chroma-opacity', '--gx-dx', '--gx-dy', '--gx-skew', '--gx-contrast', '--gx-saturate']) root.style.removeProperty(k)
  readout.value = ''
}

// ── the tracking bar rolls on every blip and keeps rolling through the fight ──
let trackTimer: ReturnType<typeof setTimeout> | null = null
function rollTrack(): void {
  trackRolling.value = false
  // restart the CSS animation on the next frame
  requestAnimationFrame(() => { trackRolling.value = true })
  if (trackTimer) clearTimeout(trackTimer)
  trackTimer = setTimeout(() => { trackRolling.value = false }, 760)
}

// ── the lock: one inverted frame, then a blackout, then the decay ──
let flashTimer: ReturnType<typeof setTimeout> | null = null
let lockedOnce = false
function fireLock(): void {
  if (lockedOnce) return
  lockedOnce = true
  flashStage.value = 'invert'
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    flashStage.value = 'black'
    flashTimer = setTimeout(() => { flashStage.value = 'none' }, 120)
  }, 70)
}

watch(() => props.intensity, (v) => {
  if (v > 0 && raf === null) raf = requestAnimationFrame(driveFrame)
  if (v <= 0 && raf !== null) { cancelAnimationFrame(raf); raf = null; resetRoot() }
  if (v <= 0) lockedOnce = false
}, { immediate: true })

watch(() => props.phase, (ph, prev) => {
  if (ph === 'blip' && props.intensity > 0) rollTrack()
  if (ph === 'rapid' && prev !== 'rapid') rollTrack()
  if (ph === 'lock') fireLock()
})

onBeforeUnmount(() => {
  if (raf !== null) cancelAnimationFrame(raf)
  if (trackTimer) clearTimeout(trackTimer)
  if (flashTimer) clearTimeout(flashTimer)
  resetRoot()
})

const noiseOpacity = computed(() => (clamp01(props.intensity) ** 1.5 * 0.34).toFixed(3))
const trackOpacity = computed(() => (0.35 + clamp01(props.intensity) * 0.55).toFixed(3))
const readoutOpacity = computed(() => (0.45 + clamp01(props.intensity) * 0.55).toFixed(3))
const scanStyle = computed(() => {
  const v = clamp01(props.intensity)
  return { '--scanline-opacity': (v * 0.45).toFixed(3), '--scanline-gap': `${(6 - v * 4).toFixed(2)}px` } as Record<string, string>
})
</script>

<style>
/* Global on purpose: several rules target #app (a sibling) and the hero's own elements. */
.gx { position: fixed; inset: 0; pointer-events: none; z-index: 9998; }
.gx-noise { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; image-rendering: pixelated; mix-blend-mode: screen;
  transition: opacity 120ms linear; }
.glitch-scanlines { position: absolute; inset: 0; opacity: 0;
  background-image: repeating-linear-gradient(0deg, rgba(255, 60, 60, var(--scanline-opacity, 0)) 0px, rgba(255, 60, 60, var(--scanline-opacity, 0)) 1px, transparent 1px, transparent var(--scanline-gap, 4px));
  mix-blend-mode: screen; transition: opacity 160ms linear; }
.glitch-scanlines.glitch-visible { opacity: 1; }
/* the tracking bar: a band that INVERTS what it crosses, rolling top → bottom */
.gx-track { position: absolute; left: -4%; right: -4%; top: -14vh; height: 11vh; opacity: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.85) 35%, rgba(255,255,255,1) 50%, rgba(255,255,255,.85) 65%, rgba(255,255,255,0) 100%);
  mix-blend-mode: difference; transform: translateY(-14vh) skewY(-1.2deg); }
.gx-track--roll { animation: gx-roll 720ms cubic-bezier(.4,.05,.6,1) 1 forwards; }
@keyframes gx-roll { 0% { transform: translateY(-14vh) skewY(-1.2deg); } 60% { transform: translateY(70vh) skewY(.8deg); } 100% { transform: translateY(118vh) skewY(-.6deg); } }
/* the lock: an inverted frame, then black */
.gx-flash { position: absolute; inset: 0; opacity: 0; background: #fff; mix-blend-mode: difference; }
.gx-flash--invert { opacity: 1; }
.gx-flash--black { opacity: .92; background: #000; mix-blend-mode: normal; transition: opacity 60ms linear; }
/* the corner readout */
.gx-readout { position: absolute; right: 18px; bottom: 16px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 11px; letter-spacing: .14em;
  color: rgba(255, 70, 70, .95); text-shadow: 0 0 8px rgba(255,40,40,.8), 2px 0 0 rgba(0,229,255,.5); }
/* the page: chromatic split + a held jitter/skew + a contrast/saturation push */
#app.glitch-chromatic {
  transform: translate(var(--gx-dx, 0px), var(--gx-dy, 0px)) skewX(var(--gx-skew, 0deg));
  filter:
    contrast(var(--gx-contrast, 1)) saturate(var(--gx-saturate, 1))
    drop-shadow(var(--chroma-offset, 0px) 0 0 rgba(255, 55, 55, calc(var(--chroma-opacity, 0) * 0.65)))
    drop-shadow(calc(-1 * var(--chroma-offset, 0px)) 0 0 rgba(55, 220, 255, calc(var(--chroma-opacity, 0) * 0.6)));
  transform-origin: 50% 0;
  will-change: filter, transform;
}
/* the hero tears: band clips on the REAL heading and lead; the text is untouched */
#app.gx-active .lp-h1 { animation: gx-tear-h1 140ms steps(1) infinite; }
#app.gx-active .lp-lead { animation: gx-tear-lead 210ms steps(1) infinite; }
@keyframes gx-tear-h1 {
  0%   { clip-path: inset(0 0 0 0); transform: translateX(0); }
  20%  { clip-path: inset(12% 0 55% 0); transform: translateX(-9px); }
  40%  { clip-path: inset(0 0 0 0); transform: translateX(0); }
  60%  { clip-path: inset(58% 0 6% 0); transform: translateX(11px); }
  75%  { clip-path: inset(30% 0 30% 0); transform: translateX(-5px) skewX(6deg); }
  90%  { clip-path: inset(0 0 0 0); transform: translateX(0); }
  100% { clip-path: inset(0 0 0 0); transform: translateX(0); }
}
@keyframes gx-tear-lead {
  0%   { clip-path: inset(0 0 0 0); transform: translateX(0); opacity: 1; }
  30%  { clip-path: inset(40% 0 20% 0); transform: translateX(7px); opacity: .85; }
  55%  { clip-path: inset(0 0 0 0); transform: translateX(0); opacity: 1; }
  80%  { clip-path: inset(5% 0 70% 0); transform: translateX(-6px); opacity: .9; }
  100% { clip-path: inset(0 0 0 0); transform: translateX(0); opacity: 1; }
}
/* accessibility: reduced motion turns every layer off even if the composable's guard were missed */
@media (prefers-reduced-motion: reduce) {
  .gx { display: none !important; }
  #app.glitch-chromatic { filter: none !important; transform: none !important; }
  #app.gx-active .lp-h1, #app.gx-active .lp-lead { animation: none !important; clip-path: none !important; }
}
</style>
