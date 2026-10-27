/**
 * services/credentialVault.ts — §POCKETBRIDGE #PK32, THE SEALED VAULT.
 *
 * The Commander's ask, verbatim: *"we should probably also take care of a safe
 * way to store credentials on phone. because all those agent credentials need
 * to be safe. how do we do this best?"*
 *
 * WHAT THIS SEALS, AND WITH WHAT.
 * `agentCredentialsStore` persists agent `client_secret`s in plaintext
 * localStorage (its own header documents the trade-off). Those secrets mint
 * agent JWTs that move money. This module encrypts that vault at rest with
 * AES-256-GCM under a key derived from the **WebAuthn PRF extension** of the
 * SAME platform credential the Pocket biometric lock already enrolls — so the
 * key material lives inside the phone's authenticator, and unsealing IS the
 * fingerprint ceremony Pocket already performs. Plaintext exists only in
 * memory, only while the session is unsealed.
 *
 * WHAT THIS DOES AND DOES NOT DEFEND (stated, not implied):
 *   ✓ a copied/backed-up/synced localStorage dump          — ciphertext only
 *   ✓ a stolen device without the owner's biometric        — no key, no vault
 *   ✓ casual devtools reading on a borrowed unlocked phone — while locked
 *   ✗ code executing inside this origin while UNSEALED     — nothing in a
 *     browser defends secrets from the page that legitimately uses them.
 *
 * KEY LADDER (strongest available, never silently downgraded):
 *   'webauthn-prf'  HKDF-SHA256(PRF(credential, vaultSalt)) → AES-GCM-256.
 *                   Requires a PRF-capable enrollment; unseal = biometric.
 *   'device-key'    a NON-EXTRACTABLE AES-GCM CryptoKey kept in IndexedDB.
 *                   Protects the *copyable* storage tiers (localStorage can be
 *                   dumped; a non-extractable key cannot), but any code in the
 *                   origin can USE the key — honestly weaker, and labeled so
 *                   in the UI. Used only when PRF is not available.
 *
 * SAFETY RULES THE STATE MACHINE ENFORCES:
 *   · seal deletes the plaintext ONLY after the ciphertext has been written,
 *     read back, and decrypted again with the same key (self-test) — a failed
 *     encrypt must never cost the user their secrets;
 *   · a write while sealed-LOCKED lands in a plaintext PENDING overlay and is
 *     merged + encrypted at the next unseal (rare — the lock screen stands in
 *     front of every flow that writes — but a lossy write path is a bug);
 *   · GCM authenticates: a tampered blob fails loudly, it does not decrypt to
 *     garbage credentials.
 *
 * The core is dependency-injected (storage + key) so vitest exercises every
 * transition in node; the browser binding at the bottom wires localStorage,
 * IndexedDB and WebCrypto. §BRIDGE R14's rule applies: the state machine is
 * pure enough to test, and the component layer only calls it.
 */

export interface VaultBlob {
  v: 1
  kdf: 'webauthn-prf' | 'device-key'
  salt: string          // b64url — PRF eval input (webauthn-prf) or HKDF salt
  iv: string            // b64url — 12-byte GCM nonce, fresh per encryption
  ct: string            // b64url — ciphertext + GCM tag
  sealed_at: string
}

export type VaultState =
  | 'plain'          // credentials live in the legacy plaintext key
  | 'sealed-locked'  // a blob exists, no key in memory — secrets unreadable
  | 'sealed-open'    // blob exists AND the session key is in memory
  | 'empty'          // nothing stored anywhere

export interface StorageLike {
  getItem(k: string): string | null
  setItem(k: string, v: string): void
  removeItem(k: string): void
}

export const PLAIN_KEY = 'agentvault_agent_credentials'
export const SEALED_KEY = 'agentvault_agent_credentials_sealed'
export const PENDING_KEY = 'agentvault_agent_credentials_pending'

/* ── b64url helpers (shared shape with usePocketLock) ──────────────────────── */
export function bufToB64u(b: ArrayBuffer | Uint8Array): string {
  const u = b instanceof Uint8Array ? b : new Uint8Array(b)
  let s = ''
  for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i])
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
export function b64uToBuf(s: string): Uint8Array {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/'))
  const a = new Uint8Array(b.length)
  for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i)
  return a
}

const subtle = () => (globalThis.crypto as Crypto).subtle
const randBytes = (n: number) => {
  const a = new Uint8Array(n)
  ;(globalThis.crypto as Crypto).getRandomValues(a)
  return a
}

/** PRF output (or any raw secret ≥32 bytes) → non-extractable AES-GCM key.
 *  HKDF with a fixed info string binds the key to this purpose alone. */
export async function deriveAesKeyFromSecret(secret: Uint8Array, salt: Uint8Array): Promise<CryptoKey> {
  const ikm = await subtle().importKey('raw', secret as BufferSource, 'HKDF', false, ['deriveKey'])
  return subtle().deriveKey(
    { name: 'HKDF', hash: 'SHA-256', salt: salt as BufferSource, info: new TextEncoder().encode('tp-pocket-credential-vault-v1') },
    ikm,
    { name: 'AES-GCM', length: 256 },
    false,                       // NON-extractable: the derived key never leaves WebCrypto
    ['encrypt', 'decrypt'],
  )
}

