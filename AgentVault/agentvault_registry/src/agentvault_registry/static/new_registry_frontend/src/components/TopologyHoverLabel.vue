<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// TopologyHoverLabel — the ONE reusable hover label for the three topology
// visualisations (AgentWorld globe, UniverseView multiverse, GalacticMap).
// Renders the content of an agent / registry hover card from a normalised
// `entity`. It is intentionally box-LESS + position-LESS: each view drops it
// inside its own already-clamped, positioned tooltip container, so this
// component owns the *content* (consistent rich info + styling) while the host
// keeps its proven placement. Avatar is a slot so AgentWorld can pass its
// FlareEncirclement / UserAvatar while the canvases fall back to a colour dot.
//
// HOVER-GLORY (2026-06-11): agent side upgraded to RegistryHoverCard grade —
// frame-accent rail, glow avatar ring, reputation meter, balance tiles.
// Prop API, #avatar slot and legacy class names unchanged (3 consumers).
import { computed } from 'vue'

const props = defineProps<{
  entity: {
    type: 'agent' | 'registry'
    name?: string | null
    did?: string | null
    description?: string | null
    // agent
    tierLabel?: string | null
    tierClass?: string | null
    reputation?: number | null
    totalTransactions?: number | null
    isSynced?: boolean
    mtlsEnabled?: boolean
    capabilities?: string[]
    originRegistry?: string | null
    spiffeId?: string | null
    balance?: number | null
    liquidBalance?: number | null
    stakedBalance?: number | null
    currency?: string | null        // native settlement currency
    foreign?: boolean               // cross-currency vs the viewer
    frame?: string | null
    // §WORLDFIND — registry-attested proven work (guild books), agent only.
    trackRecord?: {
      jobs?: number | null
      stars?: number | null
      cross_registry?: number | null
      open_disputes?: number | null
      lost_disputes?: number | null
      on_time_met?: number | null
      on_time_of?: number | null
      volume_total?: string | number | null
      volume_currency?: string | null
      distinct_posters?: number | null
      last_verified_at?: string | null
    } | null
    matchedSearch?: boolean
    /** cosmetic encirclement label, named as cosmetic so it reads as paid, not earned */
    flareLabel?: string | null
    // registry
    agentCount?: number | null
    health?: number | null
    status?: string | null
    trustDomain?: string | null
    authMethods?: string[]
    protocolVersion?: string | null
    hopDepth?: number | null
    accentColor?: string | null
  }
  localCurrency?: string | null
}>()

function num(v: any): string { return (v === null || v === undefined) ? '' : Number(v).toLocaleString(appLocale()) }
function clip(s: any, n = 40): string { const t = String(s || ''); return t.length > n ? t.slice(0, n) + '…' : t }

// Frame-derived accent when the entity carries none (A cyan · B magenta · C amber).
const FRAME_ACCENTS: Record<string, string> = { A: '#00d2d2', B: '#ff4fb4', C: '#fbbf24' }
const accent = computed(() =>
  props.entity.accentColor
  || (props.entity.frame && FRAME_ACCENTS[props.entity.frame])
  || (props.entity.type === 'agent' ? '#4fc3f7' : '#00d2d2'))

const repPct = computed(() => {
  const r = props.entity.reputation
  return r == null ? null : Math.max(0, Math.min(100, Math.round(r)))
})
const repColor = computed(() => {
  const r = repPct.value ?? 0
  return r >= 95 ? '#ffd700' : r >= 75 ? '#00d2ff' : r >= 40 ? '#34d399' : '#fbbf24'
})
const totalBal = computed(() => {
  const e = props.entity
  return e.balance ?? ((e.liquidBalance || 0) + (e.stakedBalance || 0))
})
const statusUp = computed(() => /active|ok|healthy/i.test(String(props.entity.status || '')))

