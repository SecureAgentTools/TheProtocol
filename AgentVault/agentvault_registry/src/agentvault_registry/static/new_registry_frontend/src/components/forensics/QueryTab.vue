<template>
  <div class="lfq">
    <div class="lfq-bar">
      <div class="lfq-presets">
        <span class="lfq-lbl">WINDOW</span>
        <button v-for="p in presets" :key="p.h" type="button" class="lfq-chip"
          :class="{ 'lfq-chip--active': activePreset === p.h }" @click="setPreset(p.h)">{{ p.label }}</button>
        <input type="datetime-local" v-model="customStart" class="lfq-dt" title="start" @change="activePreset = 0" />
        <span class="lfq-dash">→</span>
        <input type="datetime-local" v-model="customEnd" class="lfq-dt" title="end" @change="activePreset = 0" />
      </div>
    </div>

    <div class="lfq-filters">
      <input v-model="f.event_type" class="lfq-in" placeholder="event_type (comma-sep)" @keyup.enter="run" />
      <input v-model="f.kind" class="lfq-in" placeholder="kind (e.g. unknown, mint)" @keyup.enter="run" />
      <input v-model="f.transaction_id" class="lfq-in lfq-in--wide" placeholder="transaction_id (exact)" @keyup.enter="run" />
      <input v-model="f.aggregate_id" class="lfq-in lfq-in--wide" placeholder="aggregate_id (DID / ledger key)" @keyup.enter="run" />
      <input v-model="f.idempotency_prefix" class="lfq-in" placeholder="idempotency_key prefix (xfer-, fee-…)" @keyup.enter="run" />
      <input v-model="f.source_service" class="lfq-in" placeholder="source_service" @keyup.enter="run" />
      <select aria-label="Order" v-model="f.order" class="lfq-in"><option value="desc">newest</option><option value="asc">oldest</option></select>
      <select aria-label="Limit" v-model.number="f.limit" class="lfq-in">
        <option :value="100">100</option><option :value="200">200</option><option :value="500">500</option><option :value="1000">1000</option>
      </select>
      <button class="lfq-btn" @click="run" :disabled="store.searching">
        <Icon name="mdi:magnify" class="lfq-btn-ico" /> {{ store.searching ? 'Searching…' : 'Search' }}
      </button>
      <button class="lfq-btn lfq-btn-ghost" @click="reset">Reset</button>
      <span class="lfq-spacer"></span>
      <button class="lfq-btn lfq-btn-ghost" @click="exportJson" :disabled="!events.length">
        <Icon name="download" class="lfq-btn-ico" /> JSON
      </button>
    </div>

    <div class="lfq-hint">
      Server-side payload search over the EventStore — anchored on a bounded time window (rides idx_timestamp,
      capped at 31d) + indexed filters. No full-table scans.
    </div>

    <div v-if="res" class="lfq-summary">
      <span><b>{{ res.count }}</b> events</span>
      <span v-if="res.window">window {{ shortTs(res.window.start) }} → {{ shortTs(res.window.end) }}</span>
      <span v-if="res.truncated" class="lfq-trunc">truncated at limit — narrow the window</span>
      <span v-if="res.error" class="lfq-err">{{ res.error }}</span>
    </div>

    <div v-if="events.length" class="lfq-results">
      <div v-for="(ev, i) in events" :key="ev.id || i" class="lfq-row">
        <div class="lfq-row-head" @click="toggle(i)">
          <span class="lfq-time">{{ ts(ev.timestamp) }}</span>
          <span class="lfq-type">{{ ev.event_type }}</span>
          <span v-if="ev.data && ev.data.kind" class="lfq-kind">{{ ev.data.kind }}</span>
          <span class="lfq-agg">{{ shortId(ev.aggregate_id) }}</span>
          <span class="lfq-spacer"></span>
          <span v-if="ev.idempotency_key" class="lfq-idem">{{ ev.idempotency_key }}</span>
          <Icon :name="open.has(i) ? 'arrow-down' : 'chevron-right'" class="lfq-caret" />
        </div>
        <div v-if="open.has(i)" class="lfq-json"><JsonViewer :data="ev" label="event" :default-collapsed="false" dense max-height="280px" /></div>
      </div>
    </div>
    <ReadFailedNotice v-else-if="store.searchFailed && !store.searching" :retry="run" data-testid="lfq-unread" />
    <div v-else-if="res && !store.searching" class="lfq-empty">No events match in this window.</div>
    <div v-else-if="!res" class="lfq-empty">Pick a window + filters, then Search.</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import dayjs from 'dayjs'
import Icon from '@/components/Icon.vue'
import JsonViewer from '@/components/common/JsonViewer.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useForensicsStore } from '@/stores/forensics'
import type { FrameId } from '@/services/api/eventStoreAdmin'
import { downloadCsv } from '@/components/common/csvExport'

const props = defineProps<{ frame: FrameId }>()
const store = useForensicsStore()

const presets = [
  { h: 1, label: '1h' }, { h: 6, label: '6h' }, { h: 24, label: '24h' }, { h: 168, label: '7d' }, { h: 744, label: '31d' },
]
const activePreset = ref(24)
const customStart = ref('')
const customEnd = ref('')
const f = ref({
  event_type: '', kind: '', transaction_id: '', aggregate_id: '',
  idempotency_prefix: '', source_service: '', order: 'desc' as 'asc' | 'desc', limit: 200,
})
const open = ref<Set<number>>(new Set())

const res = computed(() => store.searchResult)
const events = computed(() => store.searchResult?.events || [])

