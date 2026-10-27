<template>
  <div ref="rootEl" class="loom" :class="{ 'loom--static': isStatic }">
    <svg
      class="loom-svg"
      viewBox="0 0 1000 560"
      role="img"
      :aria-label="ariaTitle"
      @pointermove="onScrubMove"
      @pointerleave="onScrubLeave"
    >
      <title>{{ ariaTitle }}</title>
      <defs>
        <marker id="loom-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" class="loom-arrowhead" />
        </marker>
      </defs>

      <!-- Edges -->
      <g v-for="e in geoEdges" :key="e.id" class="loom-edge"
         :data-state="edgeState[e.id] || 'idle'"
         :class="{ 'loom-edge--attack': e.attackOnly, 'loom-edge--revealed': revealed.has(e.id) }">
        <path class="loom-bed" :d="e.d" marker-end="url(#loom-arrow)" />
        <path class="loom-glow" :d="e.d" />
        <path
          class="loom-pulse"
          :d="e.d"
          pathLength="100"
          :ref="(el) => setPulseRef(e.id, el as SVGPathElement | null)"
        />
        <!-- Static-mode direction chevrons, computed analytically (no DOM reads) -->
        <g v-if="isStatic && (!e.attackOnly || revealed.has(e.id))" class="loom-chevrons">
          <path v-for="(c, i) in e.chevrons" :key="i" :d="c" class="loom-chevron" />
        </g>
        <text v-if="e.label && (!e.attackOnly || revealed.has(e.id))"
              class="loom-edge-label" :x="e.mx" :y="e.my - 7" text-anchor="middle">{{ e.label }}</text>
      </g>

      <!-- Nodes -->
      <g v-for="n in nodes" :key="n.id" class="loom-node"
         :class="[`loom-node--${n.kind}`, { 'is-lit': litNodes.has(n.id), 'is-flash': flashing === n.id }]"
         :transform="`translate(${n.x}, ${n.y})`">
        <template v-if="n.kind === 'gate'">
          <rect class="loom-node-box loom-node-gatebox" x="-24" y="-24" width="48" height="48" rx="10" transform="rotate(45)" />
          <g class="loom-node-icon" transform="translate(-8, -8) scale(0.667)">
            <g v-html="ICONS.gate"></g>
          </g>
          <text class="loom-node-label" x="0" y="46" text-anchor="middle">{{ n.label }}</text>
          <text v-if="n.sub" class="loom-node-sub" x="0" y="60" text-anchor="middle">{{ n.sub }}</text>
        </template>
        <template v-else>
          <rect class="loom-node-box" x="-74" y="-23" width="148" height="46" rx="9" />
          <g class="loom-node-icon" transform="translate(-66, -8) scale(0.667)">
            <g v-html="ICONS[n.kind]"></g>
          </g>
          <text class="loom-node-label" x="-46" :y="n.sub ? -2 : 4">{{ n.label }}</text>
          <text v-if="n.sub" class="loom-node-sub" x="-46" y="12">{{ n.sub }}</text>
        </template>
      </g>
    </svg>

    <!-- Caption bar -->
    <div class="loom-caption" :class="{ 'loom-caption--refused': refused }" role="status" aria-live="polite">
      <span class="loom-caption-dot" :data-state="captionState"></span>
      <span v-if="refused" class="loom-caption-refused">REFUSED</span>
      <span v-else-if="attackStep" class="loom-caption-step">ATTACK {{ attackStep.i }}/{{ attackStep.n }}</span>
      <span class="loom-caption-text">{{ caption || ' ' }}</span>
    </div>

    <!-- Step legend: the honest version for static / reduced motion; sr-only otherwise -->
    <ol class="loom-legend" :class="{ 'sr-only-legend': !isStatic }">
      <li v-for="(s, i) in script" :key="i">{{ s.caption || edgeById[s.edge]?.label || s.edge }}</li>
    </ol>
  </div>
</template>

<script setup lang="ts">
// FlowLoom — the directional flow canvas (strategy §8).
// A request travels as a glowing pulse along derived cubic paths. Geometry is
// pathLength-normalized so timing is independent of each path's real length;
// sweeps run on the Web Animations API (compositor-driven, pausable), never a
// rAF loop. A denied pulse halts at stopAt and stays parked: the gate flashes,
// downstream stays dark, and the darkness is the message.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import type { LoomEdge, LoomNode, LoomStep, EdgeState, NodeKind } from '@/data/blueprints/types'

const props = withDefaults(defineProps<{
  nodes: LoomNode[]
  edges: LoomEdge[]
  script: LoomStep[]
  ariaTitle?: string
  autoLoop?: boolean
}>(), { ariaTitle: 'Request flow', autoLoop: true })

