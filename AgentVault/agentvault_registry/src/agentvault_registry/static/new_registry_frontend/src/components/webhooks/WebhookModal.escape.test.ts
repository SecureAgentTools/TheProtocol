/**
 * §COCKPITDESK (2026-10-15) — the webhook form is a dialog and Escape closes it, except while the one-time secret is on
 * screen (the backdrop does not close it then either), and never for an Escape a dialog over it used.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/api/webhookService', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  webhookService: { getSupportedEvents: vi.fn(async () => ({ events: [], live: true })) },
}))

import WebhookModal from './WebhookModal.vue'

function open() {
  setActivePinia(createPinia())
  return mount(WebhookModal, { attachTo: document.body, global: { stubs: { Teleport: true } } })
}

describe('the webhook form', () => {
  it('is a dialog, and Escape closes it', async () => {
    const w = open(); await flushPromises()
    const panel = w.find('[data-testid="wh-modal"]')
    expect(panel.attributes('role')).toBe('dialog')
    expect(panel.attributes('aria-modal')).toBe('true')
    const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(ev)
    expect(w.emitted('close')).toHaveLength(1)
    expect(ev.defaultPrevented, 'the press is marked as used').toBe(true)
    w.unmount()
  })

  it('leaves an Escape another dialog already used, and stops listening once gone', async () => {
    const w = open(); await flushPromises()
    const used = (e: Event) => e.preventDefault()
    document.addEventListener('keydown', used, { capture: true })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    document.removeEventListener('keydown', used, { capture: true })
    expect(w.emitted('close')).toBeUndefined()
    w.unmount()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(w.emitted('close')).toBeUndefined()
  })
})
