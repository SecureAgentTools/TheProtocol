<!--
  TpsaBadge (2026-08-22, Commander's ask) — the TPSA-1 Ed25519 seal as a compact
  button-style badge in the dashboard HEADER. Same state as the seal strip below
  the verdict band (one verification, two views): green check = every prod frame's
  newest audit attestation verified in THIS browser (digest + Ed25519 + chain link).
  Click = re-verify and bring the full seal strip into view.
-->
<template>
  <button
    v-if="attestModes.includes(mode)"
    type="button"
    class="au-tpsa-badge"
    :class="'bst-' + summary"
    data-testid="tpsa-badge"
    :title="tooltip"
    :aria-label="'TPSA-1 attestation seal: ' + summary + '. Click to re-verify.'"
    @click="onClick"
  >
    <span class="au-tpsa-badge-mark" aria-hidden="true">&#x2721;</span>
    <span class="au-tpsa-badge-label">TPSA-1</span>
    <b v-if="summary === 'ok'" class="au-tpsa-badge-state">&check;</b>
    <b v-else-if="summary === 'fail'" class="au-tpsa-badge-state">&cross;</b>
    <b v-else-if="summary === 'unsupported'" class="au-tpsa-badge-state">!</b>
    <b v-else class="au-tpsa-badge-state au-tpsa-badge-spin">&hellip;</b>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import { useTpsaSeal } from '@/composables/useTpsaSeal'

const store = useAuditorStore()
const { mode, attestModes } = storeToRefs(store)
const { results, summary, lastVerifiedAt, verifyAll } = useTpsaSeal()

const tooltip = computed(() => {
  if (summary.value === 'unsupported') return 'This browser cannot verify Ed25519 — run the conformance script instead.'
  if (summary.value === 'busy') return 'Verifying signatures, digests and chain links in this browser…'
  if (summary.value === 'pending') return 'TPSA-1 seal not yet verified — click to verify in this browser.'
  const frames = results.value.map(r => `${r.frame.replace('frame-', '').toUpperCase()} ${r.state === 'ok' ? 'verified' : r.state === 'own' ? 'attested by its own auditor' : 'FAILED'}`).join(' · ')
  const when = lastVerifiedAt.value ? ` at ${lastVerifiedAt.value}` : ''
  return summary.value === 'ok'
    ? `Every verdict on this page is Ed25519-signed and hash-chained — verified in this browser${when}. ${frames}. Click to re-verify.`
    : `Seal verification FAILED${when}: ${frames}. Click to re-verify.`
})

async function onClick() {
  // Bring the full strip (per-frame chips + detail) into view, then re-run
  // the same verification both controls share.
  document.querySelector('[data-testid="tpsa-seal"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  await verifyAll()
}
</script>

<style scoped>
.au-tpsa-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--au-mono, monospace); font-size: 10px; font-weight: 800; letter-spacing: 0.1em;
  color: #9fd8c8; background: rgba(127,233,200,0.08);
  border: 1px solid rgba(127,233,200,0.3); border-radius: 99px;
  padding: 3px 11px; cursor: pointer; transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.au-tpsa-badge:hover { background: rgba(127,233,200,0.15); }
.au-tpsa-badge-mark { color: #ffcf6b; font-size: 11px; }
.au-tpsa-badge-label { color: #cfe9e2; }
.au-tpsa-badge-state { font-size: 11px; }
.au-tpsa-badge.bst-ok { color: #7fe9c8; border-color: rgba(127,233,200,0.5); }
.au-tpsa-badge.bst-ok .au-tpsa-badge-state { color: #7fe9c8; }
.au-tpsa-badge.bst-fail { color: #f87171; border-color: rgba(248,113,113,0.6); background: rgba(248,113,113,0.08); }
.au-tpsa-badge.bst-fail .au-tpsa-badge-state { color: #f87171; }
.au-tpsa-badge.bst-unsupported { color: #ffcf6b; border-color: rgba(255,207,107,0.5); }
.au-tpsa-badge.bst-busy .au-tpsa-badge-state, .au-tpsa-badge.bst-pending .au-tpsa-badge-state { color: #6f8a83; }
</style>
