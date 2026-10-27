import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * Quick onboarding (2026-10-09): the copy button says what happened where a screen reader hears it.
 *
 * The result ("Copied", "Not copied: the browser refused") was a live region INSIDE the button, whose content is the
 * button's name: announcements from there are not reliably read (VoiceOver above all), and the fixed aria-label "Copy
 * the DID" stayed while the button showed "Copied". Now the status region sits beside the button, and the button's name
 * is the words it shows plus what it copies ("Copy the client ID", then "Copied the client ID"). The value itself is
 * never in the DOM: it is often a secret.
 */
import CopyButton from './CopyButton.vue'

const realClipboard = Object.getOwnPropertyDescriptor(globalThis.navigator, 'clipboard')
function setClipboard(value: unknown) {
  Object.defineProperty(globalThis.navigator, 'clipboard', { configurable: true, value })
}
afterEach(() => { if (realClipboard) Object.defineProperty(globalThis.navigator, 'clipboard', realClipboard) })

function mountIt(props: Record<string, unknown>) {
  return mount(CopyButton, { props: { value: 'tp_secret_never_in_the_dom', what: 'the client ID', ...props } as any, global: { stubs: { Icon: true } } })
}

describe('CopyButton', () => {
  it('the result is announced from a status region beside the button, and the name starts with the words shown', async () => {
    setClipboard({ writeText: vi.fn(() => Promise.resolve()) })
    const w = mountIt({})
    const btn = w.find('button')
    const status = w.find('[data-testid="qo-copy-status"]')
    expect(status.attributes('role')).toBe('status')
    expect(btn.element.contains(status.element)).toBe(false)
    // no aria-label to override the visible words: the name is "Copy the client ID"
    expect(btn.attributes('aria-label')).toBeUndefined()
    expect(btn.text().replace(/\s+/g, ' ').trim()).toBe('Copy the client ID')
    await btn.trigger('click')
    await flushPromises()
    expect(status.text()).toBe('Copied')
    expect(btn.text().replace(/\s+/g, ' ').trim()).toBe('Copied the client ID')
    expect(w.html()).not.toContain('tp_secret_never_in_the_dom')
    w.unmount()
  })

  it('a refused copy says so, never "Copied"', async () => {
    setClipboard({ writeText: vi.fn(() => Promise.reject(new Error('denied'))) })
    const exec = (document as any).execCommand
    ;(document as any).execCommand = vi.fn(() => false)
    const w = mountIt({})
    await w.find('button').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="qo-copy-status"]').text()).toBe('Not copied: the browser refused')
    expect(w.find('button').text()).not.toContain('Copied')
    ;(document as any).execCommand = exec
    w.unmount()
  })

  it('an icon-only button is named by its label, which says what it copies', () => {
    const w = mountIt({ iconOnly: true, what: 'the DID of Agent 1' })
    expect(w.find('button').attributes('aria-label')).toBe('Copy the DID of Agent 1')
    expect(w.find('button').text()).toBe('')
    w.unmount()
  })
})
