<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import { authApi } from '@/services/api/auth'
import { useI18n } from '@/composables/useI18n'
import AuthShell from '@/components/auth/AuthShell.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// Multi-step flow
// recovery-key → new-password → success  (existing recovery-key path)
// email-reset → email-sent                 (new email path)
// 2026-05-10 — Default to email-reset (most users don't have recovery keys
// handy a year after registration). Recovery-key remains accessible via the
// "Use recovery key" link on the email-reset view.
// §FESUITE: Settings opens this at the recovery-key step for a signed-in person (?recovery=1)
const step = ref<'recovery-key' | 'new-password' | 'success' | 'email-reset' | 'email-sent'>(route.query.recovery === '1' ? 'recovery-key' : 'email-reset')

// Step 1 state: recovery key verification
const email = ref('')
const recoveryKey = ref('')
const emailError = ref('')
const recoveryKeyError = ref('')
const isSubmitting = ref(false)
const error = ref<string | null>(null)

// Step 2 state: set new password
const tempToken = ref<string | null>(null)
const newPassword = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const passwordError = ref('')

// Validation
function validateRecoveryForm(): boolean {
  let valid = true
  emailError.value = ''
  recoveryKeyError.value = ''
  error.value = null

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!email.value) {
    emailError.value = 'Email is required'
    valid = false
  } else if (!emailRegex.test(email.value)) {
    emailError.value = 'Please enter a valid email'
    valid = false
  }

  if (!recoveryKey.value) {
    recoveryKeyError.value = 'Recovery key is required'
    valid = false
  } else if (!/^avrec-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}$/i.test(recoveryKey.value.trim())) {
    // §FESUITE: the server issues avrec-xxxxxxxx-xxxxxxxx-xxxxxxxx (security.generate_recovery_keys); this check
    // demanded "RECOV-", a form nothing ever issued, so every recovery through the page was refused before it left
    recoveryKeyError.value = 'A recovery key looks like avrec-1a2b3c4d-5e6f7a8b-9c0d1e2f'
    valid = false
  }

  return valid
}

function validatePasswordForm(): boolean {
  passwordError.value = ''
  error.value = null

  if (!newPassword.value || newPassword.value.length < 8) {
    passwordError.value = 'Password must be at least 8 characters'
    return false
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = 'Passwords do not match'
    return false
  }
  return true
}

// Step 1: Submit recovery key to POST /auth/recover-account
async function handleRecoverySubmit() {
  if (!validateRecoveryForm()) return

  isSubmitting.value = true
  error.value = null

  try {
    const response = await apiClient.post('/auth/recover-account', {
      email: email.value.trim(),
      recovery_key: recoveryKey.value.trim().toLowerCase()
    })

    // Backend returns a temporary access_token valid for 5 minutes
    tempToken.value = response.data.access_token
    step.value = 'new-password'
  } catch (err: any) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      error.value = detail
    } else if (err.response?.status === 400) {
      error.value = 'Invalid email or recovery key. Please check and try again.'
    } else if (err.response?.status === 404) {
      error.value = 'Account not found. Please verify your email address.'
    } else {
      error.value = err.message || 'Recovery failed. Please try again.'
    }
  } finally {
    isSubmitting.value = false
  }
}

// Step 2: Set new password via POST /auth/set-new-password
async function handlePasswordSubmit() {
  if (!validatePasswordForm()) return

  isSubmitting.value = true
  error.value = null

  try {
    await apiClient.post('/auth/set-new-password', {
      new_password: newPassword.value
    }, {
      headers: {
        'Authorization': `Bearer ${tempToken.value}`
      }
    })

    step.value = 'success'
    // A new password ends every session the old one opened, this console's included: end it here so "sign in" is a
    // sign-in, not a bounce through a refused token.
    if (authStore.token) await authStore.endLocalSession('the password changed')
  } catch (err: any) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      error.value = detail
    } else if (err.response?.status === 401) {
      error.value = 'Recovery session expired. Please start over.'
      step.value = 'recovery-key'
      tempToken.value = null
    } else {
      error.value = err.message || 'Failed to set new password. Please try again.'
    }
  } finally {
    isSubmitting.value = false
  }
}

function goToLogin() {
  router.push('/login')
}

// ---------- Email reset path ----------
const emailResetAddress = ref('')
const emailResetError = ref('')
const emailResetSubmitting = ref(false)

