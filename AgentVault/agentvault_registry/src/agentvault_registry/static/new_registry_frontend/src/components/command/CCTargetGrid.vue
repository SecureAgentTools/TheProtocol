<script setup lang="ts">
import type { TargetSummary } from '@/services/api/types/diagnostics'
import CCTargetTile from './CCTargetTile.vue'

const props = defineProps<{
  targets: TargetSummary[]
  inflightTargets: Set<string>
}>()

defineEmits<{
  (e: 'open', operator_id: string): void
}>()
</script>

<template>
  <div class="cc-grid">
    <CCTargetTile
      v-for="target in targets"
      :key="target.operator_id"
      :target="target"
      :inflight="props.inflightTargets.has(target.operator_id)"
      @open="$emit('open', target.operator_id)"
    />
  </div>
</template>

<style scoped>
.cc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
</style>
