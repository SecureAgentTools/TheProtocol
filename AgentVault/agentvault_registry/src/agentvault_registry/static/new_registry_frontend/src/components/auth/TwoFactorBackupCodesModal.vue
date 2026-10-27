<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="flex items-center justify-center min-h-screen px-4">
          <!-- Backdrop -->
          <div class="fixed inset-0 bg-black/50" @click="close"></div>
          
          <!-- Modal -->
          <div class="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-6 space-y-6">
            <!-- Header -->
            <div class="flex justify-between items-center">
              <h2 class="text-2xl font-bold text-gray-900 dark:text-white">
                {{ step === 'password' ? 'Regenerate Backup Codes' : 'New Backup Codes' }}
              </h2>
              <button
                @click="close"
                aria-label="Close"
                type="button"
                class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Password Step -->
            <div v-if="step === 'password'" class="space-y-6">
              <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
                <div class="flex items-start space-x-3">
                  <svg class="w-5 h-5 text-yellow-600 dark:text-yellow-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <div class="text-sm text-yellow-800 dark:text-yellow-200">
                    <p class="font-medium">Warning</p>
                    <p class="mt-1">Regenerating backup codes will invalidate all your existing backup codes. Make sure to save the new codes.</p>
                  </div>
                </div>
              </div>

              <div class="space-y-2">
                <label for="password" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Confirm your password
                </label>
                <input
                  id="password"
                  v-model="password"
                  type="password"
                  @keydown.enter="regenerateCodes"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                  placeholder="Enter your password"
                >
              </div>

              <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm">
                {{ errorMessage }}
              </div>

              <div class="flex space-x-3">
                <button
                  @click="close"
                  class="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  @click="regenerateCodes"
                  :disabled="!password || isRegenerating"
                  class="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
                >
                  {{ isRegenerating ? 'Regenerating...' : 'Regenerate' }}
                </button>
              </div>
            </div>

            <!-- Backup Codes Display -->
            <div v-if="step === 'display'" class="space-y-6">
              <div class="text-center">
                <div class="text-5xl mb-4"><Icon name="mdi:shield-lock" /></div>
                <p class="text-gray-600 dark:text-gray-400">
                  Your new backup codes have been generated. Save these codes in a secure location.
                </p>
              </div>

              <!-- Backup Codes -->
              <div class="bg-gray-100 dark:bg-gray-700 rounded-lg p-4">
                <div class="grid grid-cols-2 gap-2">
                  <code v-for="code in backupCodes" :key="code" class="font-mono text-sm">
                    {{ code }}
                  </code>
                </div>
              </div>

              <!-- Actions -->
              <div class="flex space-x-3">
                <button
                  @click="downloadCodes"
                  class="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <Icon name="mdi:inbox" /> Download
                </button>
                <button
                  @click="copyCodes"
                  class="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <Icon name="mdi:clipboard" /> Copy
                </button>
              </div>

              <button
                @click="close"
                class="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                I've Saved My Codes
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, watch } from 'vue'
import { useTwoFactorStore } from '@/stores/twoFactor'
import { useUIStore } from '@/stores/ui'

// Props
const props = defineProps<{
  isOpen: boolean
}>()

// Emits
const emit = defineEmits<{
  close: []
}>()

// Stores
const twoFactorStore = useTwoFactorStore()
const uiStore = useUIStore()

// State
const step = ref<'password' | 'display'>('password')
const password = ref('')
const backupCodes = ref<string[]>([])
const isRegenerating = ref(false)
const errorMessage = ref('')

// Watch for modal open
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    resetModal()
  }
})

// Methods
const resetModal = () => {
  step.value = 'password'
  password.value = ''
  backupCodes.value = []
  errorMessage.value = ''
}

const regenerateCodes = async () => {
  if (!password.value) {
    errorMessage.value = 'Password is required'
    return
  }

  isRegenerating.value = true
  errorMessage.value = ''

  const result = await twoFactorStore.regenerateBackupCodes(password.value)

  if (result.success) {
    backupCodes.value = result.backupCodes || []
    step.value = 'display'
    password.value = '' // Clear password for security
  } else {
    errorMessage.value = result.error || 'Failed to regenerate backup codes'
  }

  isRegenerating.value = false
}

const downloadCodes = () => {
  twoFactorStore.downloadBackupCodes(backupCodes.value)
}

const copyCodes = () => {
  const content = backupCodes.value.join('\n')
  navigator.clipboard.writeText(content)
  uiStore.showSuccess('Copied', 'Backup codes copied to clipboard')
}

const close = () => {
  resetModal()
  emit('close')
}
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .relative,
.modal-leave-active .relative {
  transition: transform 0.3s ease;
}

.modal-enter-from .relative {
  transform: scale(0.9);
}

.modal-leave-to .relative {
  transform: scale(0.9);
}
</style>
