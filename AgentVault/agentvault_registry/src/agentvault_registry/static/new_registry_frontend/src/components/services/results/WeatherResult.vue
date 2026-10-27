<template>
  <div v-if="c">
    <div class="svc-row" style="justify-content:space-between;align-items:flex-start;margin-bottom:.75rem">
      <div>
        <div style="font-size:2.3rem;font-weight:800;line-height:1;color:#fff">{{ round(c.temperature_c) }}°<span style="font-size:1rem;color:var(--svc-dim);font-weight:600"> C</span></div>
        <div class="svc-dim" style="font-size:.8rem;margin-top:.3rem">{{ c.condition || '—' }}</div>
      </div>
      <div style="text-align:right">
        <div style="font-weight:700;font-size:.9rem">{{ loc.name || 'Location' }}</div>
        <div class="svc-faint" style="font-size:.7rem">{{ loc.country || '' }}</div>
      </div>
    </div>
    <div class="svc-stat-grid">
      <div class="svc-stat"><div class="svc-stat-label">Feels like</div><div class="svc-stat-value">{{ round(c.feels_like_c) }}°</div></div>
      <div class="svc-stat"><div class="svc-stat-label">Humidity</div><div class="svc-stat-value">{{ val(c.humidity_pct) }}<span style="font-size:.8rem">%</span></div></div>
      <div class="svc-stat"><div class="svc-stat-label">Wind</div><div class="svc-stat-value">{{ round(c.wind_speed_kmh) }}<span style="font-size:.7rem"> km/h</span></div></div>
      <div class="svc-stat"><div class="svc-stat-label">UV index</div><div class="svc-stat-value">{{ val(c.uv_index) }}</div></div>
    </div>
    <div v-if="fc.length" class="svc-wrap" style="margin-top:.7rem">
      <div v-for="(d, i) in fc.slice(0, 5)" :key="i" class="svc-soft" style="flex:1;min-width:78px;padding:.55rem .4rem;text-align:center">
        <div class="svc-stat-label">{{ dow(d.date) }}</div>
        <div style="font-weight:700;margin:.25rem 0;font-size:.84rem">{{ round(d.temp_max_c) }}° <span class="svc-faint" style="font-weight:500">{{ round(d.temp_min_c) }}°</span></div>
        <div class="svc-faint" style="font-size:.58rem;line-height:1.2">{{ d.condition || '' }}</div>
      </div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const c = computed(() => props.data?.current)
const loc = computed(() => props.data?.location || {})
const fc = computed(() => props.data?.forecast || [])
const round = (n: any) => (n == null || n === '' ? '—' : Math.round(Number(n)))
const val = (n: any) => (n == null || n === '' ? '—' : n)
const dow = (s: string) => { try { return new Date(s).toLocaleDateString(appLocale(), { weekday: 'short' }) } catch { return s } }
</script>
