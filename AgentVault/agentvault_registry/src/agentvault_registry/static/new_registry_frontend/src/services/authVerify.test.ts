import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('./api/client', () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }))

import { authApi } from './api/auth'
import { authService } from './auth'
import { config } from '@/config'

/**
 * §FESUITE (2026-10-01): "could not verify" is not "invalid".
 *
 * `authApi.verify()` turned EVERY failure of GET /developers/me into `{ valid: false, user: null }`, and
 * `verifySession()` then wrote that null over the stored user and returned it, so the store ended the session. A page
 * load while the registry restarted (a 502) or sat at its database's connection ceiling (a 503, measured on sbx-alpha)
 * signed the person out. Only a refusal (401/403) says the session is not valid; anything else is thrown.
 */
const failing = (status?: number) => Object.assign(new Error(`status ${status ?? 'none'}`), status ? { response: { status } } : {})

function b64url(o: unknown): string {
  return btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
}
/** An access token jwt-decode reads as unexpired (the session under test is live). */
const liveToken = `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 })}.sig`

const STORED = { id: '7', email: 'dev@example.test', name: 'Dev', role: 'developer', is_admin: false }

beforeEach(() => {
  get.mockReset()
  window.localStorage.clear()
  window.sessionStorage.clear()
  window.sessionStorage.setItem(config.auth.tokenKey, liveToken)
})

describe('authApi.verify answers a refusal and throws "could not verify"', () => {
  it('a 401 and a 403 are refusals: valid false', async () => {
    for (const status of [401, 403]) {
      get.mockRejectedValueOnce(failing(status))
      expect((await authApi.verify()).valid).toBe(false)
    }
  })

  it('a 503, a 502 and no response at all are thrown, never "invalid"', async () => {
    for (const status of [503, 502, undefined]) {
      get.mockRejectedValueOnce(failing(status))
      await expect(authApi.verify()).rejects.toThrow()
    }
  })

  it('a profile is a valid session', async () => {
    get.mockResolvedValueOnce({ data: { id: 7, email: 'dev@example.test', is_admin: false } })
    const r = await authApi.verify()
    expect(r.valid).toBe(true)
    expect(r.user.email).toBe('dev@example.test')
  })
})

describe('verifySession keeps a session the registry could not check', () => {
  it('could not verify, with a stored user: the stored user carries on, untouched', async () => {
    window.sessionStorage.setItem(config.auth.userKey, JSON.stringify(STORED))
    get.mockRejectedValueOnce(failing(503))
    expect(await authService.verifySession()).toEqual(STORED)
    expect(JSON.parse(window.sessionStorage.getItem(config.auth.userKey) as string)).toEqual(STORED)
  })

  it('could not verify, with no stored user: the caller is told (it keeps the session), nothing is written', async () => {
    get.mockRejectedValueOnce(failing(503))
    await expect(authService.verifySession()).rejects.toThrow()
    expect(window.sessionStorage.getItem(config.auth.userKey)).toBeNull()
    expect(window.localStorage.getItem(config.auth.userKey)).toBeNull()
  })

  it('a refusal is null, and null is never written over the stored user', async () => {
    window.sessionStorage.setItem(config.auth.userKey, JSON.stringify(STORED))
    get.mockRejectedValueOnce(failing(401))
    expect(await authService.verifySession()).toBeNull()
    expect(window.sessionStorage.getItem(config.auth.userKey)).not.toBe('null')
  })

  it('a verified profile is stored and returned', async () => {
    get.mockResolvedValueOnce({ data: { id: 7, email: 'dev@example.test', is_admin: true } })
    const u = await authService.verifySession()
    expect(u?.role).toBe('admin')
    expect(JSON.parse(window.sessionStorage.getItem(config.auth.userKey) as string).email).toBe('dev@example.test')
  })
})
