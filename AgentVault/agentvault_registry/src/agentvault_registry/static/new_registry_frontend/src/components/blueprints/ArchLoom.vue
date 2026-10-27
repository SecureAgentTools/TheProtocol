<template>
  <div ref="rootEl" class="arch" :class="{ 'arch--static': isStatic }">
    <svg class="arch-svg" viewBox="0 0 1000 760" role="img" :aria-label="ariaTitle">
      <title>{{ ariaTitle }}</title>
      <defs>
        <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" class="arch-arrowhead" />
        </marker>
      </defs>

      <!-- Trust zones -->
      <g v-for="z in arch.zones" :key="z.id" class="arch-zone" :class="`arch-zone--${z.kind}`">
        <rect :x="z.x" :y="z.y" :width="z.w" :height="z.h" rx="14" class="arch-zone-box" />
        <text :x="z.x + 14" :y="z.y + 22" class="arch-zone-label">{{ z.label }}</text>
        <text v-if="z.sub" :x="z.x + 14" :y="z.y + 36" class="arch-zone-sub">{{ z.sub }}</text>
      </g>

      <!-- Edges -->
      <g v-for="e in geoEdges" :key="e.id" class="arch-edge"
         :data-state="edgeState[e.id] || 'idle'" :class="{ 'arch-edge--dashed': e.dashed }">
        <path class="arch-bed" :d="e.d" marker-end="url(#arch-arrow)" />
        <path class="arch-glow" :d="e.d" />
        <path class="arch-pulse" :d="e.d" pathLength="100"
              :ref="(el) => setPulseRef(e.id, el as SVGPathElement | null)" />
        <g class="arch-chevrons">
          <path v-for="(c, i) in e.chevrons" :key="i" :d="c" class="arch-chevron" />
        </g>
        <text v-if="e.label" class="arch-edge-label" :x="e.mx" :y="e.my - 6" text-anchor="middle">{{ e.label }}</text>
      </g>

      <!-- Nodes -->
      <g v-for="n in arch.nodes" :key="n.id" class="arch-node"
         :class="[`arch-node--${n.kind}`, { 'is-lit': litNodes.has(n.id) }]"
         :transform="`translate(${n.x}, ${n.y})`">
        <template v-if="n.kind === 'gate'">
          <rect class="arch-node-box arch-node-gatebox" x="-20" y="-20" width="40" height="40" rx="9" transform="rotate(45)" />
          <g class="arch-node-icon" transform="translate(-7, -7) scale(0.583)"><g v-html="ICONS.gate"></g></g>
          <text class="arch-node-label" x="0" y="40" text-anchor="middle">{{ n.label }}</text>
          <text v-if="n.sub" class="arch-node-sub" x="0" y="52" text-anchor="middle">{{ n.sub }}</text>
        </template>
        <template v-else>
          <rect class="arch-node-box" x="-64" y="-20" width="128" height="40" rx="8" />
          <g class="arch-node-icon" transform="translate(-56, -7) scale(0.583)"><g v-html="ICONS[n.kind]"></g></g>
          <text class="arch-node-label" x="-38" :y="n.sub ? -2 : 3.5">{{ n.label }}</text>
          <text v-if="n.sub" class="arch-node-sub" x="-38" y="10.5">{{ n.sub }}</text>
        </template>
      </g>
    </svg>

    <!-- Trace bar -->
    <div v-if="arch.script?.length" class="arch-tracebar">
      <button v-if="!isStatic" type="button" class="arch-trace-btn" :disabled="tracing" @click="runTrace">
        {{ tracing ? t('blueprintsView.arch.tracing', 'TRACING') : t('blueprintsView.arch.trace', 'TRACE THE FLOW') }}
      </button>
      <button v-if="!isStatic && (tracing || traced)" type="button" class="arch-trace-reset" @click="resetTrace">
        {{ t('blueprintsView.arch.reset', 'Reset') }}
      </button>
      <div class="arch-caption" role="status" aria-live="polite">
        <span class="arch-caption-dot" :data-state="captionState"></span>
        <span v-if="traceStep" class="arch-caption-step">{{ traceStep.i }}/{{ traceStep.n }}</span>
        <span v-else-if="traced" class="arch-caption-done">{{ t('blueprintsView.arch.done', 'TRACED') }}</span>
        <span class="arch-caption-text">{{ caption || arch.traceLabel || ' ' }}</span>
      </div>
    </div>

    <!-- Static / reduced-motion legend: the trace as an honest ordered list -->
    <ol v-if="arch.script?.length" class="arch-legend" :class="{ 'sr-only-legend': !isStatic }">
      <li v-for="(s, i) in arch.script" :key="i">{{ s.caption || edgeById[s.edge]?.label || s.edge }}</li>
    </ol>
  </div>