async function handleEmailResetSubmit() {
  emailResetError.value = ''
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailResetAddress.value || !emailRegex.test(emailResetAddress.value)) {
    emailResetError.value = 'Please enter a valid email address'
    return
  }
  emailResetSubmitting.value = true
  try {
    await authApi.requestPasswordReset(emailResetAddress.value)
    // Backend always returns 200 — move to confirmation regardless
    step.value = 'email-sent'
  } catch (err: any) {
    // §FESUITE (lifecycle 85): this said "TRANSMISSION DISPATCHED" for a request that got no answer and for the
    // registry's own limit (3 a minute). The registry answers every address alike (200: no account enumeration), so a
    // failure tells nothing about the account; it only means nothing was sent, which is what the person needs to know.
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    if (status === 429) emailResetError.value = 'Too many reset requests from here. Wait a minute, then try again.'
    else if (!status || status >= 500) emailResetError.value = 'The reset link could not be sent: the registry did not answer. Try again in a moment.'
    else emailResetError.value = typeof detail === 'string' && detail ? detail : 'The reset link could not be sent. Check the address and try again.'
  } finally {
    emailResetSubmitting.value = false
  }
}
</script>

<template>
  <AuthShell tagline="RECOVERY PROTOCOL" status="RECOVERY PROTOCOL ACTIVE">
    <NeuralCard variant="elevated" accent="primary" class="nc-auth-card">

      <!-- ============ STEP 1: Recovery Key ============ -->
      <template v-if="step === 'recovery-key'">
        <div class="nc-auth-header">
          <h2 class="nc-auth-title">{{ t('forgotPasswordView.identityTitle') }}</h2>
          <p class="nc-auth-description">
            Enter your email and one of the recovery keys you received during registration.
          </p>
        </div>

        <form @submit.prevent="handleRecoverySubmit" class="nc-auth-form">
          <!-- Email -->
          <div class="nc-form-group">
            <label class="nc-form-label">EMAIL ADDRESS</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="mail" :size="18" class="nc-input-icon" />
              <input
                v-model="email"
                type="email"
                class="nc-input nc-input-with-icon"
                placeholder="agent@example.com"
                required
                @input="emailError = ''; error = null"
              />
            </div>
            <p v-if="emailError" class="nc-field-error">{{ emailError }}</p>
          </div>

          <!-- Recovery Key -->
          <div class="nc-form-group">
            <label class="nc-form-label">RECOVERY KEY</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="key" :size="18" class="nc-input-icon" />
              <input
                v-model="recoveryKey"
                type="text"
                class="nc-input nc-input-with-icon"
                data-testid="fp-recovery-key"
                autocomplete="off"
                spellcheck="false"
                aria-label="Recovery key"
                placeholder="avrec-xxxxxxxx-xxxxxxxx-xxxxxxxx"
                required
                @input="recoveryKeyError = ''; error = null"
              />
            </div>
            <p v-if="recoveryKeyError" class="nc-field-error">{{ recoveryKeyError }}</p>
          </div>

          <!-- Error Message -->
          <div v-if="error" class="nc-alert nc-alert-danger">
            <NeuralIcon name="alert-triangle" :size="16" />
            <span>{{ error }}</span>
          </div>

          <!-- Info Box -->
          <div class="nc-info-box">
            <NeuralIcon name="info" :size="16" />
            <div>
              <p>Recovery keys were provided when you registered your account. If you've lost your recovery keys, please contact support.</p>
            </div>
          </div>

          <!-- Submit -->
          <button
            type="submit"
            class="nc-btn nc-btn-primary nc-btn-full"
            :disabled="isSubmitting"
          >
            <span v-if="!isSubmitting" class="nc-btn-content">
              <NeuralIcon name="shield" :size="18" />
              <span>VERIFY RECOVERY KEY</span>
            </span>
            <span v-else class="nc-btn-content">
              <NeuralIcon name="loading" :size="18" class="nc-icon-spin" />
              <span>VERIFYING...</span>
            </span>
          </button>
        </form>

        <div class="nc-auth-footer">
          <p class="nc-auth-footer-text">
            Remember your password?
            <RouterLink to="/login" class="nc-link">Return to login</RouterLink>
          </p>
          <p class="nc-auth-footer-text" style="margin-top:0.75rem;">
            Lost your recovery key?
            <button class="nc-link-btn" @click="step = 'email-reset'">← Back to email reset</button>
          </p>
        </div>
      </template>

      <!-- ============ STEP 2: New Password ============ -->
      <template v-if="step === 'new-password'">
        <div class="nc-auth-header">
          <h2 class="nc-auth-title">{{ t('forgotPasswordView.setNewTitle') }}</h2>
          <p class="nc-auth-description">
            Recovery key verified. Enter your new password below. This session expires in 5 minutes.
          </p>
        </div>

        <form @submit.prevent="handlePasswordSubmit" class="nc-auth-form">
          <!-- New Password -->
          <div class="nc-form-group">
            <label class="nc-form-label">NEW PASSWORD</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="newPassword"
                :type="showPassword ? 'text' : 'password'"
                class="nc-input nc-input-with-icon"
                placeholder="••••••••"
                required
                @input="passwordError = ''; error = null"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="nc-input-toggle"
                :aria-label="showPassword ? 'Hide password' : 'Show password'"
              >
                <NeuralIcon :name="showPassword ? 'hide' : 'view'" :size="18" />
              </button>
            </div>
          </div>

          <!-- Confirm Password -->
          <div class="nc-form-group">
            <label class="nc-form-label">CONFIRM PASSWORD</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="confirmPassword"
                :type="showPassword ? 'text' : 'password'"
                class="nc-input nc-input-with-icon"
                placeholder="••••••••"
                required
                @input="passwordError = ''; error = null"
              />
            </div>
            <p v-if="passwordError" class="nc-field-error">{{ passwordError }}</p>
          </div>

          <!-- Error Message -->
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
              <NeuralIcon name="lock" :size="18" />
              <span>SET NEW PASSWORD</span>
            </span>
            <span v-else class="nc-btn-content">
              <NeuralIcon name="loading" :size="18" class="nc-icon-spin" />
              <span>UPDATING...</span>
            </span>
          </button>
        </form>
      </template>

      <!-- ============ STEP: Email Reset ============ -->
      <template v-if="step === 'email-reset'">
        <div class="nc-auth-header">
          <h2 class="nc-auth-title">{{ t('forgotPasswordView.resetViaEmail') }}</h2>
          <p class="nc-auth-description">
            Enter your registered email address. If an account exists, we'll send a reset link valid for 1 hour.
          </p>
        </div>

        <form @submit.prevent="handleEmailResetSubmit" class="nc-auth-form">
          <div class="nc-form-group">
            <label class="nc-form-label">EMAIL ADDRESS</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="mail" :size="18" class="nc-input-icon" />
              <input
                v-model="emailResetAddress"
                type="email"
                class="nc-input nc-input-with-icon"
                placeholder="agent@example.com"
                required
                @input="emailResetError = ''"
              />
            </div>
            <p v-if="emailResetError" class="nc-field-error">{{ emailResetError }}</p>
          </div>

          <button
            type="submit"
            class="nc-btn nc-btn-primary nc-btn-full"
            :disabled="emailResetSubmitting"
          >
            <span v-if="!emailResetSubmitting" class="nc-btn-content">
              <NeuralIcon name="mail" :size="18" />
              <span>SEND RESET LINK</span>
            </span>
            <span v-else class="nc-btn-content">
              <NeuralIcon name="loading" :size="18" class="nc-icon-spin" />
              <span>SENDING...</span>
            </span>
          </button>
        </form>

        <div class="nc-auth-footer">
          <p class="nc-auth-footer-text">
            <button class="nc-link-btn" @click="step = 'recovery-key'">Use recovery key instead</button>
          </p>
        </div>
      </template>

      <!-- ============ STEP: Email Sent ============ -->
      <template v-if="step === 'email-sent'">
        <div class="nc-auth-header">
          <div class="nc-success-icon">
            <NeuralIcon name="mail" :size="48" color="primary" />
          </div>
          <h2 class="nc-auth-title">{{ t('forgotPasswordView.dispatched') }}</h2>
          <p class="nc-auth-description">
            If <strong>{{ emailResetAddress }}</strong> is registered and verified, a reset link has been sent. Check your inbox — the link expires in 1 hour.
          </p>
        </div>
        <div class="nc-auth-form">
          <button @click="goToLogin" class="nc-btn nc-btn-primary nc-btn-full">
            <span class="nc-btn-content">
              <NeuralIcon name="login" :size="18" />
              <span>RETURN TO LOGIN</span>
            </span>
          </button>
        </div>
      </template>

      <!-- ============ STEP 3: Success ============ -->
      <template v-if="step === 'success'">
        <div class="nc-auth-header">
          <div class="nc-success-icon">
            <NeuralIcon name="check-circle" :size="48" color="success" />
          </div>
          <h2 class="nc-auth-title">{{ t('forgotPasswordView.updated') }}</h2>
          <p class="nc-auth-description">
            Your password has been successfully reset. You can now log in with your new password.
          </p>
        </div>

        <div class="nc-auth-form">
          <button
            @click="goToLogin"
            class="nc-btn nc-btn-primary nc-btn-full"
          >
            <span class="nc-btn-content">
              <NeuralIcon name="login" :size="18" />
              <span>RETURN TO LOGIN</span>
            </span>
          </button>
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
