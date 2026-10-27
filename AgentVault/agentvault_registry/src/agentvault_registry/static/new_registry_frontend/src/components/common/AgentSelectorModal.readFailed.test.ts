/**
 * §FESUITE (V0577): the "Agent Required" selector, which the router opens when a page needs an agent and none is
 * active. Its empty state was a bare v-else, so when the agents read failed (the store leaves the list empty and sets
 * agentFetchFailed) it said "No wallet agent yet… Create your wallet agent first" and offered to create one, to a person
 * whose agents could not be read. It now says the read failed and offers it again; a list that answered empty still
 * says "No wallet agent yet".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: { openQuickAgentModal: () => {}, showWarning: () => {} } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/composables/useActingContext', () => ({
  useRegistryFacts: () => ({ ensureFor: () => {}, currencyFor: () => 'ECU', nameFor: () => 'this registry', isForeign: () => false }),
}))

import AgentSelectorModal from './AgentSelectorModal.vue'

function store(over: Record<string, unknown>) {
  h.auth = reactive({
    showAgentSelector: true, agentLoading: false, credentialsChecked: true, agentFetchFailed: false,
    availableAgents: [] as any[], activeAgent: null,
    fetchAvailableAgents: vi.fn(async () => true), switchAgent: vi.fn(async () => true),
    ...over,
  })
  return h.auth
}

async function open() {
  const w = mount(AgentSelectorModal, { global: { stubs: { teleport: true, RouterLink: true, 'router-link': true } } })
  await flushPromises()
  return w
}

describe('the agent selector when the agents read failed', () => {
  beforeEach(() => { h.auth = null })

  it('says the read failed and offers it again, never "No wallet agent yet" or "Create your wallet agent"', async () => {
    const auth = store({ agentFetchFailed: true })
    const w = await open()
    expect(w.text()).not.toContain('No wallet agent yet')
    expect(w.text()).not.toContain('Create your wallet agent')
    const notice = w.find('[data-testid="asel-read-failed"]')
    expect(notice.exists(), 'the selector says the agents read failed').toBe(true)
    expect(notice.text()).toContain('could not be read')
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    expect(auth.fetchAvailableAgents).toHaveBeenCalledWith({ force: true })
  })

  it('a list that answered empty still says "No wallet agent yet"', async () => {
    store({})
    const w = await open()
    expect(w.text()).toContain('No wallet agent yet')
    expect(w.find('[data-testid="asel-read-failed"]').exists()).toBe(false)
  })
})
