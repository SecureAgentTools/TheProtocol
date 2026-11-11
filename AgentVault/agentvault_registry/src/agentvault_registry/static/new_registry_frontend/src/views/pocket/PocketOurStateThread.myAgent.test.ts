import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0659 (o) (order gwo_d7ce94c88a55f629c17b4ff7), the maintainer in the sessions' room (seq 1833): "if any of my agents
 * use any card, i should also see it ... maybe opake or some other indicator/distinction so the dev knows this is from his
 * agent and not posted by him/his dev account."
 *
 * The thread the console (/ourchat/:id) and Pocket (/pocket/ourchat/:id) both mount: every card type the registry posts,
 * from one of the viewer's own agents (the registry says so: sender_is_my_agent), is drawn, on his side of the thread, in
 * a lighter bubble or frame than his own, under the agent's name with a "your agent" mark. His own lines stay as they were;
 * a line he typed as his agent through his own session is his own; another member's agent is not his. The card types are
 * read from the registry's vocabulary (services/chat_service.py), so a new type fails here until it is drawn too.
 * BASE (origin/v0657/cut): his agents' lines are drawn as his own (the agents he owns are among those this browser can act
 * as, since V0641), with no mark, and his agent's request to him is not "for me".
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as null | { onMessage: (env: any) => void },
  credAgents: [] as Array<Record<string, unknown>>,
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
  return { usePocketAgent: () => ({ credAgents: ref(h.credAgents), ensureAgentFor: vi.fn().mockResolvedValue(null), noAgentReason: ref(''), sealedLocked: ref(false) }) }
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

