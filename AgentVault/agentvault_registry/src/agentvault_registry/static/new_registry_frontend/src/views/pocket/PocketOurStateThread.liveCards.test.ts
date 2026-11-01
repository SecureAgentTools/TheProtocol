import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (aa) (order gwo_840aa2b590306f7eba147758): a card updated in place, in the open thread. An update on the socket
 * (chat.card_updated) replaces the card where it is: no new message, the newer state drawn, "updated" on it; an older
 * one changes nothing; a catch-up read (the window coming back) carries a newer rev; the card's History opens its
 * history and Escape closes it. BASE (V0651): the stream has no card update, and a catch-up keeps the old card.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as null | { onMessage: (env: any) => void; onCardUpdate: (env: any) => void },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: (o: any) => { h.stream = o } }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourchat') }) }
})
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({ credAgents: ref([]), ensureAgentFor: vi.fn().mockResolvedValue(null), noAgentReason: ref(''), sealedLocked: ref(false) }) }
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
  h.route = reactive({ params: { id: 'room1' }, query: {}, path: '/pocket/ourchat/room1' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const progress = (state: string, steps: unknown[] = []) => ({ v: 1, type: 'progress', data: { title: 'V0651 pair proof', state, steps } })
const cardMsg = (rev: number, card: unknown) => ({ id: 'm2', seq: 2, kind: 'card', body: null, card, card_rev: rev,
  card_updated_at: rev ? '2026-11-01T01:00:00Z' : null, sender_ptype: 'agent', sender_id: 'did:x:tester',
  sender_name: 'session-tester', created_at: '2026-11-01T00:00:00Z' })
const text = (id: string, seq: number) => ({ id, seq, kind: 'text', body: `m${seq}`, sender_ptype: 'developer', sender_id: '7',
  sender_name: 'Mira', created_at: '2026-11-01T00:00:00Z' })
const page = (messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm',
  my_state: 'active', counterparty: null })

describe('a card updated in place, in the open thread', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.stream = null
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('an update on the socket replaces the card where it is; an older one changes nothing', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('m1', 1), cardMsg(0, progress('running'))]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-running"]').exists()).toBe(true)
    const before = w.findAll('[data-testid^="osc-progress-"]').length
    h.stream!.onCardUpdate({ conversation_id: 'room1', kind: 'dm', message: { id: 'm2', seq: 2, card: progress('passed'),
      card_rev: 1, card_updated_at: '2026-11-01T01:05:00Z' } })
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-passed"]').exists()).toBe(true)
    expect(w.findAll('[data-testid^="osc-progress-"]').length).toBe(before)        // the same card, not a second one
    expect(w.find('[data-testid="osc-live"]').text()).toContain('Updated once')
    h.stream!.onCardUpdate({ conversation_id: 'room1', kind: 'dm', message: { id: 'm2', seq: 2, card: progress('running'),
      card_rev: 1 } })
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-passed"]').exists()).toBe(true)      // an equal rev: nothing moves back
    h.stream!.onCardUpdate({ conversation_id: 'another', kind: 'dm', message: { id: 'm2', seq: 2, card: progress('failed'),
      card_rev: 9 } })
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-passed"]').exists()).toBe(true)      // another thread's update is not this one's
    w.unmount()
  })

  it('a catch-up read carries a newer rev of a card the thread holds', async () => {
    h.chat.getMessages = vi.fn()
      .mockResolvedValueOnce(page([text('m1', 1), cardMsg(0, progress('running'))]))
      .mockResolvedValue(page([text('m1', 1), cardMsg(2, progress('failed'))]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-running"]').exists()).toBe(true)
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(w.find('[data-testid="osc-progress-failed"]').exists()).toBe(true)
    expect(w.find('[data-testid="osc-live"]').text()).toContain('Updated 2 times')
    w.unmount()
  })

  it("the Guild's order card speaks as the Guild, not as a person", async () => {
    const guild = { id: 'm3', seq: 3, kind: 'card', body: null, card_rev: 1, card_updated_at: '2026-11-01T01:00:00Z',
      sender_ptype: 'system', sender_id: 'guild', created_at: '2026-11-01T00:00:00Z',
      card: { v: 1, type: 'guild.order.live', refs: { order_id: 'gwo_1' }, data: { order_id: 'gwo_1', title: 'Build (ad)',
        status: 'open', bounty: '15', currency: 'ECU', bids: 0, events: [{ type: 'posted', at: null }] } } }
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('m1', 1), guild]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-rail-author"]').text()).toContain('Guild')
    expect(w.find('[data-testid="osc-guild-live"]').exists()).toBe(true)
    w.unmount()
  })

  it("History opens the card's history; Escape closes it", async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([cardMsg(1, progress('passed'))]))
    h.chat.cardHistory = vi.fn().mockResolvedValue({ card_rev: 1, posted_at: '2026-11-01T00:00:00Z', updates: [
      { rev: 1, at: '2026-11-01T01:00:00Z', by: { ptype: 'agent', id: 'did:x:tester', name: 'session-tester' },
        changes: [{ path: 'state', from: 'running', to: 'passed' }] }] })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    await w.find('[data-testid="osc-history"]').trigger('click')
    await flushPromises()
    expect(h.chat.cardHistory).toHaveBeenCalledWith('dev-tok', 'room1', 'm2')
    expect(w.find('[data-testid="cch-rev-1"]').text()).toContain('state: running → passed')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(w.find('[data-testid="ost-card-history"]').exists()).toBe(false)
    w.unmount()
  })
})