</template>

<script setup lang="ts">
// ArchLoom (strategy §18.3) — the deployment topology canvas. A map, not a
// theatre: the full architecture is visible at rest (zones, nodes, every edge
// with direction chevrons), nothing loops ambiently, and the single optional
// TRACE THE FLOW control replays the core transaction across the topology.
// There is no denied state here by design; refusals live in FlowLoom.
// Geometry is self-contained (node metrics differ from FlowLoom's; the two
// canvases deliberately do not share a helper so a change to one cannot
// silently reshape the other).
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import type { BlueprintArch, ArchEdge, NodeKind } from '@/data/blueprints/types'

const props = withDefaults(defineProps<{
  arch: BlueprintArch
  ariaTitle?: string
}>(), { ariaTitle: 'Reference architecture' })

const { t } = useI18n()

const ICONS: Record<NodeKind, string> = {
  agent: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4M5.2 5.2l2.8 2.8M16 16l2.8 2.8M18.8 5.2L16 8M8 16l-2.8 2.8"/>',
  human: '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  registry: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M7 14h6"/>',
  teg: '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>',
  ledger: '<path d="M4 3h16v18H4z"/><path d="M8 7.5h8M8 11.5h8M8 15.5h5"/>',
  gate: '<path d="M12 3l8 3.5v5.2c0 4.8-3.4 7.9-8 9.3-4.6-1.4-8-4.5-8-9.3V6.5z"/><path d="M9 12l2 2 4-4.5"/>',
  external: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a13.4 13.4 0 010 18M12 3a13.4 13.4 0 000 18"/>',
}

// ---------------------------------------------------------------- geometry
interface Pt { x: number; y: number }
const HW = 64, HH = 20, GATE_R = 28

const nodeById = computed(() => Object.fromEntries(props.arch.nodes.map((n) => [n.id, n])))
const edgeById = computed(() => Object.fromEntries(props.arch.edges.map((e) => [e.id, e])))

function halfSize(kind: NodeKind): { hw: number; hh: number } {
  return kind === 'gate' ? { hw: GATE_R, hh: GATE_R } : { hw: HW, hh: HH }
}

interface GeoEdge extends ArchEdge { d: string; mx: number; my: number; chevrons: string[] }

function bezierAt(t: number, p0: Pt, c1: Pt, c2: Pt, p1: Pt): Pt {
  const u = 1 - t
  return {
    x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
    y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
  }
}

