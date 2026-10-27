<template>
  <div class="lff">
    <div class="lff-bar">
      <div class="lff-tabs">
        <button class="lff-t" :class="{ 'lff-t--on': filter === 'open' }" @click="setFilter('open')">Open</button>
        <button class="lff-t" :class="{ 'lff-t--on': filter === 'acked' }" @click="setFilter('acked')">Acknowledged</button>
        <button class="lff-t" :class="{ 'lff-t--on': filter === '' }" @click="setFilter('')">All</button>
      </div>
      <span class="lff-spacer"></span>
      <button class="lff-btn" @click="reload" :disabled="store.loadingFindings">
        <Icon name="refresh-cw" class="lff-btn-ico" /> {{ store.loadingFindings ? '…' : 'Refresh' }}
      </button>
    </div>

    <div v-if="store.findingsInactive" class="lff-inactive">
      <Icon name="mdi:information" class="lff-inactive-ico" />
      <div>
        <strong>Scanner inactive.</strong> The continuous Open-Findings worker is shipped but <code>FORENSIC_SCANNER_ENABLED=false</code>
        (default). Enable it per-frame to populate this inbox (it runs the registry-rail inventory + EventStore detector scan on a
        leader-elected interval and tracks first-seen/last-seen/ack). Until then, use the <b>Stuck Funds</b> board + <b>Query</b> for on-demand checks.
      </div>
    </div>

    <ReadFailedNotice v-else-if="store.findingsFailed" :retry="reload" data-testid="lff-unread" />
    <div v-else-if="store.openFindings.length" class="lff-list">
      <div v-for="fd in store.openFindings" :key="fd.finding_key" class="lff-card" :class="`lff-card--${fd.severity}`">
        <div class="lff-card-bar"></div>
        <div class="lff-card-body">
          <div class="lff-card-top">
            <span class="lff-sev" :class="`lff-sev--${fd.severity}`">{{ fd.severity }}</span>
            <span class="lff-title">{{ fd.title }}</span>
            <span class="lff-src">{{ fd.source }}</span>
            <span v-if="fd.status === 'acked'" class="lff-acked">acked</span>
            <span class="lff-spacer"></span>
            <span v-if="fd.count != null" class="lff-count">{{ fd.count }}</span>
            <button v-if="fd.status !== 'acked'" class="lff-ack" @click="ack(fd.finding_key)">ack</button>
          </div>
          <div class="lff-detail">{{ fd.detail }}</div>
          <div class="lff-meta">
            <span v-if="fd.amount != null">{{ fmt(fd.amount) }} {{ fd.currency || '' }}</span>
            <span v-if="fd.frame">{{ fd.frame }}</span>
            <span v-if="fd.first_seen">first {{ fromNow(fd.first_seen) }}</span>
            <span v-if="fd.last_seen">last {{ fromNow(fd.last_seen) }}</span>
            <code class="lff-key">{{ fd.finding_key }}</code>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="!store.loadingFindings" class="lff-empty">
      <Icon name="check" class="lff-empty-ico" /> No {{ filter || '' }} findings.
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import Icon from '@/components/Icon.vue'
import { useForensicsStore } from '@/stores/forensics'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
dayjs.extend(relativeTime)
const store = useForensicsStore()
const filter = ref<'open' | 'acked' | ''>('open')

function setFilter(v: 'open' | 'acked' | '') { filter.value = v; reload() }
function reload() { store.loadFindings(filter.value || undefined) }
function ack(key: string) { store.ackFinding(key) }
function fmt(n: number) { return n.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) }
function fromNow(ts?: string) { return ts ? dayjs(ts).fromNow() : '—' }
onMounted(() => reload())
</script>

<style scoped>
.lff { --cyan:var(--nc-primary,#00d2d2); --cyan-rgb:var(--nc-primary-rgb,0,210,210); --muted:#6b7785;
  --border:rgba(var(--cyan-rgb),0.18); --mono:'IBM Plex Mono',monospace; --red:#ff3366; --amber:#ff9500; --green:#00ff88; color:#e8eaed; }
.lff-bar { display:flex; align-items:center; margin-bottom:14px; }
.lff-tabs { display:flex; gap:4px; }
.lff-t { background:transparent; border:1px solid var(--border); color:var(--muted); border-radius:6px; padding:5px 12px; font-size:12px; cursor:pointer; }
.lff-t--on { background:rgba(var(--cyan-rgb),0.12); color:var(--cyan); border-color:rgba(var(--cyan-rgb),0.4); }
.lff-spacer { flex:1; }
.lff-btn { display:inline-flex; align-items:center; gap:6px; background:rgba(var(--cyan-rgb),0.12); color:var(--cyan); border:1px solid rgba(var(--cyan-rgb),0.35); border-radius:4px; padding:6px 12px; font-size:12px; cursor:pointer; }
.lff-btn-ico { width:14px; height:14px; }
.lff-inactive { display:flex; gap:10px; align-items:flex-start; padding:14px; border:1px dashed var(--border); border-radius:8px; color:var(--muted); font-size:12px; line-height:1.55; }
.lff-inactive-ico { width:18px; height:18px; color:var(--cyan); flex-shrink:0; margin-top:1px; }
.lff-inactive code { background:rgba(255,255,255,0.05); padding:1px 5px; border-radius:3px; font-family:var(--mono); }
.lff-list { display:flex; flex-direction:column; gap:8px; }
.lff-card { display:flex; background:rgba(var(--cyan-rgb),0.025); border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.lff-card-bar { width:4px; flex-shrink:0; }
.lff-card--high .lff-card-bar, .lff-card--critical .lff-card-bar { background:var(--red); }
.lff-card--warn .lff-card-bar { background:var(--amber); }
.lff-card--info .lff-card-bar { background:#9ad6ff; }
.lff-card-body { padding:10px 14px; flex:1; min-width:0; }
.lff-card-top { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
.lff-title { font-size:13px; font-weight:700; }
.lff-src { font-size:9px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); border:1px solid var(--border); border-radius:6px; padding:1px 6px; }
.lff-acked { font-size:9px; color:var(--green); }
.lff-sev { font-size:9px; font-weight:800; text-transform:uppercase; padding:2px 8px; border-radius:8px; }
.lff-sev--high, .lff-sev--critical { background:rgba(255,51,102,0.2); color:#ff6b8a; }
.lff-sev--warn { background:rgba(255,149,0,0.2); color:var(--amber); }
.lff-sev--info { background:rgba(154,214,255,0.16); color:#9ad6ff; }
.lff-count { font-family:var(--mono); font-weight:700; color:#d6e2ee; }
.lff-ack { background:transparent; border:1px solid var(--border); color:var(--muted); border-radius:4px; padding:3px 10px; font-size:11px; cursor:pointer; }
.lff-ack:hover { color:var(--green); border-color:rgba(0,255,136,0.4); }
.lff-detail { font-size:12px; color:var(--muted); margin-top:5px; line-height:1.5; }
.lff-meta { display:flex; gap:14px; flex-wrap:wrap; margin-top:7px; font-size:10px; color:var(--muted); font-family:var(--mono); align-items:center; }
.lff-key { background:rgba(255,255,255,0.04); padding:1px 6px; border-radius:3px; }
.lff-empty { text-align:center; padding:30px; color:var(--green); font-size:13px; display:flex; gap:8px; align-items:center; justify-content:center; }
.lff-empty-ico { width:18px; height:18px; }
</style>
