<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import AuthShell from '@/components/auth/AuthShell.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// Token from URL (hash routing — Vue Router parses query from hash URL)
const token = computed(() => route.query.token as string)

// Form state
const newPassword = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const isSubmitting = ref(false)
const submitted = ref(false)
const error = ref<string | null>(null)
const passwordError = ref('')

onMounted(() => {
  if (!token.value) {
    router.push('/forgot-password')
  }
})

// The "redirecting to login" timer belongs to this page: left before it fires (the button, a sign-in begun at once),
// it would push /login over the navigation a sign-in started and leave the person signed in on the login form.
let toLogin: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(toLogin))

// Password strength indicators
const hasLength  = computed(() => newPassword.value.length >= 12)
const hasUpper   = computed(() => /[A-Z]/.test(newPassword.value))
const hasLower   = computed(() => /[a-z]/.test(newPassword.value))
const hasDigit   = computed(() => /\d/.test(newPassword.value))
const hasSpecial = computed(() => /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(newPassword.value))

function validate(): boolean {
  passwordError.value = ''
  error.value = null

  if (!newPassword.value) {
    passwordError.value = 'Password is required'
    return false
  }
  if (newPassword.value.length < 12) {
    passwordError.value = 'Password must be at least 12 characters'
    return false
  }
  if (!hasUpper.value || !hasLower.value || !hasDigit.value || !hasSpecial.value) {
    passwordError.value = 'Password must contain uppercase, lowercase, digit, and special character'
    return false
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = 'Passwords do not match'
    return false
  }
  return true
}

async function handleSubmit() {
  if (!validate()) return

  isSubmitting.value = true
  try {
    const success = await authStore.resetPassword(token.value, newPassword.value)
    if (success) {
      submitted.value = true
      toLogin = setTimeout(() => router.push('/login'), 3000)
    } else {
      error.value = authStore.error || 'Reset failed. The link may have expired.'
    }
  } catch (err: any) {
    error.value = err.response?.data?.detail || 'Reset failed. Please request a new link.'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <AuthShell :tagline="t('resetPasswordView.subtitle')" status="RESET PROTOCOL ACTIVE">
    <NeuralCard variant="elevated" accent="primary" class="nc-auth-card">

      <!-- ============ SUCCESS ============ -->
      <template v-if="submitted">
        <div class="nc-auth-header">
          <div class="nc-success-icon">
            <NeuralIcon name="check-circle" :size="48" color="success" />
          </div>
          <h2 class="nc-auth-title">{{ t('resetPasswordView.updatedTitle') }}</h2>
          <p class="nc-auth-description">{{ t('resetPasswordView.updatedDesc') }}</p>
        </div>
        <div class="nc-auth-form">
          <button @click="router.push('/login')" class="nc-btn nc-btn-primary nc-btn-full">
            <span class="nc-btn-content">
              <NeuralIcon name="login" :size="18" />
              <span>{{ t('resetPasswordView.returnToLogin') }}</span>
            </span>
          </button>
        </div>
      </template>

      <!-- ============ FORM ============ -->
      <template v-else>
        <div class="nc-auth-header">
          <h2 class="nc-auth-title">{{ t('resetPasswordView.setNewTitle') }}</h2>
          <p class="nc-auth-description">{{ t('resetPasswordView.setNewDesc') }}</p>
        </div>

        <form @submit.prevent="handleSubmit" class="nc-auth-form">
          <!-- New Password -->
          <div class="nc-form-group">
            <label class="nc-form-label">{{ t('resetPasswordView.newPasswordLabel') }}</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="newPassword"
                :type="showPassword ? 'text' : 'password'"
                class="nc-input nc-input-with-icon"
                placeholder="••••••••"
                required
                autocomplete="new-password"
                @input="passwordError = ''; error = null"
              />
              <button type="button" @click="showPassword = !showPassword" class="nc-input-toggle" :aria-label="showPassword ? 'Hide password' : 'Show password'">
                <NeuralIcon :name="showPassword ? 'hide' : 'view'" :size="18" />
              </button>
            </div>

            <!-- Strength indicators -->
            <div class="nc-strength-grid">
              <span :class="['nc-req', hasLength  ? 'ok' : '']">≥12 chars</span>
              <span :class="['nc-req', hasUpper   ? 'ok' : '']">Uppercase</span>
              <span :class="['nc-req', hasLower   ? 'ok' : '']">Lowercase</span>
              <span :class="['nc-req', hasDigit   ? 'ok' : '']">Digit</span>
              <span :class="['nc-req', hasSpecial ? 'ok' : '']">Special</span>
            </div>
          </div>

          <!-- Confirm Password -->
          <div class="nc-form-group">
            <label class="nc-form-label">CONFIRM ACCESS KEY</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="confirmPassword"
                :type="showPassword ? 'text' : 'password'"
                class="nc-input nc-input-with-icon"
                placeholder="••••••••"
                required
                autocomplete="new-password"
                @input="passwordError = ''; error = null"
              />
            </div>
            <p v-if="passwordError" class="nc-field-error">{{ passwordError }}</p>
          </div>

          <!-- Error alert -->
          <div v-if="error" class="nc-alert nc-alert-danger">
            <NeuralIcon name="alert-triangle" :size="16" />
            <span>{{ error }}</span>
          </div>

          <!-- Submit -->
          <button
            type="submit"
            class="nc-btn nc-btn-primary nc-btn-full"
            :disabled="isSubmitting"
          >
            <span v-if="!isSubmitting" class="nc-btn-content">
              <NeuralIcon name="shield" :size="18" />
              <span>COMMIT NEW PASSWORD</span>
            </span>
            <span v-else class="nc-btn-content">
              <NeuralIcon name="loading" :size="18" class="nc-icon-spin" />
              <span>UPDATING...</span>
            </span>
          </button>
        </form>

        <div class="nc-auth-footer">
          <p class="nc-auth-footer-text">
            Link expired?
            <RouterLink to="/forgot-password" class="nc-link">Request a new one</RouterLink>
          </p>
        </div>
      </template>

    </NeuralCard>
  </AuthShell>
</template>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/auth-shell.css';
</style>
