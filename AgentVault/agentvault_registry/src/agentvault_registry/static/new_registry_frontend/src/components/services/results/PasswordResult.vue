<template>
  <div>
    <div v-if="secret">
      <div class="svc-row" style="margin-bottom:.3rem"><span class="svc-stat-label">{{ typeLabel }}</span><button class="svc-copy" @click="copy">{{ copied ? 'Copied ✓' : 'Copy' }}</button></div>
      <div class="svc-soft" style="padding:.75rem .85rem;font-family:var(--svc-mono);font-size:.98rem;color:#fff;word-break:break-all;user-select:all">{{ secret }}</div>
    </div>

    <div v-if="strengthLabel" style="margin-top:.75rem">
      <div class="svc-row" style="justify-content:space-between;margin-bottom:.3rem"><span class="svc-stat-label">Strength</span><span class="svc-v" :style="{ color: toneColor }">{{ strengthLabel }}</span></div>
      <div class="svc-meter"><div class="svc-meter-fill" :class="tone" :style="{ width: pct + '%' }"></div></div>
    </div>

    <div v-if="hasStats" class="svc-stat-grid" style="margin-top:.75rem">
      <div class="svc-stat" v-if="data.entropy_bits != null"><div class="svc-stat-label">Entropy</div><div class="svc-stat-value">{{ Math.round(Number(data.entropy_bits)) }}<span style="font-size:.7rem"> bit</span></div></div>
      <div class="svc-stat" v-if="data.length != null"><div class="svc-stat-label">Length</div><div class="svc-stat-value">{{ data.length }}</div></div>
      <div class="svc-stat" v-if="data.charset_size != null"><div class="svc-stat-label">Charset</div><div class="svc-stat-value">{{ data.charset_size }}</div></div>
      <div class="svc-stat" v-if="data.crack_time_estimate"><div class="svc-stat-label">Crack time</div><div class="svc-stat-value" style="font-size:.92rem">{{ data.crack_time_estimate }}</div></div>
    </div>

    <div v-if="issues.length" style="margin-top:.65rem">
      <div class="svc-stat-label" style="margin-bottom:.3rem">Suggestions</div>
      <div class="svc-wrap"><span v-for="(it, i) in issues" :key="i" class="svc-pill is-warn" style="font-size:.56rem">{{ it }}</span></div>
    </div>

    <JsonResult v-if="!secret && !strengthLabel && !hasStats" :data="data" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const secret = computed(() => props.data?.password || props.data?.passphrase || props.data?.api_key || props.data?.uuid || '')
const typeLabel = computed(() => String(props.data?.type || 'secret').replace(/_/g, ' '))
const issues = computed(() => props.data?.issues || [])
const hasStats = computed(() => props.data?.entropy_bits != null || props.data?.length != null || props.data?.charset_size != null || props.data?.crack_time_estimate != null)

const strengthLabel = computed(() => {
  const s = props.data?.strength
  if (typeof s === 'string' && s) return s
  if (props.data?.score != null) return ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'][Number(props.data.score)] || String(s || '')
  return ''
})
const norm = computed(() => strengthLabel.value.toLowerCase())
const pct = computed(() => {
  if (props.data?.score != null) return Math.max(8, (Number(props.data.score) / 4) * 100)
  const n = norm.value
  if (n.includes('very strong')) return 100
  if (n.includes('strong')) return 80
  if (n.includes('moderate') || n.includes('medium') || n.includes('fair') || n.includes('good')) return 55
  if (n.includes('very weak')) return 18
  if (n.includes('weak')) return 32
  return 50
})
const tone = computed(() => (pct.value >= 75 ? 'is-ok' : pct.value >= 50 ? 'is-warn' : 'is-danger'))
const toneColor = computed(() => (pct.value >= 75 ? 'var(--svc-ok)' : pct.value >= 50 ? 'var(--svc-warn)' : 'var(--svc-danger)'))

const copied = ref(false)
function copy() { try { navigator.clipboard.writeText(secret.value); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* noop */ } }
</script>
