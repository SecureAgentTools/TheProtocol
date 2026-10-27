/**
 * D6-846 (agentvault2-d6, 2026-10-26, for V0645; found by agentvault2-5b): a member who opened an admin page's link
 * directly got an almost empty page. The requiresRole branch answered next(false), so a first navigation (no page behind
 * it) left the router at / with about 20 characters on screen, and the toast named the route by its slug
 * ("admin-emission-policy requires admin privileges"). Now a direct link goes where the person's console starts
 * (homeRoute(), as the agent refusals do), a click from an open page stays on it, and the toast names the page by its title.
 * The real router; its stores stand in. RED control: on c9239bd2 the direct link stays at / and the toast reads the slug.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/composables/useFrameManifest', () => ({ whenFrameManifest: async () => null, currentFrameManifest: () => null }))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  loadRegistryConfig: async () => ({}),
}))
vi.mock('@/composables/usePocketLock', () => ({ pocketLockEngaged: () => false }))
// home is a page the test can land on cheaply (the not-found view)
vi.mock('@/services/uiMode', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  homeRoute: () => '/home-in-this-test',
}))

import router from './index'

function member() {
  h.ui = { showWarning: vi.fn(), showInfo: vi.fn(), showNotification: vi.fn(), openQuickAgentModal: vi.fn(), pulseAgentSwitcher: vi.fn() }
  h.auth = reactive({
    isAuthenticated: true, mustChangePassword: false, isSessionExpired: false, isDeveloper: true, isAdmin: false,
    user: { id: 7, role: 'developer' }, token: 'dev.jwt', userRole: 'developer',
    availableAgents: [] as any[], agentLoading: false, activeAgent: null, agentToken: null,
    agentFetchFailed: false, showAgentSelector: false,
    authSettling: () => null, checkAuth: (role: string) => role !== 'admin',
    fetchAvailableAgents: vi.fn(async () => {}),
  })
  return h.auth
}

function toastMessages(): string[] {
  return h.ui.showNotification.mock.calls.map((c: any[]) => c[0]?.message || '')
}

// the two tests run in this order on ONE router: the first makes its first navigation (a link opened directly), the
// second navigates from a page already open (a fresh router per test would leave the first one listening to the
// address bar, and the second's first navigation would carry the first's address out)
describe('a member opening an admin page', () => {
  beforeEach(() => {
    member()
  })

  it('by a link opened directly: goes where the console starts, and the toast names the page by its title', async () => {
    expect(router.currentRoute.value.matched.length, 'this test must make the first navigation').toBe(0)
    await router.push('/admin/emission-policy')
    expect(router.currentRoute.value.path, 'stayed at / with an empty page').toBe('/home-in-this-test')
    expect(toastMessages().some((m) => m.startsWith('Emission Policy requires admin privileges'))).toBe(true)
    expect(toastMessages().some((m) => m.includes('admin-emission-policy')), 'named the route by its slug').toBe(false)
  })

  it('by a click from an open page: stays on that page, and the toast names the page by its title', async () => {
    await router.push('/an-open-page-in-this-test')
    h.ui.showNotification.mockClear()
    await router.push('/admin/emission-policy')
    expect(router.currentRoute.value.path).toBe('/an-open-page-in-this-test')
    expect(toastMessages().some((m) => m.startsWith('Emission Policy requires admin privileges'))).toBe(true)
  })
})
