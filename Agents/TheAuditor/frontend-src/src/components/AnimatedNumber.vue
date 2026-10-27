<template><span>{{ display }}</span></template>

<script setup lang="ts">
/* A lightweight count-up: tweens the displayed value when `value` changes, so the
   instrument feels alive (odometer roll on the big supply figures, a gentle settle
   on the deltas). rAF-based, eased, and instant under prefers-reduced-motion. */
import { ref, watch, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  value: number
  decimals?: number
  comma?: boolean      // thousands separators
  signed?: boolean     // force a leading + on positives
  duration?: number    // ms
}>(), { decimals: 0, comma: false, signed: false, duration: 650 })

const current = ref(props.value)
const display = ref(fmt(props.value))
let raf: number | null = null

function fmt(n: number): string {
  const opts: Intl.NumberFormatOptions = {
    minimumFractionDigits: props.decimals,
    maximumFractionDigits: props.decimals,
    useGrouping: props.comma,
  }
  const s = n.toLocaleString(undefined, opts)
  return props.signed && n >= 0 ? `+${s}` : s
}

const prefersReduced = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function easeOutCubic(t: number): number { return 1 - Math.pow(1 - t, 3) }

watch(() => props.value, (to, from) => {
  if (raf) cancelAnimationFrame(raf)
  if (prefersReduced || to === from || from === undefined) {
    current.value = to
    display.value = fmt(to)
    return
  }
  const start = from
  const delta = to - start
  const t0 = performance.now()
  const step = (now: number) => {
    const p = Math.min(1, (now - t0) / props.duration)
    current.value = start + delta * easeOutCubic(p)
    display.value = fmt(current.value)
    if (p < 1) raf = requestAnimationFrame(step)
    else { display.value = fmt(to); raf = null }
  }
  raf = requestAnimationFrame(step)
})

onUnmounted(() => { if (raf) cancelAnimationFrame(raf) })
</script>
