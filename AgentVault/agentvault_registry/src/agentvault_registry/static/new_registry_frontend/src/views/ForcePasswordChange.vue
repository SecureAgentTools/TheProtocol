<script setup lang="ts">
/**
 * Forced password change (§EXCISION-10).
 *
 * `developers.must_change_password` has existed and been ENFORCED server-side for a
 * long time: `security.py::require_admin` 403s EVERY admin operation until the password
 * is changed. Nothing in the UI ever acted on it, so setting the flag produced a
 * dashboard where every action failed with a raw error and no explanation — which is
 * why it was never switched on for accounts we hand to third parties.
 *
 * This screen is the missing half. The router guard sends every authenticated
 * must-change user here and refuses to let them leave, so the server-side gate and the
 * UI finally agree.
 */
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import { usePasswordChange } from '@/composables/usePasswordChange'

const router = useRouter()
const authStore = useAuthStore()

// §FESUITE: the change revokes every live token, this console's included; the shared submit ends the local session
// and sends the person to sign in with the new password (this screen used to re-read the profile with the revoked
// token and route to mission control, and the person was thrown out by a 401 under "fully unlocked").
const { currentPassword, newPassword, confirmPassword, rules, canSubmit, submitting, error, submit } = usePasswordChange()

async function logout() {
  await authStore.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="fpc-wrap">
    <div class="fpc-card">
      <div class="fpc-kicker"><Icon name="mdi:shield-key" /> SECURITY</div>
      <h1 class="fpc-title">Choose a new password</h1>
      <p class="fpc-lede">
        This account was issued with a password that someone else has seen. Set your own
        before you continue; until then, administrative actions stay disabled.
      </p>

      <form @submit.prevent="submit">
        <label class="fpc-label">Current password
          <input v-model="currentPassword" type="password" autocomplete="current-password"
                 class="fpc-input" required />
        </label>
        <label class="fpc-label">New password
          <input v-model="newPassword" type="password" autocomplete="new-password"
                 class="fpc-input" required />
        </label>
        <label class="fpc-label">Repeat new password
          <input v-model="confirmPassword" type="password" autocomplete="new-password"
                 class="fpc-input" required />
        </label>

        <ul class="fpc-rules">
          <li :class="{ ok: rules.length }">at least 12 characters</li>
          <li :class="{ ok: rules.upper }">an upper-case letter</li>
          <li :class="{ ok: rules.lower }">a lower-case letter</li>
          <li :class="{ ok: rules.digit }">a digit</li>
          <li :class="{ ok: rules.special }">a special character</li>
          <li :class="{ ok: rules.different }">different from the current one</li>
          <li :class="{ ok: rules.match }">both entries match</li>
        </ul>

        <p v-if="error" class="fpc-error">{{ error }}</p>

        <button type="submit" class="fpc-submit" :disabled="!canSubmit">
          {{ submitting ? 'Saving…' : 'Set new password' }}
        </button>
      </form>

      <button class="fpc-logout" type="button" @click="logout">Sign out instead</button>
    </div>
  </div>
</template>

<style scoped>
.fpc-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
.fpc-card { width: 100%; max-width: 460px; background: var(--nc-surface, #0a0d16);
  border: 1px solid var(--nc-border, rgba(0,210,210,0.18)); border-radius: 10px; padding: 28px; }
.fpc-kicker { font-size: 11px; letter-spacing: .14em; color: var(--nc-primary, #00d2d2);
  display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.fpc-title { font-size: 22px; margin: 0 0 8px; color: var(--nc-text, #e8eaed); }
.fpc-lede { font-size: 13px; line-height: 1.55; color: var(--nc-muted, #a8b5c2); margin: 0 0 20px; }
.fpc-label { display: block; font-size: 12px; color: var(--nc-muted, #a8b5c2); margin-bottom: 12px; }
.fpc-input { width: 100%; margin-top: 5px; padding: 9px 11px; border-radius: 6px;
  background: rgba(255,255,255,0.03); color: var(--nc-text, #e8eaed);
  border: 1px solid var(--nc-border, rgba(0,210,210,0.18)); font-size: 14px; }
.fpc-input:focus { outline: 2px solid var(--nc-primary, #00d2d2); outline-offset: 1px; }
.fpc-rules { list-style: none; padding: 0; margin: 14px 0 16px; font-size: 12px; }
.fpc-rules li { color: var(--nc-text-muted); padding-left: 18px; position: relative; line-height: 1.85; }  /* §FESUITE: 5.7:1; --nc-muted exists nowhere, so its fallback #5a6a7a (3.2:1) always won */
.fpc-rules li::before { content: '○'; position: absolute; left: 0; }
.fpc-rules li.ok { color: var(--nc-primary, #00d2d2); }
.fpc-rules li.ok::before { content: '●'; }
.fpc-error { color: #ff6b6b; font-size: 12.5px; margin: 0 0 12px; }
.fpc-submit { width: 100%; padding: 10px; border-radius: 6px; font-size: 14px; cursor: pointer;
  background: transparent; color: var(--nc-primary, #00d2d2);
  border: 1px solid var(--nc-primary, rgba(0,210,210,0.5)); }
.fpc-submit:disabled { opacity: .4; cursor: not-allowed; }
.fpc-logout { display: block; margin: 14px auto 0; background: none; border: none; cursor: pointer;
  color: var(--nc-text-muted); font-size: 12px; text-decoration: underline; }
</style>
