<template>
  <div v-if="data && (data.ip || loc || net)">
    <div style="font-family:var(--svc-mono);font-size:1.3rem;font-weight:700;color:#fff;margin-bottom:.6rem">{{ data.ip }}</div>
    <div class="svc-kv">
      <div class="svc-kv-row" v-if="cityLine"><span class="svc-k">Location</span><span class="svc-v">{{ cityLine }}</span></div>
      <div class="svc-kv-row" v-if="loc.country"><span class="svc-k">Country</span><span class="svc-v">{{ loc.country }}<span v-if="loc.country_code" class="svc-faint"> ({{ loc.country_code }})</span></span></div>
      <div class="svc-kv-row" v-if="loc.timezone"><span class="svc-k">Timezone</span><span class="svc-v is-mono">{{ loc.timezone }}</span></div>
      <div class="svc-kv-row" v-if="net.isp"><span class="svc-k">ISP</span><span class="svc-v">{{ net.isp }}</span></div>
      <div class="svc-kv-row" v-if="net.organization"><span class="svc-k">Organization</span><span class="svc-v">{{ net.organization }}</span></div>
      <div class="svc-kv-row" v-if="net.as_number"><span class="svc-k">AS number</span><span class="svc-v is-mono">{{ net.as_number }}</span></div>
      <div class="svc-kv-row" v-if="loc.lat != null && loc.lon != null"><span class="svc-k">Coordinates</span><span class="svc-v is-mono">{{ loc.lat }}, {{ loc.lon }}</span></div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const loc = computed(() => props.data?.location || {})
const net = computed(() => props.data?.network || {})
const cityLine = computed(() => [loc.value.city, loc.value.region].filter(Boolean).join(', '))
</script>
