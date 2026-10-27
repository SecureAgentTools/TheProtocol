/**
 * §OURSTATE-5d — the encrypted local cache.
 *
 * The property that matters is not "a cache works". It is that a cache which
 * CANNOT be encrypted writes NOTHING — a plaintext fallback would quietly undo
 * the only reason the cache is allowed to exist.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  putThread, getThread, dropThread, dropAll, burnDeviceNote, cacheAvailable, MAX_MESSAGES,
} from '../localCache'
import { credentialVault, deriveAesKeyFromSecret } from '@/services/credentialVault'

class MemStore {
  map = new Map<string, string>()
  get length() { return this.map.size }
  key(i: number) { return Array.from(this.map.keys())[i] ?? null }
  getItem(k: string) { return this.map.has(k) ? this.map.get(k)! : null }
  setItem(k: string, v: string) { this.map.set(k, v) }
  removeItem(k: string) { this.map.delete(k) }
}

/** Put a real AES key into the vault the way an unsealed session would, so the
 *  crypto under test is the crypto that ships — not a stub that always says
 *  yes. */
async function openVault() {
  const secret = new Uint8Array(32).fill(7)
  const salt = new Uint8Array(32).fill(9)
  const key = await deriveAesKeyFromSecret(secret, salt)
  ;(credentialVault as any).key = key
}
function lockVault() { (credentialVault as any).key = null }

describe('§OURSTATE-5d local cache', () => {
  let st: MemStore
  beforeEach(() => { st = new MemStore(); lockVault() })

  it('writes NOTHING when the vault cannot seal it', async () => {
    const wrote = await putThread('c1', [{ id: 'm1', body: 'secret' }], st)
    expect(wrote).toBe(false)
    expect(st.length).toBe(0)
    // …and nothing on disk carries the plaintext, which is the actual claim.
    expect(JSON.stringify([...st.map.values()])).not.toContain('secret')
  })

  it('round-trips through the vault when it is open', async () => {
    await openVault()
    expect(cacheAvailable()).toBe(true)
    const wrote = await putThread('c1', [{ id: 'm1', body: 'hello there' }], st)
    expect(wrote).toBe(true)
    const back = await getThread('c1', st)
    expect(back?.messages?.[0]?.body).toBe('hello there')
  })

  it('stores ciphertext, not the message', async () => {
    await openVault()
    await putThread('c1', [{ id: 'm1', body: 'a very distinctive phrase' }], st)
    const raw = st.getItem('ourstate_cache_v1:c1') || ''
    expect(raw).not.toContain('very distinctive phrase')
    expect(JSON.parse(raw)).toHaveProperty('iv')
    expect(JSON.parse(raw)).toHaveProperty('ct')
  })

  it('reads as ABSENT once the vault locks again', async () => {
    await openVault()
    await putThread('c1', [{ id: 'm1', body: 'hello' }], st)
    lockVault()
    expect(await getThread('c1', st)).toBeNull()
  })

  it('treats a tampered blob as absent, never as an error to act on', async () => {
    await openVault()
    await putThread('c1', [{ id: 'm1', body: 'hello' }], st)
    const raw = JSON.parse(st.getItem('ourstate_cache_v1:c1')!)
    raw.ct = raw.ct.slice(0, -4) + 'AAAA'
    st.setItem('ourstate_cache_v1:c1', JSON.stringify(raw))
    expect(await getThread('c1', st)).toBeNull()
  })

  it('bounds what it keeps', async () => {
    await openVault()
    const many = Array.from({ length: MAX_MESSAGES + 20 }, (_, i) => ({ id: `m${i}` }))
    await putThread('c1', many, st)
    const back = await getThread('c1', st)
    expect(back!.messages.length).toBe(MAX_MESSAGES)
    // the TAIL is what a reader wants — the newest messages, not the oldest
    expect(back!.messages[back!.messages.length - 1].id).toBe(`m${MAX_MESSAGES + 19}`)
  })

  it('burn-for-me destroys this thread and leaves the others', async () => {
    await openVault()
    await putThread('c1', [{ id: 'a' }], st)
    await putThread('c2', [{ id: 'b' }], st)
    dropThread('c1', st)
    expect(await getThread('c1', st)).toBeNull()
    expect(await getThread('c2', st)).not.toBeNull()
  })

  it('dropAll clears every cached thread and nothing else', async () => {
    await openVault()
    await putThread('c1', [{ id: 'a' }], st)
    await putThread('c2', [{ id: 'b' }], st)
    st.setItem('unrelated_key', 'keep me')
    expect(dropAll(st)).toBe(2)
    expect(st.getItem('unrelated_key')).toBe('keep me')
  })

  it('only claims "encrypted" when there really was an encrypted copy', () => {
    // §11: the word has to be earned. With no vault there was no protected
    // copy, and saying otherwise is the privacy theater law 5 forbids.
    expect(burnDeviceNote(true)).toMatch(/encrypted/i)
    expect(burnDeviceNote(false)).toBeNull()
  })

  it('a storage that throws never breaks a send', async () => {
    await openVault()
    const hostile = {
      ...new MemStore(),
      setItem: () => { throw new Error('quota') },
      getItem: () => { throw new Error('nope') },
      removeItem: () => { throw new Error('nope') },
      key: () => null, length: 0,
    } as any
    expect(await putThread('c1', [{ id: 'a' }], hostile)).toBe(false)
    expect(await getThread('c1', hostile)).toBeNull()
    expect(() => dropThread('c1', hostile)).not.toThrow()
  })
})
