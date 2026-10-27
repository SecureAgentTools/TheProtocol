<template>
  <div class="dc-wrap" :style="{ height: height + 'px' }">
    <svg v-if="ready" class="dc-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none">
      <polygon v-if="geo.bidPoly" :points="geo.bidPoly" class="dc-area dc-bid" />
      <polygon v-if="geo.askPoly" :points="geo.askPoly" class="dc-area dc-ask" />
      <polyline v-if="geo.bidLine" :points="geo.bidLine" class="dc-edge dc-bid" />
      <polyline v-if="geo.askLine" :points="geo.askLine" class="dc-edge dc-ask" />
      <line :x1="geo.midX" :x2="geo.midX" y1="0" :y2="H" class="dc-mid" />
    </svg>
    <div v-if="ready" class="dc-tags">
      <span class="dc-tag bid" v-if="geo.bestBid">BID {{ geo.bestBid }}</span>
      <span class="dc-tag mid" v-if="geo.midPx">MID {{ geo.midPx }}</span>
      <span class="dc-tag ask" v-if="geo.bestAsk">ASK {{ geo.bestAsk }}</span>
    </div>
    <div v-else class="dc-empty">
      <Icon name="mdi:chart-line" />
      <span>depth draws from resting liquidity — book is thin</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AGORA DepthChart — dependency-free cumulative bid/ask area (2026-06-12).
 * Step-accurate market depth: at any price the curve is the total resting
 * size at-or-better. SVG with preserveAspectRatio=none + non-scaling strokes.
 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'

interface Level { price: string; qty: number }
const props = withDefaults(defineProps<{ bids: Level[]; asks: Level[]; height?: number }>(), { height: 132 })

const W = 600
const H = 100

function fmtPx(v: number): string {
  if (!isFinite(v)) return '—'
  if (v >= 1000) return v.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
  if (v >= 1) return v.toFixed(2)
  return v.toPrecision(3)
}

const sides = computed(() => ({
  // backend order: bids best-first (desc price), asks best-first (asc price)
  bids: props.bids.map(l => ({ p: parseFloat(l.price), q: l.qty })).filter(l => l.p > 0 && l.q > 0),
  asks: props.asks.map(l => ({ p: parseFloat(l.price), q: l.qty })).filter(l => l.p > 0 && l.q > 0),
}))
const ready = computed(() => sides.value.bids.length + sides.value.asks.length >= 2)

const geo = computed(() => {
  const { bids, asks } = sides.value
  const bestBid = bids[0]?.p
  const bestAsk = asks[0]?.p
  const mid = bestBid && bestAsk ? (bestBid + bestAsk) / 2 : (bestBid ?? bestAsk ?? 0)

  let lo = bids.length ? bids[bids.length - 1].p : mid
  let hi = asks.length ? asks[asks.length - 1].p : mid
  // one-sided book: mirror the present side's span so the mid sits centered
  if (!bids.length) lo = mid - (hi - mid || mid * 0.05)
  if (!asks.length) hi = mid + (mid - lo || mid * 0.05)
  const span = (hi - lo) || mid * 0.02 || 1
  lo -= span * 0.04
  hi += span * 0.04

  const cum = (ls: { p: number; q: number }[]) => {
    let c = 0
    return ls.map(l => ({ p: l.p, c: (c += l.q) }))
  }
  const bSteps = cum(bids)
  const aSteps = cum(asks)
  const maxC = Math.max(bSteps[bSteps.length - 1]?.c ?? 0, aSteps[aSteps.length - 1]?.c ?? 0, 1)

  const x = (p: number) => ((p - lo) / (hi - lo)) * W
  const y = (c: number) => H - (c / maxC) * (H - 10)

  // walk outward from best price, holding depth flat between levels (step area)
  const stepPts = (steps: { p: number; c: number }[], edgeX: number) => {
    if (!steps.length) return ''
    const pts: string[] = [`${x(steps[0].p).toFixed(1)},${H}`]
    let prevC = 0
    for (const s of steps) {
      pts.push(`${x(s.p).toFixed(1)},${y(prevC).toFixed(1)}`)
      pts.push(`${x(s.p).toFixed(1)},${y(s.c).toFixed(1)}`)
      prevC = s.c
    }
    pts.push(`${edgeX.toFixed(1)},${y(prevC).toFixed(1)}`)
    return pts.join(' ')
  }
  const bidLine = stepPts(bSteps, x(lo))
  const askLine = stepPts(aSteps, x(hi))

  return {
    midX: x(mid).toFixed(1),
    midPx: mid ? fmtPx(mid) : '',
    bestBid: bestBid ? fmtPx(bestBid) : '',
    bestAsk: bestAsk ? fmtPx(bestAsk) : '',
    bidLine,
    askLine,
    bidPoly: bidLine ? `${bidLine} ${x(lo).toFixed(1)},${H}` : '',
    askPoly: askLine ? `${askLine} ${x(hi).toFixed(1)},${H}` : '',
  }
})
</script>

<style scoped>
.dc-wrap { position: relative; width: 100%; }
.dc-svg { width: 100%; height: calc(100% - 18px); display: block; }
.dc-area.dc-bid { fill: rgba(16, 185, 129, 0.16); }
.dc-area.dc-ask { fill: rgba(239, 68, 68, 0.13); }
.dc-edge { fill: none; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.dc-edge.dc-bid { stroke: #10b981; }
.dc-edge.dc-ask { stroke: #ef4444; }
.dc-mid { stroke: rgba(var(--nc-primary-rgb), 0.55); stroke-dasharray: 4 4; vector-effect: non-scaling-stroke; }
.dc-tags { display: flex; justify-content: space-between; align-items: center; height: 18px; font-family: ui-monospace, monospace; font-size: 9px; letter-spacing: 0.08em; }
.dc-tag { font-variant-numeric: tabular-nums; }
.dc-tag.bid { color: #10b981; }
.dc-tag.ask { color: #ef4444; }
.dc-tag.mid { color: rgba(var(--nc-primary-rgb), 0.85); }
.dc-empty {
  position: absolute; inset: 0; display: flex; flex-direction: column; gap: 6px;
  align-items: center; justify-content: center; text-align: center;
  font-size: 11px; color: rgba(var(--nc-primary-rgb), 0.45); font-family: ui-monospace, monospace;
}
.dc-empty :deep(svg) { width: 22px; height: 22px; opacity: 0.7; }
</style>
