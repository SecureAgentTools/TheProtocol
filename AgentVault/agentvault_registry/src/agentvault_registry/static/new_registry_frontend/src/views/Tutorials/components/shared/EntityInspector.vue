<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed } from 'vue'
import type { CaptureRule } from '../../types/tutorial.types'

const props = defineProps<{
  captures: CaptureRule[]
  capturedValues: Record<string, any>
  justCaptured?: Record<string, any>  // Values captured in THIS step (for highlight)
}>()

const displayItems = computed(() => {
  return props.captures
    .filter(rule => props.capturedValues[rule.key] !== undefined)
    .map(rule => ({
      key: rule.key,
      label: rule.displayLabel,
      value: props.capturedValues[rule.key],
      sensitive: rule.sensitive || false,
      isNew: props.justCaptured ? props.justCaptured[rule.key] !== undefined : false
    }))
})

function formatValue(value: any, sensitive: boolean): string {
  const str = String(value)
  if (sensitive && str.length > 20) {
    return str.substring(0, 8) + '•'.repeat(8) + str.substring(str.length - 6)
  }
  if (str.length > 80) {
    return str.substring(0, 40) + '...' + str.substring(str.length - 20)
  }
  return str
}

function copyValue(value: any) {
  navigator.clipboard?.writeText(String(value))
}
</script>

<template>
  <div v-if="displayItems.length > 0" class="rounded-lg border border-gray-700/50 bg-gray-800/30 overflow-hidden">
    <div class="px-4 py-2.5 border-b border-gray-700/50 flex items-center gap-2">
      <span class="text-violet-400 text-sm"><Icon name="mdi:package" /></span>
      <span class="text-gray-300 text-xs font-semibold uppercase tracking-wider">Captured Values</span>
    </div>
    <div class="divide-y divide-gray-700/30">
      <div
        v-for="item in displayItems"
        :key="item.key"
        :class="[
          'px-4 py-2.5 flex items-center gap-3 group transition-colors',
          item.isNew ? 'bg-violet-500/10 animate-pulse-once' : ''
        ]"
      >
        <!-- Label -->
        <span class="text-gray-400 text-xs font-medium min-w-[100px] shrink-0">
          {{ item.label }}
        </span>
        <!-- Value -->
        <code class="text-xs font-mono text-emerald-300 bg-gray-900/50 px-2 py-1 rounded-sm flex-1 truncate">
          {{ formatValue(item.value, item.sensitive) }}
        </code>
        <!-- Copy button -->
        <button
          @click="copyValue(item.value)"
          class="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 touch:opacity-100 transition-opacity text-gray-500 hover:text-gray-300 text-xs px-1.5 py-0.5 rounded-sm hover:bg-gray-700/50"
          title="Copy value"
        >
          <Icon name="mdi:clipboard" />
        </button>
        <!-- New badge -->
        <span
          v-if="item.isNew"
          class="text-[10px] font-bold uppercase tracking-wider text-violet-400 bg-violet-500/20 px-1.5 py-0.5 rounded-sm"
        >
          new
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse-once {
  0% { background-color: rgba(139, 92, 246, 0.15); }
  50% { background-color: rgba(139, 92, 246, 0.25); }
  100% { background-color: rgba(139, 92, 246, 0.1); }
}
.animate-pulse-once {
  animation: pulse-once 1s ease-in-out;
}
</style>