export async function encryptJson(key: CryptoKey, data: unknown): Promise<{ iv: string; ct: string }> {
  const iv = randBytes(12)
  const pt = new TextEncoder().encode(JSON.stringify(data))
  const ct = await subtle().encrypt({ name: 'AES-GCM', iv: iv as BufferSource }, key, pt as BufferSource)
  return { iv: bufToB64u(iv), ct: bufToB64u(ct) }
}

export async function decryptJson(key: CryptoKey, ivB64u: string, ctB64u: string): Promise<any> {
  const pt = await subtle().decrypt(
    { name: 'AES-GCM', iv: b64uToBuf(ivB64u) as BufferSource }, key, b64uToBuf(ctB64u) as BufferSource)
  return JSON.parse(new TextDecoder().decode(pt))
}

/* ── the state machine ─────────────────────────────────────────────────────── */

export class CredentialVaultCore {
  private storage: StorageLike
  /** Session key, memory only, retained while sealed-open so writes can re-encrypt. */
  private key: CryptoKey | null = null
  /** Decrypted credentials, memory only. */
  private mem: Record<string, any> | null = null
  /** Bumped on every open/close/write so Vue consumers can re-read a plain object. */
  version = 0
  /** Listeners for the version bump (the shell shows/hides the sealed banner). */
  private listeners = new Set<() => void>()

  constructor(storage: StorageLike) { this.storage = storage }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  private bump(): void {
    this.version++
    for (const fn of this.listeners) { try { fn() } catch { /* a listener must not break the vault */ } }
  }

  /* ── §OURSTATE-5d: lending the vault's crypto WITHOUT lending its key ─────
     A local message cache wants exactly the protection the credential vault
     already has, and the honest way to get it is to let the vault do the work.
     The session key never leaves this object — no getter, no export — because
     a key handed out is a key that ends up somewhere it cannot be revoked
     from. Callers get ciphertext, or null when the vault is not open. */

  /** Encrypt arbitrary JSON under the OPEN session key. `null` = not open,
   *  which callers must treat as "do not cache", never as "cache in clear". */
  async sealForCache(data: unknown): Promise<{ iv: string; ct: string } | null> {
    if (!this.key) return null
    return encryptJson(this.key, data)
  }

  /** Decrypt what `sealForCache` wrote. Returns null when the vault is closed
   *  OR the blob does not authenticate — a tampered cache reads as absent, and
   *  absence is the safe answer for a cache. */
  async openFromCache(blob: { iv: string; ct: string } | null | undefined): Promise<any | null> {
    if (!this.key || !blob?.iv || !blob?.ct) return null
    try { return await decryptJson(this.key, blob.iv, blob.ct) } catch { return null }
  }

  /** Is there a live key right now? The cache asks before writing, and the UI
   *  asks before it is allowed to use the word "encrypted". */
  canSealCache(): boolean { return !!this.key }

  readBlob(): VaultBlob | null {
    try {
      const raw = this.storage.getItem(SEALED_KEY)
      if (!raw) return null
      const b = JSON.parse(raw)
      return b && b.v === 1 && typeof b.ct === 'string' ? (b as VaultBlob) : null
    } catch { return null }
  }

  state(): VaultState {
    if (this.readBlob()) return this.key && this.mem ? 'sealed-open' : 'sealed-locked'
    try {
      return this.storage.getItem(PLAIN_KEY) ? 'plain' : 'empty'
    } catch { return 'empty' }
  }
  isSealed(): boolean { const s = this.state(); return s === 'sealed-locked' || s === 'sealed-open' }
  isOpen(): boolean { return this.state() !== 'sealed-locked' }
  kdf(): VaultBlob['kdf'] | null { return this.readBlob()?.kdf ?? null }
  /** The PRF eval input for this vault. Created once at seal time. */
  saltB64u(): string | null { return this.readBlob()?.salt ?? null }

  private readPlain(key = PLAIN_KEY): Record<string, any> {
    try { return JSON.parse(this.storage.getItem(key) || '{}') || {} } catch { return {} }
  }

  /** What consumers read. Sealed-locked returns {} — callers that care ask isOpen(). */
  getAll(): Record<string, any> {
    const s = this.state()
    if (s === 'sealed-open') return { ...(this.mem || {}) }
    if (s === 'sealed-locked') return {}
    return this.readPlain()
  }

  /** Write-through. Sealed-locked writes land in the pending overlay (merged at unseal). */
  async setAll(all: Record<string, any>): Promise<void> {
    const s = this.state()
    if (s === 'sealed-open') {
      this.mem = { ...all }
      await this.persistSealed()
    } else if (s === 'sealed-locked') {
      this.storage.setItem(PENDING_KEY, JSON.stringify(all))
    } else {
      this.storage.setItem(PLAIN_KEY, JSON.stringify(all))
    }
    this.bump()
  }

