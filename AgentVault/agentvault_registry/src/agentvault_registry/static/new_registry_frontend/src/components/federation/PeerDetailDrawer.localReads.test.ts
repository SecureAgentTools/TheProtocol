import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the federation console's drawer for THIS registry. Its Lifecycle stack
 * showed a spinner until the lifecycle read brought a value, so a failed read spun for good; its Uptime, Genesis and
 * Counts vanished over a failed stats read. Each says its read failed now, with Try again; answered reads show their
 * stack and counts (the control).
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))

import PeerDetailDrawer from './PeerDetailDrawer.vue'

const LOCAL = { id: 0, name: 'eu', peer_type: 'local', status: 'ACTIVE', base_url: 'https://eu.example' } as any
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const opts = { props: { open: true, peer: LOCAL, localName: 'eu' }, global: { stubs: { Icon: true, PeerOrb: true, teleport: true, Teleport: true } } }
const STATS = { uptime_seconds: 3600, is_genesis: true, agent_count: 12, agent_card_count: 11, developer_count: 4, peer_count_active: 2, peer_count_total: 3 }
const LIFECYCLE = { application: { status: 'self_hosted' }, license: { status: 'self_hosted' }, provisioning: {}, federation: {} }
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()

function routes(fail: boolean) {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/admin/registry-stats') { if (fail) throw failure(); return { data: STATS } }
    if (url === '/admin/operator-lifecycle') { if (fail) throw failure(); return { data: LIFECYCLE } }
    return { data: { events: [] } }
  })
}
async function tab(w: ReturnType<typeof mount>, t: string) {
  ;(w.vm as any).activeTab = t
  await flushPromises()
}

describe("the drawer for this registry says what its stats and lifecycle reads answered", () => {
  beforeEach(() => { h.get.mockReset() })

  it('a failed lifecycle read says it failed, never a spinner for good; Try again shows the stack', async () => {
    routes(true)
    const w = mount(PeerDetailDrawer, opts)
    await flushPromises()
    await tab(w, 'lifecycle')
    expect(has(w, 'pdd-lifecycle-unread'), 'the stack says its read failed').toBe(true)
    expect(w.find('.pdd-lc-stack .pdd-spinner').exists(), 'no spinner over a failed read').toBe(false)
    routes(false)
    await w.find('[data-testid="pdd-lifecycle-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(has(w, 'pdd-lifecycle-unread')).toBe(false)
    expect(w.text()).toContain('APPLICATION')
    w.unmount()
  })

  it('a failed stats read: the Counts say their read failed', async () => {
    routes(true)
    const w = mount(PeerDetailDrawer, opts)
    await flushPromises()
    await tab(w, 'events')
    await tab(w, 'overview')
    expect(has(w, 'pdd-stats-unread')).toBe(true)
    w.unmount()
  })

  it('control: answered reads show the counts and the stack, with no notice', async () => {
    routes(false)
    const w = mount(PeerDetailDrawer, opts)
    await flushPromises()
    await tab(w, 'events')
    await tab(w, 'overview')
    expect(w.text()).toContain('Counts')
    expect(w.text()).toContain('12')
    await tab(w, 'lifecycle')
    expect(w.text()).toContain('APPLICATION')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
