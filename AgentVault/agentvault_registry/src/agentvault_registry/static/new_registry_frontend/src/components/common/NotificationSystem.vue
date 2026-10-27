<script setup lang="ts">
import { ref, computed, TransitionGroup } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

// Types
export interface Notification {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message?: string
  duration?: number
  persistent?: boolean
  actions?: Array<{
    label: string
    handler: () => void
  }>
}

// State
const notifications = ref<Notification[]>([])
const notificationCounter = ref(0)

// Computed
const sortedNotifications = computed(() => {
  return [...notifications.value].reverse()
})

// Methods
// §FESUITE: toasts were invisible for months (the store never knew this component), so code written meanwhile may
// raise the same one in a loop. The same title and message twice in a row refresh the one on screen instead of
// stacking, and at most MAX_VISIBLE show at once (the oldest transient one leaves first).
const MAX_VISIBLE = 4
const refreshTimers = new Map<string, ReturnType<typeof setTimeout>>()

function addNotification(notification: Omit<Notification, 'id'>) {
  const twin = notifications.value.find(
    (n) => n.type === notification.type && n.title === notification.title && (n.message || '') === (notification.message || ''),
  )
  if (twin) {
    if (!twin.persistent && (notification.duration ?? twin.duration)) {
      const prev = refreshTimers.get(twin.id)
      if (prev) clearTimeout(prev)
      refreshTimers.set(twin.id, setTimeout(() => removeNotification(twin.id), notification.duration ?? twin.duration ?? 5000))
    }
    return twin.id
  }
  while (notifications.value.length >= MAX_VISIBLE) {
    const oldest = notifications.value.findIndex((n) => !n.persistent)
    if (oldest < 0) break
    notifications.value.splice(oldest, 1)
  }
  const id = `notification-${Date.now()}-${notificationCounter.value++}`
  const newNotification: Notification = {
    id,
    duration: 5000,
    persistent: false,
    ...notification
  }
  
  notifications.value.push(newNotification)
  
  // Auto-remove after duration
  if (!newNotification.persistent && newNotification.duration) {
    refreshTimers.set(id, setTimeout(() => {
      removeNotification(id)
    }, newNotification.duration))
  }
  
  return id
}

function removeNotification(id: string) {
  const timer = refreshTimers.get(id)
  if (timer) { clearTimeout(timer); refreshTimers.delete(id) }
  const index = notifications.value.findIndex(n => n.id === id)
  if (index > -1) {
    notifications.value.splice(index, 1)
  }
}

function clearAll() {
  notifications.value = []
}

// Notification type configs
const typeConfig = {
  success: {
    icon: '✓',
    bgColor: 'bg-green-50 dark:bg-green-900/20',
    borderColor: 'border-green-200 dark:border-green-800',
    iconBgColor: 'bg-green-100 dark:bg-green-900/40',
    iconColor: 'text-green-600 dark:text-green-400',
    titleColor: 'text-green-800 dark:text-green-200',
    messageColor: 'text-green-600 dark:text-green-300'
  },
  error: {
    icon: '✕',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
    borderColor: 'border-red-200 dark:border-red-800',
    iconBgColor: 'bg-red-100 dark:bg-red-900/40',
    iconColor: 'text-red-600 dark:text-red-400',
    titleColor: 'text-red-800 dark:text-red-200',
    messageColor: 'text-red-600 dark:text-red-300'
  },
  warning: {
    icon: '!',
    bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
    borderColor: 'border-yellow-200 dark:border-yellow-800',
    iconBgColor: 'bg-yellow-100 dark:bg-yellow-900/40',
    iconColor: 'text-yellow-600 dark:text-yellow-400',
    titleColor: 'text-yellow-800 dark:text-yellow-200',
    messageColor: 'text-yellow-600 dark:text-yellow-300'
  },
  info: {
    icon: 'i',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
    iconBgColor: 'bg-blue-100 dark:bg-blue-900/40',
    iconColor: 'text-blue-600 dark:text-blue-400',
    titleColor: 'text-blue-800 dark:text-blue-200',
    messageColor: 'text-blue-600 dark:text-blue-300'
  }
}

