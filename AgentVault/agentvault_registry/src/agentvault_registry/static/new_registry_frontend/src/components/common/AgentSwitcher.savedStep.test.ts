/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): after a secret is saved and still sits unencrypted
 * in this browser, the add-keys dialog stays open on its saved step (where the secret sits, the one press that locks
 * it, Done). The header's agent switcher opens that dialog and closed it on its "saved" event, so the step never showed
 * here. Now "saved" refreshes the agents and leaves the dialog open; the dialog's own close closes it. RED on 17f71c143.
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
// the dialog itself is covered by AddCredentialsModal.savedLock.test.ts: here only what its parent does with its events
vi.mock('./AddCredentialsModal.vue', async () => {
  const { defineComponent, h: el } = await import('vue')
  return { __esModule: true, default: defineComponent({ name: 'AddCredentialsModal', props: { show: Boolean, agent: Object }, emits: ['close', 'saved'],
    setup: (props, { emit }) => () => props.show
      ? el('div', { 'data-testid': 'acm' }, [el('button', { 'data-testid': 'acm-saved', onClick: () => emit('saved') }),
        el('button', { 'data-testid': 'acm-close', onClick: () => emit('close') })])
      : null }) }
})

import AgentSwitcher from './AgentSwitcher.vue'

const notMine = { did: 'did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-000000000032', name: 'not mine, no secret', status: 'active' }

beforeEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
  h.auth = reactive({
    activeAgent: null, availableAgents: [notMine], agentLoading: false, agentFetchFailed: false, showAgentSelector: false,
    isDeveloper: true, isAdmin: false, isAgentRequired: () => false,
    fetchAvailableAgents: vi.fn(async () => true), hydrateForeignFlares: vi.fn(async () => {}),
    searchAgents: vi.fn(async () => []), switchAgent: vi.fn(async () => true),
    canActAs: (a: any) => !!a && (!!a.owned || !!(a.client_id && a.client_secret)),
  })
})

describe("the agent switcher and the add-keys dialog's saved step", () => {
  it('a save refreshes the agents and leaves the dialog open; its close closes it', async () => {
    const w = mount(AgentSwitcher, {
      attachTo: document.body,
      global: { stubs: { teleport: true, UserAvatar: true, RouterLink: true, 'router-link': true },
                mocks: { $route: { path: '/', fullPath: '/' } } },
    })
    await w.find('.as-trigger').trigger('click')
    await flushPromises()
    await w.find('.as-agent-row').trigger('click')
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
