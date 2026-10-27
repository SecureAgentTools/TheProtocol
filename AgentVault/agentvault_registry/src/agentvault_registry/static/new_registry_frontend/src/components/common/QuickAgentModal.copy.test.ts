/**
 * Quick onboarding (2026-10-09): the quick agent sheet says "Copied to clipboard" only when the copy happened.
 *
 * copyCreds() called navigator.clipboard?.writeText(...) without waiting and set "Copied" at once, so a browser with no
 * clipboard API (or one that refused the write) showed "Copied to clipboard" over credentials that were never copied,
 * and the refusal surfaced as an unhandled rejection. The credentials are shown once; a false "Copied" can lose them.
 *
 * And the name's hint promises the handle the card gets: agentApi.create sends agentSlug(name) as the humanReadableId
 * (pinned in services/api/agents.create.test.ts), while the hint still showed the old formula ("café-bot-#1" for a
 * card stored as "cafe-bot-1").
 *
 * The sheet reads its featured templates with a bare fetch on open; it is answered here, so no case reaches the
 * network of whatever runs it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(async () => {}) }) }))
vi.mock('@/stores/ui', async () => {
  const { reactive } = await import('vue')
  const ui = reactive({ showQuickAgentModal: false, closeQuickAgentModal: () => {}, openQuickAgentModal: () => {}, noteAgentCreated: () => {} })
  return { useUIStore: () => ui }
})
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ agentToken: 'tok', authenticateAsAgent: async () => true, setActiveAgentFromToken: () => {}, fetchAvailableAgents: async () => {} }),
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { create: async (b: any) => ({ did: 'did:theprotocol:copy-test', name: b.name }) } }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: () => ({ client_id: 'agent-cid', client_secret: 'tp_secret_csec' }) } }))
vi.mock('@/composables/useViewport', () => ({ useViewport: () => ({ isSmallPhone: ref(false), isPhone: ref(false) }) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ localCurrency: ref('ECU') }) }))
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
import { agentSlug } from '@/services/agentSlug'

const realClipboard = Object.getOwnPropertyDescriptor(globalThis.navigator, 'clipboard')
const realExec = (document as any).execCommand

function setClipboard(value: unknown) {
  Object.defineProperty(globalThis.navigator, 'clipboard', { configurable: true, value })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })))
})
afterEach(() => {
  if (realClipboard) Object.defineProperty(globalThis.navigator, 'clipboard', realClipboard)
  ;(document as any).execCommand = realExec
  vi.unstubAllGlobals()
})

async function createdSheet() {
  const ui = useUIStore() as any
  ui.showQuickAgentModal = false
  const w = mount(QuickAgentModal, { global: { stubs: { Icon: true, Teleport: true } } })
  ui.showQuickAgentModal = true
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('input.qa-input').setValue('Copy Test Agent')
  await w.find('.qa-foot .qa-btn--primary').trigger('click')
  for (let i = 0; i < 6; i++) await flushPromises()
  expect(w.find('.qa-copy').exists(), 'the success sheet with its credentials block').toBe(true)
  return w
}

describe('the quick agent sheet copies the credentials before it says so', () => {
  it('no clipboard API and no fallback: it does not say "Copied"', async () => {
    setClipboard(undefined)
    ;(document as any).execCommand = vi.fn(() => false)
    const w = await createdSheet()
    await w.find('.qa-copy').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.find('.qa-copy').text()).not.toContain('Copied')
    expect(w.find('.qa-copy').text()).toContain('Copy as a block')
    w.unmount()
  })

  it('a refused clipboard write falls back, and says "Copied" only when the fallback copied', async () => {
    setClipboard({ writeText: vi.fn(() => Promise.reject(new Error('denied'))) })
    const exec = vi.fn(() => true)
    ;(document as any).execCommand = exec
    const w = await createdSheet()
    await w.find('.qa-copy').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(exec).toHaveBeenCalledWith('copy')
    expect(w.find('.qa-copy').text()).toContain('Copied to clipboard')
    w.unmount()
  })

  it('control: a clipboard write that succeeds says "Copied" and carries the block', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    setClipboard({ writeText })
    const w = await createdSheet()
    await w.find('.qa-copy').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(String((writeText.mock.calls as unknown[][])[0][0])).toContain('Client ID: agent-cid')
    expect(w.find('.qa-copy').text()).toContain('Copied to clipboard')
    w.unmount()
  })
})

describe('the name hint shows the handle the card gets', () => {
  it('the hint is agentSlug(name), the humanReadableId agentApi.create sends', async () => {
    const ui = useUIStore() as any
    ui.showQuickAgentModal = false
    const w = mount(QuickAgentModal, { global: { stubs: { Icon: true, Teleport: true } } })
    ui.showQuickAgentModal = true
    for (let i = 0; i < 4; i++) await flushPromises()
    const hintCode = () => w.findAll('.qa-hint code').map((c) => c.text())
    expect(hintCode()).toContain('agent-name')
    for (const name of ['Café Bot #1?', '研究助手', 'Research Assistant']) {
      await w.find('input.qa-input').setValue(name)
      expect(hintCode()).toContain(agentSlug(name))
    }
    expect(agentSlug('Café Bot #1?')).toBe('cafe-bot-1')
    w.unmount()
  })
})
