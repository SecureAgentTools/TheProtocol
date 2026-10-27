<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { computed, ref, getCurrentInstance } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'

interface Props {
  show: boolean
  title?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  class?: string
}

const props = withDefaults(defineProps<Props>(), {
  show: false,
  size: 'md'
})

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

// Accessibility: dialog semantics + keyboard focus management. The modal panel
// gets role="dialog"/aria-modal, is labelled by its header, and traps Tab focus
// while open (restoring focus to the trigger on close) via useFocusTrap.
const panelRef = ref<HTMLElement | null>(null)
const titleId = `tp-modal-title-${getCurrentInstance()?.uid ?? 0}`
useFocusTrap(panelRef, { activeWhen: computed(() => props.show) })

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'max-w-sm'
    case 'lg':
      return 'max-w-3xl'
    case 'xl':
      return 'max-w-5xl'
    default:
      return 'max-w-lg'
  }
})

const modalClasses = computed(() => {
  const classes = ['tp-base-modal relative bg-white dark:bg-gray-800 rounded-lg shadow-xl', sizeClasses.value]
  if (props.class) {
    classes.push(props.class)
  }
  return classes.join(' ')
})

function close() {
  emit('update:show', false)
}

// Close on Escape. §COCKPITDESK (2026-10-14): the listener follows `show` from the first
// render, because a host can MOUNT this modal already open (the desk renders
// `<AgentDetailModal v-if="open" :show="true">`) and a lazy watcher never sees that first
// true. §COCKPITDESK (2026-10-15): it is the shared stack now (composables/useEscapeClose),
// so the topmost open dialog answers whichever way it was opened: this modal's own document
// listener ran after a stack dialog's opened before it, and that one closed under it. A
// dialog the stack does not know that holds the focus still owns its press, and a used press
// is marked as used, so a board behind it (a maximised desk pane) does not take it.
useEscapeClose(() => !!props.show, close, () => true, () => panelRef.value)
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="ease-out duration-300"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="ease-in duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="show"
        class="fixed inset-0 z-50 overflow-y-auto"
      >
        <div class="tp-base-modal-wrap flex min-h-screen items-center justify-center p-4 text-center sm:p-0">
          <!-- Background overlay -->
          <div
            class="fixed inset-0 bg-gray-500/75 transition-opacity"
            @click="close"
          />

          <!-- Modal panel -->
          <Transition
            enter-active-class="ease-out duration-300"
            enter-from-class="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            enter-to-class="opacity-100 translate-y-0 sm:scale-100"
            leave-active-class="ease-in duration-200"
            leave-from-class="opacity-100 translate-y-0 sm:scale-100"
            leave-to-class="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
          >
            <div
              v-if="show"
              ref="panelRef"
              :class="modalClasses"
              role="dialog"
              aria-modal="true"
              :aria-labelledby="(title || $slots.header) ? titleId : undefined"
              tabindex="-1"
            >
              <!-- Header -->
              <div
                v-if="title || $slots.header"
                :id="titleId"
                class="border-b border-gray-200 dark:border-gray-700 px-6 py-4"
              >
                <slot name="header">
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
                    {{ title }}
                  </h3>
                </slot>
              </div>

              <!-- Body -->
              <div class="px-6 py-4">
                <slot />
              </div>

              <!-- Footer -->
              <div
                v-if="$slots.footer"
                class="border-t border-gray-200 dark:border-gray-700 px-6 py-4"
              >
                <slot name="footer" />
              </div>

              <!-- Close button -->
              <button
                @click="close"
                aria-label="Close"
                class="absolute top-4 right-4 text-gray-400 hover:text-gray-500 focus:outline-hidden"
              >
                <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </Transition>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
