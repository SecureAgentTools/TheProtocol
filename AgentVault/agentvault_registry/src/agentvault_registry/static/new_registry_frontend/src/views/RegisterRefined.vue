<!-- RegisterRefined.vue - Neural Command Registration -->
<template>
  <AuthShell :tagline="t('login.logoTagline', 'NEURAL COMMAND CENTER')" :status="t('registerView.systemOnline', 'SYSTEM ONLINE')" :max-width="480">
    <!-- Registration Card -->
    <NeuralCard variant="elevated" accent="primary" class="nc-auth-card">

      <!-- ══ CONFIRMATION PANEL (shown after successful registration) ══ -->
      <template v-if="registrationComplete">
        <div class="nc-confirm-panel">
          <!-- Icon -->
          <div class="nc-confirm-icon" :class="accountReady || emailDelivered ? 'nc-confirm-icon--ok' : 'nc-confirm-icon--warn'">
            <NeuralIcon :name="accountReady ? 'check-circle' : emailDelivered ? 'mail' : 'alert-triangle'" :size="32" />
          </div>

          <h2 class="nc-confirm-title" data-testid="register-confirm-title" :data-state="accountReady ? 'ready' : emailDelivered ? 'mail-sent' : 'mail-failed'">{{ !accountReady && emailDelivered ? t('registerView.transmissionSent', 'TRANSMISSION SENT') : t('registerView.accountCreated', 'ACCOUNT CREATED') }}</h2>

          <!-- §FESUITE: a frame that needs no verification mail made the account ready at once; telling the person to
               wait for a mail that will never come (and offering to resend it) was the defect. -->
          <p v-if="accountReady" class="nc-confirm-body">
            {{ t('registerView.accountReady', 'Your account is ready to use. Sign in to continue.') }}
          </p>
          <p v-else-if="emailDelivered" class="nc-confirm-body">
            {{ t('registerView.verificationDispatched', 'Verification link dispatched to:') }}
          </p>
          <p v-else class="nc-confirm-body nc-confirm-body--warn">
            {{ t('registerView.emailDeliveryFailed', 'Account created but email delivery failed. Use the button below to retry:') }}
          </p>

          <div class="nc-confirm-email">
            <NeuralIcon name="at-sign" :size="14" />
            <span>{{ registeredEmail }}</span>
          </div>

          <!-- Resend feedback -->
          <div v-if="!accountReady && resendSuccess" class="nc-alert nc-alert-success nc-confirm-feedback">
            <NeuralIcon name="check-circle" :size="16" />
            <span>{{ t('registerView.resendSuccess', 'Verification email resent successfully.') }}</span>
          </div>
          <div v-if="!accountReady && resendError" class="nc-alert nc-alert-error nc-confirm-feedback">
            <NeuralIcon name="alert-triangle" :size="16" />
            <span>{{ resendError }}</span>
          </div>

          <!-- Sign in (the account is ready) -->
          <router-link
            v-if="accountReady"
            :to="{ path: '/login', query: { email: registeredEmail } }"
            class="nc-btn nc-btn-primary nc-btn-full"
            data-testid="register-sign-in"
          >
            <NeuralIcon name="log-in" :size="16" />
            <span>{{ t('registerView.signInNow', 'SIGN IN') }}</span>
          </router-link>

          <!-- Resend button -->
          <button
            v-else
            class="nc-btn nc-btn-ghost nc-btn-full nc-resend-btn"
            :disabled="resendCooldown > 0 || resendLoading"
            @click="handleResend"
          >
            <NeuralIcon v-if="resendLoading" name="loading" :size="16" class="nc-icon-spin" />
            <NeuralIcon v-else name="refresh-cw" :size="16" />
            <span v-if="resendLoading">{{ t('registerView.resendSending', 'SENDING...') }}</span>
            <span v-else-if="resendCooldown > 0">{{ tp('registerView.resendCooldown', 'RESEND AVAILABLE IN {n}s', { n: resendCooldown }) }}</span>
            <span v-else>{{ t('registerView.resendVerification', 'RESEND VERIFICATION EMAIL') }}</span>
          </button>

          <!-- Recovery Keys -->
          <div v-if="recoveryKeys.length > 0" class="nc-recovery-block">
            <div class="nc-recovery-header">
              <NeuralIcon name="shield" :size="14" />
              <span>{{ t('registerView.recoveryKeysHeader', 'RECOVERY KEYS — SAVE THESE NOW') }}</span>
            </div>
            <p class="nc-recovery-warn">{{ t('registerView.recoveryKeysWarn', 'These are shown ONCE and cannot be recovered. Store them offline.') }}</p>
            <div class="nc-recovery-keys">
              <div v-for="(key, i) in recoveryKeys" :key="i" class="nc-recovery-key">
                <span class="nc-recovery-index">{{ i + 1 }}</span>
                <span class="nc-recovery-value">{{ key }}</span>
              </div>
            </div>
            <!-- RR1 (audit 2026-05-07): copy + download — was: highlight-and-copy by hand -->
            <div class="nc-recovery-actions">
              <button type="button" class="nc-recovery-btn" @click="copyRecoveryKeys">
                {{ recoveryCopied ? '✓ ' + t('registerView.copied', 'COPIED') : '⧉ ' + t('registerView.copyAll', 'COPY ALL') }}
              </button>
              <button type="button" class="nc-recovery-btn" @click="downloadRecoveryKeys">
                ⬇ {{ t('registerView.downloadTxt', 'DOWNLOAD .TXT') }}
              </button>
            </div>
          </div>

          <!-- Footer -->
          <div v-if="!accountReady" class="nc-auth-footer">
            <p class="nc-footer-text">
              {{ t('registerView.alreadyVerified', 'Already verified?') }}
              <router-link to="/login" class="nc-link">{{ t('registerView.accessSystem', 'Access system') }}</router-link>
            </p>
          </div>
        </div>
      </template>

      <!-- ══ REGISTRATION FORM (default) ══ -->
      <template v-else>
        <div class="nc-auth-header">
          <h2 class="nc-auth-title">{{ t('registerView.title', 'INITIALIZE AGENT ACCOUNT') }}</h2>
          <p class="nc-auth-description">{{ t('registerView.subtitle', 'Join the sovereign agent network') }}</p>
        </div>

        <form @submit.prevent="handleRegister" class="nc-form">
          <!-- Name Input -->
          <div class="nc-input-group">
            <label class="nc-label">{{ t('registerView.identifierName', 'IDENTIFIER NAME') }}</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="user" :size="18" class="nc-input-icon" />
              <input
                v-model="name"
                type="text"
                :placeholder="t('registerView.identifierNamePlaceholder', 'Agent Smith')"
                required
                class="nc-input"
                :class="{ 'nc-input-error': errors.name }"
                @blur="validateName"
              />
            </div>
            <span v-if="errors.name" class="nc-error">{{ errors.name }}</span>
          </div>

          <!-- Email Input -->
          <div class="nc-input-group">
            <label class="nc-label">{{ t('registerView.networkAddress', 'NETWORK ADDRESS') }}</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="at-sign" :size="18" class="nc-input-icon" />
              <input
                v-model="email"
                type="email"
                :placeholder="t('registerView.networkAddressPlaceholder', 'you@example.com')"
                required
                class="nc-input"
                :class="{ 'nc-input-error': errors.email }"
                @blur="validateEmail"
              />
            </div>
            <span v-if="errors.email" class="nc-error">{{ errors.email }}</span>
          </div>

          <!-- Password Input -->
          <div class="nc-input-group">
            <label class="nc-label">{{ t('registerView.accessKey', 'ACCESS KEY') }}</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="••••••••"
                required
                class="nc-input"
                :class="{ 'nc-input-error': errors.password }"
                @blur="validatePassword"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="nc-input-toggle"
                :aria-label="showPassword ? 'Hide access key' : 'Show access key'"
              >
                <NeuralIcon :name="showPassword ? 'hide' : 'view'" :size="18" />
              </button>
            </div>
            <span v-if="errors.password" class="nc-error">{{ errors.password }}</span>

            <!-- Password Requirements -->
            <div class="nc-requirements">
              <div :class="['nc-requirement', { 'nc-requirement-met': password.length >= 12 }]">
                <div class="nc-requirement-dot"></div>
                <span>{{ t('registerView.reqMinChars', 'Minimum 12 characters') }}</span>
              </div>
              <div :class="['nc-requirement', { 'nc-requirement-met': /[A-Z]/.test(password) }]">
                <div class="nc-requirement-dot"></div>
                <span>{{ t('registerView.reqUpper', 'One uppercase letter') }}</span>
              </div>
              <div :class="['nc-requirement', { 'nc-requirement-met': /[a-z]/.test(password) }]">
                <div class="nc-requirement-dot"></div>
                <span>{{ t('registerView.reqLower', 'One lowercase letter') }}</span>
              </div>
              <div :class="['nc-requirement', { 'nc-requirement-met': /\d/.test(password) }]">
                <div class="nc-requirement-dot"></div>
                <span>{{ t('registerView.reqNumber', 'One number') }}</span>
              </div>
              <div :class="['nc-requirement', { 'nc-requirement-met': /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password) }]">
                <div class="nc-requirement-dot"></div>
                <span>{{ t('registerView.reqSpecial', 'One special character') }}</span>
              </div>
            </div>
          </div>

          <!-- Confirm Password Input -->
          <div class="nc-input-group">
            <label class="nc-label">{{ t('registerView.confirmAccessKey', 'CONFIRM ACCESS KEY') }}</label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
              <input
                v-model="confirmPassword"
                :type="showConfirmPassword ? 'text' : 'password'"
                placeholder="••••••••"
                required
                class="nc-input"
                :class="{ 'nc-input-error': errors.confirmPassword }"
                @blur="validateConfirmPassword"
              />
              <button
                type="button"
                @click="showConfirmPassword = !showConfirmPassword"
                class="nc-input-toggle"
                :aria-label="showConfirmPassword ? 'Hide access key' : 'Show access key'"
              >
                <NeuralIcon :name="showConfirmPassword ? 'hide' : 'view'" :size="18" />
              </button>
            </div>
            <span v-if="errors.confirmPassword" class="nc-error">{{ errors.confirmPassword }}</span>
          </div>

          <!-- Beta Invite Code: shown where registration-config says one is required, or when the read failed (then
               marked "if you have one": the registry still says if one is required), or when a link carries a code -->
          <div v-if="showInviteField" class="nc-input-group" data-testid="register-invite">
            <label class="nc-label">
              {{ t('registerView.betaInviteCode', 'BETA INVITE CODE') }}
              <span class="nc-label-optional" data-testid="register-invite-rule">{{ inviteRule === 'required' ? t('registerView.betaInviteRequired', '(required for beta access)') : t('registerView.betaInviteIfAny', '(if you have one)') }}</span>
            </label>
            <div class="nc-input-wrapper">
              <NeuralIcon name="key" :size="18" class="nc-input-icon" />
              <input
                v-model="inviteCode"
                type="text"
                placeholder="TP-XXXX-XXXX-XXXX-XXXX"
                class="nc-input nc-input-with-icon"
                :class="{ 'nc-input-error': errors.inviteCode, 'nc-input-prefilled': inviteCodeFromUrl }"
                :readonly="inviteCodeFromUrl"
                @input="validateInviteCode"
                autocomplete="off"
                spellcheck="false"
              />
            </div>
            <span v-if="errors.inviteCode" class="nc-error">{{ errors.inviteCode }}</span>
            <span v-if="inviteCodeFromUrl" class="nc-hint">{{ t('registerView.inviteAppliedFromLink', 'Invite code applied from your link') }}</span>
          </div>

          <!-- Terms Acceptance -->
          <div class="nc-checkbox-group">
            <input
              id="accept-terms"
              v-model="acceptTerms"
              type="checkbox"
              required
              class="nc-checkbox"
              @change="validateTerms"
            />
            <label for="accept-terms" class="nc-checkbox-label">
              {{ t('registerView.acceptIntro', 'I accept the') }}
              <a href="#/legal/terms" target="_blank" rel="noopener noreferrer" class="nc-link">{{ t('registerView.protocolTerms', 'Protocol Terms') }}</a>
              {{ t('registerView.andText', 'and') }}
              <a href="#/legal/privacy" target="_blank" rel="noopener noreferrer" class="nc-link">{{ t('registerView.privacyMatrix', 'Privacy Matrix') }}</a>
            </label>
          </div>
          <span v-if="errors.acceptTerms" class="nc-error">{{ errors.acceptTerms }}</span>

          <!-- §LEGALKIT: Privacy § 12 says the platform is for adults; the form now asks. -->
          <div class="nc-checkbox-group">
            <input id="confirm-age" v-model="confirmAge" type="checkbox" required class="nc-checkbox" />
            <label for="confirm-age" class="nc-checkbox-label">{{ t('registerView.confirmAge', 'I am 18 years of age or older') }}</label>
          </div>
          <span v-if="errors.confirmAge" class="nc-error">{{ errors.confirmAge }}</span>

          <!-- Error Message -->
          <div v-if="error" class="nc-alert nc-alert-error">
            <NeuralIcon name="alert-triangle" :size="18" />
            <span>{{ error }}</span>
          </div>

          <!-- Submit Button -->
          <button
            type="submit"
            :disabled="isSubmitting"
            class="nc-btn nc-btn-primary nc-btn-full"
          >
            <NeuralIcon v-if="!isSubmitting" name="user-plus" :size="20" />
            <NeuralIcon v-else name="loading" :size="20" class="nc-icon-spin" />
            <span>{{ isSubmitting ? t('registerView.submitting', 'INITIALIZING...') : t('registerView.createAccount', 'CREATE ACCOUNT') }}</span>
          </button>
        </form>

        <!-- Login Link -->
        <div class="nc-auth-footer">
          <p class="nc-footer-text">
            {{ t('registerView.alreadyInitialized', 'Already initialized?') }}
            <router-link to="/login" class="nc-link">
              {{ t('registerView.accessSystem', 'Access system') }}
            </router-link>
          </p>
        </div>
      </template><!-- end v-else registration form -->

    </NeuralCard>
  </AuthShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import AuthShell from '@/components/auth/AuthShell.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t, tp } = useI18n()

