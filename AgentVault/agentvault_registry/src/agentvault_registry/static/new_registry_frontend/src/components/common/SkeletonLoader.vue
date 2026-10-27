<!--
  SkeletonLoader.vue — shimmer placeholder blocks for loading states.

  Usage:
    <SkeletonLoader variant="text" :rows="4" />
    <SkeletonLoader variant="list" :rows="3" />
    <SkeletonLoader variant="stat" />
    <SkeletonLoader variant="card" />
    <SkeletonLoader variant="block" width="100%" height="180px" />

  Honours prefers-reduced-motion (falls back to a soft pulse).
-->
<template>
  <div class="sk" role="status" aria-busy="true" :aria-label="label">
    <!-- TEXT: stacked lines, last line shorter -->
    <template v-if="variant === 'text'">
      <div
        v-for="n in rows"
        :key="n"
        class="sk-bar sk-shimmer"
        :style="{ width: n === rows && rows > 1 ? '62%' : '100%' }"
      />
    </template>

    <!-- LIST: square + two lines per row -->
    <template v-else-if="variant === 'list'">
      <div v-for="n in rows" :key="n" class="sk-list-row">
        <div class="sk-square sk-shimmer" />
        <div class="sk-list-lines">
          <div class="sk-bar sk-shimmer" style="width: 70%" />
          <div class="sk-bar sk-bar--sm sk-shimmer" style="width: 45%" />
        </div>
      </div>
    </template>

    <!-- STAT: chip + big value + label (mirrors StatCard) -->
    <template v-else-if="variant === 'stat'">
      <div class="sk-square sk-square--lg sk-shimmer" />
      <div class="sk-bar sk-bar--lg sk-shimmer" style="width: 55%; margin-top: 0.9rem" />
      <div class="sk-bar sk-bar--sm sk-shimmer" style="width: 38%; margin-top: 0.55rem" />
    </template>

    <!-- CARD: header line + body lines inside a framed block -->
    <template v-else-if="variant === 'card'">
      <div class="sk-card">
        <div class="sk-bar sk-bar--lg sk-shimmer" style="width: 48%" />
        <div class="sk-bar sk-shimmer" style="width: 100%; margin-top: 1rem" />
        <div class="sk-bar sk-shimmer" style="width: 92%" />
        <div class="sk-bar sk-shimmer" style="width: 78%" />
      </div>
    </template>

    <!-- BLOCK: single configurable rectangle -->
    <template v-else>
      <div class="sk-bar sk-shimmer" :style="{ width, height }" />
    </template>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'text' | 'list' | 'stat' | 'card' | 'block'
  rows?: number
  width?: string
  height?: string
  label?: string
}>(), {
  variant: 'text',
  rows: 3,
  width: '100%',
  height: '120px',
  label: 'Loading…',
})
</script>

<style scoped>
.sk { display: flex; flex-direction: column; gap: 0.6rem; width: 100%; }

.sk-bar {
  height: 0.85rem;
  border-radius: 5px;
  background: var(--nc-dark, #0e1220);
}
.sk-bar--sm { height: 0.6rem; }
.sk-bar--lg { height: 1.2rem; }

.sk-square {
  width: 38px; height: 38px; flex: 0 0 auto;
  border-radius: 9px;
  background: var(--nc-dark, #0e1220);
}
.sk-square--lg { width: 46px; height: 46px; border-radius: 12px; }

.sk-list-row { display: flex; align-items: center; gap: 0.75rem; }
.sk-list-lines { flex: 1; display: flex; flex-direction: column; gap: 0.45rem; }

.sk-card {
  display: flex; flex-direction: column; gap: 0.55rem;
  padding: 1.25rem;
  border: 1px solid var(--nc-border-subtle, #232833);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.012);
}

/* shimmer sweep */
.sk-shimmer {
  position: relative;
  overflow: hidden;
}
.sk-shimmer::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(
    90deg,
    transparent 0,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.07) 45%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12) 50%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.07) 55%,
    transparent 100%
  );
  animation: sk-sweep 1.4s ease-in-out infinite;
}

@keyframes sk-sweep {
  100% { transform: translateX(100%); }
}

@media (prefers-reduced-motion: reduce) {
  .sk-shimmer::after { animation: none; }
  .sk-shimmer { animation: sk-pulse 1.6s ease-in-out infinite; }
  @keyframes sk-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
}
</style>