// §WORLDFIND — proven work, from the registry's own guild books. Shown ABOVE
// the graph-reputation meter because it answers the question a buyer actually
// asks ("did this agent do the job") rather than "where does it sit in a
// trust graph". Renders only when there is a record; zeros stay silent.
const tr = computed<any>(() => {
  const t = (props.entity as any).trackRecord
  // canonical compact: `jobs`, `stars`, `cross_registry` (see agent_locations.py)
  return t && Number(t.jobs) > 0 ? t : null
})
const trStars = computed(() => {
  const s = tr.value?.stars
  return s == null ? null : Number(s).toFixed(1).replace(/\.0$/, '')
})
// On-time has an HONEST denominator: only engagements whose awarded bid carried
// an eta promise count. With no such bid there is nothing to report, and the
// chip stays away rather than inventing a 0 of 0.
const trOnTime = computed(() => {
  const t: any = tr.value
  return t && t.on_time_of > 0 ? `${t.on_time_met}/${t.on_time_of}` : null
})
const trVolume = computed(() => {
  const t: any = tr.value
  if (!t || t.volume_total == null) return null
  const n = Number(t.volume_total)
  if (!isFinite(n) || n <= 0) return null
  const s = n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(Math.round(n * 100) / 100)
  return `${s} ${t.volume_currency || ''}`.trim()
})
const trLast = computed(() => {
  const t: any = tr.value
  if (!t?.last_verified_at) return null
  const d = new Date(t.last_verified_at)
  if (isNaN(d.getTime())) return null
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  return days <= 0 ? 'today' : days === 1 ? '1d ago' : `${days}d ago`
})
</script>

