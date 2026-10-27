/**
 * COCKPIT CARD — device signer (2026-07-25, WebAuthn).
 *
 * Replaces the earlier WebCrypto signer. That one held a non-extractable key, which proves the
 * key cannot be stolen but does NOT require a human to be present when it is used — it signed
 * silently. For a liability confirmation that is precisely the wrong property.
 *
 * WebAuthn fixes it at the layer that can actually enforce it. A platform credential created with
 * `userVerification: "required"` lives in the phone's hardware keystore, and the operating system
 * refuses to produce an assertion without a fingerprint or device PIN. The proof is not our word:
 * the authenticator sets the UV bit inside the signed authenticator data, and the server rejects
 * any assertion where it is clear. Our JavaScript cannot fake it, and neither can an attacker who
 * has taken over this page.
 *
 * The challenge signed is the server's challenge hash — the hash of the exact facts on screen —
 * so an assertion can never be replayed onto a different action.
 */

import { pocketCredentialId } from './usePocketLock'

// TS 5.7+ types a Uint8Array by its buffer; WebAuthn and Push take a BufferSource, which excludes a buffer that could be
// shared, so these helpers say what they return: a fresh ArrayBuffer-backed array.
function b64uToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}

function bytesToB64u(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let s = ''
  bytes.forEach(b => { s += String.fromCharCode(b) })
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(hex.length / 2)
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16)
  return out
}

export interface RegistrationOptions {
  rp: { id: string; name: string }
  user: { id: string; name: string; displayName: string }
  challenge: string
  pubKeyCredParams: Array<{ type: string; alg: number }>
  timeout: number
  attestation: string
  authenticatorSelection: Record<string, any>
}

export interface AssertionResult {
  credential_id: string
  authenticator_data: string
  client_data_json: string
  signature: string
}

export function useDeviceSigner() {
  const supported =
    typeof window !== 'undefined' &&
    !!window.PublicKeyCredential &&
    typeof navigator !== 'undefined' &&
    !!navigator.credentials

  /** Is a built-in (fingerprint/face/PIN) authenticator actually available on this device? */
  async function platformAvailable(): Promise<boolean> {
    if (!supported) return false
    try {
      return await (window.PublicKeyCredential as any).isUserVerifyingPlatformAuthenticatorAvailable()
    } catch { return false }
  }

  /** Create the credential. The OS prompts for the fingerprint here, at enrolment. */
  async function register(opts: RegistrationOptions): Promise<{ attestation_object: string; client_data_json: string }> {
    if (!supported) throw new Error('This device cannot hold a biometric credential.')
    const cred = (await navigator.credentials.create({
      publicKey: {
        rp: opts.rp,
        user: {
          id: b64uToBytes(opts.user.id),
          name: opts.user.name,
          displayName: opts.user.displayName,
        },
        challenge: b64uToBytes(opts.challenge),
        pubKeyCredParams: opts.pubKeyCredParams as any,
        timeout: opts.timeout,
        attestation: opts.attestation as AttestationConveyancePreference,
        authenticatorSelection: opts.authenticatorSelection,
      },
    })) as PublicKeyCredential | null
    if (!cred) throw new Error('Enrolment was cancelled.')
    const res = cred.response as AuthenticatorAttestationResponse
    return {
      attestation_object: bytesToB64u(res.attestationObject),
      client_data_json: bytesToB64u(res.clientDataJSON),
    }
  }

  /**
   * Sign a confirmation. `challengeHashHex` is the server's sha256 over the exact facts shown.
   * The OS raises the biometric prompt — there is no code path that skips it.
   */
  async function sign(challengeHashHex: string, credentialIdB64u?: string): Promise<AssertionResult> {
    if (!supported) throw new Error('This device cannot produce a signed confirmation.')
    // Always target THIS device's enrolled credential. With no allowCredentials the browser opens
    // the account passkey picker instead of the app's own biometric — which is exactly the
    // confusing "Google approval" sheet that made an approval look done when nothing was sent.
    const credId = credentialIdB64u || pocketCredentialId()
    if (!credId) {
      throw new Error('No biometric enrolled on this device. Enable it in Pocket → More → biometric lock.')
    }
    const assertion = (await navigator.credentials.get({
      publicKey: {
        challenge: hexToBytes(challengeHashHex),
        timeout: 120000,
        userVerification: 'required',   // the OS enforces this; the server re-checks the UV bit
        allowCredentials: [{ type: 'public-key', id: b64uToBytes(credId) }],
      },
    })) as PublicKeyCredential | null
    if (!assertion) throw new Error('Confirmation was cancelled.')
    const res = assertion.response as AuthenticatorAssertionResponse
    return {
      credential_id: assertion.id,
      authenticator_data: bytesToB64u(res.authenticatorData),
      client_data_json: bytesToB64u(res.clientDataJSON),
      signature: bytesToB64u(res.signature),
    }
  }

  return { supported, platformAvailable, register, sign }
}