const geoEdges = computed<GeoEdge[]>(() => props.arch.edges.map((e) => {
  const a = nodeById.value[e.from], b = nodeById.value[e.to]
  const ah = halfSize(a.kind), bh = halfSize(b.kind)
  const dx = b.x - a.x, dy = b.y - a.y
  let p0: Pt, p1: Pt, c1: Pt, c2: Pt
  if (Math.abs(dx) >= Math.abs(dy)) {
    const s = Math.sign(dx) || 1
    p0 = { x: a.x + ah.hw * s, y: a.y }
    p1 = { x: b.x - bh.hw * s, y: b.y }
    const pull = (p1.x - p0.x) * 0.42
    c1 = { x: p0.x + pull, y: p0.y }
    c2 = { x: p1.x - pull, y: p1.y }
  } else {
    const s = Math.sign(dy) || 1
    p0 = { x: a.x, y: a.y + ah.hh * s }
    p1 = { x: b.x, y: b.y - bh.hh * s }
    const pull = (p1.y - p0.y) * 0.42
    c1 = { x: p0.x, y: p0.y + pull }
    c2 = { x: p1.x, y: p1.y - pull }
  }
  if (e.curve) {
    const len = Math.hypot(dx, dy) || 1
    const px = (-dy / len) * e.curve, py = (dx / len) * e.curve
    c1 = { x: c1.x + px, y: c1.y + py }
    c2 = { x: c2.x + px, y: c2.y + py }
  }
  const d = `M ${p0.x} ${p0.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p1.x} ${p1.y}`
  const mid = bezierAt(e.labelT ?? 0.5, p0, c1, c2, p1)
  const chevrons = [0.42, 0.62].map((tt) => {
    const p = bezierAt(tt, p0, c1, c2, p1)
    const q = bezierAt(Math.min(tt + 0.04, 1), p0, c1, c2, p1)
    const ang = Math.atan2(q.y - p.y, q.x - p.x)
    const l = 5
    const a1 = ang + 2.5, a2 = ang - 2.5
    return `M ${p.x + Math.cos(a1) * l} ${p.y + Math.sin(a1) * l} L ${p.x} ${p.y} L ${p.x + Math.cos(a2) * l} ${p.y + Math.sin(a2) * l}`
  })
  return { ...e, d, mx: mid.x, my: mid.y, chevrons }
}))

// ---------------------------------------------------------------- trace
type TraceState = 'idle' | 'active' | 'settled'
const edgeState = reactive<Record<string, TraceState>>({})
const litNodes = reactive(new Set<string>())
const caption = ref('')
const captionState = ref<TraceState>('idle')
const traceStep = ref<{ i: number; n: number } | null>(null)
const tracing = ref(false)
const traced = ref(false)

const pulseEls = new Map<string, SVGPathElement>()
function setPulseRef(id: string, el: SVGPathElement | null) {
  if (el) pulseEls.set(id, el)
  else pulseEls.delete(id)
}

const rootEl = ref<HTMLElement | null>(null)
const isStatic = ref(false)
let runId = 0
let currentAnim: Animation | null = null

const OFFSET_START = 212
const OFFSET_DONE = 100

function resetVisual() {
  for (const e of props.arch.edges) edgeState[e.id] = 'idle'
  litNodes.clear()
  caption.value = ''
  captionState.value = 'idle'
  traceStep.value = null
  traced.value = false
  for (const el of pulseEls.values()) {
    el.getAnimations().forEach((a) => a.cancel())
    el.style.strokeDasharray = '12 188'
    el.style.strokeDashoffset = String(OFFSET_START)
  }
}

function sweep(edgeId: string, dur: number): Promise<void> {
  return new Promise((resolve) => {
    const el = pulseEls.get(edgeId)
    if (!el) { resolve(); return }
    el.getAnimations().forEach((a) => a.cancel())
    const anim = el.animate(
      [{ strokeDashoffset: String(OFFSET_START) }, { strokeDashoffset: String(OFFSET_DONE) }],
      { duration: Math.max(dur, 200), easing: 'linear', fill: 'forwards' },
    )
    currentAnim = anim
    anim.onfinish = () => { currentAnim = null; resolve() }
    anim.oncancel = () => { currentAnim = null; resolve() }
  })
}

