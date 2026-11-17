<template>
  <nav class="pt" :aria-label="t('proxy.tabs.aria', 'TheProtocol Proxy')" data-testid="proxy-tabs">
    <RouterLink v-for="x in items" :key="x.name" :to="{ name: x.name }" class="pt-a" :class="{ on: current === x.name }" :aria-current="current === x.name ? 'page' : undefined" :data-testid="`proxy-tab-${x.name}`">{{ x.label }}</RouterLink>
  </nav>
</template>

<script setup lang="ts">
// V0664 C3 (order gwo_4110e12c11a69a93de878829): the proxy console's three pages, the shape of C4's migrate tabs.
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ current: string }>()
const { t } = useI18n()
const items = computed(() => [
  { name: 'proxy', label: t('proxy.tabs.overview', 'Overview') },
  { name: 'proxy-new', label: t('proxy.tabs.build', 'Build a spec') },
  { name: 'proxy-mine', label: t('proxy.tabs.mine', 'My proxies') },
])
void props
</script>

<style scoped>
.pt { display: flex; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; gap: 2px; border-bottom: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .18); }
.pt::-webkit-scrollbar { display: none; }
.pt-a { flex: none; white-space: nowrap; padding: 10px 14px; font: 700 11px/1 'IBM Plex Mono', monospace; letter-spacing: .05em; text-transform: uppercase; color: #8b97a6; text-decoration: none; border-bottom: 2px solid transparent; min-height: 40px; display: inline-flex; align-items: center; }
.pt-a:hover { color: #e8eaed; }
.pt-a.on { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.pt-a:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .6); outline-offset: -2px; }
@media (max-width: 640px) { .pt-a { padding: 10px 11px; font-size: 10.5px; } }
</style>
