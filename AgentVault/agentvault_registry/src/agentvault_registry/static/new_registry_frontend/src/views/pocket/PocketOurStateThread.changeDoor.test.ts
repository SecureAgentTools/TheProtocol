import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

/**
 * V0666 D3 (order gwo_542285271416c653ca39af3f): /change <title> in a conversation. In an organization's room it opens the
 * Code changes proposal for that organization's release line, prefilled with the title and announced in this room; several
 * lines offer a picker; no line, code distributions off, or a conversation that is no organization's room says why in one
 * sentence and opens nothing. Parsing never posts. Red before D3: /change is an unknown command.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  push: null as unknown as Mock<(to: unknown) => Promise<undefined>>,
  lines: null as any, enabled: true, creds: [{ did: 'did:a:me' }] as any[],
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/api/codeDistributions', () => ({ listOrgLines: (...a: any[]) => h.lines(...a) }))
vi.mock('@/composables/useRegistryConfig', async (orig) => ({ ...(await orig<any>()),
  useRegistryConfig: () => ({ codeDistributionsEnabled: ref(h.enabled), load: vi.fn(), config: ref({}), loaded: ref(true), readFailed: ref(false),
    workflowTemplatesEnabled: ref(false), localCurrency: ref('ECU') }) }))
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/ourchat') }) }
})
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({ credAgents: ref(h.creds), ensureAgentFor: vi.fn().mockResolvedValue(null), noAgentReason: ref(''), sealedLocked: ref(false) }) }
})
vi.mock('@/composables/usePocketLock', async () => {
  const { ref } = await import('vue')
  return { usePocketLock: () => ({ enabled: ref(false), verify: vi.fn().mockResolvedValue(true) }) }
})
vi.mock('@/composables/useActingContext', async () => {
  const { ref } = await import('vue')
  return { useActingContext: () => ({ actingCurrencyLabel: ref('ECU') }) }
})
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  const route = reactive({ params: { id: 'room1' }, query: {}, path: '/ourchat/room1' })
  return { useRoute: () => route, useRouter: () => ({ push: (to: unknown) => h.push(to), replace: vi.fn().mockResolvedValue(undefined) }) }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const page = (room: unknown) => ({ messages: [], last_seq: 0, page_bound: 40, kind: room ? 'org' : 'dm', my_state: 'active', counterparty: null, room })
const L = (slug: string, state = 'active') => ({ slug, title: `Line ${slug}`, release_name: `V0666_${slug}`, state })

async function type(room: unknown, text: string) {
  h.chat.getMessages = vi.fn().mockResolvedValue(page(room))
  const w = mount(PocketOurStateThread, opts)
  await flushPromises()
  await w.find('[data-testid="ost-input"]').setValue(text)
  await w.find('[data-testid="ost-send"]').trigger('click')
  await flushPromises()
  return w
}

describe('/change in a conversation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}; h.enabled = true; h.creds = [{ did: 'did:a:me' }]
    h.push = vi.fn(async (_to: unknown) => undefined)
    h.lines = vi.fn().mockResolvedValue([L('lyceum')])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('in an organization\'s room with one line opens the proposal for it, with the title, announced in this room; nothing is posted', async () => {
    const w = await type({ org_id: 'org-a', title: 'Builders' }, '/change A seating chart')
    expect(h.lines).toHaveBeenCalledWith('org-a')
    expect(h.push).toHaveBeenCalledWith({ name: 'code-changes-new', query: { line: 'lyceum', room: 'room1', title: 'A seating chart' } })
    expect(h.chat.postMessage).toBeUndefined()
    w.unmount()
  })

  it('with several lines offers a picker, and the pick opens that line', async () => {
    h.lines = vi.fn().mockResolvedValue([L('lyceum'), L('kiosk')])
    const w = await type({ org_id: 'org-a' }, '/change A seating chart')
    expect(h.push).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ost-change-pick"]').text()).toContain('Which release line')
    await w.find('[data-testid="ost-change-pick-kiosk"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'code-changes-new', query: { line: 'kiosk', room: 'room1', title: 'A seating chart' } })
    expect(w.find('[data-testid="ost-change-pick"]').exists()).toBe(false)
    w.unmount()
  })

  it('outside an organization\'s room says where it works, and asks for no line', async () => {
    const w = await type(null, '/change A seating chart')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('/change works in a room of an organization')
    expect(h.lines).not.toHaveBeenCalled(); expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })

  it('with code distributions off says so, and asks for nothing', async () => {
    h.enabled = false
    const w = await type({ org_id: 'org-a' }, '/change A seating chart')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('Code distributions are off on this registry.')
    expect(h.lines).not.toHaveBeenCalled(); expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })

  it('an organization with no line says so', async () => {
    h.lines = vi.fn().mockResolvedValue([])
    const w = await type({ org_id: 'org-a' }, '/change A seating chart')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('has no release line yet')
    expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })

  it('a /change refusal never offers to create a wallet agent: its sentence is not about an agent (chat pass 2)', async () => {
    h.creds = []
    const w = await type(null, '/change A seating chart')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('/change works in a room of an organization')
    expect(w.find('[data-testid="ost-hint-create"]').exists()).toBe(false)
    w.unmount()
  })
})
