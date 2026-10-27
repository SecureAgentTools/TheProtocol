<!--
  Per-User Conservation (I3) — independent witness.

  The headline invariant (I1, Δ=0) sums ALL balances, so it is structurally blind to a
  SINGLE account going negative (one agent at −100 and the treasury at +100 still net
  Δ=0). I3 reads the same materialized_balances snapshot and asserts the per-agent
  floor: every agent's liquid AND locked balance ≥ 0. A breach here means an individual
  account lost funds even while total supply balances — exactly the class the 2026-06
  user-funds audit (F1/F5) uncovered and fixed. Also surfaces the 24h escrow
  lock-anomaly fingerprint (NegativeEscrowLockClamped recurring = the F1 class is back).
-->
<template>
  <section v-if="puFrames.length" class="au-pu">
    <div class="au-pu-head">
      <span class="au-pu-glyph" aria-hidden="true">&#x25C9;</span>
      <span class="au-label">IS ANYONE HOLDING A NEGATIVE BALANCE?</span>
      <InfoDot title="Why per-account, not just the total" testid="info-au-pu-sub">
        Asserts the per-account floor &mdash; <code>liquid &ge; 0</code> and <code>locked &ge; 0</code> for
      <b>every</b> agent &mdash; from the same balance snapshot as the supply invariant. The headline
      &Delta; cannot see an individual account going negative; this can.
      </InfoDot>
      <span class="au-pu-i3">I3 &middot; INDEPENDENT</span>
      <span class="au-pu-spacer"></span>
      <span :class="['au-pu-agg', aggOk ? 'st-ok' : 'st-breach']">
        <span class="au-pu-agg-dot"></span>{{ aggOk ? 'ALL ACCOUNTS WHOLE' : 'ACCOUNT BREACH' }}
      </span>
    </div>

    <div class="au-pu-grid">
      <article v-for="f in puFrames" :key="f.id" :class="['au-pu-card', f.pu.status === 'OK' ? 'st-ok' : 'st-breach']">
        <header class="au-pu-card-head">
          <span class="au-pu-frame">{{ f.name }}</span>
          <span :class="['au-pu-badge', f.pu.status === 'OK' ? 'st-ok' : 'st-breach']">
            {{ f.pu.status === 'OK' ? '✓ OK' : '✕ BREACH' }}
          </span>
        </header>

        <div class="au-pu-body">
          <div class="au-pu-big">
            <span class="au-pu-num">{{ f.pu.negative_agents }}</span>
            <span class="au-pu-num-key">negative account{{ f.pu.negative_agents === 1 ? '' : 's' }}</span>
          </div>
          <div v-if="f.pu.status !== 'OK'" class="au-pu-worst">
            <span v-if="f.pu.worst_staked < 0">worst locked <b class="au-mono">{{ f.pu.worst_staked.toFixed(2) }}</b></span>
            <span v-if="f.pu.worst_liquid < 0">worst liquid <b class="au-mono">{{ f.pu.worst_liquid.toFixed(2) }}</b></span>
            <span v-if="f.pu.negative_total > 0">total short <b class="au-mono">{{ f.pu.negative_total.toFixed(2) }}</b></span>
          </div>
          <div v-else class="au-pu-clean">every account&rsquo;s funds fully present</div>
        </div>

        <footer class="au-pu-foot">
          <span class="au-pu-fp" :class="{ warn: f.pu.escrow_negative_clamps_24h > 0 }"
                title="NegativeEscrowLockClamped events in 24h — recurring means the escrow double-release class is back">
            clamps 24h <b class="au-mono">{{ f.pu.escrow_negative_clamps_24h }}</b>
          </span>
          <span class="au-pu-fp" title="Routine phantom-escrow sweeps in 24h">
            sweeps 24h <b class="au-mono">{{ f.pu.escrow_orphan_releases_24h }}</b>
          </span>
        </footer>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import InfoDot from './InfoDot.vue'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import type { PerUser } from '@/types/auditor'

const store = useAuditorStore()
const { frames, latestByFrame } = storeToRefs(store)

