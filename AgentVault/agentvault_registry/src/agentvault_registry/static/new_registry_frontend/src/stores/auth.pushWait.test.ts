/**
 * §FESUITE (2026-10-10, lifecycle 84): a sign-in waiting for the phone's fingerprint, on the device that signs in.
 *  - When the wait ends without a sign-in, the page says what happened and what to do next: it said the bare state
 *    ("Sign-in denied", "Sign-in expired", "Approval expired", "Sign-in request no longer exists").
 *  - The person can stop waiting: the wait ends at once, says nothing went wrong, and a later approval on the phone
 *    signs nothing in here.
 *  - The control: an approval on the phone still signs this device in.
 * The store's own harness (auth.ownedAgentPick.test.ts); the registry's push-login rail answered per test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const push = vi.hoisted(() => ({ status: vi.fn(), token: vi.fn(), challenge: vi.fn(), approveDirect: vi.fn() }))
vi.mock('@/services/api/pushLogin', () => ({ pushLoginApi: push }))
const ui = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }))
vi.mock('./ui', () => ({ useUIStore: () => ui }))
vi.mock('./globalReset', () => ({ globalReset: vi.fn() }))

import { apiClient } from '@/services/api/client'
import { authService } from '@/services/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentDidsCache } from '@/services/agentDidsCache'
import { useAuthStore } from './auth'

const notFound = () => Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } })

beforeEach(() => {
  localStorage.clear()
  Object.values(push).forEach(f => f.mockReset())
  vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'isAuthenticated').mockReturnValue(false)
  vi.spyOn(authService, 'setTokens').mockImplementation(() => {})
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({} as any)
  vi.spyOn(agentCredentialsStore, 'mergeWithStoredCredentials').mockImplementation((a: any) => a)
  vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null)
  vi.spyOn(agentDidsCache, 'cacheAgents').mockImplementation(() => {})
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] } as any)
  vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} } as any)
  setActivePinia(createPinia())
})

afterEach(() => { vi.restoreAllMocks() })

/** a sign-in the registry answered with "approve on your phone" (no token yet) */
function waiting(expiresIn = 120) {
  const store = useAuthStore()
  store.pushApprovalId = 'lgn_test'
  store.pushApprovalExpiresIn = expiresIn
  return store
}

describe('the end of a wait for the phone says what happened and what to do next', () => {
  it('denied on the phone', async () => {
    push.status.mockResolvedValue({ status: 'denied' })
    const store = waiting()
    expect(await store.completePushLogin()).toBe(false)
    expect(store.error).toBe('Your phone denied this sign-in.')
    expect(store.pushApprovalId).toBe('')
  })

  it('the registry expired the request', async () => {
    push.status.mockResolvedValue({ status: 'expired' })
    const store = waiting()
    expect(await store.completePushLogin()).toBe(false)
    expect(store.error).toMatch(/not approved in time\. sign in again to send a new request to your phone/i)
  })

  it('the wait ran out on this device', async () => {
    const store = waiting(-15)   // the deadline is the request's window plus 15 s: already past
    expect(await store.completePushLogin()).toBe(false)
    expect(store.error).toMatch(/not approved in time/i)
  })

  it('the request is gone', async () => {
    push.status.mockRejectedValue(notFound())
    const store = waiting()
    expect(await store.completePushLogin()).toBe(false)
    expect(store.error).toMatch(/no longer waiting\. sign in again/i)
  })
})

describe('the person can stop waiting', () => {
  it('ends at once, says nothing went wrong, and a later approval signs nothing in', async () => {
    let polls = 0
    push.status.mockImplementation(async () => ({ status: polls++ === 0 ? 'pending' : 'approved' }))
    push.token.mockResolvedValue({ access_token: 'phone.jwt', token_type: 'bearer' })
    const store = waiting()
    const t0 = Date.now()
    const wait = store.completePushLogin()
    await vi.waitFor(() => expect(polls).toBe(1))
    store.stopWaitingForPhone()
    expect(await wait).toBe(false)
    expect(Date.now() - t0, 'at once, not after the two-second pause').toBeLessThan(1500)
    expect(store.error).toBeFalsy()
    expect(store.pushApprovalId).toBe('')
    expect(push.token, 'nothing redeemed').not.toHaveBeenCalled()
    expect(store.token).toBeFalsy()
  })

  it('control: an approval on the phone signs this device in', async () => {
    push.status.mockResolvedValue({ status: 'approved' })
    push.token.mockResolvedValue({ access_token: 'phone.jwt', token_type: 'bearer' })
    const store = waiting()
    expect(await store.completePushLogin()).toBe(true)
    expect(store.token).toBe('phone.jwt')
    expect(store.error).toBeFalsy()
  })
})
