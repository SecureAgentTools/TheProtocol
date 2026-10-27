<template>
  <section class="gal" aria-label="Action log">
    <header class="gal-head">
      <span class="gal-title"><Icon name="mdi:format-list-bulleted" :size="12" /> Action log</span>
      <span class="gal-count">{{ entries.length }}</span>
      <button v-if="entries.length" class="gal-clear" type="button" title="Clear log" @click="$emit('clear')">
        <Icon name="mdi:close" :size="10" /> clear
      </button>
    </header>
    <p v-if="!entries.length" class="gal-empty">No actions yet this session.</p>
    <ul v-else class="gal-list">
      <li v-for="e in entries" :key="e.id" class="gal-item">
        <div
          class="gal-row" :class="[`gal-row--${e.status}`, { 'gal-row--openable': !!e.payload }]"
          role="button" :tabindex="e.payload ? 0 : -1"
          @click="togglePayload(e)" @keydown.enter="togglePayload(e)"
        >
          <span class="gal-dot" :class="`gal-dot--${e.status}`" aria-hidden="true"></span>
          <span class="gal-ts">{{ fmt(e.ts) }}</span>
          <span class="gal-target">{{ e.target }}</span>
          <span class="gal-action">{{ e.action }}</span>
          <span v-if="e.detail" class="gal-detail" :title="e.detail">{{ e.detail }}</span>
          <button v-if="e.payload" class="gal-copy" type="button" title="Copy result JSON" @click.stop="copy(e)">
            <Icon name="mdi:content-copy" :size="11" />
          </button>
          <Icon v-if="e.payload" :name="openIds.has(e.id) ? 'mdi:chevron-up' : 'mdi:chevron-down'" :size="11" class="gal-chev" />
        </div>
        <pre v-if="e.payload && openIds.has(e.id)" class="gal-payload">{{ pretty(e.payload) }}</pre>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ActionLogEntry } from '@/services/api/command'

defineProps<{ entries: ActionLogEntry[] }>()
defineEmits<{ (e: 'clear'): void }>()

const openIds = ref<Set<string>>(new Set())
function togglePayload(e: ActionLogEntry) {
  if (!e.payload) return
  const s = new Set(openIds.value)
  s.has(e.id) ? s.delete(e.id) : s.add(e.id)
  openIds.value = s
}
const pretty = (p: any) => {
  try { return JSON.stringify(p, null, 2).slice(0, 4000) } catch { return String(p) }
}
const fmt = (ts: number) => new Date(ts).toLocaleTimeString(appLocale(), { hour12: false })
function copy(e: ActionLogEntry) {
  try { navigator.clipboard?.writeText(JSON.stringify(e.payload, null, 2)) } catch { /* clipboard unavailable */ }
}
</script>

<style scoped>
.gal { display: flex; flex-direction: column; min-height: 0; }
.gal-head { display: flex; align-items: center; gap: 8px; padding: 6px 2px; }
.gal-title { display: inline-flex; align-items: center; gap: 6px; font-size: .62rem; text-transform: uppercase; letter-spacing: .1em; font-weight: 700; color: var(--nc-text-muted, #94a3b8); }
.gal-count { font-size: .62rem; color: var(--nc-text-muted, #94a3b8); margin-left: auto; }
.gal-clear {
  display: inline-flex; align-items: center; gap: 3px;
  background: transparent; border: 1px solid rgba(255,255,255,.1); border-radius: 5px;
  color: var(--nc-text-muted, #94a3b8); font-size: .58rem; padding: 1px 6px; cursor: pointer;
}
.gal-clear:hover { color: #ef4444; border-color: rgba(239,68,68,.4); }
.gal-empty { margin: 2px; font-size: .72rem; color: var(--nc-text-muted, #94a3b8); }
.gal-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; max-height: 180px; display: grid; gap: 4px; }
.gal-item { display: grid; gap: 0; }
.gal-row {
  display: flex; align-items: baseline; gap: 7px;
  padding: 5px 7px; border-radius: 6px;
  background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.05);
  font-size: .7rem; font-family: ui-monospace, monospace;
}
.gal-row--openable { cursor: pointer; }
.gal-row--openable:hover { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .35); }
.gal-row--err { border-color: rgba(239,68,68,.35); }
.gal-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; align-self: center; }
.gal-dot--ok { background: #10b981; }
.gal-dot--err { background: #ef4444; }
.gal-dot--pending { background: #f59e0b; animation: gal-pulse 1.1s ease infinite; }
@keyframes gal-pulse { 50% { opacity: .35; } }
.gal-ts { color: var(--nc-text-muted, #94a3b8); flex: 0 0 auto; }
.gal-target { color: var(--nc-primary, #00d2d2); font-weight: 700; flex: 0 0 auto; max-width: 34%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gal-action { color: var(--nc-text-primary, #e8eaed); flex: 0 0 auto; }
.gal-detail { color: var(--nc-text-muted, #94a3b8); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; min-width: 0; }
.gal-copy {
  flex: 0 0 auto; width: 22px; height: 22px; display: grid; place-items: center; align-self: center;
  background: transparent; border: 1px solid rgba(255,255,255,.08); border-radius: 5px;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gal-copy:hover { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .4); }
.gal-chev { flex: 0 0 auto; align-self: center; color: var(--nc-text-muted, #94a3b8); }
.gal-payload {
  margin: 2px 0 0; padding: 7px 9px; border-radius: 6px; max-height: 140px; overflow: auto;
  background: rgba(4,8,14,.6); border: 1px solid rgba(255,255,255,.06);
  font-size: .62rem; line-height: 1.4; color: var(--nc-text-muted, #cbd5e1);
  font-family: ui-monospace, monospace; white-space: pre-wrap; word-break: break-word;
}
</style>
