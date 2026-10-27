<script setup lang="ts">
/**
 * The header strip's LED ticker (the default strip; Settings > Preferences > Header strip offers the still announcement
 * bar instead, AnnouncementBar.vue).
 *
 * §ALERTS header strip (2026-10-06, agentvault2-09). His words: "check why alerts are not connected to the header thing
 * where the broadcasts are displayed", then "i really like the led but polishing it would be cool additionally". What
 * changed:
 *  - ALERTS mode asked the Health Monitor's alerts route with an extra 'health' path segment, which does not exist (the
 *    route is /admin/prometheus-metrics,
 *    and even there the alerts were Prometheus's, which only scrapes here: empty by construction). A 404 on EVERY scroll
 *    loop, each one a global "Not Found / Not Found" toast, under a strip that read "NO ALERTS // MONITORING ACTIVE". It
 *    reads vmalert's alerts now (services/header/activeAlerts.ts: one shared poll, no global toasts), admins only;
 *  - BROADCASTS come from the notification store the bell reads (one read, one unread set) instead of a second fetch,
 *    and a failed read says so instead of "<node> // ONLINE";
 *  - a press on a message opens it (a broadcast in the bell's modal, an alert on the Health Monitor; a failed read
 *    retries); the badge switches mode and counts; hovering pauses the scroll; a keyboard can reach it;
 *  - the board: unlit dots behind the text (drawn once per resize, blitted), soft edges, and text the font has no glyph
 *    for is mapped (ä -> a, an em dash -> -) instead of vanishing.
 */
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useRegistryInfoStore } from '@/stores/registryInfo'
import { useAuthStore } from '@/stores/auth'
import { hasAdminFlag } from '@/composables/usePermissions'
import { useNotificationStore } from '@/stores/notifications'
import { useUIStore } from '@/stores/ui'
import { LED_GLYPHS } from '@/services/header/ledFont'
import {
  C_CYAN, alertStripItems, broadcastStripItems, normalizeLedText, type Rgb, type StripItem,
} from '@/services/header/headerStrip'
import { acquireActiveAlerts, activeAlerts, refreshActiveAlerts } from '@/services/header/activeAlerts'

const { t } = useI18n()
const tt = (key: string, fallback: string): string => t(key, fallback)
const router = useRouter()
const registryInfo = useRegistryInfoStore()
const authStore = useAuthStore()
const notif = useNotificationStore()
const uiStore = useUIStore()

// §pass66 (2026-05-22) — replace hardcoded "SOVEREIGN NODE" with the actual
// registry name from /federation/info. Renders correctly on each registry
// without needing rebuild — Frame A shows "REGISTRY-A", Frame B shows
// "FRAME-B", cloud-ops show "CLOUD-OP-OP-PARIS" etc. (uppercased for the
// LED matrix aesthetic). Fallback to "REGISTRY" if the store isn't loaded
// yet (no flash of "SOVEREIGN NODE" branding on a cloud-op login screen).
function nodeLabel(): string {
  return (registryInfo.registryName || 'REGISTRY').toUpperCase()
}

// ── State ──
const canvas = ref<HTMLCanvasElement | null>(null)
const container = ref<HTMLDivElement | null>(null)
// §bc1 T1.9 — persist last-chosen mode across reloads.
const LED_MODE_KEY = 'theprotocol:ledTickerMode'
function loadPersistedMode(): 'broadcasts' | 'alerts' {
  try {
    const raw = localStorage.getItem(LED_MODE_KEY)
    if (raw === 'broadcasts' || raw === 'alerts') return raw
  } catch (_) { /* ignore */ }
  return 'broadcasts'
}
const mode = ref<'broadcasts' | 'alerts'>(loadPersistedMode())
const paused = ref(false)

// D6-837 (agentvault2-69's find, 2026-10-25): GET /admin/alerts/active asks for admin_platform
// (routers/admin_health.get_active_alerts); asked whenever isAdmin held (any of the five admin flags), it refused a
// treasury-only or support-only admin on every page (403). The same rule as the route: is_admin or admin_platform.
const canReadAlerts = computed(() => hasAdminFlag(authStore.user, 'platform'))
// Alerts are an admin's view: the reader answers `hidden` for anyone the route refuses, who then has no alerts mode.
const canSeeAlerts = computed(() => canReadAlerts.value && activeAlerts.state !== 'hidden')
const shownMode = computed<'broadcasts' | 'alerts'>(() => (mode.value === 'alerts' && canSeeAlerts.value ? 'alerts' : 'broadcasts'))