// ── Post-registration confirmation state ──────────────────────────────────
const registrationComplete = ref(false)
const registeredEmail = ref('')
const recoveryKeys = ref<string[]>([])
const emailDelivered = ref(true)       // false = backend sent "could not send" message
// The frame asks for no verification mail: the account is ready the moment it exists (registration-config, with the
// register answer's own words as the fallback when the config could not be read).
const verificationRequired = ref(true)
const accountReady = ref(false)
const resendLoading = ref(false)
const resendSuccess = ref(false)
const resendError = ref('')
const resendCooldown = ref(0)          // seconds remaining on cooldown
const COOLDOWN_SECONDS = 60
let cooldownTimer: ReturnType<typeof setInterval> | null = null

function startCooldown() {
  resendCooldown.value = COOLDOWN_SECONDS
  if (cooldownTimer) clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    resendCooldown.value--
    if (resendCooldown.value <= 0) {
      clearInterval(cooldownTimer!)
      cooldownTimer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
})

async function handleResend() {
  if (resendCooldown.value > 0 || resendLoading.value) return
  resendLoading.value = true
  resendSuccess.value = false
  resendError.value = ''
  try {
    await apiClient.post('/auth/resend-verification', { email: registeredEmail.value })
    resendSuccess.value = true
    emailDelivered.value = true
    startCooldown()
  } catch (err: any) {
    const status = err.response?.status
    if (status === 503) {
      resendError.value = 'Email delivery failed. Check your address or try again shortly.'
    } else {
      resendError.value = err.response?.data?.detail || 'Resend failed. Please try again.'
    }
  } finally {
    resendLoading.value = false
  }
}

