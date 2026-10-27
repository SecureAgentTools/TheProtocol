<template>
  <div v-if="data && data.expression">
    <div class="svc-row" style="margin-bottom:.3rem"><span class="svc-stat-label">Cron expression</span><button class="svc-copy" @click="copy">{{ copied ? 'Copied ✓' : 'Copy' }}</button></div>
    <div class="svc-soft" style="padding:.65rem .8rem;font-family:var(--svc-mono);font-size:1.1rem;font-weight:600;color:var(--svc);text-align:center;letter-spacing:.06em">{{ data.expression }}</div>
    <p v-if="data.description" class="svc-dim" style="font-size:.82rem;margin:.6rem 0 0;text-align:center">{{ data.description }}</p>
    <div v-if="runs.length" style="margin-top:.75rem">
      <div class="svc-stat-label" style="margin-bottom:.35rem">Next runs</div>
      <div class="svc-kv">
        <div v-for="(r, i) in runs.slice(0, 5)" :key="i" class="svc-kv-row"><span class="svc-k">Run {{ i + 1 }}</span><span class="svc-v is-mono">{{ r }}</span></div>
      </div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
// typed as an array so the template's v-for index is a number (vue-tsc 3 reads a loop over `any` as possibly an object)
const runs = computed<unknown[]>(() => props.data?.next_5_runs || props.data?.next_runs || [])
const copied = ref(false)
function copy() { try { navigator.clipboard.writeText(props.data.expression); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* noop */ } }
</script>
