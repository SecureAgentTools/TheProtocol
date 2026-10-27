<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { onMounted, onUnmounted, watch, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTutorialRunnerStore } from './stores/tutorialRunnerStore'
import { getTrackById, allTracks } from './data/trackDefinitions'
import { useEventStoreWebSocket, destroyEventStoreWebSocket } from './services/eventStoreWebSocket'
import TutorialProgress from './components/shared/TutorialProgress.vue'
import StepExplainer from './components/shared/StepExplainer.vue'
import ApiCallCard from './components/shared/ApiCallCard.vue'
import EntityInspector from './components/shared/EntityInspector.vue'
import EventPanel from './components/shared/EventPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useTutorialRunnerStore()
const esws = useEventStoreWebSocket()

const trackId = computed(() => route.params.trackId as string)
const currentStep = computed(() => store.currentStep)
const stepResult = computed(() =>
  currentStep.value ? store.stepResults[currentStep.value.id] : undefined
)

// Event panel state
const eventPanelOpen = ref(false)
const PANEL_KEY = 'theprotocol_event_panel_open'
try {
  eventPanelOpen.value = localStorage.getItem(PANEL_KEY) === 'true'
} catch { /* ignore */ }

function toggleEventPanel() {
  eventPanelOpen.value = !eventPanelOpen.value
  try { localStorage.setItem(PANEL_KEY, String(eventPanelOpen.value)) } catch { /* ignore */ }
}

// Celebration state
const showCelebration = ref(false)
let celebrationTimer: ReturnType<typeof setTimeout> | null = null

// Watch for track completion
watch(() => store.isTrackComplete, (complete) => {
  if (complete) {
    showCelebration.value = true
    celebrationTimer = setTimeout(() => { showCelebration.value = false }, 5000)
  }
})

// Next track suggestion
const nextTrack = computed(() => {
  if (!store.activeTrack) return null
  const progress = store.loadAllProgress()
  return allTracks.find(t => {
    if (t.id === store.activeTrack?.id) return false
    const p = progress[t.id]
    if (p && p.completedStepIds.length === t.steps.length) return false
    // Check prerequisites satisfied
    if (t.prerequisites) {
      return t.prerequisites.every(pre => {
        const pp = progress[pre]
        const preTrack = allTracks.find(at => at.id === pre)
        return pp && preTrack && pp.completedStepIds.length === preTrack.steps.length
      })
    }
    return true
  })
})

// All captured values accumulated so far
const allCapturedKeys = computed(() => {
  if (!store.activeTrack) return []
  const keys: Array<{ key: string; label: string; value: any }> = []
  for (const step of store.activeTrack.steps) {
    if (step.captures) {
      for (const cap of step.captures) {
        if (store.capturedValues[cap.key] !== undefined) {
          keys.push({
            key: cap.key,
            label: cap.displayLabel,
            value: store.capturedValues[cap.key]
          })
        }
      }
    }
  }
  return keys
})

// Load track on mount + connect WS
onMounted(() => {
  loadTrack()
  store.checkSandbox()
  esws.connect()
})

onUnmounted(() => {
  if (celebrationTimer) clearTimeout(celebrationTimer)
  destroyEventStoreWebSocket()
})

watch(trackId, () => {
  loadTrack()
})

function loadTrack() {
  const track = getTrackById(trackId.value)
  if (!track) {
    router.push({ name: 'tutorials' })
    return
  }
  store.loadTrack(track)
}

async function executeStep() {
  await store.executeCurrentStep()
}

function handleGoToStep(index: number) {
  store.goToStep(index)
}

function handleReset() {
  if (confirm('Reset all progress for this tutorial? Captured values will be lost.')) {
    store.resetTrack()
    showCelebration.value = false
  }
}
</script>

