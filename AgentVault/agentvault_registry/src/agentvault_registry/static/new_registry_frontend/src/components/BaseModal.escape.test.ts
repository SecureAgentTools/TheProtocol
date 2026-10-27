/**
 * §COCKPITDESK (2026-10-14) — Escape closes the modal frame most of the app's dialogs share, however the host opens it.
 *
 * The listener followed changes of `show` and never its first value, so a host that MOUNTS the modal already open (the
 * desk's agent card, `<AgentDetailModal v-if="open" :show="true">`) got a dialog Escape could not close, while the focus
 * trap beside it had already learned to start with its first value. Also checked: the listener leaves with the component,
 * a dialog opened over this one keeps its own Escape, and an Escape this modal used is marked as used.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import BaseModal from './BaseModal.vue'

let w: VueWrapper | null = null
afterEach(() => { w?.unmount(); w = null; document.body.innerHTML = '' })

function open(props: Record<string, unknown> = {}) {
  w = mount(BaseModal, { props: { show: true, title: 'Agent card', ...props }, slots: { default: '<button data-testid="inside">x</button>' }, attachTo: document.body })
  return w
}
function escape(target: EventTarget = document) {
  const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  target.dispatchEvent(e)
  return e
}
const closes = () => (w!.emitted('update:show') ?? []).filter(([v]) => v === false).length

describe('Escape on the shared modal frame', () => {
  it('closes a modal that was mounted already open', async () => {
    open(); await flushPromises()
    const e = escape()
    expect(closes()).toBe(1)
    expect(e.defaultPrevented, 'the press is marked as used').toBe(true)
  })

  it('closes a modal opened after it was mounted, and does nothing while it is closed', async () => {
    open({ show: false }); await flushPromises()
    expect(escape().defaultPrevented).toBe(false)
    expect(closes()).toBe(0)
    await w!.setProps({ show: true }); await flushPromises()
    escape()
    expect(closes()).toBe(1)
    await w!.setProps({ show: false })
    escape()
    expect(closes(), 'a closed modal leaves Escape alone').toBe(1)
  })

  it('stops listening once it is gone', async () => {
    open(); await flushPromises()
    const gone = w!
    gone.unmount(); w = null
    const e = escape()
    expect(e.defaultPrevented).toBe(false)
    expect((gone.emitted('update:show') ?? []).length).toBe(0)
  })

  it('leaves Escape to a dialog opened over it, and takes it back when that one is gone', async () => {
    open(); await flushPromises()
    const over = document.createElement('div')
    over.setAttribute('role', 'dialog'); over.setAttribute('aria-modal', 'true')
    const btn = document.createElement('button'); over.appendChild(btn); document.body.appendChild(over)
    btn.focus()
    expect(document.activeElement).toBe(btn)
    escape(btn)
    expect(closes(), 'the dialog on top owns this press').toBe(0)
    over.remove()
    ;(document.querySelector('[data-testid="inside"]') as HTMLElement).focus()
    escape()
    expect(closes()).toBe(1)
  })

  it('closes when focus sits on the page behind it (the trigger kept focus)', async () => {
    const trigger = document.createElement('button'); document.body.appendChild(trigger)
    open(); await flushPromises()
    trigger.focus()
    escape(trigger)
    expect(closes()).toBe(1)
  })
})
