<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  // §MCPTEST30 (V0561): null = nothing measured. The ring drew 0% in red over an empty fleet, a claim about a
  // population that was not there; it now draws an empty grey ring and a dash.
  pct: number | null
  label?: string
}>()

// Circumference of r=36 circle: 2πr ≈ 226.19
const dasharray = computed(() => `${((props.pct ?? 0) / 100) * 226} 226`)

const ringColor = computed(() => {
  if (props.pct == null) return 'var(--nc-text-muted)'
  if (props.pct >= 95) return 'var(--nc-success)'
  if (props.pct >= 80) return 'var(--nc-warning)'
  return 'var(--nc-danger)'
})
</script>

<template>
  <div class="cc-ring">
    <svg viewBox="0 0 80 80" class="cc-ring-svg">
      <circle cx="40" cy="40" r="36" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="6" />
      <circle
        cx="40" cy="40" r="36" fill="none"
        :stroke="ringColor"
        stroke-width="6"
        stroke-linecap="round"
        :stroke-dasharray="dasharray"
        transform="rotate(-90 40 40)"
        style="transition: stroke-dasharray 0.6s ease, stroke 0.4s ease;"
      />
    </svg>
    <div class="cc-ring-center">
      <div class="cc-ring-pct" :style="{ color: ringColor }" data-testid="cc-ring-pct">{{ pct == null ? '—' : `${Math.round(pct)}%` }}</div>
      <div class="cc-ring-label">{{ label || 'fleet' }}</div>
    </div>
  </div>
</template>

<style scoped>
.cc-ring { position: relative; width: 80px; height: 80px; flex-shrink: 0; }
.cc-ring-svg { width: 100%; height: 100%; }
.cc-ring-center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  pointer-events: none;
}
.cc-ring-pct { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 16px; font-weight: 600; line-height: 1; }
.cc-ring-label { font-size: 8px; letter-spacing: 0.18em; color: var(--nc-text-muted); text-transform: uppercase; margin-top: 3px; font-family: 'JetBrains Mono', ui-monospace, monospace; }
</style>
