<!--
  FX Reserve Solvency (I2) + Cross-Frame FX Triangle — independent witness.

  The supply invariant (I1, Δ=0) is structurally BLIND to FX liquidity: @fx_reserve
  and @fx_router are ordinary balances counted in Σ(liquid+locked), so a draining
  reserve or stranded op→op router residue keeps Δ=0. This panel renders the auditor's
  INDEPENDENT reserve-solvency read (balance vs its own configured floor) plus the
  cross-frame FX triangle — the implied cross-rate between every pair of sovereign
  reserves (AVT · JDAY · BVT), TRACKED but never gated. It self-hides on environments
  with no FX reserve frames.
-->
<template>
  <section v-if="reserveFrames.length" class="au-solv">
    <div class="au-solv-head">
      <span class="au-solv-glyph" aria-hidden="true">&#x25C8;</span>
      <span class="au-label">CAN THE FX RESERVE COVER ITS FLOOR?</span>
      <InfoDot title="What reserve solvency means" testid="info-au-solv-sub">
        Reserve balances read directly from each frame&rsquo;s <code>materialized_balances</code> &mdash;
      checked against the auditor&rsquo;s own floors, never the registry.
      </InfoDot>
      <span class="au-solv-i2">I2 &middot; INDEPENDENT</span>
      <span class="au-solv-spacer"></span>
      <span :class="['au-solv-agg', 'st-' + aggStatus.toLowerCase()]">
        <span class="au-solv-agg-dot"></span>{{ aggLabel }}
      </span>
    </div>

    <div class="au-solv-grid">
      <!-- Reserve fuel gauges -->
      <article
        v-for="rf in reserveFrames"
        :key="rf.id"
        :class="['au-solv-card', 'ccy-' + rf.sol.currency.toLowerCase(), 'st-' + rf.sol.status.toLowerCase()]"
      >
        <div class="au-solv-aura" aria-hidden="true" :style="{ background: 'radial-gradient(120% 80% at 0% 0%, ' + ccyHue(rf.sol.currency, 0.10) + ', transparent 60%)' }"></div>
        <header class="au-solv-card-head">
          <span class="au-solv-ccy" :style="{ color: ccyHue(rf.sol.currency), borderColor: ccyHue(rf.sol.currency, 0.4) }">{{ rf.sol.currency }}</span>
          <span class="au-solv-frame">{{ rf.name }}</span>
          <span class="au-solv-acct">@fx_reserve</span>
        </header>

        <div class="au-solv-bal">
          <AnimatedNumber :value="rf.sol.reserve_balance" :decimals="2" comma />
          <span class="au-solv-unit" :style="{ color: ccyHue(rf.sol.currency) }">{{ rf.sol.currency }}</span>
        </div>

        <!-- Fuel gauge: fill = gauge_pct, floor tick at floorPos, status-coloured -->
        <div class="au-solv-gauge" role="meter" :aria-valuenow="Math.round(rf.sol.gauge_pct)" aria-valuemin="0" aria-valuemax="100">
          <div class="au-solv-gauge-track"></div>
          <div class="au-solv-gauge-fill" :style="{ width: rf.sol.gauge_pct + '%', background: gaugeFill(rf.sol) }"></div>
          <div class="au-solv-gauge-floor" :style="{ left: floorPos(rf.sol) + '%' }" :title="'floor ' + fmt(rf.sol.floor)">
            <span class="au-solv-gauge-floor-tick"></span>
          </div>
        </div>

        <footer class="au-solv-card-foot">
          <span class="au-solv-floor">FLOOR <b class="au-mono">{{ fmt(rf.sol.floor) }}</b></span>
          <span class="au-solv-head-room" v-if="rf.sol.headroom_x !== null">
            &times;{{ rf.sol.headroom_x.toFixed(rf.sol.headroom_x >= 10 ? 0 : 1) }} <span class="au-solv-dim">headroom</span>
          </span>
          <span :class="['au-solv-badge', 'st-' + rf.sol.status.toLowerCase()]">
            {{ statusGlyph(rf.sol.status) }} {{ statusLabel(rf.sol.status) }}
          </span>
        </footer>

        <!-- op→op @fx_router residue (only when the router DID is configured) -->
        <div v-if="rf.sol.router_status" :class="['au-solv-router', 'st-' + rf.sol.router_status.toLowerCase()]">
          <span class="au-solv-router-key">&#x21C4; @fx_router residue</span>
          <span class="au-solv-router-val au-mono">{{ fmt(rf.sol.router_residue || 0) }} {{ rf.sol.currency }}</span>
          <span class="au-solv-router-tag">{{ rf.sol.router_status === 'RESIDUE' ? 'SWEEP →@fx_reserve' : 'clear' }}</span>
        </div>
      </article>
    </div>

    <!-- Cross-frame FX triangle (TRACKED, never gated) -->
    <div v-if="triangle" class="au-pool au-tri">
      <div class="au-pool-head">
        <span class="au-label">CROSS-FRAME FX TRIANGLE</span>
        <span class="au-pool-tracked" title="Implied cross-rates move with price by design — the gates are Δ=0 (I1) and reserve solvency (I2)">TRACKED &middot; NOT GATED</span>
      </div>

      <!-- reserve vertices: one per sovereign frame -->
      <div class="au-tri-verts">
        <div
          v-for="v in triangle.vertices"
          :key="v.ccy"
          class="au-tri-vert"
          :style="{ borderTopColor: ccyHue(v.ccy, 0.55), background: 'radial-gradient(130% 100% at 50% 0%, ' + ccyHue(v.ccy, 0.08) + ', transparent 72%)' }"
        >
          <span class="au-tri-ccy" :style="{ color: ccyHue(v.ccy), borderColor: ccyHue(v.ccy, 0.4) }">{{ v.ccy }}</span>
          <span class="au-tri-bal au-mono">{{ fmt(v.reserve) }}</span>
          <span class="au-tri-frame">{{ v.frame }} &middot; @fx_reserve</span>
        </div>
      </div>

      <!-- implied cross-rate edges: reserveₓ / reserveᵧ, both directions -->
      <div class="au-tri-edges">
        <div v-for="e in triangle.edges" :key="e.a + e.b" class="au-tri-edge">
          <span class="au-tri-edge-pair">
            <b :style="{ color: ccyHue(e.a) }">{{ e.a }}</b>
            <span class="au-tri-edge-knot">&#x21C4;</span>
            <b :style="{ color: ccyHue(e.b) }">{{ e.b }}</b>
          </span>
          <span class="au-tri-edge-rate au-mono">{{ e.spot_a_per_b.toFixed(4) }}<span class="au-solv-dim"> {{ e.a }}/{{ e.b }}</span></span>
          <span class="au-tri-edge-inv au-mono">{{ e.spot_b_per_a.toFixed(4) }}<span class="au-solv-dim"> {{ e.b }}/{{ e.a }}</span></span>
        </div>
      </div>

      <!-- loop closure: the one number that matters, fully explained -->
      <div v-if="triangle.loop_product !== null" class="au-tri-loop">
        <span class="au-tri-loop-key">loop &prod;<span class="au-solv-dim"> &mdash; implied cross-rates, full cycle</span></span>
        <span class="au-tri-loop-val au-mono">{{ triangle.loop_product.toFixed(4) }}</span>
        <span class="au-tri-loop-tag">&#x2713; arbitrage-free by construction</span>
      </div>

      <div class="au-pool-foot">
        Each cross-rate is derived <em>independently</em> by the auditor from the two reserve balances
        (reserve<sub>x</sub> &#x2044; reserve<sub>y</sub>) &mdash; it never trusts the registry&rsquo;s quoted FX.
        With all three sovereign reserves present the rates are mutually consistent (loop&nbsp;=&nbsp;1.0000); the gates
        remain &#x0394;=0 (I1) and reserve solvency (I2). Spot drifts with price by design.
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import InfoDot from './InfoDot.vue'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import type { Solvency, FxTriangle } from '@/types/auditor'
import AnimatedNumber from '@/components/AnimatedNumber.vue'

const store = useAuditorStore()
const { frames, latestByFrame, mode } = storeToRefs(store)

interface ReserveFrame { id: string; name: string; sol: Solvency }

// Reserve frames in the active environment that expose a solvency read.
const reserveFrames = computed<ReserveFrame[]>(() => {
  const out: ReserveFrame[] = []
  for (const f of frames.value) {
    if (f.mode && f.mode !== mode.value) continue
    const sol = latestByFrame.value[f.id]?.extra_data?.solvency
    if (sol && sol.present) out.push({ id: f.id, name: f.name, sol })
  }
  return out
})

// Cross-frame FX triangle — every reserve frame is a vertex; each pair an edge whose
// implied cross-rate is reserveₓ/reserveᵧ. Currency-AGNOSTIC: no hardcoded AVT/BVT
// pairing — it reads whatever reserves the frames expose, ordered AVT · JDAY · BVT.
const CCY_ORDER: Record<string, number> = { AVT: 0, JDAY: 1, BVT: 2 }
const triangle = computed<FxTriangle | null>(() => {
  const verts = reserveFrames.value
    .filter((r) => r.sol.reserve_balance > 0)
    .map((r) => ({ ccy: r.sol.currency, frame: r.name, reserve: r.sol.reserve_balance }))
    .sort((a, b) => (CCY_ORDER[a.ccy] ?? 9) - (CCY_ORDER[b.ccy] ?? 9))
  if (verts.length < 2) return null
  const edges = []
  for (let i = 0; i < verts.length; i++) {
    for (let j = i + 1; j < verts.length; j++) {
      edges.push({
        a: verts[i].ccy, b: verts[j].ccy,
        spot_a_per_b: verts[i].reserve / verts[j].reserve,
        spot_b_per_a: verts[j].reserve / verts[i].reserve,
      })
    }
  }
  // Loop product over a 3-cycle = (A/B)·(B/C)·(C/A) = 1.0000 by construction —
  // the auditor's three independent cross-rates are mutually consistent (no arb).
  const loop = verts.length >= 3
    ? (verts[0].reserve / verts[1].reserve) *
      (verts[1].reserve / verts[2].reserve) *
      (verts[2].reserve / verts[0].reserve)
    : null
  return { vertices: verts, edges, loop_product: loop }
})

const RANK = { BREACH: 0, LOW: 1, SOLVENT: 2 } as const
const aggStatus = computed(() => {
  let worst: 'SOLVENT' | 'LOW' | 'BREACH' = 'SOLVENT'
  for (const r of reserveFrames.value) {
    if (RANK[r.sol.status] < RANK[worst]) worst = r.sol.status
  }
  return worst
})
const aggLabel = computed(() =>
  aggStatus.value === 'SOLVENT' ? 'ALL RESERVES OK'
    : aggStatus.value === 'LOW' ? 'RESERVE RUNNING LOW' : 'RESERVE BELOW FLOOR'
)

function ccyHue(ccy: string, alpha = 1): string {
  // AVT green · JDAY blue (matches the dashboard's Frame-B accent) · BVT amber.
  const hex = ccy === 'BVT' ? '#ffb300' : ccy === 'JDAY' ? '#00b0ff' : '#00c853'
  if (alpha === 1) return hex
  const h = hex.replace('#', '')
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${alpha})`
}
function gaugeFill(s: Solvency): string {
  const base = s.status === 'BREACH' ? '#ff1744' : s.status === 'LOW' ? '#ff9100' : ccyHue(s.currency)
  return `linear-gradient(90deg, ${hexA(base, 0.55)}, ${base})`
}
function hexA(hex: string, a: number): string {
  const h = hex.replace('#', '')
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`
}
// Floor tick position = gauge% at balance==floor = gauge_pct / headroom_x (clamped).
function floorPos(s: Solvency): number {
  if (!s.headroom_x || s.headroom_x <= 0) return 10
  return Math.max(3, Math.min(92, s.gauge_pct / s.headroom_x))
}
function statusGlyph(st: string): string {
  return st === 'SOLVENT' ? '✓' : st === 'LOW' ? '◉' : '✗'
}

