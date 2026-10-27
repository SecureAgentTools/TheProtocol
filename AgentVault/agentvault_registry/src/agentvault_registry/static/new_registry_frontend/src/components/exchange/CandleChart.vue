<template>
  <div class="cc-wrap" ref="wrapEl">
    <canvas ref="canvasEl" class="cc-canvas" @mousemove="onMove" @mouseleave="onLeave"></canvas>
    <div v-if="crossX !== null" class="cc-cross" :style="{ left: crossX + 'px' }"></div>
    <div v-if="!candles.length" class="cc-empty">no trades yet — the chart begins with the first fill</div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AGORA CandleChart — dependency-free canvas OHLCV (2026-06-12, AAA+ pass).
 * House rule: no new chart deps (chartjs-chart-financial absent by design);
 * colors resolve from CSS vars at draw time (MetricCard.vue precedent).
 * Candles + volume + time axis + last-price tag + last-candle glow +
 * crosshair that EMITS hover so the parent renders the OHLC readout band.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface CandlePoint { t: string; o: string; h: string; l: string; c: string; v: number }
export interface ChartHover { label: string; o: string; h: string; l: string; c: string; v: number; rising: boolean }

const props = withDefaults(defineProps<{ candles: CandlePoint[]; height?: number }>(), { height: 280 })
const emit = defineEmits<{ (e: 'hover', p: ChartHover | null): void }>()

const wrapEl = ref<HTMLDivElement>()
const canvasEl = ref<HTMLCanvasElement>()
const crossX = ref<number | null>(null)

let geom: { x0: number; cw: number; n: number } | null = null
let spanMs = 0
let resizeObs: ResizeObserver | null = null

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function draw() {
  const canvas = canvasEl.value
  const wrap = wrapEl.value
  if (!canvas || !wrap) return
  const dpr = window.devicePixelRatio || 1
  const W = wrap.clientWidth
  const H = props.height
  canvas.width = W * dpr
  canvas.height = H * dpr
  canvas.style.width = `${W}px`
  canvas.style.height = `${H}px`
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)

  const cs = props.candles
  if (!cs.length) { geom = null; return }

  const up = '#10b981'
  const down = '#ef4444'
  const accentRgb = cssVar('--nc-primary-rgb', '34, 211, 238')
  const grid = `rgba(${accentRgb}, 0.07)`
  const textC = `rgba(${accentRgb}, 0.5)`

  const padL = 8, padR = 58, padT = 12, padB = 16
  const volH = Math.floor(H * 0.15)
  const priceH = H - volH - padT - padB
  const n = cs.length
  const cw = Math.max(3, Math.floor((W - padL - padR) / n))
  const bw = Math.max(1, Math.min(26, Math.floor(cw * 0.62)))
  geom = { x0: padL, cw, n }
  spanMs = new Date(cs[n - 1].t).getTime() - new Date(cs[0].t).getTime()

  const highs = cs.map(c => parseFloat(c.h)), lows = cs.map(c => parseFloat(c.l))
  let hi = Math.max(...highs), lo = Math.min(...lows)
  if (hi === lo) { hi += hi * 0.01 || 1; lo -= lo * 0.01 || 1 }
  const span = hi - lo
  hi += span * 0.05; lo -= span * 0.05
  const y = (p: number) => padT + (hi - p) / (hi - lo) * priceH
  const maxV = Math.max(...cs.map(c => c.v), 1)

  ctx.font = '10px ui-monospace, monospace'
  ctx.lineWidth = 1

  // vertical time gridlines + labels in the bottom strip
  const innerW = W - padL - padR
  const maxLabels = Math.max(3, Math.floor(innerW / 64))
  const tStep = Math.max(1, Math.ceil(n / maxLabels))
  ctx.strokeStyle = grid
  ctx.fillStyle = textC
  for (let i = 0; i < n; i += tStep) {
    const xC = padL + i * cw + Math.floor(cw / 2)
    ctx.beginPath(); ctx.moveTo(xC + 0.5, padT); ctx.lineTo(xC + 0.5, H - padB); ctx.stroke()
    ctx.fillText(timeLabel(cs[i].t), Math.max(2, xC - 16), H - 4)
  }

  // horizontal grid + right axis labels
  for (let i = 0; i <= 4; i++) {
    const p = hi - ((hi - lo) * i) / 4
    const yy = y(p)
    ctx.strokeStyle = grid
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke()
    ctx.fillStyle = textC
    ctx.fillText(fmtPx(p), W - padR + 6, yy + 3)
  }

  // candles + volume (last candle gets a soft glow)
  cs.forEach((c, i) => {
    const o = parseFloat(c.o), cl = parseFloat(c.c), h = parseFloat(c.h), l = parseFloat(c.l)
    const xC = padL + i * cw + Math.floor(cw / 2)
    const rising = cl >= o
    const col = rising ? up : down
    const isLast = i === n - 1
    ctx.save()
    if (isLast) { ctx.shadowColor = col; ctx.shadowBlur = 10 }
    ctx.strokeStyle = col
    ctx.fillStyle = rising ? 'rgba(16,185,129,0.85)' : 'rgba(239,68,68,0.85)'
    ctx.beginPath(); ctx.moveTo(xC + 0.5, y(h)); ctx.lineTo(xC + 0.5, y(l)); ctx.stroke()
    const yO = y(o), yC = y(cl)
    ctx.fillRect(xC - Math.floor(bw / 2), Math.min(yO, yC), bw, Math.max(1, Math.abs(yC - yO)))
    ctx.restore()
    const vh = Math.max(1, Math.round((c.v / maxV) * (volH - 4)))
    ctx.fillStyle = rising ? 'rgba(16,185,129,0.28)' : 'rgba(239,68,68,0.28)'
    ctx.fillRect(xC - Math.floor(bw / 2), H - padB - vh, bw, vh)
  })

  // last-price dashed line + axis price tag
  const lastC = parseFloat(cs[n - 1].c)
  const lastY = y(lastC)
  ctx.strokeStyle = `rgba(${accentRgb}, 0.7)`
  ctx.setLineDash([4, 4])
  ctx.beginPath(); ctx.moveTo(padL, lastY); ctx.lineTo(W - padR, lastY); ctx.stroke()
  ctx.setLineDash([])
  const tag = fmtPx(lastC)
  const tw = ctx.measureText(tag).width + 10
  ctx.fillStyle = `rgba(${accentRgb}, 0.18)`
  ctx.strokeStyle = `rgba(${accentRgb}, 0.55)`
  ctx.beginPath()
  if (typeof (ctx as any).roundRect === 'function') (ctx as any).roundRect(W - padR + 2, lastY - 8, tw, 16, 4)
  else ctx.rect(W - padR + 2, lastY - 8, tw, 16)
  ctx.fill(); ctx.stroke()
  ctx.fillStyle = `rgba(${accentRgb}, 1)`
  ctx.font = 'bold 10px ui-monospace, monospace'
  ctx.fillText(tag, W - padR + 7, lastY + 3)
}

