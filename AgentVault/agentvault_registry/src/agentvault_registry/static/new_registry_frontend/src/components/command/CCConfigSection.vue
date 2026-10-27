<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  title: string
  payload: unknown
  language?: 'json' | 'text'
}>()

const collapsed = ref(false)

const formatted = computed(() => {
  if (props.payload == null) return '(empty)'
  if (typeof props.payload === 'string') return props.payload
  try { return JSON.stringify(props.payload, null, 2) }
  catch { return String(props.payload) }
})

async function copy() {
  try { await navigator.clipboard.writeText(formatted.value) } catch { /* ignore */ }
}
</script>

<template>
  <div class="cc-cfg">
    <div class="cc-cfg-head" @click="collapsed = !collapsed">
      <span class="cc-cfg-title">{{ title }}</span>
      <div class="cc-cfg-actions">
        <button class="cc-cfg-btn" @click.stop="copy" title="copy">⎘</button>
        <span class="cc-cfg-toggle">{{ collapsed ? '▸' : '▾' }}</span>
      </div>
    </div>
    <pre v-if="!collapsed" class="cc-cfg-pre">{{ formatted }}</pre>
  </div>
</template>

<style scoped>
.cc-cfg { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; overflow: hidden; }
.cc-cfg-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; cursor: pointer; }
.cc-cfg-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.14em; color: rgba(255,255,255,0.7); text-transform: uppercase; }
.cc-cfg-actions { display: flex; gap: 8px; align-items: center; }
.cc-cfg-btn { background: none; border: none; color: rgba(255,255,255,0.55); cursor: pointer; font-size: 13px; padding: 2px 6px; }
.cc-cfg-btn:hover { color: #f4f6f8; }
.cc-cfg-toggle { color: rgba(255,255,255,0.4); font-size: 11px; }
.cc-cfg-pre {
  margin: 0; padding: 10px 14px; background: rgba(0,0,0,0.4); border-top: 1px solid rgba(255,255,255,0.05);
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #d4dee5;
  max-height: 320px; overflow: auto; white-space: pre-wrap; word-break: break-word;
}
</style>
