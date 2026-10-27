/**
 * POCKET biometric app-lock (2026-07-08) — WebAuthn PLATFORM authenticator (Face ID / Touch ID /
 * Android fingerprint) as a device-local lock over the Pocket shell.
 *
 * HONEST SCOPE: this is an app-LOCK (client-side gate over an already-authenticated session),
 * not passkey server auth. The session JWT is untouched; the lock keeps casual access off an
 * unlocked phone — the exact pattern consumer phone apps use for their in-app biometric lock.
 * Full passkey LOGIN (server-side WebAuthn ceremony) is the flagged follow-up.
 */
import { ref } from 'vue'
import {
  credentialVault, vaultKeyFromPrf, deviceVaultKey, newVaultSalt, b64uToBuf as vB64uToBuf,
} from '@/services/credentialVault'

const KEY = 'pk_biolock'          // { enabled: true, credId: <b64url>, prf?: boolean }
const SESSION_KEY = 'pk_unlocked' // sessionStorage — unlocked for this browser session
const GRACE_MS = 2 * 60 * 1000    // background grace before relock

const locked = ref(false)
const enabled = ref(false)
const busy = ref(false)
let hiddenAt = 0
let wired = false

function b64uToBuf(s: string): ArrayBuffer {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/'))
  const a = new Uint8Array(b.length)
  for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i)
  return a.buffer
}
function bufToB64u(b: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
// TS 5.7+ types a Uint8Array by its buffer; WebAuthn and Push take a BufferSource, which excludes a buffer that could be
// shared, so these helpers say what they return: a fresh ArrayBuffer-backed array.
function rand(n = 32): Uint8Array<ArrayBuffer> { const a = new Uint8Array(n); crypto.getRandomValues(a); return a }
function readCfg(): { enabled: boolean; credId?: string; prf?: boolean } {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}') } catch { return { enabled: false } }
}

/**
 * §POCKETBRIDGE #PK32 — ONE CEREMONY, BOTH JOBS.
 * When the credential vault is sealed under 'webauthn-prf', every biometric
 * assertion this file performs also asks the authenticator to evaluate the
 * vault's PRF salt, and a successful prompt UNSEALS the vault in the same
 * breath. Without this, unlocking Pocket and then sending money would cost
 * two fingerprints for one intent — the exact double-prompt the approve-login
 * screen's comment warns about.
 */
function vaultPrfRequest(): { extensions: any; salt: string } | null {
  try {
    if (credentialVault.state() !== 'sealed-locked') return null
    if (credentialVault.kdf() !== 'webauthn-prf') return null
    const salt = credentialVault.saltB64u()
    if (!salt) return null
    return { extensions: { prf: { eval: { first: vB64uToBuf(salt) } } }, salt }
  } catch { return null }
}

async function maybeUnsealFromAssertion(assertion: any, salt: string | null): Promise<void> {
  if (!salt) return
  try {
    const prfOut = assertion?.getClientExtensionResults?.()?.prf?.results?.first
    if (!prfOut) return   // authenticator did not evaluate — vault stays locked, honestly
    const key = await vaultKeyFromPrf(prfOut, salt)
    await credentialVault.unseal(key)
  } catch (e) {
    // A failed unseal must never fail the UNLOCK — the session is still valid,
    // the vault just stays sealed and consumers say so.
    console.warn('[pocket-lock] vault unseal failed', e)
  }
}

/** device-key vaults need no biometric for the KEY — open them as soon as the
 *  shell asks. (The lock screen still gates the UI exactly as before.) */
export async function maybeUnsealDeviceKeyVault(): Promise<void> {
  try {
    if (credentialVault.state() !== 'sealed-locked') return
    if (credentialVault.kdf() !== 'device-key') return
    await credentialVault.unseal(await deviceVaultKey())
  } catch (e) { console.warn('[pocket-lock] device-key unseal failed', e) }
}