async function runTrace() {
  const steps = props.arch.script
  if (!steps?.length || tracing.value) return
  const my = ++runId
  tracing.value = true
  resetVisual()
  let i = 0
  for (const s of steps) {
    if (my !== runId) return
    i += 1
    const e = edgeById.value[s.edge]
    if (!e) continue
    traceStep.value = { i, n: steps.length }
    edgeState[s.edge] = 'active'
    litNodes.add(e.from)
    caption.value = s.caption || ''
    captionState.value = 'active'
    await sweep(s.edge, s.dwellMs)
    if (my !== runId) return
    edgeState[s.edge] = 'settled'
    litNodes.add(e.to)
  }
  if (my !== runId) return
  traceStep.value = null
  captionState.value = 'settled'
  caption.value = props.arch.traceLabel || ''
  tracing.value = false
  traced.value = true
}

function resetTrace() {
  ++runId
  if (currentAnim) currentAnim.cancel()
  tracing.value = false
  resetVisual()
}

// ---------------------------------------------------------------- lifecycle
let mqMotion: MediaQueryList | null = null
let mqNarrow: MediaQueryList | null = null

function evalStatic() {
  const next = (mqMotion?.matches ?? false) || (mqNarrow?.matches ?? false)
  if (next !== isStatic.value) {
    isStatic.value = next
    resetTrace()
  }
}

onMounted(() => {
  mqMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  mqNarrow = window.matchMedia('(max-width: 700px)')
  isStatic.value = mqMotion.matches || mqNarrow.matches
  mqMotion.addEventListener?.('change', evalStatic)
  mqNarrow.addEventListener?.('change', evalStatic)
})

onBeforeUnmount(() => {
  ++runId
  if (currentAnim) currentAnim.cancel()
  mqMotion?.removeEventListener?.('change', evalStatic)
  mqNarrow?.removeEventListener?.('change', evalStatic)
})
</script>

<script lang="ts">
export default { name: 'ArchLoom' }
</script>

<style scoped>
.arch {
  --flow: var(--nc-primary, #00d2d2);
  --flow-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --settle: #10b981;
  --arch-idle: #6b7785;
  width: 100%;
}
.arch-svg { width: 100%; height: auto; display: block; overflow: visible; }

/* Trust zones */
.arch-zone-box { fill: rgba(var(--flow-rgb), 0.022); stroke: rgba(var(--flow-rgb), 0.16); stroke-width: 1; }
.arch-zone--fabric .arch-zone-box { fill: rgba(var(--flow-rgb), 0.045); stroke: rgba(var(--flow-rgb), 0.24); }
.arch-zone--external .arch-zone-box { fill: transparent; stroke: rgba(107, 119, 133, 0.45); stroke-dasharray: 6 5; }
.arch-zone-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px; font-weight: 800; letter-spacing: 0.1em; fill: rgba(var(--flow-rgb), 0.8);
}
.arch-zone--external .arch-zone-label { fill: var(--arch-idle); }
.arch-zone-sub { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 9px; fill: var(--arch-idle); }

/* Edges */
.arch-bed { fill: none; stroke: rgba(var(--flow-rgb), 0.2); stroke-width: 1.2; }
.arch-edge--dashed .arch-bed { stroke-dasharray: 4 5; stroke: rgba(var(--flow-rgb), 0.16); }
.arch-arrowhead { fill: rgba(var(--flow-rgb), 0.4); }
.arch-glow { fill: none; stroke: var(--flow); stroke-width: 6; stroke-linecap: round; opacity: 0; transition: opacity 0.5s ease; }
.arch-pulse { fill: none; stroke: var(--flow); stroke-width: 2.4; stroke-linecap: round; stroke-dasharray: 12 188; stroke-dashoffset: 212; }
.arch-edge[data-state="active"] .arch-glow { opacity: 0.22; }
.arch-edge[data-state="settled"] .arch-glow { opacity: 0.1; }
.arch-edge[data-state="settled"] .arch-bed { stroke: rgba(var(--flow-rgb), 0.38); }
.arch-chevron { fill: none; stroke: rgba(var(--flow-rgb), 0.4); stroke-width: 1.3; stroke-linecap: round; stroke-linejoin: round; }
.arch-edge-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 10px; fill: var(--arch-idle); opacity: 0.7;
  transition: fill 0.3s ease, opacity 0.3s ease;
}
.arch-edge[data-state="active"] .arch-edge-label,
.arch-edge[data-state="settled"] .arch-edge-label { fill: rgba(var(--flow-rgb), 0.9); opacity: 0.95; }