// Form state
const name = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const acceptTerms = ref(false)
const confirmAge = ref(false)
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const inviteCode = ref('')
const inviteCodeFromUrl = ref(false)  // true if auto-filled from URL
// §FESUITE (V0578): the invite field follows what registration-config answered. It defaulted to shown and "(required for
// beta access)" (this line said "hidden until config fetched"), so every visitor saw "required" until the config answered
// and kept seeing it when the read failed, on frames that register without an invite. Unread: no field (a link's code is
// still shown); failed: the field, marked "if you have one".
const inviteRule = ref<'unread' | 'required' | 'open' | 'failed'>('unread')
const showInviteField = computed(() => inviteRule.value === 'required' || inviteRule.value === 'failed' || inviteCodeFromUrl.value)

// Validation state
const errors = ref({
  name: '',
  email: '',
  password: '',
  confirmPassword: '',
  acceptTerms: '',
  confirmAge: '',
  inviteCode: ''
})

// Fetch registration config + auto-fill invite code from URL
onMounted(async () => {
  // a link's code is applied at once, whatever the config read does (it waited for that read before)
  const invite = route.query.invite as string | undefined
  if (invite) {
    inviteCode.value = invite
    inviteCodeFromUrl.value = true
  }
  try {
    const resp = await fetch('/api/v1/auth/registration-config')
    if (!resp.ok) throw new Error(`registration-config answered ${resp.status}`)
    const cfg = await resp.json()
    // an absent switch reads as required, as before; only an explicit false opens registration
    inviteRule.value = (cfg?.beta_invite_required ?? true) ? 'required' : 'open'
    verificationRequired.value = cfg?.email_verification_required ?? true
  } catch {
    inviteRule.value = 'failed'
  }
})

