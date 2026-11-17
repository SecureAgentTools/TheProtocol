/**
 * V0662 console polish, item 13 (order gwo_0aa7b875cbf65b6347f5f775): the agents pane sends fewer requests at once.
 *
 * CrowdSec banned his phone on 2026-11-08 at 03:58Z for a crawl (http-crawl-non_statics, 53 events); the requests it
 * kept were all GET /api/v1/agent-metrics/<did>, and the one console surface that reads that for many agents is this
 * pane (metrics and deployments for each agent on its page, every 30 s). Its refresh ran again on every page-size
 * change, and the page size follows the tile's height, which settles in several steps after mount: each step started
 * a whole new pass over the page while the last one was still running, so the passes overlapped. Now a pass is never
 * started while one runs: a change during a pass asks for ONE more pass over the page as it then is.
 * Red on f569f6a6e: the passes overlap (more than one metrics read in flight) and the settle costs four passes.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ mine: [] as any[], inFlight: 0, maxInFlight: 0, metricsCalls: 0, fit: null as any }))
const slow = async <T>(v: T): Promise<T> => {
  h.inFlight++; h.maxInFlight = Math.max(h.maxInFlight, h.inFlight)
  await new Promise((r) => setTimeout(r, 2))
  h.inFlight--
  return v
}
vi.mock('@/services/api/agentOps', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api/agentOps')>()),
  agentOpsApi: {
    metrics: vi.fn(async () => { h.metricsCalls++; return slow({ total_requests: 0, success_rate: 0, last_active: null }) }),
    deployments: vi.fn(async () => []),
  },
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: vi.fn(async () => h.mine) } }))
vi.mock('@/composables/useFillCount', async () => {
  const { ref: r } = await import('vue')
  h.fit = r(8)
  return { useFillCount: () => ({ count: h.fit }) }
})
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))
vi.mock('@/services/cockpit/agentDoor', () => ({ openDeployment: vi.fn(), openAgent: vi.fn(), isOpenable: () => false }))

import PaneAgentOps from './PaneAgentOps.vue'

const settle = async () => { for (let i = 0; i < 200; i++) { await new Promise((r) => setTimeout(r, 2)); await flushPromises() } }

describe('the agents pane while its tile settles', () => {
  beforeEach(() => {
    localStorage.clear()
    h.mine = Array.from({ length: 30 }, (_, i) => ({ did: `did:theprotocol:owned-${i}`, name: `Owned ${i}`, status: 'active' }))
    h.inFlight = 0; h.maxInFlight = 0; h.metricsCalls = 0
    if (h.fit) h.fit.value = 8
  })

  it('one pass at a time, and a settle in four steps costs at most one more pass', async () => {
    const w = mount(PaneAgentOps, { global: { stubs: { AgentLink: true } } })
    try {
      await new Promise((r) => setTimeout(r, 1)); await flushPromises()
      for (const n of [12, 16, 24]) { h.fit.value = n; await flushPromises() }   // the tile settles while the first pass runs
      await settle()
      expect(h.maxInFlight, 'never two metrics reads at once').toBe(1)
      // the first pass (8 rows) and one more over the settled page (24 rows); before: 8 + 12 + 16 + 24, overlapping
      expect(h.metricsCalls).toBeLessThanOrEqual(8 + 24)
      expect(w.findAll('[data-testid="rat-row"]').length).toBe(24)
    } finally { w.unmount() }
  })

  it('a quiet tile still refreshes its page (control)', async () => {
    const w = mount(PaneAgentOps, { global: { stubs: { AgentLink: true } } })
    try {
      await settle()
      expect(h.metricsCalls).toBe(8)
    } finally { w.unmount() }
  })
})
