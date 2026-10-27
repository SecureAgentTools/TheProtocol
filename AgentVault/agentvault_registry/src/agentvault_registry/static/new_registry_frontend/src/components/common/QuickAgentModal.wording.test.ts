/**
 * The quick agent sheet's own words (2026-10-09, his word "fix the popup text"):
 * - its success line named Staking on every registry ("Agent-required pages (Contracts, Disputes, Staking, Attestations)
 *   just unlocked.", in Pocket "Send, Stake and OurChat ..."), while EU and ASIA run STAKING_ENABLED=false (the BaFin
 *   letter's posture). It names Staking only where the registry says a staking position can be opened; an unread
 *   config names none.
 * - its credential note sent a lost secret to "My Agents > Rotate signing key", which rotates the DID signing key and
 *   never the client secret. The rail that issues a new client ID and secret is Reset credentials (Quick onboarding,
 *   My Agents).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const registry = { config: ref<Record<string, unknown>>({}) }

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(async () => {}) }) }))
vi.mock('@/stores/ui', async () => {
  const { reactive } = await import('vue')
  const ui = reactive({ showQuickAgentModal: false, closeQuickAgentModal: () => {}, openQuickAgentModal: () => {}, noteAgentCreated: () => {} })
  return { useUIStore: () => ui }
})
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ agentToken: 'tok', authenticateAsAgent: async () => true, setActiveAgentFromToken: () => {}, fetchAvailableAgents: async () => {} }),
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { create: async (b: any) => ({ did: 'did:theprotocol:wording-test', name: b.name }) } }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: () => ({ client_id: 'agent-cid', client_secret: 'tp_secret_csec' }) } }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: ref(false), isPhone: ref(false) }) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ localCurrency: ref('ECU'), config: registry.config }) }))
vi.mock('@/stores/agents', () => {
  const st = { agents: [{ did: 'did:theprotocol:wallet', name: 'Wallet', card_data: { tags: ['wallet'] } }], myAgentsFailed: false, fetchMyAgents: async () => {} }
  return { useAgentStore: () => st }
})
vi.mock('@/services/api/developers', () => ({ developerApi: { getAgentBalancesBatch: async () => ({ balances: {} }) } }))
vi.mock('@/services/api/client', () => ({ apiClient: { patch: async () => ({}) } }))
vi.mock('@/services/api/reputationBond', () => ({
  reputationBondApi: { getConfig: async () => ({ mode: 'off', amount: '0', currency: 'ECU', treasury_backstop: false }), bondFromWallet: vi.fn(), bondBackstop: vi.fn() },
}))

import { useUIStore } from '@/stores/ui'
import QuickAgentModal from './QuickAgentModal.vue'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })))
})
afterEach(() => {
  vi.unstubAllGlobals()
})

async function successSheet(cfg: Record<string, unknown>) {
  registry.config.value = cfg
  const ui = useUIStore() as any
  ui.showQuickAgentModal = false
  const w = mount(QuickAgentModal, { global: { stubs: { Icon: true, Teleport: true } } })
  ui.showQuickAgentModal = true
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('input.qa-input').setValue('Wording Test Agent')
  await w.find('.qa-foot .qa-btn--primary').trigger('click')
  for (let i = 0; i < 6; i++) await flushPromises()
  const line = w.findAll('p').find((p) => /just unlocked|yours to use now/.test(p.text()))
  expect(line, 'the success line').toBeTruthy()
  const note = w.find('[data-testid="qa-creds-note"]')
  expect(note.exists(), 'the credential note').toBe(true)
  return { w, line: line!.text(), note: note.text() }
}

describe('the quick agent sheet names Staking only where staking is on', () => {
  it('a registry with staking off (EU, ASIA): no Staking in the success line', async () => {
    const { w, line } = await successSheet({ staking_enabled: false })
    expect(line).toContain('Agent-required pages (Contracts, Disputes, Attestations) just unlocked.')
    expect(line).not.toMatch(/stak/i)
    w.unmount()
  })

  it('an unread registry config names no Staking either', async () => {
    const { w, line } = await successSheet({})
    expect(line).not.toMatch(/stak/i)
    w.unmount()
  })

  it('control: a registry with locking on still lists the Locks page', async () => {
    const { w, line } = await successSheet({ staking_enabled: true })
    expect(line).toContain('Locks')
    expect(line).not.toMatch(/stak/i)
    w.unmount()
  })
})

describe('the credential note points at the rail that issues a new secret', () => {
  it('Reset credentials, never "Rotate signing key"', async () => {
    const { w, note } = await successSheet({ staking_enabled: false })
    expect(note).toContain('Reset credentials')
    expect(note).not.toContain('Rotate signing key')
    expect(note).not.toContain('—')
    w.unmount()
  })
})
