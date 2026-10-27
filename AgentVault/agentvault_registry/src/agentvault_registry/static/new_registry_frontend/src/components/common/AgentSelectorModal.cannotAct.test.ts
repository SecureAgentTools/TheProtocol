/**
 * §MCPTEST30 (V0640): the agent picker says the server's word for a revoked or suspended agent, before any credentials
 * door. agentvault2-5b's code read of cdff1f8e: actable() turned false for such a row, so selectAgent took its "cannot
 * act from here" branch and opened Add Credentials, the row read "No secret saved in this browser", and the store's
 * "Agent deleted" notice could not be reached from the picker (its test called the store directly). Driven here
 * through the picker itself: the row, the press, and a control that the credentials door still opens where it should.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: { openQuickAgentModal: () => {}, showWarning: vi.fn(), showInfo: vi.fn(),
  showSuccess: vi.fn(), showError: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/composables/useActingContext', () => ({
  useRegistryFacts: () => ({ ensureFor: () => {}, currencyFor: () => 'ECU', nameFor: () => 'this registry', isForeign: () => false }),
}))

import AgentSelectorModal from './AgentSelectorModal.vue'

const did = (n: number) => `did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-00000000000${n}`
const deleted = { did: did(1), name: 'gone', owned: true, status: 'revoked', hasCredentials: true }
const suspended = { did: did(2), name: 'held', owned: true, status: 'active', enforcement_status: 'suspended' }
const foreign = { did: did(3), name: 'theirs', owned: false }

function store(agents: any[]) {
  h.auth = reactive({
    showAgentSelector: true, agentLoading: false, credentialsChecked: true, agentFetchFailed: false,
    availableAgents: agents, activeAgent: null,
    canActAs: (a: any) => !!a?.owned,
    fetchAvailableAgents: vi.fn(async () => true), switchAgent: vi.fn(async () => false),
  })
  return h.auth
}

async function open() {
  const w = mount(AgentSelectorModal, { global: { stubs: { teleport: true, RouterLink: true, 'router-link': true } } })
  await flushPromises()
  return w
}

async function press(w: any) {
  await w.find('button.flex-1').trigger('click')
  await flushPromises()
  await vi.dynamicImportSettled()   // the credentials modal is an async component: let it load before reading
  await flushPromises()
}

describe('the agent picker and an agent that cannot act', () => {
  beforeEach(() => { h.auth = null; vi.clearAllMocks() })

  it.each([
    ['deleted', deleted, 'Deleted on its registry', 'Agent deleted', 'has been deleted (revoked): it cannot act any more.'],
    ['suspended', suspended, 'Suspended on its registry', 'Agent suspended', 'is suspended on its registry: it cannot act while the suspension holds.'],
  ])('a %s agent says so on its row and on a press, and no credentials door opens', async (_k, agent, row, title, sentence) => {
    const auth = store([agent])
    const w = await open()
    expect(w.find('[data-testid="agent-selector-cannot-act"]').text()).toContain(row)
    expect(w.text()).not.toContain('No secret saved in this browser')
    expect(w.text()).not.toContain('refused the saved secret')
    expect(w.find('[data-testid="agent-selector-add-secret"]').exists(), 'an Add Credentials door for an agent that cannot act').toBe(false)
    await press(w)
    expect(h.ui.showError).toHaveBeenCalledTimes(1)
    const [t, body] = h.ui.showError.mock.calls[0]
    expect(t).toBe(title)
    expect(body).toContain(sentence)
    expect(auth.switchAgent).not.toHaveBeenCalled()
    expect(w.text()).not.toContain('Add Agent Credentials')
  })

  it('control: an agent this console cannot act as from here still opens its credentials door', async () => {
    store([foreign])
    const w = await open()
    expect(w.find('[data-testid="agent-selector-cannot-act"]').exists()).toBe(false)
    await press(w)
    expect(w.text()).toContain('Add Agent Credentials')
    expect(h.ui.showError).not.toHaveBeenCalled()
  })
})
