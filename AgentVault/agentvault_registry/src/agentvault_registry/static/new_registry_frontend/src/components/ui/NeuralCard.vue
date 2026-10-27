<template>
  <div 
    :class="cardClasses"
    @click="handleClick"
  >
    <!-- Top Border Accent -->
    <div v-if="accent" class="nc-card-accent" :class="`nc-accent-${accent}`"></div>
    
    <!-- Scan Line Effect -->
    <div v-if="scanline" class="nc-card-scanline"></div>
    
    <!-- Header Slot -->
    <div v-if="$slots.header" class="nc-card-header">
      <slot name="header"></slot>
    </div>
    
    <!-- Main Content -->
    <div class="nc-card-body" :class="{ 'nc-card-body-padded': !noPadding }">
      <slot></slot>
    </div>
    
    <!-- Footer Slot -->
    <div v-if="$slots.footer" class="nc-card-footer">
      <slot name="footer"></slot>
    </div>
    
    <!-- Hover Glow Effect -->
    <div v-if="glow" class="nc-card-glow"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'default' | 'elevated' | 'outlined' | 'glass' | 'flat'
  accent?: 'primary' | 'success' | 'warning' | 'danger' | false
  glow?: boolean
  scanline?: boolean
  clickable?: boolean
  noPadding?: boolean
  class?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  accent: false,
  glow: false,
  scanline: false,
  clickable: false,
  noPadding: false
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

const cardClasses = computed(() => {
  const classes = ['nc-card', `nc-card-${props.variant}`]
  
  if (props.clickable) {
    classes.push('nc-card-clickable')
  }
  
  if (props.glow) {
    classes.push('nc-card-has-glow')
  }
  
  if (props.class) {
    classes.push(props.class)
  }
  
  return classes
})

const handleClick = (event: MouseEvent) => {
  if (props.clickable) {
    emit('click', event)
  }
}
</script>

<style scoped>
/* Base Card Styles */
.nc-card {
  position: relative;
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  overflow: hidden;
  transition: all var(--nc-duration-normal) var(--nc-easing-default);
}

/* Variants */

/* §DISCPANEL (2026-09-06, his "the boxes look trash") — `flat` was passed by five call sites in
   Discovery.vue and DEFINED NOWHERE: the prop type did not list it and no `.nc-card-flat` rule existed, so
   those five boxes rendered with the bare `.nc-card` base — square corners, flat surface, no hairline — beside
   agent cards built to the house language. This is that language's quiet panel (Design_Language.md §2):
   primary-tinted fill, hairline border, faint top sheen, light blur, soft shadow, and no hover lift, because a
   panel that holds a search field or a number is not a clickable tile. */
.nc-card-flat {
  background:
    linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%),
    rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 12px;
  backdrop-filter: blur(9px) saturate(1.05);
  -webkit-backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
}
.nc-card-flat:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); }

.nc-card-elevated {
  background: var(--nc-elevated);
  box-shadow: var(--nc-shadow-md);
}

.nc-card-outlined {
  background: transparent;
  border: 1px solid var(--nc-border-strong);
}

.nc-card-glass {
  background: rgba(26, 29, 40, 0.6);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(42, 47, 62, 0.5);
}

/* Clickable State */
.nc-card-clickable {
  cursor: pointer;
}

.nc-card-clickable:hover {
  background: var(--nc-elevated);
  border-color: var(--nc-border-strong);
  transform: translateY(-2px);
}

.nc-card-clickable:active {
  transform: translateY(0);
}

/* Top Accent Bar */
.nc-card-accent {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  background: var(--nc-primary);
  background-size: 200% 100%;
}

.nc-accent-primary {
  background: linear-gradient(90deg, var(--nc-primary) 0%, var(--nc-primary-bright) 50%, var(--nc-primary) 100%);
  animation: accent-shift 3s linear infinite;
}

.nc-accent-success {
  background: linear-gradient(90deg, var(--nc-success) 0%, var(--nc-success-bright) 50%, var(--nc-success) 100%);
  animation: accent-shift 3s linear infinite;
}

.nc-accent-warning {
  background: linear-gradient(90deg, var(--nc-warning) 0%, var(--nc-warning-bright) 50%, var(--nc-warning) 100%);
  animation: accent-shift 3s linear infinite;
}

.nc-accent-danger {
  background: linear-gradient(90deg, var(--nc-danger) 0%, var(--nc-danger-bright) 50%, var(--nc-danger) 100%);
  animation: accent-shift 3s linear infinite;
}

@keyframes accent-shift {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

/* Scan Line Effect */
.nc-card-scanline {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    180deg,
    transparent 0%,
    var(--nc-scan-line) 50%,
    transparent 100%
  );
  background-size: 100% 200%;
  animation: scanline-move 8s linear infinite;
  pointer-events: none;
  opacity: 0.5;
}

@keyframes scanline-move {
  0% { background-position: 0% -100%; }
  100% { background-position: 0% 100%; }
}

/* Card Sections */
.nc-card-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--nc-border-subtle);
  background: rgba(0, 0, 0, 0.2);
}

.nc-card-body {
  position: relative;
}

.nc-card-body-padded {
  padding: 1.25rem;
}

.nc-card-footer {
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--nc-border-subtle);
  background: rgba(0, 0, 0, 0.2);
}

/* Glow Effect */
.nc-card-has-glow {
  position: relative;
}

.nc-card-glow {
  position: absolute;
  inset: -1px;
  background: linear-gradient(
    45deg,
    transparent,
    var(--nc-primary-glow),
    transparent
  );
  opacity: 0;
  transition: opacity var(--nc-duration-normal);
  pointer-events: none;
  z-index: -1;
}

.nc-card-has-glow:hover .nc-card-glow {
  opacity: 1;
  animation: glow-pulse 2s ease-in-out infinite;
}

@keyframes glow-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* Responsive */
@media (max-width: 768px) {
  .nc-card-header,
  .nc-card-body-padded,
  .nc-card-footer {
    padding: 1rem;
  }
}
</style>
