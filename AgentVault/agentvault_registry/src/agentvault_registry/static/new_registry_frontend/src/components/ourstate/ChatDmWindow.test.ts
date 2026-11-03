import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0655 (ay) (order gwo_57362aa3484807226198b8de): the small direct-message window the room's side panel opens. It opens
 * the direct thread with the member through the chat's own routes (the existing thread, or a new one as the chat allows),
 * shows its last lines, and a sent line lands in that thread. BASE (V0654): the component does not exist.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))

import ChatDmWindow from './ChatDmWindow.vue'

const LEAD = { did: 'did:theprotocol:eu.test:Lead', name: 'session-lead' }
const msg = (seq: number, body: string, mine: boolean) => ({ id: `d${seq}`, seq, kind: 'text', body,
  sender_ptype: mine ? 'developer' : 'agent', sender_id: mine ? 6 : 'did:theprotocol:eu.test:lead', created_at: '2026-11-03T11:00:00Z' })

function mountWindow(target = LEAD) {
  return mount(ChatDmWindow, { props: { token: 'dev.tok', target }, attachTo: document.body })
}

describe('the direct-message window over the room', () => {
  beforeEach(() => {
    h.chat = {}
    h.chat.createConversation = vi.fn().mockResolvedValue({ conversation_id: 'dm-1', created: false })
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [msg(7, 'which proof runs first?', false), msg(8, 'the console proof', true)] })
  })

  it('opens the member\'s direct thread through the chat\'s own routes and shows its last lines, who wrote each', async () => {
    const w = mountWindow()
    await flushPromises()
    expect(h.chat.createConversation).toHaveBeenCalledWith('dev.tok', 'dm', { ptype: 'agent', agent_did: LEAD.did })
    expect(h.chat.getMessages).toHaveBeenCalledWith('dev.tok', 'dm-1', undefined, 6)
    expect(w.attributes('data-conv')).toBe('dm-1')
    expect(w.attributes('role')).toBe('dialog')
    expect(w.attributes('aria-label')).toBe('Direct message with session-lead')
    expect(w.find('[data-testid="cdw-line-7"]').text()).toContain('session-lead')     // the DID matched without case
    expect(w.find('[data-testid="cdw-line-8"]').text()).toContain('You')
    expect(w.find('[data-testid="cdw-line-8"]').classes()).toContain('mine')
    w.unmount()
  })

  it('a sent line lands in the direct thread, shows in the window, and clears the box', async () => {
    h.chat.postMessage = vi.fn().mockResolvedValue({ message: msg(9, 'start the pair proof after it', true) })
    const w = mountWindow()
    await flushPromises()
    await w.find('[data-testid="cdw-input"]').setValue('  start the pair proof after it ')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(1)
    const [tok, conv, payload] = h.chat.postMessage.mock.calls[0]
    expect([tok, conv, payload.kind, payload.body]).toEqual(['dev.tok', 'dm-1', 'text', 'start the pair proof after it'])
    expect(typeof payload.client_ref).toBe('string')
    expect(w.find('[data-testid="cdw-line-9"]').text()).toContain('start the pair proof after it')
    expect((w.find('[data-testid="cdw-input"]').element as HTMLTextAreaElement).value).toBe('')
    w.unmount()
  })

  it('a refused send keeps the line in the box and says so; an empty box sends nothing', async () => {
    h.chat.postMessage = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'rate limited' }))
    const w = mountWindow()
    await flushPromises()
    await w.find('form').trigger('submit')
    expect(h.chat.postMessage).not.toHaveBeenCalled()
    await w.find('[data-testid="cdw-input"]').setValue('hello')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-testid="cdw-send-failed"]').text()).toBe('rate limited')
    expect((w.find('[data-testid="cdw-input"]').element as HTMLTextAreaElement).value).toBe('hello')
    w.unmount()
  })

  it('a thread that cannot be opened says so and offers no box to type into', async () => {
    h.chat.createConversation = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'you cannot message this agent' }))
    const w = mountWindow()
    await flushPromises()
    expect(w.find('[data-testid="cdw-failed"]').text()).toBe('you cannot message this agent')
    expect(w.find('[data-testid="cdw-input"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="cdw-open"]').attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('Escape and the close button close it; Open the thread names the thread', async () => {
    const w = mountWindow()
    await flushPromises()
    await w.find('[data-testid="cdw-input"]').trigger('keydown', { key: 'Escape' })
    await w.find('[data-testid="cdw-close"]').trigger('click')
    expect(w.emitted('close')?.length).toBe(2)
    await w.find('[data-testid="cdw-open"]').trigger('click')
    expect(w.emitted('open')).toEqual([['dm-1']])
    w.unmount()
  })

  it('another member opens that member\'s thread', async () => {
    const w = mountWindow()
    await flushPromises()
    h.chat.createConversation.mockResolvedValueOnce({ conversation_id: 'dm-2', created: true })
    h.chat.getMessages.mockResolvedValueOnce({ messages: [] })
    await w.setProps({ target: { did: 'did:theprotocol:eu.test:tester', name: null } })
    await flushPromises()
    expect(h.chat.createConversation).toHaveBeenLastCalledWith('dev.tok', 'dm', { ptype: 'agent', agent_did: 'did:theprotocol:eu.test:tester' })
    expect(w.attributes('data-conv')).toBe('dm-2')
    expect(w.find('[data-testid="cdw-empty"]').exists()).toBe(true)
    expect(w.find('.cdw-who').text()).toBe('did:theprotocol:eu.test:tester')     // no name: the DID, never blank
    w.unmount()
  })
})
