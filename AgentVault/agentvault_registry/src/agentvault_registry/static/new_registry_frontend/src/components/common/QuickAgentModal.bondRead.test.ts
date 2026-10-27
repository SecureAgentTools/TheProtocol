/**
 * §FESUITE (V0578): after a new agent is created the quick agent sheet reads /reputation-bond/config and shows the bond
 * door: the bond a provider needs here, and how to fund it. A failed read hid the door, which is exactly what a registry
 * that asks no bond shows, so the owner of a new provider was not told a bond is needed. The sheet now says the bond
 * rule could not be read (with Try again), and hides the door only where the registry answered that no bond is asked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getConfig: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(async () => {}) }) }))
vi.mock('@/stores/ui', async () => {
  const { reactive } = await import('vue')
  const ui = reactive({ showQuickAgentModal: false, closeQuickAgentModal: () => {}, openQuickAgentModal: () => {}, noteAgentCreated: () => {} })
  return { useUIStore: () => ui }
})
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ agentToken: 'tok', authenticateAsAgent: async () => true, setActiveAgentFromToken: () => {}, loadAvailableAgents: async () => {} }),
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { create: async (b: any) => ({ did: 'did:theprotocol:new-provider', name: b.name }) } }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: () => ({ client_id: 'cid', client_secret: 'csec' }) } }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: ref(false), isPhone: ref(false) }) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/stores/agents', () => {
  // an account that already has its wallet agent: the new agent is a provider, not a wallet
  const st = { agents: [{ did: 'did:theprotocol:wallet', name: 'Wallet', capabilities: ['wallet'], card_data: { tags: ['wallet'] } }], myAgentsFailed: false, fetchMyAgents: async () => {} }
  return { useAgentStore: () => st }
})
vi.mock('@/services/api/developers', () => ({ developerApi: { getAgentBalancesBatch: async () => ({ balances: {} }) } }))
vi.mock('@/services/api/client', () => ({ apiClient: { patch: async () => ({}) } }))
vi.mock('@/services/api/reputationBond', () => ({
  reputationBondApi: { getConfig: (...a: unknown[]) => h.getConfig(...a), bondFromWallet: vi.fn(), bondBackstop: vi.fn() },
}))

import { useUIStore } from '@/stores/ui'
import QuickAgentModal from './QuickAgentModal.vue'

const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

async function createProvider() {
  const ui = useUIStore() as any
  ui.showQuickAgentModal = false
  const w = mount(QuickAgentModal, { global: { stubs: { Icon: true, Teleport: true } } })
  ui.showQuickAgentModal = true   // the sheet opens as the console opens it
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe("the quick agent sheet's bond door after a new provider is created", () => {
  beforeEach(() => { h.getConfig.mockReset() })

  it('a failed bond config read says so, and is not the sheet of a registry that asks no bond', async () => {
    h.getConfig.mockRejectedValue(badGateway())
    const w = await createProvider()
    await w.find('input.qa-input').setValue('Provider One')
    await w.find('.qa-foot .qa-btn--primary').trigger('click')
    for (let i = 0; i < 6; i++) await flushPromises()
    expect(w.text()).toContain('Provider One')
    expect(w.find('[data-testid="qa-bond-unread"]').exists(),
      'a failed bond config read drew the sheet of a registry that asks no bond').toBe(true)
    h.getConfig.mockResolvedValue({ mode: 'enforce', amount: '250', currency: 'ECU', treasury_backstop: false })
    await w.find('[data-testid="qa-bond-unread"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.find('[data-testid="qa-bond-door"]').exists()).toBe(true)
    expect(w.find('[data-testid="qa-bond-unread"]').exists()).toBe(false)
  })

  it('a registry that answered "no bond" shows neither the door nor the notice', async () => {
    h.getConfig.mockResolvedValue({ mode: 'off', amount: '0', currency: 'ECU', treasury_backstop: false })
    const w = await createProvider()
    await w.find('input.qa-input').setValue('Provider Two')
    await w.find('.qa-foot .qa-btn--primary').trigger('click')
    for (let i = 0; i < 6; i++) await flushPromises()
    expect(w.text()).toContain('Provider Two')
    expect(w.find('[data-testid="qa-bond-door"]').exists()).toBe(false)
    expect(w.find('[data-testid="qa-bond-unread"]').exists()).toBe(false)
  })
})
