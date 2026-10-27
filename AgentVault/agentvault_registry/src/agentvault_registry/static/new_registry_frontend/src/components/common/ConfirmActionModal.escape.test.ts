import { describe, expect, it, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import ConfirmActionModal from './ConfirmActionModal.vue'

const open: VueWrapper[] = []
afterEach(() => { while (open.length) open.pop()!.unmount() })
const esc = () => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))

describe('ConfirmActionModal and Escape (useEscapeClose)', () => {
  it('closes on an Escape pressed while the focus is outside it', async () => {
    const w = mount(ConfirmActionModal, { props: { show: true, title: 'Delete?', message: 'Sure?' }, attachTo: document.body })
    open.push(w)
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    esc(); await nextTick()
    expect(w.emitted('close')).toHaveLength(1)
  })
  it('keeps the Escape while its action runs (busy), like its disabled Cancel', async () => {
    const w = mount(ConfirmActionModal, { props: { show: true, title: 'Delete?', message: 'Sure?', busy: true }, attachTo: document.body })
    open.push(w)
    esc(); await nextTick()
    expect(w.emitted('close')).toBeUndefined()
  })
  it('hears nothing while it is closed', async () => {
    const w = mount(ConfirmActionModal, { props: { show: false, title: 'Delete?', message: 'Sure?' }, attachTo: document.body })
    open.push(w)
    esc(); await nextTick()
    expect(w.emitted('close')).toBeUndefined()
  })
})
