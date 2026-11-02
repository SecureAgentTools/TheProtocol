import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h as hh, inject, reactive } from 'vue'

/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc), the maintainer in the sessions' room (seq 686): the chat list "is not
 * collapsable". With two panes and a thread open the list folds to a narrow rail that keeps the unread count and the way
 * back; the choice is kept per person on this device (a reload keeps it); while no thread is open the list shows (the
 * "pick a conversation" pane only ever sits beside it); a phone keeps one pane at a time. The list's header, the rail and
 * the thread's arrow work one state, handed down by the shell. BASE (V0652): no fold.
 */
const s = vi.hoisted(() => ({ route: null as any, wideMatches: true }))
vi.mock('vue-router', () => ({ useRoute: () => s.route }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 } }) }))

import OurChatShell from './OurChatShell.vue'
import { OURCHAT_LIST_FOLD } from '@/services/chat/listFold'

/* the list, as far as the shell is concerned: it reports its unread count and offers the fold, both through the shell */
const ListStub = defineComponent({
  setup() {
    const ctl = inject(OURCHAT_LIST_FOLD)!
    ctl.setUnread(3)
    return () => hh('div', { 'data-testid': 'stub-list' }, ctl.canFold.value
      ? [hh('button', { 'data-testid': 'stub-fold', onClick: () => ctl.toggle() })] : [])
  },
})
const stubs = { PocketOurState: ListStub, Icon: true, 'router-view': true, RouterView: true }
const shown = (el: any) => !!el.exists() && (el.element as HTMLElement).style.display !== 'none'

describe('the conversation list folds beside an open thread', () => {
  const realMatchMedia = window.matchMedia
  beforeEach(() => {
    s.route = reactive({ params: { id: 'room1' }, query: {} })
    s.wideMatches = true
    ;(window as any).matchMedia = (q: string) => ({ matches: s.wideMatches, media: q,
      addEventListener: () => {}, removeEventListener: () => {} })
    try { localStorage.clear() } catch { /* no storage */ }
  })
  afterEach(() => { (window as any).matchMedia = realMatchMedia; document.body.innerHTML = '' })

  it('folds to the rail with the unread count, opens again from the rail, and a reload keeps the choice', async () => {
    const w = mount(OurChatShell, { global: { stubs } })
    await flushPromises()
    expect(shown(w.find('[data-testid="ocs-list"]'))).toBe(true)
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    await w.find('[data-testid="stub-fold"]').trigger('click')
    expect(w.find('[data-testid="ocs-root"]').attributes('data-list')).toBe('folded')
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(true)
    expect(w.find('[data-testid="ocs-rail-unread"]').text()).toContain('3')
    expect(shown(w.find('[data-testid="ocs-list"]'))).toBe(false)   // kept mounted behind the rail: its count goes on
    w.unmount()

    const again = mount(OurChatShell, { global: { stubs } })   // a reload: a fresh read of this person's choice
    await flushPromises()
    expect(again.find('[data-testid="ocs-rail"]').exists()).toBe(true)
    await again.find('[data-testid="ocs-rail-open"]').trigger('click')
    expect(again.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    expect(shown(again.find('[data-testid="ocs-list"]'))).toBe(true)
    again.unmount()
    const third = mount(OurChatShell, { global: { stubs } })
    await flushPromises()
    expect(third.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    third.unmount()
  })

  it('while no thread is open the list shows, folded or not, beside the pick pane', async () => {
    localStorage.setItem('ourchat.list.v1.6', 'folded')
    s.route.params = {}
    const w = mount(OurChatShell, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    expect(shown(w.find('[data-testid="ocs-list"]'))).toBe(true)
    expect(w.find('[data-testid="ocs-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="stub-fold"]').exists()).toBe(false)   // nothing to fold beside
    s.route.params = { id: 'room1' }
    await flushPromises()
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(true)     // a thread opens: the kept choice applies
    w.unmount()
  })

  it('a phone keeps one pane at a time: no rail, no fold, whatever was kept', async () => {
    localStorage.setItem('ourchat.list.v1.6', 'folded')
    s.wideMatches = false
    const w = mount(OurChatShell, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    expect(w.find('[data-testid="ocs-list"]').exists()).toBe(false)    // the thread alone, as before
    expect(w.find('[data-testid="ocs-thread"]').exists()).toBe(true)
    w.unmount()
  })

  it("one person's choice is theirs: another account on this device starts with the list open", async () => {
    localStorage.setItem('ourchat.list.v1.7', 'folded')
    const w = mount(OurChatShell, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="ocs-rail"]').exists()).toBe(false)
    w.unmount()
  })
})