// UI state
const isSubmitting = ref(false)
const submitError = ref('')
const error = computed(() => submitError.value || authStore.error)

// Validation functions
function validateName() {
  if (!name.value) {
    errors.value.name = 'Identifier required'
  } else if (name.value.length < 2) {
    errors.value.name = 'Minimum 2 characters'
  } else {
    errors.value.name = ''
  }
}

function validateEmail() {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!email.value) {
    errors.value.email = 'Network address required'
  } else if (!emailRegex.test(email.value)) {
    errors.value.email = 'Invalid address format'
  } else {
    errors.value.email = ''
  }
}

function validatePassword() {
  if (!password.value) {
    errors.value.password = 'Access key required'
  } else if (password.value.length < 12) {
    errors.value.password = 'Minimum 12 characters'
  } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{}|;:,.<>?])/.test(password.value)) {
    errors.value.password = 'Must include uppercase, lowercase, number and special character'
  } else {
    errors.value.password = ''
  }
}

function validateConfirmPassword() {
  if (!confirmPassword.value) {
    errors.value.confirmPassword = 'Confirmation required'
  } else if (confirmPassword.value !== password.value) {
    errors.value.confirmPassword = 'Keys do not match'
  } else {
    errors.value.confirmPassword = ''
  }
}

function validateTerms() {
  if (!confirmAge.value) {
    errors.value.confirmAge = t('registerView.confirmAgeRequired', 'Please confirm that you are 18 or older')
  } else {
    errors.value.confirmAge = ''
  }
  if (!acceptTerms.value) {
    errors.value.acceptTerms = 'Protocol acceptance required'
  } else {
    errors.value.acceptTerms = ''
  }
}

