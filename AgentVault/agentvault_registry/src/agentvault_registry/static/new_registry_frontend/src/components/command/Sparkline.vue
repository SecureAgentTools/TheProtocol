<template>
  <!-- GCC P8 — tiny dependency-free latency sparkline (client-side ring buffer). -->
  <svg
    v-if="points.length >= 2"
    class="gcs" :width="width" :height="height"
    :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" aria-hidden="true"
  >
    <polyline :points="path" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" />
    <circle :cx="lastX" :cy="lastY" r="1.8" fill="currentColor" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ points: number[]; width?: number; height?: number }>(), {
  width: 64,
  height: 16,
})

const coords = computed(() => {
  const pts = props.points
  const n = pts.length
  if (n < 2) return [] as Array<[number, number]>
  const min = Math.min(...pts)
  const max = Math.max(...pts)
  const span = max - min || 1
  const padY = 2
  return pts.map((v, i) => [
    (i / (n - 1)) * (props.width - 2) + 1,
    props.height - padY - ((v - min) / span) * (props.height - padY * 2),
  ] as [number, number])
})
const path = computed(() => coords.value.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '))
const lastX = computed(() => coords.value.length ? coords.value[coords.value.length - 1][0] : 0)
const lastY = computed(() => coords.value.length ? coords.value[coords.value.length - 1][1] : 0)
</script>

<style scoped>
.gcs { display: inline-block; vertical-align: middle; opacity: .85; }
</style>
