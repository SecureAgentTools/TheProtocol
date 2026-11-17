/**
 * V0662, the admin guard in the API client (layer 2 of PLAN_2026-11-13_NO_ADMIN_CALLS_FOR_NON_ADMINS.md). Through the
 * real apiClient (its interceptors run, an adapter stands in for the network):
 *  - a member's admin call is refused before it is sent, quietly (no global error toast: the page's own catch says
 *    what it needs), counted, and warned once per route in the console;
 *  - an admin holding the flag sends it; the tours' Try it live (a member's route) is sent;
 *  - a session whose profile has not loaded yet is not judged (an admin page must not lose its first reads);
 *  - a visitor's admin call is refused too.
 * Red on f569f6a6e: every call is sent.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosRequestConfig } from 'axios'

let apiClient: any
let errorHandler: any
let auth: any
let guard: any

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient } = await import('@/services/api/client'))
  ;({ errorHandler } = await import('@/utils/errorHandler'))
  const { useAuthStore } = await import('@/stores/auth')
  auth = useAuthStore()
  guard = await import('@/services/api/adminGuard')
}, 30_000)

const sent: string[] = []
const ok = async (cfg: AxiosRequestConfig) => { sent.push(`${(cfg.method || 'get').toUpperCase()} ${cfg.url}`); return { data: {}, status: 200, statusText: '', headers: {}, config: cfg } }
let handled: ReturnType<typeof vi.spyOn>
let warn: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  sent.length = 0
  guard._resetAdminGuard()
  handled = vi.spyOn(errorHandler, 'handleError').mockImplementation(() => {})
  warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
})
afterEach(() => { handled.mockRestore(); warn.mockRestore(); auth.user = null; auth.token = null })

describe('the client decides before it sends', () => {
  it('a member\'s admin call is not sent: refused quietly, counted, warned once', async () => {
    auth.token = 'dev.jwt'; auth.user = { id: 7, is_admin: false }
    const e1 = await apiClient.get('/admin/events/search', { adapter: ok }).then(() => null, (e: any) => e)
    const e2 = await apiClient.get('/admin/events/search', { adapter: ok }).then(() => null, (e: any) => e)
    expect(sent).toEqual([])
    expect(e1?.code).toBe('ERR_ADMIN_REFUSED_LOCALLY')
    expect(e1?.response?.status).toBe(403)
    expect(e2?.code).toBe('ERR_ADMIN_REFUSED_LOCALLY')
    expect(handled, 'no global error toast').not.toHaveBeenCalled()
    expect(guard.adminRefusedCount()).toBe(2)
    expect(warn.mock.calls.filter((c: any[]) => String(c[0]).includes('/admin/events/search')).length).toBe(1)
  })

  it('an admin with the flag sends it; a member\'s route under /admin/ is sent', async () => {
    auth.token = 'dev.jwt'; auth.user = { id: 1, admin_platform: true }
    await apiClient.get('/admin/events/search', { adapter: ok })
    auth.user = { id: 7, is_admin: false }
    await apiClient.post('/admin/tutorial/execute', {}, { adapter: ok })
    expect(sent).toEqual(['GET /admin/events/search', 'POST /admin/tutorial/execute'])
  })

  it('a session whose profile has not loaded is not judged (control)', async () => {
    auth.token = 'dev.jwt'; auth.user = null
    await apiClient.get('/admin/events/search', { adapter: ok })
    expect(sent).toEqual(['GET /admin/events/search'])
  })

  it('a visitor\'s admin call is refused too', async () => {
    auth.token = null; auth.user = null
    const e = await apiClient.get('/admin/federation/topology-overview', { adapter: ok }).then(() => null, (x: any) => x)
    expect(sent).toEqual([])
    expect(e?.code).toBe('ERR_ADMIN_REFUSED_LOCALLY')
  })
})