const items = computed<StripItem[]>(() => (shownMode.value === 'alerts'
  ? alertStripItems(activeAlerts.state, activeAlerts.alerts, tt)
  // "no new broadcasts" only after a read said so: the list hydrated from localStorage is the last answer, not this one
  : broadcastStripItems(notif.items, { failed: notif.unreadFailed, loading: !notif.lastReadAt }, tt)))

const severeFiring = computed(() => activeAlerts.counts.page + activeAlerts.counts.critical)
const badgeCount = computed(() => (shownMode.value === 'alerts' ? activeAlerts.counts.firing : notif.items.length))
const badgeText = computed(() => {
  const label = shownMode.value === 'alerts' ? t('ledTicker.alerts', 'ALERTS') : t('ledTicker.broadcasts', 'BROADCASTS')
  return badgeCount.value > 0 ? `${label} ${badgeCount.value}` : label
})
const badgeClass = computed(() => {
  if (shownMode.value === 'broadcasts') return 'led-badge-cast'
  if (activeAlerts.state === 'unreadable') return 'led-badge-amber'
  if (severeFiring.value > 0) return 'led-badge-red'
  return activeAlerts.counts.firing > 0 ? 'led-badge-amber' : 'led-badge-alert'
})
// in broadcasts mode an admin still sees that alerts are firing: a dot on the badge, the count in its title
const alertDot = computed(() => (shownMode.value === 'broadcasts' && canSeeAlerts.value && activeAlerts.counts.firing > 0
  ? (severeFiring.value > 0 ? 'red' : 'amber') : ''))
const switchTitle = computed(() => {
  if (shownMode.value === 'alerts') return t('ledTicker.switchToBroadcasts', 'Click to switch to Broadcasts')
  const firing = activeAlerts.counts.firing
  return firing > 0
    ? `${firing} ${t('ledTicker.alertsFiringSwitch', 'alerts firing: click to switch to System Alerts')}`
    : t('ledTicker.switchToAlerts', 'Click to switch to System Alerts')
})
const srText = computed(() => items.value.map((i) => i.text).join('. '))
const boardTitle = computed(() => (shownMode.value === 'alerts'
  ? t('ledTicker.pressToOpenAlerts', 'Press to open the alerts')
  : t('ledTicker.pressToOpen', 'Press a message to open it')))

// LED config
const DOT_SIZE = 2
const DOT_GAP = 1
const DOT_PITCH = DOT_SIZE + DOT_GAP
const ROWS = 11
const SCROLL_SPEED = 1.2
const SEPARATOR: Rgb = [0, 80, 80]

// ── Types ──
type DotCol = { row: number; color: Rgb }[]
interface Segment { start: number; end: number; item: StripItem }

// ── Render state ──
let animFrame = 0
let scrollX = 0
let dotBuffer: DotCol[] = []
let segments: Segment[] = []
let builtFromStatusOnly = true
let pendingRebuild = false
let gridCanvas: HTMLCanvasElement | null = null

/*
 * §LITEBRIDGE polish 1 — THIS TICKER IS THE ONLY PER-FRAME WORK LEFT.
 *
 * Found by profiling the light bridge, which promises "no per-frame work" and
 * then sat at 88% `(program)` with `fillRect` the one JS entry above 1%. It was
 * not the bridge: this header ticker runs a requestAnimationFrame loop drawing
 * a few hundred rectangles a frame, on EVERY page, forever — including in a
 * hidden tab, including for someone who has just told us their machine cannot
 * afford the stage.
 *
 * Three states instead of one:
 *   hidden tab      -> stop entirely. Nobody is looking.
 *   reduced motion  -> ~5fps. The OS asked for less movement, not for a blank
 *                      strip: a ticker that stops scrolling stops being readable
 *                      past its first few words, so it crawls instead of freezing.
 *   otherwise       -> unchanged, 60fps.
 *
 * 🔴 §TICKERLAG-2 (2026-08-30, his report: "when i switch to light mode
 * broadcast fps really gets cut. its a big slow down") — `bridge.gfx === 'lite'`
 * USED TO BE READ HERE and no longer is. That key is set by Mission Control's
 * VIEW > LIGHT button, whose own tooltip says what it is for: "the light bridge:
 * no WebGL, no per-frame drawing". It is a statement about a 3D STAGE. This is a
 * 638x33 two-dimensional canvas in the app header, and coupling it to that
 * button dropped the chrome of EVERY VIEW to 5fps for anyone who had ever chosen
 * the light bridge once. Measured with a control: default 53-60fps, gfx=lite
 * **5.0fps**, restored 59.5fps. Measured cost of the canvas it was "saving":
 * ~0.4ms/frame, i.e. noise, in an interleaved A/B against removing it entirely.
 * A capability preference for one view is not a motion preference for the app.
 *
 * SCROLL_SPEED is scaled by the step so the text moves at the same speed on the
 * screen either way; only the number of frames drawn changes.
 */