/** Router-visible lock state. The lock USED to be only an overlay inside PocketShell, which
 *  meant the Android back button simply navigated out of the shell and landed in advanced mode
 *  with no biometric ever provided (Commander-found, 2026-07-25). A dismissible overlay is not
 *  an access control; the guard in router/index.ts consults this so the lock is enforced on
 *  every route, not just the one that happens to render the overlay. */
/** The ONE credential this device holds. Everything that needs a biometric — the lock, a
 *  liability confirmation, a sign-in approval — signs with THIS id. Handing an empty or unknown
 *  allowCredentials to the browser is what makes it fall back to the account passkey picker
 *  (the "Google approval" sheet the Commander hit), so callers must always pass it. */
export function pocketCredentialId(): string | null {
  try {
    const cfg = JSON.parse(localStorage.getItem(KEY) || '{}')
    return cfg?.credId || null
  } catch { return null }
}

/** Mark the session as biometrically satisfied. Called after a biometric LOGIN so the shell does
 *  not immediately demand a second fingerprint for the same human, in the same breath. */
export function markPocketUnlocked(): void {
  try { sessionStorage.setItem(SESSION_KEY, '1') } catch {}
}

export function pocketLockEngaged(): boolean {
  try {
    const raw = localStorage.getItem(KEY)
    const cfg = raw ? JSON.parse(raw) : null
    if (!cfg?.enabled || !cfg?.credId) return false
    return sessionStorage.getItem(SESSION_KEY) !== '1'
  } catch { return false }
}


