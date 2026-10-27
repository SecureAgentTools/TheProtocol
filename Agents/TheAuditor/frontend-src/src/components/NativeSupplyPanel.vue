<!--
  Native Supply (V6, 2026-06-19) — per-currency conservation on a currency-blind ledger.

  The balance ledger is currency-AGNOSTIC: "circulating" sums every currency present on a
  frame's books while "issued" is native issuance — so an FX-active frame reads circulating >
  issued. That is a metric artifact, NOT a leak. This panel reframes it honestly:
     native_circulating = circulating − transit_net   (transit_net = in-transit cross-frame
                          settlement residue; the foreign/in-flight value on the books)
  and gates the proof on coverage: a frame whose issuance is all post-baseline (typed_mints
  complete) is PROVEN (native_issued == native_circulating, recon_gap ≈ 0); a genesis frame
  whose issuance predates the audit baseline is honestly framed as genesis-era (Δ=0 still
  holds — NOT a breach). The cross-TEG rail is same-currency by design (cross-currency settles
  on the FX rail, not here), so its volume is attributed entirely to the frame's native currency.
-->
<template>
  <section v-if="nsFrames.length" class="au-ns">
    <div class="au-ns-head">
      <span class="au-ns-glyph" aria-hidden="true">&#x25C8;</span>
      <span class="au-label">WAS EVERY UNIT ACTUALLY ISSUED?</span>
      <InfoDot title="How native conservation is proven" testid="info-au-ns-sub">
        The ledger is currency-agnostic, so a frame's <code>circulating</code> sums every currency on its
      books while <code>issued</code> is native issuance. Native conservation =
      <code>native circulating (= circulating &minus; in-transit) == native issued</code>. Proven where issuance
      coverage is complete; a genesis frame whose issuance predates the audit baseline is marked unverified
      (&Delta;=0 still holds).
      </InfoDot>
      <span class="au-ns-tag">PER CURRENCY &middot; ISSUED = CIRCULATING &middot; CURRENCY-BLIND LEDGER</span>
    </div>

    <div class="au-ns-grid">
      <article v-for="f in nsFrames" :key="f.id" class="au-ns-card" :class="okClass(f.n)">
        <header class="au-ns-card-head">
          <span class="au-ns-frame">{{ f.name }}</span>
          <span class="au-ns-ccy">{{ glyph(f.n.native_currency) }} {{ f.n.native_currency || '' }}</span>
          <span class="au-ns-badge" :class="okClass(f.n)">{{ okText(f.n) }}</span>
        </header>

        <!-- Headline: native currency on the books -->
        <div class="au-ns-headline">
          <span class="au-ns-headline-v au-mono">{{ fmt(f.n.native_circulating) }}</span>
          <span class="au-ns-headline-u">{{ f.n.native_currency || '' }} on the books (native)</span>
        </div>

        <!-- The conservation line: native issued vs native circulating -->
        <div class="au-ns-recon" :class="okClass(f.n)">
          <template v-if="f.n.native_supply_ok === true">
            <span class="au-ns-recon-eq">native issued</span>
            <span class="au-ns-recon-v au-mono">{{ fmt(f.n.native_issued) }}</span>
            <span class="au-ns-recon-op">==</span>
            <span class="au-ns-recon-eq">circulating</span>
            <span class="au-ns-recon-ok">&check; conserved &middot; gap {{ fmtSigned(gapResolved(f.n)) }}<template v-if="isRebased(f.n)"> &middot; rebased over the {{ fmtShort(f.n.writedown_baseline || 0) }} write-down (baseline {{ baselineDay(f.n) }})</template></span>
          </template>
          <!-- false = a real, quantified gap. null = the independent issuance re-derivation does not
               cover this frame's full history. These are different facts and must not share a
               sentence: the old copy called BOTH of them "expected for a founding frame", which
               was false on every frame except Frame A and hid a genuine gap behind reassurance. -->
          <template v-else-if="f.n.native_supply_ok === false">
            <span class="au-ns-recon-warn">
              <b>&check; &Delta;=0 conserved</b>, but native issuance does not reconcile:
              <span class="au-ns-dim">circulating minus cross-frame settlement exceeds independently
              re-derived issuance by</span>
              <b class="au-mono">{{ fmtSigned(gapResolved(f.n)) }} {{ f.n.native_currency }}</b>.
              That balance exists on the ledger without a typed issuance event behind it.
              <span v-if="isRebased(f.n)" class="au-ns-dim">Net of the documented
              {{ fmtShort(f.n.writedown_baseline || 0) }} write-down baseline set {{ baselineDay(f.n) }}.</span>
              <span class="au-ns-dim">Under investigation &mdash; shown rather than smoothed over.</span>
            </span>
          </template>
          <template v-else>
            <span class="au-ns-recon-warn">
              <b>&check; &Delta;=0 conserved.</b>
              <span class="au-ns-dim">Independent issuance re-derivation does not cover this frame's full
              history, so native issuance is not re-computed here
              ({{ fmt(f.n.native_issued) }} {{ f.n.native_currency }} re-derived). Not a discrepancy:
              conservation is still verified atomically.</span>
            </span>
          </template>
        </div>

        <div class="au-ns-basisline"><span class="au-ns-dim">basis:</span> {{ basisLabel(f.n) }}</div>

        <!-- In-transit cross-frame settlement residue (the "extra" vs a naive issued read) -->
        <div class="au-ns-residual" :class="f.n.crossframe_residual < 0 ? 'neg' : 'pos'">
          <span class="au-ns-res-label">in-transit cross-frame settlement</span>
          <span class="au-ns-res-v au-mono">{{ fmtSigned(f.n.crossframe_residual) }}</span>
        </div>

        <!-- Currency attribution: the foreign currency flowing through this frame's books -->
        <div v-if="f.n.crossteg_by_currency && f.n.crossteg_by_currency.length" class="au-ns-ccy-attr">
          <div class="au-ns-where-label">
            CROSS-TEG RAIL VOLUME <span class="au-ns-dim">&middot; same-currency settlement (native)</span>
          </div>
          <div class="au-ns-bar" role="img" :aria-label="'currency mix for ' + f.name">
            <span v-for="c in f.n.crossteg_by_currency" :key="c.currency"
                  class="au-ns-seg" :class="c.native ? 'seg-native' : 'seg-foreign'"
                  :style="{ width: pct(c, f.n) + '%' }"
                  :title="c.currency + (c.native ? ' (native)' : ' (foreign)') + ' — ' + fmt(c.completed_volume) + ' over ' + c.transfers.toLocaleString() + ' transfers'"></span>
          </div>
          <div class="au-ns-legend">
            <span v-for="c in f.n.crossteg_by_currency" :key="c.currency" class="au-ns-leg">
              <i class="au-ns-dot" :class="c.native ? 'seg-native' : 'seg-foreign'"></i>
              {{ glyph(c.currency) }} {{ c.currency }}
              <span class="au-ns-leg-kind">{{ c.native ? 'native' : 'foreign' }}</span>
              <b class="au-mono">{{ fmtShort(c.completed_volume) }}</b>
            </span>
          </div>
          <div class="au-ns-attr-note">
            The cross-registry (cross-TEG) rail is <b>same-currency by design</b> &mdash; cross-currency
            settles on the FX rail, not here &mdash; so this volume is entirely the frame's
            <b>native</b> currency. (The stored per-row currency label is not authoritative; attributed to native.)
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import InfoDot from './InfoDot.vue'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import type { NativeSupply, NativeSupplyCcy } from '@/types/auditor'

