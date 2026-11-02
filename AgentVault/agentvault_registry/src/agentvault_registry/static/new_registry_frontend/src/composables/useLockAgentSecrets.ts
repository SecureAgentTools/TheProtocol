/**
 * Where an agent's secret sits in this browser, and the one press that locks it.
 *
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): the console keeps an agent's client secret in
 * this browser's storage, readable by any script on the page, until the lock seals it. The import that puts a secret
 * there offers the lock at once, instead of leaving it to Pocket's settings. The ceremony is Pocket's own
 * (usePocketLock: enrol the device's fingerprint or face unlock if it is not enrolled, then seal under its key; a
 * device that cannot derive that key is offered the weaker device-key seal, explicitly, never as a silent downgrade).
 */
import { ref } from 'vue'
import { usePocketLock } from '@/composables/usePocketLock'
import { useI18n } from '@/composables/useI18n'

export type SecretPlace = 'plain' | 'sealed-fingerprint' | 'sealed-device' | 'sealed' | 'none'

export function placeOf(info: { state: string; kdf: string | null }): SecretPlace {
  if (info.state === 'plain') return 'plain'
  if (info.state === 'sealed-open' || info.state === 'sealed-locked') {
    if (info.kdf === 'webauthn-prf') return 'sealed-fingerprint'
    if (info.kdf === 'device-key') return 'sealed-device'
    return 'sealed'
  }
  return 'none'
}

/** WebAuthn and WebCrypto exist only in a secure context (HTTPS, or localhost): over plain http neither lock can run. */
function secureHere(): boolean {
  return typeof window === 'undefined' || window.isSecureContext !== false
}

export function useLockAgentSecrets() {
  const { t } = useI18n()
  const lock = usePocketLock()
  const place = ref<SecretPlace>(placeOf(lock.vaultInfo()))
  const busy = ref(false)
  const msg = ref('')
  const offerDeviceKey = ref(false)

  function refresh(): SecretPlace {
    place.value = placeOf(lock.vaultInfo())
    return place.value
  }

  /** One press: enrol the device unlock if needed, then seal every agent secret in this browser under its key. */
  async function lockNow(): Promise<boolean> {
    if (busy.value) return false
    busy.value = true
    msg.value = ''
    offerDeviceKey.value = false
    try {
      if (!secureHere()) {
        // over plain http (a LAN address, a kit frame without TLS) the browser has neither the device unlock nor the key
        // store the seal needs: say so instead of blaming the device, and offer no seal that cannot run
        msg.value = t('agentSecret.insecure', 'This page is not served over HTTPS, so this browser can lock nothing here: the secret stays unencrypted.')
        return false
      }
      if (!lock.enabled.value && !(await lock.available())) {
        // no fingerprint or face unlock on this device: say so, and offer the weaker seal instead of a prompt that fails
        offerDeviceKey.value = true
        msg.value = t('agentSecret.noUnlock', 'This device has no fingerprint or face unlock. A device key still protects copied storage; it is weaker.')
        return false
      }
      if (!lock.enabled.value && !(await lock.enroll())) {
        msg.value = t('agentSecret.enrollCancelled', 'The device unlock was not set up; the secret stays unencrypted here.')
        return false
      }
      const r = await lock.sealCredentials()
      if (r.ok) return true   // the line above says where the secret sits now: a message would only repeat it
      if (r.reason === 'prf-unavailable') {
        offerDeviceKey.value = true
        msg.value = t('agentSecret.noPrf', 'This device cannot derive a key from its unlock. A device key still protects copied storage; it is weaker.')
        return false
      }
      msg.value = r.reason || t('agentSecret.sealFailed', 'Locking failed; nothing was changed.')
      return false
    } finally {
      busy.value = false
      refresh()
    }
  }

  /** The weaker seal, offered only when the device cannot derive a key from its unlock. */
  async function sealWithDeviceKey(): Promise<boolean> {
    if (busy.value) return false
    busy.value = true
    msg.value = ''
    try {
      if (!secureHere()) {
        offerDeviceKey.value = false
        msg.value = t('agentSecret.insecure', 'This page is not served over HTTPS, so this browser can lock nothing here: the secret stays unencrypted.')
        return false
      }
      const r = await lock.sealCredentialsDeviceKey()
      // on success the line above says where the secret sits now: a message would only repeat it
      msg.value = r.ok ? '' : (r.reason || t('agentSecret.sealFailed', 'Locking failed; nothing was changed.'))
      if (r.ok) offerDeviceKey.value = false
      return r.ok
    } finally {
      busy.value = false
      refresh()
    }
  }

  return { place, busy, msg, offerDeviceKey, lockNow, sealWithDeviceKey, refresh }
}
