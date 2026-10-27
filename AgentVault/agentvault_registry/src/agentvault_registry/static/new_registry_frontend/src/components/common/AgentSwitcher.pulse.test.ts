/**
 * §FESUITE (2026-10-10): one door at a time. The agent guard and a locked sidebar item open the agent picker AND pulse the
 * switcher in the top right, and the pulse opened the switcher's dropdown: its click-outside overlay (fixed, z 99998,
 * transparent) lay over the picker, so the first press on an agent in the picker only closed the dropdown (the console
 * suite's lifecycle 82, `.as-overlay intercepts pointer events`). While the picker is open the switcher glows and stays
 * shut; with no picker open the pulse still opens it. The real stores and the real switcher.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/stores/globalReset', () => ({ globalReset: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/', path: '/' }), useRouter: () => ({ push: vi.fn() }) }))

import { apiClient } from '@/services/api/client'
import { authService } from '@/services/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentDidsCache } from '@/services/agentDidsCache'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import AgentSwitcher from './AgentSwitcher.vue'

beforeEach(() => {
  localStorage.clear()
  vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'isAuthenticated').mockReturnValue(true)
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({} as any)
  vi.spyOn(agentCredentialsStore, 'mergeWithStoredCredentials').mockImplementation((a: any) => a)
  vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null)
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] } as any)
  setActivePinia(createPinia())
})

afterEach(() => { vi.restoreAllMocks() })

async function switcher(pickerOpen: boolean) {
  const auth = useAuthStore()
  auth.token = 'dev.jwt'
  auth.user = { id: 7, role: 'developer', email: 'd@x' } as any
  auth.availableAgents = [{ did: 'did:theprotocol:a1', name: 'mine', owned: true }] as any
  auth.showAgentSelector = pickerOpen
  const w = mount(AgentSwitcher, {
    attachTo: document.body,
    global: {
      stubs: { teleport: true, UserAvatar: true, RouterLink: true, 'router-link': true },
      mocks: { $route: { path: '/', fullPath: '/' } },
    },
  })
  await flushPromises()
  useUIStore().pulseAgentSwitcher()     // what the guard does when an agent page meets no acting agent
  await flushPromises()
  return w
}

describe('the switcher pulse beside the agent picker', () => {
  it('while the picker is open, the switcher glows and stays shut (no overlay over the picker)', async () => {
    const w = await switcher(true)
    expect(w.find('.as-overlay').exists(), 'the dropdown overlay over the picker').toBe(false)
    expect(w.find('.as-trigger--pulse').exists(), 'the switcher still glows').toBe(true)
    w.unmount()
  })

  it('with no picker open, the pulse still opens the dropdown', async () => {
    const w = await switcher(false)
    expect(w.find('.as-overlay').exists()).toBe(true)
    w.unmount()
  })
})
