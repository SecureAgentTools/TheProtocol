<template>
  <!-- GCC P7 — Fleet Status Deck: live situational-awareness strip docked to the
       bottom of the map stage. Pure presentation over the existing 30s fleet poll,
       the treasury cache and the session store — NO pollers of its own. -->
  <div class="gcc-deck" :class="{ 'gcc-deck--closed': !open }" @contextmenu.stop>
    <div class="gcc-deck-bar">
      <span class="gcc-deck-title"><Icon name="mdi:radar" :size="11" /> FLEET</span>
      <span class="gcc-deck-stat" :title="`${upCount} of ${total} registries answered /health`">
        <span class="gcc-deck-dot" :class="upCount === total ? 'gcc-deck-dot--up' : 'gcc-deck-dot--deg'"></span>
        {{ upCount }}/{{ total }} up
      </span>
      <span
        v-if="driftCount"
        class="gcc-deck-stat gcc-deck-stat--warn"
        :title="`${driftCount} registries report a different version than ${localVer} (card-reported — may lag a card pull)`"
      >{{ driftCount }} drift</span>
      <span
        v-for="(v, ccy) in sums" :key="ccy"
        class="gcc-deck-stat gcc-deck-stat--sum"
        :title="`Sum of KNOWN treasury balances in ${ccy} (local + connected consoles)`"
      >Σ {{ compactN(v) }} {{ ccy }}</span>
      <!-- P11: supply invariant per GENUINE frame source (the trust row) -->
      <span
        v-for="d in (deltas || [])" :key="`d-${d.frame}`"
        class="gcc-deck-delta"
        :class="d.status === 'OK' ? 'gcc-deck-delta--ok' : 'gcc-deck-delta--bad'"
        :title="`${d.frame === 'LOCAL' ? 'This registry' : 'Frame ' + d.frame} supply invariant: Δ=${d.delta} (${d.status})`"
      >Δ{{ d.frame }} {{ d.delta }}</span>
      <!-- GC2-2: HOST vitals — the single box every registry lives on -->
      <span
        v-if="host"
        class="gcc-deck-host"
        :class="`gcc-deck-host--${hostTone}`"
        :title="`Host vitals — CPU ${pf(host.cpuPct)} · RAM ${pf(host.memPct)} · disk ${pf(host.diskPct)}`"
      >
        <Icon name="mdi:server" :size="10" />
        {{ pf(host.cpuPct) }}·{{ pf(host.memPct) }}·{{ pf(host.diskPct) }}
      </span>
      <span class="gcc-deck-spacer"></span>
      <!-- GC2-5: health-transition history -->
      <button class="gcc-deck-btn" type="button" title="Health transition history (this session)" @click="$emit('toggle-alerts')">
        <Icon name="mdi:bell-outline" :size="11" /><span v-if="alertCount" class="gcc-deck-bell-n">{{ alertCount }}</span>
      </button>
      <button class="gcc-deck-btn" type="button" title="Reconnect all stored sessions" :disabled="busy" @click="$emit('reconnect-all')">
        <Icon name="mdi:connection" :size="12" />
      </button>
      <button class="gcc-deck-btn" type="button" title="Refresh treasury balances (local + connected)" :disabled="busy" @click="$emit('refresh-balances')">
        <Icon name="mdi:cash-multiple" :size="12" />
      </button>
      <button class="gcc-deck-btn" type="button" :title="open ? 'Collapse deck' : 'Expand deck'" @click="toggle">
        <Icon :name="open ? 'mdi:chevron-down' : 'mdi:chevron-up'" :size="13" />
      </button>
    </div>

    <div v-show="open" class="gcc-deck-rail" role="listbox" aria-label="Fleet registries">
      <button
        v-for="e in entries" :key="e.key"
        class="gcc-deck-chip"
        :class="{ 'gcc-deck-chip--sel': e.key === selectedKey, 'gcc-deck-chip--local': e.is_local, 'gcc-deck-chip--busy': isRestarting(e.key) }"
        type="button" role="option" :aria-selected="e.key === selectedKey"
        :title="isRestarting(e.key) ? `${e.name} — restarting; watching for recovery…` : chipTitle(e)"
        @click="$emit('select', e)"
      >
        <span class="gcc-deck-dot" :class="dotClass(e.key)"></span>
        <span class="gcc-deck-nm">{{ e.name }}</span>
        <Icon v-if="isRestarting(e.key)" name="mdi:restart" :size="11" class="gcc-deck-busy-ic" />
        <span v-if="e.frame" class="gcc-deck-fr">{{ e.frame }}</span>
        <span class="gcc-deck-ms">{{ latency(e.key) }}</span>
        <span class="gcc-deck-ver" :class="{ 'gcc-deck-ver--drift': isDrift(e) }">{{ shortVer(e.card_software_version) }}</span>
        <span v-if="balShort(e)" class="gcc-deck-bal">{{ balShort(e) }}</span>
        <Icon v-if="connectedKeys.includes(e.key)" name="mdi:connection" :size="10" class="gcc-deck-conn" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { DirectoryEntry, FleetProbe, RegistryDirectory } from '@/services/api/command'

