<template>
  <nav class="cct" :aria-label="t('codeChanges.tabs.aria', 'Code changes')" data-testid="cc-tabs">
    <RouterLink v-for="x in items" :key="x.name" :to="{ name: x.name }" class="cct-a" :class="{ on: current === x.name }" :aria-current="current === x.name ? 'page' : undefined" :data-testid="`cc-tab-${x.name}`">{{ x.label }}</RouterLink>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

defineProps<{ current: string }>()
const { t } = useI18n()
// the tab row is where the contributor track opens beside the changes (a tab is one entry here and one route)
const items = computed(() => [
  { name: 'code-changes', label: t('codeChanges.tabs.changes', 'Changes') },
  { name: 'code-changes-new', label: t('codeChanges.tabs.propose', 'Propose') },
  { name: 'code-changes-track', label: t('codeChanges.tabs.track', 'Track') },
])
</script>

<style scoped>
.cct { display: flex; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; gap: 2px; border-bottom: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .18); }
.cct::-webkit-scrollbar { display: none; }
.cct-a { flex: none; white-space: nowrap; padding: 10px 14px; font: 700 11px/1 'IBM Plex Mono', monospace; letter-spacing: .05em; text-transform: uppercase; color: #8b97a6; text-decoration: none; border-bottom: 2px solid transparent; min-height: 40px; display: inline-flex; align-items: center; }
.cct-a:hover { color: #e8eaed; }
.cct-a.on { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.cct-a:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .6); outline-offset: -2px; }
</style>
