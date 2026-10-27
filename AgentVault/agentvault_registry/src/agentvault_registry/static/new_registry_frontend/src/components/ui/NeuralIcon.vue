<template>
  <component :is="iconComponent" 
    :class="iconClasses"
    :size="size"
    :stroke-width="strokeWidth"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { resolveNeuralIcon } from './neuralIcons'

interface Props {
  name: string
  size?: number | string
  color?: string
  strokeWidth?: number | string
  class?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: 20,
  strokeWidth: 2,
  color: 'currentColor'
})

// The icon for this name: a named import from the table in ./neuralIcons.ts, or its help-circle fallback for a
// name the table does not have (NO EMOJIS: every icon is a Lucide component).
const iconComponent = computed(() => resolveNeuralIcon(props.name))

// Compute icon classes
const iconClasses = computed(() => {
  const classes = ['nc-icon']
  
  if (props.color) {
    if (props.color.startsWith('#') || props.color.startsWith('rgb')) {
      // Custom color will be applied via style
    } else {
      // Semantic color class
      classes.push(`nc-icon-${props.color}`)
    }
  }
  
  if (props.class) {
    classes.push(props.class)
  }
  
  if (props.name === 'loading') {
    classes.push('nc-icon-spin')
  }
  
  return classes.join(' ')
})
</script>

<style scoped>
.nc-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all var(--nc-duration-fast) var(--nc-easing-default);
}

/* Semantic colors */
.nc-icon-primary {
  color: var(--nc-primary);
}

.nc-icon-success {
  color: var(--nc-success);
}

.nc-icon-warning {
  color: var(--nc-warning);
}

.nc-icon-danger {
  color: var(--nc-danger);
}

.nc-icon-muted {
  color: var(--nc-text-muted);
}

.nc-icon-gray {
  color: #9ca3af;
}

.nc-icon-bronze {
  color: #cd7f32;
}

/* Hover effects */
.nc-icon:hover {
  transform: scale(1.1);
}

/* Spin animation for loading */
.nc-icon-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
