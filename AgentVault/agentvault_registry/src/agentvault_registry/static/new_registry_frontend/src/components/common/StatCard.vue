<!--
  StatCard.vue — standard metric tile (icon + big value + label + optional trend pill).
  Matches the neural-command card system (surface bg, hairline border, accent chip).

  Usage:
    <StatCard icon="mdi:wallet" label="Balance" :value="balance" accent="primary"
              trend="+12.4%" trend-dir="up" sub="last 24h" />
    <StatCard icon="mdi:account-group" label="Agents" value="—" loading />

  Slots:  #icon (override), #default (extra content under the value/label).
-->
<template>
  <div class="sc" :class="[`sc--${accent}`, { 'sc--loading': loading }]">
    <div class="sc-top">
      <div v-if="icon || $slots.icon" class="sc-icon">
        <slot name="icon"><Icon :name="icon!" /></slot>
      </div>
      <span v-if="trend && !loading" class="sc-trend" :class="`sc-trend--${resolvedDir}`">
        <Icon v-if="resolvedDir !== 'flat'" :name="resolvedDir === 'up' ? 'mdi:trending-up' : 'mdi:trending-down'" class="sc-trend-ico" />
        {{ trend }}
      </span>
    </div>

    <template v-if="loading">
      <div class="sc-skel sc-skel--value" />
      <div class="sc-skel sc-skel--label" />
    </template>
    <template v-else>
      <div class="sc-value">{{ value }}</div>
      <div class="sc-label">
        {{ label }}<span v-if="sub" class="sc-sub"> · {{ sub }}</span>
      </div>
    </template>

    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'

const props = withDefaults(defineProps<{
  label: string
  value?: string | number
  icon?: string
  trend?: string | number
  trendDir?: 'up' | 'down' | 'flat'
  sub?: string
  accent?: 'primary' | 'success' | 'warning' | 'danger' | 'purple' | 'muted'
  loading?: boolean
}>(), {
  accent: 'primary',
  loading: false,
})

// Infer direction from the trend's sign when trendDir isn't given.
const resolvedDir = computed<'up' | 'down' | 'flat'>(() => {
  if (props.trendDir) return props.trendDir
  const s = String(props.trend ?? '').trim()
  if (s.startsWith('-') || s.startsWith('▼') || s.startsWith('↓')) return 'down'
  if (s.startsWith('+') || s.startsWith('▲') || s.startsWith('↑')) return 'up'
  return 'flat'
})
</script>

<style scoped>
.sc {
  --sc-rgb: var(--nc-primary-rgb);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 1.05rem 1.1rem;
  background: var(--nc-surface, #131825);
  border: 1px solid var(--nc-border-subtle, #232833);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color var(--nc-duration-fast, 200ms), transform var(--nc-duration-fast, 200ms), box-shadow var(--nc-duration-fast, 200ms);
}
.sc::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 2px;
  background: linear-gradient(90deg, rgba(var(--sc-rgb), 0.55), transparent 65%);
  opacity: 0.7;
}
.sc:hover {
  border-color: rgba(var(--sc-rgb), 0.35);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.sc--primary { --sc-rgb: var(--nc-primary-rgb); }
.sc--success { --sc-rgb: 0, 255, 136; }
.sc--warning { --sc-rgb: 255, 149, 0; }
.sc--danger  { --sc-rgb: 255, 51, 102; }
.sc--purple  { --sc-rgb: 139, 92, 246; }
.sc--muted   { --sc-rgb: 148, 163, 184; }

.sc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.2rem;
}

.sc-icon {
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 9px;
  font-size: 1.05rem;
  color: rgba(var(--sc-rgb), 0.92);
  background: rgba(var(--sc-rgb), 0.09);
  border: 1px solid rgba(var(--sc-rgb), 0.2);
}
.sc-icon :deep(svg) { width: 1.05rem; height: 1.05rem; }

.sc-trend {
  display: inline-flex; align-items: center; gap: 0.2rem;
  font-size: 0.64rem; font-weight: 700; letter-spacing: 0.03em;
  padding: 0.2rem 0.45rem;
  border-radius: 999px;
  white-space: nowrap;
}
.sc-trend-ico { width: 0.8rem; height: 0.8rem; }
.sc-trend-ico :deep(svg) { width: 0.8rem; height: 0.8rem; }
.sc-trend--up   { color: #00ff88; background: rgba(0, 255, 136, 0.1);  border: 1px solid rgba(0, 255, 136, 0.22); }
.sc-trend--down { color: #ff3366; background: rgba(255, 51, 102, 0.1); border: 1px solid rgba(255, 51, 102, 0.22); }
.sc-trend--flat { color: rgba(255,255,255,0.5); background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); }

.sc-value {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--nc-text-primary, #e8eaed);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

.sc-label {
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--nc-text-muted, rgba(255,255,255,0.45));
}
.sc-sub { color: rgba(255, 255, 255, 0.3); text-transform: none; letter-spacing: 0; font-weight: 500; }

/* loading shimmer (self-contained so StatCard stays standalone) */
.sc-skel {
  border-radius: 5px;
  background: var(--nc-dark, #0e1220);
  position: relative; overflow: hidden;
}
.sc-skel--value { height: 1.5rem; width: 58%; }
.sc-skel--label { height: 0.66rem; width: 40%; margin-top: 0.3rem; }
.sc-skel::after {
  content: ''; position: absolute; inset: 0; transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(var(--sc-rgb), 0.12), transparent);
  animation: sc-sweep 1.4s ease-in-out infinite;
}
@keyframes sc-sweep { 100% { transform: translateX(100%); } }
@media (prefers-reduced-motion: reduce) { .sc-skel::after { animation: none; } }
</style>
