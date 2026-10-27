<template>
  <div v-if="headlines.length">
    <a v-for="(h, i) in headlines.slice(0, 8)" :key="i" class="news-item" :href="safeExternalUrl(h.link)" target="_blank" rel="noopener noreferrer">
      <span class="news-title">{{ h.title }}</span>
      <span class="news-meta">
        <span v-if="h.source" class="svc-pill is-muted" style="font-size:.5rem">{{ h.source }}</span>
        <span v-if="h.published" class="svc-faint" style="font-size:.6rem">{{ h.published }}</span>
      </span>
    </a>
    <div v-if="data.sources_queried && data.sources_queried.length" class="svc-faint" style="font-size:.6rem;margin-top:.5rem">Sources: {{ data.sources_queried.join(', ') }}</div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const headlines = computed(() => props.data?.headlines || [])
</script>

<style scoped>
.news-item { display: flex; flex-direction: column; gap: 0.3rem; padding: 0.6rem 0; border-bottom: 1px solid var(--svc-line-soft); text-decoration: none; transition: padding-left 0.15s ease; }
.news-item:last-child { border-bottom: 0; }
.news-item:hover { padding-left: 0.3rem; }
.news-title { font-size: 0.78rem; font-weight: 600; color: var(--svc-ink); line-height: 1.35; }
.news-item:hover .news-title { color: var(--svc); }
.news-meta { display: flex; align-items: center; gap: 0.5rem; }
</style>