export function usePocketLock() {
  enabled.value = !!readCfg().enabled

  async function available(): Promise<boolean> {
    try {
      return !!window.PublicKeyCredential &&
        await (PublicKeyCredential as any).isUserVerifyingPlatformAuthenticatorAvailable()
    } catch { return false }
  }

  /** Enroll the device biometric (creates a platform credential kept on-device). */
  async function enroll(): Promise<boolean> {
    busy.value = true
    try {
      const cred: any = await navigator.credentials.create({
        publicKey: {
          challenge: rand(),
          rp: { name: 'Pocket', id: location.hostname },
          user: { id: rand(16), name: 'pocket-lock', displayName: 'Pocket lock' },
          // ES256 ONLY. RS256 was accepted here before, but the server-side verifier speaks
          // ES256 — an RS256 credential would lock fine and then fail every signed confirmation.
          pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
          authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required', residentKey: 'discouraged' },
          timeout: 60000,
          attestation: 'none',
          // #PK32 — ask for the PRF extension at CREATE time. Without it, the
          // authenticator will not evaluate PRF at get() time and the sealed
          // vault cannot use this credential. Harmless where unsupported.
          extensions: { prf: {} } as any,
        },
      })
      if (!cred?.rawId) return false
      const prfEnabled = !!cred.getClientExtensionResults?.()?.prf?.enabled
      localStorage.setItem(KEY, JSON.stringify({ enabled: true, credId: bufToB64u(cred.rawId), prf: prfEnabled }))
      enabled.value = true
      try { sessionStorage.setItem(SESSION_KEY, '1') } catch {}

      // Register the SAME credential server-side so it can also sign confirmations and sign-in
      // approvals. One enrolment, one credential, one prompt — instead of the lock and the
      // signer each minting their own. Best-effort: if the registry has the feature dark, the
      // local lock still works exactly as before.
      try {
        const { apiClient } = await import('@/services/api/client')
        await apiClient.post('/liability/webauthn/register', {
          attestation_object: bufToB64u(cred.response.attestationObject),
          client_data_json: bufToB64u(cred.response.clientDataJSON),
        })
      } catch (e) {
        console.warn('[pocket-lock] biometric enrolled locally but not registered server-side', e)
      }
      return true
    } catch { return false }
    finally { busy.value = false }
  }

  /** Turn the lock off. Refused while the vault is sealed under this
   *  credential's PRF — removing the lock then would strand the only key that
   *  can ever open the vault. Unseal first (More → sealed credentials). */
  function disable(): { ok: boolean; reason?: string } {
    try {
      if (credentialVault.isSealed() && credentialVault.kdf() === 'webauthn-prf') {
        return { ok: false, reason: 'Credentials are sealed with this fingerprint key. Unseal them first, then turn the lock off.' }
      }
    } catch { /* vault unreadable — do not block the lock over it */ }
    try { localStorage.removeItem(KEY) } catch {}
    enabled.value = false
    locked.value = false
    return { ok: true }
  }

  /** Biometric prompt against the enrolled credential. A sealed vault rides
   *  the same assertion (PRF eval) and opens with it — one prompt, both jobs. */
  async function unlock(): Promise<boolean> {
    const cfg = readCfg()
    if (!cfg.enabled || !cfg.credId) { locked.value = false; return true }
    busy.value = true
    const prfReq = vaultPrfRequest()
    try {
      const a: any = await navigator.credentials.get({
        publicKey: {
          challenge: rand(),
          allowCredentials: [{ type: 'public-key', id: b64uToBuf(cfg.credId) }],
          userVerification: 'required',
          timeout: 60000,
          ...(prfReq ? { extensions: prfReq.extensions } : {}),
        },
      })
      if (a) {
        await maybeUnsealFromAssertion(a, prfReq?.salt ?? null)
        locked.value = false
        try { sessionStorage.setItem(SESSION_KEY, '1') } catch {}
        try { (navigator as any).vibrate?.(8) } catch {}
        return true
      }
      return false
    } catch { return false }
    finally { busy.value = false }
  }

  /** One-off biometric CONFIRM for a sensitive action (send / approve). Does NOT touch lock state.
   *  Returns true if verified. If biometrics aren't enrolled, resolves true (no gate to apply). */
  async function verify(): Promise<boolean> {
    const cfg = readCfg()
    if (!cfg.enabled || !cfg.credId) return true
    busy.value = true
    const prfReq = vaultPrfRequest()
    try {
      const a: any = await navigator.credentials.get({
        publicKey: { challenge: rand(), allowCredentials: [{ type: 'public-key', id: b64uToBuf(cfg.credId) }], userVerification: 'required', timeout: 60000,
          ...(prfReq ? { extensions: prfReq.extensions } : {}) },
      })
      if (a) {
        await maybeUnsealFromAssertion(a, prfReq?.salt ?? null)
        try { (navigator as any).vibrate?.(8) } catch {}
        return true
      }
      return false
    } catch { return false }
    finally { busy.value = false }
  }

  /* ── #PK32 the sealed-vault ceremonies ─────────────────────────────────────
   * All three return a reason instead of throwing: the More screen renders the
   * reason verbatim, and a blocked control must say why (TPPS-1 S5). */

  function vaultInfo(): { state: string; kdf: string | null } {
    try { return { state: credentialVault.state(), kdf: credentialVault.kdf() } }
    catch { return { state: 'empty', kdf: null } }
  }

  /** Seal under the lock credential's PRF. `prf-unavailable` means the
   *  enrolled credential predates PRF (or the platform lacks it) — the caller
   *  offers re-enrolment or the device-key fallback, explicitly. */
  async function sealCredentials(): Promise<{ ok: boolean; mode?: 'webauthn-prf'; reason?: string }> {
    const cfg = readCfg()
    if (!cfg.enabled || !cfg.credId) return { ok: false, reason: 'Enroll the biometric lock first — the seal is built on its key.' }
    if (credentialVault.isSealed()) return { ok: false, reason: 'Already sealed.' }
    busy.value = true
    try {
      const salt = newVaultSalt()
      const a: any = await navigator.credentials.get({
        publicKey: {
          challenge: rand(),
          allowCredentials: [{ type: 'public-key', id: b64uToBuf(cfg.credId) }],
          userVerification: 'required', timeout: 60000,
          extensions: { prf: { eval: { first: vB64uToBuf(salt) } } } as any,
        },
      })
      const prfOut = a?.getClientExtensionResults?.()?.prf?.results?.first
      if (!prfOut) return { ok: false, reason: 'prf-unavailable' }
      const key = await vaultKeyFromPrf(prfOut, salt)
      await credentialVault.seal(key, salt, 'webauthn-prf')
      return { ok: true, mode: 'webauthn-prf' }
    } catch (e: any) {
      return { ok: false, reason: e?.message || 'Sealing failed — nothing was changed.' }
    } finally { busy.value = false }
  }

  /** The honest fallback: seal under a NON-EXTRACTABLE device key. Defends the
   *  copyable storage tiers, not code running in this origin — labeled so. */
  async function sealCredentialsDeviceKey(): Promise<{ ok: boolean; mode?: 'device-key'; reason?: string }> {
    if (credentialVault.isSealed()) return { ok: false, reason: 'Already sealed.' }
    busy.value = true
    try {
      const key = await deviceVaultKey()
      await credentialVault.seal(key, newVaultSalt(), 'device-key')
      return { ok: true, mode: 'device-key' }
    } catch (e: any) {
      return { ok: false, reason: e?.message || 'Sealing failed — nothing was changed.' }
    } finally { busy.value = false }
  }

  /** Decrypt back to plaintext storage (the explicit opt-out). */
  async function unsealCredentialsToPlain(): Promise<{ ok: boolean; reason?: string }> {
    const blobKdf = credentialVault.kdf()
    if (!blobKdf) return { ok: false, reason: 'Nothing is sealed.' }
    busy.value = true
    try {
      if (blobKdf === 'device-key') {
        await credentialVault.unsealToPlain(await deviceVaultKey())
        return { ok: true }
      }
      const cfg = readCfg()
      const salt = credentialVault.saltB64u()
      if (!cfg.credId || !salt) return { ok: false, reason: 'The sealing key is gone — restore this device’s lock enrolment or re-import the credentials.' }
      const a: any = await navigator.credentials.get({
        publicKey: {
          challenge: rand(),
          allowCredentials: [{ type: 'public-key', id: b64uToBuf(cfg.credId) }],
          userVerification: 'required', timeout: 60000,
          extensions: { prf: { eval: { first: vB64uToBuf(salt) } } } as any,
        },
      })
      const prfOut = a?.getClientExtensionResults?.()?.prf?.results?.first
      if (!prfOut) return { ok: false, reason: 'The fingerprint key would not evaluate — vault left sealed.' }
      await credentialVault.unsealToPlain(await vaultKeyFromPrf(prfOut, salt))
      return { ok: true }
    } catch (e: any) {
      return { ok: false, reason: e?.message || 'Unseal failed — vault left sealed.' }
    } finally { busy.value = false }
  }

  /** Call once from the Pocket shell: locks on entry (fresh session) + after background grace. */
  function arm() {
    const cfg = readCfg()
    let unlockedThisSession = false
    try { unlockedThisSession = sessionStorage.getItem(SESSION_KEY) === '1' } catch {}
    if (cfg.enabled && !unlockedThisSession) locked.value = true
    if (wired) return
    wired = true
    document.addEventListener('visibilitychange', () => {
      if (!readCfg().enabled) return
      if (document.visibilityState === 'hidden') { hiddenAt = Date.now() }
      else if (hiddenAt && Date.now() - hiddenAt > GRACE_MS) {
        locked.value = true
        try { sessionStorage.removeItem(SESSION_KEY) } catch {}
        // #PK32 — relocking the shell also drops the vault key: past the grace
        // window the decrypted secrets leave memory with the session they
        // belonged to. (device-key vaults reopen without a prompt; prf vaults
        // reopen with the same fingerprint that unlocks the shell.)
        try { if (credentialVault.kdf() === 'webauthn-prf') credentialVault.relock() } catch {}
      }
    })
  }

  return {
    locked, enabled, busy, available, enroll, disable, unlock, verify, arm,
    vaultInfo, sealCredentials, sealCredentialsDeviceKey, unsealCredentialsToPlain,
  }
}