const SLOW_MS = 200
let slowTimer: ReturnType<typeof setTimeout> | null = null
let motionQuery: MediaQueryList | null = null
function prefersLessMotion(): boolean {
  // The OS accessibility signal, and ONLY that. See §TICKERLAG-2 above.
  return !!motionQuery?.matches
}
/** Re-schedule the next frame under whichever policy currently applies. */
function scheduleFrame() {
  if (slowTimer) { clearTimeout(slowTimer); slowTimer = null }
  if (animFrame) { cancelAnimationFrame(animFrame); animFrame = 0 }
  if (typeof document !== 'undefined' && document.hidden) return   // resumed on visibilitychange
  // a paused board is a still picture: one frame was drawn, the next comes when the pointer leaves
  if (paused.value) return
  if (prefersLessMotion()) { slowTimer = setTimeout(() => { slowTimer = null; draw() }, SLOW_MS); return }
  animFrame = requestAnimationFrame(draw)
}
function onVisibility() { scheduleFrame() }
function onMotionChange() { scheduleFrame() }

function textToDots(text: string, color: Rgb): DotCol[] {
  const cols: DotCol[] = []
  for (const ch of normalizeLedText(text, LED_GLYPHS)) {
    const glyph = LED_GLYPHS[ch] || LED_GLYPHS[' ']
    for (let c = 0; c < glyph.length; c++) {
      const dots: DotCol[0] = []
      for (let r = 0; r < 7; r++) {
        if (glyph[c] & (1 << r)) dots.push({ row: r + 2, color })
      }
      cols.push(dots)
    }
    cols.push([]) // char gap
  }
  return cols
}

function makeSeparator(): DotCol[] {
  const cols: DotCol[] = [[], []]
  const mid: DotCol[0] = []
  for (let r = 3; r <= 7; r++) mid.push({ row: r, color: SEPARATOR })
  cols.push(mid)
  cols.push([])
  cols.push([])
  return cols
}

function buildBuffer() {
  const list: StripItem[] = items.value.length > 0
    ? items.value
    : [{ key: 'node', kind: 'status', text: nodeLabel(), color: C_CYAN }]

  dotBuffer = []
  segments = []
  const canvasW = canvas.value?.width || 800
  const padCols = Math.ceil(canvasW / DOT_PITCH) + 10

  // Start pad
  for (let i = 0; i < padCols; i++) dotBuffer.push([])

  for (let i = 0; i < list.length; i++) {
    const start = dotBuffer.length
    dotBuffer.push(...textToDots(list[i].text, list[i].color))
    segments.push({ start, end: dotBuffer.length, item: list[i] })
    if (i < list.length - 1) dotBuffer.push(...makeSeparator())
  }

  // End pad for seamless loop
  for (let i = 0; i < padCols; i++) dotBuffer.push([])
  builtFromStatusOnly = list.every((i) => i.kind === 'status')
  pendingRebuild = false
}

/**
 * The unlit board behind the text: one dim dot at every position, drawn ONCE per resize (and theme change) to an
 * offscreen canvas that each frame blits in a single drawImage. 2026-10-06: the grid is wanted now ("polishing it would
 * be cool"), drawn the way the §TICKERLAG note below says it must be: --nc-primary-rgb resolved here, never var() in a
 * canvas colour. One column wider than the board so the scroll's sub-dot offset never shows an edge.
 */
function buildGrid() {
  const cvs = canvas.value
  const ctr = container.value
  if (!cvs || !ctr || typeof document === 'undefined') { gridCanvas = null; return }
  const g = document.createElement('canvas')
  g.width = cvs.width + DOT_PITCH
  g.height = cvs.height
  const gx = g.getContext('2d')
  if (!gx) { gridCanvas = null; return }
  gx.fillStyle = '#05050a'
  gx.fillRect(0, 0, g.width, g.height)
  const rgb = (getComputedStyle(ctr).getPropertyValue('--nc-primary-rgb') || '').trim()
  gx.fillStyle = `rgba(${rgb || '0, 210, 210'}, 0.07)`
  // an unparseable colour is IGNORED by a canvas (fillStyle keeps the background): test the assignment, fall back
  if (gx.fillStyle === '#05050a') gx.fillStyle = 'rgba(0, 210, 210, 0.07)'
  for (let x = 0; x < g.width; x += DOT_PITCH) {
    for (let r = 0; r < ROWS; r++) gx.fillRect(x, r * DOT_PITCH, DOT_SIZE, DOT_SIZE)
  }
  gridCanvas = g
}

