<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-50 overflow-y-auto">
        <div class="flex items-center justify-center min-h-screen px-4">
          <!-- Backdrop -->
          <div class="fixed inset-0 bg-black/50" @click="handleClose"></div>
          
          <!-- Modal -->
          <div class="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6 space-y-6">
            <!-- Header -->
            <div class="flex justify-between items-center">
              <h2 class="text-2xl font-bold text-gray-900 dark:text-white">
                {{ getStepTitle() }}
              </h2>
              <button
                @click="handleClose"
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
              <p class="text-gray-600 dark:text-gray-400">
                Enter your password to begin setting up two-factor authentication.
              </p>

              <div class="space-y-2">
                <label for="password" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Password
                </label>
                <input
                  id="password"
                  v-model="password"
                  type="password"
                  @keydown.enter="startSetup"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                  placeholder="Enter your password"
                >
              </div>

              <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm">
                {{ errorMessage }}
              </div>

              <button
                @click="startSetup"
                :disabled="!password || twoFactorStore.isSettingUp"
                class="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                {{ twoFactorStore.isSettingUp ? 'Setting up...' : 'Continue' }}
              </button>
            </div>

            <!-- Setup Step -->
            <div v-if="step === 'setup'" class="space-y-6">
              <p class="text-gray-600 dark:text-gray-400">
                Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.)
              </p>

              <!-- QR Code -->
              <div class="flex flex-col items-center space-y-4">
                <div class="p-4 bg-white rounded-lg">
                  <img 
                    v-if="twoFactorStore.setupData?.qrCode"
                    :src="twoFactorStore.setupData.qrCode"
                    alt="2FA QR Code"
                    class="w-48 h-48"
                  />
                  <canvas v-else ref="qrCanvas" class="w-48 h-48"></canvas>
                </div>
                <p class="text-sm text-gray-500 dark:text-gray-400 text-center">
                  Scan this QR code with your authenticator app
                </p>
                <!-- §DISCREFINE — enrolling ON the phone that holds the authenticator
                     is the common case now, and that phone cannot scan its own screen.
                     The otpauth:// link hands the secret straight to the app in one tap. -->
                <a
                  v-if="twoFactorStore.setupData?.otpauthUri"
                  :href="twoFactorStore.setupData.otpauthUri"
                  data-testid="tfa-tap-to-add"
                  class="text-sm px-3 py-2 rounded-sm bg-blue-600 text-white hover:bg-blue-700"
                >
                  <Icon name="mdi:cellphone" /> On this device: add to authenticator app
                </a>
              </div>

              <!-- Manual Entry -->
              <div class="space-y-2">
                <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Or enter this code manually:
                </p>
                <div class="flex items-center space-x-2">
                  <code class="flex-1 px-3 py-2 bg-gray-100 dark:bg-gray-700 rounded-sm text-sm font-mono break-all">
                    {{ twoFactorStore.setupData?.secret }}
                  </code>
                  <button
                    @click="copySecret"
                    class="px-3 py-2 bg-gray-200 dark:bg-gray-700 rounded-sm hover:bg-gray-300 dark:hover:bg-gray-600"
                  >
                    <Icon name="mdi:clipboard" /> Copy
                  </button>
                </div>
              </div>

              <!-- Continue Button -->
              <button
                @click="step = 'verify'"
                class="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                Continue to Verification
              </button>
            </div>

            <!-- Verify Step -->
            <div v-if="step === 'verify'" class="space-y-6">
              <p class="text-gray-600 dark:text-gray-400">
                Enter the 6-digit code from your authenticator app to complete setup.
              </p>

              <!-- Verification Code Input -->
              <div class="flex justify-center space-x-2">
                <input
                  v-for="(digit, index) in verificationCode"
                  :key="index"
                  :ref="el => (codeInputs[index] = el)"
                  v-model="verificationCode[index]"
                  type="text"
                  maxlength="1"
                  pattern="[0-9]"
                  inputmode="numeric"
                  :autocomplete="index === 0 ? 'one-time-code' : 'off'"
                  class="w-12 h-12 text-center text-2xl border-2 border-gray-300 dark:border-gray-600 rounded-lg focus:border-blue-500 focus:outline-hidden dark:bg-gray-700 dark:text-white"
                  @input="handleCodeInput(index)"
                  @keydown.backspace="handleBackspace(index)"
                  @paste="handlePaste"
                >
              </div>

              <!-- Error Message -->
              <div v-if="errorMessage" class="text-red-600 dark:text-red-400 text-sm text-center">
                {{ errorMessage }}
              </div>

              <!-- Buttons -->
              <div class="flex space-x-3">
                <button
                  @click="step = 'setup'"
                  class="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Back
                </button>
                <button
                  @click="verifyCode"
                  :disabled="!isCodeComplete || twoFactorStore.isVerifying"
                  class="flex-1 px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
                >
                  {{ twoFactorStore.isVerifying ? 'Verifying...' : 'Enable 2FA' }}
                </button>
              </div>
            </div>

            <!-- Backup Codes Step -->
            <div v-if="step === 'backup'" class="space-y-6">
              <div class="text-center">
                <div class="text-5xl mb-4"><Icon name="mdi:shield-lock" /></div>
                <h3 class="text-xl font-bold text-gray-900 dark:text-white mb-2">
                  2FA Successfully Enabled!
                </h3>
                <p class="text-gray-600 dark:text-gray-400">
                  Save these backup codes in a secure location. You can use them to access your account if you lose your authenticator device.
                </p>
              </div>

              <!-- Backup Codes -->
              <div class="bg-gray-100 dark:bg-gray-700 rounded-lg p-4">
                <div class="grid grid-cols-2 gap-2">
                  <code v-for="code in twoFactorStore.setupData?.backupCodes" :key="code" class="font-mono text-sm">
                    {{ code }}
                  </code>
                </div>
              </div>

              <!-- Actions -->
              <div class="flex space-x-3">
                <button
                  @click="downloadBackupCodes"
                  class="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <Icon name="mdi:inbox" /> Download
                </button>
                <button
                  @click="copyBackupCodes"
                  class="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <Icon name="mdi:clipboard" /> Copy
                </button>
              </div>

              <button
                @click="finish"
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
import { ref, computed, watch, nextTick } from 'vue'
import { useTwoFactorStore } from '@/stores/twoFactor'
import { useUIStore } from '@/stores/ui'
// QRCode library not needed - backend provides the QR code as base64 image

