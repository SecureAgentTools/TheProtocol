/**
 * §FESUITE (V0578): Pocket's Activity reads either the frame's sampled window or ONE agent's own record. A failed
 * per-agent read was said at the scope control, and the page below it still said "All quiet in the sampled window." (and
 * so did an answer that carried the server's own error note): a read that failed drawn as nothing happening. The quiet
 * state is now said only over a read that answered without an error.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: (...a: unknown[]) => h.get(...a) } }))
vi.mock('@/composables/usePocketAgent', () => ({ usePocketAgent: () => ({ credAgents: computed(() => [{ did: 'did:theprotocol:mine', name: 'Mine' }]) }) }))
vi.mock('@/composables/useLedgerStream', () => ({
  useLedgerStream: () => ({ anyConnected: ref(false), totalEvents: ref(0), droppedForRender: ref(0), onVerbs: () => () => {} }),
}))
vi.mock('@/composables/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ ptrH: ref(0), ptrArmed: ref(false), onTouchStart() {}, onTouchMove() {}, onTouchEnd() {} }),
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ amount: (v: unknown) => String(v) }) }))

import PocketActivity from './PocketActivity.vue'

const QUIET = 'All quiet in the sampled window.'
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

async function activity() {
  const w = mount(PocketActivity, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe("Pocket's Activity says 'all quiet' only over a read that answered", () => {
  beforeEach(() => { h.get.mockReset() })

  it('a failed per-agent read is not "All quiet"', async () => {
    h.get.mockResolvedValueOnce({ data: { events: [], sampled_window: 200 } })
    const w = await activity()
    expect(w.text()).toContain(QUIET)
    h.get.mockRejectedValueOnce(badGateway())
    await w.find('[data-testid="pv-scope-sel"]').setValue('did:theprotocol:mine')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.find('[data-testid="pv-scope-err"]').exists()).toBe(true)
    expect(w.text(), 'said all quiet under a per-agent read that failed').not.toContain(QUIET)
  })

  it('an answer carrying the server\'s error note is not "All quiet"', async () => {
    h.get.mockResolvedValueOnce({ data: { events: [], sampled_window: 200, error: 'The ledger could not be read just now.' } })
    const w = await activity()
    expect(w.find('[data-testid="pv-scope-err"]').text()).toContain('could not be read')
    expect(w.text(), 'said all quiet beside the server saying its read failed').not.toContain(QUIET)
  })

  it('an answered empty window is "All quiet"', async () => {
    h.get.mockResolvedValueOnce({ data: { events: [], sampled_window: 200 } })
    const w = await activity()
    expect(w.text()).toContain(QUIET)
  })
})
