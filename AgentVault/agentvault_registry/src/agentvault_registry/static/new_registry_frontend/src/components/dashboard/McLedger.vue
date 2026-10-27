<!--
  McLedger.vue — §MCFOLD (2026-09-02) — the live ledger on Mission Control.

  NOT a ledger of its own. `BridgeLedger` renders (14 rows, a 300-row ring, one flush per
  400 ms, per-frame chips, MINE/ALL scope), `useLedgerStream` is the ONE set of sockets for
  the whole page, `useMineDids` answers whose. Mission Control used to open three raw
  sockets itself and re-render the whole view on every event (the shape the stream
  composable's own header names as what it replaced); this host costs one child render
  boundary and nothing per event.
-->
<template>
  <div class="mcl" data-testid="mc-ledger" :data-strip="props.strip" :data-scope-state="scopeState" :data-mine-count="mineDids.length">
    <BridgeLedger :mine-dids="mineDids" :scope-note="scopeNote" :can-open-forensics="false" :mine-available="!props.public" :strip="props.strip" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import BridgeLedger from '@/components/bridge/BridgeLedger.vue'
import { useMineDids } from '@/composables/useMineDids'
/** §LPSTRIPS — `public`: a visitor with no account. No DID read (it would 401 and print a note about
 *  "your agents"), ALL scope only. */
const props = withDefaults(defineProps<{ public?: boolean; strip?: 'main' | 'sandbox' }>(), { public: false, strip: 'main' })
const { mineDids, scopeNote, scopeState, load } = useMineDids()
if (props.public) { scopeNote.value = null; scopeState.value = 'none' }
onMounted(() => { if (!props.public) void load() })
</script>

<style scoped>
/* The strip bounds the height so the ledger's OWN feed scrolls (an unbounded `.blg` grows
   past the strip and clips — §COCKPITFIT's forbidden outcome). */
.mcl { display: flex; flex-direction: column; height: 26rem; min-height: 0; }
.mcl :deep(.blg) { border: 0; background: transparent; padding: 0; flex: 1 1 auto; min-height: 0; }
</style>
