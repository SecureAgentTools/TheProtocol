/**
 * §FESUITE (V0578): /architecture draws the peer frame with a dot, lit when a peer is active and dim when none is. With
 * /api/v1/federation/registries and /api/v1/federation/network-stats both failing it drew the dim dot: a public page
 * saying the peer frame is not active because a read failed. The loading sweep fixed this page's figures; this is its
 * last claim over a failed read. A peer this page could not read is now a ring titled "Not read".
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

vi.mock('@/composables/useRegistryConfig', () => ({
  useRegistryConfig: () => {
    const config = ref<Record<string, unknown>>({ registry_name: 'eu', governance_weight_mode: 'member' })
    const loaded = ref(true); const readOk = ref(true)
    return { config, loaded, readOk, readFailed: computed(() => false), reload: () => {}, localCurrency: ref(''), trustDomain: ref('') }
  },
}))

import NetworkArchitecture from './NetworkArchitecture.vue'

const stubs = { RouterLink: { template: '<a><slot /></a>' }, 'router-link': { template: '<a><slot /></a>' } }
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
const down = { ok: false, status: 503, json: async () => ({}) }
function reads(byPath: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = String(url).replace(window.location.origin, '')
    return path in byPath ? byPath[path] : down
  }))
}
async function page() {
  const w = mount(NetworkArchitecture, { global: { stubs } })
  for (let i = 0; i < 6; i++) await flushPromises()
  return w
}
const dot = (w: ReturnType<typeof mount>) => w.find('.arch-topo-node--b .arch-topo-dot')

afterEach(() => { vi.unstubAllGlobals() })

describe('/architecture draws the peer frame from what it read', () => {
  it('with the peers and network reads failed, the peer is not drawn as inactive', async () => {
    reads({})
    const w = await page()
    expect(dot(w).classes(), 'drew the peer dim (not active) over failed reads').not.toContain('arch-topo-dot--dim')
    expect(dot(w).classes()).not.toContain('arch-topo-dot--cyan')
    expect(dot(w).classes()).toContain('arch-topo-dot--unread')
    expect(dot(w).attributes('title')).toBe('Not read')
  })

  it('an active peer lights the dot; peers that answered with none active dim it', async () => {
    reads({ '/api/v1/federation/registries': ok([{ registry_name: 'asia', federation_status: 'ACTIVE' }]) })
    let w = await page()
    expect(dot(w).classes()).toContain('arch-topo-dot--cyan')
    w.unmount()
    reads({ '/api/v1/federation/registries': ok([]), '/api/v1/federation/network-stats': ok({ activeRegistries: 1 }) })
    w = await page()
    expect(dot(w).classes()).toContain('arch-topo-dot--dim')
    expect(dot(w).attributes('title')).toBeUndefined()
  })

  it('a failed peers read with the network read answering two registries still lights it', async () => {
    reads({ '/api/v1/federation/network-stats': ok({ activeRegistries: 2 }) })
    const w = await page()
    expect(dot(w).classes()).toContain('arch-topo-dot--cyan')
  })
})
