<template>
  <nav ref="el" class="mt" :class="{ 'fade-l': fade.left, 'fade-r': fade.right }" :aria-label="t('migrate.tabs.aria', 'Migrate a system')" data-testid="migrate-tabs">
    <RouterLink v-for="x in items" :key="x.name" :to="{ name: x.name }" class="mt-a" :class="{ on: current === x.name }" :aria-current="current === x.name ? 'page' : undefined" :data-testid="`migrate-tab-${x.name}`">{{ x.label }}</RouterLink>
  </nav>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { edgeFade } from '@/services/migrate/tabsFade'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ current: string }>()
const { t } = useI18n()
// a row that scrolls says so: it fades at the edge that is cut off
const el = ref<HTMLElement | null>(null)
const fade = reactive({ left: false, right: false })
const measure = () => { const e = el.value; if (!e) return; const f = edgeFade(e.scrollLeft, e.clientWidth, e.scrollWidth); fade.left = f.left; fade.right = f.right }
let ro: ResizeObserver | null = null
onMounted(() => {
  measure()
  el.value?.addEventListener('scroll', measure, { passive: true })
  if (typeof ResizeObserver !== 'undefined' && el.value) { ro = new ResizeObserver(measure); ro.observe(el.value) }
  // the current tab is kept in view
  el.value?.querySelector('[aria-current="page"]')?.scrollIntoView?.({ inline: 'center', block: 'nearest' })
})
onBeforeUnmount(() => { el.value?.removeEventListener('scroll', measure); ro?.disconnect() })
const items = computed(() => [
  { name: 'migrate', label: t('migrate.tabs.library', 'Library') },
  { name: 'migrate-new', label: t('migrate.tabs.build', 'Build') },
  { name: 'migrate-mine', label: t('migrate.tabs.mine', 'My templates') },
  { name: 'migrate-runs', label: t('migrate.tabs.runs', 'My migrations') },
  { name: 'migrate-report', label: t('migrate.tabs.report', 'Read a report') },
])
void props
</script>

<style scoped>
.mt { display: flex; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; gap: 2px; border-bottom: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .18); }
.mt::-webkit-scrollbar { display: none; }
.mt-a { flex: none; white-space: nowrap; padding: 10px 14px; font: 700 11px/1 'IBM Plex Mono', monospace; letter-spacing: .05em; text-transform: uppercase; color: #8b97a6; text-decoration: none; border-bottom: 2px solid transparent; min-height: 40px; display: inline-flex; align-items: center; }
.mt-a:hover { color: #e8eaed; }
.mt-a.on { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.mt-a:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .6); outline-offset: -2px; }
.mt.fade-r { -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to right, #000 calc(100% - 36px), transparent); }
.mt.fade-l { -webkit-mask-image: linear-gradient(to left, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to left, #000 calc(100% - 36px), transparent); }
.mt.fade-l.fade-r { -webkit-mask-image: linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); mask-image: linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); }
@media (max-width: 640px) { .mt-a { padding: 10px 11px; font-size: 10.5px; } }
</style>