const emit = defineEmits<{ (e: 'attack-finished'): void }>()

// Inline stroke icons, 24x24 space (scaled 0.667 => 16px). No emoji, house rule.
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
const HW = 74, HH = 23, GATE_R = 33 // rect half-w/h, gate diamond half-diagonal

function halfSize(kind: NodeKind): { hw: number; hh: number } {
  return kind === 'gate' ? { hw: GATE_R, hh: GATE_R } : { hw: HW, hh: HH }
}

const nodeById = computed(() => Object.fromEntries(props.nodes.map((n) => [n.id, n])))
const edgeById = computed(() => Object.fromEntries(props.edges.map((e) => [e.id, e])))

interface GeoEdge extends LoomEdge {
  d: string
  mx: number
  my: number
  chevrons: string[]
}

function cubicFor(e: LoomEdge): { p0: Pt; c1: Pt; c2: Pt; p1: Pt } {
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
    // Perpendicular bow — reversed pairs bow to opposite sides automatically.
    const len = Math.hypot(dx, dy) || 1
    const px = (-dy / len) * e.curve, py = (dx / len) * e.curve
    c1 = { x: c1.x + px, y: c1.y + py }
    c2 = { x: c2.x + px, y: c2.y + py }
  }
  return { p0, c1, c2, p1 }
}

function bezierAt(t: number, p0: Pt, c1: Pt, c2: Pt, p1: Pt): Pt {
  const u = 1 - t
  return {
    x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
    y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
  }
}

const geoEdges = computed<GeoEdge[]>(() => props.edges.map((e) => {
  if (e.d) return { ...e, d: e.d, mx: 0, my: 0, chevrons: [] }
  const { p0, c1, c2, p1 } = cubicFor(e)
  const d = `M ${p0.x} ${p0.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p1.x} ${p1.y}`
  const mid = bezierAt(e.labelT ?? 0.5, p0, c1, c2, p1)
  // Analytic chevrons for static mode: three arrows along the curve.
  const chevrons = [0.3, 0.55, 0.8].map((t) => {
    const p = bezierAt(t, p0, c1, c2, p1)
    const q = bezierAt(Math.min(t + 0.04, 1), p0, c1, c2, p1)
    const ang = Math.atan2(q.y - p.y, q.x - p.x)
    const l = 6
    const a1 = ang + 2.5, a2 = ang - 2.5
    return `M ${p.x + Math.cos(a1) * l} ${p.y + Math.sin(a1) * l} L ${p.x} ${p.y} L ${p.x + Math.cos(a2) * l} ${p.y + Math.sin(a2) * l}`
  })
  return { ...e, d, mx: mid.x, my: mid.y, chevrons }
}))

// ---------------------------------------------------------------- state
const edgeState = reactive<Record<string, EdgeState>>({})
const litNodes = reactive(new Set<string>())
const revealed = reactive(new Set<string>())
const flashing = ref<string | null>(null)
const caption = ref('')
const captionState = ref<EdgeState>('idle')
const attackStep = ref<{ i: number; n: number } | null>(null)
const refused = ref(false)

const pulseEls = new Map<string, SVGPathElement>()
function setPulseRef(id: string, el: SVGPathElement | null) {
  if (el) pulseEls.set(id, el)
  else pulseEls.delete(id)
}

const rootEl = ref<HTMLElement | null>(null)
const inView = ref(false)
const isStatic = ref(false)

let runId = 0
let currentAnim: Animation | null = null
let restartTimer: number | null = null
const inAttack = ref(false)
const scrubbing = ref(false)
let scrubResume: number | null = null

// Pulse sweep constants (pathLength=100, dasharray "12 188"): the packet's
// front sits at (212 - offset); 212 = parked before entry, 100 = fully exited.
const OFFSET_START = 212
const OFFSET_DONE = 100
function offsetFor(stopAt?: number): number {
  return stopAt == null ? OFFSET_DONE : OFFSET_START - 100 * Math.min(Math.max(stopAt, 0), 1)
}

function resetVisual() {
  for (const e of props.edges) edgeState[e.id] = 'idle'
  litNodes.clear()
  revealed.clear()
  flashing.value = null
  caption.value = ''
  captionState.value = 'idle'
  attackStep.value = null
  refused.value = false
  for (const el of pulseEls.values()) {
    el.getAnimations().forEach((a) => a.cancel())
    el.style.strokeDasharray = '12 188'
    el.style.strokeDashoffset = String(OFFSET_START)
  }
}