// Props
const props = defineProps<{
  isOpen: boolean
}>()

// Emits
const emit = defineEmits<{
  close: []
  complete: []
}>()

// Stores
const twoFactorStore = useTwoFactorStore()
const uiStore = useUIStore()

// State
const step = ref<'password' | 'setup' | 'verify' | 'backup'>('password')
const password = ref('')
const qrCanvas = ref<HTMLCanvasElement>()
const verificationCode = ref(['', '', '', '', '', ''])
const codeInputs = ref<any[]>([])
const errorMessage = ref('')

// Computed
const isCodeComplete = computed(() => 
  verificationCode.value.every(digit => digit !== '')
)

// Watch for modal open
watch(() => props.isOpen, async (newVal) => {
  if (newVal) {
    resetModal()
  }
})

// Watch for step changes to display QR code
watch(step, async (newStep) => {
  if (newStep === 'setup') {
    await nextTick()
    // QR code is already generated by backend as a base64 image
    // No need to generate it client-side
  }
})

// Methods
const resetModal = () => {
  step.value = 'password'
  password.value = ''
  verificationCode.value = ['', '', '', '', '', '']
  errorMessage.value = ''
  twoFactorStore.clearData()
}

const getStepTitle = () => {
  switch (step.value) {
    case 'password':
      return 'Enable Two-Factor Authentication'
    case 'setup':
      return 'Scan QR Code'
    case 'verify':
      return 'Verify Setup'
    case 'backup':
      return 'Backup Codes'
    default:
      return 'Two-Factor Authentication'
  }
}

const startSetup = async () => {
  if (!password.value) {
    errorMessage.value = 'Password is required'
    return
  }

  errorMessage.value = ''
  const result = await twoFactorStore.startSetup(password.value)
  
  // Debug: Log the setup data to see what we're getting
  import.meta.env.DEV && console.log('2FA Setup Data:', twoFactorStore.setupData)
  import.meta.env.DEV && console.log('QR Code data URI length:', twoFactorStore.setupData?.qrCode?.length)
  import.meta.env.DEV && console.log('Secret:', twoFactorStore.setupData?.secret)
  
  if (result.success) {
    step.value = 'setup'
    password.value = '' // Clear password for security
  } else {
    errorMessage.value = result.error || 'Failed to start 2FA setup'
  }
}

// Remove or comment out generateQRCode function as it's not needed
// The backend already provides a base64-encoded QR code image

const handleCodeInput = (index: number) => {
  const value = verificationCode.value[index]
  
  // Only allow numeric input
  if (value && !/^\d$/.test(value)) {
    verificationCode.value[index] = ''
    return
  }
  
  // Move to next input if value entered
  if (value && index < 5) {
    codeInputs.value[index + 1]?.focus()
  }
}

const handleBackspace = (index: number) => {
  if (!verificationCode.value[index] && index > 0) {
    codeInputs.value[index - 1]?.focus()
  }
}

const handlePaste = (event: ClipboardEvent) => {
  event.preventDefault()
  const pastedData = event.clipboardData?.getData('text')
  
  if (pastedData && /^\d{6}$/.test(pastedData)) {
    // If exactly 6 digits pasted, fill all inputs
    pastedData.split('').forEach((digit, index) => {
      verificationCode.value[index] = digit
    })
    // Focus last input
    codeInputs.value[5]?.focus()
  }
}

const copySecret = () => {
  if (twoFactorStore.setupData?.secret) {
    navigator.clipboard.writeText(twoFactorStore.setupData.secret)
    uiStore.showSuccess('Copied', 'Secret key copied to clipboard')
  }
}

const verifyCode = async () => {
  if (!isCodeComplete.value) return
  
  errorMessage.value = ''
  const code = verificationCode.value.join('')
  
  const result = await twoFactorStore.completeSetup(code)
  
  if (result.success) {
    step.value = 'backup'
  } else {
    errorMessage.value = result.error || 'Invalid verification code'
    // Clear code inputs on error
    verificationCode.value = ['', '', '', '', '', '']
    codeInputs.value[0]?.focus()
  }
}

const downloadBackupCodes = () => {
  if (twoFactorStore.setupData?.backupCodes) {
    twoFactorStore.downloadBackupCodes(twoFactorStore.setupData.backupCodes)
  }
}

const copyBackupCodes = () => {
  if (twoFactorStore.setupData?.backupCodes) {
    const content = twoFactorStore.setupData.backupCodes.join('\n')
    navigator.clipboard.writeText(content)
    uiStore.showSuccess('Copied', 'Backup codes copied to clipboard')
  }
}

const finish = () => {
  emit('complete')
  handleClose()
}

const handleClose = () => {
  // Clear sensitive data
  twoFactorStore.clearData()
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
