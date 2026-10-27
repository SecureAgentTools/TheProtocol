<script setup lang="ts">
/**
 * §COCKPIT P5 — DECISIONS. Chrome only; the decision itself lives in `DecisionQueue`.
 *
 * P1 built this pane read-only, with its own fetch, its own ack, its own line
 * rendering and its own unit rule — all of which Pocket's Approvals view ALSO had, in
 * its own shape. Two implementations of "what a decision looks like and what answering
 * it does" is the §ORGLEAK class in a costume, and it had already begun to bite: only
 * one of the two acked, hashed what it showed, or knew the posture, so what a receipt
 * meant depended on which screen the human happened to be at.
 *
 * So this file is now a shell and a mount. Every state a decision can be in — loading,
 * unreachable, nothing waiting, one answerable and N inert behind it — is rendered by
 * the queue, in one place, for both surfaces. PaneShell keeps what it is for: the
 * title, the freshness chip, and R2's honest "not available on this registry" tile.
 */
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import DecisionQueue from './DecisionQueue.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t } = useI18n()
const def = PANES.decisions
</script>

<template>
  <PaneShell
    :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
    :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds" :wide="def.wide"
    :loading="false" :error="''" :empty="false"
  >
    <!-- The queue owns loading / error / empty: one implementation of those states,
         so the desk and the phone cannot describe the same situation differently. -->
    <DecisionQueue variant="desk" :poll-seconds="def.pollSeconds ?? 20" />
    <p class="ckd-dq-foot">
      <RecordLink kind="consent" :label="t('cockpit.door.consent', 'Full evidence chain')" />
    </p>
  </PaneShell>
</template>

<style scoped>
.ckd-dq-foot { margin: .3rem 0 0; font-size: .62rem; }
</style>