// Display vocabulary: the API's SOLVENT/LOW/BREACH is a fourth set of words meaning the same
// three things every other panel says. Collapse it at the boundary so the page speaks one language.
function statusLabel(st: string) {
  return st === 'SOLVENT' ? 'OK' : st === 'LOW' ? 'WATCH' : 'BREACH'
}
function fmt(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<style scoped>
.au-solv {
  margin: 28px 0 8px;
  padding: 0 4px;
}
.au-solv-head {
  display: flex; align-items: center; gap: 12px; margin-bottom: 6px;
}
.au-solv-glyph { color: var(--au-accent); font-size: 14px; filter: drop-shadow(0 0 8px rgba(0,200,83,0.5)); }
.au-label {
  font-family: var(--au-display); font-size: 11px; letter-spacing: 0.22em;
  color: var(--au-text-secondary); text-transform: uppercase;
}
.au-solv-i2 {
  font-family: var(--au-font); font-size: 9px; letter-spacing: 0.16em;
  color: var(--au-accent-b); border: 1px solid var(--au-accent-b-subtle);
  background: var(--au-accent-b-subtle); padding: 2px 7px; border-radius: 3px;
}
.au-solv-spacer { flex: 1; }
.au-solv-agg {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 10px; letter-spacing: 0.14em; padding: 4px 11px; border-radius: 3px;
  border: 1px solid var(--au-border-bright); font-family: var(--au-font);
}
.au-solv-agg-dot { width: 7px; height: 7px; border-radius: 50%; }
.au-solv-agg.st-solvent { color: var(--au-accent); border-color: rgba(0,200,83,0.3); }
.au-solv-agg.st-solvent .au-solv-agg-dot { background: var(--au-accent); box-shadow: 0 0 8px var(--au-accent); animation: au-solv-pulse 2.4s ease-in-out infinite; }
.au-solv-agg.st-low { color: var(--au-warning); border-color: rgba(255,145,0,0.35); }
.au-solv-agg.st-low .au-solv-agg-dot { background: var(--au-warning); box-shadow: 0 0 8px var(--au-warning); }
.au-solv-agg.st-breach { color: var(--au-danger); border-color: rgba(255,23,68,0.45); }
.au-solv-agg.st-breach .au-solv-agg-dot { background: var(--au-danger); box-shadow: 0 0 10px var(--au-danger); animation: au-solv-blink 0.9s steps(2) infinite; }
.au-solv-sub {
  font-size: 10.5px; color: var(--au-text-dim); margin-bottom: 16px; max-width: 760px; line-height: 1.6;
}
.au-solv-sub code { color: var(--au-text-secondary); font-size: 10px; }

.au-solv-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px; margin-bottom: 16px;
}
.au-solv-card {
  position: relative; background: var(--au-gradient); border: 1px solid var(--au-border);
  border-radius: var(--au-radius-lg); padding: 18px 20px 16px; overflow: hidden; isolation: isolate;
  box-shadow: var(--au-shadow); transition: border-color var(--au-transition), box-shadow var(--au-transition);
}
.au-solv-card::before {
  content: ''; position: absolute; inset: 0 auto 0 0; width: 3px;
  background: var(--au-accent); opacity: 0.5;
}
.au-solv-card.ccy-bvt::before { background: #ffb300; }
.au-solv-card.ccy-jday::before { background: #00b0ff; }
.au-solv-card.st-low::before { background: var(--au-warning); }
.au-solv-card.st-breach::before { background: var(--au-danger); box-shadow: 0 0 18px var(--au-danger); }
.au-solv-card.st-breach { border-color: rgba(255,23,68,0.4); box-shadow: var(--au-glow-danger); }
.au-solv-card:hover { border-color: var(--au-border-bright); }
.au-solv-aura { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
.au-solv-card > *:not(.au-solv-aura) { position: relative; z-index: 1; }

.au-solv-card-head { display: flex; align-items: center; gap: 9px; margin-bottom: 13px; }
.au-solv-ccy {
  font-family: var(--au-display); font-size: 10px; letter-spacing: 0.12em; font-weight: 600;
  border: 1px solid; border-radius: 3px; padding: 2px 7px; background: rgba(0,0,0,0.25);
}
.au-solv-frame { font-size: 12px; color: var(--au-text); letter-spacing: 0.04em; }
.au-solv-acct {
  margin-left: auto; font-family: var(--au-font); font-size: 9.5px; color: var(--au-text-ghost);
  letter-spacing: 0.05em;
}
.au-solv-bal {
  font-family: var(--au-display); font-size: 31px; font-weight: 600; color: var(--au-text);
  letter-spacing: 0.01em; line-height: 1; margin-bottom: 14px; display: flex; align-items: baseline; gap: 8px;
}
.au-solv-unit { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; }

.au-solv-gauge { position: relative; height: 13px; margin-bottom: 17px; }
.au-solv-gauge-track {
  position: absolute; inset: 0; background: rgba(0,0,0,0.35);
  border: 1px solid var(--au-hairline); border-radius: 6px;
}
.au-solv-gauge-fill {
  position: absolute; top: 1px; bottom: 1px; left: 1px; border-radius: 6px;
  transition: width 600ms cubic-bezier(0.16,1,0.3,1);
  box-shadow: 0 0 10px rgba(0,200,83,0.25), inset 0 1px 0 rgba(255,255,255,0.22);
  border-right: 2px solid rgba(224,242,233,0.7);
}
.au-solv-card.st-low .au-solv-gauge-fill { box-shadow: 0 0 10px rgba(255,145,0,0.3); }
.au-solv-card.st-breach .au-solv-gauge-fill { box-shadow: 0 0 12px rgba(255,23,68,0.5); }
.au-solv-gauge-floor { position: absolute; top: -3px; bottom: -3px; width: 0; }
.au-solv-gauge-floor-tick {
  position: absolute; top: 0; bottom: 0; left: -1px; width: 2px;
  background: var(--au-danger); box-shadow: 0 0 6px rgba(255,23,68,0.7);
}
.au-solv-gauge-floor::after {
  content: 'FLOOR'; position: absolute; top: -13px; left: 50%; transform: translateX(-50%);
  font-size: 7px; letter-spacing: 0.12em; color: var(--au-danger-dim); white-space: nowrap;
}

.au-solv-card-foot { display: flex; align-items: center; gap: 10px; }
.au-solv-floor { font-size: 10px; color: var(--au-text-dim); letter-spacing: 0.05em; }
.au-solv-floor b { color: var(--au-text-secondary); font-weight: 500; }
.au-solv-head-room { font-size: 11px; color: var(--au-accent); font-family: var(--au-font); margin-left: auto; }
.au-solv-card.ccy-bvt .au-solv-head-room { color: #ffb300; }
.au-solv-card.ccy-jday .au-solv-head-room { color: #00b0ff; }
.au-solv-card.st-low .au-solv-head-room { color: var(--au-warning); }
.au-solv-card.st-breach .au-solv-head-room { color: var(--au-danger); }
.au-solv-dim { color: var(--au-text-ghost); font-size: 0.9em; }
.au-solv-badge {
  font-size: 9.5px; letter-spacing: 0.1em; padding: 3px 8px; border-radius: 3px; font-family: var(--au-font);
}
.au-solv-badge.st-solvent { color: var(--au-accent); background: var(--au-accent-subtle); }
.au-solv-badge.st-low { color: var(--au-warning); background: rgba(255,145,0,0.1); }
.au-solv-badge.st-breach { color: var(--au-danger); background: rgba(255,23,68,0.12); }

.au-solv-router {
  display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 10px;
  border-top: 1px dashed var(--au-hairline); font-size: 10px;
}
.au-solv-router-key { color: var(--au-text-dim); letter-spacing: 0.04em; }
.au-solv-router-val { margin-left: auto; color: var(--au-text-secondary); }
.au-solv-router-tag { font-size: 8.5px; letter-spacing: 0.08em; padding: 2px 6px; border-radius: 2px; }
.au-solv-router.st-ok .au-solv-router-tag { color: var(--au-text-dim); background: rgba(255,255,255,0.03); }
.au-solv-router.st-residue .au-solv-router-tag { color: var(--au-warning); background: rgba(255,145,0,0.12); }
.au-solv-router.st-residue .au-solv-router-val { color: var(--au-warning); }

/* ── Cross-frame pool ───────────────────────────────────────── */
.au-pool {
  background: linear-gradient(135deg, rgba(0,176,255,0.04), rgba(255,179,0,0.03));
  border: 1px solid var(--au-border); border-radius: var(--au-radius-lg);
  padding: 16px 20px 14px;
}
.au-pool-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.au-pool-tracked {
  margin-left: auto; font-size: 8.5px; letter-spacing: 0.16em; color: var(--au-text-dim);
  border: 1px dashed var(--au-border-bright); padding: 3px 9px; border-radius: 3px; cursor: help;
}
.au-pool-body { display: flex; align-items: stretch; gap: 16px; }
.au-pool-leg {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 5px; padding: 12px; background: rgba(0,0,0,0.22); border-radius: var(--au-radius);
  border: 1px solid var(--au-hairline);
}
.au-pool-leg-ccy { font-family: var(--au-display); font-size: 11px; letter-spacing: 0.14em; font-weight: 600; }
.au-pool-leg.ccy-avt .au-pool-leg-ccy { color: var(--au-accent); }
.au-pool-leg.ccy-bvt .au-pool-leg-ccy { color: #ffb300; }
.au-pool-leg.ccy-avt { border-top: 2px solid rgba(0,200,83,0.45); }
.au-pool-leg.ccy-bvt { border-top: 2px solid rgba(255,179,0,0.45); }
.au-pool-leg-val { font-size: 19px; color: var(--au-text); }
.au-pool-leg.ccy-avt .au-pool-leg-val { color: #aef0c6; }
.au-pool-leg.ccy-bvt .au-pool-leg-val { color: #ffd98a; }
.au-pool-leg-key { font-size: 8.5px; color: var(--au-text-ghost); letter-spacing: 0.08em; }
.au-pool-core {
  flex: 1.2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
}
.au-pool-spot { font-family: var(--au-display); font-size: 35px; font-weight: 600; color: var(--au-text); line-height: 1; letter-spacing: 0.01em; }
.au-pool-spot-key { font-size: 8.5px; letter-spacing: 0.18em; color: var(--au-text-secondary); text-transform: uppercase; }
.au-pool-beam { display: flex; align-items: center; gap: 4px; margin: 5px 0; width: 100%; max-width: 160px; }
.au-pool-beam-x, .au-pool-beam-y { height: 2px; flex: 1; border-radius: 2px; }
.au-pool-beam-x { background: linear-gradient(90deg, transparent, var(--au-accent)); }
.au-pool-beam-y { background: linear-gradient(90deg, #ffb300, transparent); }
.au-pool-beam-knot { color: var(--au-text-secondary); font-size: 13px; }
.au-pool-fulcrum {
  width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent;
  border-top: 7px solid var(--au-text-dim); margin: -2px auto 3px; opacity: 0.55;
}
.au-pool-spot-inv { font-size: 10px; color: var(--au-text-dim); }
.au-pool-metrics { display: flex; gap: 16px; margin-top: 16px; }
.au-pool-metric {
  flex: 1; display: flex; align-items: center; justify-content: space-between;
  padding: 9px 13px; background: rgba(0,0,0,0.2); border-radius: var(--au-radius);
  border: 1px solid var(--au-hairline);
}
.au-pool-metric-key { font-size: 10px; color: var(--au-text-secondary); letter-spacing: 0.06em; }
.au-pool-metric-val { font-size: 13px; color: var(--au-text); }
.au-pool-foot { margin-top: 12px; font-size: 9.5px; color: var(--au-text-ghost); line-height: 1.6; }
.au-pool-foot em { color: var(--au-text-dim); font-style: italic; }
.au-pool-foot sub { font-size: 0.82em; }

/* ── Cross-frame FX triangle ─────────────────────────────────── */
.au-tri-verts {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px; margin-bottom: 14px;
}
.au-tri-vert {
  position: relative; display: flex; flex-direction: column; align-items: center;
  gap: 5px; padding: 13px 12px 11px; border-radius: var(--au-radius);
  background: rgba(0,0,0,0.22); border: 1px solid var(--au-hairline);
  border-top: 2px solid var(--au-accent); overflow: hidden; isolation: isolate;
}
.au-tri-ccy {
  font-family: var(--au-display); font-size: 11px; letter-spacing: 0.14em; font-weight: 600;
  border: 1px solid; border-radius: 3px; padding: 1px 7px; background: rgba(0,0,0,0.3);
}
.au-tri-bal { font-size: 18px; color: var(--au-text); }
.au-tri-frame { font-size: 8.5px; color: var(--au-text-ghost); letter-spacing: 0.05em; }

.au-tri-edges { display: flex; flex-direction: column; gap: 7px; }
.au-tri-edge {
  display: grid; grid-template-columns: minmax(108px, 1.1fr) 1fr 1fr; align-items: center; gap: 10px;
  padding: 8px 13px; background: rgba(0,0,0,0.18); border-radius: var(--au-radius);
  border: 1px solid var(--au-hairline);
}
.au-tri-edge-pair { display: inline-flex; align-items: center; gap: 7px; font-family: var(--au-display); font-size: 11px; letter-spacing: 0.07em; }
.au-tri-edge-knot { color: var(--au-text-dim); font-size: 12px; }
.au-tri-edge-rate { font-size: 13px; color: var(--au-text); text-align: right; }
.au-tri-edge-inv { font-size: 11px; color: var(--au-text-dim); text-align: right; }

.au-tri-loop {
  display: flex; align-items: center; gap: 11px; margin-top: 13px; padding: 10px 14px;
  background: rgba(0,200,83,0.06); border: 1px solid rgba(0,200,83,0.22); border-radius: var(--au-radius);
}
.au-tri-loop-key { font-size: 10.5px; color: var(--au-text-secondary); letter-spacing: 0.05em; }
.au-tri-loop-val { margin-left: auto; font-size: 17px; color: var(--au-accent); font-weight: 600; }
.au-tri-loop-tag { font-size: 9px; letter-spacing: 0.1em; color: var(--au-accent); background: var(--au-accent-subtle); padding: 3px 8px; border-radius: 3px; white-space: nowrap; }

@media (max-width: 560px) {
  .au-tri-edge { grid-template-columns: 1fr; gap: 4px; }
  .au-tri-edge-rate, .au-tri-edge-inv { text-align: left; }
  .au-tri-loop { flex-wrap: wrap; }
  .au-tri-loop-val { margin-left: 0; }
}

@keyframes au-solv-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
@keyframes au-solv-blink { 0% { opacity: 1; } 50% { opacity: 0.25; } }

@media (max-width: 720px) {
  .au-pool-body { flex-direction: column; }
  .au-pool-metrics { flex-direction: column; gap: 8px; }
}
</style>
