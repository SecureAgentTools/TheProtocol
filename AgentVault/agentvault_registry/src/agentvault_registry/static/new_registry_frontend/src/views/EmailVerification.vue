<template>
  <AuthShell tagline="IDENTITY VERIFICATION" status="VERIFICATION GATEWAY">
    <!-- Success -->
    <NeuralCard v-if="status === 'success'" variant="elevated" accent="primary" class="nc-auth-card">
      <div class="ev-status">
        <div class="ev-icon ev-icon-success">
          <NeuralIcon name="check-circle" :size="44" />
        </div>
        <h2 class="ev-title ev-title-success">
          {{ alreadyVerified ? t('emailVerificationView.alreadyVerified') : t('emailVerificationView.verified') }}
        </h2>
        <p class="ev-desc">
          {{ alreadyVerified ? t('emailVerificationView.alreadyDesc') : t('emailVerificationView.verifiedDesc') }}
        </p>
        <button class="ev-btn ev-btn-primary" @click="goToLogin">
          <NeuralIcon name="log-in" :size="16" />
          <span>{{ t('emailVerificationView.login') }}</span>
        </button>
      </div>
    </NeuralCard>

    <!-- Failed -->
    <NeuralCard v-else-if="status === 'failed'" variant="elevated" accent="primary" class="nc-auth-card">
      <div class="ev-status">
        <div class="ev-icon ev-icon-failed">
          <NeuralIcon name="x-circle" :size="44" />
        </div>
        <h2 class="ev-title ev-title-failed">{{ t('emailVerificationView.failed') }}</h2>
        <p class="ev-desc">{{ failureMessage }}</p>

        <!-- Inline resend (replaces "Please register again" — users with
             expired tokens just need a fresh email, not a re-registration). -->
        <div v-if="!resendDone" class="ev-resend-form">
          <p class="ev-resend-label">{{ t('emailVerificationView.resendLabel') }}</p>
          <input
            v-model="resendEmail"
            type="email"
            class="nc-input ev-resend-input"
            placeholder="you@example.com"
            :disabled="resendBusy"
            @keyup.enter="onResend"
          />
          <button
            class="ev-btn ev-btn-primary"
            :disabled="resendBusy || !resendEmail"
            @click="onResend"
          >
            <NeuralIcon name="mail" :size="16" />
            <span>{{ resendBusy ? t('emailVerificationView.resendBusy') : t('emailVerificationView.resend') }}</span>
          </button>
          <p v-if="resendError" class="nc-field-error" style="margin-top:0.5rem">{{ resendError }}</p>
        </div>
        <div v-else class="ev-resend-confirmation">
          <NeuralIcon name="check-circle" :size="20" color="success" />
          <p class="ev-desc" style="margin: 0.5rem 0 1rem">
            {{ t('emailVerificationView.resendConfirm') }}
          </p>
        </div>

        <div class="ev-actions">
          <button class="ev-btn ev-btn-secondary" @click="goToLogin">
            <NeuralIcon name="log-in" :size="16" />
            <span>{{ t('emailVerificationView.backToLogin') }}</span>
          </button>
        </div>
      </div>
    </NeuralCard>

    <!-- Loading / Pending -->
    <NeuralCard v-else variant="elevated" accent="primary" class="nc-auth-card">
      <div class="ev-status">
        <div class="ev-icon ev-icon-pending">
          <NeuralIcon name="mail" :size="44" />
        </div>
        <h2 class="ev-title">{{ t('emailVerificationView.pendingTitle') }}</h2>
        <p class="ev-desc">{{ t('emailVerificationView.pendingDesc') }}</p>
        <button class="ev-btn ev-btn-primary" @click="goToLogin">
          <NeuralIcon name="log-in" :size="16" />
          <span>{{ t('emailVerificationView.goToLogin') }}</span>
        </button>
      </div>
    </NeuralCard>
  </AuthShell>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import AuthShell from '@/components/auth/AuthShell.vue'
import { authApi } from '@/services/api/auth'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

const status = computed(() => (route.query.status as string) || '')
const reason = computed(() => (route.query.reason as string) || '')
const alreadyVerified = computed(() => route.query.already === 'true')

const failureMessage = computed(() => {
  switch (reason.value) {
    case 'expired':
      return 'Your verification link has expired. Request a fresh one below — your account is intact.'
    case 'not_found':
      return 'This verification link is invalid or has already been used. Request a fresh one below if you still need to verify.'
    case 'error':
      return 'A server error occurred during verification. Please try again in a moment.'
    default:
      return 'Verification could not be completed. Request a fresh verification link below.'
  }
})

// Inline resend form state (failed-status branch only)
const resendEmail = ref('')
const resendBusy = ref(false)
const resendDone = ref(false)
const resendError = ref<string | null>(null)

async function onResend() {
  if (!resendEmail.value || resendBusy.value) return
  resendBusy.value = true
  resendError.value = null
  try {
    await authApi.resendVerification(resendEmail.value)
    resendDone.value = true
  } catch (e: any) {
    resendError.value = e?.response?.data?.detail || e?.message || 'Could not send verification email. Try again.'
  } finally {
    resendBusy.value = false
  }
}

const goToLogin = () => router.push('/login')
const goToRegister = () => router.push('/register')
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/auth-shell.css';
</style>
