<template>
  <!--
    §BRIDGE R14.5 — THE READOUT HE CAN SCREENSHOT.

    Why this exists: across P2, R11 and R13 he reported "it lags" and "the black
    sphere", and every one of those rounds cost me measurement I could not do
    from here. This box has no GPU: swiftshader renders every canvas on the CPU,
    so the §8 wall-clock budgets are not measurable on this machine at all. The
    numbers that matter live on HIS hardware, and until now the only way to read
    them was a console call he would have to type.

    So: a dev-gated strip that turns an adjective into a number, plus COPY, so a
    report arrives as data. Nothing here is new measurement — every field is a
    counter `bridgeStats()` already computed (canvas:4943). This is a display.

    Labels are deliberately NOT i18n'd: this renders only behind
    `?bridgedebug=1`, it is an instrument panel, and putting "p50" through seven
    locale bundles would be ceremony, not translation.
  -->
  <div v-if="on" class="bph" data-testid="bridge-perf-hud">
    <div class="bph-hdr">
      <span class="bph-title">BRIDGE PERF</span>
      <button type="button" class="bph-copy" data-testid="bph-copy" title="Copy this readout as text" @click="copy">
        {{ copied ? 'COPIED' : 'COPY' }}
      </button>
    </div>

    <!-- The stage seam can be genuinely absent (no WebGL, stage unmounted).
         Zeros would read as "nothing is happening", which is a different claim
         from "I cannot see". Say which one it is. -->
    <p v-if="!stageSeen" class="bph-absent" data-testid="bph-absent">
      stage seam absent &mdash; no numbers to report (WebGL off, or the stage is not mounted)
    </p>

    <template v-else>
      <div class="bph-row">
        <span class="bph-k">RENDER</span>
        <span class="bph-v" :class="renderClass">p50 {{ fmt(r.p50) }}</span>
        <span class="bph-v">p90 {{ fmt(r.p90) }}</span>
        <span class="bph-v">max {{ fmt(r.max) }}</span>
        <span class="bph-n">n={{ r.n }}</span>
      </div>
      <div class="bph-row">
        <span class="bph-k">STAGE</span>
        <span class="bph-v">stars {{ s.agentSprites ?? '?' }}</span>
        <span class="bph-v">pop {{ s.density?.drawn ?? '?' }}</span>
        <span class="bph-v">verbs {{ s.active ?? '?' }}/{{ s.poolCap ?? '?' }}</span>
        <span class="bph-v" :class="{ 'bph-warn': (s.droppedForPool || 0) > 0 }">drop {{ s.droppedForPool ?? '?' }}</span>
      </div>
      <div class="bph-row">
        <span class="bph-k">SCENERY</span>
        <span class="bph-v">neb {{ s.territory?.nebulae ?? '?' }}</span>
        <span class="bph-v">lanes {{ s.territory?.lanesDrawn ?? '?' }}</span>
        <span class="bph-v">atmos {{ atmos }}</span>
      </div>
      <div class="bph-row">
        <!-- The 866-row leak in P2 was invisible until something counted the
             DOM. It is counted here forever. -->
        <span class="bph-k">DOM</span>
        <span class="bph-v" :class="{ 'bph-warn': dom.ledger > 60 }">ledger {{ dom.ledger }}</span>
        <span class="bph-v" :class="{ 'bph-warn': dom.fleet > 60 }">fleet {{ dom.fleet }}</span>
      </div>
      <div class="bph-row">
        <span class="bph-k">STREAM</span>
        <!-- A rate needs a window, and the window has to be stated while it is
             still short: the pulse bar's rule, same reason. -->
        <span class="bph-v">{{ rate === null ? '--' : rate + '/min' }}</span>
        <span class="bph-n">over {{ windowLabel }}</span>
        <span class="bph-v">seen {{ seen }}</span>
      </div>
      <div class="bph-row">
        <span class="bph-k">GFX</span>
        <span class="bph-v">dpr {{ s.pixelRatio ?? '?' }}</span>
        <span class="bph-v">composer {{ s.usesComposer ? 'ON' : 'off' }}</span>
        <span class="bph-v">reduced {{ s.reducedMotion ? 'ON' : 'off' }}</span>
        <span class="bph-v">mode {{ s.mode ?? '?' }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

const on = ref(false)
const s = ref<any>({})
const stageSeen = ref(false)
const dom = ref({ ledger: 0, fleet: 0 })
const seen = ref(0)
const rate = ref<number | null>(null)
const copied = ref(false)
const atmos = ref('?')

let timer: any = null
let copyTimer: any = null
/** First sample of the session, so the rate window is honest about its length. */
let firstAt = 0
let firstSeen = 0

const r = computed(() => {
  const m = s.value?.renderMs
  return m && typeof m === 'object' ? m : { n: 0, p50: null, p90: null, max: null }
})

/** 16.7ms is one frame at 60fps: over it, the stage is the bottleneck. */
const renderClass = computed(() => {
  const p = r.value.p50
  if (typeof p !== 'number') return ''
  if (p > 16.7) return 'bph-bad'
  if (p > 11) return 'bph-warn'
  return 'bph-good'
})

const windowLabel = computed(() => {
  if (!firstAt) return '--'
  const secs = Math.round((Date.now() - firstAt) / 1000)
  return secs < 90 ? `${secs}s` : `${Math.round(secs / 60)}m`
})

function fmt(v: any): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '--'
}

