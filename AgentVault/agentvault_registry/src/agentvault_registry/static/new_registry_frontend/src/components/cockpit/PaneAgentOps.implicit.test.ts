/**
 * §COCKPITDESK (2026-10-14) — Your agents with nothing pinned. Pins live in the browser, so a new device or a new account
 * opened the pane on "No agents on the board yet" while Agents alive listed the agent beside it (lifecycle 98's photograph).
 * With no choice stored, the board shows the agents the account owns and stores nothing; the first add or removal copies
 * what is shown into the person's own list and changes that; a stored empty list is a choice and stays empty.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const A = 'did:theprotocol:owned-a'
const B = 'did:theprotocol:owned-b'
const h = vi.hoisted(() => ({ mine: [] as any[] }))
vi.mock('@/services/api/agentOps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api/agentOps')>()),
  agentOpsApi: { metrics: vi.fn(async () => ({ total_requests: 0, success_rate: 0, last_active: null })), deployments: vi.fn(async () => []) },
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: vi.fn(async () => h.mine) } }))
vi.mock('@/composables/useFillCount', () => ({ useFillCount: () => ({ count: ref(8) }) }))
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))
vi.mock('@/services/cockpit/agentDoor', () => ({ openDeployment: vi.fn(), openAgent: vi.fn(), isOpenable: () => false }))

import PaneAgentOps from './PaneAgentOps.vue'

async function pane() {
  const w = mount(PaneAgentOps, { global: { stubs: { AgentLink: { props: ['did', 'label'], template: '<span class="alink" :data-did="did">{{ label }}</span>' } } } })
  await flushPromises()
  return w
}
const rows = (w: any) => w.findAll('[data-testid="rat-row"]').map((r: any) => r.find('.alink').attributes('data-did'))
const stored = () => localStorage.getItem('ckd_agent_pins')

describe('Your agents with nothing pinned', () => {
  beforeEach(() => {
    localStorage.clear()
    h.mine = [{ did: A, name: 'Owned A', status: 'active' }, { did: B, name: 'Owned B', status: 'active' }]
  })

  it('shows the agents the account owns, says so, and stores nothing', async () => {
    const w = await pane()
    expect(rows(w)).toEqual([A, B])
    expect(w.find('[data-testid="rat-implicit"]').exists()).toBe(true)
    expect(w.find('[data-testid="rat-empty"]').exists()).toBe(false)
    expect(w.find('[data-testid="rat-root"]').attributes('data-implicit')).toBe('1')
    expect(stored(), 'nothing written before a gesture').toBeNull()
  })

  it('makes the board the person\'s own on the first removal, starting from what was shown', async () => {
    const w = await pane()
    await w.findAll('[data-testid="rat-unpin"]')[0].trigger('click'); await flushPromises()
    expect(rows(w)).toEqual([B])
    expect(JSON.parse(stored() || 'null')).toEqual([B])
    expect(w.find('[data-testid="rat-implicit"]').exists()).toBe(false)
  })

  it('keeps an emptied board empty: a stored empty list is a choice', async () => {
    const w = await pane()
    await w.findAll('[data-testid="rat-unpin"]')[0].trigger('click'); await flushPromises()
    await w.findAll('[data-testid="rat-unpin"]')[0].trigger('click'); await flushPromises()
    expect(rows(w)).toEqual([])
    expect(stored()).toBe('[]')
    expect(w.find('[data-testid="rat-empty"]').exists()).toBe(true)
    w.unmount()
    const again = await pane()
    expect(rows(again), 'a reload keeps the empty choice').toEqual([])
    expect(again.find('[data-testid="rat-implicit"]').exists()).toBe(false)
  })

  it('leaves a stored list alone', async () => {
    localStorage.setItem('ckd_agent_pins', JSON.stringify([B]))
    const w = await pane()
    expect(rows(w)).toEqual([B])
    expect(w.find('[data-testid="rat-implicit"]').exists()).toBe(false)
  })

  it('says no agents when the account owns none', async () => {
    h.mine = []
    const w = await pane()
    expect(rows(w)).toEqual([])
    expect(w.find('[data-testid="rat-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="rat-implicit"]').exists()).toBe(false)
  })
})
