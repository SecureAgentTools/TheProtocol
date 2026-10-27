<template>
  <!-- §FESUITE (2026-10-04, his word "settings ... needs some polish"): this panel was a stock card (white/gray surfaces,
       a bright blue button, its own headings) inside the Settings card that already titles it; it now speaks the page's
       language: the card's help text, a status pill, the console's buttons. The labels the security lifecycle presses
       stay ("Enable Two-Factor Authentication", "Disable 2FA"). -->
  <div class="tfa">
    <div class="tfa-head">
      <p class="st-card-help tfa-lead">
        A code from an authenticator app is asked at sign-in, in addition to your password.
      </p>
      <span v-if="twoFactorStore.statusRead === 'ok'" class="tfa-status" :class="twoFactorStore.isEnabled ? 'tfa-status--on' : 'tfa-status--off'" data-testid="tfa-status">
        {{ twoFactorStore.isEnabled ? 'Enabled' : 'Disabled' }}
      </span>
    </div>

    <!-- §FESUITE (2026-10-05): the status and its buttons wait for the status read; a failed one says so (it drew
         "Disabled" and the enable button over an account whose 2FA may be on) -->
    <p v-if="twoFactorStore.statusRead === 'idle' || twoFactorStore.statusRead === 'loading'" class="st-card-help" data-testid="tfa-loading">
      {{ t('common.loading') }}
    </p>
    <ReadFailedNotice v-else-if="twoFactorStore.statusRead === 'failed'" dense :retry="twoFactorStore.checkStatus" />
    <div v-else-if="!twoFactorStore.isEnabled">
      <button class="nc-btn nc-btn-primary" @click="showSetupModal = true">
        Enable Two-Factor Authentication
      </button>
    </div>

    <div v-else>
      <p class="st-card-help">
        Your account is protected with two-factor authentication<template v-if="twoFactorStore.verifiedAt">, enabled since
        {{ formatDate(twoFactorStore.verifiedAt) }}</template>.
      </p>
      <p class="st-card-help">
        Keep your backup codes somewhere safe: each one signs you in once if you lose the phone with your authenticator app
        (Google Authenticator, Authy, Microsoft Authenticator and others work).
      </p>
      <div class="tfa-actions">
        <button class="nc-btn nc-btn-secondary" @click="showBackupCodesModal = true">
          Regenerate Backup Codes
        </button>
        <button class="nc-btn nc-btn-danger" @click="showDisableModal = true">
          Disable 2FA
        </button>
      </div>
    </div>

    <!-- Modals -->
    <TwoFactorSetupModal
      :is-open="showSetupModal"
      @close="handleSetupClose"
      @complete="handleSetupComplete"
    />

    <TwoFactorBackupCodesModal
      :is-open="showBackupCodesModal"
      @close="showBackupCodesModal = false"
    />

    <TwoFactorDisableModal
      :is-open="showDisableModal"
      @close="showDisableModal = false"
      @disabled="handleDisabled"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, onMounted } from 'vue'
import { useTwoFactorStore } from '@/stores/twoFactor'
import { useI18n } from '@/composables/useI18n'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import TwoFactorSetupModal from './TwoFactorSetupModal.vue'
import TwoFactorBackupCodesModal from './TwoFactorBackupCodesModal.vue'
import TwoFactorDisableModal from './TwoFactorDisableModal.vue'

// Store
const twoFactorStore = useTwoFactorStore()
const { t } = useI18n()

// State
const showSetupModal = ref(false)
const showBackupCodesModal = ref(false)
const showDisableModal = ref(false)

// Lifecycle
onMounted(async () => {
  // Check 2FA status on mount
  await twoFactorStore.checkStatus()
})

// Methods
const formatDate = (dateString: string) => {
  return new Date(dateString).toLocaleDateString(appLocale(), {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const handleSetupClose = () => {
  showSetupModal.value = false
}

const handleSetupComplete = async () => {
  showSetupModal.value = false
  // Refresh status
  await twoFactorStore.checkStatus()
}

const handleDisabled = async () => {
  showDisableModal.value = false
  // Refresh status
  await twoFactorStore.checkStatus()
}
</script>

<style scoped>
.tfa { display: flex; flex-direction: column; gap: 14px; }
.tfa-head {
  display: flex;
  flex-wrap: wrap;   /* on a phone the status pill goes below the lead instead of squeezing it */
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px 16px;
}
.tfa-lead { flex: 1 1 260px; margin: 0; }
.tfa-status {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-family: var(--st-mono, ui-monospace, monospace);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border: 1px solid var(--st-border, rgba(255, 255, 255, 0.12));
}
.tfa-status--on { color: var(--st-green, #10dc81); border-color: currentColor; }
.tfa-status--off { color: var(--st-text-muted, #8b9bb4); }
.tfa-actions { display: flex; flex-wrap: wrap; gap: 10px; }
</style>
