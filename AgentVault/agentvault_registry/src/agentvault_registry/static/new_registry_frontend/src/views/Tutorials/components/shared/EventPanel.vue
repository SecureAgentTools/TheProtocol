<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch, nextTick } from 'vue'
import type { EventStoreEvent } from '../../types/tutorial.types'
import { useEventStoreWebSocket } from '../../services/eventStoreWebSocket'
import { liveOld } from '@/services/ledgerNames'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const esws = useEventStoreWebSocket()
const scrollContainer = ref<HTMLElement | null>(null)
const paused = ref(false)
const filterType = ref('all')

const filteredEvents = computed(() => {
  const evts = esws.events.value
  if (filterType.value === 'all') return evts
  return evts.filter(e => e.event_type === filterType.value)
})

const uniqueEventTypes = computed(() => {
  const types = new Set(esws.events.value.map(e => e.event_type))
  return Array.from(types).sort()
})

// Auto-scroll to bottom on new events
watch(() => esws.eventCount.value, async () => {
  if (paused.value || !scrollContainer.value) return
  await nextTick()
  scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
})

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString(appLocale(), { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      + '.' + String(d.getMilliseconds()).padStart(3, '0')
  } catch {
    return ts
  }
}

function truncateDid(did: string): string {
  if (!did || did.length <= 20) return did
  return did.slice(0, 16) + '...' + did.slice(-4)
}

const eventMeta: Record<string, { color: string; icon: string }> = {
  // §FESUITE: names in the console's icon map, not emoji
  AgentCreated: { color: 'text-emerald-400', icon: 'mdi:account-plus' },
  AgentOnboarded: { color: 'text-green-400', icon: 'mdi:check-circle' },
  TokensTransferred: { color: 'text-amber-400', icon: 'mdi:cash-fast' },
  TreasuryFundingGranted: { color: 'text-blue-400', icon: 'mdi:bank' },
  TreasurySlashReceived: { color: 'text-orange-400', icon: 'mdi:bank' },
  DisputeFiled: { color: 'text-rose-400', icon: 'mdi:scale-balance' },
  DisputeResolved: { color: 'text-purple-400', icon: 'mdi:gavel' },
  DisputeSlash: { color: 'text-red-400', icon: 'mdi:alert-octagon' },
  DisputeCompensationRequest: { color: 'text-pink-400', icon: 'mdi:email-fast' },
  DisputeCompensationMinted: { color: 'text-green-400', icon: 'mdi:cash-check' },
  ReputationChanged: { color: 'text-violet-400', icon: 'mdi:star' },
  EvidenceSubmitted: { color: 'text-gray-400', icon: 'mdi:file-document' },
  CrossRegistryTransferCompleted: { color: 'text-cyan-400', icon: 'mdi:earth' },
}

function getMeta(type: string) {
  return eventMeta[liveOld(type)] || { color: 'text-gray-400', icon: 'mdi:radio-tower' }
}
</script>

<template>
  <transition name="slide-panel">
    <div
      v-if="visible"
      class="w-80 shrink-0 border-l border-gray-700/50 bg-gray-950/80 flex flex-col h-full"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-3 py-2.5 border-b border-gray-700/40">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-gray-200"><Icon name="mdi:lightning-bolt" /> Live Events</span>
          <div
            :class="[
              'w-2 h-2 rounded-full',
              esws.connected.value ? 'bg-emerald-400' :
              esws.connectionError.value?.includes('Reconnecting') ? 'bg-amber-400 animate-pulse' :
              'bg-red-400'
            ]"
            :title="esws.connected.value ? 'Connected' : (esws.connectionError.value || 'Disconnected')"
          />
        </div>
        <button @click="emit('close')" class="text-gray-500 hover:text-gray-300 text-xs px-1">✕</button>
      </div>

      <!-- Event list -->
      <div ref="scrollContainer" class="flex-1 overflow-y-auto overflow-x-hidden">
        <div v-if="filteredEvents.length === 0" class="flex items-center justify-center h-32 text-gray-600 text-xs">
          {{ esws.connected.value ? 'Waiting for events...' : 'Not connected' }}
        </div>
        <div
          v-for="(evt, idx) in filteredEvents"
          :key="evt.id + '-' + idx"
          class="px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors"
        >
          <div class="flex items-center justify-between mb-0.5">
            <div class="flex items-center gap-1.5 min-w-0">
              <Icon :name="getMeta(evt.event_type).icon" class="text-xs" aria-hidden="true" />
              <span :class="['text-xs font-semibold truncate', getMeta(evt.event_type).color]">
                {{ evt.event_type }}
              </span>
            </div>
            <span class="text-[9px] text-gray-600 font-mono shrink-0 ml-1">
              {{ formatTime(evt.receivedAt) }}
            </span>
          </div>
          <div class="text-[10px] text-gray-500 font-mono truncate">
            {{ truncateDid(evt.aggregate_id) }}
          </div>
          <details class="mt-1">
            <summary class="text-[9px] text-gray-600 cursor-pointer hover:text-gray-400">data</summary>
            <pre class="text-[9px] text-gray-500 mt-1 overflow-x-auto max-h-24 whitespace-pre-wrap break-all">{{ JSON.stringify(evt.data, null, 1) }}</pre>
          </details>
        </div>
      </div>

      <!-- Footer controls -->
      <div class="px-3 py-2 border-t border-gray-700/40 flex items-center gap-2">
        <select aria-label="Filter events"
          v-model="filterType"
          class="text-[10px] bg-gray-800 text-gray-400 border border-gray-700 rounded-sm px-1.5 py-1 flex-1 min-w-0"
        >
          <option value="all">All Events</option>
          <option v-for="t in uniqueEventTypes" :key="t" :value="t">{{ t }}</option>
        </select>
        <button
          @click="paused = !paused"
          :class="['text-[10px] px-2 py-1 rounded-sm border', paused ? 'border-amber-500/50 text-amber-400' : 'border-gray-700 text-gray-500 hover:text-gray-300']"
          :title="paused ? 'Resume auto-scroll' : 'Pause auto-scroll'"
        >
          {{ paused ? '▶' : '⏸' }}
        </button>
        <button
          @click="esws.clearEvents()"
          class="text-[10px] text-gray-500 hover:text-red-400 px-2 py-1 rounded-sm border border-gray-700"
          title="Clear events"
        >
          ✕
        </button>
      </div>

      <!-- Connection error banner -->
      <div
        v-if="esws.connectionError.value && !esws.connected.value"
        class="px-3 py-1.5 bg-red-900/20 border-t border-red-800/30 text-[10px] text-red-400"
      >
        {{ esws.connectionError.value }}
        <button
          @click="esws.connect()"
          class="ml-2 underline hover:text-red-300"
        >
          Retry
        </button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: all 0.2s ease;
}
.slide-panel-enter-from,
.slide-panel-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
</style>