function paintStatic() {
  // Final frame of the happy path, no motion. Attack edges stay hidden.
  resetVisual()
  for (const s of props.script) {
    edgeState[s.edge] = 'settled'
    const e = edgeById.value[s.edge]
    if (e) { litNodes.add(e.from); litNodes.add(e.to) }
  }
}

function sweep(edgeId: string, dur: number, stopAt?: number): Promise<void> {
  return new Promise((resolve) => {
    const el = pulseEls.get(edgeId)
    if (!el) { resolve(); return }
    el.getAnimations().forEach((a) => a.cancel())
    const target = offsetFor(stopAt)
    const anim = el.animate(
      [{ strokeDashoffset: String(OFFSET_START) }, { strokeDashoffset: String(target) }],
      { duration: Math.max(dur, 200), easing: 'linear', fill: 'forwards' },
    )
    currentAnim = anim
    // Ambient loops pause off-screen; a user-triggered attack always plays.
    if (!inView.value && !inAttack.value) anim.pause()
    anim.onfinish = () => { currentAnim = null; resolve() }
    anim.oncancel = () => { currentAnim = null; resolve() }
  })
}

async function playScript(steps: LoomStep[], opts: { loop: boolean; attack: boolean }) {
  const my = ++runId
  if (opts.attack) { inAttack.value = true } else { inAttack.value = false }
  resetVisual()
  if (opts.attack) for (const s of steps) revealed.add(s.edge)
  let stepNo = 0
  for (const s of steps) {
    if (my !== runId) return
    stepNo += 1
    const e = edgeById.value[s.edge]
    if (!e) continue
    if (opts.attack) attackStep.value = { i: stepNo, n: steps.length }
    edgeState[s.edge] = s.state === 'denied' ? 'denied' : 'active'
    litNodes.add(e.from)
    caption.value = s.caption || ''
    captionState.value = s.state
    await sweep(s.edge, s.dwellMs, s.state === 'denied' ? s.stopAt ?? 0.7 : undefined)
    if (my !== runId) return
    if (s.state === 'denied') {
      flashing.value = s.flashNode || e.to
      // Parked. Downstream stays dark, and that is the message.
      // Attack replays end here; a scripted happy path (the hero's standing
      // denial branch) parks the edge and keeps narrating.
      if (opts.attack) {
        // The unmistakable end state: the caption bar flips to REFUSED and
        // stays there until reset. A parked pulse alone read as "stuck".
        refused.value = true
        attackStep.value = null
        emit('attack-finished')
        return
      }
      continue
    }
    edgeState[s.edge] = 'settled'
    litNodes.add(e.to)
  }
  if (my !== runId) return
  if (opts.attack) { emit('attack-finished'); return }
  if (opts.loop && props.autoLoop) {
    restartTimer = window.setTimeout(() => {
      if (my === runId && inView.value && !scrubbing.value) playScript(props.script, { loop: true, attack: false })
    }, 2400)
  }
}

// ------------------------------------------------------------- public API
function playHappy() {
  if (isStatic.value) { paintStatic(); return }
  playScript(props.script, { loop: true, attack: false })
}
function runAttack(steps: LoomStep[]) {
  if (restartTimer) { clearTimeout(restartTimer); restartTimer = null }
  if (isStatic.value) {
    // Static denial: park the state without motion.
    ++runId
    resetVisual()
    inAttack.value = true
    for (const s of steps) {
      revealed.add(s.edge)
      edgeState[s.edge] = s.state
      const e = edgeById.value[s.edge]
      if (e) litNodes.add(e.from)
      caption.value = s.caption || ''
      captionState.value = s.state
      if (s.state === 'denied') flashing.value = s.flashNode || e?.to || null
    }
    emit('attack-finished')
    return
  }
  playScript(steps, { loop: false, attack: true })
}
function resetToHappy() {
  if (restartTimer) { clearTimeout(restartTimer); restartTimer = null }
  playHappy()
}
defineExpose({ playHappy, runAttack, resetToHappy })

