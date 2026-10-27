<!--
  PanelHeader.vue — standard panel / section header (icon + title + optional action).

  Usage:
    <PanelHeader icon="mdi:chart-line" title="Staking" subtitle="APY by tier">
      <template #action><button class="nc-btn nc-btn-ghost">View all</button></template>
    </PanelHeader>

  Slots:  #icon (override the icon), #action (right-aligned controls),
          #default (extra inline meta after the title).
-->
<template>
  <header class="ph" :class="[`ph--${accent}`, { 'ph--divider': divider }]">
    <div class="ph-lead">
      <div v-if="icon || $slots.icon" class="ph-icon">
        <slot name="icon"><Icon :name="icon!" /></slot>
      </div>
      <div class="ph-titles">
        <div class="ph-title-row">
          <h3 class="ph-title">{{ title }}</h3>
          <slot />
        </div>
        <p v-if="subtitle" class="ph-sub">{{ subtitle }}</p>
      </div>
    </div>
    <div v-if="$slots.action" class="ph-action">
      <slot name="action" />
    </div>
  </header>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'

withDefaults(defineProps<{
  title: string
  subtitle?: string
  icon?: string
  accent?: 'primary' | 'success' | 'warning' | 'danger' | 'purple' | 'muted'
  divider?: boolean
}>(), {
  accent: 'primary',
  divider: false,
})
</script>

<style scoped>
.ph {
  --ph-rgb: var(--nc-primary-rgb);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.85rem;
}
.ph--divider { border-bottom: 1px solid var(--nc-border-subtle, #232833); margin-bottom: 1rem; }

.ph--primary { --ph-rgb: var(--nc-primary-rgb); }
.ph--success { --ph-rgb: 0, 255, 136; }
.ph--warning { --ph-rgb: 255, 149, 0; }
.ph--danger  { --ph-rgb: 255, 51, 102; }
.ph--purple  { --ph-rgb: 139, 92, 246; }
.ph--muted   { --ph-rgb: 148, 163, 184; }

.ph-lead { display: flex; align-items: center; gap: 0.7rem; min-width: 0; }

.ph-icon {
  width: 34px; height: 34px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  border-radius: 9px;
  font-size: 1rem;
  color: rgba(var(--ph-rgb), 0.92);
  background: rgba(var(--ph-rgb), 0.09);
  border: 1px solid rgba(var(--ph-rgb), 0.2);
}
.ph-icon :deep(svg) { width: 1rem; height: 1rem; }

.ph-titles { min-width: 0; }
.ph-title-row { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; }

.ph-title {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--nc-text-primary, #e8eaed);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ph-sub {
  margin: 0.15rem 0 0;
  font-size: 0.7rem;
  line-height: 1.4;
  color: var(--nc-text-muted, rgba(255,255,255,0.45));
}

.ph-action { flex: 0 0 auto; display: flex; align-items: center; gap: 0.5rem; }
</style>
