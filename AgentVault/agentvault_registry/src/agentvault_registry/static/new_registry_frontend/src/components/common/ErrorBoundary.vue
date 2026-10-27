<script setup lang="ts">
import { ref, onErrorCaptured, computed, getCurrentInstance, onBeforeUnmount } from 'vue'
import type { Router } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { isStaleChunkError, recoverFromStaleChunk } from '@/services/staleChunk'

const { t } = useI18n()

// Props
interface Props {
  fallback?: string
  showDetails?: boolean
  onError?: (error: Error) => void
}

const props = withDefaults(defineProps<Props>(), {
  fallback: 'Something went wrong. Please try again.',
  showDetails: false
})

// State
const error = ref<Error | null>(null)
const errorInfo = ref<string>('')
const showErrorDetails = ref(false)

// Error handling
onErrorCaptured((err: Error, instance, info) => {
  console.error('Error caught by boundary:', err)
  // §FESUITE (2026-10-10): a component's chunk that cannot load (the quick-create sheet, after a deploy removed it, on a
  // page opened before) gets the router's answer to a view's: clear the asset cache and reload, at most twice in a row,
  // then the reload banner (services/staleChunk.ts). The panel kept "Failed to fetch dynamically imported module" until
  // the person reloaded (V0590's deployed proof); it shows only once the reloads are spent.
  if (isStaleChunkError(err) && recoverFromStaleChunk() === 'reloading') return false
  error.value = err
  errorInfo.value = info
  
  // Call custom error handler if provided
  if (props.onError) {
    props.onError(err)
  }
  
  // Prevent the error from propagating
  return false
})

// §FESUITE (2026-10-10): a person who moves to another page gets that page, not the last one's crash. The boundary wraps
// the whole console (App.vue), so a page that threw while the registry did not answer kept "Oops! Something went wrong"
// over every page until Try again or a reload (sweeps/recovery on V0589: the API tester). The router's own hook, read
// from the app (a boundary mounted without a router keeps its panel until Try again, as before).
const router = getCurrentInstance()?.appContext.config.globalProperties.$router as Router | undefined
const stopResetOnMove = router?.afterEach((to, from) => {
  if (error.value && to.fullPath !== from.fullPath) reset()
})
onBeforeUnmount(() => { stopResetOnMove?.() })

// Computed
const errorMessage = computed(() => {
  if (!error.value) return ''
  return error.value.message || props.fallback
})

const errorStack = computed(() => {
  if (!error.value?.stack) return ''
  // Clean up stack trace for display
  return error.value.stack
    .split('\n')
    .slice(0, 5) // Show only first 5 lines
    .join('\n')
})

// Check if we're in development mode
const isDev = computed(() => import.meta.env.DEV)

// Methods
function reset() {
  error.value = null
  errorInfo.value = ''
  showErrorDetails.value = false
}

function toggleDetails() {
  showErrorDetails.value = !showErrorDetails.value
}

function reload() {
  window.location.reload()
}
</script>

<template>
  <!-- Error state (data-testid: the console suite tells a crashed page from a quiet one by it, in any language) -->
  <div v-if="error" class="min-h-[400px] flex items-center justify-center p-4" data-testid="error-boundary">
    <div class="max-w-md w-full">
      <div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6">
        <!-- Error icon -->
        <div class="flex justify-center mb-4">
          <div class="w-16 h-16 bg-red-100 dark:bg-red-900/40 rounded-full flex items-center justify-center">
            <svg
              class="w-8 h-8 text-red-600 dark:text-red-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
        </div>

        <!-- Error message -->
        <h3 class="text-lg font-semibold text-red-800 dark:text-red-200 text-center mb-2">
          {{ t('errorBoundary.title') }}
        </h3>
        <p class="text-red-600 dark:text-red-300 text-center mb-4">
          {{ errorMessage }}
        </p>

        <!-- Error details (dev mode) -->
        <div v-if="showDetails || isDev" class="mb-4">
          <button
            @click="toggleDetails"
            class="text-sm text-red-600 dark:text-red-400 hover:underline mb-2"
          >
            {{ showErrorDetails ? t('errorBoundary.hide') : t('errorBoundary.show') }} {{ t('errorBoundary.details') }}
          </button>
          
          <div v-if="showErrorDetails" class="mt-2">
            <pre class="text-xs bg-red-100 dark:bg-red-900/40 p-3 rounded-sm overflow-x-auto text-red-800 dark:text-red-200">{{ errorStack }}</pre>
            <p v-if="errorInfo" class="text-xs text-red-600 dark:text-red-400 mt-1">
              {{ t('errorBoundary.component') }}: {{ errorInfo }}
            </p>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex space-x-3 justify-center">
          <button
            @click="reset"
            class="px-4 py-2 bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 border border-red-300 dark:border-red-700 rounded-md hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
          >
            {{ t('errorBoundary.tryAgain') }}
          </button>
          <button
            @click="reload"
            class="px-4 py-2 bg-red-600 dark:bg-red-700 text-white rounded-md hover:bg-red-700 dark:hover:bg-red-600 transition-colors"
          >
            {{ t('errorBoundary.reloadPage') }}
          </button>
        </div>
      </div>

      <!-- Help text -->
      <p class="text-center text-sm text-gray-500 dark:text-gray-400 mt-4">
        {{ t('errorBoundary.persistContact') }}
      </p>
    </div>
  </div>

  <!-- Normal state (no error) -->
  <div v-else>
    <slot />
  </div>
</template>

<style scoped>
/* Error animation */
@keyframes shake {
  0%, 100% {
    transform: translateX(0);
  }
  10%, 30%, 50%, 70%, 90% {
    transform: translateX(-2px);
  }
  20%, 40%, 60%, 80% {
    transform: translateX(2px);
  }
}

.error-shake {
  animation: shake 0.5s ease-in-out;
}
</style>