const props = defineProps<{
  directory: RegistryDirectory | null
  fleet: Record<string, FleetProbe>
  treasury: Record<string, string | null>
  connectedKeys: string[]
  selectedKey: string | null
  busy: boolean
  latHist?: Record<string, number[]>   // P8 — latency ring buffers for chip tooltips
  deltas?: Array<{ frame: string; delta: number | null; status: string }>   // P11 — genuine frame Δs
  restartingKeys?: string[]            // P11+ — keys mid-restart (chip pulses "busy")
  host?: { cpuPct: number | null; memPct: number | null; diskPct: number | null } | null   // GC2-2 — the box's vitals
  alertCount?: number                  // GC2-5 — health-transition history size
}>()
const isRestarting = (key: string) => !!props.restartingKeys?.includes(key)
// GC2-2: worst-of thresholds — the chip ambers/reds on whichever vital is hottest.
const hostTone = computed<'ok' | 'warn' | 'crit'>(() => {
  const h = props.host
  if (!h) return 'ok'
  const c = h.cpuPct ?? 0, m = h.memPct ?? 0, d = h.diskPct ?? 0
  if (c >= 92 || m >= 95 || d >= 90) return 'crit'
  if (c >= 75 || m >= 90 || d >= 80) return 'warn'
  return 'ok'
})
const pf = (v: number | null | undefined) => (typeof v === 'number' ? `${Math.round(v)}%` : '—')
defineEmits<{
  (e: 'select', entry: DirectoryEntry): void
  (e: 'reconnect-all'): void
  (e: 'refresh-balances'): void
  (e: 'toggle-alerts'): void
}>()

const open = ref(localStorage.getItem('gcc_deck_open') !== '0')
function toggle() {
  open.value = !open.value
  try { localStorage.setItem('gcc_deck_open', open.value ? '1' : '0') } catch { /* private mode */ }
}

const entries = computed<DirectoryEntry[]>(() => {
  const all = props.directory?.registries ?? []
  const frames = all.filter(e => e.tier.endsWith('mainframe'))
    .sort((a, b) => (b.is_local ? 1 : 0) - (a.is_local ? 1 : 0) || a.name.localeCompare(b.name))
  const ops = all.filter(e => !e.tier.endsWith('mainframe')).sort((a, b) => a.name.localeCompare(b.name))
  return [...frames, ...ops]
})

const total = computed(() => entries.value.length)
const upCount = computed(() => entries.value.filter(e => props.fleet[e.key]?.health === 'up').length)

