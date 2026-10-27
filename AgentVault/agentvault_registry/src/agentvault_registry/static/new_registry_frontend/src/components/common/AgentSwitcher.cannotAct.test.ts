/**
 * §MCPTEST30 (V0640): the header's agent switcher says the server's word for a revoked or suspended agent, before its
 * credentials door. agentvault2-5b's code read of cdff1f8e: selectAgent opened Add Credentials for any row without a
 * saved client id and secret, a deleted agent included, and with a saved secret the store refused quietly (its notice
 * shows only while the picker modal is open) and the dropdown stayed open. Driven here through the switcher itself: the
 * row, the press, and a control that the credentials door still opens for an agent with nothing wrong but its secret.
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

const did = (n: number) => `did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-00000000001${n}`
const saved = { client_id: 'cid', client_secret: 'sec' }
const deletedSaved = { did: did(1), name: 'gone', status: 'revoked', ...saved }
const deletedBare = { did: did(2), name: 'gone too', status: 'revoked' }
const suspended = { did: did(3), name: 'held', status: 'active', enforcement_status: 'suspended', ...saved }
const noSecret = { did: did(4), name: 'needs its secret', status: 'active' }

function store(agents: any[]) {
  h.auth = reactive({
    activeAgent: null, availableAgents: agents, agentLoading: false, agentFetchFailed: false, showAgentSelector: false,
    isDeveloper: true, isAdmin: false, isAgentRequired: () => false,
    fetchAvailableAgents: vi.fn(async () => true), hydrateForeignFlares: vi.fn(async () => {}),
    searchAgents: vi.fn(async () => []), switchAgent: vi.fn(async () => false),
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

describe('the agent switcher and an agent that cannot act', () => {
  beforeEach(() => { h.auth = null; vi.clearAllMocks(); document.body.innerHTML = '' })

  it.each([
    ['deleted, a secret saved', deletedSaved, 'Deleted on its registry', 'Agent deleted', 'has been deleted (revoked): it cannot act any more.'],
    ['deleted, no secret saved', deletedBare, 'Deleted on its registry', 'Agent deleted', 'has been deleted (revoked): it cannot act any more.'],
    ['suspended', suspended, 'Suspended on its registry', 'Agent suspended', 'is suspended on its registry: it cannot act while the suspension holds.'],
  ])('%s: its row says so, a press says why and closes, and no credentials door opens', async (_k, agent, row, title, sentence) => {
    const { w, auth } = await openWith([agent])
    expect(w.find('[data-testid="as-row-cannot-act"]').text()).toContain(row)
    expect(w.text()).not.toContain('No credentials · click to add')
    await press(w)
    expect(h.ui.showError).toHaveBeenCalledTimes(1)
    const [t, body] = h.ui.showError.mock.calls[0]
    expect(t).toBe(title)
    expect(body).toContain(sentence)
    expect(auth.switchAgent).not.toHaveBeenCalled()
    expect(w.find('.as-agent-row').exists(), 'the dropdown closes').toBe(false)
    expect(w.text()).not.toContain('Add Agent Credentials')
    w.unmount()
  })

  it('control: an active agent with no saved secret still opens its credentials door', async () => {
    const { w } = await openWith([noSecret])
    expect(w.find('[data-testid="as-row-cannot-act"]').exists()).toBe(false)
    expect(w.text()).toContain('No credentials · click to add')
    await press(w)
    expect(w.text()).toContain('Add Agent Credentials')
    expect(h.ui.showError).not.toHaveBeenCalled()
    w.unmount()
  })
})
