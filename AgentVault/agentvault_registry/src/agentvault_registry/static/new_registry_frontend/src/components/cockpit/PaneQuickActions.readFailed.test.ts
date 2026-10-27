/**
 * §FESUITE (V0577): the desk's Quick actions pane tells a person with no agent to create one ("You have no agents on this
 * account yet" + "Create your wallet agent"). It decided that from the agents store, which on a failed read keeps its
 * empty list and zero total and sets myAgentsFailed, so a failed read became "you have none" and an offer to create one.
 * "0 agents" is now claimed only after a read that answered; a failed read says so and offers it again.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ agents: null as any }))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => h.agents }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: null, availableAgents: [] }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => reactive({ agentCreatedTick: 0, openQuickAgentModal: vi.fn() }) }))
vi.mock('@/composables/useActingContext', () => ({ useActingContext: () => ({ actingCurrencyLabel: ref('ECU') }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(async () => {}) }) }))

import PaneQuickActions from './PaneQuickActions.vue'

function agentStore(over: Record<string, unknown>) {
  h.agents = reactive({ agents: [] as any[], totalCount: 0, loading: false, myAgentsFailed: false, fetchMyAgents: vi.fn(async () => {}), ...over })
  return h.agents
}

async function pane() {
  const w = mount(PaneQuickActions, { global: { stubs: { BridgeQuickActions: true, RecordLink: true } } })
  await flushPromises()
  return w
}

describe("the desk's Quick actions pane when the agents read failed", () => {
  beforeEach(() => { h.agents = null })

  it('says the read failed and offers it again, never "You have no agents" or "Create your wallet agent"', async () => {
    const store = agentStore({ myAgentsFailed: true })
    const w = await pane()
    expect(w.text()).not.toContain('You have no agents on this account yet')
    expect(w.find('[data-testid="ckd-qa-create"]').exists(), 'offered to create a first agent over a failed read').toBe(false)
    const notice = w.find('[data-testid="ckd-qa-agents-unread"]')
    expect(notice.exists()).toBe(true)

    store.fetchMyAgents.mockImplementation(async () => { store.myAgentsFailed = false })
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(store.fetchMyAgents).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="ckd-qa-agents-unread"]').exists()).toBe(false)
    expect(w.text()).toContain('You have no agents on this account yet')
  })

  it('a read that answered none still says none and offers the first agent', async () => {
    agentStore({})
    const w = await pane()
    expect(w.text()).toContain('You have no agents on this account yet')
    expect(w.find('[data-testid="ckd-qa-create"]').exists()).toBe(true)
  })
})