/** §TICKERLAG — eight strings for the life of the page (4 colours x 2 alphas). */
const COLOR_CACHE = new Map<number, [string, string]>()

function draw() {
  const cvs = canvas.value
  if (!cvs) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  const w = cvs.width
  const h = cvs.height
  const screenCols = Math.ceil(w / DOT_PITCH) + 1
  const startCol = Math.floor(scrollX / DOT_PITCH)
  const offsetPx = scrollX % DOT_PITCH

  // The board: the unlit grid (moves with the text, so a lit dot always sits on a grid position), or a plain clear
  if (gridCanvas) {
    ctx.drawImage(gridCanvas, -offsetPx, 0)
  } else {
    ctx.fillStyle = '#05050a'
    ctx.fillRect(0, 0, w, h)
  }

  // §TICKERLAG (2026-08-30) — THE "DIM BACKGROUND GRID" NEVER DREW ANYTHING.
  // `ctx.fillStyle` is a CSS <color>, and a canvas does not resolve `var()`:
  // per spec an unparseable value is IGNORED, so fillStyle kept the '#05050a'
  // set by the clear immediately above and the loop painted the background onto
  // the background. Verified in the browser, not read: assigning that exact
  // string leaves fillStyle === '#05050a'.
  // The cost was real even though the pixels were not — measured 214 cols x 11
  // rows = 2,354 fillStyle assignments (each parsing a string that fails) plus
  // 2,354 fillRect calls, EVERY FRAME, on every view, at dpr 1; a retina laptop
  // pays it twice over. Deleted rather than repaired: repairing it would ADD a
  // grid that has never been on screen, which is a design change, not a fix.
  // If the grid is wanted, resolve --nc-primary-rgb ONCE per resize and draw it
  // to an offscreen canvas, then blit that instead of 2,354 rects a frame.

  if (dotBuffer.length === 0) { scheduleFrame(); return }

  for (let sc = 0; sc < screenCols; sc++) {
    const dc = startCol + sc
    if (dc < 0 || dc >= dotBuffer.length) continue
    const col = dotBuffer[dc]
    if (!col) continue
    const px = sc * DOT_PITCH - offsetPx

    for (const dot of col) {
      const py = dot.row * DOT_PITCH
      const [r, g, b] = dot.color
      // §TICKERLAG — the colour strings are built from a four-entry palette and
      // two fixed alphas, so there are eight of them in the whole program; they
      // were being re-concatenated twice per lit dot per frame. Memoised.
      const key = r * 65536 + g * 256 + b
      let pair = COLOR_CACHE.get(key)
      if (!pair) { pair = [`rgba(${r}, ${g}, ${b}, 0.15)`, `rgba(${r}, ${g}, ${b}, 0.92)`]
                   COLOR_CACHE.set(key, pair) }
      // Glow
      ctx.fillStyle = pair[0]
      ctx.fillRect(px - 1, py - 1, DOT_SIZE + 2, DOT_SIZE + 2)
      // Core
      ctx.fillStyle = pair[1]
      ctx.fillRect(px, py, DOT_SIZE, DOT_SIZE)
    }
  }

  // Same pixels per SECOND in either mode; only the frame count changes. A paused board does not move.
  if (!paused.value) scrollX += prefersLessMotion() ? SCROLL_SPEED * (SLOW_MS / 16.7) : SCROLL_SPEED
  if (scrollX >= dotBuffer.length * DOT_PITCH) {
    scrollX = 0
    // §ALERTS: the data no longer refreshes per pass (that was the 404 on every loop); new content lands at the end
    // of a pass, so the text on screen never jumps mid-sentence
    if (pendingRebuild) buildBuffer()
  }

  scheduleFrame()
}

// ── Data: the store and the alert reader push; the board follows ──
const itemsSignature = computed(() => items.value.map((i) => `${i.key}|${i.text}`).join('\n'))
watch(itemsSignature, () => {
  // a status line (loading, a failure, "none") gives way at once, and so does anything at the start of a pass
  if (builtFromStatusOnly || scrollX < DOT_PITCH * 8) { buildBuffer(); scrollX = 0 } else { pendingRebuild = true }
})

