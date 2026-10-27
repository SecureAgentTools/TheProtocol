<script setup lang="ts">
import { computed } from 'vue'
import type { TutorialTrack, SavedTrackProgress } from '../../types/tutorial.types'
import Icon from '@/components/Icon.vue'
import { trackIcon } from '../../trackIcons'

const props = defineProps<{
  track: TutorialTrack
  savedProgress?: SavedTrackProgress | null
  payoutAvt?: number
  isPaidOut?: boolean
  /** When true the card is shown disabled/greyed and can't be launched. */
  locked?: boolean
  /** Tooltip + inline label for the locked state, e.g. "Requires admin_enforcement". */
  lockedLabel?: string
}>()

const emit = defineEmits<{
  (e: 'select', trackId: string): void
}>()

const completedCount = computed(() =>
  props.savedProgress?.completedStepIds.length ?? 0
)

const totalSteps = computed(() => props.track.steps.length)

const progressPercent = computed(() =>
  totalSteps.value > 0
    ? Math.round((completedCount.value / totalSteps.value) * 100)
    : 0
)

const isStarted = computed(() => completedCount.value > 0)
const isComplete = computed(() => completedCount.value === totalSteps.value)

const completionTime = computed(() => {
  if (!isComplete.value || !props.savedProgress) return null
  const first = props.savedProgress.firstStepAt
  const last = props.savedProgress.completedAt
  if (!first || !last) return null
  const ms = new Date(last).getTime() - new Date(first).getTime()
  if (ms <= 0) return null
  const totalSec = Math.round(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return min > 0 ? `${min}m ${sec}s` : `${sec}s`
})

</script>

<template>
  <button
    @click="!locked && emit('select', track.id)"
    :disabled="locked"
    :aria-disabled="locked || undefined"
    :title="locked ? (lockedLabel || 'Requires admin access') : undefined"
    class="group relative w-full text-left rounded-xl border border-gray-700/50 bg-gray-900/50 overflow-hidden transition-all flex flex-col"
    :class="locked
      ? 'track-card--locked cursor-not-allowed'
      : 'hover:border-gray-600 hover:shadow-xl hover:shadow-black/20 hover:-translate-y-0.5'"
  >
    <!-- Lock badge (admin/flag-gated track) -->
    <div
      v-if="locked"
      class="absolute top-3 right-3 z-10"
    >
      <div class="w-9 h-9 rounded-full flex items-center justify-center bg-gray-800/90 border border-gray-600 text-gray-300">
        <Icon name="mdi:lock" />
      </div>
    </div>

    <!-- Completion badge -->
    <div
      v-if="!locked && isComplete"
      class="absolute top-3 right-3 z-10"
    >
      <div
        :class="['w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold bg-linear-to-br/srgb shadow-lg badge-pulse', track.gradientFrom, track.gradientTo]"
      >
        <span class="text-white drop-shadow-sm">✓</span>
      </div>
    </div>

    <!-- Gradient accent top — fixed to top, no margin -->
    <div
      :class="['h-1.5 w-full bg-linear-to-r/srgb shrink-0', track.gradientFrom, track.gradientTo]"
    />

    <!-- Card body — flex-grow so description fills space -->
    <div class="p-5 flex flex-col flex-1">
      <!-- Icon + Title Row -->
      <div class="flex items-start gap-3 mb-2">
        <Icon :name="trackIcon(track.icon)" class="text-2xl leading-none" aria-hidden="true" />
        <div class="flex-1 min-w-0">
          <h3 class="text-white font-bold text-base group-hover:text-violet-300 transition-colors leading-tight">
            {{ track.title }}
          </h3>
          <p class="text-gray-400 text-xs mt-0.5">{{ track.subtitle }}</p>
        </div>
      </div>

      <!-- Description — flex-grow to push bottom content down -->
      <p class="text-gray-400 text-sm leading-relaxed mb-3 flex-1">
        {{ track.description }}
      </p>

      <!-- Grant badge (where the registry's achievement catalog holds an amount) -->
      <div v-if="payoutAvt && payoutAvt > 0" class="flex items-center gap-2 mb-3 px-2.5 py-1.5 rounded-lg bg-amber-500/5 border border-amber-500/15">
        <span class="text-amber-400 text-xs font-bold">{{ payoutAvt }} units</span>
        <span class="text-amber-400/50 text-[10px]">grant</span>
        <span v-if="isPaidOut" class="ml-auto text-emerald-400 text-[10px] font-semibold">✓ Received</span>
        <span v-else-if="isComplete" class="ml-auto text-amber-300/60 text-[10px]">Grant pending</span>
      </div>

      <!-- Meta Row — always at bottom of card body -->
      <div class="flex items-center justify-between mt-auto">
        <div class="flex items-center gap-3 text-xs text-gray-500">
          <span>{{ track.steps.length }} steps</span>
          <span>·</span>
          <span>~{{ track.estimatedMinutes }} min</span>
        </div>

        <!-- Progress or Status -->
        <span v-if="locked" class="inline-flex items-center gap-1 text-xs text-gray-400">
          <Icon name="mdi:lock" />
          {{ lockedLabel || 'Requires admin access' }}
        </span>
        <div v-else-if="isComplete" class="flex flex-col items-end gap-0.5">
          <div class="flex items-center gap-1.5 text-xs text-emerald-400 font-semibold">
            <span>✓</span>
            <span>{{ track.completionTitle || 'Complete' }}</span>
          </div>
          <span v-if="completionTime" class="text-[10px] text-gray-500">{{ completionTime }}</span>
        </div>
        <div v-else-if="isStarted" class="flex items-center gap-2">
          <div class="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
            <div
              class="h-full bg-violet-500 rounded-full transition-all"
              :style="{ width: `${progressPercent}%` }"
            />
          </div>
          <span class="text-xs text-gray-400 font-mono">{{ completedCount }}/{{ totalSteps }}</span>
        </div>
        <span v-else class="text-xs text-gray-600">Not started</span>
      </div>
    </div>

    <!-- Prerequisites badge — always at very bottom -->
    <div
      v-if="track.prerequisites && track.prerequisites.length > 0"
      class="px-5 py-2 border-t border-gray-700/30 bg-amber-500/5 shrink-0"
    >
      <span class="text-xs text-amber-400/80">
        Requires: {{ track.prerequisites.join(', ') }}
      </span>
    </div>
  </button>
</template>

<style scoped>
@keyframes badge-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(139, 92, 246, 0); }
}
.badge-pulse {
  animation: badge-glow 2s ease-in-out 1;
}
/* Access-control LOCK — dimmed, non-interactive admin/flag-gated card. */
.track-card--locked {
  opacity: 0.55;
}
</style>