// Expose methods for external use
defineExpose({
  addNotification,
  removeNotification,
  clearAll,
  // Convenience methods
  success: (title: string, message?: string, options?: Partial<Notification>) => 
    addNotification({ type: 'success', title, message, ...options }),
  error: (title: string, message?: string, options?: Partial<Notification>) => 
    addNotification({ type: 'error', title, message, ...options }),
  warning: (title: string, message?: string, options?: Partial<Notification>) => 
    addNotification({ type: 'warning', title, message, ...options }),
  info: (title: string, message?: string, options?: Partial<Notification>) => 
    addNotification({ type: 'info', title, message, ...options })
})
</script>

<template>
  <!-- §LEDGERGATE (V0601): the stack is drawn above every page, panel and dialog (.nsys-stack below). At z-50 the beta
       banner (9999) lay over a notice's title on every page that shows it, and every overlay above 50 hid a notice
       raised from inside it; found by journal 51's photo drill, where "Ledger busy" sat under the banner. -->
  <div class="nsys-stack fixed top-4 right-4 pointer-events-none">
    <!-- A live region that exists before any toast does, so a screen reader announces each one as it arrives
         (an error is role="alert" and is announced at once). -->
    <TransitionGroup
      name="notification"
      tag="div"
      class="space-y-4"
      aria-live="polite"
      aria-relevant="additions"
    >
      <div
        v-for="notification in sortedNotifications"
        :key="notification.id"
        class="pointer-events-auto"
        data-testid="toast"
        :data-kind="notification.type"
        :role="notification.type === 'error' ? 'alert' : undefined"
      >
        <div
          :class="[
            'max-w-sm w-full shadow-lg rounded-lg border',
            typeConfig[notification.type].bgColor,
            typeConfig[notification.type].borderColor
          ]"
        >
          <div class="p-4">
            <div class="flex items-start">
              <!-- Icon -->
              <div
                :class="[
                  'shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-bold',
                  typeConfig[notification.type].iconBgColor,
                  typeConfig[notification.type].iconColor
                ]"
              >
                {{ typeConfig[notification.type].icon }}
              </div>
              
              <!-- Content -->
              <div class="ml-3 flex-1">
                <h3
                  :class="[
                    'text-sm font-medium',
                    typeConfig[notification.type].titleColor
                  ]"
                >
                  {{ notification.title }}
                </h3>
                <p
                  v-if="notification.message"
                  :class="[
                    'mt-1 text-sm',
                    typeConfig[notification.type].messageColor
                  ]"
                >
                  {{ notification.message }}
                </p>
                
                <!-- Actions -->
                <div v-if="notification.actions" class="mt-3 flex space-x-2">
                  <button
                    v-for="action in notification.actions"
                    :key="action.label"
                    @click="action.handler"
                    :class="[
                      'text-sm font-medium hover:underline',
                      typeConfig[notification.type].iconColor
                    ]"
                  >
                    {{ action.label }}
                  </button>
                </div>
              </div>
              
              <!-- Close button -->
              <button
                @click="removeNotification(notification.id)"
                class="shrink-0 ml-4 text-gray-400 hover:text-gray-500 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-sm"
                data-testid="toast-close"
                :aria-label="t('common.dismissNotification', 'Dismiss notification')"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
/* above the beta banner (App.vue, 9999), every modal overlay (up to 99999) and the guided tour (99990), like Frame
   Management's own page notices (100050); below the skip link (100100) and the stale-code bar, which outrank a notice */
.nsys-stack { z-index: 100050; }

/* Notification transitions */
.notification-enter-active,
.notification-leave-active {
  transition: all 0.3s ease;
}

.notification-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.notification-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

.notification-move {
  transition: transform 0.3s ease;
}

/* Optional: Slide in from top animation */
.notification-top-enter-from {
  transform: translateY(-100%);
  opacity: 0;
}

.notification-top-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>