// ---------------------------------------------------------------- scrub
function onScrubMove(ev: PointerEvent) {
  if (isStatic.value || inAttack.value || ev.pointerType !== 'mouse') return
  const svg = ev.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const t = Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1)
  scrubbing.value = true
  ++runId // cancel the running script
  if (currentAnim) currentAnim.cancel()
  if (restartTimer) { clearTimeout(restartTimer); restartTimer = null }
  if (scrubResume) { clearTimeout(scrubResume); scrubResume = null }
  // Map t over the script timeline.
  const total = props.script.reduce((a, s) => a + s.dwellMs, 0) || 1
  let acc = 0
  litNodes.clear()
  for (const s of props.script) {
    const e = edgeById.value[s.edge]
    const el = pulseEls.get(s.edge)
    const start = acc / total
    acc += s.dwellMs
    const end = acc / total
    if (t >= end) {
      edgeState[s.edge] = 'settled'
      if (e) { litNodes.add(e.from); litNodes.add(e.to) }
      if (el) el.style.strokeDashoffset = String(OFFSET_DONE)
    } else if (t > start) {
      const f = (t - start) / (end - start)
      edgeState[s.edge] = 'active'
      if (e) litNodes.add(e.from)
      if (el) el.style.strokeDashoffset = String(OFFSET_START - (OFFSET_START - OFFSET_DONE) * f)
      caption.value = s.caption || ''
      captionState.value = 'active'
    } else {
      edgeState[s.edge] = 'idle'
      if (el) el.style.strokeDashoffset = String(OFFSET_START)
    }
  }
}
function onScrubLeave() {
  if (!scrubbing.value) return
  scrubResume = window.setTimeout(() => {
    scrubbing.value = false
    if (!inAttack.value) playHappy()
  }, 900)
}

// ---------------------------------------------------------------- lifecycle
let io: IntersectionObserver | null = null
let mqMotion: MediaQueryList | null = null
let mqNarrow: MediaQueryList | null = null

function evalStatic() {
  const reduce = mqMotion?.matches ?? false
  const narrow = mqNarrow?.matches ?? false
  const next = reduce || narrow
  if (next !== isStatic.value) {
    isStatic.value = next
    ++runId
    if (currentAnim) currentAnim.cancel()
    if (next) paintStatic()
    else playHappy()
  }
}

onMounted(() => {
  mqMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  mqNarrow = window.matchMedia('(max-width: 700px)')
  isStatic.value = mqMotion.matches || mqNarrow.matches
  mqMotion.addEventListener?.('change', evalStatic)
  mqNarrow.addEventListener?.('change', evalStatic)

  io = new IntersectionObserver((entries) => {
    const vis = entries[0]?.isIntersecting ?? false
    inView.value = vis
    if (vis) {
      if (currentAnim) currentAnim.play()
      else if (!isStatic.value && !inAttack.value && !scrubbing.value) playHappy()
      else if (isStatic.value && !inAttack.value) paintStatic()
    } else if (currentAnim && !inAttack.value) {
      // Ambient loops pause off-screen. A user-triggered attack never pauses:
      // the click-then-scroll choreography can briefly report the loom as
      // not intersecting, and pausing there froze the replay on step one.
      currentAnim.pause()
    }
  }, { threshold: 0.25 })
  if (rootEl.value) io.observe(rootEl.value)
})

onBeforeUnmount(() => {
  ++runId
  if (currentAnim) currentAnim.cancel()
  if (restartTimer) clearTimeout(restartTimer)
  if (scrubResume) clearTimeout(scrubResume)
  io?.disconnect()
  mqMotion?.removeEventListener?.('change', evalStatic)
  mqNarrow?.removeEventListener?.('change', evalStatic)
})
</script>

<style scoped>
.loom {
  --flow: var(--nc-primary, #00d2d2);
  --flow-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --settle: #10b981;
  --deny: #f59e0b;
  --loom-idle: #6b7785;
  width: 100%;
}
.loom-svg { width: 100%; height: auto; display: block; overflow: visible; }

/* Edges — three stacked paths, one geometry */
.loom-bed { fill: none; stroke: rgba(var(--flow-rgb), 0.16); stroke-width: 1.25; }
.loom-arrowhead { fill: rgba(var(--flow-rgb), 0.35); }
.loom-glow { fill: none; stroke: var(--flow); stroke-width: 7; stroke-linecap: round; opacity: 0; transition: opacity 0.5s ease, stroke 0.3s ease; }
.loom-pulse { fill: none; stroke: var(--flow); stroke-width: 2.6; stroke-linecap: round; stroke-dasharray: 12 188; stroke-dashoffset: 212; }

.loom-edge[data-state="active"] .loom-glow { opacity: 0.22; }
.loom-edge[data-state="settled"] .loom-glow { opacity: 0.1; }
.loom-edge[data-state="settled"] .loom-bed { stroke: rgba(var(--flow-rgb), 0.34); }
.loom-edge[data-state="denied"] .loom-glow { stroke: var(--deny); opacity: 0.3; }
.loom-edge[data-state="denied"] .loom-pulse { stroke: var(--deny); stroke-width: 3.6; filter: drop-shadow(0 0 4px rgba(245, 158, 11, 0.65)); }
.loom-edge[data-state="denied"] .loom-bed { stroke: rgba(245, 158, 11, 0.4); }

/* Attack-only edges: invisible until their replay reveals them, then dashed */
.loom-edge--attack { opacity: 0; pointer-events: none; }
.loom-edge--attack.loom-edge--revealed { opacity: 1; }
.loom-edge--attack .loom-bed { stroke-dasharray: 4 5; }

.loom-edge-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 10.5px; fill: var(--loom-idle); opacity: 0.6;
  transition: opacity 0.3s ease, fill 0.3s ease;
}
.loom-edge[data-state="active"] .loom-edge-label,
.loom-edge[data-state="settled"] .loom-edge-label { fill: rgba(var(--flow-rgb), 0.9); opacity: 0.95; }
.loom-edge[data-state="denied"] .loom-edge-label { fill: var(--deny); opacity: 0.95; }

