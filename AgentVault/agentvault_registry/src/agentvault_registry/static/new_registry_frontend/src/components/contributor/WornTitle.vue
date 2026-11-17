<!--
  WornTitle — the title under a person's name (V0665; the Commander's feedback on the Track tab, room seq 4404: "set my commander title for me").
  The chosen title is drawn as its emblem; with none chosen, the commander flare tier wears the COMMANDER plate (a rule of the code: nothing is stored, so taking a
  title off returns to it); anyone else with no title shows nothing. The caller's class and test id land on whichever is drawn.
-->
<template>
  <CommanderPlate v-if="worn === 'commander'" :size="size" />
  <TitleEmblem v-else-if="worn" :title-key="worn" :size="size" :variant="titleVariant(worn)" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import CommanderPlate from '@/components/contributor/CommanderPlate.vue'
import TitleEmblem from '@/components/contributor/TitleEmblem.vue'
import { titleVariant, wornTitleOf } from '@/services/contributorTrackView'

const props = defineProps<{ title?: string | null; flareTier?: string | null; size: 'sidebar' | 'card' | 'large' }>()
const worn = computed(() => wornTitleOf(props.title, props.flareTier))
</script>