function sample(): void {
  try {
    // The seam is `__bridge.stats()`. It is NOT `bridgeStats` — that is the name
    // of the method BridgeStage exposes to its parent, which the debug hook
    // republishes under a different key. Getting this wrong does not throw: the
    // optional chain yields undefined and the panel honestly reports "absent",
    // which looks exactly like a stage that failed to mount. Verified live.
    const st = (window as any).__bridge?.stats?.()
    if (st && typeof st === 'object') { s.value = st; stageSeen.value = true }
    else stageSeen.value = false
  } catch { stageSeen.value = false }

  try {
    dom.value = {
      ledger: document.querySelectorAll('.blg-row').length,
      fleet: document.querySelectorAll('.bfl-line').length,
    }
  } catch { /* the count is the only casualty */ }

  try {
    const stream = (window as any).__bridgeStream?.()
    const n = Number(stream?.totalEvents)
    if (Number.isFinite(n)) {
      seen.value = n
      if (!firstAt) { firstAt = Date.now(); firstSeen = n }
      const mins = (Date.now() - firstAt) / 60000
      // Below ~8s the divisor is small enough to invent a spectacular rate out
      // of two events. Report nothing rather than a number that is noise.
      rate.value = mins > 0.13 ? Math.round((n - firstSeen) / mins) : null
    }
  } catch { /* leave the last honest reading */ }

  try {
    atmos.value = String(localStorage.getItem('bridge.atmosphere') || 'subtle')
  } catch { atmos.value = '?' }
}

function asText(): string {
  const m = r.value
  return [
    `BRIDGE PERF  ${new Date().toISOString()}`,
    stageSeen.value ? '' : 'stage seam ABSENT (no WebGL, or stage not mounted)',
    `render  p50=${fmt(m.p50)} p90=${fmt(m.p90)} max=${fmt(m.max)} n=${m.n}`,
    `stage   stars=${s.value?.agentSprites} pop=${s.value?.density?.drawn} verbs=${s.value?.active}/${s.value?.poolCap} dropped=${s.value?.droppedForPool}`,
    `scenery nebulae=${s.value?.territory?.nebulae} lanes=${s.value?.territory?.lanesDrawn} atmosphere=${atmos.value}`,
    `dom     ledgerRows=${dom.value.ledger} fleetRows=${dom.value.fleet}`,
    `stream  rate=${rate.value === null ? 'n/a' : rate.value + '/min'} over=${windowLabel.value} seen=${seen.value}`,
    `gfx     dpr=${s.value?.pixelRatio} composer=${s.value?.usesComposer} reduced=${s.value?.reducedMotion} mode=${s.value?.mode}`,
  ].filter(Boolean).join('\n')
}

async function copy(): Promise<void> {
  const text = asText()
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Clipboard is permissioned and can simply refuse. A silent failure would
    // be the worst outcome for a button whose whole job is handing him text.
    try {
      const ta = document.createElement('textarea')
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
      document.body.appendChild(ta); ta.select(); document.execCommand('copy')
      document.body.removeChild(ta)
    } catch { /* nothing left to try */ }
  }
  copied.value = true
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copied.value = false }, 1400)
}

onMounted(() => {
  try { on.value = new URLSearchParams(window.location.search).has('bridgedebug') } catch { on.value = false }
  if (!on.value) return
  sample()
  timer = setInterval(sample, 1000)
})
onUnmounted(() => { clearInterval(timer); clearTimeout(copyTimer) })

defineExpose({ asText })
</script>

<style scoped>
/* Docks INSIDE the stage column and bottom-left, because the ledger lives in a
   rail and his standing instruction is that nothing covers the live ledger. */
.bph {
  /* TOP-left, not bottom-left. Measured on the canary: at bottom-left this box
     (389x141) landed at x609-998 y695-836 and the MAP restore control sits at
     x762-1093 y790-833 — `elementFromPoint` at the restore's own centre
     returned `.bph-v`, so the debug overlay was swallowing the click that
     brings the panels back. R11 #2 existed precisely to stop that control being
     unreachable, and I made it unreachable again with an instrument. The stage
     column's top-left is empty; the bottom is where the app puts things. */
  position: absolute;
  left: 0.75rem;
  top: 0.75rem;
  z-index: 6;
  pointer-events: auto;
  min-width: 21rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.14));
  border-radius: 6px;
  background: var(--nc-elevated, rgba(10, 14, 20, 0.86));
  backdrop-filter: none;   /* P2: never over a repainting canvas. */
  font-family: var(--nc-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.68rem;
  line-height: 1.5;
  color: var(--nc-text-secondary, #9fb0c0);
}
.bph-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem; }
.bph-title { letter-spacing: 0.14em; color: var(--nc-text-primary, #dbe6f0); font-size: 0.62rem; }
.bph-copy {
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.18));
  background: transparent; color: var(--nc-text-secondary, #9fb0c0);
  border-radius: 4px; padding: 0.1rem 0.45rem; cursor: pointer;
  font: inherit; letter-spacing: 0.1em;
  min-height: 20px;   /* R11 polish: 20px is the floor for a hit target. */
}
.bph-copy:hover { color: var(--nc-text-primary, #dbe6f0); border-color: var(--nc-primary, #64ffda); }
.bph-absent { margin: 0; color: var(--nc-warning, #ffb74d); }
.bph-row { display: flex; gap: 0.55rem; align-items: baseline; white-space: nowrap; }
.bph-k { width: 4.4rem; flex: none; color: var(--nc-text-muted, #6b7d8f); letter-spacing: 0.08em; }
.bph-v { font-variant-numeric: tabular-nums; }
.bph-n { color: var(--nc-text-muted, #6b7d8f); }
.bph-good { color: var(--nc-success, #64ffda); }
.bph-warn { color: var(--nc-warning, #ffb74d); }
.bph-bad { color: var(--nc-danger, #ff6b6b); }
</style>
