/**
 * §OURSTATE-5d — the encrypted local message cache.
 *
 * Why it exists: a thread should open instantly and still read on a train with
 * no signal. Why it is built THIS way: the strategy's §11 sets one condition on
 * a local copy — *"when an encrypted local cache exists, burn-for-me
 * additionally destroys the local key material, and only then does the word
 * 'cryptographic' appear in the UI."*
 *
 * So the rule here is absolute and simple:
 *
 *     **No key, no cache.**
 *
 * If the sealed vault (§POCKETCREDS) is open, messages are cached as AES-GCM
 * ciphertext under its session key — which this module never sees, because the
 * vault does the sealing. If the vault is locked or was never set up, nothing
 * is written at all. A plaintext chat cache on a phone is a copy of your
 * conversations sitting in a place any other script on the origin can read,
 * and "faster scrolling" is not worth that trade.
 *
 * What this is NOT:
 *   * NOT end-to-end encryption. The registry still hosts the thread in clear
 *     and the header still says whose registry it is (law 5). This protects
 *     the copy ON THIS DEVICE, nothing more, and the UI wording says exactly
 *     that — never "encrypted chat", which would be a lie about the hosting.
 *   * NOT a source of truth. It is a cache: the server's answer always wins,
 *     and a cache that fails to decrypt is treated as absent rather than as an
 *     error worth interrupting anyone about.
 */
import { credentialVault } from '@/services/credentialVault'

const PREFIX = 'ourstate_cache_v1:'
/** Bounded on purpose: a phone should not accumulate a year of threads. */
export const MAX_MESSAGES = 60

export interface CachedThread {
  messages: any[]
  cached_at: string
}

export interface CacheStorage {
  getItem(k: string): string | null
  setItem(k: string, v: string): void
  removeItem(k: string): void
  key(i: number): string | null
  readonly length: number
}

function store(s?: CacheStorage): CacheStorage | null {
  if (s) return s
  try { return window.localStorage as unknown as CacheStorage } catch { return null }
}

const keyFor = (convId: string) => `${PREFIX}${convId}`

/** Write the tail of a thread, encrypted. Returns whether anything was stored,
 *  so a caller can tell "cached" from "not cacheable" instead of assuming. */
export async function putThread(convId: string, messages: any[],
                                s?: CacheStorage): Promise<boolean> {
  const st = store(s)
  if (!st || !convId) return false
  const sealed = await credentialVault.sealForCache({
    messages: (messages || []).slice(-MAX_MESSAGES),
    cached_at: new Date().toISOString(),
  } as CachedThread)
  // The whole point: no key, no write. Not a degraded plaintext write.
  if (!sealed) return false
  try {
    st.setItem(keyFor(convId), JSON.stringify(sealed))
    return true
  } catch { return false }   // quota / private mode: a cache may always fail
}

/** Read a thread back, or null. Null covers every failure — locked vault,
 *  absent entry, tampered blob — because a cache has exactly one useful
 *  answer when it cannot serve: "ask the server". */
export async function getThread(convId: string, s?: CacheStorage): Promise<CachedThread | null> {
  const st = store(s)
  if (!st || !convId) return null
  let raw: string | null = null
  try { raw = st.getItem(keyFor(convId)) } catch { return null }
  if (!raw) return null
  let blob: any = null
  try { blob = JSON.parse(raw) } catch { return null }
  const out = await credentialVault.openFromCache(blob)
  if (!out || !Array.isArray(out.messages)) return null
  return out as CachedThread
}

/** Destroy this thread's local copy. Called by burn-for-me — and the reason
 *  burn can honestly mention the device copy at all. */
export function dropThread(convId: string, s?: CacheStorage): void {
  const st = store(s)
  if (!st || !convId) return
  try { st.removeItem(keyFor(convId)) } catch { /* nothing to do */ }
}

/** Destroy every cached thread (sign-out, vault reset). */
export function dropAll(s?: CacheStorage): number {
  const st = store(s)
  if (!st) return 0
  const doomed: string[] = []
  for (let i = 0; i < st.length; i++) {
    const k = st.key(i)
    if (k && k.startsWith(PREFIX)) doomed.push(k)
  }
  for (const k of doomed) { try { st.removeItem(k) } catch { /* keep going */ } }
  return doomed.length
}

/** The sentence the burn footnote may add — and ONLY when a device copy was
 *  actually encrypted. The word "encrypted" has to be earned per §11; with no
 *  vault there was no protected copy, and claiming one would be exactly the
 *  privacy theater law 5 forbids. */
export function burnDeviceNote(hadEncryptedCopy: boolean): string | null {
  return hadEncryptedCopy
    ? 'The copy on this device was encrypted and has been deleted.'
    : null
}

/** Is caching possible right now? The UI asks before it says anything about
 *  a device copy at all. */
export function cacheAvailable(): boolean {
  return credentialVault.canSealCache()
}