/** The registry's closed card vocabulary, read from its source: the types it posts, and the ones it refuses for now. */
function frozenset(src: string, name: string): string[] {
  const start = src.indexOf(`${name} = frozenset({`)
  if (start < 0) throw new Error(`${name} is not in services/chat_service.py`)
  const body = src.slice(start, src.indexOf('})', start)).split('\n').map((l) => l.replace(/#.*$/, '')).join('\n')
  return [...body.matchAll(/"([a-z][a-z0-9_.]*)"/g)].map((m) => m[1])
}
const SERVICE = fs.readFileSync(path.resolve(__dirname, '../../../../../services/chat_service.py'), 'utf8')
const POSTED = [...frozenset(SERVICE, 'CLIENT_POSTABLE_CARDS'), ...frozenset(SERVICE, 'RAIL_ONLY_CARDS')].sort()
const LATER = frozenset(SERVICE, 'LATER_PHASE_CARDS').sort()

const ME = 6
const AGENT = 'did:theprotocol:eu.test:session-lead'      // one of the viewer's own agents
const PEER = 'did:theprotocol:eu.test:member-agent'       // another member's agent
const APR = `apr_${'a'.repeat(32)}`
const SAMPLES: Record<string, { data: Record<string, unknown>; refs?: Record<string, unknown> }> = {
  'pay.request': { data: { amount: '12.5', currency: 'ECU', memo: 'the proof run' } },
  'pay.receipt': { data: { amount: '12.5', currency: 'ECU', tx_id: 'tx-v0659' } },
  'agent.card': { data: { did: PEER, name: 'member-agent' } },
  'contract.offer': { data: { ref: 'ctr_v0659', title: 'Translate the handbook' } },
  'guild.order': { data: { ref: 'gwo_000000000000000000000001', title: 'Write the proxy\'s MQTT source' } },
  media: { data: { attachment_id: 'att-v0659', name: 'report.md', mime: 'text/markdown', bytes: 120 } },
  applet: { data: { title: 'Pick a slot', fields: [{ kind: 'text', key: 'note', label: 'Note' }], action: { kind: 'open_reply', label: 'Send' } } },
  'exchange.listing': { data: { symbol: 'SMKD', display_name: 'Samarkand Freight Lines' } },
  'engagement.proposal': { data: { title: 'Audit the ledger', total: '40', currency: 'ECU' } },
  'engagement.counter': { data: { title: 'Audit the ledger', total: '35', currency: 'ECU' }, refs: { supersedes: 'msg-proposal' } },
  progress: { data: { title: 'V0659 pair proof', state: 'running', steps: [{ label: 'console', state: 'running' }] } },
  'service.call': { data: { ask: 'the weather in Berlin', status: 'dispatched' } },
  'service.result': { data: { ok: true, stage: 'settled', summary: 'delivered' } },
  'share.certificate': { data: { certificate_id: 'cert-v0659', symbol: 'SMKD', qty: 3, currency: 'ECU', digest: '0'.repeat(64) } },
  'org.work.receipt': { data: { kind: 'treasury.fund', amount: '5', currency: 'ECU' } },
  'engagement.offer': { data: { contract_id: 'ctr_v0659', total: '40', currency: 'ECU' } },
  'engagement.accepted': { data: { contract_id: 'ctr_v0659', total: '40', currency: 'ECU' } },
  'engagement.milestone': { data: { contract_id: 'ctr_v0659', seq: 1 } },
  'engagement.settled': { data: { contract_id: 'ctr_v0659', seq: 1, amount: '40', currency: 'ECU' } },
  'approval.request': { data: { approval_id: APR, title: 'Roll V0659 to the sandbox', expires_at: '2026-11-08T12:00:00+00:00' } },
  'approval.decided': { data: { approval_id: APR, title: 'Roll V0659 to the sandbox', decision: 'approved', decided_by_developer_id: ME } },
  'choice.request': { data: { approval_id: APR, title: 'Which slot', options: ['morning', 'evening'], expires_at: '2026-11-08T12:00:00+00:00' } },
  'choice.decided': { data: { approval_id: APR, title: 'Which slot', options: ['morning', 'evening'], decision: 'chosen',
    decided_by_developer_id: ME, chosen: { index: 0, label: 'morning' } } },
  'guild.order.live': { data: { order_id: 'gwo_000000000000000000000002', title: 'Write the proxy\'s SFTP source', status: 'open', events: [] } },
}
const at = '2026-11-07T10:45:00Z'
const cardLine = (seq: number, type: string, over: Record<string, unknown> = {}) => ({
  id: `m${seq}`, seq, kind: 'card', body: null, card: { v: 1, type, ...SAMPLES[type] }, sender_ptype: 'agent',
  sender_id: AGENT, sender_name: 'session-lead', sender_is_my_agent: true, created_at: at, ...over })
const textLine = (seq: number, over: Record<string, unknown> = {}) => ({
  id: `m${seq}`, seq, kind: 'text', body: `line ${seq}`, card: null, sender_ptype: 'agent', sender_id: AGENT,
  sender_name: 'session-lead', sender_is_my_agent: true, created_at: at, ...over })
const ownLine = (seq: number) => ({ id: `m${seq}`, seq, kind: 'text', body: 'approved', card: null, sender_ptype: 'developer',
  sender_id: String(ME), sender_name: 'maintainer', sender_is_my_agent: false, created_at: at })
const page = (messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'org',
  my_state: 'active', counterparty: null, my_last_read_seq: 0 })
const msgEl = (w: any, seq: number) => w.find(`[data-testid="ost-msg-${seq}"]`)

describe('what my own agents post, in my thread', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.stream = null
    // the agents the viewer owns are among those this browser acts as (V0641: through his session, no secret saved)
    h.credAgents = [{ did: AGENT, name: 'session-lead', client_id: '', client_secret: '', viaSession: true }]
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('has a sample for every card type the registry posts (a new type fails here until it has one)', () => {
    expect(Object.keys(SAMPLES).sort()).toEqual(POSTED)
    expect(LATER, 'a type the registry refuses for now; posted one day, it moves to the lists above').toEqual(['topup.offer'])
  })

  it('every card type my agent posts is drawn, as my agent\'s and never as my own', async () => {
    const lines = [ownLine(1), ...POSTED.map((type, i) => cardLine(i + 2, type))]
    h.chat.getMessages = vi.fn().mockResolvedValue(page(lines))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const drawn: string[] = []
    POSTED.forEach((type, i) => {
      const el = msgEl(w, i + 2)
      expect(el.exists(), `${type}: the line is in the thread`).toBe(true)
      expect(el.find(`[data-testid="osc-${type}"]`).exists(), `${type}: its card is drawn`).toBe(true)
      expect(el.find('[data-testid="osc-unknown"]').exists(), `${type}: not as an unsupported card`).toBe(false)
      expect(el.classes(), `${type}: marked as my agent's`).toContain('my-agent')
      drawn.push(type)
    })
    expect(drawn).toEqual(POSTED)
    // the agent's name heads its lines, with the mark beside it
    const author = w.find('[data-testid="ost-author-2"]')
    expect(author.find('[data-testid="ost-my-agent"]').exists()).toBe(true)
    expect(author.find('[data-testid="ost-my-agent"]').text()).toBe('your agent')
    // my own line stays as it was: mine, unmarked
    expect(msgEl(w, 1).classes()).toContain('mine')
    expect(msgEl(w, 1).classes()).not.toContain('my-agent')
    expect(w.find('[data-testid="ost-author-1"] [data-testid="ost-my-agent"]').exists()).toBe(false)
    w.unmount()
  })

  it('a text line of my agent\'s is marked as well, in a lighter bubble than my own', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([ownLine(1), textLine(2)]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(msgEl(w, 2).classes()).toContain('my-agent')
    expect(msgEl(w, 2).find('.ost-bubble').exists()).toBe(true)
    expect(w.find('[data-testid="ost-author-2"] [data-testid="ost-my-agent"]').exists()).toBe(true)
    expect(msgEl(w, 1).classes()).not.toContain('my-agent')
    w.unmount()
  })

  it('another member\'s agent is not mine, and neither is a rail\'s card', async () => {
    const guild = { ...cardLine(3, 'guild.order.live'), sender_ptype: 'system', sender_id: 'guild', sender_name: 'Guild',
      sender_is_my_agent: false }
    h.chat.getMessages = vi.fn().mockResolvedValue(page([ownLine(1),
      textLine(2, { sender_id: PEER, sender_name: 'member-agent', sender_is_my_agent: false }), guild]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    for (const seq of [2, 3]) {
      expect(msgEl(w, seq).classes()).not.toContain('my-agent')
      expect(msgEl(w, seq).classes()).not.toContain('mine')
    }
    expect(w.find('[data-testid="ost-my-agent"]').exists()).toBe(false)
    expect(msgEl(w, 3).find('[data-testid="osc-guild.order.live"]').exists()).toBe(true)
    w.unmount()
  })

  it('a line I typed as my agent through my own session stays my own', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([textLine(1, { sent_by_owner: true })]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(msgEl(w, 1).classes()).toContain('mine')
    expect(msgEl(w, 1).classes()).not.toContain('my-agent')
    expect(w.find('[data-testid="ost-by-owner"]').exists()).toBe(true)
    w.unmount()
  })

  it('my agent\'s request to me waits on me ("for me"), and its money doors stay closed to me', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([ownLine(1), cardLine(2, 'approval.request'),
      cardLine(3, 'pay.request'), cardLine(4, 'pay.request', { sender_id: PEER, sender_name: 'member-agent', sender_is_my_agent: false })]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(msgEl(w, 2).classes()).toContain('for-me')
    expect(msgEl(w, 3).find('[data-testid="osc-pay-door"]').exists(), 'no Pay on my own side\'s request').toBe(false)
    expect(msgEl(w, 4).find('[data-testid="osc-pay-door"]').exists(), 'Pay on another member\'s').toBe(true)
    w.unmount()
  })

  it('one agent, two hands: a line I typed as my agent and a line it wrote itself each head their own author row', async () => {
    // REVIEW (98edfcf03): the author row followed the sender alone, so the second line sat under the first one's row:
    // my agent's own line under "sent by its owner" (no mark), or a line I typed under the "your agent" mark
    h.chat.getMessages = vi.fn().mockResolvedValue(page([textLine(1, { sent_by_owner: true }), textLine(2),
      textLine(3, { sent_by_owner: true })]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    for (const [seq, own] of [[1, false], [2, true], [3, false]] as const) {
      const author = w.find(`[data-testid="ost-author-${seq}"]`)
      expect(author.exists(), `line ${seq} heads its own author row`).toBe(true)
      expect(author.find('[data-testid="ost-my-agent"]').exists(), `line ${seq}: the "your agent" mark`).toBe(own)
      expect(author.find('[data-testid="ost-by-owner"]').exists(), `line ${seq}: "sent by its owner"`).toBe(!own)
    }
    w.unmount()
  })

  it('what my agent wrote since I last read is new to me: the NEW line stands before it', async () => {
    // BASE (origin/v0658/cut): my agent's lines counted as mine, so nothing after my own line read as new
    h.chat.getMessages = vi.fn().mockResolvedValue({ ...page([ownLine(1), textLine(2), textLine(3)]), my_last_read_seq: 1 })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const line = w.find('[data-testid="ost-unread-line"]')
    expect(line.exists(), 'the NEW line').toBe(true)
    expect(line.text()).toContain('2')
    const order = w.findAll('[data-testid="ost-unread-line"], [data-testid^="ost-msg-"]').map((e) => e.attributes('data-testid'))
    expect(order.indexOf('ost-unread-line')).toBe(order.indexOf('ost-msg-2') - 1)
    w.unmount()
  })

  it('a thread under my line counts my agent\'s replies as new, and opens by itself for its request to me', async () => {
    // BASE (origin/v0658/cut): its replies were mine, so the bar said nothing new and the request stayed folded
    h.chat.getMessages = vi.fn().mockResolvedValue({ ...page([ownLine(1), textLine(2, { reply_to: 'm1' }),
      cardLine(3, 'approval.request', { reply_to: 'm1' })]), my_last_read_seq: 1 })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const bar = w.find('[data-testid="ost-thread-1"]')
    expect(bar.exists(), 'the thread\'s bar under my line').toBe(true)
    expect(bar.find('.ost-thread-new').exists(), 'the bar says what is new').toBe(true)
    expect(bar.find('.ost-thread-new').text()).toContain('2 new')
    expect(bar.find('.ost-thread-forme').exists(), 'the bar says what is for me').toBe(true)
    expect(bar.find('.ost-thread-forme').text()).toContain('1 for you')
    expect(bar.attributes('aria-expanded'), 'its request to me opens the thread').toBe('true')
    expect(msgEl(w, 3).classes()).toContain('in-thread')
    expect(msgEl(w, 3).classes()).toContain('my-agent')
    w.unmount()
  })

  it('a live line without the mark takes what the thread said about the same agent', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([ownLine(1), textLine(2)]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const { sender_is_my_agent: _drop, ...bare } = cardLine(3, 'progress')
    h.stream!.onMessage({ conversation_id: 'room1', kind: 'org', message: bare })
    h.stream!.onMessage({ conversation_id: 'room1', kind: 'org', message: { ...textLine(4), sender_id: PEER,
      sender_name: 'member-agent', sender_is_my_agent: undefined } })
    await flushPromises()
    expect(msgEl(w, 3).classes()).toContain('my-agent')
    expect(msgEl(w, 4).classes()).not.toContain('my-agent')
    w.unmount()
  })
})
