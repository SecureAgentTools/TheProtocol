/**
 * V0641 (agentvault2-5b, 2026-10-25, with agentvault2-66): the header's agent switcher signs in as an agent you own on
 * this registry through your session when no secret is saved in this browser, as the picker modal has since
 * 2026-10-10 (the store's canActAs, §FEFRAME W3). Its selectAgent asked only "is a secret saved here": the row said
 * "No credentials · click to add" and a press opened Add Credentials for a secret the agent does not need. Driven
 * through the switcher itself (the harness of AgentSwitcher.cannotAct.test.ts), with a control that an agent the store
 * cannot act as still opens its credentials door.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: {
  showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn(), showSuccess: vi.fn(), openQuickAgentModal: vi.fn(),
  pulseAgentSwitcher: vi.fn(), agentSwitcherAttention: false, agentSwitcherPulseAutoOpen: false, agentSwitcherPulseToken: 0,
} }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/', path: '/' }), useRouter: () => ({ push: vi.fn() }) }))

import AgentSwitcher from './AgentSwitcher.vue'

const did = (n: number) => `did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-00000000003${n}`
const ownedHere = { did: did(1), name: 'mine, no secret here', status: 'active', owned: true }
const notMine = { did: did(2), name: 'not mine, no secret', status: 'active' }

function store(agents: any[]) {
  h.auth = reactive({
    activeAgent: null, availableAgents: agents, agentLoading: false, agentFetchFailed: false, showAgentSelector: false,
    isDeveloper: true, isAdmin: false, isAgentRequired: () => false,
    fetchAvailableAgents: vi.fn(async () => true), hydrateForeignFlares: vi.fn(async () => {}),
    searchAgents: vi.fn(async () => []), switchAgent: vi.fn(async () => true),
    // the store's rule (stores/auth.ts canActAs): an agent you own here needs no secret; any other needs one
    canActAs: (a: any) => !!a && (!!a.owned || !!(a.client_id && a.client_secret)),
  })
  return h.auth
}

async function openWith(agents: any[]) {
  const auth = store(agents)
  const w = mount(AgentSwitcher, {
    attachTo: document.body,
    global: { stubs: { teleport: true, UserAvatar: true, RouterLink: true, 'router-link': true },
              mocks: { $route: { path: '/', fullPath: '/' } } },
  })
  await w.find('.as-trigger').trigger('click')
  await flushPromises()
  return { w, auth }
}

async function press(w: any) {
  await w.find('.as-agent-row').trigger('click')
  await flushPromises()
  await vi.dynamicImportSettled()   // the credentials modal is an async component: let it load before reading
  await flushPromises()
}

describe('the agent switcher and an agent you own with no secret saved here', () => {
  beforeEach(() => { h.auth = null; vi.clearAllMocks(); document.body.innerHTML = '' })

  it('its row says it signs in through your session, and a press signs in, no credentials door', async () => {
    const { w, auth } = await openWith([ownedHere])
    expect(w.find('[data-testid="as-row-owned"]').text()).toContain('signs in through your session')
    expect(w.text()).not.toContain('No credentials · click to add')
    expect(w.find('.as-agent-row--nocreds').exists(), 'not drawn as a row missing its credentials').toBe(false)
    await press(w)
    expect(auth.switchAgent).toHaveBeenCalledWith(ownedHere.did)
    expect(w.text()).not.toContain('Add Agent Credentials')
    w.unmount()
  })

  it('control: an agent the store cannot act as (not yours, no secret) still opens its credentials door', async () => {
    const { w, auth } = await openWith([notMine])
    expect(w.find('[data-testid="as-row-owned"]').exists()).toBe(false)
    expect(w.text()).toContain('No credentials · click to add')
    await press(w)
    expect(w.text()).toContain('Add Agent Credentials')
    expect(auth.switchAgent).not.toHaveBeenCalled()
    w.unmount()
  })
})