<template>
  <div class="flex h-[calc(100vh-64px)] overflow-hidden">
    <!-- Main content area -->
    <div class="flex-1 overflow-y-auto">
      <div class="max-w-5xl mx-auto px-4 py-6 space-y-6">

        <!-- Celebration banner -->
        <transition name="celebration">
          <div
            v-if="showCelebration && store.activeTrack"
            class="relative rounded-xl overflow-hidden"
          >
            <div :class="['p-5 text-center bg-linear-to-r/srgb', store.activeTrack.gradientFrom, store.activeTrack.gradientTo]">
              <div class="text-3xl mb-2"><Icon name="mdi:creation" /></div>
              <div class="text-white font-bold text-xl mb-1">
                {{ store.activeTrack.completionTitle || 'Track Complete!' }}
              </div>
              <p class="text-white/80 text-sm">
                All {{ store.totalSteps }} steps completed. You've mastered {{ store.activeTrack.title }}.
              </p>
              <div class="flex items-center justify-center gap-4 mt-4">
                <button
                  @click="router.push({ name: 'tutorials' })"
                  class="px-4 py-2 rounded-lg text-sm font-medium bg-white/20 hover:bg-white/30 text-white transition-colors"
                >
                  ← Back to Hub
                </button>
                <button
                  v-if="nextTrack"
                  @click="router.push({ name: 'tutorial-runner', params: { trackId: nextTrack.id } })"
                  class="px-4 py-2 rounded-lg text-sm font-semibold bg-white text-gray-900 hover:bg-gray-100 transition-colors"
                >
                  Next: {{ nextTrack.title }} →
                </button>
              </div>
            </div>
          </div>
        </transition>

        <!-- Header -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-4">
            <button
              @click="router.push({ name: 'tutorials' })"
              class="text-gray-400 hover:text-white transition-colors text-sm flex items-center gap-1"
            >
              ← Back to Tutorials
            </button>
            <div v-if="store.activeTrack">
              <h1 class="text-xl font-bold text-white">{{ store.activeTrack.title }}</h1>
              <p class="text-gray-400 text-sm">{{ store.activeTrack.subtitle }}</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <!-- Event panel toggle -->
            <button
              @click="toggleEventPanel"
              :class="[
                'flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition-colors',
                eventPanelOpen
                  ? 'border-violet-500/50 text-violet-300 bg-violet-500/10'
                  : 'border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600'
              ]"
            >
              <span><Icon name="mdi:lightning-bolt" /></span>
              <span class="hidden sm:inline">Events</span>
              <span
                v-if="esws.eventCount.value > 0"
                class="ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-violet-500/20 text-violet-300"
              >
                {{ esws.eventCount.value > 99 ? '99+' : esws.eventCount.value }}
              </span>
              <div
                :class="[
                  'w-1.5 h-1.5 rounded-full ml-0.5',
                  esws.connected.value ? 'bg-emerald-400' : 'bg-red-400'
                ]"
              />
            </button>

            <!-- Sandbox health indicator -->
            <div class="flex items-center gap-1.5 text-xs">
              <div
                :class="[
                  'w-2 h-2 rounded-full',
                  store.sandboxHealthy === true ? 'bg-emerald-400' :
                  store.sandboxHealthy === false ? 'bg-red-400' : 'bg-gray-500'
                ]"
              />
              <span :class="store.sandboxHealthy ? 'text-gray-400' : 'text-red-400'" class="hidden sm:inline">
                {{ store.sandboxHealthy === true ? 'Sandbox Online' :
                   store.sandboxHealthy === false ? 'Sandbox Offline' : 'Checking...' }}
              </span>
            </div>
            <button
              @click="handleReset"
              class="text-xs text-gray-500 hover:text-red-400 transition-colors px-2 py-1 rounded-sm hover:bg-gray-800"
            >
              Reset
            </button>
          </div>
        </div>

        <!-- Progress -->
        <TutorialProgress
          v-if="store.activeTrack"
          :steps="store.activeTrack.steps"
          :current-step-index="store.currentStepIndex"
          :completed-step-ids="store.completedStepIds"
          :track-color="store.activeTrack.color"
          @go-to-step="handleGoToStep"
        />

        <!-- Current Step Content -->
        <div v-if="currentStep" class="space-y-4">
          <!-- Step Explainer -->
          <StepExplainer
            :title="currentStep.title"
            :subtitle="currentStep.subtitle"
            :explanation="currentStep.explanation"
            :step-number="currentStep.stepNumber"
            :is-complete="store.completedStepIds.has(currentStep.id)"
            :is-active="true"
            :notes="currentStep.notes"
          />

          <!-- API Call Card -->
          <ApiCallCard
            :step="currentStep"
            :result="stepResult"
            :captured-values="store.capturedValues"
            :is-executing="store.isExecuting"
            :can-execute="store.canExecuteCurrentStep"
            :track-color="store.activeTrack?.color"
            @execute="executeStep"
          />

          <!-- Navigation -->
          <div class="flex items-center justify-between pt-4">
            <button
              @click="store.previousStep()"
              :disabled="store.currentStepIndex === 0"
              :class="[
                'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                store.currentStepIndex > 0
                  ? 'text-gray-300 hover:text-white hover:bg-gray-800'
                  : 'text-gray-600 cursor-not-allowed'
              ]"
            >
              ← Previous
            </button>

            <button
              v-if="!store.isTrackComplete"
              @click="store.nextStep()"
              :disabled="!store.canAdvance"
              :class="[
                'px-5 py-2 rounded-lg text-sm font-semibold transition-all',
                store.canAdvance
                  ? 'bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/20'
                  : 'bg-gray-700/50 text-gray-500 cursor-not-allowed'
              ]"
            >
              Next Step →
            </button>

            <div v-else class="text-center">
              <div class="text-emerald-400 font-bold text-lg mb-1"><Icon name="mdi:creation" /> Track Complete!</div>
              <p class="text-gray-400 text-sm">All {{ store.totalSteps }} steps completed.</p>
              <div class="flex items-center gap-3 mt-3">
                <button
                  @click="router.push({ name: 'tutorials' })"
                  class="px-4 py-2 rounded-lg text-sm text-violet-400 hover:text-white hover:bg-violet-600/20 transition-colors"
                >
                  Back to Hub
                </button>
                <button
                  v-if="nextTrack"
                  @click="router.push({ name: 'tutorial-runner', params: { trackId: nextTrack.id } })"
                  class="px-4 py-2 rounded-lg text-sm font-semibold bg-violet-600 hover:bg-violet-500 text-white transition-colors"
                >
                  {{ nextTrack.title }} →
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- All Captured Values (collapsible) -->
        <details v-if="allCapturedKeys.length > 1" class="rounded-lg border border-gray-700/50 bg-gray-900/30">
          <summary class="px-4 py-3 cursor-pointer text-gray-400 text-xs font-semibold uppercase tracking-wider hover:text-gray-300">
            All Captured Values ({{ allCapturedKeys.length }})
          </summary>
          <div class="px-4 pb-4 space-y-1.5">
            <div
              v-for="item in allCapturedKeys"
              :key="item.key"
              class="flex items-center gap-2 text-xs"
            >
              <span class="text-gray-500 min-w-[120px]">{{ item.label }}:</span>
              <code class="text-emerald-300 font-mono truncate">{{ item.value }}</code>
            </div>
          </div>
        </details>
      </div>
    </div>

    <!-- Event Panel Sidebar -->
    <EventPanel
      :visible="eventPanelOpen"
      @close="toggleEventPanel"
    />
  </div>
</template>

<style scoped>
.celebration-enter-active {
  transition: all 0.4s ease-out;
}
.celebration-leave-active {
  transition: all 0.3s ease-in;
}
.celebration-enter-from {
  transform: translateY(-20px);
  opacity: 0;
}
.celebration-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
</style>
