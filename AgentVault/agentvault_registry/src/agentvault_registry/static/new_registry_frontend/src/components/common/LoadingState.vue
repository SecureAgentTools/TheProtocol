<script setup lang="ts">
import { computed } from 'vue'

// Props
interface Props {
  text?: string
  size?: 'small' | 'medium' | 'large'
  fullScreen?: boolean
  overlay?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  text: 'Loading...',
  size: 'medium',
  fullScreen: false,
  overlay: false
})

// Computed
const sizeClasses = computed(() => {
  const sizes = {
    small: 'w-8 h-8',
    medium: 'w-12 h-12',
    large: 'w-16 h-16'
  }
  return sizes[props.size]
})

const textSizeClass = computed(() => {
  const sizes = {
    small: 'text-sm',
    medium: 'text-base',
    large: 'text-lg'
  }
  return sizes[props.size]
})

const containerClasses = computed(() => {
  if (props.fullScreen) {
    return 'fixed inset-0 z-50'
  }
  if (props.overlay) {
    return 'absolute inset-0 z-10'
  }
  return 'relative'
})
</script>

<template>
  <div
    :class="[
      containerClasses,
      'flex flex-col items-center justify-center',
      (fullScreen || overlay) && 'bg-white/80 dark:bg-gray-900/80 backdrop-blur-xs'
    ]"
  >
    <!-- Spinner -->
    <div class="relative">
      <div
        :class="[
          sizeClasses,
          'animate-spin rounded-full border-b-2 border-blue-600 dark:border-blue-400'
        ]"
      />
      <div
        :class="[
          sizeClasses,
          'absolute inset-0 rounded-full border-2 border-gray-200 dark:border-gray-700'
        ]"
      />
    </div>
    
    <!-- Loading text -->
    <p
      v-if="text"
      :class="[
        'mt-4 font-medium text-gray-700 dark:text-gray-300',
        textSizeClass
      ]"
    >
      {{ text }}
    </p>
    
    <!-- Additional content slot -->
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
  </div>
</template>

<style scoped>
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.animate-spin {
  animation: spin 1s linear infinite;
}

/* Alternative loading animations */
.loading-dots {
  display: inline-flex;
  align-items: center;
}

.loading-dots span {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  margin: 0 0.125rem;
  background-color: currentColor;
  border-radius: 50%;
  animation: loading-dots 1.4s infinite ease-in-out both;
}

.loading-dots span:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes loading-dots {
  0%,
  80%,
  100% {
    transform: scale(0);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* Pulse animation */
.pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
</style>
