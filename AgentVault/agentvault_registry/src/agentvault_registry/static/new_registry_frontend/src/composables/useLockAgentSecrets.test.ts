/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): the one press that locks an agent's secret in this
 * browser is Pocket's own ceremony: enrol the device unlock when it is not enrolled, then seal under its key; a device
 * that cannot derive the key is offered the weaker device-key seal explicitly, never silently; a cancelled enrolment
 * changes nothing and says so. BASE (V0652): there is no such press outside Pocket's settings.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ lock: null as any }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => h.lock }))

import { placeOf, useLockAgentSecrets } from './useLockAgentSecrets'

function lock(o: { enabled?: boolean; enroll?: boolean; seal?: any; device?: any; state?: string; available?: boolean } = {}) {
  const info: { state: string; kdf: string | null } = { state: o.state ?? 'plain', kdf: null }
  h.lock = {
    enabled: ref(!!o.enabled),
    available: vi.fn(async () => o.available !== false),
    enroll: vi.fn(async () => { if (o.enroll !== false) h.lock.enabled.value = true; return o.enroll !== false }),
    sealCredentials: vi.fn(async () => {
      const r = o.seal ?? { ok: true }
      if (r.ok) { info.state = 'sealed-open'; info.kdf = 'webauthn-prf' }
      return r
    }),
    sealCredentialsDeviceKey: vi.fn(async () => {
      const r = o.device ?? { ok: true }
      if (r.ok) { info.state = 'sealed-open'; info.kdf = 'device-key' }
      return r
    }),
    vaultInfo: () => ({ ...info }),
  }
  return h.lock
}

beforeEach(() => lock())

describe('where a secret sits', () => {
  it('reads the vault state and its key', () => {
    expect(placeOf({ state: 'plain', kdf: null })).toBe('plain')
    expect(placeOf({ state: 'sealed-open', kdf: 'webauthn-prf' })).toBe('sealed-fingerprint')
    expect(placeOf({ state: 'sealed-locked', kdf: 'device-key' })).toBe('sealed-device')
    expect(placeOf({ state: 'sealed-open', kdf: null })).toBe('sealed')
    expect(placeOf({ state: 'empty', kdf: null })).toBe('none')
  })
})

describe('the one press', () => {
  it('enrols the device unlock, then seals', async () => {
    const l = lock()
    const s = useLockAgentSecrets()
    expect(s.place.value).toBe('plain')
    expect(await s.lockNow()).toBe(true)
    expect(l.enroll).toHaveBeenCalledTimes(1)
    expect(l.sealCredentials).toHaveBeenCalledTimes(1)
    expect(s.place.value).toBe('sealed-fingerprint')
    expect(s.msg.value, 'the line says it; no message repeats it (the drive at cf500f9e6 showed both)').toBe('')
  })

  it('seals at once where the lock is already enrolled', async () => {
    const l = lock({ enabled: true })
    const s = useLockAgentSecrets()
    expect(await s.lockNow()).toBe(true)
    expect(l.enroll).not.toHaveBeenCalled()
  })

  it('changes nothing when the enrolment is cancelled, and says so', async () => {
    const l = lock({ enroll: false })
    const s = useLockAgentSecrets()
    expect(await s.lockNow()).toBe(false)
    expect(l.sealCredentials).not.toHaveBeenCalled()
    expect(s.place.value).toBe('plain')
    expect(s.msg.value).toContain('not set up')
  })

  it('offers the device-key seal where the device cannot derive a key, and never seals with it unasked', async () => {
    const l = lock({ seal: { ok: false, reason: 'prf-unavailable' } })
    const s = useLockAgentSecrets()
    expect(await s.lockNow()).toBe(false)
    expect(s.offerDeviceKey.value).toBe(true)
    expect(l.sealCredentialsDeviceKey).not.toHaveBeenCalled()
    expect(s.place.value).toBe('plain')
    expect(await s.sealWithDeviceKey()).toBe(true)
    expect(s.place.value).toBe('sealed-device')
    expect(s.offerDeviceKey.value).toBe(false)
    expect(s.msg.value).toBe('')
  })

  it('offers the device-key seal at once where the device has no fingerprint or face unlock', async () => {
    const l = lock({ available: false })
    const s = useLockAgentSecrets()
    expect(await s.lockNow()).toBe(false)
    expect(l.enroll).not.toHaveBeenCalled()
    expect(s.offerDeviceKey.value).toBe(true)
    expect(s.msg.value).toContain('no fingerprint or face unlock')
  })

  it('over plain http says the page is not served over HTTPS, and offers no seal that cannot run', async () => {
    // RED on 897009979: it blamed the device ("no fingerprint or face unlock") and offered the device key, whose seal
    // then failed with a raw error (WebCrypto is absent outside a secure context; the drive measured both)
    const l = lock()
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    try {
      const s = useLockAgentSecrets()
      expect(await s.lockNow()).toBe(false)
      expect(s.msg.value).toContain('not served over HTTPS')
      expect(s.offerDeviceKey.value).toBe(false)
      expect(l.enroll).not.toHaveBeenCalled()
      expect(await s.sealWithDeviceKey()).toBe(false)
      expect(l.sealCredentialsDeviceKey).not.toHaveBeenCalled()
      expect(s.place.value).toBe('plain')
    } finally {
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    }
  })

  it("shows a refusal's own words", async () => {
    lock({ seal: { ok: false, reason: 'Already sealed.' } })
    const s = useLockAgentSecrets()
    await s.lockNow()
    expect(s.msg.value).toBe('Already sealed.')
  })
})
