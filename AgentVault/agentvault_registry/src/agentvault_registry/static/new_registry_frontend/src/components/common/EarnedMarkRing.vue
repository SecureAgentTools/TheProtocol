<!--
  EarnedMarkRing — §AGENTDISC #190 (2026-08-16), reworked by §MARKCOLLAR.

  Mount point for a ledger-earned mark on a BARE avatar (one with no cosmetic
  encirclement): Discovery cards, the agent modal hero. Avatars that DO wear an
  encirclement get the identical mark from inside FlareEncirclement instead.

  This component owns no visual of its own any more. It positions the slotted
  avatar and lays EarnedMarkCollar over it. The mark is drawn in exactly one
  place (EarnedMarkCollar) so the two mount points cannot drift apart.

  With zero verified jobs it renders the bare slot: no chrome, no mark. Zero is
  the honest answer for most agents and it should look like zero, not like a
  lesser badge.
-->
<template>
  <span v-if="hasMark" class="emr" :data-testid="`earned-ring-${marks.tier}`">
    <slot />
    <EarnedMarkCollar :tr="tr" :size="size" />
  </span>
  <slot v-else />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import EarnedMarkCollar from '@/components/common/EarnedMarkCollar.vue'
import { earnedMarks, type TrackRecordCompact } from '@/services/api/trackRecord'

const props = withDefaults(defineProps<{
  tr: TrackRecordCompact | null | undefined
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
}>(), { size: 'md' })

const marks = computed(() => earnedMarks(props.tr))
const hasMark = computed(() => !!marks.value.tier)
</script>

<style scoped>
/* Establishes the positioning context the collar absolutely fills. Sized by the
   slotted avatar, so this works at every avatar size without being told one. */
.emr { position: relative; display: inline-flex; flex: none; }
</style>
