/**
 * §FESUITE 135 (2026-10-15): a profile's website and GitHub link are the person's own words, and the registry stores them
 * as typed. Bound to href unchecked, a "javascript:" website was a link that ran in the console's origin for whoever
 * opened the profile and pressed it. Only an http(s) address is a link; anything else is left out.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, ref } from 'vue'

const h = vi.hoisted(() => ({ profile: {} as Record<string, unknown> }))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({
    t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k),
    tp: (k: string, fb: string, p?: Record<string, unknown>) => String(fb ?? k).replace(/\{(\w+)\}/g, (_m, n) => String(p?.[n] ?? '')),
  }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: () => {} }) }))
vi.mock('@/services/api/chat', () => ({
  chatApi: {
    handleProfile: async () => h.profile,
    handlePulse: async () => ({ moments: [] }),
    createConversation: async () => ({}),
  },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:me' } }) }))
vi.mock('@/composables/usePocketAgent', () => ({
  usePocketAgent: () => ({ credAgents: computed(() => []), noAgentReason: computed(() => ''), ensureAgentFor: async () => true }),
}))
vi.mock('@/composables/useFrameManifest', () => ({ currentOwnCurrency: () => 'SBXA' }))
vi.mock('@/composables/useFocusTrap', () => ({ useFocusTrap: () => {} }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ amount: (v: unknown) => String(v) }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => ({ enabled: ref(false), verify: async () => true }) }))
vi.mock('@/composables/usePocketNfc', () => ({
  usePocketNfc: () => ({ supported: ref(false), scanning: ref(false), writing: ref(false), stopScan() {}, scanPayRequest: async () => null,
    writePayRequest: async () => {}, buildPayUri: () => '' }),
}))
vi.mock('@/services/api/teg', () => ({ tegApi: { smartSend: async () => ({}) } }))

import PocketProfile from './PocketProfile.vue'

let w: VueWrapper | null = null
afterEach(() => { w?.unmount(); w = null })

async function linksFor(profile: Record<string, unknown>): Promise<string[]> {
  // links show only on a public profile (a private one says it publishes nothing)
  h.profile = { display_name: 'Someone', handle: 'someone', visibility: 'public', contact: { policy: 'open' }, ...profile }
  w = mount(PocketProfile, {
    props: { show: true, handle: 'someone', token: 'dev-token' },
    global: { stubs: { Icon: true, OurStateIdentity: true, ActingContextNotice: true, PocketSend: true } },
    attachTo: document.body,
  })
  await flushPromises()
  return Array.from(document.querySelectorAll('a.pp-link')).map((a) => a.getAttribute('href') || '')
}

describe('a profile\'s links', () => {
  it('links an http(s) website and GitHub page', async () => {
    const hrefs = await linksFor({ website_url: 'https://example.org/me', github_url: 'https://github.com/someone' })
    expect(hrefs).toContain('https://example.org/me')
    expect(hrefs).toContain('https://github.com/someone')
  })

  it('never makes a javascript: or data: address a link', async () => {
    const hrefs = await linksFor({ website_url: 'javascript:alert(document.domain)', github_url: 'data:text/html,<b>x</b>' })
    expect(hrefs.filter((x) => /^\s*(javascript|data):/i.test(x))).toEqual([])
    expect(hrefs).toEqual([])
  })
})
