<template>
  <div>
    <div v-if="transform">
      <div class="svc-row" style="margin-bottom:.3rem"><span class="svc-stat-label">{{ opLabel }}</span><button class="svc-copy" @click="copy">{{ copied ? 'Copied ✓' : 'Copy' }}</button></div>
      <div class="svc-soft" style="padding:.65rem .8rem;font-family:var(--svc-mono);font-size:.78rem;color:#fff;word-break:break-all;max-height:240px;overflow:auto;white-space:pre-wrap">{{ transform }}</div>
    </div>

    <template v-else-if="hasStats">
      <div class="svc-stat-grid">
        <div class="svc-stat" v-if="data.word_count != null"><div class="svc-stat-label">Words</div><div class="svc-stat-value">{{ num(data.word_count) }}</div></div>
        <div class="svc-stat" v-if="chars != null"><div class="svc-stat-label">Characters</div><div class="svc-stat-value">{{ num(chars) }}</div></div>
        <div class="svc-stat" v-if="data.sentence_count != null"><div class="svc-stat-label">Sentences</div><div class="svc-stat-value">{{ num(data.sentence_count) }}</div></div>
        <div class="svc-stat" v-if="readingTime"><div class="svc-stat-label">Reading time</div><div class="svc-stat-value" style="font-size:1rem">{{ readingTime }}</div></div>
      </div>
      <div v-if="readability != null" class="svc-kv" style="margin-top:.6rem">
        <div class="svc-kv-row"><span class="svc-k">{{ readabilityLabel }}</span><span class="svc-v">{{ readability }}</span></div>
      </div>
      <div v-if="keywords.length" style="margin-top:.65rem">
        <div class="svc-stat-label" style="margin-bottom:.3rem">Top keywords</div>
        <div class="svc-wrap"><span v-for="(k, i) in keywords" :key="i" class="svc-chip" style="cursor:default">{{ k[0] }} <span class="svc-faint" style="margin-left:.25rem">{{ k[1] }}</span></span></div>
      </div>
    </template>

    <JsonResult v-else :data="data" />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const d = computed(() => props.data || {})
const transform = computed(() => d.value.result || d.value.output || d.value.hash || d.value.transformed || '')
const opLabel = computed(() => String(d.value.operation || d.value.op || (d.value.hash ? 'Hash' : 'Result')).replace(/_/g, ' '))
const chars = computed(() => d.value.char_count ?? d.value.character_count ?? d.value.chars)
const hasStats = computed(() => d.value.word_count != null || chars.value != null)
const readingTime = computed(() => {
  const r = d.value.reading_time ?? d.value.reading_time_minutes ?? d.value.reading_time_min
  if (r == null) return ''
  return typeof r === 'number' ? `${r} min` : String(r)
})
const readability = computed(() => d.value.readability ?? d.value.flesch_reading_ease ?? d.value.flesch_kincaid_grade ?? null)
const readabilityLabel = computed(() => (d.value.flesch_kincaid_grade != null && d.value.readability == null && d.value.flesch_reading_ease == null ? 'Grade level' : 'Readability'))
const keywords = computed(() => {
  const kd = d.value.keyword_density || d.value.keywords
  if (Array.isArray(kd)) return kd.slice(0, 8).map((x: any) => (Array.isArray(x) ? x : [x.word || x.term || x, x.count ?? x.density ?? '']))
  if (kd && typeof kd === 'object') return Object.entries(kd).sort((a: any, b: any) => Number(b[1]) - Number(a[1])).slice(0, 8)
  return []
})
const num = (n: any) => (n == null ? '—' : Number(n).toLocaleString(appLocale()))
const copied = ref(false)
function copy() { try { navigator.clipboard.writeText(String(transform.value)); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* noop */ } }
</script>
