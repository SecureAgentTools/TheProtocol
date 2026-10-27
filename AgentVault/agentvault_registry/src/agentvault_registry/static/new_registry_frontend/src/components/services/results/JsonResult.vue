<template>
  <div>
    <div class="svc-row" style="margin-bottom:.4rem">
      <span class="svc-stat-label">Response</span>
      <button class="svc-copy" @click="copy">{{ copied ? 'Copied ✓' : 'Copy' }}</button>
    </div>
    <pre class="svc-pre">{{ pretty }}</pre>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
const props = defineProps<{ data: any }>()
const pretty = computed(() => {
  const d = props.data
  if (d == null) return '(no data)'
  if (typeof d === 'string') return d
  try { return JSON.stringify(d, null, 2) } catch { return String(d) }
})
const copied = ref(false)
function copy() {
  try { navigator.clipboard.writeText(pretty.value); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* noop */ }
}
</script>
