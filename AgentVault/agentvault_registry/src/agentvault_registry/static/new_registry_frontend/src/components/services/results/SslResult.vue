<template>
  <div v-if="data && (ssl || http || data.domain)">
    <div class="svc-row" style="justify-content:space-between;align-items:flex-start;gap:1rem;margin-bottom:.6rem">
      <div style="min-width:0">
        <div style="font-weight:700;word-break:break-all">{{ data.domain }}</div>
        <div class="svc-wrap" style="margin-top:.4rem">
          <span class="svc-pill" :class="ssl.valid ? 'is-ok' : 'is-danger'">SSL {{ ssl.valid ? 'valid' : 'invalid' }}</span>
          <span v-if="ssl.days_until_expiry != null" class="svc-pill" :class="expiryTone">{{ ssl.days_until_expiry }}d to expiry</span>
          <span v-if="http.status_code" class="svc-pill" :class="http.status_code < 400 ? 'is-ok' : 'is-warn'">HTTP {{ http.status_code }}</span>
        </div>
      </div>
      <div v-if="score != null" style="text-align:center;flex-shrink:0">
        <div style="font-size:1.8rem;font-weight:800;line-height:1" :style="{ color: scoreColor }">{{ score }}</div>
        <div class="svc-stat-label">security</div>
      </div>
    </div>
    <div v-if="score != null" class="svc-meter" style="margin-bottom:.75rem"><div class="svc-meter-fill" :class="scoreTone" :style="{ width: score + '%' }"></div></div>
    <div class="svc-kv">
      <div class="svc-kv-row" v-if="issuerText"><span class="svc-k">Issuer</span><span class="svc-v">{{ issuerText }}</span></div>
      <div class="svc-kv-row" v-if="ssl.protocol_version"><span class="svc-k">Protocol</span><span class="svc-v is-mono">{{ ssl.protocol_version }}</span></div>
      <div class="svc-kv-row" v-if="ssl.expiry_date"><span class="svc-k">Expires</span><span class="svc-v">{{ ssl.expiry_date }}</span></div>
      <div class="svc-kv-row" v-if="http.response_time_ms != null"><span class="svc-k">Response time</span><span class="svc-v">{{ http.response_time_ms }} ms</span></div>
    </div>
    <div v-if="present.length || missing.length" style="margin-top:.7rem">
      <div class="svc-stat-label" style="margin-bottom:.35rem">Security headers</div>
      <div class="svc-wrap">
        <span v-for="h in present" :key="'p' + h" class="svc-pill is-ok" style="font-size:.54rem">{{ h }}</span>
        <span v-for="h in missing" :key="'m' + h" class="svc-pill is-danger" style="font-size:.54rem">{{ h }}</span>
      </div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const ssl = computed(() => props.data?.ssl || {})
const issuerText = computed(() => {
  const i: any = ssl.value?.issuer
  if (!i) return ''
  if (typeof i === 'string') return i
  return i.organization || i.common_name || i.O || i.CN || Object.values(i).filter((v) => typeof v === 'string')[0] || ''
})
const http = computed(() => props.data?.http || {})
const score = computed(() => {
  let s: any = http.value?.security_score
  if (s == null) return null
  if (typeof s === 'string') {
    const m = s.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+)/) // "7/10" → 70
    if (m) return Math.round((parseFloat(m[1]) / parseFloat(m[2])) * 100)
    const n = parseFloat(s); return isFinite(n) ? n : null
  }
  const n = Number(s); return isFinite(n) ? (n <= 10 ? n * 10 : n) : null
})
const toList = (v: any): string[] => (!v ? [] : Array.isArray(v) ? v : (typeof v === 'object' ? Object.keys(v) : []))
const present = computed(() => toList(http.value?.security_headers_present))
const missing = computed(() => toList(http.value?.security_headers_missing))
const scoreTone = computed(() => (score.value == null ? '' : score.value >= 80 ? 'is-ok' : score.value >= 50 ? 'is-warn' : 'is-danger'))
const scoreColor = computed(() => (score.value == null ? 'var(--svc-ink)' : score.value >= 80 ? 'var(--svc-ok)' : score.value >= 50 ? 'var(--svc-warn)' : 'var(--svc-danger)'))
const expiryTone = computed(() => { const d = ssl.value?.days_until_expiry; return d > 30 ? 'is-ok' : d > 7 ? 'is-warn' : 'is-danger' })
</script>
