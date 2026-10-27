<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TutorialStep, StepResult } from '../../types/tutorial.types'
import JsonViewer from './JsonViewer.vue'
import StatusBadge from './StatusBadge.vue'
import EntityInspector from './EntityInspector.vue'

const props = defineProps<{
  step: TutorialStep
  result?: StepResult
  capturedValues: Record<string, any>
  isExecuting: boolean
  canExecute: boolean
  trackColor?: string  // e.g. "violet"
}>()

const emit = defineEmits<{
  (e: 'execute'): void
}>()

const showRequest = ref(true)
const showResponse = ref(true)

const borderColor = computed(() => {
  const c = props.trackColor || 'violet'
  return `border-l-${c}-500`
})

const hasResponse = computed(() =>
  props.result?.response !== undefined
)

const isSuccess = computed(() =>
  props.result?.status === 'success'
)

const isFailed = computed(() =>
  props.result?.status === 'failed'
)

/**
 * Build the display URL for the request panel.
 * Resolves $variable placeholders for display.
 */
const displayUrl = computed(() => {
  if (props.result?.request?.url) return props.result.request.url
  let path = props.step.apiCall.path
  // Resolve path params for display
  if (props.step.apiCall.pathParams) {
    for (const [param, ref] of Object.entries(props.step.apiCall.pathParams)) {
      const val = ref.startsWith('$')
        ? props.capturedValues[ref.slice(1)] || `<${ref}>`
        : ref
      path = path.replace(`{${param}}`, val)
    }
  }
  path = path.replace(/\$(\w+)/g, (_, key) =>
    props.capturedValues[key] || `<$${key}>`
  )
  return `${window.location.origin}/sandbox/api/v1${path}`
})

/**
 * Build display body — resolve variables for preview.
 */
const displayBody = computed(() => {
  if (props.result?.request?.body) return props.result.request.body
  if (!props.step.apiCall.body) return null
  const body = JSON.parse(JSON.stringify(props.step.apiCall.body))
  resolveVars(body)
  return body
})

function resolveVars(obj: any) {
  for (const key of Object.keys(obj)) {
    if (typeof obj[key] === 'string' && obj[key].startsWith('$')) {
      const capKey = obj[key].slice(1)
      if (props.capturedValues[capKey] !== undefined) {
        obj[key] = props.capturedValues[capKey]
      }
    } else if (typeof obj[key] === 'object' && obj[key] !== null) {
      resolveVars(obj[key])
    }
  }
}

/**
 * Display headers — informational only.
 */
const displayHeaders = computed(() => {
  if (props.result?.request?.headers) return props.result.request.headers
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const auth = props.step.apiCall.authType
  if (auth === 'developer' || auth === 'admin') {
    h['Authorization'] = 'Bearer <developer-jwt>'
  } else if (auth === 'agent') {
    const tok = props.step.apiCall.authTokenRef
    const val = tok?.startsWith('$') ? props.capturedValues[tok.slice(1)] : undefined
    h['Authorization'] = `Bearer ${val ? maskToken(val) : '<agent-jwt>'}`
  } else if (auth === 'bootstrap') {
    const tok = props.step.apiCall.authTokenRef
    const val = tok?.startsWith('$') ? props.capturedValues[tok.slice(1)] : undefined
    h['Bootstrap-Token'] = val ? maskToken(val) : '<bootstrap-token>'
  }
  return h
})

function maskToken(token: string): string {
  if (token.length <= 20) return token
  return `${token.substring(0, 10)}...${token.substring(token.length - 6)}`
}

const methodColors: Record<string, string> = {
  GET: 'text-emerald-400 bg-emerald-500/10',
  POST: 'text-blue-400 bg-blue-500/10',
  PUT: 'text-amber-400 bg-amber-500/10',
  DELETE: 'text-red-400 bg-red-500/10'
}
</script>