/* Nodes */
.arch-node-box {
  fill: rgba(10, 14, 22, 0.72);
  stroke: rgba(var(--flow-rgb), 0.24);
  stroke-width: 1;
  transition: stroke 0.35s ease, fill 0.35s ease;
}
.arch-node.is-lit .arch-node-box { stroke: rgba(var(--flow-rgb), 0.8); fill: rgba(var(--flow-rgb), 0.07); }
.arch-node--external .arch-node-box { stroke: rgba(107, 119, 133, 0.5); stroke-dasharray: 4 3; }
.arch-node--external.is-lit .arch-node-box { stroke: rgba(var(--flow-rgb), 0.6); }
.arch-node-icon { stroke: rgba(var(--flow-rgb), 0.85); fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; opacity: 0.55; transition: opacity 0.35s ease; }
.arch-node.is-lit .arch-node-icon { opacity: 1; }
.arch-node-icon :deep(*) { vector-effect: non-scaling-stroke; }
.arch-node-label { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 10.5px; font-weight: 600; fill: #cfd8e3; }
.arch-node-sub { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 8.5px; fill: var(--arch-idle); }
.arch-node.is-lit .arch-node-label { fill: #eef3f8; }

/* Trace bar */
.arch-tracebar { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.5rem; }
.arch-trace-btn {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem; font-weight: 800; letter-spacing: 0.1em;
  color: var(--flow); background: rgba(var(--flow-rgb), 0.06);
  border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 8px;
  padding: 0.5rem 0.95rem; cursor: pointer; flex-shrink: 0;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}
.arch-trace-btn:hover:not(:disabled) { background: rgba(var(--flow-rgb), 0.13); box-shadow: 0 0 14px rgba(var(--flow-rgb), 0.25); }
.arch-trace-btn:disabled { opacity: 0.55; cursor: default; }
.arch-trace-reset {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem; color: var(--arch-idle); background: none;
  border: 1px solid rgba(107, 119, 133, 0.35); border-radius: 8px;
  padding: 0.5rem 0.7rem; cursor: pointer; flex-shrink: 0;
}
.arch-caption {
  display: flex; align-items: center; gap: 0.55rem; flex: 1; min-width: 0;
  min-height: 2.1rem; padding: 0.45rem 0.8rem;
  border: 1px solid rgba(var(--flow-rgb), 0.14); border-radius: 9px;
  background: rgba(var(--flow-rgb), 0.03);
}
.arch-caption-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--arch-idle); flex-shrink: 0; transition: background 0.3s ease, box-shadow 0.3s ease; }
.arch-caption-dot[data-state="active"] { background: var(--flow); box-shadow: 0 0 8px rgba(var(--flow-rgb), 0.8); }
.arch-caption-dot[data-state="settled"] { background: var(--settle); }
.arch-caption-step {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem; font-weight: 800; letter-spacing: 0.08em; color: var(--flow);
  border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 5px; padding: 0.12rem 0.4rem; flex-shrink: 0;
}
.arch-caption-done {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem; font-weight: 800; letter-spacing: 0.1em; color: #052014;
  background: var(--settle); border-radius: 5px; padding: 0.14rem 0.45rem; flex-shrink: 0;
}
.arch-caption-text { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.7rem; color: #b7c2cf; line-height: 1.45; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Legend */
.arch-legend { margin: 0.7rem 0 0; padding-left: 1.2rem; }
.arch-legend li { font-size: 0.7rem; color: #8b98a7; line-height: 1.6; }
.sr-only-legend { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@media (prefers-reduced-motion: reduce) {
  .arch-glow, .arch-node-box, .arch-node-icon, .arch-edge-label { transition: none; }
}
</style>
