import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the Workers panel's ten observability cards read their aggregates with
 * silent catches. A failed read left a card at "LOADING" for good, on a green card, and the pull-sync
 * card said "healthy" in green over a status it never read. A card says UNREAD now (the pull-sync one "unread") and is
 * green only over a status it read. Answered aggregates keep their verdicts (the control).
 */
const h = vi.hoisted(() => ({
  get: vi.fn(),
  agg: {
    getSweeperStatus: vi.fn(), getCanaryJudgeStatus: vi.fn(), getRebalancerStatus: vi.fn(), getSagaStatus: vi.fn(),
    getSupplyAuditorStatus: vi.fn(), getCollusionStatus: vi.fn(), getFederationSyncStatus: vi.fn(),
    getAgentHealthStatus: vi.fn(), getCanaryIronhandStatus: vi.fn(), getPullsyncStatus: vi.fn(),
  },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get } }))
vi.mock('@/services/api/crossTegSweeper', () => ({ getSweeperStatus: h.agg.getSweeperStatus }))
vi.mock('@/services/api/canaryJudge', () => ({ getCanaryJudgeStatus: h.agg.getCanaryJudgeStatus }))
vi.mock('@/services/api/canaryRebalancer', () => ({ getRebalancerStatus: h.agg.getRebalancerStatus }))
vi.mock('@/services/api/sagaTimeout', () => ({ getSagaStatus: h.agg.getSagaStatus }))
vi.mock('@/services/api/supplyAuditor', () => ({ getSupplyAuditorStatus: h.agg.getSupplyAuditorStatus }))
vi.mock('@/services/api/collusionWorker', () => ({ getCollusionStatus: h.agg.getCollusionStatus }))
vi.mock('@/services/api/federationSync', () => ({ getFederationSyncStatus: h.agg.getFederationSyncStatus }))
vi.mock('@/services/api/agentHealth', () => ({ getAgentHealthStatus: h.agg.getAgentHealthStatus }))
vi.mock('@/services/api/canaryIronhand', () => ({ getCanaryIronhandStatus: h.agg.getCanaryIronhandStatus }))
vi.mock('@/services/api/agentCardPullsync', () => ({ getPullsyncStatus: h.agg.getPullsyncStatus }))

import WorkerTasksPanel from './WorkerTasksPanel.vue'

const stubs = {
  Icon: true, CrossTegSweeperModal: true, CanaryJudgeModal: true, CanaryRebalancerModal: true, SagaTimeoutCheckerModal: true,
  SupplyAuditorModal: true, CollusionWorkerModal: true, FederationSyncModal: true, AgentHealthModal: true,
  CanaryIronhandModal: true, AgentCardPullSyncModal: true,
}
const WORKERS = {
  summary: { total: 1, with_leader: 1, no_leader: 0 },
  workers: [{ name: 'supply_auditor', description: 'd', schedule_label: '60s', category: 'audit', has_leader: true,
    leader_worker: 'w1', lease_ttl_seconds: 30, last_run_at: null, last_status: null }],
  snapshot_at: '2026-10-05T12:00:00Z',
}
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

function aggregateCards(w: ReturnType<typeof mount>) {
  return w.findAll('.wt-card--cts')
}

describe('the Workers cards say an unread aggregate is unread', () => {
  beforeEach(() => {
    h.get.mockReset().mockResolvedValue({ data: WORKERS })
    for (const f of Object.values(h.agg)) f.mockReset().mockRejectedValue(failure())
  })

  it('every aggregate read failed: UNREAD on each card, no green card, no "healthy"', async () => {
    const w = mount(WorkerTasksPanel, { global: { stubs } })
    await flushPromises()
    const cards = aggregateCards(w)
    expect(cards.length, 'the ten aggregate cards').toBe(10)
    const pills = cards.map((c) => c.find('.wt-pill').text())
    expect(pills.filter((p) => /^(LOADING|HEALTHY|healthy|loading)$/.test(p)), 'pills over failed reads').toEqual([])
    expect(pills.filter((p) => /^unread$/i.test(p)).length).toBe(10)
    expect(cards.filter((c) => c.classes('wt-card--ok')).length, 'green cards over failed reads').toBe(0)
    w.unmount()
  })

  it('before any answer the cards say LOADING (and the pull-sync card loading), never healthy', async () => {
    for (const f of Object.values(h.agg)) f.mockReset().mockReturnValue(new Promise(() => {}))
    const w = mount(WorkerTasksPanel, { global: { stubs } })
    await flushPromises()
    const pills = aggregateCards(w).map((c) => c.find('.wt-pill').text())
    expect(pills.filter((p) => /^loading$/i.test(p)).length).toBe(10)
    w.unmount()
  })

  it('control: an answered healthy aggregate still reads HEALTHY on a green card', async () => {
    h.agg.getSweeperStatus.mockResolvedValue({
      summary: { cycles_24h: 10, aborted_24h: 0, resumed_24h: 0, errors_24h: 0, pending_total: 0, teg_count: 2 },
      per_op: [], errors_by_reason: {}, snapshot_iso: '2026-10-05T12:00:00Z',
    })
    const w = mount(WorkerTasksPanel, { global: { stubs } })
    await flushPromises()
    const sweeper = aggregateCards(w).find((c) => c.text().includes('cross_teg_sweeper'))!
    expect(sweeper.find('.wt-pill').text()).toBe('HEALTHY')
    expect(sweeper.classes('wt-card--ok')).toBe(true)
    w.unmount()
  })
})
