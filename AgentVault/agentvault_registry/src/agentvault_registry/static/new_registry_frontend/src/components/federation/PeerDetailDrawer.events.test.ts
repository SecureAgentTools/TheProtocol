import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the federation console's peer drawer (the live one; Federation.vue's inline
 * drawer is v-if="false") read a peer's events and, over a failed read, set the list to [] and said "No events for this
 * peer." (for this registry itself, "No federation events on aggregate registry:self."). It says the read failed now
 * (Try again); an answered empty window still says none.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))

import PeerDetailDrawer from './PeerDetailDrawer.vue'

const PEER = { id: 9, name: 'asia', peer_type: 'frame', status: 'ACTIVE', base_url: 'https://asia.example' } as any
const LOCAL = { id: 0, name: 'eu', peer_type: 'local', status: 'ACTIVE', base_url: 'https://eu.example' } as any
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const opts = (peer: any) => ({ props: { open: true, peer, localName: 'eu' }, global: { stubs: { Icon: true, PeerOrb: true, teleport: true, Teleport: true } } })

async function openEvents(w: ReturnType<typeof mount>) {
  ;(w.vm as any).activeTab = 'events'
  await flushPromises()
}

describe('the peer drawer says what its events read answered', () => {
  beforeEach(() => { h.get.mockReset() })

  for (const [who, peer, none] of [['a peer', PEER, 'No events for this peer.'], ['this registry', LOCAL, 'No federation events on aggregate registry:self.']] as const) {
    it(`${who}: a failed read says it failed, not "${none}"`, async () => {
      h.get.mockRejectedValue(failure())
      const w = mount(PeerDetailDrawer, opts(peer))
      await flushPromises()
      await openEvents(w)
      expect(w.text()).not.toContain(none)
      expect(w.find('[data-testid="pdd-events-unread"]').exists()).toBe(true)
      w.unmount()
    })
  }

  it('an answered empty window says none', async () => {
    h.get.mockResolvedValue({ data: { events: [] } })
    const w = mount(PeerDetailDrawer, opts(PEER))
    await flushPromises()
    await openEvents(w)
    expect(w.text()).toContain('No events for this peer.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