const shortVer = (v: string | null) => {
  if (!v) return '—'
  const m = v.match(/V\d{4}$/)
  return m ? m[0] : v.slice(-6)
}
const localVer = computed(() => {
  const local = entries.value.find(e => e.is_local)
  return local ? shortVer(local.card_software_version) : '—'
})
// Drift only counts when the peer's card is FRESH — a stale cached card (common
// on sandbox/canary frames whose federation sync lags) reports an old version
// that isn't real drift, just an un-pulled cache. Without this, frame-c showed
// "15 drift" purely because its cached peer cards predate the live fleet tag.
const DRIFT_FRESH_MS = 3 * 24 * 60 * 60 * 1000  // 3 days
const isDrift = (e: DirectoryEntry) => {
  if (e.is_local || localVer.value === '—') return false
  const v = shortVer(e.card_software_version)
  if (v === '—' || v === localVer.value) return false
  const pulled = e.card_last_pulled_at ? Date.parse(e.card_last_pulled_at) : NaN
  if (Number.isNaN(pulled) || (Date.now() - pulled) > DRIFT_FRESH_MS) return false  // stale cache ≠ drift
  return true
}
const driftCount = computed(() => {
  const d = entries.value.filter(isDrift).length
  const remotes = entries.value.filter(e => !e.is_local).length
  // If EVERY remote "drifts" from local, the LOCAL build is the outlier (e.g. an
  // ahead canary, or a sandbox frame whose peers run an old image) — that's not
  // actionable fleet drift, so don't alarm. Real partial drift (some behind a
  // roll) still shows. This is why frame-c stopped showing a bogus "15 drift".
  return (remotes > 0 && d >= remotes) ? 0 : d
})

const dotClass = (key: string) => {
  const h = props.fleet[key]?.health
  return h === 'up' ? 'gcc-deck-dot--up' : h === 'down' ? 'gcc-deck-dot--down' : h === 'degraded' ? 'gcc-deck-dot--deg' : 'gcc-deck-dot--unk'
}
const latency = (key: string) => {
  const p = props.fleet[key]
  return p && p.health !== 'down' ? `${p.latency_ms}ms` : (p ? 'down' : '—')
}

const compactN = (n: number) =>
  Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n)
const balShort = (e: DirectoryEntry) => {
  const t = props.treasury[e.key]
  if (!t) return ''
  const n = Number(t)
  return Number.isFinite(n) ? compactN(n) : ''
}
const sums = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const e of props.directory?.registries ?? []) {
    const t = props.treasury[e.key]
    if (!t) continue
    const n = Number(t)
    if (!Number.isFinite(n)) continue
    out[e.currency] = (out[e.currency] || 0) + n
  }
  return out
})

const chipTitle = (e: DirectoryEntry) => {
  const parts = [`${e.name} · ${e.tier} · ${e.currency}`]
  const p = props.fleet[e.key]
  if (p) parts.push(p.health === 'down' ? `down (${p.error || 'no answer'})` : `${p.health} · ${p.latency_ms}ms`)
  if (e.card_software_version) parts.push(`version ${shortVer(e.card_software_version)}${isDrift(e) ? ` (≠ local ${localVer.value})` : ''}`)
  const t = props.treasury[e.key]
  if (t) parts.push(`treasury ${Number(t).toLocaleString(appLocale(), { maximumFractionDigits: 2 })} ${e.currency}`)
  const h = props.latHist?.[e.key]
  if (h && h.length >= 2) {
    const min = Math.min(...h), max = Math.max(...h)
    const avg = Math.round(h.reduce((a, b) => a + b, 0) / h.length)
    parts.push(`latency last ${h.length}: ${min}–${max}ms · avg ${avg}ms`)
  }
  if (props.connectedKeys.includes(e.key)) parts.push('console connected')
  return parts.join('\n')
}
</script>

