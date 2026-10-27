/**
 * Changing a password while signed in (§FESUITE). One rule set and one submit for Settings and the forced change.
 *
 * POST /auth/change-password bumps the account's token_version, which revokes EVERY live token, the one this console
 * holds included. So a success ends the local session and sends the person to the login form with their address
 * filled in and a sentence saying why; the old forced-change flow re-read the profile with the revoked token and the
 * person was thrown out by a 401 under a toast that said "Your account is now fully unlocked".
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'

export function usePasswordChange() {
  const router = useRouter()
  const authStore = useAuthStore()
  const uiStore = useUIStore()
  const { t } = useI18n()

  const currentPassword = ref('')
  const newPassword = ref('')
  const confirmPassword = ref('')
  const submitting = ref(false)
  const error = ref('')

  // Mirrors the server rule (/auth/change-password): 12+ with upper, lower, digit and a special character.
  const rules = computed(() => ({
    length: newPassword.value.length >= 12,
    upper: /[A-Z]/.test(newPassword.value),
    lower: /[a-z]/.test(newPassword.value),
    digit: /[0-9]/.test(newPassword.value),
    special: /[^A-Za-z0-9]/.test(newPassword.value),
    match: newPassword.value.length > 0 && newPassword.value === confirmPassword.value,
    different: newPassword.value.length > 0 && newPassword.value !== currentPassword.value,
  }))
  const canSubmit = computed(() => !!currentPassword.value && Object.values(rules.value).every(Boolean) && !submitting.value)

  async function submit(): Promise<boolean> {
    if (!canSubmit.value) return false
    submitting.value = true
    error.value = ''
    const email = String((authStore.user as unknown as Record<string, unknown> | null)?.email || '')
    try {
      await apiClient.post('/auth/change-password', {
        current_password: currentPassword.value,
        new_password: newPassword.value,
      })
    } catch (e: any) {
      error.value =
        e?.response?.data?.detail ||
        e?.response?.data?.error?.detail ||
        t('passwordChange.failed', 'Could not change the password. Check the current one and try again.')
      submitting.value = false
      return false
    }
    currentPassword.value = newPassword.value = confirmPassword.value = ''
    uiStore.showSuccess(
      t('passwordChange.changed', 'Password changed'),
      t('passwordChange.signInAgain', 'Every session ended with the old password. Sign in with the new one.'),
    )
    await authStore.endLocalSession('the password changed')
    submitting.value = false
    await router.replace({ path: '/login', query: email ? { email } : {} })
    return true
  }

  return { currentPassword, newPassword, confirmPassword, rules, canSubmit, submitting, error, submit }
}
