<template>
  <div class="gfo">
    <p class="gfo-hint">Click a registry or agent on the map — or pick one below — to command it.</p>
    <input v-model.trim="q" class="gfo-search" type="search" placeholder="filter registries… (name / tier / currency)" aria-label="Filter registries" />

    <!-- Frames -->
    <section class="gfo-sec">
      <h4 class="gfo-h">Frames</h4>
      <button
        v-for="e in frames" :key="e.key"
        class="gfo-row" type="button"
        @click="$emit('select', e)"
      >
        <span class="gfo-dot" :class="dotClass(e.key)" aria-hidden="true"></span>
        <span class="gfo-name">{{ e.name }}</span>
        <span v-if="e.is_local" class="gfo-chip gfo-chip--local">LOCAL</span>
        <span class="gfo-chip">{{ e.currency }}</span>
        <span class="gfo-meta">{{ shortVer(e.card_software_version) }}</span>
        <span class="gfo-meta">{{ latency(e.key) }}</span>
      </button>
    </section>

    <!-- Cloud operators -->
    <section class="gfo-sec">
      <h4 class="gfo-h">Cloud operators <span class="gfo-count">{{ ops.length }}</span></h4>
      <button
        v-for="e in ops" :key="e.key"
        class="gfo-row" type="button"
        @click="$emit('select', e)"
      >
        <span class="gfo-dot" :class="dotClass(e.key)" aria-hidden="true"></span>
        <span class="gfo-name">{{ e.name }}</span>
        <span class="gfo-chip">{{ e.currency }}</span>
        <span class="gfo-meta">{{ shortVer(e.card_software_version) }}</span>
        <span class="gfo-meta">{{ latency(e.key) }}</span>
      </button>
    </section>

    <!-- Fleet-wide actions (run on the LOCAL master) -->
    <section class="gfo-sec">
      <h4 class="gfo-h">Fleet actions <span class="gfo-badge-fleet">FLEET</span></h4>
      <div class="gfo-canary">
        <span class="gfo-canary-k">Canaries</span>
        <span class="gfo-canary-v" :class="canaryPaused ? 'gfo-warn' : 'gfo-ok'">
          {{ canary ? (canaryPaused ? 'PAUSED' : 'running') : 'n/a' }}
        </span>
        <button v-if="canary && !canaryPaused" class="gfo-btn" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'canary_pause')">Pause all</button>
        <button v-if="canary && canaryPaused" class="gfo-btn gfo-btn--go" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'canary_resume')">Resume</button>
      </div>
      <div class="gfo-canary">
        <span class="gfo-canary-k">Federation sync</span>
        <span class="gfo-canary-v">card + peer rounds</span>
        <button class="gfo-btn" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'federation_sync')">Trigger</button>
      </div>
      <div class="gfo-canary">
        <span class="gfo-canary-k">Credentials vault</span>
        <span class="gfo-canary-v">import / export per-registry logins + agent creds</span>
        <button class="gfo-btn" type="button" @click="$emit('fleet-action', 'open_vault')">Open</button>
      </div>
      <div class="gfo-canary">
        <span class="gfo-canary-k">Sessions</span>
        <span class="gfo-canary-v">re-mint consoles from stored refresh tokens</span>
        <button class="gfo-btn" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'reconnect_all')">Reconnect all</button>
      </div>
      <!-- P11 sweeps — one button, every CONNECTED console -->
      <div class="gfo-canary gfo-sweep">
        <span class="gfo-canary-k">Snapshot sweep</span>
        <span class="gfo-canary-v">TEG → EventStore balance snapshot on every connected registry</span>
        <button class="gfo-btn" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'sweep_snapshot')">Sweep</button>
      </div>
      <div class="gfo-canary gfo-sweep">
        <span class="gfo-canary-k">Refresh sweep</span>
        <span class="gfo-canary-v">treasuries + intel for local + all connected</span>
        <button class="gfo-btn" type="button" :disabled="!!busyAction" @click="$emit('fleet-action', 'sweep_refresh')">Refresh</button>
      </div>
      <div class="gfo-canary gfo-sweep">
        <span class="gfo-canary-k">Balance reconcile</span>
        <span class="gfo-canary-v">multi-op ES↔TEG drift report per frame (read-only)</span>
        <button class="gfo-btn" type="button" @click="$emit('fleet-action', 'open_reconcile')">Open</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DirectoryEntry, FleetProbe, RegistryDirectory } from '@/services/api/command'

const props = defineProps<{
  directory: RegistryDirectory | null
  fleet: Record<string, FleetProbe>
  canary: any | null
  busyAction: string | null
}>()
defineEmits<{ (e: 'select', entry: DirectoryEntry): void; (e: 'fleet-action', id: string): void }>()