interface PuFrame { id: string; name: string; pu: PerUser }

const puFrames = computed<PuFrame[]>(() =>
  (frames.value || [])
    .map((f) => {
      const pu = latestByFrame.value[f.id]?.extra_data?.per_user
      return pu ? { id: f.id, name: f.name, pu } : null
    })
    .filter((x): x is PuFrame => x !== null),
)

const aggOk = computed(() => puFrames.value.every((f) => f.pu.status === 'OK'))
</script>

<style scoped>
.au-pu { margin: 22px 0; }
.au-pu-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.au-pu-glyph { color: #7fe9c8; font-size: 16px; }
.au-label { font-family: var(--au-mono, ui-monospace, monospace); font-size: 12px; font-weight: 800; letter-spacing: 0.18em; color: #cfe9e2; }
.au-pu-i3 { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; border: 1px solid rgba(127,233,200,0.25); border-radius: 99px; padding: 2px 8px; }
.au-pu-spacer { flex: 1; }
.au-pu-agg { display: inline-flex; align-items: center; gap: 7px; font-family: var(--au-mono, monospace); font-size: 10.5px; font-weight: 800; letter-spacing: 0.1em; padding: 3px 10px; border-radius: 99px; }
.au-pu-agg.st-ok { color: #7fe9c8; background: rgba(127,233,200,0.10); border: 1px solid rgba(127,233,200,0.3); }
.au-pu-agg.st-breach { color: #ff9b8a; background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.35); }
.au-pu-agg-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.au-pu-agg.st-breach .au-pu-agg-dot { animation: puPulse 1.5s ease-in-out infinite; }
.au-pu-sub { font-size: 12px; color: #8aa39d; margin-bottom: 14px; max-width: 72ch; line-height: 1.5; }
.au-pu-sub code { font-family: var(--au-mono, monospace); color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 5px; border-radius: 4px; }
.au-mono { font-family: var(--au-mono, ui-monospace, monospace); }

.au-pu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.au-pu-card { border-radius: 14px; padding: 14px 16px; background: linear-gradient(180deg, rgba(20,40,36,0.40), rgba(12,22,20,0.20)); }
.au-pu-card.st-ok { border: 1px solid rgba(127,233,200,0.18); }
.au-pu-card.st-breach { border: 1px solid rgba(248,113,113,0.40); background: linear-gradient(180deg, rgba(60,22,20,0.45), rgba(22,12,12,0.25)); }
.au-pu-card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.au-pu-frame { font-weight: 800; color: #e6f5f0; font-size: 15px; }
.au-pu-badge { font-family: var(--au-mono, monospace); font-size: 10px; font-weight: 800; letter-spacing: 0.1em; padding: 2px 9px; border-radius: 99px; }
.au-pu-badge.st-ok { color: #7fe9c8; background: rgba(127,233,200,0.10); border: 1px solid rgba(127,233,200,0.3); }
.au-pu-badge.st-breach { color: #ff9b8a; background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.4); animation: puPulse 1.5s ease-in-out infinite; }

.au-pu-body { padding: 4px 0 8px; }
.au-pu-big { display: flex; align-items: baseline; gap: 8px; }
.au-pu-num { font-family: var(--au-mono, monospace); font-size: 30px; font-weight: 800; line-height: 1; }
.st-ok .au-pu-num { color: #7fe9c8; }
.st-breach .au-pu-num { color: #ff9b8a; }
.au-pu-num-key { font-size: 11.5px; color: #8aa39d; }
.au-pu-worst { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 7px; font-size: 11px; color: #d8b3aa; }
.au-pu-worst b { color: #ff9b8a; }
.au-pu-clean { margin-top: 7px; font-size: 11px; color: #6f8a83; }

.au-pu-foot { display: flex; gap: 14px; border-top: 1px dashed rgba(127,233,200,0.15); padding-top: 8px; }
.au-pu-fp { font-size: 10px; color: #6f8a83; }
.au-pu-fp b { color: #9fb8b2; }
.au-pu-fp.warn b { color: #ffcf6b; }

@keyframes puPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
</style>
