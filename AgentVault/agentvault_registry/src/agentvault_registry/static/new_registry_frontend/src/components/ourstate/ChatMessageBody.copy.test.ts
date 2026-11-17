import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ChatMessageBody from './ChatMessageBody.vue'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): a code block in a message has a language label and a copy
 * button; a click on it puts that block's code on the clipboard and says Copied for a moment. One listener on the body
 * catches every block's button (the sanitized HTML carries no handler). Tables, task lists and collapsible sections render
 * in the message. BASE (7a2dddb62): a code block is a bare <pre>, a table is text.
 */
const body = 'Run this:\n\n```bash\nmake test\n```\n\nthen this:\n\n```\nmake ship\n```'
let writeText: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  writeText = vi.fn(async () => {})
  vi.stubGlobal('navigator', { clipboard: { writeText } })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('the copy button on a code block', () => {
  it('is on every block, with the language when the fence names one', () => {
    const w = mount(ChatMessageBody, { props: { body } })
    const buttons = w.findAll('.cm-copy')
    expect(buttons).toHaveLength(2)
    expect(buttons.map((b) => b.text())).toEqual(['Copy', 'Copy'])
    expect(buttons[0].attributes('type')).toBe('button')
    expect(w.findAll('.cm-code-lang').map((l) => l.text())).toEqual(['bash'])
  })

  it('copies its own block\'s code and says Copied, and the other block is untouched', async () => {
    const w = mount(ChatMessageBody, { props: { body } })
    const buttons = w.findAll('.cm-copy')
    await buttons[1].trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('make ship\n')
    expect(buttons[1].text()).toBe('Copied')
    expect(buttons[0].text()).toBe('Copy')
  })

  it('goes back to Copy after a moment', async () => {
    const w = mount(ChatMessageBody, { props: { body } })
    const btn = w.findAll('.cm-copy')[0]
    await btn.trigger('click')
    await flushPromises()
    expect(btn.text()).toBe('Copied')
    vi.advanceTimersByTime(1600)
    expect(btn.text()).toBe('Copy')
  })

  it('a click on the message\'s words copies nothing', async () => {
    const w = mount(ChatMessageBody, { props: { body } })
    await w.find('p').trigger('click')
    await flushPromises()
    expect(writeText).not.toHaveBeenCalled()
  })

  it('a message with no code has no button and no wrapper', () => {
    const w = mount(ChatMessageBody, { props: { body: 'just `inline` code and words' } })
    expect(w.find('.cm-copy').exists()).toBe(false)
    expect(w.find('.cm-code').exists()).toBe(false)
  })

  it('cannot be forged: a button typed into a message is text, and only a code block makes a real one', () => {
    const w = mount(ChatMessageBody, { props: { body: '<button class="cm-copy" onclick="x()">Copy</button>' } })
    expect(w.find('button.cm-copy').exists()).toBe(false)
    expect(w.text()).toContain('<button')
  })
})

describe('the new blocks, in the message', () => {
  it('a table', () => {
    const w = mount(ChatMessageBody, { props: { body: '| a | b |\n|---|---|\n| 1 | 2 |' } })
    expect(w.findAll('th')).toHaveLength(2)
    expect(w.findAll('td').map((c) => c.text())).toEqual(['1', '2'])
  })

  it('a task list', () => {
    const w = mount(ChatMessageBody, { props: { body: '- [x] shipped\n- [ ] announced' } })
    expect(w.findAll('.cm-task-done')).toHaveLength(1)
    expect(w.findAll('.cm-task-open')).toHaveLength(1)
    expect(w.text()).toContain('shipped')
  })

  it('a collapsible section, closed', () => {
    const w = mount(ChatMessageBody, { props: { body: '::: details The log\nline one\n:::' } })
    expect(w.find('details.cm-details summary').text()).toBe('The log')
    expect((w.find('details').element as HTMLDetailsElement).open).toBe(false)
  })

  it('still a status chip first and a mention marked beside them', () => {
    const w = mount(ChatMessageBody, { props: { body: 'DONE: @lead see\n\n| a |\n|---|\n| 1 |', mentions: [{ key: 'agt:x', token: 'lead' }] } })
    expect(w.find('.cm-chip').text()).toBe('DONE')
    expect(w.find('.cm-mention').text()).toBe('@lead')
    expect(w.find('table').exists()).toBe(true)
  })
})
