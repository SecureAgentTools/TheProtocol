<template>
  <div class="topo-wrap" ref="wrapRef">
    <canvas ref="canvasRef" @mousemove="onMouseMove" @click="onClick"></canvas>
    <div v-if="hovered" class="topo-tooltip" :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }">
      <div class="topo-tt-name">{{ hovered.name }}</div>
      <div class="topo-tt-frame">Frame {{ hovered.frame }} &middot; Hop {{ hovered.hop_depth || 0 }}</div>
      <div v-if="hovered.agent_count" class="topo-tt-meta">{{ hovered.agent_count }} agents</div>
      <div v-if="hovered.grade" class="topo-tt-meta">Grade: {{ hovered.grade }} ({{ hovered.boris_score }})</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

interface TopoNode {
  id: string; name: string; frame: string; url: string
  hop_depth?: number; agent_count?: number; is_healthy?: boolean
  response_ms?: number; boris_score?: number; grade?: string
  x: number; y: number; vx: number; vy: number; r: number
}

interface TopoEdge { source: string; target: string }

const props = defineProps<{
  registries: any[]
  edges: any[]
}>()

const canvasRef = ref<HTMLCanvasElement>()
const wrapRef = ref<HTMLDivElement>()
const hovered = ref<TopoNode | null>(null)
const tooltipX = ref(0)
const tooltipY = ref(0)

let nodes: TopoNode[] = []
let edgeList: TopoEdge[] = []
let W = 800, H = 600
let animFrame = 0

function layout() {
  if (!props.registries?.length) return

  const frameA = props.registries.filter(r => r.frame !== 'B')
  const frameB = props.registries.filter(r => r.frame === 'B')

  nodes = props.registries.map((reg, i) => {
    const isB = reg.frame === 'B'
    const group = isB ? frameB : frameA
    const gi = group.indexOf(reg)
    const cx = isB ? W * 0.70 : W * 0.30
    const cy = H * 0.5
    // Spread nodes in a grid-like pattern for better initial positioning
    const cols = Math.ceil(Math.sqrt(group.length))
    const row = Math.floor(gi / cols)
    const col = gi % cols
    const spacingX = Math.min(W * 0.35, 300) / Math.max(cols, 1)
    const spacingY = Math.min(H * 0.7, 400) / Math.max(Math.ceil(group.length / cols), 1)
    const startX = cx - (cols * spacingX) / 2
    const startY = cy - (Math.ceil(group.length / cols) * spacingY) / 2
    return {
      ...reg,
      x: startX + col * spacingX + spacingX / 2,
      y: startY + row * spacingY + spacingY / 2,
      vx: 0, vy: 0,
      r: Math.max(8, Math.min(20, 8 + (reg.agent_count || 0) * 0.6)),
    }
  })

  edgeList = (props.edges || []).map(e => ({
    source: typeof e.source === 'string' ? e.source : e.source?.id || '',
    target: typeof e.target === 'string' ? e.target : e.target?.id || '',
  }))

  // Spring-force layout (60 iterations)
  const nodeMap = new Map(nodes.map(n => [n.id, n]))
  for (let iter = 0; iter < 60; iter++) {
    // Repulsion between all pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]
        let dx = b.x - a.x, dy = b.y - a.y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const force = 2000 / (dist * dist)
        const fx = (dx / dist) * force, fy = (dy / dist) * force
        a.vx -= fx; a.vy -= fy
        b.vx += fx; b.vy += fy
      }
    }
    // Attraction along edges
    for (const e of edgeList) {
      const a = nodeMap.get(e.source), b = nodeMap.get(e.target)
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      const force = (dist - 100) * 0.01
      const fx = (dx / Math.max(dist, 1)) * force
      const fy = (dy / Math.max(dist, 1)) * force
      a.vx += fx; a.vy += fy
      b.vx -= fx; b.vy -= fy
    }
    // Frame gravity: pull A left, B right
    for (const n of nodes) {
      const cx = n.frame === 'B' ? W * 0.72 : W * 0.32
      n.vx += (cx - n.x) * 0.005
      n.vy += (H * 0.5 - n.y) * 0.003
    }
    // Apply velocity with damping
    for (const n of nodes) {
      n.x += n.vx * 0.3
      n.y += n.vy * 0.3
      n.vx *= 0.7; n.vy *= 0.7
      n.x = Math.max(n.r + 10, Math.min(W - n.r - 10, n.x))
      n.y = Math.max(n.r + 10, Math.min(H - n.r - 10, n.y))
    }
  }
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  canvas.width = W * dpr; canvas.height = H * dpr
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  ctx.scale(dpr, dpr)

  // Background
  ctx.fillStyle = '#060b14'
  ctx.fillRect(0, 0, W, H)

  // Frame labels
  ctx.font = '10px monospace'
  ctx.fillStyle = 'rgba(var(--nc-primary-rgb),0.3)'
  ctx.fillText('FRAME A', 20, 20)
  ctx.fillStyle = 'rgba(201,168,76,0.3)'
  ctx.fillText('FRAME B', W - 70, 20)

  // Divider line
  ctx.strokeStyle = 'rgba(255,255,255,0.05)'
  ctx.setLineDash([4, 8])
  ctx.beginPath()
  ctx.moveTo(W * 0.52, 30); ctx.lineTo(W * 0.52, H - 10)
  ctx.stroke()
  ctx.setLineDash([])

  const nodeMap = new Map(nodes.map(n => [n.id, n]))

  // Draw edges
  for (const e of edgeList) {
    const a = nodeMap.get(e.source), b = nodeMap.get(e.target)
    if (!a || !b) continue
    const crossFrame = a.frame !== b.frame
    ctx.strokeStyle = crossFrame ? 'rgba(201,168,76,0.25)' : 'rgba(var(--nc-primary-rgb),0.12)'
    ctx.lineWidth = crossFrame ? 1.5 : 0.8
    if (crossFrame) ctx.setLineDash([3, 5])
    ctx.beginPath()
    ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
    ctx.stroke()
    ctx.setLineDash([])
  }

  // Draw nodes
  for (const n of nodes) {
    const isB = n.frame === 'B'
    const baseColor = isB ? 'rgba(201,168,76,' : 'rgba(var(--nc-primary-rgb),'
    const isHov = hovered.value?.id === n.id

    // Glow
    if (isHov) {
      ctx.shadowBlur = 20
      ctx.shadowColor = isB ? '#c9a84c' : 'var(--nc-primary)'
    }

    // Circle fill
    ctx.beginPath()
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
    ctx.fillStyle = baseColor + (isHov ? '0.5)' : '0.25)')
    ctx.fill()
    ctx.strokeStyle = baseColor + (isHov ? '1)' : '0.6)')
    ctx.lineWidth = isHov ? 2 : 1.2
    ctx.stroke()

    ctx.shadowBlur = 0
    ctx.shadowColor = 'transparent'

    // Health indicator dot
    if (n.is_healthy !== undefined) {
      ctx.beginPath()
      ctx.arc(n.x + n.r * 0.6, n.y - n.r * 0.6, 3, 0, Math.PI * 2)
      ctx.fillStyle = n.is_healthy ? '#22c55e' : '#ef4444'
      ctx.fill()
    }

    // Label
    const label = (n.name || n.id).replace(/^cloud-op-|operator|registry-?/gi, '').replace(/-/g, ' ').trim()
    const shortLabel = label.length > 12 ? label.slice(0, 11) + '..' : label
    ctx.font = `${isHov ? 'bold ' : ''}9px monospace`
    ctx.fillStyle = isB ? 'rgba(201,168,76,0.8)' : 'rgba(var(--nc-primary-rgb),0.8)'
    ctx.textAlign = 'center'
    ctx.fillText(shortLabel, n.x, n.y + n.r + 12)
  }
}

