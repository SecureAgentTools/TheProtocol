<script setup lang="ts">
/**
 * §COCKPITA R3 (§MINELEDGER) — the live EventStore ledger, scoped to YOUR agents.
 *
 * His ask was for "the same filtered (for owned agents) eventstore live ledger, like the
 * bridge has ... they are really good with inspect already in". So this deliberately adds
 * NO ledger of its own: `BridgeLedger` is the rendering, `BridgePayloadModal` is the
 * inspect, `useLedgerStream` is the socket, and this file only answers the one question
 * the bridge answers differently — WHOSE agents.
 *
 * 🔴 ONE BUS. The desk's C1 law is a single WS subscription for the whole page, and
 * `useLedgerStream` is a singleton, so mounting this pane opens NO new socket. A pane that
 * quietly opened a second one would still look correct on screen.
 *
 * 🔴 `mine` MUST ACTUALLY MEAN MINE. §BRIDGE found this exact predicate reading TRUE for
 * 200 of 4,098 agents because it was fed by a capped, hydrated list — and the 200 it had
 * were the newest forge fixtures rather than the agents moving money. The DID set here
 * comes from `/developers/me/agent-dids`, the identity-only endpoint written for that bug,
 * whose own docstring is sized for "the whole fleet of 4,093 ... one request". On
 * registry-a this account owns 4,130 agents, which is precisely the population that broke
 * it before.
 *
 * 🔴 AN EMPTY LEDGER IS TWO DIFFERENT FACTS. "None of your agents did anything" and "we do
 * not yet know which agents are yours" render identically and mean opposite things, so the
 * scope note is passed down until the DID set is genuinely known. Quiet is a finding; not
 * knowing is not.
 */
import { onMounted } from 'vue'
import PaneShell from './PaneShell.vue'
import { PANES } from './paneRegistry'
import BridgeLedger from '@/components/bridge/BridgeLedger.vue'
import { useMineDids } from '@/composables/useMineDids'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const def = PANES.ledger

// §MCFOLD — WHOSE agents is answered once, in `useMineDids`, for this pane AND the
// dashboard's ledger strip. BridgeLedger owns the stream join.
const { mineDids, scopeNote, scopeState, load } = useMineDids()
onMounted(load)
</script>

<template>
  <!-- §COCKPITFRAME F1 — ON THE SHELL. HIS REPORT: *"live ledger … ha[s] no background."*
       Measured: this pane's root computed to `rgba(0,0,0,0)` while every shell pane read
       `rgb(19,24,37)`. The frame was never drawn because nothing drew it — and the comment
       below the template asserted the opposite as though it were true.
       ⚠ `inner-scroll`: BridgeLedger owns its own scroll, so the shell body must not add a
       second one. That is the two-scrollbar trap this file already warned about. -->
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds" inner-scroll>
    <div class="pledger" data-testid="pledger-root" data-tour="cockpit-ledger"
         :data-mine-count="mineDids.length" :data-scope-state="scopeState">
      <!-- canOpenForensics stays FALSE: the admin forensics door belongs to the bridge, and a
           dead-end button is worse than no button (§DISCREFINE). -->
      <BridgeLedger :mine-dids="mineDids" :scope-note="scopeNote" :can-open-forensics="false" />
    </div>
  </PaneShell>
</template>

<style scoped>
.pledger { display: flex; flex-direction: column; min-height: 0; flex: 1; }
/* The pane shell owns the frame (it really does, since §COCKPITFRAME F1); the ledger owns
   its own scroll. Giving this wrapper a height of its own is how a nested scroller ends up
   with two scrollbars. */
/* ⚠ `.blg` is itself a flex column whose FEED is `flex:1; overflow-y:auto` — so it only
   scrolls if something bounds its height. Inside the shell's `inner-scroll` body (which is
   `overflow: hidden`) an unbounded `.blg` would grow past the tile and be CLIPPED, which is
   the one outcome §COCKPITFIT forbids: content you cannot see is worse than a void you can.
   These two declarations are what make the ledger's own scrollbar the only one. */
.pledger :deep(.blg) { border: 0; background: transparent; padding: 0;
                       flex: 1 1 auto; min-height: 0; }
</style>
