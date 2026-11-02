/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): after a secret is saved and still sits unencrypted
 * in this browser, the add-keys dialog stays open on its saved step (where the secret sits, the one press that locks
 * it, Done). The agent picker opens that dialog and closed it on its "saved" event, so the step never showed here. Now
 * "saved" refreshes the list and leaves the dialog open; the dialog's own close closes it. RED on 17f71c143.
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
// the dialog itself is covered by AddCredentialsModal.savedLock.test.ts: here only what its parent does with its events
vi.mock('./AddCredentialsModal.vue', async () => {
  const { defineComponent, h: el } = await import('vue')
  return { __esModule: true, default: defineComponent({ name: 'AddCredentialsModal', props: { show: Boolean, agent: Object }, emits: ['close', 'saved'],
    setup: (props, { emit }) => () => props.show
      ? el('div', { 'data-testid': 'acm' }, [el('button', { 'data-testid': 'acm-saved', onClick: () => emit('saved') }),
        el('button', { 'data-testid': 'acm-close', onClick: () => emit('close') })])
      : null }) }
})

import AgentSelectorModal from './AgentSelectorModal.vue'

const foreign = { did: 'did:theprotocol:asia.example:0b6d5e6c-0000-4000-8000-000000000002', name: 'theirs', owned: false }

beforeEach(() => {
  h.auth = reactive({
    showAgentSelector: true, agentLoading: false, credentialsChecked: true, agentFetchFailed: false,
    availableAgents: [foreign], activeAgent: null, canActAs: () => false,
    fetchAvailableAgents: vi.fn(async () => true), switchAgent: vi.fn(async () => true),
  })
})

describe("the agent picker and the add-keys dialog's saved step", () => {
  it('a save refreshes the list and leaves the dialog open; its close closes it', async () => {
    const w = mount(AgentSelectorModal, { global: { stubs: { teleport: true, RouterLink: true, 'router-link': true } } })
    await flushPromises()
    await w.find('button.flex-1').trigger('click')
    await flushPromises()
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(w.find('[data-testid="acm"]').exists(), 'the dialog opened').toBe(true)
    const before = h.auth.fetchAvailableAgents.mock.calls.length
    await w.find('[data-testid="acm-saved"]').trigger('click')
    await flushPromises()
    expect(h.auth.fetchAvailableAgents.mock.calls.length, 'the save refreshes the agents').toBeGreaterThan(before)
    expect(w.find('[data-testid="acm"]').exists(), 'the dialog stays open on its saved step').toBe(true)
    await w.find('[data-testid="acm-close"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="acm"]').exists()).toBe(false)
  })
})