<template>
  <div class="thl">
    <!-- accent rail — now for BOTH kinds (agents get their frame accent) -->
    <div class="thl-accent"
         :style="{ background: `linear-gradient(90deg, ${accent}, ${accent}55, transparent)` }"></div>

    <div class="thl-head">
      <span class="thl-avatar thl2-ring" :style="{ '--thl-accent': accent }">
        <slot name="avatar">
          <span class="thl-dot" :class="entity.type" :style="{ background: accent, boxShadow: `0 0 9px ${accent}` }"></span>
        </slot>
      </span>
      <span class="thl-name-wrap">
        <span class="thl-name">
          <span v-if="entity.status" class="thl2-status" :class="statusUp ? 'thl2-status--up' : 'thl2-status--warn'" :title="String(entity.status)"></span>
          {{ entity.name || '—' }}
        </span>
        <span class="thl-badges">
          <span v-if="entity.type === 'agent'" class="thl-badge thl2-badge--agent" :style="{ color: accent, borderColor: accent + '66', background: accent + '1f' }">AGENT<template v-if="entity.frame"> · {{ entity.frame }}</template></span>
          <span v-if="entity.tierLabel" class="thl-badge thl2-badge--tier" :class="entity.tierClass || ''"
                :style="(repPct != null && repPct > 0) ? { color: repColor, borderColor: repColor + '66', background: repColor + '22' } : {}">{{ entity.tierLabel }}</span>
          <span v-if="entity.isSynced" class="thl-badge thl-badge--fed">FEDERATED</span>
          <span v-if="entity.mtlsEnabled" class="thl-badge thl-badge--mtls">mTLS</span>
          <span v-if="entity.type === 'registry'" class="thl-badge thl-badge--reg">REGISTRY</span>
        </span>
      </span>
    </div>

    <div v-if="entity.did" class="thl-did">{{ clip(entity.did, 42) }}</div>
    <p v-if="entity.description" class="thl-desc">{{ clip(entity.description, 90) }}</p>

    <!-- AGENT — HOVER-GLORY layout -->
    <template v-if="entity.type === 'agent'">
      <!-- PROVEN WORK — registry-attested, the headline fact about an agent -->
      <div v-if="tr" class="thl-proven" data-testid="thl-proven">
        <span class="thl-proven-k">PROVEN</span>
        <span class="thl-proven-chip">{{ tr.jobs }} verified</span>
        <span v-if="trStars" class="thl-proven-chip thl-proven-chip--star">{{ trStars }}★</span>
        <span v-if="tr.cross_registry > 0" class="thl-proven-chip thl-proven-chip--x">{{ tr.cross_registry }} cross-registry</span>
        <span v-if="tr.open_disputes > 0" class="thl-proven-chip thl-proven-chip--bad">{{ tr.open_disputes }} open dispute{{ tr.open_disputes === 1 ? '' : 's' }}</span>
        <span v-else-if="tr.lost_disputes > 0" class="thl-proven-chip thl-proven-chip--bad">{{ tr.lost_disputes }} lost</span>
      </div>
      <!-- second line: the facts a buyer asks for next. Every one of these is
           already computed by the same grouped pass, so none of it costs a
           query. Silent when the registry does not know. -->
      <div v-if="tr && (trOnTime || trVolume || trLast || tr.distinct_posters > 1)" class="thl-proven thl-proven--sub">
        <span v-if="trOnTime" class="thl-proven-chip thl-proven-chip--dim">{{ trOnTime }} on time</span>
        <span v-if="trVolume" class="thl-proven-chip thl-proven-chip--dim">{{ trVolume }} settled</span>
        <span v-if="tr.distinct_posters > 1" class="thl-proven-chip thl-proven-chip--dim">{{ tr.distinct_posters }} clients</span>
        <span v-if="trLast" class="thl-proven-chip thl-proven-chip--dim">last {{ trLast }}</span>
      </div>
      <!-- what the agent is WEARING, named as cosmetic so it can never be read
           as a credential. Earned marks are above; this is the paid axis. -->
      <div v-if="entity.flareLabel" class="thl-cosmetic" data-testid="thl-cosmetic">
        <span class="thl-k">Cosmetic</span>
        <span class="thl-cosmetic-v">{{ entity.flareLabel }}</span>
      </div>

      <!-- reputation meter -->
      <div v-if="repPct != null && repPct > 0" class="thl2-rep">
        <span class="thl-k">Reputation</span>
        <span class="thl2-rep-bar">
          <span class="thl2-rep-fill" :style="{ width: repPct + '%', background: `linear-gradient(90deg, ${repColor}88, ${repColor})`, boxShadow: `0 0 6px ${repColor}66` }"></span>
        </span>
        <span class="thl2-rep-n" :style="{ color: repColor }">{{ repPct }}</span>
      </div>

      <!-- balance tiles -->
      <div v-if="totalBal > 0" class="thl2-tiles">
        <span class="thl2-tile">
          <span class="thl-k">Total</span>
          <span class="thl2-tile-v">{{ num(totalBal) }} <em class="thl2-ccy">{{ entity.currency || localCurrency }}</em></span>
        </span>
        <span v-if="(entity.liquidBalance || 0) > 0" class="thl2-tile">
          <span class="thl-k">Liquid</span>
          <span class="thl2-tile-v" style="color:#4fc3f7">{{ num(entity.liquidBalance) }}</span>
        </span>
        <span v-if="(entity.stakedBalance || 0) > 0" class="thl2-tile">
          <span class="thl-k">Locked</span>
          <span class="thl2-tile-v" style="color:#ab47bc">{{ num(entity.stakedBalance) }}</span>
        </span>
      </div>

      <!-- remaining facts -->
      <div class="thl-stats">
        <span v-if="entity.totalTransactions != null && entity.totalTransactions > 0" class="thl-stat"><span class="thl-k">Txns</span><span class="thl-v">{{ num(entity.totalTransactions) }}</span></span>
        <span v-if="entity.originRegistry" class="thl-stat"><span class="thl-k">Home</span><span class="thl-v thl2-home">{{ clip(entity.originRegistry, 18) }}</span></span>
      </div>

      <!-- GC3: IRONHAND identity — the start of the SVID for mTLS-enrolled agents -->
      <div v-if="entity.spiffeId" class="thl-origin" :title="String(entity.spiffeId)">
        <span class="thl-k">SVID</span>
        <span class="thl-origin-v thl-mono">{{ clip(String(entity.spiffeId).replace('spiffe://', ''), 40) }}</span>
      </div>

      <div v-if="entity.capabilities && entity.capabilities.length" class="thl-caps">
        <span v-for="c in entity.capabilities.slice(0, 4)" :key="c" class="thl-cap">{{ c }}</span>
      </div>
      <div v-if="entity.foreign && entity.currency" class="thl-origin"><span class="thl-fx">⇄ {{ entity.currency }} · cross-currency</span></div>
    </template>

    <!-- REGISTRY stats (unchanged — already great) -->
    <template v-else>
      <div class="thl-stats">
        <span v-if="entity.currency" class="thl-stat"><span class="thl-k">Currency</span><span class="thl-v thl-ccy">{{ entity.currency }}</span></span>
        <span v-if="entity.agentCount != null" class="thl-stat"><span class="thl-k">Agents</span><span class="thl-v">{{ num(entity.agentCount) }}</span></span>
        <span v-if="entity.status" class="thl-stat"><span class="thl-k">Status</span><span class="thl-v" :style="{ color: statusUp ? '#34d399' : '#fbbf24' }">{{ entity.status }}</span></span>
        <span v-if="entity.health != null" class="thl-stat"><span class="thl-k">Health</span><span class="thl-v">{{ entity.health }}%</span></span>
        <span v-if="entity.hopDepth != null" class="thl-stat"><span class="thl-k">Hop</span><span class="thl-v">{{ entity.hopDepth === 0 ? 'local' : entity.hopDepth }}</span></span>
      </div>
      <div v-if="entity.trustDomain" class="thl-origin"><span class="thl-k">Trust</span><span class="thl-origin-v thl-mono">{{ entity.trustDomain }}</span></div>
      <div v-if="entity.authMethods && entity.authMethods.length" class="thl-caps">
        <span v-for="m in entity.authMethods.slice(0, 4)" :key="m" class="thl-cap thl-cap--dim">{{ m }}</span>
      </div>
      <div v-if="entity.foreign && entity.currency" class="thl-origin"><span class="thl-fx">⇄ {{ entity.currency }} · cross-currency</span></div>
    </template>
  </div>
