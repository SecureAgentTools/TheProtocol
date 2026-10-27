<!-- An agent's credentials, shown once (quick onboarding, 2026-10-09): the client ID and the client secret, each with a
     copy button, the secret masked until the person reveals it. Used by the issued identity card and by the reset dialog,
     so both say the same thing the same way. The secret is in the DOM only while revealed, and never in a title. -->
<template>
  <div class="qo-creds" data-testid="qo-creds">
    <div class="qo-creds__row">
      <span class="qo-creds__label">{{ t('quickOnboarding.creds.clientId', 'Client ID') }}</span>
      <div class="qo-creds__value-line">
        <code class="qo-creds__value" data-testid="qo-cred-client-id">{{ clientId }}</code>
        <CopyButton :value="clientId" :what="t('quickOnboarding.creds.clientIdWhat', 'the client ID')" quiet />
      </div>
    </div>
    <div class="qo-creds__row">
      <span class="qo-creds__label">{{ t('quickOnboarding.creds.clientSecret', 'Client secret') }}</span>
      <div class="qo-creds__value-line">
        <code class="qo-creds__value qo-creds__value--secret" :class="{ 'is-masked': !revealed }"
              data-testid="qo-cred-secret" :data-revealed="revealed ? '1' : '0'">
          <template v-if="revealed">{{ clientSecret }}</template>
          <template v-else><span aria-hidden="true">{{ SECRET_MASK }}</span><span class="sr-only">{{ t('quickOnboarding.creds.secretHidden', 'Hidden') }}</span></template>
        </code>
        <button type="button" class="qo-creds__reveal" data-testid="qo-cred-reveal" @click="revealed = !revealed">
          <Icon :name="revealed ? 'mdi:eye-off' : 'mdi:eye'" class="qo-creds__reveal-icon" />
          <span>{{ revealed ? t('quickOnboarding.creds.hideSecret', 'Hide secret') : t('quickOnboarding.creds.showSecret', 'Show secret') }}</span>
        </button>
        <CopyButton :value="clientSecret" :what="t('quickOnboarding.creds.clientSecretWhat', 'the client secret')" quiet />
      </div>
    </div>
    <p class="qo-creds__once" data-testid="qo-creds-once">
      <Icon name="mdi:shield-key" class="qo-creds__once-icon" />
      <span>{{ t('quickOnboarding.creds.once', 'Shown once: store the secret now. This browser keeps a copy so the console can sign in as this agent, but nobody can show it to you again.') }}</span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import CopyButton from './CopyButton.vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ clientId: string; clientSecret: string }>()
const { t } = useI18n()
/** what a hidden secret reads as: fixed width, no character of the secret */
const SECRET_MASK = '••••••••••••••••••••'
const revealed = ref(false)
// a new pair starts hidden again
watch(() => props.clientSecret, () => { revealed.value = false })
</script>

<style scoped>
.qo-creds { display: flex; flex-direction: column; gap: 0.75rem; min-width: 0; }
.qo-creds__row { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
.qo-creds__label {
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--nc-text-secondary, #9aa0a6);
}
.qo-creds__value-line { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; min-width: 0; }
.qo-creds__value {
  flex: 1 1 14rem; min-width: 0;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', ui-monospace, Menlo, Consolas, monospace;
  font-size: 0.82rem; line-height: 1.45; overflow-wrap: anywhere;
  color: var(--nc-text-primary, #e8eaed);
  background: rgba(0, 0, 0, 0.32); border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 8px; padding: 0.45rem 0.65rem;
}
.qo-creds__value--secret { color: #ffd88a; }
.qo-creds__value--secret.is-masked { letter-spacing: 0.12em; color: var(--nc-text-secondary, #9aa0a6); }
.qo-creds__reveal {
  display: inline-flex; align-items: center; gap: 0.35rem; min-height: 28px; padding: 0.2rem 0.55rem;
  border-radius: 8px; cursor: pointer; font: inherit; font-size: 0.76rem; font-weight: 600;
  color: var(--nc-text-primary, #e8eaed); background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
}
.qo-creds__reveal:hover { border-color: rgba(var(--nc-primary-rgb), 0.55); background: rgba(var(--nc-primary-rgb), 0.08); }
.qo-creds__reveal:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-creds__reveal-icon { font-size: 0.95rem; }
.qo-creds__once {
  display: flex; align-items: flex-start; gap: 0.5rem; margin: 0;
  font-size: 0.8rem; line-height: 1.5; color: #ffd88a;
  background: rgba(255, 149, 0, 0.08); border: 1px solid rgba(255, 149, 0, 0.3); border-radius: 10px;
  padding: 0.6rem 0.75rem;
}
.qo-creds__once-icon { font-size: 1rem; margin-top: 0.1rem; color: #ffd88a; }
</style>
