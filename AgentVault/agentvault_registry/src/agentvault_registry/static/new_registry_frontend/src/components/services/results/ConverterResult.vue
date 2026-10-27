<template>
  <div v-if="data && data.content != null">
    <div class="svc-row" style="justify-content:space-between;margin-bottom:.45rem">
      <span class="svc-pill">{{ up(data.from_format) }} → {{ up(data.to_format) }}</span>
      <button class="svc-copy" @click="copy">{{ copied ? 'Copied ✓' : 'Copy' }}</button>
    </div>
    <pre class="svc-pre">{{ data.content }}</pre>
    <div v-if="data.content_length != null" class="svc-faint" style="font-size:.6rem;margin-top:.4rem">{{ data.content_length }} characters</div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const up = (s: any) => String(s || '').toUpperCase()
const copied = ref(false)
function copy() { try { navigator.clipboard.writeText(String(props.data.content)); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* noop */ } }
</script>
