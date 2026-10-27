import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FRAMES posture (2026-10-06, agentvault2-09; his words: "Frames are not buyable ... We may say yes. We may say no ...
 * this is the problematic passage ... frame can be run by anyone who is eligable (its in the federation terms ...
 * hyperlink it) free for everyone for now. later licensing should cover the cost of theprotocol. only for profit will
 * pay"). The frames tab's fine print says the Federation Operator Terms' posture in their own words and links them; the
 * retracted sentence is gone (de falls back to this English line until it is translated: the translations backlog).
 */
vi.mock('@/composables/useFrameManifest', async () => {
  const { computed } = await import('vue')
  return { useFrameManifest: () => ({ manifest: computed(() => null), settled: computed(() => true), frames: computed(() => []) }) }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useRoute: () => ({ query: { tab: 'frames' } }) }))

import OperatorPage from './OperatorPage.vue'

const opts = { global: { stubs: { Icon: true, RouterLink: true, 'router-link': true, Teleport: true, teleport: true } } }

describe("the frames tab's fine print states the federation terms' posture", () => {
  it('links the terms, says who pays and when, and keeps the contact', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const w = mount(OperatorPage, opts)
    await flushPromises()
    const fine = w.find('.op-callout--gold .op-fineprint')
    expect(fine.exists()).toBe(true)
    const text = fine.text()
    expect(text).toContain('Anyone eligible under the Federation Operator Terms can run a frame on the network')
    expect(text).toContain('free for everyone today')
    expect(text).toContain('educational, research and non-profit organisations')
    expect(text).toContain('only to cover the costs of running the network')
    const terms = fine.find('a[href="#/legal/operators"]')
    expect(terms.exists() && terms.text()).toBe('Federation Operator Terms')
    expect(fine.find('a[href="mailto:commander@theprotocol.cloud"]').text()).toBe('commander@theprotocol.cloud')
    for (const gone of ['not buyable', 'We may say no', 'referrals program']) expect(text).not.toContain(gone)
    // the tab's opening line says the same (his word 2026-10-06 on "Yours, when we say yes to your form, is the next one")
    const page = w.text()
    expect(page).toContain('Yours can be the next one: anyone eligible under the federation terms can run a frame.')
    expect(page).not.toContain('when we say yes to your form')
    w.unmount()
    vi.unstubAllGlobals()
  })
})