function findNodeAt(mx: number, my: number): TopoNode | null {
  for (const n of nodes) {
    const dx = mx - n.x, dy = my - n.y
    if (dx * dx + dy * dy < (n.r + 4) * (n.r + 4)) return n
  }
  return null
}

function onMouseMove(e: MouseEvent) {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  const mx = e.clientX - rect.left, my = e.clientY - rect.top
  const node = findNodeAt(mx, my)
  hovered.value = node
  if (node) {
    tooltipX.value = mx + 15
    tooltipY.value = my - 10
    if (canvasRef.value) canvasRef.value.style.cursor = 'pointer'
  } else {
    if (canvasRef.value) canvasRef.value.style.cursor = 'default'
  }
  draw()
}

function onClick(e: MouseEvent) {
  // Could emit click event for future use
}

function resize() {
  const wrap = wrapRef.value
  if (!wrap) return
  W = wrap.clientWidth || 800
  H = Math.max(550, Math.min(800, wrap.clientHeight || 650))
  layout()
  draw()
}

watch(() => [props.registries, props.edges], () => {
  layout()
  draw()
}, { deep: true })

onMounted(() => {
  nextTick(() => {
    resize()
    window.addEventListener('resize', resize)
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  if (animFrame) cancelAnimationFrame(animFrame)
})
</script>

<style scoped>
.topo-wrap {
  position: relative; width: 100%; min-height: 550px;
  background: #060b14; border: 1px solid rgba(var(--nc-primary-rgb),0.12); border-radius: 6px;
  overflow: hidden;
}
canvas { display: block; width: 100%; }
.topo-tooltip {
  position: absolute; pointer-events: none; z-index: 10;
  background: rgba(6,11,20,0.95); border: 1px solid rgba(var(--nc-primary-rgb),0.3);
  border-radius: 4px; padding: 8px 12px; font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; color: #e0ffe0; max-width: 220px;
}
.topo-tt-name { font-weight: 600; color: var(--nc-primary); margin-bottom: 2px; }
.topo-tt-frame { color: #668866; font-size: 10px; }
.topo-tt-meta { color: #99bb99; font-size: 10px; margin-top: 2px; }
</style>