<style scoped>
.gcc-deck {
  position: absolute; left: 10px; right: 10px; bottom: 10px; z-index: 35;
  display: flex; flex-direction: column; gap: 0;
  background: rgba(8, 12, 20, 0.88);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .22);
  border-radius: 10px;
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(0,0,0,.45);
}
.gcc-deck-bar {
  display: flex; align-items: center; gap: 9px;
  padding: 6px 9px;
}
.gcc-deck--closed .gcc-deck-bar { padding: 5px 9px; }
.gcc-deck-title {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: .58rem; font-weight: 800; letter-spacing: .16em;
  color: var(--nc-primary, #00d2d2);
}
.gcc-deck-stat {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: .62rem; font-weight: 600; color: var(--nc-text-muted, #94a3b8);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.gcc-deck-stat--warn { color: #fbbf24; font-weight: 700; }
.gcc-deck-stat--sum { color: #10b981; font-weight: 700; }
.gcc-deck-spacer { flex: 1 1 auto; }
.gcc-deck-btn {
  flex: 0 0 auto; width: 24px; height: 24px; display: grid; place-items: center;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 6px;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gcc-deck-btn:hover:not(:disabled) { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); }
.gcc-deck-btn:disabled { opacity: .45; cursor: not-allowed; }

.gcc-deck-rail {
  display: flex; gap: 6px; align-items: stretch;
  padding: 0 9px 8px; overflow-x: auto; overflow-y: hidden;
  scrollbar-width: thin;
}
.gcc-deck-rail::-webkit-scrollbar { height: 5px; }
.gcc-deck-rail::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb, 0,210,210), .25); border-radius: 3px; }

.gcc-deck-chip {
  flex: 0 0 auto; display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 8px; border-radius: 7px; cursor: pointer;
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08);
  color: var(--nc-text-primary, #e8eaed); font-size: .66rem;
}
.gcc-deck-chip:hover { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .06); }
.gcc-deck-chip--sel { border-color: var(--nc-primary, #00d2d2); box-shadow: 0 0 9px rgba(var(--nc-primary-rgb, 0,210,210), .35); }
.gcc-deck-chip--local { background: rgba(16,185,129,.06); }
/* P11+ restart-visibility: chip pulses amber while its op is mid-restart. */
.gcc-deck-chip--busy { border-color: rgba(251,191,36,.6); animation: gcc-deck-busy 1.1s ease-in-out infinite; }
.gcc-deck-busy-ic { color: #fbbf24; animation: gcc-deck-busyspin 1.6s linear infinite; flex: 0 0 auto; }
@keyframes gcc-deck-busy {
  0%, 100% { box-shadow: 0 0 0 rgba(251,191,36,0); background: rgba(251,191,36,.05); }
  50%      { box-shadow: 0 0 10px rgba(251,191,36,.45); background: rgba(251,191,36,.13); }
}
@keyframes gcc-deck-busyspin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .gcc-deck-chip--busy { animation: none; border-color: rgba(251,191,36,.7); background: rgba(251,191,36,.12); }
  .gcc-deck-busy-ic { animation: none; }
}
.gcc-deck-nm { font-weight: 700; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gcc-deck-fr {
  font-size: .54rem; font-weight: 800; padding: 0 4px; border-radius: 3px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .12); border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .3);
  color: var(--nc-primary, #00d2d2);
}
.gcc-deck-ms { font-size: .58rem; color: var(--nc-text-muted, #94a3b8); font-variant-numeric: tabular-nums; }
.gcc-deck-ver { font-size: .56rem; font-weight: 700; color: var(--nc-text-muted, #94a3b8); }
.gcc-deck-ver--drift { color: #fbbf24; }
.gcc-deck-bal { font-size: .58rem; font-weight: 800; color: #10b981; font-variant-numeric: tabular-nums; }
.gcc-deck-conn { color: var(--nc-primary, #00d2d2); }

.gcc-deck-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.gcc-deck-dot--up { background: #10b981; }
.gcc-deck-dot--down { background: #ef4444; }
.gcc-deck-dot--deg { background: #f59e0b; }
.gcc-deck-dot--unk { background: rgba(255,255,255,.2); }
.gcc-deck-delta {
  flex: 0 0 auto; font-size: .56rem; font-weight: 800; padding: 1px 5px; border-radius: 4px;
  font-variant-numeric: tabular-nums;
}
.gcc-deck-delta--ok { background: rgba(16,185,129,.1); border: 1px solid rgba(16,185,129,.4); color: #10b981; }
.gcc-deck-delta--bad { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.5); color: #ef4444; }
/* GC2-2: HOST vitals chip */
.gcc-deck-host { display: inline-flex; align-items: center; gap: 4px; font-family: var(--mono); font-size: 0.56rem; padding: 2px 8px; border-radius: 999px; }
.gcc-deck-host--ok   { background: rgba(120,150,190,.08); border: 1px solid rgba(120,150,190,.3); color: rgba(255,255,255,.6); }
.gcc-deck-host--warn { background: rgba(255,179,0,.1); border: 1px solid rgba(255,179,0,.45); color: #ffb300; }
.gcc-deck-host--crit { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.55); color: #ef4444; }
/* GC2-5: bell badge */
.gcc-deck-bell-n { font-family: var(--mono); font-size: 0.52rem; color: var(--nc-primary-bright); margin-left: 2px; }
</style>