.loom-chevron { fill: none; stroke: rgba(var(--flow-rgb), 0.5); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }

/* Nodes */
.loom-node-box {
  fill: rgba(10, 14, 22, 0.72);
  stroke: rgba(var(--flow-rgb), 0.22);
  stroke-width: 1.1;
  transition: stroke 0.35s ease, fill 0.35s ease, filter 0.35s ease;
}
.loom-node.is-lit .loom-node-box { stroke: rgba(var(--flow-rgb), 0.75); fill: rgba(var(--flow-rgb), 0.07); }
.loom-node--gate .loom-node-box { stroke: rgba(var(--flow-rgb), 0.35); }
.loom-node--human.is-lit .loom-node-box { stroke: rgba(var(--flow-rgb), 0.9); }

.loom-node.is-flash .loom-node-box {
  stroke: var(--deny);
  fill: rgba(245, 158, 11, 0.09);
  animation: loom-flash 1.1s ease-in-out 3;
}
@keyframes loom-flash {
  0%, 100% { stroke-opacity: 1; }
  50% { stroke-opacity: 0.35; }
}

.loom-node-icon { stroke: rgba(var(--flow-rgb), 0.85); fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; opacity: 0.5; transition: opacity 0.35s ease; }
.loom-node.is-lit .loom-node-icon { opacity: 1; }
.loom-node.is-flash .loom-node-icon { stroke: var(--deny); opacity: 1; }
.loom-node-icon :deep(*) { vector-effect: non-scaling-stroke; }

.loom-node-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px; font-weight: 600; fill: #cfd8e3;
}
.loom-node-sub { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 9.5px; fill: var(--loom-idle); }
.loom-node.is-lit .loom-node-label { fill: #eef3f8; }

/* Caption bar */
.loom-caption {
  display: flex; align-items: center; gap: 0.55rem;
  min-height: 2.1rem; margin-top: 0.4rem; padding: 0.45rem 0.8rem;
  border: 1px solid rgba(var(--flow-rgb), 0.14); border-radius: 9px;
  background: rgba(var(--flow-rgb), 0.03);
}
.loom-caption-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--loom-idle); flex-shrink: 0; transition: background 0.3s ease, box-shadow 0.3s ease; }
.loom-caption-dot[data-state="active"] { background: var(--flow); box-shadow: 0 0 8px rgba(var(--flow-rgb), 0.8); }
.loom-caption-dot[data-state="settled"] { background: var(--settle); }
.loom-caption-dot[data-state="denied"] { background: var(--deny); box-shadow: 0 0 8px rgba(245, 158, 11, 0.7); }
.loom-caption-text { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.72rem; color: #b7c2cf; line-height: 1.45; }
.loom-caption-step { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.62rem; font-weight: 800; letter-spacing: 0.08em; color: var(--deny); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 5px; padding: 0.12rem 0.4rem; flex-shrink: 0; }
.loom-caption-refused { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.66rem; font-weight: 800; letter-spacing: 0.12em; color: #0a0a06; background: var(--deny); border-radius: 5px; padding: 0.16rem 0.5rem; flex-shrink: 0; }
.loom-caption--refused { border-color: rgba(245, 158, 11, 0.5); background: rgba(245, 158, 11, 0.05); }

/* Step legend */
.loom-legend { margin: 0.7rem 0 0; padding-left: 1.2rem; }
.loom-legend li { font-size: 0.7rem; color: #8b98a7; line-height: 1.6; }
.sr-only-legend { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@media (prefers-reduced-motion: reduce) {
  .loom-glow, .loom-node-box, .loom-node-icon, .loom-edge-label { transition: none; }
  .loom-node.is-flash .loom-node-box { animation: none; }
}
</style>
