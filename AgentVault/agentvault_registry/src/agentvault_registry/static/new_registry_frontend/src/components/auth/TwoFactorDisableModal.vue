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
                Disable Two-Factor Authentication
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

            <!-- Warning -->
            <div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
              <div class="flex items-start space-x-3">
                <svg class="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <div class="text-sm text-red-800 dark:text-red-200">
                  <p class="font-medium">Warning: This will reduce your account security</p>
                  <p class="mt-1">Disabling two-factor authentication will make your account more vulnerable to unauthorized access.</p>
                </div>
              </div>
            </div>

            <!-- Consequences List -->
            <div class="space-y-3">
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
                By disabling 2FA, you will:
              </p>
              <ul class="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li class="flex items-start space-x-2">
                  <span class="text-red-500 mt-0.5">•</span>
                  <span>Remove the additional security layer from your account</span>
                </li>
                <li class="flex items-start space-x-2">
                  <span class="text-red-500 mt-0.5">•</span>
                  <span>Invalidate all existing backup codes</span>
                </li>
                <li class="flex items-start space-x-2">
                  <span class="text-red-500 mt-0.5">•</span>
                  <span>Need only your password to sign in</span>
                </li>
              </ul>
            </div>

            <!-- Password Input -->
            <div class="space-y-2">
              <label for="disable-password" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Confirm your password to continue
              </label>
              <input
                id="disable-password"
                v-model="password"
                type="password"
                @keydown.enter="disable2FA"
                class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                placeholder="Enter your password"
              >
            </div>

            <!-- Code Input: the server requires a current code (or an unused backup code) as well as the password -->
            <div class="space-y-2">
              <label for="disable-code" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Authenticator code or backup code
              </label>
              <input
                id="disable-code"
                v-model="code"
                type="text"
                inputmode="text"
                autocomplete="one-time-code"
                maxlength="9"
                @keydown.enter="disable2FA"
                class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                placeholder="123456 or XXXX-XXXX"
              >
            </div>

            <!-- Error Message -->
            <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm">
              {{ errorMessage }}
            </div>

            <!-- Buttons -->
            <div class="flex space-x-3">
              <button
                @click="close"
                class="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <button
                @click="disable2FA"
                :disabled="!password || !code.trim() || twoFactorStore.isDisabling"
                class="flex-1 px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                {{ twoFactorStore.isDisabling ? 'Disabling...' : 'Disable 2FA' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useTwoFactorStore } from '@/stores/twoFactor'

// Props
const props = defineProps<{
  isOpen: boolean
}>()

// Emits
const emit = defineEmits<{
  close: []
  disabled: []
}>()

// Store
const twoFactorStore = useTwoFactorStore()

// State
const password = ref('')
const code = ref('')
const errorMessage = ref('')

// Watch for modal open
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    resetModal()
  }
})

// Methods
const resetModal = () => {
  password.value = ''
  code.value = ''
  errorMessage.value = ''
}

const disable2FA = async () => {
  if (!password.value) {
    errorMessage.value = 'Password is required'
    return
  }
  if (!code.value.trim()) {
    errorMessage.value = 'A code from your authenticator app (or a backup code) is required'
    return
  }

  errorMessage.value = ''
  const result = await twoFactorStore.disable(password.value, code.value.trim())

  if (result.success) {
    emit('disabled')
    close()
  } else {
    errorMessage.value = result.error || 'Failed to disable 2FA'
  }
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
