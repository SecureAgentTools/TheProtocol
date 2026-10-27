<template>
  <div class="fmp" :class="{ 'has-pin': !!point }">
    <svg
      ref="svgRef"
      class="fmp-map"
      :viewBox="`0 0 ${W} ${H}`"
      :style="{ aspectRatio: `${W} / ${H}` }"
      role="group"
      :aria-label="label"
      aria-roledescription="map"
      tabindex="0"
      data-testid="fc-map"
      @click="onClick"
      @keydown="onKey"
    >
      <g :transform="`translate(0, ${-topPx})`">
        <image
          v-for="tile in tiles"
          :key="tile.href"
          :href="safeExternalUrl(tile.href)"
          :x="tile.x"
          :y="tile.y"
          :width="TILE"
          :height="TILE"
          preserveAspectRatio="none"
        />
      </g>
      <rect class="fmp-shade" x="0" y="0" :width="W" :height="H" />
      <g class="fmp-grid" aria-hidden="true">
        <line v-for="x in meridians" :key="`m${x}`" :x1="x" :x2="x" y1="0" :y2="H" />
        <line v-for="y in parallels" :key="`p${y}`" x1="0" :x2="W" :y1="y" :y2="y" />
      </g>
      <g v-if="point" class="fmp-pin" :transform="`translate(${point.x}, ${point.y})`" data-testid="fc-map-pin">
        <circle class="fmp-pin-pulse" r="16" />
        <circle class="fmp-pin-ring" r="8" />
        <circle class="fmp-pin-dot" r="3.5" />
      </g>
    </svg>
    <div class="fmp-readout" aria-live="polite">
      <Icon name="mdi:crosshairs-gps" class="fmp-readout-icon" />
      <span v-if="point" class="fmp-coords">{{ latNumber }}, {{ lngNumber }}</span>
      <span v-else>{{ hint }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
/**
 * The frame request's location picker: the self-hosted basemap (Web Mercator, zoom 2 = 4 x 4 tiles of 256 px) cropped
 * to the latitude band people live in, a pin where the draft's coordinates point, a click to move it and the arrow
 * keys to nudge it (Shift: 5 degrees). The math is frameRequestForm.ts's, so the tests pin it rather than this file.
 */
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { MAP_BAND, coordinate, fromMapPoint, mercatorBandRange, toMapPoint } from '@/services/frameRequestForm'

// `label`, not `ariaLabel`: a component prop spelled aria-label in a template is read as the native attribute.
const props = defineProps<{ lat: string; lng: string; hint: string; label: string }>()
const emit = defineEmits<{ (e: 'pick', value: { lat: number; lng: number }): void }>()

const TILE = 256
const W = TILE * 4
const band = mercatorBandRange()
const topPx = band.top * W
const H = Math.round((band.bottom - band.top) * W)

const svgRef = ref<SVGSVGElement | null>(null)

const tiles = computed(() => {
  const out: { href: string; x: number; y: number }[] = []
  for (let row = 0; row < 4; row++) {
    if ((row + 1) * TILE <= topPx || row * TILE >= topPx + H) continue
    for (let col = 0; col < 4; col++) out.push({ href: `/assets/basemap/2/${col}/${row}.png`, x: col * TILE, y: row * TILE })
  }
  return out
})

const meridians = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150].map(lng => ((lng + 180) / 360) * W)
const parallels = [60, 30, 0, -30].map(lat => toMapPoint(lat, 0, W, H).y)

const latNumber = computed(() => coordinate(props.lat))
const lngNumber = computed(() => coordinate(props.lng))
const point = computed(() => {
  const lat = latNumber.value
  const lng = lngNumber.value
  if (lat === null || lng === null || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null
  return toMapPoint(lat, lng, W, H)
})

function onClick(event: MouseEvent) {
  const el = svgRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const x = ((event.clientX - rect.left) / rect.width) * W
  const y = ((event.clientY - rect.top) / rect.height) * H
  emit('pick', fromMapPoint(x, y, W, H))
}

const NUDGE: Record<string, [number, number]> = {
  ArrowUp: [1, 0], ArrowDown: [-1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
}

function onKey(event: KeyboardEvent) {
  const move = NUDGE[event.key]
  if (!move) return
  event.preventDefault()
  const by = event.shiftKey ? 5 : 1
  const lat = Math.min(MAP_BAND.north, Math.max(MAP_BAND.south, (latNumber.value ?? 0) + move[0] * by))
  const lng = Math.min(180, Math.max(-180, (lngNumber.value ?? 0) + move[1] * by))
  emit('pick', { lat: Math.round(lat * 100) / 100, lng: Math.round(lng * 100) / 100 })
}
</script>

<style scoped>
.fmp { display: flex; flex-direction: column; gap: 8px; }
.fmp-map {
  display: block; width: 100%; height: auto; cursor: crosshair;
  border-radius: 10px; border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  background: #05070d; outline: none;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.fmp-map:hover { border-color: rgba(var(--nc-primary-rgb), 0.38); }
.fmp-map:focus-visible { border-color: rgba(var(--nc-primary-rgb), 0.6); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.16); }
.fmp-shade { fill: rgba(var(--nc-primary-rgb), 0.05); pointer-events: none; }
.fmp-grid line { stroke: rgba(var(--nc-primary-rgb), 0.12); stroke-width: 1; stroke-dasharray: 2 6; pointer-events: none; }
.fmp-pin { pointer-events: none; }
.fmp-pin-pulse { fill: rgba(var(--nc-primary-rgb), 0.18); transform-origin: 0 0; animation: fmp-pulse 2.2s ease-out infinite; }
.fmp-pin-ring { fill: rgba(var(--nc-primary-rgb), 0.28); stroke: var(--nc-primary); stroke-width: 1.5; }
.fmp-pin-dot { fill: #fff; }
@keyframes fmp-pulse {
  0% { transform: scale(0.4); opacity: 0.9; }
  100% { transform: scale(1.6); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .fmp-pin-pulse { animation: none; opacity: 0.5; }
}
.fmp-readout {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--muted, #7d8594);
}
.fmp-readout-icon { font-size: 14px; color: var(--nc-primary); }
.fmp-coords { font-family: var(--mono, ui-monospace, monospace); color: var(--text-secondary, #b8c0cc); font-variant-numeric: tabular-nums; }
</style>
