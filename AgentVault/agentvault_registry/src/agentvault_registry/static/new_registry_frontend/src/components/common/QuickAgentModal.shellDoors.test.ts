/**
 * V0658 (v), session-lead's decision (the sessions' room, seq 2389): a press inside a shell stays in that shell. The
 * quick agent sheet is mounted by both shells (DashboardLayout and PocketShell), so its doors follow the one it was
 * opened in: "Request {ccy}" and "My Agents" open the desktop console's My Agents from the desktop console and Pocket's
 * own surfaces from Pocket, whatever is saved and however wide the window. Its sentence about where things are
 * (§PHONEWORDS) agrees with the doors.
 * RED on e0fe8732c: the doors and the sentence followed the saved choice, so the desktop console with Pocket saved sent
 * "Request ECU" to Pocket home and named Pocket's surfaces, and Pocket on a wide window with a desktop choice saved sent
 * them out of Pocket.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ push: vi.fn(async (_to: unknown) => undefined) }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/stores/ui', async () => {
  const { reactive } = await import('vue')
  const ui = reactive({ showQuickAgentModal: false, closeQuickAgentModal: () => {}, openQuickAgentModal: () => {}, noteAgentCreated: () => {} })
  return { useUIStore: () => ui }
})
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ agentToken: 'tok', authenticateAsAgent: async () => true, setActiveAgentFromToken: () => {}, fetchAvailableAgents: async () => {} }),
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { create: async (b: any) => ({ did: 'did:theprotocol:shell-door-test', name: b.name }) } }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: () => ({ client_id: 'agent-cid', client_secret: 'tp_secret_csec' }) } }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: ref(false), isPhone: ref(false) }) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ localCurrency: ref('ECU'), config: ref({ staking_enabled: false }) }) }))
vi.mock('@/stores/agents', () => {
  const st = { agents: [{ did: 'did:theprotocol:wallet', name: 'Wallet', card_data: { tags: ['wallet'] } }], myAgentsFailed: false, fetchMyAgents: async () => {} }
  return { useAgentStore: () => st }
})
// the new agent holds nothing, so the sheet offers its funding door
vi.mock('@/services/api/developers', () => ({
  developerApi: { getAgentBalancesBatch: async () => ({ balances: { 'did:theprotocol:shell-door-test': { liquid_balance: '0' } } }) },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { patch: async () => ({}) } }))
vi.mock('@/services/api/reputationBond', () => ({
  reputationBondApi: { getConfig: async () => ({ mode: 'off', amount: '0', currency: 'ECU', treasury_backstop: false }), bondFromWallet: vi.fn(), bondBackstop: vi.fn() },
}))

import { useUIStore } from '@/stores/ui'
import * as uiMode from '@/services/uiMode'
import QuickAgentModal from './QuickAgentModal.vue'

// read off the module, so the binding the shell rule adds fails as an assertion where it is missing
const doors = uiMode as unknown as Record<string, any>
const width = window.innerWidth

function openedIn(shell: 'desktop' | 'pocket', saved: 'pocket' | 'advanced', px: number) {
  const path = shell === 'pocket' ? '/pocket/home' : '/mission-control'
  if (typeof doors.bindDoorRouter === 'function') doors.bindDoorRouter({ currentRoute: { value: { path, meta: { shell } } } })
  localStorage.setItem(uiMode.UI_MODE_KEY, saved)
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: px })
}

async function successSheet() {
  const ui = useUIStore() as any
  ui.showQuickAgentModal = false
  const w = mount(QuickAgentModal, { global: { stubs: { Icon: true, Teleport: true } } })
  ui.showQuickAgentModal = true
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('input.qa-input').setValue('Shell Door Test')
  await w.find('.qa-foot .qa-btn--primary').trigger('click')
  for (let i = 0; i < 6; i++) await flushPromises()
  expect(w.find('[data-testid="qa-success-sub"]').attributes('data-held'), 'the new agent holds nothing').toBe('zero')
  return w
}

async function pressBoth(w: Awaited<ReturnType<typeof successSheet>>) {
  await w.find('[data-testid="qa-fund-door"]').trigger('click')
  const myAgents = w.findAll('.qa-foot button').find((b) => b.text().includes('My Agents'))
  expect(myAgents, 'the My Agents door').toBeTruthy()
  await myAgents!.trigger('click')
  return h.push.mock.calls.map((c) => c[0])
}

describe('the quick agent sheet keeps its doors in the shell it was opened in', () => {
  beforeEach(() => {
    h.push.mockClear()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })))
  })
  afterEach(() => {
    if (typeof doors.bindDoorRouter === 'function') doors.bindDoorRouter(null)
    localStorage.clear()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
    vi.unstubAllGlobals()
  })

  it('opened in the desktop console with Pocket saved on a narrow window: My Agents, and the desktop pages named', async () => {
    openedIn('desktop', 'pocket', 390)
    const w = await successSheet()
    expect(w.find('[data-testid="qa-success-sub"]').text()).toContain('Agent-required pages (Contracts, Disputes, Attestations) just unlocked.')
    expect(await pressBoth(w)).toEqual(['/my-agents?fund=1', '/my-agents'])
    // seq 2419: "Move funds from your wallet agent" opens the desktop console's Forex Desk, from the wallet
    h.push.mockClear()
    await w.find('[data-testid="qa-move-door"]').trigger('click')
    expect(h.push.mock.calls.map((c) => c[0])).toEqual(
      ['/forex?to=did%3Atheprotocol%3Ashell-door-test&from=did%3Atheprotocol%3Awallet'])
    w.unmount()
  })

  it("opened in Pocket on a wide window with a desktop choice saved: Pocket's own surfaces, and Pocket's named", async () => {
    openedIn('pocket', 'advanced', 1440)
    const w = await successSheet()
    expect(w.find('[data-testid="qa-success-sub"]').text()).toContain('Send and OurChat are yours to use now.')
    expect(await pressBoth(w)).toEqual(['/pocket/home?fund=1', '/pocket/agents'])
    h.push.mockClear()
    await w.find('[data-testid="qa-move-door"]').trigger('click')
    expect(h.push.mock.calls.map((c) => c[0])).toEqual(['/pocket/pay?to=did%3Atheprotocol%3Ashell-door-test'])
    w.unmount()
  })
})
