import { describe, it, expect, afterEach } from 'vitest'
import { defineComponent, h, ref, nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useEscapeClose, escapeStackDepth } from './useEscapeClose'
import BaseModal from '@/components/BaseModal.vue'

const mounted: VueWrapper[] = []
afterEach(() => { while (mounted.length) mounted.pop()!.unmount() })

function dialog(open: ReturnType<typeof ref<boolean>>, closes: string[], name: string, when?: () => boolean) {
  const C = defineComponent({ setup() { useEscapeClose(open as any, () => { closes.push(name); open.value = false }, when); return () => h('div') } })
  const w = mount(C, { attachTo: document.body }); mounted.push(w); return w
}
const esc = () => { const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }); document.body.dispatchEvent(e); return e }

describe('useEscapeClose', () => {
  it('closes a dialog whose focus stayed on the button outside it', async () => {
    const open = ref(true); const closes: string[] = []
    dialog(open, closes, 'form')
    esc(); await nextTick()
    expect(closes).toEqual(['form'])
    expect(escapeStackDepth()).toBe(0)
  })
  it('closes only the topmost: a confirm over a form', async () => {
    const form = ref(true); const confirm = ref(false); const closes: string[] = []
    dialog(form, closes, 'form'); dialog(confirm, closes, 'confirm')
    confirm.value = true; await nextTick()
    esc(); await nextTick()
    expect(closes).toEqual(['confirm'])
    esc(); await nextTick()
    expect(closes).toEqual(['confirm', 'form'])
  })
  it('a dialog that refuses (in flight) keeps the Escape and the one under it stays', async () => {
    const form = ref(true); const busy = ref(true); const top = ref(false); const closes: string[] = []
    dialog(form, closes, 'form'); dialog(top, closes, 'busy', () => !busy.value)
    top.value = true; await nextTick()
    const e = esc(); await nextTick()
    expect(closes).toEqual([])
    expect(e.defaultPrevented).toBe(true)
  })
  it('leaves an Escape another handler already used', async () => {
    const open = ref(true); const closes: string[] = []
    dialog(open, closes, 'form')
    const stop = (e: KeyboardEvent) => e.preventDefault()
    document.body.addEventListener('keydown', stop)
    esc(); await nextTick()
    document.body.removeEventListener('keydown', stop)
    expect(closes).toEqual([])
  })
  it('stops listening when closed or unmounted', async () => {
    const open = ref(true); const closes: string[] = []
    const w = dialog(open, closes, 'form')
    expect(escapeStackDepth()).toBe(1)
    open.value = false; await nextTick()
    expect(escapeStackDepth()).toBe(0)
    open.value = true; await nextTick()
    w.unmount(); mounted.pop()
    expect(escapeStackDepth()).toBe(0)
  })
})

describe('useEscapeClose across the app\'s dialogs', () => {
  it('a BaseModal opened over a stack dialog takes the Escape; the dialog under it stays', async () => {
    const form = ref(true); const closes: string[] = []
    dialog(form, closes, 'form')
    const m = mount(BaseModal, { props: { show: true, title: 'Over' }, attachTo: document.body }); mounted.push(m)
    await nextTick()
    esc(); await nextTick()
    expect((m.emitted('update:show') ?? []).filter(([v]) => v === false)).toHaveLength(1)
    expect(closes).toEqual([])
  })
  it('a dialog the stack does not know, holding the focus, keeps its press when the top names its element', async () => {
    const top = document.createElement('div'); top.setAttribute('aria-modal', 'true'); document.body.appendChild(top)
    const open = ref(true); const closes: string[] = []
    const C = defineComponent({ setup() { useEscapeClose(open as any, () => closes.push('top'), undefined, () => top); return () => h('div') } })
    const w = mount(C, { attachTo: document.body }); mounted.push(w)
    const other = document.createElement('div'); other.setAttribute('aria-modal', 'true')
    const btn = document.createElement('button'); other.appendChild(btn); document.body.appendChild(other)
    btn.focus()
    const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }); btn.dispatchEvent(e)
    expect(closes).toEqual([])
    expect(e.defaultPrevented).toBe(false)
    other.remove(); top.remove()
  })
})