const q = ref('')
const match = (e: DirectoryEntry) => {
  const s = q.value.toLowerCase()
  return !s || e.name.toLowerCase().includes(s) || e.tier.toLowerCase().includes(s) || e.currency.toLowerCase().includes(s) || (e.frame || '').toLowerCase().includes(s)
}
const regs = computed(() => (props.directory?.registries ?? []).filter(match))
const frames = computed(() =>
  regs.value.filter(e => e.tier.endsWith('mainframe')).sort((a, b) => (b.is_local ? 1 : 0) - (a.is_local ? 1 : 0) || a.name.localeCompare(b.name)),
)
const ops = computed(() => regs.value.filter(e => !e.tier.endsWith('mainframe')).sort((a, b) => a.name.localeCompare(b.name)))

const canaryPaused = computed(() => !!(props.canary?.paused ?? props.canary?.fleet_paused))

const dotClass = (key: string) => {
  const h = props.fleet[key]?.health
  return h === 'up' ? 'gfo-dot--up' : h === 'down' ? 'gfo-dot--down' : h === 'degraded' ? 'gfo-dot--deg' : 'gfo-dot--unk'
}
const latency = (key: string) => {
  const p = props.fleet[key]
  return p && p.health !== 'down' ? `${p.latency_ms}ms` : (p ? 'down' : '—')
}
const shortVer = (v: string | null) => {
  if (!v) return '—'
  const m = v.match(/V\d{4}$/)
  return m ? m[0] : v.slice(-6)
}
</script>

<style scoped>
.gfo { display: grid; gap: 14px; }
.gfo-hint { margin: 0; font-size: .72rem; color: var(--nc-text-muted, #94a3b8); }
.gfo-search {
  width: 100%; padding: 7px 10px; font-size: 14px;
  background: rgba(4, 8, 14, 0.55); border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
  color: var(--nc-text-primary, #e8eaed);
}
.gfo-search:focus { outline: none; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .5); }
.gfo-sec { display: grid; gap: 5px; }
.gfo-h {
  margin: 0 0 2px; display: flex; align-items: center; gap: 7px;
  font-size: .62rem; text-transform: uppercase; letter-spacing: .12em; font-weight: 700;
  color: var(--nc-text-muted, #94a3b8);
}
.gfo-count { font-weight: 600; }
.gfo-badge-fleet {
  font-size: .56rem; padding: 1px 6px; border-radius: 4px; letter-spacing: .12em;
  background: rgba(245,158,11,.12); border: 1px solid rgba(245,158,11,.4); color: #fbbf24;
}
.gfo-row {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  padding: 7px 9px; border-radius: 8px; cursor: pointer;
  background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.06);
  color: var(--nc-text-primary, #e8eaed); font-size: .76rem;
}
.gfo-row:hover { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .4); background: rgba(var(--nc-primary-rgb, 0,210,210), .05); }
.gfo-dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.gfo-dot--up { background: #10b981; }
.gfo-dot--down { background: #ef4444; }
.gfo-dot--deg { background: #f59e0b; }
.gfo-dot--unk { background: rgba(255,255,255,.2); }
.gfo-name { font-weight: 700; flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gfo-chip {
  flex: 0 0 auto; font-size: .58rem; font-weight: 700; letter-spacing: .06em;
  padding: 1px 6px; border-radius: 4px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .1); border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .3);
  color: var(--nc-primary, #00d2d2);
}
.gfo-chip--local { background: rgba(16,185,129,.12); border-color: rgba(16,185,129,.4); color: #10b981; }
.gfo-meta { flex: 0 0 auto; font-size: .62rem; color: var(--nc-text-muted, #94a3b8); font-variant-numeric: tabular-nums; }
.gfo-canary {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 8px;
  background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.06); font-size: .74rem;
}
.gfo-canary-k { font-weight: 700; }
.gfo-canary-v { flex: 1 1 auto; color: var(--nc-text-muted, #94a3b8); }
.gfo-ok { color: #10b981; }
.gfo-warn { color: #f59e0b; font-weight: 700; }
.gfo-btn {
  flex: 0 0 auto; min-height: 30px; padding: 0 11px; border-radius: 7px; cursor: pointer;
  font-size: .68rem; font-weight: 700;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12); color: var(--nc-text-primary, #e8eaed);
}
.gfo-btn:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); }
.gfo-btn--go { color: #10b981; border-color: rgba(16,185,129,.4); }
.gfo-btn:disabled { opacity: .45; cursor: not-allowed; }
</style>
