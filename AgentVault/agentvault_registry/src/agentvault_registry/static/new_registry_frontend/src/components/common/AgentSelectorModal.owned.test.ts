/**
 * §FESUITE (2026-10-10): the agent picker acts as an agent you own here without a saved secret (the store's canActAs,
 * §FEFRAME W3: it signs in through your session). It asked only "is a secret saved here": pressing an owned agent opened
 * "Add Credentials" for a secret it does not need, and the card read "No secret saved in this browser". Since the agent
 * guard sends a member whose owned agent could not sign in to this picker, that was a dead end.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: { openQuickAgentModal: () => {}, showWarning: () => {}, showInfo: () => {},
  showSuccess: () => {}, showError: () => {} } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/composables/useActingContext', () => ({
  useRegistryFacts: () => ({ ensureFor: () => {}, currencyFor: () => 'ECU', nameFor: () => 'this registry', isForeign: () => false }),
}))

import AgentSelectorModal from './AgentSelectorModal.vue'

const owned = { did: 'did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-000000000001', name: 'mine', owned: true }
const foreign = { did: 'did:theprotocol:asia.example:0b6d5e6c-0000-4000-8000-000000000002', name: 'theirs', owned: false }

function store(agents: any[]) {
  h.auth = reactive({
    showAgentSelector: true, agentLoading: false, credentialsChecked: true, agentFetchFailed: false,
    availableAgents: agents, activeAgent: null,
    canActAs: (a: any) => !!a?.owned,
    fetchAvailableAgents: vi.fn(async () => true), switchAgent: vi.fn(async () => true),
  })
  return h.auth
}

async function open() {
  const w = mount(AgentSelectorModal, { global: { stubs: { teleport: true, RouterLink: true, 'router-link': true } } })
  await flushPromises()
  return w
}

describe('the agent picker and an agent you own here', () => {
  beforeEach(() => { h.auth = null })

  it('pressing an owned agent with no saved secret acts as it, and its card says why no secret is needed', async () => {
    const auth = store([owned])
    const w = await open()
    expect(w.text()).not.toContain('No secret saved in this browser')
    expect(w.find('[data-testid="agent-selector-owned"]').exists()).toBe(true)
    expect(w.find('[data-testid="agent-selector-add-secret"]').exists(), 'an "Add Credentials" door it does not need').toBe(false)
    await w.find('button.flex-1').trigger('click')
    await flushPromises()
    expect(auth.switchAgent).toHaveBeenCalledWith(owned.did)
  })

  it('an agent this console cannot act as still asks for its secret', async () => {
    const auth = store([foreign])
    const w = await open()
    expect(w.text()).toContain('No secret saved in this browser')
    expect(w.find('[data-testid="agent-selector-add-secret"]').exists()).toBe(true)
    await w.find('button.flex-1').trigger('click')
    await flushPromises()
    expect(auth.switchAgent).not.toHaveBeenCalled()
  })

  it('a refused secret is re-entered, even on an owned agent', async () => {
    const auth = store([{ ...owned, hasInvalidCredentials: true }])
    const w = await open()
    await w.find('button.flex-1').trigger('click')
    await flushPromises()
    expect(auth.switchAgent).not.toHaveBeenCalled()
  })
})
