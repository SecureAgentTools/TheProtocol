<!--
  AttestationSeal (§GLOBALSTD Phase 3.1, 2026-08-22) — TPSA-1 in-browser verification.

  The verdict band above says the money is conserved; this strip proves the CLAIM
  itself is real: it fetches the latest signed attestation per prod frame and
  verifies — in this browser, against the published JWKS, with WebCrypto —
  that sha256(payload) == digest, that the Ed25519 signature covers those exact
  bytes, and that the chain links (prev_hash == digest of the attestation before).
  Nothing here trusts the page: the same three checks run identically from the
  conformance script with no browser at all.
-->
<template>
  <section v-if="attestModes.includes(mode)" class="au-seal" data-testid="tpsa-seal">
    <span class="au-seal-mark" aria-hidden="true">&#x2721;</span>
    <span class="au-seal-label">TPSA-1</span>
    <span class="au-seal-copy">every verdict above is signed &amp; hash-chained</span>
    <span v-for="r in results" :key="r.frame" class="au-seal-chip" :class="'st-' + r.state" :title="r.detail" :data-seal-frame="r.frame" :data-seal-state="r.state">
      {{ shortName(r.frame) }}
      <b v-if="r.state === 'ok'">&check;</b>
      <b v-else-if="r.state === 'fail'">&cross;</b>
      <b v-else-if="r.state === 'own'" class="au-seal-own">own auditor</b>
      <b v-else>&hellip;</b>
      <span v-if="r.seq" class="au-seal-seq au-mono">seq {{ r.seq.toLocaleString() }}</span>
    </span>
    <button class="au-seal-btn" @click="verifyAll" :disabled="busy">{{ busy ? 'verifying&#8230;' : verified ? 're-verify' : 'verify' }}</button>
    <span v-if="kid" class="au-seal-kid au-mono" :title="'signing key id (JWKS)'">kid {{ kid }}</span>
    <span v-if="unsupported" class="au-seal-unsup">this browser cannot verify Ed25519 &mdash; run the conformance script instead</span>
  </section>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import { useTpsaSeal } from '@/composables/useTpsaSeal'

const store = useAuditorStore()
const { mode, attestModes } = storeToRefs(store)

// The verification itself lives in ONE place (useTpsaSeal); the header badge
// renders the same state, so re-verifying from either updates both.
const { results, busy, verified, kid, unsupported, verifyAll } = useTpsaSeal()

const shortName = (f: string) => f.replace('frame-', '').toUpperCase()

onMounted(() => { void verifyAll() })
// Switching tier changes WHICH chains are on screen, so the proof must be re-run.
// Without this the band keeps the previous tier's chips — the defect this replaced.
watch(mode, () => { void verifyAll() })
</script>

<style scoped>
.au-seal { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin: -6px 0 18px; padding: 6px 12px; border: 1px solid rgba(127,233,200,0.14); border-radius: 10px; background: rgba(20,40,36,0.25); font-size: 11px; color: #8aa39d; }
.au-seal-mark { color: #ffcf6b; }
.au-seal-label { font-family: var(--au-mono, monospace); font-weight: 800; letter-spacing: 0.14em; color: #cfe9e2; font-size: 10.5px; }
.au-seal-copy { color: #6f8a83; }
.au-seal-chip { display: inline-flex; align-items: center; gap: 5px; font-family: var(--au-mono, monospace); font-size: 10px; padding: 2px 8px; border-radius: 99px; border: 1px solid rgba(127,233,200,0.2); }
.au-seal-chip.st-ok { color: #7fe9c8; border-color: rgba(127,233,200,0.4); }
.au-seal-chip.st-fail { color: #f87171; border-color: rgba(248,113,113,0.5); }
.au-seal-chip.st-pending { color: #6f8a83; }
.au-seal-chip.st-own { color: #8b949e; border-color: rgba(139,148,158,0.35); }
.au-seal-own { font-weight: 600; font-size: 9px; letter-spacing: 0.04em; }
.au-seal-seq { color: #6f8a83; font-size: 9px; }
.au-seal-btn { margin-left: auto; font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.08em; color: #9fd8c8; background: rgba(127,233,200,0.08); border: 1px solid rgba(127,233,200,0.3); border-radius: 6px; padding: 3px 10px; cursor: pointer; }
.au-seal-btn:disabled { opacity: 0.6; cursor: wait; }
.au-seal-kid { font-size: 9px; color: #6f8a83; }
.au-seal-unsup { color: #ffcf6b; font-size: 10px; }
</style>