function timeLabel(t: string): string {
  const d = new Date(t)
  if (spanMs > 48 * 3600 * 1000) return d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
  return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', hour12: false })
}

function fmtPx(p: number): string {
  if (p >= 1000) return p.toFixed(0)
  if (p >= 1) return p.toFixed(2)
  return p.toPrecision(3)
}

function onMove(ev: MouseEvent) {
  if (!geom || !props.candles.length || !canvasEl.value) { onLeave(); return }
  const rect = canvasEl.value.getBoundingClientRect()
  const x = ev.clientX - rect.left
  const i = Math.min(geom.n - 1, Math.max(0, Math.floor((x - geom.x0) / geom.cw)))
  const c = props.candles[i]
  if (!c) { onLeave(); return }
  crossX.value = geom.x0 + i * geom.cw + Math.floor(geom.cw / 2)
  const d = new Date(c.t)
  emit('hover', {
    label: `${d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' })}`,
    o: fmtPx(parseFloat(c.o)), h: fmtPx(parseFloat(c.h)),
    l: fmtPx(parseFloat(c.l)), c: fmtPx(parseFloat(c.c)),
    v: c.v, rising: parseFloat(c.c) >= parseFloat(c.o),
  })
}

function onLeave() {
  crossX.value = null
  emit('hover', null)
}

watch(() => props.candles, draw, { deep: true })
onMounted(() => {
  draw()
  resizeObs = new ResizeObserver(draw)
  if (wrapEl.value) resizeObs.observe(wrapEl.value)
})
onBeforeUnmount(() => { resizeObs?.disconnect() })
</script>

<style scoped>
.cc-wrap { position: relative; width: 100%; }
.cc-canvas { display: block; width: 100%; cursor: crosshair; }
.cc-cross {
  position: absolute; top: 12px; bottom: 16px; width: 0; pointer-events: none;
  border-left: 1px dashed rgba(var(--nc-primary-rgb), 0.45);
}
.cc-empty {
  position: absolute; inset: 0; display: grid; place-items: center;
  font-size: 12px; color: rgba(var(--nc-primary-rgb), 0.45); font-family: ui-monospace, monospace;
}
</style>
