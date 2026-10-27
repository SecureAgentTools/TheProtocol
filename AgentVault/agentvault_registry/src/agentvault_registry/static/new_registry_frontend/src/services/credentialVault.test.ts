/**
 * credentialVault.test.ts — §POCKETBRIDGE #PK32.
 *
 * The state machine and the crypto, exercised in node (webcrypto is global
 * since Node 18). The WebAuthn PRF half cannot run here — the battery drives
 * it with a CDP virtual authenticator where the runtime supports PRF, and the
 * key-provider seam these tests use is exactly the seam the browser fills.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import {
  CredentialVaultCore, deriveAesKeyFromSecret, encryptJson, decryptJson,
  bufToB64u, b64uToBuf, PLAIN_KEY, SEALED_KEY, PENDING_KEY,
  type StorageLike,
} from './credentialVault'

function fakeStorage(): StorageLike & { dump(): Record<string, string> } {
  const m = new Map<string, string>()
  return {
    getItem: k => m.get(k) ?? null,
    setItem: (k, v) => { m.set(k, v) },
    removeItem: k => { m.delete(k) },
    dump: () => Object.fromEntries(m),
  }
}

const SECRET = new Uint8Array(32).fill(7)
const OTHER = new Uint8Array(32).fill(9)
const SALT = new Uint8Array(32).fill(3)
const saltB64u = bufToB64u(SALT)

const CREDS = {
  'did:theprotocol:alpha': { did: 'did:theprotocol:alpha', client_id: 'c1', client_secret: 's1', name: 'Alpha' },
  'did:theprotocol:beta': { did: 'did:theprotocol:beta', client_id: 'c2', client_secret: 's2' },
}

describe('crypto primitives', () => {
  it('b64url roundtrips bytes exactly', () => {
    const bytes = new Uint8Array([0, 1, 250, 251, 252, 253, 254, 255, 62, 63])
    expect(Array.from(b64uToBuf(bufToB64u(bytes)))).toEqual(Array.from(bytes))
  })

  it('encrypt/decrypt roundtrips JSON under a derived key', async () => {
    const key = await deriveAesKeyFromSecret(SECRET, SALT)
    const { iv, ct } = await encryptJson(key, CREDS)
    expect(await decryptJson(key, iv, ct)).toEqual(CREDS)
  })

  it('the derivation is deterministic — same secret+salt opens what another instance sealed', async () => {
    const k1 = await deriveAesKeyFromSecret(SECRET, SALT)
    const k2 = await deriveAesKeyFromSecret(SECRET, SALT)
    const { iv, ct } = await encryptJson(k1, { a: 1 })
    expect(await decryptJson(k2, iv, ct)).toEqual({ a: 1 })
  })

  it('a wrong key does not decrypt to garbage — it throws (GCM authenticates)', async () => {
    const key = await deriveAesKeyFromSecret(SECRET, SALT)
    const wrong = await deriveAesKeyFromSecret(OTHER, SALT)
    const { iv, ct } = await encryptJson(key, CREDS)
    await expect(decryptJson(wrong, iv, ct)).rejects.toThrow()
  })

  it('a tampered ciphertext throws', async () => {
    const key = await deriveAesKeyFromSecret(SECRET, SALT)
    const { iv, ct } = await encryptJson(key, CREDS)
    const bytes = b64uToBuf(ct)
    bytes[0] ^= 0xff
    await expect(decryptJson(key, iv, bufToB64u(bytes))).rejects.toThrow()
  })
})

describe('CredentialVaultCore state machine', () => {
  let storage: ReturnType<typeof fakeStorage>
  let vault: CredentialVaultCore
  let key: CryptoKey

  beforeEach(async () => {
    storage = fakeStorage()
    vault = new CredentialVaultCore(storage)
    key = await deriveAesKeyFromSecret(SECRET, SALT)
  })

  it('starts empty, becomes plain on a write', async () => {
    expect(vault.state()).toBe('empty')
    await vault.setAll(CREDS)
    expect(vault.state()).toBe('plain')
    expect(vault.getAll()).toEqual(CREDS)
  })

  it('seal encrypts, self-tests, and only THEN deletes the plaintext', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    expect(vault.state()).toBe('sealed-open')
    expect(storage.getItem(PLAIN_KEY)).toBeNull()
    const blob = JSON.parse(storage.getItem(SEALED_KEY) as string)
    expect(blob.kdf).toBe('webauthn-prf')
    // ⚠ Assert the JSON KEY, not the 2-char secret value: a 2-char substring
    // lands in ~400 chars of random base64 roughly one run in ten — this
    // assertion failed on a healthy vault before it was taught that.
    expect(storage.getItem(SEALED_KEY)).not.toContain('client_secret')      // ciphertext, not JSON
    expect(vault.getAll()).toEqual(CREDS)                   // memory serves reads
  })

  it('sealing twice is refused', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    await expect(vault.seal(key, saltB64u, 'webauthn-prf')).rejects.toThrow()
  })

  it('relock drops the secrets from reads; storage holds only ciphertext', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    vault.relock()
    expect(vault.state()).toBe('sealed-locked')
    expect(vault.getAll()).toEqual({})
    expect(JSON.stringify(storage.dump())).not.toContain('client_secret')
  })

  it('unseal with the right key restores; with the wrong key it stays locked', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    vault.relock()
    const wrong = await deriveAesKeyFromSecret(OTHER, SALT)
    await expect(vault.unseal(wrong)).rejects.toThrow()
    expect(vault.state()).toBe('sealed-locked')
    await vault.unseal(key)
    expect(vault.getAll()).toEqual(CREDS)
  })

  it('a write while sealed-LOCKED lands in pending and merges at unseal — never lost, never plaintext-forever', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    vault.relock()
    const extra = { 'did:theprotocol:gamma': { did: 'did:theprotocol:gamma', client_id: 'c3', client_secret: 's3' } }
    await vault.setAll({ ...extra })                        // locked: goes to PENDING
    expect(storage.getItem(PENDING_KEY)).toContain('gamma')
    await vault.unseal(key)
    expect(storage.getItem(PENDING_KEY)).toBeNull()         // merged and cleared
    expect(vault.getAll()['did:theprotocol:gamma']).toBeTruthy()
    expect(vault.getAll()['did:theprotocol:alpha']).toBeTruthy()
    // and the merge was re-encrypted: a fresh core with the key sees it too
    const fresh = new CredentialVaultCore(storage)
    await fresh.unseal(await deriveAesKeyFromSecret(SECRET, SALT))
    expect(fresh.getAll()['did:theprotocol:gamma']).toBeTruthy()
  })

  it('writes while sealed-open re-encrypt: a fresh instance with the key reads the update', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    const next = { ...CREDS, 'did:theprotocol:delta': { did: 'did:theprotocol:delta', client_id: 'c4', client_secret: 's4' } }
    await vault.setAll(next)
    const fresh = new CredentialVaultCore(storage)
    expect(fresh.state()).toBe('sealed-locked')
    await fresh.unseal(await deriveAesKeyFromSecret(SECRET, SALT))
    expect(Object.keys(fresh.getAll())).toHaveLength(3)
  })

  it('unsealToPlain is the explicit opt-out: plaintext restored, blob gone', async () => {
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    vault.relock()
    await vault.unsealToPlain(await deriveAesKeyFromSecret(SECRET, SALT))
    expect(vault.state()).toBe('plain')
    expect(storage.getItem(SEALED_KEY)).toBeNull()
    expect(vault.getAll()).toEqual(CREDS)
  })

  it('version bumps + onChange fires on every transition a consumer can observe', async () => {
    let fired = 0
    vault.onChange(() => { fired++ })
    await vault.setAll(CREDS)
    await vault.seal(key, saltB64u, 'webauthn-prf')
    vault.relock()
    await vault.unseal(key)
    expect(fired).toBeGreaterThanOrEqual(4)
  })
})