  private async persistSealed(): Promise<void> {
    if (!this.key || this.mem === null) throw new Error('vault is not open')
    const blob = this.readBlob()
    if (!blob) throw new Error('sealed blob missing')
    const { iv, ct } = await encryptJson(this.key, this.mem)
    const next: VaultBlob = { ...blob, iv, ct }
    this.storage.setItem(SEALED_KEY, JSON.stringify(next))
  }

  /**
   * Seal the current plaintext vault under `key`. `saltB64u` records the key's
   * derivation input (the PRF eval salt) so every later unseal asks the SAME
   * question of the authenticator. Plaintext is deleted only after the written
   * blob decrypts again (self-test) — never before.
   */
  async seal(key: CryptoKey, saltB64u: string, kdf: VaultBlob['kdf']): Promise<void> {
    if (this.isSealed()) throw new Error('already sealed')
    const data = this.readPlain()
    const { iv, ct } = await encryptJson(key, data)
    const blob: VaultBlob = { v: 1, kdf, salt: saltB64u, iv, ct, sealed_at: new Date().toISOString() }
    this.storage.setItem(SEALED_KEY, JSON.stringify(blob))
    // Self-test: read back what was actually stored and prove it decrypts.
    const back = this.readBlob()
    if (!back) throw new Error('sealed blob did not persist')
    const round = await decryptJson(key, back.iv, back.ct)
    if (JSON.stringify(round) !== JSON.stringify(data)) throw new Error('seal self-test mismatch')
    this.storage.removeItem(PLAIN_KEY)
    this.key = key
    this.mem = data
    this.bump()
  }

  /** Open a sealed vault with the derived key. Merges any pending writes. */
  async unseal(key: CryptoKey): Promise<void> {
    const blob = this.readBlob()
    if (!blob) throw new Error('nothing is sealed')
    const data = await decryptJson(key, blob.iv, blob.ct)   // GCM throws on wrong key/tamper
    this.key = key
    this.mem = (data && typeof data === 'object') ? data : {}
    const pendingRaw = this.storage.getItem(PENDING_KEY)
    if (pendingRaw) {
      try {
        const pending = JSON.parse(pendingRaw)
        if (pending && typeof pending === 'object') this.mem = { ...this.mem, ...pending }
      } catch { /* unreadable pending: drop rather than corrupt the vault */ }
      this.storage.removeItem(PENDING_KEY)
      await this.persistSealed()
    }
    this.bump()
  }

  /** Decrypt and return to plaintext storage (the explicit opt-out). */
  async unsealToPlain(key: CryptoKey): Promise<void> {
    await this.unseal(key)
    this.storage.setItem(PLAIN_KEY, JSON.stringify(this.mem || {}))
    this.storage.removeItem(SEALED_KEY)
    this.key = null
    this.mem = null
    this.bump()
  }

  /** Drop the session key (relock). The blob stays; secrets leave memory. */
  relock(): void {
    this.key = null
    this.mem = null
    this.bump()
  }
}

/* ── browser binding ───────────────────────────────────────────────────────── */

const memoryStorage = (): StorageLike => {
  const m = new Map<string, string>()
  return { getItem: k => m.get(k) ?? null, setItem: (k, v) => { m.set(k, v) }, removeItem: k => { m.delete(k) } }
}

export const credentialVault = new CredentialVaultCore(
  typeof window !== 'undefined' && window.localStorage ? window.localStorage : memoryStorage(),
)

/** Fresh 32-byte PRF salt for a new seal. */
export function newVaultSalt(): string { return bufToB64u(randBytes(32)) }

/**
 * webauthn-prf path: turn a PRF output (BufferSource from
 * getClientExtensionResults().prf.results.first) into the vault key.
 * The blob's own salt doubles as HKDF salt — one recorded input, two uses.
 */
export async function vaultKeyFromPrf(prfOutput: ArrayBuffer | Uint8Array, saltB64u: string): Promise<CryptoKey> {
  const secret = prfOutput instanceof Uint8Array ? prfOutput : new Uint8Array(prfOutput)
  return deriveAesKeyFromSecret(secret, b64uToBuf(saltB64u))
}

/* device-key fallback: a NON-EXTRACTABLE AES key parked in IndexedDB. */
const IDB_DB = 'tp_pocket_vault'
const IDB_STORE = 'keys'
const IDB_KEY = 'vault-key-v1'

function idbOpen(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_DB, 1)
    req.onupgradeneeded = () => { req.result.createObjectStore(IDB_STORE) }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}
function idbGet(db: IDBDatabase): Promise<CryptoKey | null> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readonly').objectStore(IDB_STORE).get(IDB_KEY)
    tx.onsuccess = () => resolve(tx.result || null)
    tx.onerror = () => reject(tx.error)
  })
}
function idbPut(db: IDBDatabase, key: CryptoKey): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite').objectStore(IDB_STORE).put(key, IDB_KEY)
    tx.onsuccess = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/** Get (or mint) the device-key fallback. Non-extractable by construction. */
export async function deviceVaultKey(): Promise<CryptoKey> {
  const db = await idbOpen()
  try {
    const existing = await idbGet(db)
    if (existing) return existing
    const key = await subtle().generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
    await idbPut(db, key as CryptoKey)
    return key as CryptoKey
  } finally { db.close() }
}
