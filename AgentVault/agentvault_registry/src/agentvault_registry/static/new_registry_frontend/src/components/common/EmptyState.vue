<!--
  EmptyState.vue — shared empty / zero-data state.
  Generalises the `.mc-estate` pattern shipped in MissionControl.vue
  (icon-in-soft-square + title + subtext + optional CTA).

  Usage:
    <EmptyState
      icon="mdi:telescope" accent="purple"
      title="No rankings yet"
      subtitle="Reputation builds as agents transact"
      cta-label="Explore agents" cta-to="/discovery" />

    <EmptyState title="Nothing here" cta-label="Refresh" @cta="reload" />

  Slots:  #icon (override the icon), #default (extra content under subtitle),
          #cta (fully custom action area).
-->
<template>
  <div class="es" :class="[`es--${accent}`, { 'es--dense': dense }]">
    <div class="es-icon">
      <slot name="icon"><Icon :name="icon" /></slot>
    </div>
    <p class="es-title">{{ title }}</p>
    <p v-if="subtitle" class="es-sub">{{ subtitle }}</p>

    <slot />

    <slot name="cta">
      <RouterLink v-if="ctaTo" :to="ctaTo" class="es-cta">
        {{ ctaLabel }} <span class="es-cta-arrow" aria-hidden="true">→</span>
      </RouterLink>
      <button v-else-if="ctaLabel" type="button" class="es-cta" @click="$emit('cta')">
        {{ ctaLabel }} <span class="es-cta-arrow" aria-hidden="true">→</span>
      </button>
    </slot>
  </div>
</template>

<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import Icon from '@/components/Icon.vue'

withDefaults(defineProps<{
  icon?: string
  title: string
  subtitle?: string
  ctaLabel?: string
  ctaTo?: RouteLocationRaw
  accent?: 'primary' | 'success' | 'purple' | 'warning' | 'danger' | 'muted'
  dense?: boolean
}>(), {
  icon: 'mdi:inbox',
  accent: 'primary',
  dense: false,
})

defineEmits<{ (e: 'cta'): void }>()
</script>

<style scoped>
.es {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 0.55rem;
  padding: 2rem 1.25rem;
  min-height: 150px;
  /* per-accent rgb tuple, overridden by .es--* below */
  --es-rgb: var(--nc-primary-rgb);
}
.es--dense { padding: 1.4rem 1rem; min-height: 120px; gap: 0.45rem; }

.es--primary { --es-rgb: var(--nc-primary-rgb); }
.es--success { --es-rgb: 0, 255, 136; }
.es--purple  { --es-rgb: 139, 92, 246; }
.es--warning { --es-rgb: 255, 149, 0; }
.es--danger  { --es-rgb: 255, 51, 102; }
.es--muted   { --es-rgb: 148, 163, 184; }

.es-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.35rem;
  color: rgba(var(--es-rgb), 0.9);
  background: rgba(var(--es-rgb), 0.08);
  border: 1px solid rgba(var(--es-rgb), 0.2);
  box-shadow: 0 0 22px rgba(var(--es-rgb), 0.07) inset;
}
.es-icon :deep(svg) { width: 1.35rem; height: 1.35rem; }

.es-title {
  margin: 0.15rem 0 0;
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(255, 255, 255, 0.62);
}

.es-sub {
  margin: 0;
  max-width: 32ch;
  font-size: 0.7rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.34);
}

.es-cta {
  margin-top: 0.4rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-decoration: none;
  cursor: pointer;
  color: rgba(var(--es-rgb), 0.9);
  padding: 0.42rem 0.85rem;
  border-radius: 6px;
  border: 1px solid rgba(var(--es-rgb), 0.25);
  background: rgba(var(--es-rgb), 0.06);
  font-family: inherit;
  transition: background var(--nc-duration-fast, 200ms), border-color var(--nc-duration-fast, 200ms), transform var(--nc-duration-fast, 200ms);
}
.es-cta:hover {
  background: rgba(var(--es-rgb), 0.14);
  border-color: rgba(var(--es-rgb), 0.45);
  transform: translateY(-1px);
}
.es-cta:focus-visible {
  outline: 2px solid rgba(var(--es-rgb), 0.55);
  outline-offset: 2px;
}
.es-cta-arrow { transition: transform var(--nc-duration-fast, 200ms); }
.es-cta:hover .es-cta-arrow { transform: translateX(2px); }
</style>