function toggleMode() {
  mode.value = mode.value === 'broadcasts' ? 'alerts' : 'broadcasts'
}

watch(mode, (next) => {
  scrollX = 0
  try { localStorage.setItem(LED_MODE_KEY, next) } catch (_) { /* ignore */ }
  if (next === 'alerts') void refreshActiveAlerts()
  buildBuffer()
})

/** The item under a point on the board (or the nearest one within 12 columns), from the segments of the buffer. */
function itemAt(clientX: number): StripItem | null {
  const cvs = canvas.value
  if (!cvs) return null
  const rect = cvs.getBoundingClientRect()
  const x = (clientX - rect.left) * (cvs.width / Math.max(1, rect.width || cvs.width))
  const col = Math.floor((scrollX + x) / DOT_PITCH)
  let best: { d: number, item: StripItem } | null = null
  for (const seg of segments) {
    if (col >= seg.start && col < seg.end) return seg.item
    const d = col < seg.start ? seg.start - col : col - seg.end + 1
    if (d <= 12 && (!best || d < best.d)) best = { d, item: seg.item }
  }
  return best?.item ?? null
}

function openBell(broadcastId?: number) {
  try {
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell', { detail: { broadcastId } }))
  } catch (_) { /* ignore */ }
}

/** What a press does: open the broadcast, open the alerts, or retry the read that failed. */
function act(item: StripItem | null) {
  if (item?.retry === 'broadcasts') { void notif.fetchUnread(); return }
  if (item?.retry === 'alerts') { void refreshActiveAlerts(); return }
  if (item?.kind === 'broadcast' && item.broadcastId != null) { openBell(item.broadcastId); return }
  if (shownMode.value === 'alerts') { void router.push({ path: '/health-monitor', query: { tab: 'prometheus' } }); return }
  openBell()
}
function onBoardClick(ev: MouseEvent) { act(itemAt(ev.clientX)) }
function onBoardKey() { act(items.value[0] ?? null) }

function resizeCanvas() {
  const cvs = canvas.value
  const ctr = container.value
  if (!cvs || !ctr) return
  cvs.width = ctr.clientWidth
  cvs.height = ROWS * DOT_PITCH
  buildGrid()
  buildBuffer()
}

// the theme's colour moved: the unlit dots follow (the class lands first, so read it on the next tick)
watch(() => uiStore.brandTheme, () => { void nextTick(buildGrid) })
watch(paused, (p) => { if (!p) scheduleFrame() })

// alerts are polled for admins only, once however many surfaces show them
let releaseAlerts: (() => void) | null = null
watch(() => canReadAlerts.value, (admin) => {
  if (admin && !releaseAlerts) releaseAlerts = acquireActiveAlerts()
  if (!admin && releaseAlerts) { releaseAlerts(); releaseAlerts = null }
}, { immediate: true })

// ── Lifecycle ──
onMounted(() => {
  resizeCanvas()
  // §pass66 — the registry name arrives from /federation/info; the placeholder line uses it once it lands
  registryInfo.load().then(() => { if (builtFromStatusOnly) buildBuffer() }).catch(() => { /* the label stays generic */ })
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionQuery.addEventListener?.('change', onMotionChange)
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('resize', resizeCanvas)
  scheduleFrame()
})

onUnmounted(() => {
  if (animFrame) cancelAnimationFrame(animFrame)
  if (slowTimer) { clearTimeout(slowTimer); slowTimer = null }
  motionQuery?.removeEventListener?.('change', onMotionChange)
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('resize', resizeCanvas)
  if (releaseAlerts) { releaseAlerts(); releaseAlerts = null }
})
</script>

<template>
  <div
    ref="container"
    class="led-wrap"
    data-testid="led-ticker"
    :data-mode="shownMode"
    @pointerenter="paused = true"
    @pointerleave="paused = false"
  >
    <div
      class="led-board"
      role="button"
      tabindex="0"
      data-testid="led-board"
      :title="boardTitle"
      :aria-label="`${shownMode === 'alerts' ? t('ledTicker.alerts', 'ALERTS') : t('ledTicker.broadcasts', 'BROADCASTS')}: ${items[0]?.text || ''}`"
      @click.stop="onBoardClick"
      @keydown.enter.prevent="onBoardKey"
      @keydown.space.prevent="onBoardKey"
    >
      <canvas ref="canvas" class="led-canvas" aria-hidden="true" />
    </div>
    <!-- the canvas is pixels: this is the text, for a screen reader and for a test -->
    <span class="led-sr" aria-live="polite" data-testid="led-text">{{ srText }}</span>
    <button
      v-if="canSeeAlerts"
      type="button"
      class="led-badge"
      :class="badgeClass"
      data-testid="led-badge"
      :title="switchTitle"
      :aria-label="switchTitle"
      @click.stop="toggleMode"
    >
      <span v-if="alertDot" class="led-badge-dot" :class="'led-badge-dot-' + alertDot" data-testid="led-alert-dot" aria-hidden="true" />{{ badgeText }}
    </button>
    <span v-else class="led-badge" :class="badgeClass" data-testid="led-badge">{{ badgeText }}</span>
  </div>
