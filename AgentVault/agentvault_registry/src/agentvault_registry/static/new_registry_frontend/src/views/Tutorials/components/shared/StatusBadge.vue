<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  statusCode: number
  timeMs?: number
}>()

const statusClass = computed(() => {
  if (props.statusCode >= 200 && props.statusCode < 300) return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
  if (props.statusCode >= 300 && props.statusCode < 400) return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
  if (props.statusCode >= 400 && props.statusCode < 500) return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
  if (props.statusCode >= 500) return 'bg-red-500/20 text-red-400 border-red-500/30'
  return 'bg-gray-500/20 text-gray-400 border-gray-500/30'
})

const statusText = computed(() => {
  const map: Record<number, string> = {
    200: 'OK', 201: 'Created', 204: 'No Content',
    400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
    404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable',
    500: 'Server Error', 502: 'Bad Gateway', 503: 'Unavailable'
  }
  return map[props.statusCode] || ''
})

const statusIcon = computed(() => {
  if (props.statusCode >= 200 && props.statusCode < 300) return '✓'
  if (props.statusCode >= 400) return '✗'
  return '→'
})
</script>

<template>
  <div class="flex items-center gap-2">
    <span
      :class="['inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-mono font-bold border', statusClass]"
    >
      <span>{{ statusIcon }}</span>
      <span>{{ statusCode }}</span>
      <span v-if="statusText" class="font-normal opacity-80">{{ statusText }}</span>
    </span>
    <span
      v-if="timeMs !== undefined"
      class="text-xs text-gray-500 font-mono"
    >
      {{ Math.round(timeMs) }}ms
    </span>
  </div>
</template>
