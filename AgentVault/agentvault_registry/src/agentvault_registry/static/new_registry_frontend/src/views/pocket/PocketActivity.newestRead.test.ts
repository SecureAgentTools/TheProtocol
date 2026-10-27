/**
 * §LEDGERGATE (V0601): Pocket's Activity draws only its newest read. The first read (the frame's sampled window) was still
 * on its way when a person picked one agent's own record; the per-agent read answered first and the window answered
 * after it, so the whole fleet's rows stood under "this agent's own ledger record" (journal 51's photo drill on Sandbox
 * Alpha: 78 rows of other agents for an agent whose record holds 6). RED on fe/batch-v0600 (the late window wins).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

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

const at = '2026-10-12T07:13:47Z'
const fleet = Array.from({ length: 12 }, (_, i) => ({ id: `w${i}`, event_type: 'TokensTransferred', timestamp: at,
  aggregate_id: `did:theprotocol:other-${i}`, data: { amount: '9', message: `someone else ${i}` } }))
const own = [
  { id: 'a1', event_type: 'TokensTransferred', timestamp: at, aggregate_id: 'did:theprotocol:mine', data: { amount: '1.5', message: 'my own send' } },
  { id: 'a2', event_type: 'AgentCreated', timestamp: '2026-10-12T07:00:24Z', aggregate_id: 'did:theprotocol:mine', data: {} },
]

describe("Pocket's Activity draws only its newest read", () => {
  beforeEach(() => { h.get.mockReset() })

  it("a window that answers after the agent's own record does not replace it", async () => {
    let answerWindow: (v: unknown) => void = () => {}
    h.get.mockImplementationOnce(() => new Promise((r) => { answerWindow = r }))   // the sampled window, still on its way
    h.get.mockResolvedValueOnce({ data: { events: own, total: 2, scope: 'agent', agent_did: 'did:theprotocol:mine', complete: true } })
    const w = mount(PocketActivity, { global: { stubs: { Icon: true } } })
    await flushPromises()
    await w.find('[data-testid="pv-scope-sel"]').setValue('did:theprotocol:mine')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.text()).toContain('my own send')
    answerWindow({ data: { events: fleet, sampled_window: 200 } })   // the first read answers last
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.text(), "another scope's rows under this agent's caption").not.toContain('someone else')
    expect(w.text()).toContain('my own send')
    expect(w.find('[data-testid="pv-scope"]').text()).toContain("this agent's own ledger record")
    expect(w.find('[data-testid="pv-scope"]').text()).toContain('2')
  })

  it('the newest read still draws when the window was the only one asked', async () => {
    h.get.mockResolvedValueOnce({ data: { events: fleet, sampled_window: 200 } })
    const w = mount(PocketActivity, { global: { stubs: { Icon: true } } })
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.text()).toContain('someone else 0')
  })
})
