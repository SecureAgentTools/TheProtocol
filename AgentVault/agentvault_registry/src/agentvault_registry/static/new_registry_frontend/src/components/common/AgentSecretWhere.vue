<template>
  <div class="asw" :class="place === 'plain' ? 'asw--plain' : 'asw--sealed'" data-testid="agent-secret-where" :data-place="place">
    <p class="asw-text" role="status">
      <template v-if="place === 'plain' || place === 'none'">{{ t('agentSecret.plain', 'This secret is kept in this browser, unencrypted: any script on this page, and anyone with this browser profile, can read it.') }}</template>
      <template v-else-if="place === 'sealed-fingerprint'">{{ t('agentSecret.sealedFingerprint', 'This secret is encrypted in this browser and opens with your fingerprint or face.') }}</template>
      <template v-else-if="place === 'sealed-device'">{{ t('agentSecret.sealedDevice', 'This secret is sealed in this browser with a device key: copied storage cannot be read; this page still can.') }}</template>
      <template v-else>{{ t('agentSecret.sealedOther', 'This secret is sealed in this browser.') }}</template>
    </p>
    <div v-if="place === 'plain' || place === 'none' || offerDeviceKey" class="asw-actions">
      <button v-if="!offerDeviceKey" type="button" class="asw-btn" data-testid="agent-secret-lock" :disabled="busy" @click="lockNow">
        {{ busy ? t('agentSecret.locking', 'Locking…') : t('agentSecret.lock', 'Lock it with this device') }}
      </button>
      <button v-else type="button" class="asw-btn asw-btn--weak" data-testid="agent-secret-device-key" :disabled="busy" @click="sealWithDeviceKey">
        {{ t('agentSecret.deviceKey', 'Seal with a device key instead') }}
      </button>
    </div>
    <p v-if="msg" class="asw-msg" data-testid="agent-secret-msg">{{ msg }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): one line that says where an agent's secret sits
 * in this browser, and while it sits there unencrypted, the one press that locks it (useLockAgentSecrets).
 */
import { onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useLockAgentSecrets } from '@/composables/useLockAgentSecrets'

const { t } = useI18n()
const { place, busy, msg, offerDeviceKey, lockNow, sealWithDeviceKey, refresh } = useLockAgentSecrets()
onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.asw {
  margin: 10px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.12));
  border-radius: 6px;
  font-size: 0.8rem;
  line-height: 1.45;
}
.asw--plain { border-color: var(--nc-warning, #ffa000); }
.asw--sealed { border-color: var(--nc-success, #3fb950); }
.asw-text { margin: 0; }
.asw-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
.asw-btn {
  font: inherit;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid var(--nc-primary, #00d4ff);
  background: transparent;
  color: var(--nc-primary, #00d4ff);
  cursor: pointer;
}
.asw-btn:disabled { opacity: 0.6; cursor: default; }
.asw-btn--weak { border-color: var(--nc-text-muted, #8b949e); color: var(--nc-text-muted, #8b949e); }
.asw-msg { margin: 8px 0 0; color: var(--nc-text-muted, #8b949e); }
</style>