function setPreset(h: number) { activePreset.value = h; customStart.value = ''; customEnd.value = '' }
function toggle(i: number) { const n = new Set(open.value); n.has(i) ? n.delete(i) : n.add(i); open.value = n }
function ts(t?: string) { return t ? dayjs(t).format('MMM D HH:mm:ss') : '—' }
function shortTs(t?: string) { return t ? dayjs(t).format('MMM D HH:mm') : '—' }
function shortId(s?: string | null) { if (!s) return '—'; return s.length > 34 ? s.slice(0, 28) + '…' : s }

function run() {
  open.value = new Set()
  const params: any = { frame: props.frame, limit: f.value.limit, order: f.value.order }
  if (activePreset.value) {
    params.end = new Date().toISOString()
    params.start = new Date(Date.now() - activePreset.value * 3600_000).toISOString()
  } else {
    if (customStart.value) params.start = new Date(customStart.value).toISOString()
    if (customEnd.value) params.end = new Date(customEnd.value).toISOString()
  }
  for (const k of ['event_type', 'kind', 'transaction_id', 'aggregate_id', 'idempotency_prefix', 'source_service'] as const) {
    if (f.value[k]) params[k] = f.value[k]
  }
  store.runSearch(params)
}
function reset() {
  f.value = { event_type: '', kind: '', transaction_id: '', aggregate_id: '', idempotency_prefix: '', source_service: '', order: 'desc', limit: 200 }
  setPreset(24)
}
function exportJson() {
  const blob = new Blob([JSON.stringify(events.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `forensics_search_${dayjs().format('YYYYMMDD_HHmmss')}.json`
  a.click(); URL.revokeObjectURL(a.href)
}
// keep csv import referenced (lint) — JSON export is primary for nested payloads
void downloadCsv
</script>

<style scoped>
.lfq { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0,210,210); --muted:#6b7785;
  --border: rgba(var(--cyan-rgb),0.18); --mono:'IBM Plex Mono',monospace; --amber:#ff9500; --red:#ff3366;
  --green:#00ff88; color:#e8eaed; }
.lfq-bar { margin-bottom: 10px; }
.lfq-presets { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.lfq-lbl { font-size:9px; font-weight:700; letter-spacing:0.14em; color:var(--muted); }
.lfq-dash { color: var(--muted); }
.lfq-chip { background:rgba(var(--cyan-rgb),0.04); border:1px solid var(--border); color:var(--muted);
  border-radius:12px; padding:4px 12px; font-size:11px; cursor:pointer; font-weight:600; }
.lfq-chip--active { background:rgba(var(--cyan-rgb),0.14); color:var(--cyan); border-color:rgba(var(--cyan-rgb),0.45); }
.lfq-dt { background:rgba(0,0,0,0.35); color:#e8eaed; border:1px solid var(--border); border-radius:4px; padding:4px 8px; font-size:11px; font-family:var(--mono); }
.lfq-filters { display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
.lfq-in { background:rgba(0,0,0,0.35); color:#e8eaed; border:1px solid var(--border); border-radius:4px; padding:6px 9px; font-size:12px; font-family:var(--mono); min-width:140px; }
.lfq-in--wide { min-width:240px; }
.lfq-in:focus { outline:none; border-color:rgba(var(--cyan-rgb),0.5); }
.lfq-btn { display:inline-flex; align-items:center; gap:6px; background:rgba(var(--cyan-rgb),0.12); color:var(--cyan);
  border:1px solid rgba(var(--cyan-rgb),0.35); border-radius:4px; padding:6px 14px; font-size:12px; cursor:pointer; font-weight:600; }
.lfq-btn:hover:not(:disabled) { background:rgba(var(--cyan-rgb),0.22); }
.lfq-btn:disabled { opacity:0.45; cursor:not-allowed; }
.lfq-btn-ghost { background:transparent; color:var(--muted); border-color:var(--border); }
.lfq-btn-ico { width:14px; height:14px; }
.lfq-spacer { flex:1; }
.lfq-hint { font-size:11px; color:var(--muted); margin-bottom:12px; }
.lfq-summary { display:flex; gap:16px; align-items:center; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-bottom:10px; padding:8px 12px; background:rgba(var(--cyan-rgb),0.04); border:1px solid var(--border); border-radius:6px; }
.lfq-summary b { color:#e8eaed; font-family:var(--mono); }
.lfq-trunc { color:var(--amber); }
.lfq-err { color:var(--red); }
.lfq-results { display:flex; flex-direction:column; }
.lfq-row { border-bottom:1px solid rgba(var(--cyan-rgb),0.06); }
.lfq-row-head { display:flex; align-items:center; gap:10px; padding:7px 4px; cursor:pointer; flex-wrap:wrap; }
.lfq-row-head:hover { background:rgba(var(--cyan-rgb),0.04); }
.lfq-time { font-family:var(--mono); font-size:11px; color:#c8d8e8; min-width:120px; }
.lfq-type { font-family:var(--mono); font-size:11px; font-weight:700; color:var(--cyan); }
.lfq-kind { font-family:var(--mono); font-size:10px; color:#9ab0c4; background:rgba(255,255,255,0.04); padding:1px 6px; border-radius:6px; }
.lfq-agg { font-family:var(--mono); font-size:10px; color:var(--muted); }
.lfq-idem { font-family:var(--mono); font-size:10px; color:#7e8a99; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.lfq-caret { width:14px; height:14px; color:var(--muted); }
.lfq-json { padding:6px 4px 12px; }
.lfq-empty { text-align:center; padding:34px; color:var(--muted); border:1px dashed var(--border); border-radius:8px; font-size:12px; }
</style>