</template>

<style scoped>
.led-wrap {
  position: relative;
  height: 33px;
  width: 100%;
  border-radius: 5px;
  overflow: hidden;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  background: #05050a;
  box-shadow:
    inset 0 1px 4px rgba(0, 0, 0, 0.6),
    0 0 6px rgba(var(--nc-primary-rgb), 0.03);
  transition: border-color 0.2s;
}
.led-wrap:hover,
.led-wrap:focus-within {
  border-color: rgba(var(--nc-primary-rgb), 0.22);
}
.led-board {
  position: absolute;
  inset: 0;
  cursor: pointer;
  outline: none;
}
.led-board:focus-visible {
  box-shadow: inset 0 0 0 1px rgba(var(--nc-primary-rgb), 0.55);
}
.led-canvas {
  display: block;
  width: 100%;
  height: 100%;
  image-rendering: pixelated;
  /* text fades in at the right edge and out at the left, like a board seen through a bezel */
  -webkit-mask-image: linear-gradient(to right, transparent 0, #000 22px, #000 calc(100% - 22px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0, #000 22px, #000 calc(100% - 22px), transparent 100%);
}
.led-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
/* §CHATPOLISH (2026-08-30) — this chip sat over the scrolling canvas on a 6%
   tint, so the marquee ran THROUGH it: measured on four of five desktop
   screenshots, "No new broadcas|BROADCASTS" overlapping into glyph soup. The
   canvas keeps its full width (the scroll wraps on it); the chip now paints an
   opaque plate over the panel background with a short fade on its leading edge,
   so text passes BEHIND it and dissolves instead of colliding. */
.led-badge {
  position: absolute;
  top: 3px;
  right: 4px;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #05050a;
  box-shadow: -12px 0 12px -6px #05050a;
  font-size: 7.5px;
  font-weight: 800;
  letter-spacing: 0.12em;
  font-family: 'Fira Code', monospace;
  padding: 2px 5px;
  border-radius: 3px;
  border: 1px solid transparent;
  line-height: 1.2;
}
button.led-badge {
  cursor: pointer;
  pointer-events: auto;
}
button.led-badge:hover,
button.led-badge:focus-visible {
  border-color: currentColor;
  outline: none;
}
span.led-badge {
  pointer-events: none;
}
.led-badge-cast {
  color: rgba(var(--nc-primary-rgb), 0.7);
  /* background-IMAGE, not background: the shorthand would drop the opaque
     plate above and put the marquee back through the chip. */
  background-image: linear-gradient(rgba(var(--nc-primary-rgb), 0.06),
                                    rgba(var(--nc-primary-rgb), 0.06));
}
.led-badge-alert {
  color: rgba(16, 220, 129, 0.75);
  background-image: linear-gradient(rgba(16, 220, 129, 0.06),
                                    rgba(16, 220, 129, 0.06));
}
.led-badge-amber {
  color: rgba(245, 180, 30, 0.9);
  background-image: linear-gradient(rgba(245, 180, 30, 0.08), rgba(245, 180, 30, 0.08));
}
.led-badge-red {
  color: rgba(255, 90, 90, 0.95);
  background-image: linear-gradient(rgba(240, 70, 70, 0.1), rgba(240, 70, 70, 0.1));
}
.led-badge-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.led-badge-dot-red {
  background: #f04646;
  box-shadow: 0 0 4px #f04646;
}
.led-badge-dot-amber {
  background: #f5b41e;
  box-shadow: 0 0 4px #f5b41e;
}
@media (prefers-reduced-motion: no-preference) {
  .led-badge-dot-red { animation: led-dot-pulse 1.6s ease-in-out infinite; }
}
@keyframes led-dot-pulse {
  50% { opacity: 0.35; }
}
</style>
