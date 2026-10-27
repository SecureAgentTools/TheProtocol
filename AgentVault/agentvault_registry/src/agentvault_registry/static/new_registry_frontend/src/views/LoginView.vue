<template>
  <AuthShell :tagline="t('login.logoTagline', 'NEURAL COMMAND CENTER')" :status="t('login.systemOnline', 'SYSTEM ONLINE')">
    <!-- Auth Card -->
    <NeuralCard variant="elevated" accent="primary" class="nc-auth-card">
      <div class="nc-auth-header">
        <h2 class="nc-auth-title">{{ t('login.title', 'SYSTEM AUTHENTICATION') }}</h2>
        <p class="nc-auth-description">{{ t('login.subtitle', 'Enter credentials to access the sovereign agent network') }}</p>
      </div>

      <!-- Login Form -->
      <form @submit.prevent="handleLogin" class="nc-auth-form">
        <!-- Username Field -->
        <div class="nc-form-group">
          <label class="nc-form-label">{{ t('login.identifier', 'IDENTIFIER') }}</label>
          <div class="nc-input-wrapper">
            <NeuralIcon name="user" :size="18" class="nc-input-icon" />
            <input
              v-model="email"
              type="email"
              class="nc-input nc-input-with-icon"
              :placeholder="t('login.identifierPlaceholder', 'agent{\'@\'}example.com')"
              required
              autocomplete="username"
              @input="clearError"
            />
          </div>
        </div>

        <!-- Password Field -->
        <div class="nc-form-group">
          <label class="nc-form-label">{{ t('login.accessKey', 'ACCESS KEY') }}</label>
          <div class="nc-input-wrapper">
            <NeuralIcon name="lock" :size="18" class="nc-input-icon" />
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              class="nc-input nc-input-with-icon"
              placeholder="••••••••"
              required
              autocomplete="current-password"
              @input="clearError"
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
        </div>

        <!-- Remember Me -->
        <div class="nc-form-group nc-checkbox-group">
          <label class="nc-checkbox">
            <input
              v-model="rememberMe"
              type="checkbox"
              class="nc-checkbox-input"
            />
            <span class="nc-checkbox-box"></span>
            <span class="nc-checkbox-label">{{ t('login.maintainSession', 'Maintain session') }}</span>
          </label>
          <RouterLink to="/forgot-password" class="nc-link">
            {{ t('login.recoveryProtocol', 'Recovery protocol') }}
          </RouterLink>
        </div>

        <!-- Submit Button -->
        <button
          type="submit"
          class="nc-btn nc-btn-primary nc-btn-full"
          :disabled="isSubmitting"
        >
          <span v-if="!isSubmitting" class="nc-btn-content">
            <NeuralIcon name="lock" :size="18" />
            <span>{{ t('login.authenticate', 'AUTHENTICATE') }}</span>
          </span>
          <span v-else class="nc-btn-content">
            <NeuralIcon name="loading" :size="18" class="nc-icon-spin" />
            <span>{{ t('login.authenticating', 'AUTHENTICATING...') }}</span>
          </span>
        </button>

        <!-- Error Message -->
        <div v-if="error" class="nc-alert nc-alert-danger">
          <NeuralIcon name="alert-triangle" :size="16" />
          <span>{{ error }}</span>
        </div>

        <!-- Resend verification CTA (only shown when backend signals
             X-Verification-Required:true on a 403 — i.e., login was correct
             but account isn't email-verified yet). -->
        <div v-if="verificationRequired" class="nc-resend-block">
          <button
            type="button"
            class="nc-btn nc-btn-secondary nc-btn-full nc-resend-btn"
            :disabled="resendBusy || resendDone"
            @click="onResendVerification"
          >
            <NeuralIcon name="mail" :size="16" />
            <span v-if="resendDone">{{ t('login.verificationSent', 'VERIFICATION EMAIL SENT') }}</span>
            <span v-else-if="resendBusy">{{ t('login.verificationSending', 'SENDING…') }}</span>
            <span v-else>{{ t('login.resendVerification', 'RESEND VERIFICATION EMAIL') }}</span>
          </button>
          <p v-if="resendDone" class="nc-resend-confirm">
            Fresh verification link sent to <strong>{{ email }}</strong>. Check your inbox (and spam folder).
          </p>
          <p v-else-if="resendError" class="nc-resend-error">{{ resendError }}</p>
        </div>
      </form>

      <!-- Footer Links -->
      <div class="nc-auth-footer">
        <p class="nc-auth-footer-text">
          {{ t('login.noAccount', 'Need an account?') }}
          <RouterLink to="/register" class="nc-link">{{ t('login.initializeAccount', 'Initialize agent account') }}</RouterLink>
        </p>
      </div>

      <!-- Demo Credentials (Development Only) -->
      <div v-if="isDevelopment" class="nc-demo-box">
        <div class="nc-demo-header">
          <NeuralIcon name="command" :size="14" />
          <span>{{ t('login.testCredentials', 'TEST CREDENTIALS') }}</span>
        </div>
        <div class="nc-demo-content">
          <div class="nc-mono">ID: commander@theprotocol.cloud</div>
          <div class="nc-mono">KEY: (any password)</div>
        </div>
      </div>
    </NeuralCard>
  </AuthShell>

  <!-- 2FA Modal -->
  <!-- PUSH LOGIN: the browser holds no secret; it simply waits for the phone. -->
  <div v-if="awaitingPush" class="lg-push-wait" role="status" aria-live="polite" data-testid="lg-push-wait">
    <p><strong>Check your phone</strong></p>
    <p class="lg-push-sub">Sent to your phone for biometric verification. Approve it with your fingerprint and this page continues on its own.</p>
    <!-- how long the request waits, and a way back to the form (it waited up to two minutes with the form shut) -->
    <p class="lg-push-sub lg-push-left" data-testid="lg-push-left">{{ pushLeftText }}</p>
    <button type="button" class="lg-push-stop" data-testid="lg-push-stop" @click="stopWaiting">Stop waiting</button>
  </div>

  <TwoFactorLoginModal
    :isOpen="show2faModal"
    @success="on2faSuccess"
    @close="show2faModal = false"
  />
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { homeRoute } from '@/services/uiMode'
import { authApi } from '@/services/api/auth'
import { useI18n } from '@/composables/useI18n'
import TwoFactorLoginModal from '@/components/auth/TwoFactorLoginModal.vue'
import AuthShell from '@/components/auth/AuthShell.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

// Form state (an address handed over by the register confirmation's sign-in door is prefilled)
const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const password = ref('')
const rememberMe = ref(false)
const showPassword = ref(false)

// UI state
const isSubmitting = ref(false)
const show2faModal = ref(false)
const awaitingPush = ref(false)   // PUSH LOGIN: waiting on the phone's fingerprint
// PUSH LOGIN: the seconds the phone's request still waits (the registry's own window), shown on the waiting card
const pushLeft = ref(0)
let pushClock: ReturnType<typeof setInterval> | null = null
const pushLeftText = computed(() => {
  const s = Math.max(0, pushLeft.value)
  return `Waiting for your phone: ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} left`
})
function stopPushClock() { if (pushClock) { clearInterval(pushClock); pushClock = null } }
function startPushClock() {
  const end = Date.now() + (authStore.pushApprovalExpiresIn || 120) * 1000
  const tick = () => { pushLeft.value = Math.max(0, Math.ceil((end - Date.now()) / 1000)) }
  stopPushClock(); tick(); pushClock = setInterval(tick, 1000)
}
/** Stop waiting for the phone: the form is back; the request on the phone expires on its own and signs nothing in here. */
function stopWaiting() { authStore.stopWaitingForPhone() }
// leaving the page ends the wait too: a phone's later approval would otherwise sign in a page the person had left
onUnmounted(() => { stopPushClock(); if (awaitingPush.value) authStore.stopWaitingForPhone() })
const error = computed(() => authStore.error)
const verificationRequired = computed(() => (authStore as any).verificationRequired)

// Resend-verification CTA state (visible when verificationRequired = true)
const resendBusy = ref(false)
const resendDone = ref(false)
const resendError = ref<string | null>(null)

async function onResendVerification() {
  if (!email.value || resendBusy.value || resendDone.value) return
  resendBusy.value = true
  resendError.value = null
  try {
    await authApi.resendVerification(email.value)
    resendDone.value = true
  } catch (err: any) {
    resendError.value = err?.response?.data?.detail
      || err?.message
      || 'Could not send verification email. Try again.'
  } finally {
    resendBusy.value = false
  }
}

// Check if in development mode
const isDevelopment = computed(() => import.meta.env.DEV)

// Clear error on input change
function clearError() {
  authStore.clearError()
  // Also reset resend-CTA state when user starts typing again
  resendDone.value = false
  resendError.value = null
}

async function handleLogin() {
  if (!email.value || !password.value) {
    return
  }

  isSubmitting.value = true
  try {
    const success = await authStore.login(
      {
        email: email.value,
        password: password.value
      },
      rememberMe.value
    )

    if (success) {
      // §POCKETBRIDGE #PK23 — saved mode choice wins, else phones land in Pocket.
      const redirectTo = (route.query.redirect as string) || homeRoute()
      await router.push(redirectTo)
    } else if (authStore.pushApprovalId) {
      // PUSH LOGIN: the account requires approval from its enrolled phone. Nothing was issued;
      // we wait for the fingerprint on the other device, then redeem.
      awaitingPush.value = true
      startPushClock()
      const ok = await authStore.completePushLogin()
      awaitingPush.value = false
      stopPushClock()
      if (ok) {
        const redirectTo = (route.query.redirect as string) || homeRoute()
        await router.push(redirectTo)
      }
    } else if (!authStore.error) {
      // Login returned false but no error — means 2FA is required
      show2faModal.value = true
    }
  } catch (err) {
    // §FESUITE: a refused credential (a 4xx) is the person's mistake, already shown to them; only the unexpected is an error
    const status = (err as any)?.response?.status
    if (!status || status >= 500) console.error('Login error:', err)
  } finally {
    isSubmitting.value = false
  }
}

async function on2faSuccess() {
  show2faModal.value = false
  // After 2FA validation, the twoFactorStore.validateCode sets the token in authStore
  // Check if we're now authenticated and redirect
  if (authStore.isAuthenticated) {
    const redirectTo = (route.query.redirect as string) || '/mission-control'
    await router.push(redirectTo)
  }
}
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/auth-shell.css';

/* PUSH LOGIN (2026-07-25): the wait had no rule, so its two lines drew below the sign-in card, out of sight on a
   desktop, while the page waited for the phone. It is a card at the foot of the screen until the phone answers. */
.lg-push-wait {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 60;
  width: min(420px, calc(100vw - 32px)); padding: 14px 18px; border-radius: 12px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4); background: var(--nc-surface, #131825);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45); color: var(--nc-text-primary, #e2e8f0); text-align: center;
}
.lg-push-wait p { margin: 0; }
.lg-push-wait .lg-push-sub { margin-top: 6px; font-size: 0.82rem; line-height: 1.45; color: var(--nc-text-secondary, #cbd5e1); }
.lg-push-wait .lg-push-left { font-variant-numeric: tabular-nums; }
.lg-push-stop {
  margin-top: 10px; padding: 6px 14px; border-radius: 8px; font-size: 0.82rem; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5); background: transparent; color: var(--nc-text-primary, #e2e8f0);
}
.lg-push-stop:hover, .lg-push-stop:focus-visible { background: rgba(var(--nc-primary-rgb), 0.12); }
</style>
