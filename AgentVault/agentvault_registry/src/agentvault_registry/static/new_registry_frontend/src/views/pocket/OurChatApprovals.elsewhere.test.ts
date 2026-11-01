import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0652 (y), his seq 477: he approved on the desktop, and his phone still offered Approve on the same request (the
 * server answered the second press with an idempotent 200, "already decided this way"). session-lead's spec (seq 481):
 * a request decided on another device leaves the panel as soon as the window comes back (focus, a visible tab), and a
 * late press says "Already approved at 04:35 (another device)", never a fresh "approved". Only the newest read applies,
 * so a read started before the decision cannot bring the decided request back.
 * BASE (V0651): no read on focus or visibility, the stale read wins, the late press says nothing.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>>, me: 6 as number | null }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: h.me === null ? null : { id: h.me } }) }))

import OurChatApprovals from './OurChatApprovals.vue'
import { timeLabel } from '@/services/chat/messageText'
import { appLocale } from '@/services/appLocale'

const NOW = Date.parse('2026-10-31T04:40:00Z')
const AT = '2026-10-31T04:35:12Z'
const item = (id: string) => ({
  id, conversation_id: 'room1', status: 'pending', title: `Request ${id}`, unlocks: `step ${id}`,
  requester: { agent_did: 'did:theprotocol:eu:00000000aaaaaa', name: 'session-release' },
  created_at: '2026-10-31T04:20:00Z', expires_at: '2026-10-31T06:00:00Z',
})
const listing = (items: unknown[]) => ({ items, can_decide: true, presence: 'off' })
const record = (id: string, decision: 'approved' | 'denied', developerId: number, name: string) => ({
  id, status: decision,
  decision: { decision, decided_at: AT, decided_by: { developer_id: developerId, name, role: 'owner' } },
})
const opts = { props: { conversationId: 'room1', token: 'dev-tok' }, global: { stubs: { Icon: true, StepUpConfirm: true } } }

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('an approval decided on another device', () => {
  beforeEach(() => {
    h.chat = {}
    h.me = 6
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => { vi.useRealTimers() })

  it('leaves the panel when the window regains focus, without a reload', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(true)
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(h.chat.listApprovals).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    w.unmount()
  })

  it('leaves the panel when the tab becomes visible again, and a hidden tab reads nothing', async () => {
    let state = 'hidden'
    const spy = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => state as DocumentVisibilityState)
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(h.chat.listApprovals).toHaveBeenCalledTimes(1)          // going away is not a reason to read
    state = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(h.chat.listApprovals).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    w.unmount()
    spy.mockRestore()
  })

  it('stops listening once the panel is gone', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_1')]))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    w.unmount()
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(h.chat.listApprovals).toHaveBeenCalledTimes(1)
  })

  it('applies only the newest read: one started before the decision cannot bring the decided request back', async () => {
    const stale = deferred<any>()
    h.chat.listApprovals = vi.fn()
      .mockResolvedValueOnce(listing([item('apr_1')]))              // the panel opens
      .mockReturnValueOnce(stale.promise)                            // focus: a read still on its way
      .mockResolvedValue(listing([]))                                // the read after the decision
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decided: [{ id: 'apr_1' }], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    window.dispatchEvent(new Event('focus'))
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    stale.resolve(listing([item('apr_1')]))                          // the old answer lands last
    await flushPromises()
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    w.unmount()
  })

  it('answers a late press with when it was approved, on another device of the same developer', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue(
      { decision: 'approved', decided: [], skipped: { apr_1: 'already_approved' }, already: true })
    h.chat.getApproval = vi.fn().mockResolvedValue(record('apr_1', 'approved', 6, 'Commander'))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    expect(h.chat.getApproval).toHaveBeenCalledWith('dev-tok', 'apr_1')
    const line = w.find('[data-testid="oca-late"]')
    expect(line.exists()).toBe(true)
    expect(line.attributes('data-mine')).toBe('1')
    expect(line.text()).toBe(`Already approved at ${timeLabel(AT, NOW, appLocale())} (another device)`)
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(false)
    expect(w.find('[data-testid="oca-error"]').exists()).toBe(false)
    expect(w.emitted('late')).toHaveLength(1)                         // the thread catches up: its card reads the decision
    w.unmount()
  })

  it('names the approver when someone else decided it', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decided: [], skipped: { apr_1: 'already_approved' }, already: true })
    h.chat.getApproval = vi.fn().mockResolvedValue(record('apr_1', 'approved', 9, 'Alex'))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    const line = w.find('[data-testid="oca-late"]')
    expect(line.attributes('data-mine')).toBe('0')
    expect(line.text()).toBe(`Already approved at ${timeLabel(AT, NOW, appLocale())} by Alex`)
    w.unmount()
  })

  it('a press the other way (409) reads the record: already denied, and no error line', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    h.chat.decideApprovals = vi.fn().mockRejectedValue(Object.assign(new Error('HTTP 409'),
      { status: 409, detail: 'already decided the other way; a decision is final' }))
    h.chat.getApproval = vi.fn().mockResolvedValue(record('apr_1', 'denied', 6, 'Commander'))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    const line = w.find('[data-testid="oca-late"]')
    expect(line.attributes('data-decision')).toBe('denied')
    expect(line.text()).toBe(`Already denied at ${timeLabel(AT, NOW, appLocale())} (another device)`)
    expect(w.find('[data-testid="oca-error"]').exists()).toBe(false)
    w.unmount()
  })

  it('a 409 whose record cannot be read keeps the server sentence', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValue(listing([item('apr_1')]))
    h.chat.decideApprovals = vi.fn().mockRejectedValue(Object.assign(new Error('HTTP 409'),
      { status: 409, detail: 'already decided the other way; a decision is final' }))
    h.chat.getApproval = vi.fn().mockRejectedValue(Object.assign(new Error('HTTP 503'), { status: 503 }))
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="oca-late"]').exists()).toBe(false)
    expect(w.find('[data-testid="oca-error"]').text()).toBe('already decided the other way; a decision is final')
    w.unmount()
  })

  it('a fresh decision says nothing late and reads no record', async () => {
    h.chat.listApprovals = vi.fn().mockResolvedValueOnce(listing([item('apr_1')])).mockResolvedValue(listing([]))
    h.chat.decideApprovals = vi.fn().mockResolvedValue({ decision: 'approved', decided: [{ id: 'apr_1' }], skipped: {} })
    const w = mount(OurChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="oca-approve-apr_1"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="oca-late"]').exists()).toBe(false)
    expect(h.chat.getApproval).toBeUndefined()
    expect(w.emitted('late')).toBeUndefined()
    w.unmount()
  })
})