<template>
  <div class="rounded-xl border border-gray-700/60 bg-gray-900/50 overflow-hidden shadow-lg">
    <!-- REQUEST Panel -->
    <div class="border-l-4 border-l-violet-500">
      <!-- Request Header -->
      <button
        @click="showRequest = !showRequest"
        class="w-full px-4 py-3 flex items-center gap-3 bg-gray-800/60 hover:bg-gray-800/80 transition-colors"
      >
        <span class="text-gray-500 text-xs">{{ showRequest ? '▼' : '▶' }}</span>
        <span class="text-gray-400 text-xs font-semibold uppercase tracking-wider">Request</span>
        <span :class="['px-2 py-0.5 rounded-sm text-xs font-bold font-mono', methodColors[step.apiCall.method] || 'text-gray-400']">
          {{ step.apiCall.method }}
        </span>
        <code class="text-gray-300 text-xs font-mono truncate flex-1 text-left">
          {{ displayUrl }}
        </code>
      </button>

      <!-- Request Body -->
      <div v-show="showRequest" class="px-4 pb-4">
        <!-- Headers -->
        <div class="mt-3 mb-3">
          <div class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-1.5">Headers</div>
          <div class="bg-gray-950/50 rounded-lg p-3 space-y-1">
            <div v-for="(value, key) in displayHeaders" :key="key" class="flex gap-2 text-xs font-mono">
              <span class="text-cyan-400 shrink-0">{{ key }}:</span>
              <span class="text-gray-400 truncate">{{ value }}</span>
            </div>
          </div>
        </div>

        <!-- Body -->
        <div v-if="displayBody">
          <div class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-1.5">Body</div>
          <JsonViewer :data="displayBody" :initially-expanded="true" />
        </div>

        <!-- Description -->
        <p class="text-gray-500 text-xs mt-3 italic">
          {{ step.apiCall.description }}
        </p>
      </div>
    </div>

    <!-- Execute Button -->
    <div class="px-4 py-3 bg-gray-800/30 border-t border-b border-gray-700/30 flex items-center justify-center gap-3">
      <button
        v-if="!isSuccess"
        @click="emit('execute')"
        :disabled="!canExecute || isExecuting"
        :class="[
          'px-6 py-2.5 rounded-lg font-semibold text-sm transition-all flex items-center gap-2',
          canExecute && !isExecuting
            ? 'bg-linear-to-r/srgb from-violet-600 to-purple-700 hover:from-violet-500 hover:to-purple-600 text-white shadow-lg shadow-violet-500/20 hover:shadow-violet-500/40'
            : 'bg-gray-700/50 text-gray-500 cursor-not-allowed'
        ]"
      >
        <span v-if="isExecuting" class="inline-block animate-spin">⟳</span>
        <span v-else>▶</span>
        {{ isExecuting ? 'Executing...' : 'Execute Call' }}
      </button>
      <div v-else class="flex items-center gap-2 text-emerald-400 text-sm font-semibold">
        <span>✓</span>
        <span>Step Complete</span>
      </div>
    </div>

    <!-- RESPONSE Panel -->
    <div
      v-if="hasResponse || isFailed"
      :class="[
        'border-l-4 transition-all',
        isSuccess ? 'border-l-emerald-500' : 'border-l-red-500'
      ]"
    >
      <button
        @click="showResponse = !showResponse"
        class="w-full px-4 py-3 flex items-center gap-3 bg-gray-800/40 hover:bg-gray-800/60 transition-colors"
      >
        <span class="text-gray-500 text-xs">{{ showResponse ? '▼' : '▶' }}</span>
        <span class="text-gray-400 text-xs font-semibold uppercase tracking-wider">Response</span>
        <StatusBadge
          v-if="result?.response"
          :status-code="result.response.statusCode"
          :time-ms="result.response.timeMs"
        />
      </button>

      <div v-show="showResponse" class="px-4 pb-4">
        <!-- Error message -->
        <div v-if="result?.error" class="mt-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
          <p class="text-red-400 text-sm font-mono">{{ result.error }}</p>
        </div>

        <!-- Response Body -->
        <div v-if="result?.response?.body" class="mt-3">
          <div class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-1.5">Response Body</div>
          <JsonViewer :data="result.response.body" :initially-expanded="true" />
        </div>
      </div>
    </div>

    <!-- Captured Values -->
    <div v-if="isSuccess && step.captures && step.captures.length > 0" class="border-t border-gray-700/30">
      <div class="p-4">
        <EntityInspector
          :captures="step.captures"
          :captured-values="capturedValues"
          :just-captured="result?.capturedValues"
        />
      </div>
    </div>
  </div>
</template>
