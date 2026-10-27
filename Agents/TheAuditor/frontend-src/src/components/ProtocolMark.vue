<template>
  <div
    class="pmark-wrap"
    :class="[`pmark-${tone}`, { 'pmark-alive': alive }]"
    :style="{ width: size + 'px', height: size + 'px' }"
  >
    <svg viewBox="0 0 200 200" :width="size" :height="size" class="pmark">
      <defs>
        <linearGradient :id="gradId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" class="pst0" />
          <stop offset="50%" class="pst1" />
          <stop offset="100%" class="pst2" />
        </linearGradient>
        <linearGradient :id="shineId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0" />
          <stop offset="45%" stop-color="#FFFFFF" stop-opacity="0" />
          <stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.85" />
          <stop offset="55%" stop-color="#FFFFFF" stop-opacity="0" />
          <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0" />
        </linearGradient>
        <pattern :id="scanId" x="0" y="0" width="100%" height="6" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="100%" y2="0" stroke="#000" stroke-width="1.5" opacity="0.5" />
        </pattern>
        <mask :id="maskId">
          <path d="M 100 20 L 25 110 L 65 110 L 100 65 L 135 110 L 175 110 Z" fill="white" />
          <path d="M 100 180 L 25 90 L 65 90 L 100 135 L 135 90 L 175 90 Z" fill="white" />
        </mask>
      </defs>

      <!-- Top chevron -->
      <path d="M 100 20 L 25 110 L 65 110 L 100 65 L 135 110 L 175 110 Z" :fill="`url(#${gradId})`" class="pmark-shape" />
      <path d="M 100 20 L 25 110 L 65 110 L 100 65 L 135 110 L 175 110 Z" :fill="`url(#${scanId})`" />

      <!-- Bottom chevron -->
      <path d="M 100 180 L 25 90 L 65 90 L 100 135 L 135 90 L 175 90 Z" :fill="`url(#${gradId})`" opacity="0.85" class="pmark-shape" />
      <path d="M 100 180 L 25 90 L 65 90 L 100 135 L 135 90 L 175 90 Z" :fill="`url(#${scanId})`" />

      <!-- Animated shine sweep -->
      <g :mask="`url(#${maskId})`" v-if="alive" class="pmark-shine-group">
        <rect x="0" y="-50" width="200" height="80" :fill="`url(#${shineId})`" class="pmark-shine" />
      </g>

      <!-- Center core -->
      <circle cx="100" cy="100" r="3" class="pmark-core" />
    </svg>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  size?: number | string
  glow?: boolean
  alive?: boolean
  tone?: 'green' | 'red'   // auditor default = green (kryptonite); red on critical breach
}>(), { size: 32, glow: false, alive: false, tone: 'green' })

const uid = Math.random().toString(36).slice(2, 8)
const gradId = `pmark-g-${uid}`
const shineId = `pmark-s-${uid}`
const scanId = `pmark-sc-${uid}`
const maskId = `pmark-m-${uid}`
</script>

<style scoped>
.pmark-wrap { display: inline-block; position: relative; }
.pmark { display: block; position: relative; z-index: 2; transition: filter 0.45s ease; }

/* ── GREEN — the Auditor's kryptonite mark (default, glows at rest) ── */
.pmark-green .pst0 { stop-color: #86FFBE; }
.pmark-green .pst1 { stop-color: #15E05F; }
.pmark-green .pst2 { stop-color: #0A6E36; }
.pmark-green .pmark-core { fill: #D6FFE6; }
.pmark-green .pmark {
  filter: drop-shadow(0 0 6px rgba(70, 255, 150, 0.55)) drop-shadow(0 0 18px rgba(0, 200, 83, 0.30));
  animation: kryptoGlow 3.6s ease-in-out infinite;
}
@keyframes kryptoGlow {
  0%, 100% { filter: drop-shadow(0 0 5px rgba(70, 255, 150, 0.42)) drop-shadow(0 0 14px rgba(0, 200, 83, 0.20)); }
  50% { filter: drop-shadow(0 0 13px rgba(110, 255, 178, 0.85)) drop-shadow(0 0 32px rgba(0, 200, 83, 0.5)); }
}
.pmark-green .pmark-core { animation: kryptoCore 3.6s ease-in-out infinite; }
@keyframes kryptoCore { 0%, 100% { opacity: 0.45; r: 2.4; } 50% { opacity: 1; r: 3.4; } }

/* ── RED — breach klaxon (tone='red' + alive on critical) ── */
.pmark-red .pst0 { stop-color: #FF3838; }
.pmark-red .pst1 { stop-color: #DC2626; }
.pmark-red .pst2 { stop-color: #7F1D1D; }
.pmark-red .pmark-core { fill: #FECACA; }
.pmark-red .pmark { filter: drop-shadow(0 0 6px rgba(220, 38, 38, 0.5)); }
.pmark-red.pmark-alive .pmark { animation: breatheRed 1.15s ease-in-out infinite; }
@keyframes breatheRed {
  0%, 100% { filter: drop-shadow(0 0 8px rgba(255, 56, 56, 0.6)) drop-shadow(0 0 18px rgba(220, 38, 38, 0.3)); }
  50% { filter: drop-shadow(0 0 22px rgba(255, 56, 56, 1)) drop-shadow(0 0 46px rgba(220, 38, 38, 0.55)); }
}

/* Shine sweep (only when alive) + shape saturation pulse */
.pmark-shine { animation: pmark-sweep 4.5s ease-in-out infinite; transform-origin: center; }
@keyframes pmark-sweep {
  0% { transform: translateY(-30px); opacity: 0; }
  10% { opacity: 1; }
  50% { opacity: 1; }
  85% { transform: translateY(220px); opacity: 0.6; }
  100% { transform: translateY(220px); opacity: 0; }
}
.pmark-alive .pmark-shape { animation: pmark-saturate 3.0s ease-in-out infinite; }
@keyframes pmark-saturate {
  0%, 100% { filter: saturate(1) brightness(1); }
  50% { filter: saturate(1.45) brightness(1.18); }
}

/* Hover — a faint kryptonite jitter (green) */
.pmark-green:hover .pmark { animation: kryptoGlow 1.8s ease-in-out infinite; }

@media (prefers-reduced-motion: reduce) {
  .pmark-green .pmark, .pmark-green .pmark-core, .pmark-red.pmark-alive .pmark,
  .pmark-shine, .pmark-alive .pmark-shape { animation: none !important; }
}
</style>
