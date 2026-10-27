<template>
  <div class="pmark-wrap" :style="{ width: size + 'px', height: size + 'px' }" :class="{ 'pmark-alive': alive }">
    <svg viewBox="0 0 200 200" :width="size" :height="size" class="pmark">
      <defs>
        <!-- Main red gradient -->
        <linearGradient :id="gradId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#FF3838" />
          <stop offset="50%" stop-color="#DC2626" />
          <stop offset="100%" stop-color="#7F1D1D" />
        </linearGradient>
        <!-- Bright accent gradient (used for shine sweep) -->
        <linearGradient :id="shineId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0" />
          <stop offset="45%" stop-color="#FECACA" stop-opacity="0" />
          <stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.85" />
          <stop offset="55%" stop-color="#FECACA" stop-opacity="0" />
          <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0" />
        </linearGradient>
        <!-- Scanline pattern -->
        <pattern :id="scanId" x="0" y="0" width="100%" height="6" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="100%" y2="0" stroke="#000" stroke-width="1.5" opacity="0.5" />
        </pattern>
        <!-- Mask: only show shine inside the chevron shapes -->
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

      <!-- Animated shine sweep (only visible when alive=true) -->
      <g :mask="`url(#${maskId})`" v-if="alive" class="pmark-shine-group">
        <rect x="0" y="-50" width="200" height="80" :fill="`url(#${shineId})`" class="pmark-shine" />
      </g>

      <!-- Center pulse dot (boot indicator) -->
      <circle v-if="alive" cx="100" cy="100" r="3" fill="#FECACA" class="pmark-core" />
    </svg>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  size?: number | string
  glow?: boolean
  alive?: boolean
}>(), { size: 32, glow: false, alive: false })

const uid = Math.random().toString(36).slice(2, 8)
const gradId = `pmark-g-${uid}`
const shineId = `pmark-s-${uid}`
const scanId = `pmark-sc-${uid}`
const maskId = `pmark-m-${uid}`
</script>

<style scoped>
.pmark-wrap {
  display: inline-block;
  position: relative;
  /* Default soft glow when glow prop is set via parent */
}
.pmark { display: block; position: relative; z-index: 2; }

/* Alive mode: drop-shadow breathing, scan sweep, core pulse */
.pmark-alive .pmark {
  filter: drop-shadow(0 0 8px rgba(220, 38, 38, 0.55));
  animation: pmark-breathe 3.6s ease-in-out infinite;
}

@keyframes pmark-breathe {
  0%, 100% {
    filter: drop-shadow(0 0 6px rgba(220, 38, 38, 0.45)) drop-shadow(0 0 14px rgba(220, 38, 38, 0.18));
  }
  50% {
    filter: drop-shadow(0 0 18px rgba(255, 56, 56, 0.85)) drop-shadow(0 0 36px rgba(220, 38, 38, 0.45));
  }
}

/* Scary scan sweep — bright band travels top→bottom every 5s */
.pmark-shine {
  animation: pmark-sweep 5s ease-in-out infinite;
  transform-origin: center;
}
@keyframes pmark-sweep {
  0% { transform: translateY(-30px); opacity: 0; }
  10% { opacity: 1; }
  50% { opacity: 1; }
  85% { transform: translateY(220px); opacity: 0.6; }
  100% { transform: translateY(220px); opacity: 0; }
}

/* Center boot dot — slow blink */
.pmark-core {
  animation: pmark-blink 2.4s ease-in-out infinite;
  transform-origin: center;
}
@keyframes pmark-blink {
  0%, 90%, 100% { opacity: 0.2; r: 2; }
  45% { opacity: 1; r: 4; }
}

/* Shape: subtle saturation pulse synced with breathing */
.pmark-alive .pmark-shape {
  animation: pmark-saturate 3.6s ease-in-out infinite;
}
@keyframes pmark-saturate {
  0%, 100% { filter: saturate(1) brightness(1); }
  50% { filter: saturate(1.4) brightness(1.15); }
}

/* Static glow (when glow=true but alive=false) */
.pmark-wrap:not(.pmark-alive) .pmark {
  filter: drop-shadow(0 0 4px rgba(220, 38, 38, 0.3));
}

/* Hover jitter — subtle "scary alive" interaction */
.pmark-alive:hover .pmark {
  animation: pmark-glitch 0.4s linear, pmark-breathe 3.6s ease-in-out infinite 0.4s;
}
@keyframes pmark-glitch {
  0% { transform: translate(0, 0); }
  20% { transform: translate(-1px, 1px); filter: drop-shadow(0 0 18px rgba(255, 0, 0, 1)) hue-rotate(-10deg); }
  40% { transform: translate(1px, -1px); }
  60% { transform: translate(-1px, 0); filter: drop-shadow(0 0 22px rgba(255, 56, 56, 1)); }
  80% { transform: translate(1px, 1px); }
  100% { transform: translate(0, 0); }
}
</style>
