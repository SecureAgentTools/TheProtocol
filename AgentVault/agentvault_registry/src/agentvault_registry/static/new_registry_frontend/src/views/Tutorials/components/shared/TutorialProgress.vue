<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed } from 'vue'
import type { TutorialStep } from '../../types/tutorial.types'

const props = defineProps<{
  steps: TutorialStep[]
  currentStepIndex: number
  completedStepIds: Set<string>
  trackColor?: string
}>()

const emit = defineEmits<{
  (e: 'go-to-step', index: number): void
}>()

const progressPercent = computed(() => {
  if (props.steps.length === 0) return 0
  return Math.round((props.completedStepIds.size / props.steps.length) * 100)
})

function stepStatus(step: TutorialStep, index: number): 'completed' | 'active' | 'locked' | 'available' {
  if (props.completedStepIds.has(step.id)) return 'completed'
  if (index === props.currentStepIndex) return 'active'
  // Check if prerequisite is met
  if (!step.requiresStepId || props.completedStepIds.has(step.requiresStepId)) return 'available'
  return 'locked'
}

const statusStyles: Record<string, string> = {
  completed: 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400',
  active: 'bg-violet-500/20 border-violet-500/50 text-violet-400 ring-2 ring-violet-500/30',
  available: 'bg-gray-700/30 border-gray-600/50 text-gray-400 hover:border-gray-500 cursor-pointer',
  locked: 'bg-gray-800/30 border-gray-700/30 text-gray-600 cursor-not-allowed opacity-50'
}

const connectorStyles: Record<string, string> = {
  completed: 'bg-emerald-500/50',
  active: 'bg-violet-500/30',
  available: 'bg-gray-700/50',
  locked: 'bg-gray-800/30'
}
</script>

<template>
  <div class="space-y-4">
    <!-- Progress Bar -->
    <div class="flex items-center gap-3">
      <div class="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          class="h-full bg-linear-to-r/srgb from-violet-600 to-purple-500 rounded-full transition-all duration-500 ease-out"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>
      <span class="text-xs font-mono text-gray-400 shrink-0">
        {{ completedStepIds.size }}/{{ steps.length }}
      </span>
    </div>

    <!-- Step Pills - Horizontal scrollable -->
    <div class="flex items-center gap-1 overflow-x-auto pb-2 tp-scrollbar">
      <template v-for="(step, index) in steps" :key="step.id">
        <!-- Step Pill -->
        <button
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all whitespace-nowrap shrink-0',
            statusStyles[stepStatus(step, index)]
          ]"
          :disabled="stepStatus(step, index) === 'locked'"
          @click="stepStatus(step, index) !== 'locked' && emit('go-to-step', index)"
          :title="step.title"
        >
          <!-- Step indicator -->
          <span v-if="stepStatus(step, index) === 'completed'" class="text-emerald-400">✓</span>
          <span v-else-if="stepStatus(step, index) === 'active'" class="text-violet-400">●</span>
          <span v-else-if="stepStatus(step, index) === 'locked'" class="text-gray-600"><Icon name="mdi:lock" /></span>
          <span v-else class="text-gray-500">{{ step.stepNumber }}</span>

          <span class="hidden sm:inline">{{ step.title }}</span>
          <span class="sm:hidden">{{ step.stepNumber }}</span>
        </button>

        <!-- Connector -->
        <div
          v-if="index < steps.length - 1"
          :class="['w-4 h-0.5 rounded-full shrink-0', connectorStyles[stepStatus(step, index)]]"
        />
      </template>
    </div>
  </div>
</template>

<style scoped>
.tp-scrollbar::-webkit-scrollbar {
  height: 4px;
}
.tp-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.tp-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(107, 114, 128, 0.3);
  border-radius: 2px;
}
</style>