const store = useAuditorStore()
const { frames, latestByFrame } = storeToRefs(store)

interface NSFrame { id: string; name: string; n: NativeSupply }

const nsFrames = computed<NSFrame[]>(() =>
  (frames.value || [])
    .map((f) => {
      const n = latestByFrame.value[f.id]?.extra_data?.native_supply
      return n ? { id: f.id, name: f.name, n } : null
    })
    .filter((x): x is NSFrame => x !== null),
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

// §GLOBALSTD Phase 0-A (2026-08-22): the panel must read what the backend publishes.
// Where a frozen write-down baseline exists (recon_basis = writedown_rebaselined) the
// honest figure is recon_gap_rebased; the raw gap restates documented history forever.
const gapResolved = (n: NativeSupply) =>
  n.recon_gap_rebased !== null && n.recon_gap_rebased !== undefined ? n.recon_gap_rebased : n.recon_gap
const isRebased = (n: NativeSupply) =>
  n.recon_basis === 'writedown_rebaselined' && n.recon_gap_rebased !== null && n.recon_gap_rebased !== undefined
const baselineDay = (n: NativeSupply) => (n.writedown_baseline_set_at || '').slice(0, 10)
const BASIS_LABEL: Record<string, string> = {
  typed_mints_complete: 'full issuance coverage',
  federated_reconciled: 'federated reconciliation',
  writedown_rebaselined: 'rebased over documented write-down',
  pre_baseline_genesis: 'issuance predates baseline',
  coverage_unknown: 'coverage unknown',
}
const basisLabel = (n: NativeSupply) => BASIS_LABEL[n.recon_basis] || n.recon_basis

// Currency glyph convention: AVT=◆ · JDAY=◇ · BVT=◈ (matches the 3-currency model).
const GLYPHS: Record<string, string> = { AVT: '◆', JDAY: '◇', BVT: '◈' }
const glyph = (c: string | null) => (c ? GLYPHS[c.toUpperCase()] || '○' : '')

const okClass = (n: NativeSupply) =>
  n.native_supply_ok === true ? 'ok-proven'
  : n.native_supply_ok === false ? 'ok-breach'
  : 'ok-unverified'
const okText = (n: NativeSupply) =>
  n.native_supply_ok === true ? 'CONSERVED ✓'
  : n.native_supply_ok === false ? 'BREACH'
  : 'Δ=0 ✓ · GENESIS-ERA'

const pct = (c: NativeSupplyCcy, n: NativeSupply) => {
  const total = (n.crossteg_by_currency || []).reduce((s, x) => s + Math.abs(x.completed_volume), 0) || 1
  return (Math.abs(c.completed_volume) / total) * 100
}
</script>

<style scoped>
.au-ns { margin: 22px 0; }
.au-ns-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.au-ns-glyph { color: #ffcf6b; font-size: 16px; }
.au-label { font-family: var(--au-mono, ui-monospace, monospace); font-size: 12px; font-weight: 800; letter-spacing: 0.18em; color: #cfe9e2; }
.au-ns-tag { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; border: 1px solid rgba(127,233,200,0.25); border-radius: 99px; padding: 2px 8px; }
.au-ns-sub { font-size: 12px; color: #8aa39d; margin: 6px 0 14px; max-width: 78ch; line-height: 1.55; }
.au-ns-sub code, .au-mono { font-family: var(--au-mono, ui-monospace, monospace); }
.au-ns-sub code { color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 5px; border-radius: 4px; }

.au-ns-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.au-ns-card {
  border: 1px solid rgba(127,233,200,0.14); border-radius: 14px; padding: 16px 18px;
  background: linear-gradient(180deg, rgba(20,40,36,0.40), rgba(12,22,20,0.20));
}
.au-ns-card.ok-proven { border-color: rgba(127,233,200,0.30); }
.au-ns-card.ok-unverified { border-color: rgba(127,233,200,0.20); }
.au-ns-card.ok-breach { border-color: rgba(248,113,113,0.45); }

.au-ns-card-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.au-ns-frame { font-weight: 800; color: #e6f5f0; font-size: 15px; }
.au-ns-ccy { font-family: var(--au-mono, monospace); font-size: 10px; color: #ffcf6b; border: 1px solid rgba(255,207,107,0.3); border-radius: 5px; padding: 1px 6px; }
.au-ns-badge { margin-left: auto; font-family: var(--au-mono, monospace); font-size: 9px; font-weight: 800; letter-spacing: 0.08em; padding: 2px 8px; border-radius: 99px; }
.au-ns-badge.ok-proven { color: #0c1614; background: #7fe9c8; }
.au-ns-badge.ok-unverified { color: #9fd8c8; background: rgba(127,233,200,0.10); border: 1px solid rgba(127,233,200,0.34); }
.au-ns-badge.ok-breach { color: #fff; background: #f87171; }

.au-ns-headline { display: flex; align-items: baseline; gap: 9px; margin: 2px 0 10px; }
.au-ns-headline-v { font-size: 24px; font-weight: 800; color: #e6f5f0; line-height: 1; letter-spacing: -0.01em; }
.au-ns-headline-u { font-size: 11px; color: #8aa39d; }

.au-ns-recon { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; font-size: 11.5px; padding: 7px 9px; border-radius: 8px; margin-bottom: 8px; }
.au-ns-recon.ok-proven { background: rgba(127,233,200,0.08); }
.au-ns-recon.ok-unverified { background: rgba(127,233,200,0.05); }
.au-ns-recon.ok-breach { background: rgba(248,113,113,0.10); }
.au-ns-recon-eq { color: #6f8a83; font-size: 10px; }
.au-ns-recon-v { color: #cfe2dc; }
.au-ns-recon-op { color: #7fe9c8; font-weight: 800; }
.au-ns-recon-ok { color: #7fe9c8; margin-left: auto; font-size: 10px; }
.au-ns-recon-warn { color: #9fb8b2; line-height: 1.5; }
.au-ns-recon-warn b { color: #7fe9c8; }
.au-ns-attr-note b { color: #aee7d6; font-style: normal; }
.au-ns-dim { color: #6f8a83; }

.au-ns-basisline { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.06em; color: #6f8a83; margin: -2px 0 8px 2px; }
.au-ns-residual { display: flex; align-items: baseline; gap: 8px; font-size: 11px; padding: 3px 2px; margin-bottom: 10px; }
.au-ns-res-label { color: #8aa39d; }
.au-ns-res-v { margin-left: auto; font-weight: 700; }
.au-ns-residual.pos .au-ns-res-v { color: #7fe9c8; }
.au-ns-residual.neg .au-ns-res-v { color: #ffcf6b; }

.au-ns-where-label { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.12em; color: #6f8a83; margin: 4px 0 6px; }
.au-ns-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: rgba(255,255,255,0.04); }
.au-ns-seg { height: 100%; min-width: 3px; }
.seg-native { background: #7fe9c8; }
.seg-foreign { background: #c79a7a; }
.au-ns-legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 7px; }
.au-ns-leg { font-size: 10.5px; color: #9fb8b2; display: inline-flex; align-items: center; gap: 4px; }
.au-ns-leg b { color: #d6ece6; }
.au-ns-leg-kind { color: #6f8a83; font-size: 9px; }
.au-ns-dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.au-ns-attr-note { font-size: 10px; color: #7f9c95; font-style: italic; margin-top: 8px; line-height: 1.45; max-width: 60ch; }
.au-ns-attr-note code { color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 4px; border-radius: 4px; font-style: normal; }
</style>