function validateInviteCode() {
  // No client-side validation — backend will reject invalid codes.
  // Just clear on change.
  errors.value.inviteCode = ''
}

function validateForm() {
  validateName()
  validateEmail()
  validatePassword()
  validateConfirmPassword()
  validateTerms()

  return !Object.values(errors.value).some(error => error !== '')
}

// RR1 (audit 2026-05-07): copy + download helpers for the "shown once"
// recovery keys. Replaces the previous manual highlight-and-copy UX.
const recoveryCopied = ref(false)
async function copyRecoveryKeys() {
  const text = recoveryKeys.value
    .map((k, i) => `${i + 1}. ${k}`)
    .join('\n')
  try {
    await navigator.clipboard.writeText(text)
    recoveryCopied.value = true
    setTimeout(() => { recoveryCopied.value = false }, 2500)
  } catch {
    // Clipboard API blocked in some contexts — fall back to a textarea trick.
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* nothing else to do */ }
    document.body.removeChild(ta)
    recoveryCopied.value = true
    setTimeout(() => { recoveryCopied.value = false }, 2500)
  }
}
function downloadRecoveryKeys() {
  const text =
    `THEPROTOCOL — Recovery Keys for ${registeredEmail.value}\n` +
    `Generated: ${new Date().toISOString()}\n` +
    `These keys can recover your account if you lose access. Store offline.\n\n` +
    recoveryKeys.value.map((k, i) => `${i + 1}. ${k}`).join('\n') +
    `\n`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeEmail = (registeredEmail.value || 'theprotocol').replace(/[^a-z0-9._-]/gi, '_')
  a.download = `${safeEmail}-recovery-keys.txt`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function handleRegister() {
  if (!validateForm()) return

  isSubmitting.value = true
  submitError.value = ''
  authStore.clearError()

  try {
    const response = await apiClient.post('/auth/register', {
      name: name.value,
      email: email.value,
      password: password.value,
      invite_code: inviteCode.value || undefined,
      tos_accepted: acceptTerms.value,   // consent record (server stamps the authoritative version)
      age_confirmed: confirmAge.value    // §LEGALKIT: recorded as document age18
    })

    const msg: string = response.data?.message || ''
    registeredEmail.value = email.value
    recoveryKeys.value = response.data?.recovery_keys || []
    // Backend signals delivery failure via message content
    emailDelivered.value = !msg.toLowerCase().includes('could not send')
    accountReady.value = !verificationRequired.value || /ready to use|verification is currently disabled/i.test(msg)
    registrationComplete.value = true
    // Start cooldown immediately so user can't spam on first load
    startCooldown()
  } catch (err: any) {
    submitError.value = err.response?.data?.detail || err.message || 'Registration failed'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/auth-shell.css';
</style>
