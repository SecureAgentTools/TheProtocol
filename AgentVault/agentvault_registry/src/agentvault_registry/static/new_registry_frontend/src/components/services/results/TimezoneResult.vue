<template>
  <div v-if="data && (data.time_24h || data.current_time)">
    <div style="text-align:center;margin-bottom:.65rem">
      <div style="font-family:var(--svc-mono);font-size:2.4rem;font-weight:700;color:#fff;letter-spacing:.04em;line-height:1">{{ data.time_24h || data.current_time }}</div>
      <div class="svc-dim" style="font-size:.82rem;margin-top:.3rem">{{ data.date || '' }}</div>
    </div>
    <div class="svc-kv">
      <div class="svc-kv-row" v-if="data.timezone"><span class="svc-k">Timezone</span><span class="svc-v is-mono">{{ data.timezone }}</span></div>
      <div class="svc-kv-row" v-if="data.utc_offset"><span class="svc-k">UTC offset</span><span class="svc-v is-mono">{{ data.utc_offset }}</span></div>
      <div class="svc-kv-row" v-if="data.time_12h"><span class="svc-k">12-hour</span><span class="svc-v is-mono">{{ data.time_12h }}</span></div>
      <div class="svc-kv-row" v-if="dst != null"><span class="svc-k">Daylight saving</span><span class="svc-v">{{ dst ? 'Active' : 'Inactive' }}</span></div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const dst = computed(() => props.data?.dst ?? props.data?.is_dst ?? null)
</script>
