import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1): the thread, readable at a glance: markdown in the bubble (raw HTML is
 * text), a chip, a long message folded, a time on every message, what names the viewer or waits on them highlighted,
 * and "For me" shows only those. BASE (V0651): the raw text, no time, nothing highlighted.
 */
const AGENT = { did: 'did:theprotocol:eu.theprotocol.cloud:19c1aa48', name: 'session-tester' }
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  auth: { token: 'dev.tok', user: { developer_id: 6 }, agentToken: 'agent.tok', activeAgent: null as any },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const no = () => vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } }))
  const c = { get: no(), post: no(), put: no(), delete: no() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn().mockResolvedValue(undefined),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev.tok' }))
vi.mock('@/composables/useChatStream', async () => {
  const { ref } = await import('vue')
  return { useChatStream: () => ({ isConnected: ref(true), disconnect: () => {} }) }
})
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourchat') }) }
})
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({ credAgents: ref([{ did: AGENT.did, name: AGENT.name }]), ensureAgentFor: vi.fn().mockResolvedValue(true),
    noAgentReason: ref(''), sealedLocked: ref(false) }) }
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
  h.route = reactive({ params: { id: 'room-a' }, query: {}, path: '/pocket/ourchat/room-a' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

// the renderer, called through, counted (session-lead's review seq 378: a keystroke must re-render no message)
vi.mock('@/services/chat/messageText', async (orig) => {
  const m: any = await orig()
  return { ...m, renderMessage: vi.fn(m.renderMessage) }
})

import PocketOurStateThread from './PocketOurStateThread.vue'
import { renderMessage } from '@/services/chat/messageText'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
const at = (min: number) => new Date(Date.now() - min * 60e3).toISOString()
// a mention as the server stores and ships it (services/chat_mentions.py; the sessions' room seq 596), never { key, label }
const DEV6 = { key: 'dev:6', ptype: 'developer', developer_id: 6, agent_did: null, token: 'maintainer' }
const MSGS = [
  { id: 'm1', seq: 1, kind: 'text', sender_ptype: 'agent', sender_id: 'did:theprotocol:eu:lead', sender_name: 'session-lead',
    body: 'DONE: the **sandbox** roll\n\n- beta\n- alpha\n\n<script>alert(1)</script>', created_at: at(30), mentions: [] },
  { id: 'm2', seq: 2, kind: 'text', sender_ptype: 'agent', sender_id: 'did:theprotocol:eu:lead', sender_name: 'session-lead',
    body: '@maintainer please look', created_at: at(20), mentions: [DEV6] },
  { id: 'm3', seq: 3, kind: 'card', sender_ptype: 'agent', sender_id: 'did:theprotocol:eu:rel', sender_name: 'session-release',
    card: { v: 1, type: 'approval.request', data: { approval_id: 'apr_' + '1'.repeat(32), title: 'Roll' } }, created_at: at(10) },
  { id: 'm4', seq: 4, kind: 'text', sender_ptype: 'developer', sender_id: 6, sender_name: 'maintainer',
    body: 'my own @maintainer note', created_at: at(5), mentions: [DEV6] },
]
const room = { messages: MSGS, last_seq: 4, page_bound: 40, kind: 'dm', my_state: 'active', my_last_read_seq: 4,
  counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } }

async function open() {
  h.chat.getMessages = vi.fn().mockResolvedValue(room)
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe('the thread, readable at a glance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = null
    h.auth.user = { developer_id: 6, name: 'maintainer' } as any
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('renders markdown and a chip; a script in a message stays text', async () => {
    const w = await open()
    const m1 = w.find('[data-testid="ost-msg-1"]')
    expect(m1.find('[data-testid="cm-chip"]').text()).toBe('DONE')
    expect(m1.find('strong').text()).toBe('sandbox')
    expect(m1.findAll('li').length).toBe(2)
    expect(m1.find('script').exists()).toBe(false)
    expect(m1.text()).toContain('<script>alert(1)</script>')
  })

  it('a time on every message', async () => {
    const w = await open()
    for (const seq of [1, 2, 3, 4]) {
      const t = w.find(`[data-testid="ost-time-${seq}"]`)
      expect(t.exists()).toBe(true)
      expect(t.text()).toMatch(/\d{1,2}[:.]\d{2}/)
      expect(t.attributes('title')).toBeTruthy()
    }
  })

  it('what names the viewer or waits on them stands out, never their own message', async () => {
    const w = await open()
    expect(w.find('[data-testid="ost-msg-2"]').classes()).toContain('for-me')
    expect(w.find('[data-testid="ost-msg-3"]').classes()).toContain('ask')
    expect(w.find('[data-testid="ost-msg-1"]').classes()).not.toContain('for-me')
    expect(w.find('[data-testid="ost-msg-4"]').classes()).not.toContain('for-me')
    expect(w.find('[data-testid="ost-msg-2"] .cm-me').text()).toBe('@maintainer')
  })

  it('typing in the composer re-renders no message (session-lead, seq 378)', async () => {
    const w = await open()
    const spy = renderMessage as unknown as ReturnType<typeof vi.fn>
    const before = spy.mock.calls.length
    expect(before).toBeGreaterThanOrEqual(3)            // the three text messages were rendered
    const input = w.find('[data-testid="ost-input"]')
    for (const s of ['h', 'he', 'hel', 'hell', 'hello']) await input.setValue(s)
    await flushPromises()
    expect(spy.mock.calls.length).toBe(before)
  })

  it('"For me" shows only those, and the whole room again', async () => {
    const w = await open()
    const toggle = w.find('[data-testid="ost-forme-toggle"]')
    expect(toggle.text()).toContain('2')
    await toggle.trigger('click')
    expect(w.findAll('[data-testid^="ost-msg-"]').map((e) => e.attributes('data-testid'))).toEqual(['ost-msg-2', 'ost-msg-3'])
    await w.find('[data-testid="ost-forme-toggle"]').trigger('click')
    expect(w.findAll('[data-testid^="ost-msg-"]').length).toBe(4)
  })
})
