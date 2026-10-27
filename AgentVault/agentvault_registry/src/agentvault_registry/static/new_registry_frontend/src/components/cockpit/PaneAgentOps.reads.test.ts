/**
 * §FESUITE (V0577): the desk's Agents pane reads two things per pinned row every cycle, the agent's metrics and its
 * deployments, and swallowed each failure into null. A failed metrics read was then neverObserved(null): the row said
 * "no traffic recorded" ("No request has ever been recorded for this agent"); a failed deployments read said "no
 * deployment record", and the selected agent's detail "No deployments have been recorded through this registry for this
 * agent." Each read's failure is now kept apart from its answer: the row says the traffic or the deployments are unread,
 * the detail says the read failed and offers it again. Answers of none still say none.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ metrics: vi.fn(), deployments: vi.fn() }))
vi.mock('@/services/api/agentOps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api/agentOps')>()),
  agentOpsApi: { metrics: h.metrics, deployments: h.deployments },
}))
const DID = 'did:theprotocol:pinned-1'
vi.mock('@/services/api/agents', () => ({
  agentApi: { getMyAgents: vi.fn(async () => [{ did: DID, name: 'Pinned One', status: 'active' }]) },
}))
vi.mock('@/composables/useFillCount', () => ({ useFillCount: () => ({ count: ref(8) }) }))
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))
vi.mock('@/services/cockpit/agentDoor', () => ({ openDeployment: vi.fn(), openAgent: vi.fn(), isOpenable: () => false }))

import PaneAgentOps from './PaneAgentOps.vue'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const NO_TRAFFIC = { total_requests: 0, success_rate: 0, last_active: null }

async function board() {
  localStorage.setItem('ckd_agent_pins', JSON.stringify([DID]))
  const w = mount(PaneAgentOps, { global: { stubs: { AgentLink: true } } })
  await flushPromises()
  return w
}

describe("the desk's Agents pane when a row's reads fail", () => {
  beforeEach(() => {
    localStorage.clear()
    h.metrics.mockReset()
    h.deployments.mockReset()
  })

  it('a failed metrics read is "traffic unread", never "no traffic recorded"', async () => {
    h.metrics.mockRejectedValue(noAnswer())
    h.deployments.mockResolvedValue([])
    const w = await board()
    expect(w.find('[data-testid="rat-no-traffic"]').exists(), 'drew "no traffic recorded" over a failed read').toBe(false)
    expect(w.find('[data-testid="rat-traffic-unread"]').exists()).toBe(true)
  })

  it('a failed deployments read is "deployments unread" on the row and a failed read in the detail', async () => {
    h.metrics.mockResolvedValue(NO_TRAFFIC)
    h.deployments.mockRejectedValue(noAnswer())
    const w = await board()
    expect(w.find('[data-testid="rat-deploy-none"]').exists(), 'drew "no deployment record" over a failed read').toBe(false)
    expect(w.find('[data-testid="rat-deploy-unread"]').exists()).toBe(true)

    await w.find('[data-testid="rat-row"]').trigger('click')
    expect(w.find('[data-testid="rat-detail-none"]').exists(), 'drew "No deployments have been recorded" over a failed read').toBe(false)
    const notice = w.find('[data-testid="rat-detail-failed"]')
    expect(notice.exists()).toBe(true)

    h.deployments.mockResolvedValue([])
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="rat-detail-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="rat-detail-none"]').exists()).toBe(true)
  })

  it('answers of none still say none', async () => {
    h.metrics.mockResolvedValue(NO_TRAFFIC)
    h.deployments.mockResolvedValue([])
    const w = await board()
    expect(w.find('[data-testid="rat-no-traffic"]').exists()).toBe(true)
    expect(w.find('[data-testid="rat-deploy-none"]').exists()).toBe(true)
  })
})
