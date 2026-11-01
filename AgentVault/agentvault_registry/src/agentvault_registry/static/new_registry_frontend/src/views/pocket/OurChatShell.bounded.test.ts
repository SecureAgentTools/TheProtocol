import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'

/**
 * V0651 (y) (measured at 393 px on V0650's bundle: the thread grew to its whole history, the page scrolled, and the
 * approvals panel pinned above the history sat about 2,800 px above the latest message): on a phone an OPEN thread is
 * bounded like the desktop's pane, by the viewport less the shell's top and the bottom space the page's scroller keeps
 * for its bar (read from its padding, never assumed), so the history scrolls inside the thread and the panel stays in
 * view. The list keeps the document flow, and the desktop's two panes keep their own height. BASE (V0650): no bound.
 */
const h = vi.hoisted(() => ({ route: null as any, wideMatches: false }))
vi.mock('vue-router', () => ({ useRoute: () => h.route }))

import OurChatShell from './OurChatShell.vue'

const stubs = { PocketOurState: true, Icon: true, 'router-view': true, RouterView: true }

function mountIn(paddingBottom = '83px') {
  const host = document.createElement('main')
  host.setAttribute('style', `overflow-y: auto; padding-bottom: ${paddingBottom};`)
  document.body.appendChild(host)
  return mount(OurChatShell, { attachTo: host, global: { stubs } })
}

describe('a thread on a phone is bounded, so the pinned panel stays in view', () => {
  const realMatchMedia = window.matchMedia
  beforeEach(() => {
    h.route = reactive({ params: { id: 'room1' }, query: {} })
    h.wideMatches = false
    ;(window as any).matchMedia = (q: string) => ({ matches: h.wideMatches, media: q,
      addEventListener: () => {}, removeEventListener: () => {} })
  })
  afterEach(() => { (window as any).matchMedia = realMatchMedia; document.body.innerHTML = '' })

  it('bounds an open thread by the measured bottom space of the page', async () => {
    const w = mountIn('83px')
    await flushPromises()
    const root = w.find('[data-testid="ocs-root"]')
    expect(root.classes()).toContain('ocs-bounded')
    expect(root.attributes('style') || '').toContain('--ocs-offset: 83px')
  })

  it('leaves the list in the document flow', async () => {
    h.route.params = {}
    const w = mountIn()
    await flushPromises()
    const root = w.find('[data-testid="ocs-root"]')
    expect(root.classes()).not.toContain('ocs-bounded')
    expect(root.attributes('style') || '').toBe('')
  })

  it('bounds the thread when one opens after the list, and keeps the desktop panes their own height', async () => {
    h.route.params = {}
    const w = mountIn('40px')
    await flushPromises()
    h.route.params = { id: 'room2' }
    await flushPromises()
    expect(w.find('[data-testid="ocs-root"]').classes()).toContain('ocs-bounded')
    h.wideMatches = true
    const wide = mountIn('0px')
    await flushPromises()
    const root = wide.find('[data-testid="ocs-root"]')
    expect(root.classes()).toContain('ocs-two')
    expect(root.classes()).not.toContain('ocs-bounded')
    expect(root.attributes('style') || '').toContain('height: calc(100vh - 0px)')
  })

  it('V0652 (ad): the wide panes leave the bottom space Pocket keeps for its tab bar (the composer stays above it)', async () => {
    // BASE (V0651): calc(100vh - 0px): at 1920 the composer's send sat under Pocket's tab bar and the page scrolled 84 px
    h.wideMatches = true
    const wide = mountIn('83px')
    await flushPromises()
    expect(wide.find('[data-testid="ocs-root"]').attributes('style') || '').toContain('height: calc(100vh - 83px)')
  })
})
