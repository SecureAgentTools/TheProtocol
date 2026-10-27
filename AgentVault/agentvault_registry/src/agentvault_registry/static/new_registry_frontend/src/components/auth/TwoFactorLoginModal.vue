<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="flex items-center justify-center min-h-screen px-4">
          <!-- Backdrop -->
          <div class="fixed inset-0 bg-black/50"></div>
          
          <!-- Modal -->
          <div class="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-6 space-y-6">
            <!-- Header -->
            <div class="flex justify-between items-center">
              <h2 class="text-2xl font-bold text-gray-900 dark:text-white">
                Two-Factor Authentication
              </h2>
              <button
                @click="cancel"
                class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Tab Selection -->
            <div class="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1">
              <button
                @click="mode = 'authenticator'"
                :class="[
                  'flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors',
                  mode === 'authenticator' 
                    ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-white shadow-sm' 
                    : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                ]"
              >
                Authenticator App
              </button>
              <button
                @click="mode = 'backup'"
                :class="[
                  'flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors',
                  mode === 'backup' 
                    ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-white shadow-sm' 
                    : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                ]"
              >
                Backup Code
              </button>
            </div>

            <!-- Authenticator Mode -->
            <div v-if="mode === 'authenticator'" class="space-y-6">
              <p class="text-gray-600 dark:text-gray-400">
                Enter the 6-digit code from your authenticator app
              </p>

              <!-- Code Input -->
              <div class="flex justify-center space-x-2">
                <input
                  v-for="(digit, index) in authCode"
                  :key="`auth-${index}`"
                  :ref="el => (authInputs[index] = el)"
                  v-model="authCode[index]"
                  type="text"
                  maxlength="1"
                  pattern="[0-9]"
                  inputmode="numeric"
                  :autocomplete="index === 0 ? 'one-time-code' : 'off'"
                  class="w-12 h-12 text-center text-2xl border-2 border-gray-300 dark:border-gray-600 rounded-lg focus:border-blue-500 focus:outline-hidden dark:bg-gray-700 dark:text-white"
                  @input="handleAuthInput(index)"
                  @keydown.backspace="handleAuthBackspace(index)"
                  @paste="handleAuthPaste"
                >
              </div>

              <!-- Error Message -->
              <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm text-center">
                {{ errorMessage }}
              </div>

              <!-- Submit Button -->
              <button
                @click="submitAuthCode"
                :disabled="!isAuthCodeComplete || isSubmitting"
                class="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                {{ isSubmitting ? 'Verifying...' : 'Verify' }}
              </button>
            </div>

            <!-- Backup Code Mode -->
            <div v-if="mode === 'backup'" class="space-y-6">
              <p class="text-gray-600 dark:text-gray-400">
                Enter one of your backup codes to sign in
              </p>

              <!-- Backup Code Input -->
              <div class="space-y-2">
                <input
                  v-model="backupCode"
                  type="text"
                  @keydown.enter="submitBackupCode"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white font-mono"
                  placeholder="Enter backup code"
                >
              </div>

              <!-- Error Message -->
              <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm text-center">
                {{ errorMessage }}
              </div>

              <!-- Submit Button -->
              <button
                @click="submitBackupCode"
                :disabled="!backupCode || isSubmitting"
                class="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                {{ isSubmitting ? 'Verifying...' : 'Sign In' }}
              </button>

              <p class="text-sm text-gray-500 dark:text-gray-400 text-center">
                Each backup code can only be used once
              </p>
            </div>

            <!-- Help Text -->
            <div class="border-t border-gray-200 dark:border-gray-700 pt-4">
              <p class="text-sm text-gray-500 dark:text-gray-400 text-center">
                Lost your authenticator? 
                <button
                  @click="mode = mode === 'authenticator' ? 'backup' : 'authenticator'"
                  class="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  {{ mode === 'authenticator' ? 'Use backup code' : 'Use authenticator app' }}
                </button>
              </p>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useTwoFactorStore } from '@/stores/twoFactor'
import { useRouter } from 'vue-router'

// Props
const props = defineProps<{
  isOpen: boolean
}>()

// Emits
const emit = defineEmits<{
  close: []
  success: []
}>()

// Stores & Router
const twoFactorStore = useTwoFactorStore()
const router = useRouter()

// State
const mode = ref<'authenticator' | 'backup'>('authenticator')
const authCode = ref(['', '', '', '', '', ''])
const authInputs = ref<any[]>([])
const backupCode = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')

// Computed
const isAuthCodeComplete = computed(() => 
  authCode.value.every(digit => digit !== '')
)

// Watch for modal open
watch(() => props.isOpen, async (newVal) => {
  if (newVal) {
    resetModal()
    await nextTick()
    // Focus first input
    if (mode.value === 'authenticator') {
      authInputs.value[0]?.focus()
    }
  }
})

// Watch mode changes to focus inputs
watch(mode, async () => {
  await nextTick()
  if (mode.value === 'authenticator') {
    authInputs.value[0]?.focus()
  }
})

// Methods
const resetModal = () => {
  mode.value = 'authenticator'
  authCode.value = ['', '', '', '', '', '']
  backupCode.value = ''
  errorMessage.value = ''
  isSubmitting.value = false
}

const handleAuthInput = (index: number) => {
  const value = authCode.value[index]
  
  // Only allow numeric input
  if (value && !/^\d$/.test(value)) {
    authCode.value[index] = ''
    return
  }
  
  // Move to next input if value entered
  if (value && index < 5) {
    authInputs.value[index + 1]?.focus()
  }
  
  // Auto-submit if all digits entered
  if (isAuthCodeComplete.value) {
    submitAuthCode()
  }
}

const handleAuthBackspace = (index: number) => {
  if (!authCode.value[index] && index > 0) {
    authInputs.value[index - 1]?.focus()
  }
}

const handleAuthPaste = (event: ClipboardEvent) => {
  event.preventDefault()
  const pastedData = event.clipboardData?.getData('text')
  
  if (pastedData && /^\d{6}$/.test(pastedData)) {
    // If exactly 6 digits pasted, fill all inputs
    pastedData.split('').forEach((digit, index) => {
      authCode.value[index] = digit
    })
    // Auto-submit
    submitAuthCode()
  }
}

const submitAuthCode = async () => {
  if (!isAuthCodeComplete.value || isSubmitting.value) return
  
  isSubmitting.value = true
  errorMessage.value = ''
  
  const code = authCode.value.join('')
  const result = await twoFactorStore.validateCode(code)
  
  if (result.success) {
    emit('success')
    emit('close')
    // Navigate to mission-control or intended route
    const redirect = router.currentRoute.value.query.redirect as string
    router.push(redirect || '/mission-control')
  } else {
    errorMessage.value = result.error || 'Invalid code. Please try again.'
    // Clear code on error
    authCode.value = ['', '', '', '', '', '']
    authInputs.value[0]?.focus()
  }
  
  isSubmitting.value = false
}

const submitBackupCode = async () => {
  if (!backupCode.value || isSubmitting.value) return
  
  isSubmitting.value = true
  errorMessage.value = ''
  
  const result = await twoFactorStore.recoverWithBackupCode(backupCode.value)
  
  if (result.success) {
    emit('success')
    emit('close')
    // Navigate to mission-control or intended route
    const redirect = router.currentRoute.value.query.redirect as string
    router.push(redirect || '/mission-control')
  } else {
    errorMessage.value = result.error || 'Invalid backup code. Please try again.'
    backupCode.value = ''
  }
  
  isSubmitting.value = false
}

const cancel = () => {
  // Clear partial token and close
  twoFactorStore.clearData()
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
