<!--
  Circulating Supply (V4, reframed 2026-06-10) — the clean per-frame supply picture.

  Headline is CIRCULATING SUPPLY (the real number). Then the actionable signal: is any
  NEW value getting stuck (transit drift vs baseline). Then WHERE it sits. The full
  identity (issued − destroyed + net-position = circulating) is a collapsible
  reconciliation detail for auditors — `net cross-frame & escrow position` (transit_net)
  is a by-design accounting term (≈0 intra-frame; non-zero = this frame's net external
  flow), Δ=0-conserved, NOT missing/stuck funds. The breakdown sums exactly to it
  (escrow/stake legs + a balancing transfer_settlement line) — nothing "unknown".
-->
<template>
  <section v-if="compFrames.length" class="au-comp">
    <div class="au-comp-head">
      <span class="au-comp-glyph" aria-hidden="true">&#x25D1;</span>
      <span class="au-label">WHERE IS THE MONEY?</span>
      <span class="au-comp-tag">PER FRAME &middot; WHERE IT SITS &middot; &Delta;=0 CONSERVED</span>
    </div>

    <div class="au-comp-grid">
      <article v-for="f in compFrames" :key="f.id" :id="'comp-' + f.id" class="au-comp-card">
        <header class="au-comp-card-head">
          <span class="au-comp-frame">{{ f.name }}</span>
          <span class="au-comp-ccy">{{ f.c.currency || '' }}</span>
          <span class="au-comp-holders">{{ f.c.holder_count.toLocaleString() }} holders</span>
        </header>

        <!-- Headline: circulating supply (the clean real number) -->
        <div class="au-comp-headline">
          <span class="au-comp-headline-v au-mono">{{ fmt(f.c.circulating) }}</span>
          <span class="au-comp-headline-u">{{ f.c.currency || '' }} in circulation</span>
          <button class="au-comp-info" type="button" @click="openRecon($event)"
                  aria-label="What is this number? Open the reconciliation detail"
                  title="What is this? — open the reconciliation breakdown that explains issued vs circulating">i</button>
        </div>

        <!-- Supply tiers — circulating = issued + net escrow/transit. Makes the
             issued↔circulating gap self-evident so the card never reads as a Δ-break. -->
        <div class="au-comp-identity au-mono" :title="identityTitle(f.c)">
          <span class="au-comp-id-eq">=</span>
          <span class="au-comp-id-base">{{ fmt(native(f.c)) }}</span>
          <span class="au-comp-id-lbl">net issued <em>(ledger)</em></span>
          <span class="au-comp-id-op" :class="f.c.transit_net < 0 ? 'neg' : 'pos'">{{ f.c.transit_net < 0 ? '−' : '+' }}</span>
          <span class="au-comp-id-add" :class="f.c.transit_net < 0 ? 'neg' : 'pos'">{{ fmtAbs(f.c.transit_net) }}</span>
          <span class="au-comp-id-lbl">escrow &amp; transit</span>
        </div>

        <!-- HONEST ISSUANCE (V6): the line above is the ledger ACCUMULATOR (issued_acc −
             destroyed_acc, genesis-inclusive + transfer-leg folded), NOT confirmed issuance.
             Distinguish it from VERIFIED typed issuance so the card never overstates issuance. -->
        <div v-if="f.ns" class="au-comp-mint" :class="f.ns.native_supply_ok === true ? 'mint-ok' : 'mint-genesis'">
          <template v-if="f.ns.native_supply_ok === true">
            <span class="au-comp-mint-i">&check;</span>
            <b>fully verified</b> &mdash; typed issuance <b class="au-mono">{{ fmt(f.ns.native_issued) }}</b> {{ f.ns.native_currency }}
            reconcile exactly with circulating, &Delta;=0.
          </template>
          <template v-else-if="f.ns.native_issued === 0">
            <span class="au-comp-mint-i">&check;</span>
            <b>&Delta;=0 conserved.</b> No new {{ f.ns.native_currency }} issued since baseline &mdash; it is a relabel of this
            founding frame's original currency; genesis issuance predates the verification baseline (expected, not a gap).
          </template>
          <template v-else>
            <span class="au-comp-mint-i">&check;</span>
            <b>&Delta;=0 conserved.</b> <b class="au-mono">{{ fmt(f.ns.native_issued) }}</b> {{ f.ns.native_currency }} issued by typed events since baseline;
            the rest is genesis-era (predates it). Founding frame &mdash; independent issuance reconciliation covers the
            post-baseline window only, not a discrepancy.
          </template>
        </div>

        <!-- Transit position drift vs baseline (it's transit_net movement, not stranding) -->
        <div v-if="f.c.transit_drift_status" class="au-comp-drift" :class="'drift-' + f.c.transit_drift_status.toLowerCase()"
             title="Movement of the escrow/settlement position since the last clean baseline — a monitoring signal, not the position itself. Δ=0 is unaffected.">
          <span class="au-comp-drift-dot"></span>
          <span class="au-comp-drift-label">DRIFT</span>
          <span class="au-comp-drift-base">vs baseline</span>
          <span class="au-comp-drift-tag">{{ driftText(f.c.transit_drift_status) }}</span>
          <span class="au-comp-drift-val au-mono">{{ fmtSigned(f.c.transit_drift || 0) }}</span>
        </div>

        <!-- Where it sits: stacked bar -->
        <div class="au-comp-where">
          <div class="au-comp-where-label">WHERE IT SITS</div>
          <div class="au-comp-bar" role="img" :aria-label="'supply distribution for ' + f.name">
            <span v-for="seg in segments(f.c)" :key="seg.key"
                  class="au-comp-seg" :class="'seg-' + seg.key"
                  :style="{ width: seg.pct + '%' }"
                  :title="seg.label + ' ' + fmt(seg.val) + ' (' + seg.pct.toFixed(1) + '%)'"></span>
          </div>
          <div class="au-comp-legend">
            <span v-for="seg in segments(f.c)" :key="seg.key" class="au-comp-leg">
              <i class="au-comp-dot" :class="'seg-' + seg.key"></i>{{ seg.label }}
              <b class="au-mono">{{ fmtShort(seg.val) }}</b>
            </span>
          </div>
        </div>

        <!-- Top holders -->
        <div class="au-comp-holders-list">
          <div class="au-comp-where-label">TOP HOLDERS</div>
          <div v-for="(h, i) in f.c.top_holders.slice(0, 6)" :key="h.did" class="au-comp-holder">
            <span class="au-comp-rank">{{ i + 1 }}</span>
            <span class="au-comp-htag" :class="'seg-' + holderSeg(h.label)">{{ h.label }}</span>
            <code class="au-comp-hdid">{{ shortDid(h.did) }}</code>
            <span class="au-comp-hval au-mono">{{ fmtShort(h.total) }}</span>
          </div>
        </div>

        <!-- Reconciliation detail (collapsible — auditors only) -->
        <details class="au-comp-recon">
          <summary class="au-comp-recon-sum">Reconciliation detail &middot; supply identity &amp; breakdown</summary>
          <div class="au-comp-recon-note">
            <code>net issued &minus; destroyed + net&nbsp;position = circulating</code> (&Delta;=0 by construction).
            <b>net issued (ledger)</b> is the per-event accumulator (<code>issued_acc &minus; destroyed_acc</code>) &mdash;
            genesis-inclusive and with cross-frame transfer legs folded in, so it is <b>not</b> the same as
            confirmed typed issuance (see <b>Native Supply</b> for the verified per-currency figure).
            <b>net escrow &amp; settlement position</b> is &asymp;0 for a fully-settled single ledger; non-zero =
            value held in escrow + in-flight cross-TEG / cross-frame settlement, conserved across the
            federation &mdash; not missing funds.
          </div>
          <div class="au-comp-water">
            <div class="au-comp-row"><span class="au-comp-k">net issued <em>(ledger accumulator)</em></span><span class="au-comp-v au-mono">{{ fmt(f.c.issued) }}</span></div>
            <div class="au-comp-row au-comp-sub-row"><span class="au-comp-k">&minus; destroyed</span><span class="au-comp-v au-mono">{{ fmt(f.c.destroyed) }}</span></div>
            <div class="au-comp-row au-comp-sub-row" :class="f.c.transit_net < 0 ? 'neg' : 'pos'">
              <span class="au-comp-k">+ net escrow &amp; settlement position</span>
              <span class="au-comp-v au-mono">{{ fmt(f.c.transit_net) }}</span>
            </div>
            <div class="au-comp-row au-comp-total"><span class="au-comp-k">= circulating</span><span class="au-comp-v au-mono">{{ fmt(f.c.circulating) }}</span></div>
          </div>
          <div v-if="f.c.transit_by_kind && f.c.transit_by_kind.length" class="au-comp-transit">
            <div class="au-comp-where-label">
              breakdown <span class="au-comp-dim" v-if="f.c.transit_by_kind_at">&middot; {{ ago(f.c.transit_by_kind_at) }}</span>
              <span v-if="f.c.reconciled" class="au-comp-recon-ok">&check; sums to position</span>
            </div>
            <div class="au-comp-flow-note">escrow lock/release are <b>gross</b> 2-phase flow &mdash; they net into the position above, not standing balances.</div>
            <div v-for="r in topKinds(f.c.transit_by_kind)" :key="r.kind" class="au-comp-kind">
              <span class="au-comp-kind-name" :class="r.net_to_balances < 0 ? 'neg' : 'pos'">{{ kindLabel(r.kind) }}</span>
              <span class="au-comp-kind-ev">{{ r.events != null ? r.events.toLocaleString() + ' ev' : 'net' }}</span>
              <span class="au-comp-kind-val au-mono" :class="r.net_to_balances < 0 ? 'neg' : 'pos'">{{ fmtSigned(r.net_to_balances) }}</span>
            </div>
          </div>
        </details>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import type { Composition, NativeSupply } from '@/types/auditor'

const store = useAuditorStore()
const { frames, latestByFrame } = storeToRefs(store)

interface CompFrame { id: string; name: string; c: Composition; ns: NativeSupply | null }

const compFrames = computed<CompFrame[]>(() =>
  (frames.value || [])
    .map((f) => {
      const c = latestByFrame.value[f.id]?.extra_data?.composition
      const ns = latestByFrame.value[f.id]?.extra_data?.native_supply || null
      return c ? { id: f.id, name: f.name, c, ns } : null
    })
    .filter((x): x is CompFrame => x !== null),
)

const fmt = (n: number) => Math.round(n).toLocaleString()
const fmtShort = (n: number) => {
  const a = Math.abs(n)
  if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (a >= 1e3) return (n / 1e3).toFixed(0) + 'k'
  return Math.round(n).toString()
}
const fmtSigned = (n: number) => (n >= 0 ? '+' : '') + fmtShort(n)
const fmtAbs = (n: number) => fmt(Math.abs(n))

// Supply tiers: native (locally issued, net of burns) is the monetary base;
// transit_net is the net escrow + cross-TEG/cross-frame settlement position on top.
// native + transit_net = circulating, by construction.
const native = (c: Composition) => c.issued - c.destroyed
// Info "i" → open + scroll to THIS frame's reconciliation detail (the explainer).
const openRecon = (ev: Event) => {
  const card = (ev.currentTarget as HTMLElement | null)?.closest('.au-comp-card')
  const det = card?.querySelector('details.au-comp-recon') as HTMLDetailsElement | null
  if (det) {
    det.open = true
    det.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
}

const identityTitle = (c: Composition) =>
  `circulating ${fmt(c.circulating)} = issued ${fmt(c.issued)}`
  + (c.destroyed ? ` − destroyed ${fmt(c.destroyed)}` : '')
  + ` ${c.transit_net < 0 ? '−' : '+'} ${fmtAbs(c.transit_net)} net escrow & settlement position (Δ=0)`

const SEG_DEFS = [
  { key: 'staked', label: 'locked', get: (c: Composition) => c.buckets.total_staked },
  { key: 'treasury', label: 'treasury', get: (c: Composition) => c.buckets.treasury },
  { key: 'fee', label: 'fee_collector', get: (c: Composition) => c.buckets.fee_collector },
  { key: 'fxreserve', label: 'fx_reserve', get: (c: Composition) => c.buckets.fx_reserve },
  { key: 'escrow', label: 'escrow (open orders)', get: (c: Composition) => c.buckets.escrow || 0 },
  // liquid agents = agents bucket minus the locked already shown (locked spans agents+whales);
  // approximate "liquid in agents" = circulating − locked − system buckets − escrow, floored at 0.
  { key: 'agents', label: 'agents (liquid)', get: (c: Composition) =>
      Math.max(0, c.circulating - c.buckets.total_staked - c.buckets.treasury - c.buckets.fee_collector - c.buckets.fx_reserve - (c.buckets.escrow || 0)) },
]

const segments = (c: Composition) => {
  const total = Math.max(1, c.circulating)
  return SEG_DEFS.map((s) => {
    const val = s.get(c)
    return { key: s.key, label: s.label, val, pct: (val / total) * 100 }
  }).filter((s) => s.val > 0)
}

const holderSeg = (label: string) => {
  if (label === 'treasury') return 'treasury'
  if (label === 'fee_collector') return 'fee'
  if (label === 'fx_reserve') return 'fxreserve'
  if (label === 'fx_router') return 'fxreserve'
  return 'agents'
}

const topKinds = (rows: { kind: string; events: number | null; net_to_balances: number }[]) =>
  [...rows].sort((a, b) => Math.abs(b.net_to_balances) - Math.abs(a.net_to_balances)).slice(0, 8)

// Friendly labels for the reconciliation breakdown (no raw enum/"unknown").
const KIND_LABELS: Record<string, string> = {
  cross_teg_escrow_lock: 'escrow lock',
  cross_teg_escrow_release: 'escrow release',
  cross_teg_escrow_compensate: 'escrow compensate',
  escrow_reconcile_release: 'escrow reconcile',
  escrow_negative_lock_clamp: 'escrow clamp',
  stake_lock: 'lock',
  stake_unlock: 'unlock',
  transfer_settlement: 'transfer settlement (net)',
}
const kindLabel = (k: string): string => KIND_LABELS[k] || k.replace(/_/g, ' ')

const driftText = (s: string): string => {
  if (s === 'STRANDING') return 'net outflow'
  if (s === 'RETURNING') return 'net inflow'
  return 'at baseline'
}

const shortDid = (did: string) => {
  if (did.includes('teg_system')) return did.split(':').pop() || did
  const tail = did.split(':').pop() || did
  return tail.length > 14 ? tail.slice(0, 8) + '…' : tail
}

const ago = (iso: string) => {
  try {
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
    if (s < 90) return 'just now'
    if (s < 5400) return Math.round(s / 60) + 'm ago'
    return Math.round(s / 3600) + 'h ago'
  } catch { return '' }
}
</script>

<style scoped>
.au-comp { margin: 22px 0; }
.au-comp-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.au-comp-glyph { color: #7fe9c8; font-size: 16px; }
.au-label { font-family: var(--au-mono, ui-monospace, monospace); font-size: 12px; font-weight: 800; letter-spacing: 0.18em; color: #cfe9e2; }
.au-comp-tag { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; border: 1px solid rgba(127,233,200,0.25); border-radius: 99px; padding: 2px 8px; }
.au-comp-sub { font-size: 12px; color: #8aa39d; margin-bottom: 14px; max-width: 70ch; line-height: 1.5; }
.au-comp-sub code, .au-mono { font-family: var(--au-mono, ui-monospace, monospace); }
.au-comp-sub code { color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 5px; border-radius: 4px; }

.au-comp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.au-comp-card {
  border: 1px solid rgba(127,233,200,0.14); border-radius: 14px; padding: 16px 18px;
  background: linear-gradient(180deg, rgba(20,40,36,0.40), rgba(12,22,20,0.20));
  scroll-margin-top: 84px; /* so the "i" jump from the top supply list lands below any header */
}
/* brief highlight when an "i" jump lands here */
.au-comp-card.au-comp-flash { animation: auCompFlash 1.8s ease-out; }
@keyframes auCompFlash {
  0% { border-color: rgba(127,233,200,0.9); box-shadow: 0 0 0 2px rgba(127,233,200,0.35); }
  100% { border-color: rgba(127,233,200,0.14); box-shadow: none; }
}
.au-comp-card-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.au-comp-frame { font-weight: 800; color: #e6f5f0; font-size: 15px; }
.au-comp-ccy { font-family: var(--au-mono, monospace); font-size: 10px; color: #7fe9c8; border: 1px solid rgba(127,233,200,0.3); border-radius: 5px; padding: 1px 6px; }
.au-comp-holders { margin-left: auto; font-size: 10.5px; color: #6f8a83; }

/* Headline: circulating supply — the clean real number, front and center */
.au-comp-headline { display: flex; align-items: baseline; gap: 9px; margin: 2px 0 10px; }
.au-comp-headline-v { font-size: 26px; font-weight: 800; color: #7fe9c8; line-height: 1; letter-spacing: -0.01em; }
.au-comp-headline-u { font-size: 11px; color: #8aa39d; }

/* Supply-tier identity line: circulating = issued + net escrow/transit */
.au-comp-identity { display: flex; align-items: baseline; flex-wrap: wrap; gap: 5px; margin: 0 0 11px; font-size: 11.5px; }
.au-comp-id-eq { color: #51655f; }
.au-comp-id-base { color: #cfe2dc; }
.au-comp-id-lbl { color: #6f8a83; font-size: 10px; letter-spacing: 0.02em; }
.au-comp-id-op { font-weight: 800; }
.au-comp-id-add { font-weight: 700; }
.au-comp-id-op.pos, .au-comp-id-add.pos { color: #7fe9c8; }
.au-comp-id-op.neg, .au-comp-id-add.neg { color: #ffcf6b; }
.au-comp-id-lbl em { font-style: normal; color: #51655f; }

/* Honest issuance caption — distinguishes the ledger accumulator from VERIFIED typed issuance (V6) */
.au-comp-mint { font-size: 11px; line-height: 1.5; margin: -2px 0 11px; padding: 6px 9px; border-radius: 8px; max-width: 64ch; }
.au-comp-mint b { color: #e6f5f0; }
.au-comp-mint .au-mono { color: #e6f5f0; }
.au-comp-mint-i { font-weight: 800; margin-right: 4px; }
.au-comp-mint.mint-ok { background: rgba(127,233,200,0.08); color: #9fd8c8; }
.au-comp-mint.mint-ok .au-comp-mint-i { color: #7fe9c8; }
/* genesis-era frames (A/B): Δ=0-conserved, calm/neutral — NEVER an amber warning */
.au-comp-mint.mint-genesis { background: rgba(127,233,200,0.05); color: #9fb8b2; }
.au-comp-mint.mint-genesis .au-comp-mint-i { color: #7fc9b0; }

/* "i" info affordance on the circulating headline → opens the reconciliation detail */
.au-comp-info {
  margin-left: 6px; align-self: center; width: 16px; height: 16px; flex: none;
  border-radius: 50%; border: 1px solid rgba(127,233,200,0.40); background: rgba(127,233,200,0.06);
  color: #7fe9c8; font-family: Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 700;
  font-size: 11px; line-height: 1; cursor: pointer; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
}
.au-comp-info:hover { background: rgba(127,233,200,0.18); border-color: #7fe9c8; }
.au-comp-info:active { transform: scale(0.92); }
.au-comp-info:focus-visible { outline: 2px solid #7fe9c8; outline-offset: 2px; }

/* Reconciliation detail — collapsed by default; auditors expand it */
.au-comp-recon { margin-top: 12px; border-top: 1px dashed rgba(127,233,200,0.16); padding-top: 8px; }
.au-comp-recon-sum { cursor: pointer; font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; user-select: none; }
.au-comp-recon-sum:hover { color: #aee7d6; }
.au-comp-recon-note { font-size: 11px; color: #8aa39d; line-height: 1.5; margin: 8px 0 10px; max-width: 64ch; }
.au-comp-recon-note code { color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 5px; border-radius: 4px; font-family: var(--au-mono, monospace); }
.au-comp-recon-ok { color: #7fe9c8; font-size: 9px; margin-left: 6px; letter-spacing: 0; }

.au-comp-water { border-bottom: 1px dashed rgba(127,233,200,0.16); padding-bottom: 10px; margin-bottom: 12px; }
.au-comp-row { display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; font-size: 13px; }
.au-comp-k { color: #b6cfc9; }
.au-comp-k em { color: #7f9c95; font-style: normal; font-size: 11px; }
.au-comp-v { color: #e6f5f0; font-size: 13px; }
.au-comp-sub-row .au-comp-k, .au-comp-sub-row .au-comp-v { color: #93ada7; font-size: 12px; }
.au-comp-row.neg .au-comp-v { color: #ffb38a; }
.au-comp-row.pos .au-comp-v { color: #7fe9c8; }
.au-comp-transit-char { font-size: 10px; color: #c79a7a; margin: -2px 0 4px; padding-left: 2px; font-style: italic; }
.au-comp-total { margin-top: 4px; padding-top: 6px; border-top: 1px solid rgba(127,233,200,0.18); }
.au-comp-total .au-comp-k { font-weight: 800; color: #e6f5f0; }
.au-comp-total .au-comp-v { font-weight: 800; color: #7fe9c8; font-size: 14px; }

.au-comp-where-label { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.12em; color: #6f8a83; margin: 10px 0 6px; }
.au-comp-dim { color: #51655f; }
.au-comp-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: rgba(255,255,255,0.04); }
/* min-width so small-but-present tiers (e.g. escrow) stay visible instead of collapsing to sub-pixel */
.au-comp-seg { height: 100%; min-width: 3px; }
.seg-staked { background: #5bb3ff; }
.seg-treasury { background: #b88bff; }
.seg-fee { background: #ffcf6b; }
.seg-fxreserve { background: #7fe9c8; }
.seg-escrow { background: #ff8fab; }
.seg-agents { background: #3d6e64; }
.au-comp-legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 7px; }
.au-comp-leg { font-size: 10.5px; color: #9fb8b2; display: inline-flex; align-items: center; gap: 4px; }
.au-comp-leg b { color: #d6ece6; }
.au-comp-dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }

.au-comp-holder { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 11.5px; }
.au-comp-rank { color: #51655f; width: 12px; font-family: var(--au-mono, monospace); }
.au-comp-htag { font-size: 9px; padding: 1px 6px; border-radius: 99px; color: #0c1614; font-weight: 700; }
.au-comp-htag.seg-treasury { background: #b88bff; } .au-comp-htag.seg-fee { background: #ffcf6b; }
.au-comp-htag.seg-fxreserve { background: #7fe9c8; } .au-comp-htag.seg-agents { background: #3d6e64; color: #cfe9e2; }
.au-comp-hdid { color: #8aa39d; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.au-comp-hval { color: #e6f5f0; }

.au-comp-transit { margin-top: 12px; border-top: 1px dashed rgba(127,233,200,0.16); padding-top: 10px; }
.au-comp-flow-note { font-size: 10px; color: #7f9c95; font-style: italic; margin: 1px 0 7px; line-height: 1.45; max-width: 60ch; }
.au-comp-flow-note b { color: #c79a7a; font-style: normal; }
.au-comp-kind { display: flex; align-items: center; gap: 8px; padding: 2px 0; font-size: 11.5px; }
.au-comp-kind-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.au-comp-kind-name.neg { color: #ffb38a; } .au-comp-kind-name.pos { color: #7fe9c8; }
.au-comp-kind-ev { color: #6f8a83; font-size: 10px; }
.au-comp-kind-val.neg { color: #ffb38a; } .au-comp-kind-val.pos { color: #7fe9c8; }

.au-comp-drift { display: flex; align-items: center; gap: 7px; margin-top: 6px; padding: 5px 8px; border-radius: 7px; font-size: 11px; }
.au-comp-drift-dot { width: 7px; height: 7px; border-radius: 50%; }
.au-comp-drift-label { color: #9fb8b2; font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.08em; }
.au-comp-drift-base { color: #6f8a83; font-size: 9px; letter-spacing: 0; }
.au-comp-drift-val { font-weight: 700; }
.au-comp-drift-tag { margin-left: auto; font-size: 10px; }
.drift-ok { background: rgba(127,233,200,0.07); }
.drift-ok .au-comp-drift-dot { background: #7fe9c8; } .drift-ok .au-comp-drift-val, .drift-ok .au-comp-drift-tag { color: #7fe9c8; }
.drift-stranding { background: rgba(248,113,113,0.10); }
.drift-stranding .au-comp-drift-dot { background: #f87171; animation: driftPulse 1.6s ease-in-out infinite; } .drift-stranding .au-comp-drift-val, .drift-stranding .au-comp-drift-tag { color: #ff9b8a; }
.drift-returning { background: rgba(255,207,107,0.08); }
.drift-returning .au-comp-drift-dot { background: #ffcf6b; } .drift-returning .au-comp-drift-val, .drift-returning .au-comp-drift-tag { color: #ffcf6b; }
@keyframes driftPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
</style>