</template>

<style scoped>
.thl { min-width: 196px; max-width: 304px; position: relative; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.thl-accent { position: absolute; top: -9px; left: -11px; right: -11px; height: 3px; border-radius: 3px 3px 0 0; }
.thl-head { display: flex; align-items: center; gap: 9px; margin-top: 2px; }
.thl-avatar { flex-shrink: 0; display: inline-flex; }
/* HOVER-GLORY: glow ring around whatever the avatar slot renders */
.thl2-ring { position: relative; border-radius: 50%; padding: 2px;
  background: radial-gradient(circle, var(--thl-accent, #4fc3f7) 0%, transparent 72%);
  box-shadow: 0 0 11px color-mix(in srgb, var(--thl-accent, #4fc3f7) 55%, transparent); }
.thl-dot { width: 13px; height: 13px; border-radius: 50%; background: #4fc3f7; box-shadow: 0 0 7px #4fc3f7aa; display: inline-block; }
.thl-dot.registry { border-radius: 3px; background: #00e676; box-shadow: 0 0 7px #00e67688; }
.thl-name-wrap { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.thl-name { font-size: 13.5px; font-weight: 800; color: #fff; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
.thl2-status { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.thl2-status--up { background: #34d399; box-shadow: 0 0 6px #34d39988; animation: thl2-pulse 2s ease-in-out infinite; }
.thl2-status--warn { background: #fbbf24; box-shadow: 0 0 6px #fbbf2488; }
@keyframes thl2-pulse { 50% { opacity: .55; } }
.thl-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.thl-badge { font-size: 8px; font-weight: 800; letter-spacing: 0.5px; padding: 1px 5px; border-radius: 4px; }
.thl2-badge--agent { border: 1px solid; }
.thl2-badge--tier { color: #cbd5e1; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.16); }
.thl2-badge--tier.tier-elite { color: #ffd700; background: rgba(255,215,0,0.12); border-color: rgba(255,215,0,0.45); }
.thl2-badge--tier.tier-high { color: #00d2ff; background: rgba(0,210,255,0.1); border-color: rgba(0,210,255,0.4); }
.thl-badge--fed { color: #ffab40; background: rgba(255,171,64,0.18); border: 1px solid rgba(255,171,64,0.45); }
.thl-badge--mtls { color: #34d399; background: rgba(16,185,129,0.16); border: 1px solid rgba(16,185,129,0.4); }
.thl-badge--reg { color: #00e676; background: rgba(0,230,118,0.14); border: 1px solid rgba(0,230,118,0.38); }
.thl-did { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: rgba(255,255,255,0.4); margin-top: 5px; word-break: break-all; }
.thl-desc { font-size: 11px; color: rgba(255,255,255,0.66); line-height: 1.4; margin: 6px 0 0; }
/* HOVER-GLORY: reputation meter */
.thl2-rep { display: flex; align-items: center; gap: 7px; margin-top: 8px; }
.thl2-rep-bar { flex: 1 1 auto; height: 5px; border-radius: 3px; background: rgba(255,255,255,0.07); overflow: hidden; }
.thl2-rep-fill { display: block; height: 100%; border-radius: 3px; }
.thl2-rep-n { font-size: 11.5px; font-weight: 800; font-variant-numeric: tabular-nums; }
/* HOVER-GLORY: balance tiles */
.thl2-tiles { display: flex; gap: 6px; margin-top: 8px; }
.thl2-tile { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1px;
  padding: 5px 7px; border-radius: 7px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); }
.thl2-tile-v { font-size: 11.5px; font-weight: 800; color: #e8eefc; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.thl2-ccy { font-style: normal; font-size: 9px; color: #fcd34d; font-weight: 700; }
.thl2-home { color: #90a4ae; }
.thl-stats { display: flex; flex-wrap: wrap; gap: 5px 12px; margin-top: 7px; }
.thl-stat { display: inline-flex; flex-direction: column; gap: 1px; }
.thl-k { font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.5px; color: rgba(255,255,255,0.4); }
.thl-v { font-size: 12px; font-weight: 700; color: #e8eefc; }
.thl-ccy { color: #fcd34d; }
/* §WORLDFIND — proven-work band. Deliberately a DIFFERENT visual class from
   cosmetic flare: thin, geometric, no animation. Earned marks are not decor. */
.thl-proven { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 7px; }
.thl-proven-k { font-size: 8.5px; letter-spacing: 0.09em; color: rgba(52,211,153,0.85); font-weight: 700; margin-right: 2px; }
.thl-proven-chip { font-size: 9px; padding: 1px 6px; border-radius: 99px;
  color: rgba(52,211,153,0.95); background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.3); }
.thl-proven-chip--star { color: rgba(251,191,36,0.95); background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.3); }
.thl-proven-chip--x { color: rgba(0,210,255,0.95); background: rgba(0,210,255,0.1); border-color: rgba(0,210,255,0.3); }
.thl-proven-chip--bad { color: rgba(248,113,113,0.95); background: rgba(248,113,113,0.1); border-color: rgba(248,113,113,0.32); }
.thl-proven-chip--dim { color: rgba(203,213,225,0.8); background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.14); }
.thl-proven--sub { margin-top: 4px; }
/* Cosmetic line: muted on purpose. Paid decoration must never out-shout the
   earned band directly above it. */
.thl-cosmetic { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
.thl-cosmetic-v { font-size: 9.5px; color: rgba(196,181,253,0.9); letter-spacing: 0.01em; }
.thl-caps { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
.thl-cap { font-size: 9px; padding: 1px 6px; border-radius: 99px; color: rgba(0,210,210,0.92); background: rgba(0,210,210,0.1); border: 1px solid rgba(0,210,210,0.28); }
.thl-cap--dim { color: rgba(255,255,255,0.6); background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.12); }
.thl-origin { display: flex; align-items: baseline; gap: 6px; margin-top: 6px; }
.thl-origin-v { color: #90a4ae; font-size: 11px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.thl-mono { font-family: 'IBM Plex Mono', monospace; font-size: 10px; }
.thl-fx { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; color: #ffd54f; background: rgba(255,213,79,0.12); border: 1px solid rgba(255,213,79,0.45); }
.tier-elite, .thl-v.tier-elite { color: #ffd700; }
.tier-high, .thl-v.tier-high { color: #00d2ff; }
</style>
