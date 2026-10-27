/**
 * §FESUITE (V0577): the router guard for a page that acts as one of your agents (/senate and the other requiresAgent
 * routes) reads your agents when none is active. When that read failed (the store leaves the list empty and sets
 * agentFetchFailed), the guard fell through to its "no agents at all" branch: "No wallet agent yet … Create your wallet
 * agent first", the create sheet open and a redirect home, for a member whose agents could not be read. It now opens the
 * agent picker (which says the read failed and reads again), warns in those words, and keeps the person where they were.
 * The real router; its stores and frame lookups stand in.
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
  homeRoute: () => '/no-such-page-in-this-test',
}))

import router from './index'

function member(over: Record<string, unknown>) {
  h.ui = { showWarning: vi.fn(), showInfo: vi.fn(), showNotification: vi.fn(), openQuickAgentModal: vi.fn(), pulseAgentSwitcher: vi.fn() }
  h.auth = reactive({
    isAuthenticated: true, mustChangePassword: false, isSessionExpired: false, isDeveloper: true, isAdmin: false,
    user: { id: 7, role: 'developer' }, token: 'dev.jwt', userRole: 'developer',
    availableAgents: [] as any[], agentLoading: false, activeAgent: null, agentToken: null,
    agentFetchFailed: false, showAgentSelector: false,
    authSettling: () => null, checkAuth: () => true,
    fetchAvailableAgents: vi.fn(async () => {}),
    ...over,
  })
  return h.auth
}

describe('opening a page that needs an agent when your agents could not be read', () => {
  beforeEach(async () => {
    member({})
    await router.replace('/no-such-page-in-this-test')
  })

  it('opens the picker and says the read failed, never "No wallet agent yet" with the create sheet', async () => {
    const auth = member({})
    auth.fetchAvailableAgents.mockImplementation(async () => { auth.agentFetchFailed = true })
    await router.push('/senate')
    expect(h.ui.showInfo.mock.calls.map((c: any[]) => c[0]), 'said "No wallet agent yet" over a failed read').not.toContain('No wallet agent yet')
    expect(h.ui.openQuickAgentModal, 'opened the create sheet over a failed read').not.toHaveBeenCalled()
    expect(auth.showAgentSelector).toBe(true)
    expect(h.ui.showWarning.mock.calls.map((c: any[]) => c[0])).toContain('Your agents could not be read')
    expect(router.currentRoute.value.path).toBe('/no-such-page-in-this-test')
  })

  it('an account the read answered with no agents is still told to create its wallet agent', async () => {
    member({})
    await router.push('/senate')
    expect(h.ui.showInfo.mock.calls.map((c: any[]) => c[0])).toContain('No wallet agent yet')
    expect(h.ui.openQuickAgentModal).toHaveBeenCalled()
  })
})

/**
 * §FESUITE (2026-10-10, sweeps/recovery on V0589): a console booted while the registry did not answer reads its agents
 * from the browser's cache, and the saved agent's sign-in fails with no answer. An agent the person OWNS here needs no
 * saved secret (canActAs, §FEFRAME W3), but the guard asked only "is a secret saved here", said "No agent can act in this
 * browser yet ... none has its credentials stored here", opened the create sheet and sent the person home; the sheet was
 * still open on the page once the registry was back.
 */
describe('opening a page that needs an agent when the saved agent could not sign in', () => {
  const owned = { did: 'did:theprotocol:sandbox-b.theprotocol.cloud:0b6d5e6c-0000-4000-8000-000000000001', owned: true, name: 'mine' }
  beforeEach(async () => {
    member({})
    await router.replace('/no-such-page-in-this-test')
  })

  it('an owned agent whose sign-in had no answer: the picker and the outage said, never the create sheet', async () => {
    const auth = member({ availableAgents: [owned], canActAs: (a: any) => !!a?.owned, agentSignInWasAnOutage: () => true })
    await router.push('/senate')
    expect(h.ui.openQuickAgentModal, 'opened the create sheet for an agent the person owns').not.toHaveBeenCalled()
    const warned = h.ui.showWarning.mock.calls.map((c: any[]) => c[0])
    expect(warned).toContain('Your agent could not sign in just now')
    expect(warned).not.toContain('No agent can act in this browser yet')
    expect(auth.showAgentSelector).toBe(true)
    expect(router.currentRoute.value.path).toBe('/no-such-page-in-this-test')
  })

  it('an owned agent not signed in for another reason: the picker, as before', async () => {
    member({ availableAgents: [owned], canActAs: (a: any) => !!a?.owned, agentSignInWasAnOutage: () => false })
    await router.push('/senate')
    expect(h.ui.openQuickAgentModal).not.toHaveBeenCalled()
    expect(h.ui.showWarning.mock.calls.map((c: any[]) => c[0])).toContain('Active Agent Required')
  })

  it('agents this console cannot act as (not owned here, no saved secret) still get the create sheet', async () => {
    const foreign = { ...owned, owned: false }
    member({ availableAgents: [foreign], canActAs: (a: any) => !!a?.owned, agentSignInWasAnOutage: () => true })
    await router.push('/senate')
    expect(h.ui.showWarning.mock.calls.map((c: any[]) => c[0])).toContain('No agent can act in this browser yet')
    expect(h.ui.openQuickAgentModal).toHaveBeenCalled()
  })
})
