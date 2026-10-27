import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the ten worker modals of the admin Workers panel drew their verdicts over a
 * status read that failed. The supply auditor said "invariant holds" under a dash; the saga checker said "No pending
 * settlements past deadline — the happy path."; the ironhand canary "No failures in the last 24h. Fleet healthy."; the
 * health checker "No agents currently in non-healthy state." (and, its transitions read swallowed, "No state transitions
 * on record — fleet healthy + stable."); the others "all healthy", "all clean", "0 TEGs · pending 0" and the like. Each
 * modal is mounted here with every read answered 502, every tab is opened, no claim may show, and every tab that draws
 * from the status says it could not be read. An answered status keeps its verdicts (the controls at the end).
 */
const api = vi.hoisted(() => ({
  getPullsyncStatus: vi.fn(),
  getAgentHealthStatus: vi.fn(), getAgentHealthTransitions: vi.fn(),
  getCanaryIronhandStatus: vi.fn(), getCanaryIronhandEvents: vi.fn(),
  getCanaryJudgeStatus: vi.fn(), getCanaryJudgeEvents: vi.fn(),
  getRebalancerStatus: vi.fn(), getRebalancerEvents: vi.fn(),
  getCollusionStatus: vi.fn(), getCollusionRings: vi.fn(),
  getSweeperStatus: vi.fn(), getSweeperEvents: vi.fn(),
  getFederationSyncStatus: vi.fn(),
  getSagaStatus: vi.fn(), getSagaEvents: vi.fn(),
  getSupplyAuditorStatus: vi.fn(), getSupplyAuditorEvents: vi.fn(),
}))
vi.mock('@/services/api/agentCardPullsync', () => ({ getPullsyncStatus: api.getPullsyncStatus }))
vi.mock('@/services/api/agentHealth', () => ({
  getAgentHealthStatus: api.getAgentHealthStatus, getAgentHealthTransitions: api.getAgentHealthTransitions }))
vi.mock('@/services/api/canaryIronhand', () => ({
  getCanaryIronhandStatus: api.getCanaryIronhandStatus, getCanaryIronhandEvents: api.getCanaryIronhandEvents }))
vi.mock('@/services/api/canaryJudge', () => ({
  getCanaryJudgeStatus: api.getCanaryJudgeStatus, getCanaryJudgeEvents: api.getCanaryJudgeEvents }))
vi.mock('@/services/api/canaryRebalancer', () => ({
  getRebalancerStatus: api.getRebalancerStatus, getRebalancerEvents: api.getRebalancerEvents }))
vi.mock('@/services/api/collusionWorker', () => ({
  getCollusionStatus: api.getCollusionStatus, getCollusionRings: api.getCollusionRings }))
vi.mock('@/services/api/crossTegSweeper', () => ({
  getSweeperStatus: api.getSweeperStatus, getSweeperEvents: api.getSweeperEvents }))
vi.mock('@/services/api/federationSync', () => ({ getFederationSyncStatus: api.getFederationSyncStatus }))
vi.mock('@/services/api/sagaTimeout', () => ({ getSagaStatus: api.getSagaStatus, getSagaEvents: api.getSagaEvents }))
vi.mock('@/services/api/supplyAuditor', () => ({
  getSupplyAuditorStatus: api.getSupplyAuditorStatus, getSupplyAuditorEvents: api.getSupplyAuditorEvents }))
vi.mock('@/components/common/csvExport', () => ({ downloadCsv: vi.fn() }))

import AgentCardPullSyncModal from './AgentCardPullSyncModal.vue'
import AgentHealthModal from './AgentHealthModal.vue'
import CanaryIronhandModal from './CanaryIronhandModal.vue'
import CanaryJudgeModal from './CanaryJudgeModal.vue'
import CanaryRebalancerModal from './CanaryRebalancerModal.vue'
import CollusionWorkerModal from './CollusionWorkerModal.vue'
import CrossTegSweeperModal from './CrossTegSweeperModal.vue'
import FederationSyncModal from './FederationSyncModal.vue'
import SagaTimeoutCheckerModal from './SagaTimeoutCheckerModal.vue'
import SupplyAuditorModal from './SupplyAuditorModal.vue'

const opts = { global: { stubs: { teleport: true, Icon: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'),
  { response: { status: 502, data: '<html>502 Bad Gateway</html>' } })

interface Case {
  name: string
  comp: any
  /** the tab buttons' class (none: a modal without tabs) */
  tab?: string
  /** the tabs that draw from the status read: each must say it could not be read */
  noticeTabs: string[]
  /** a modal without tabs: its body must say it could not be read (the peers list) */
  noticeInBody?: boolean
  /** what the modal said over the failed reads before this change */
  claims: (string | RegExp)[]
}

const CASES: Case[] = [
  { name: 'SupplyAuditorModal', comp: SupplyAuditorModal, tab: '.sam-tab', noticeTabs: ['Local Cycle'],
    claims: ['invariant holds', 'across 0 registries', 'No local cycle recorded yet'] },
  { name: 'CanaryRebalancerModal', comp: CanaryRebalancerModal, tab: '.crm-tab', noticeTabs: ['Funding Paths'],
    claims: ['all healthy', /\b0 active\b/, 'No rebalancer fundings in last 24h'] },
  { name: 'CanaryIronhandModal', comp: CanaryIronhandModal, tab: '.cim-tab', noticeTabs: ['Failure Breakdown'],
    claims: [/\b0 pass\b/, /\b0 fail\b/, 'No failures in the last 24h', 'Fleet healthy'] },
  { name: 'CanaryJudgeModal', comp: CanaryJudgeModal, tab: '.cjm-tab', noticeTabs: ['Outcome Breakdown', 'Latency'],
    claims: [/\b0 paths\b/, /\b0 pass\b/, 'no failures in 24h', 'No path has < 100% pass rate'] },
  { name: 'CollusionWorkerModal', comp: CollusionWorkerModal, noticeTabs: [], claims: ['all clean'] },
  { name: 'CrossTegSweeperModal', comp: CrossTegSweeperModal, tab: '.cts-tab', noticeTabs: ['Trends'],
    claims: ['all healthy', /\b0 TEGs\b/, 'pending 0', 'across 0 TEGs'] },
  { name: 'SagaTimeoutCheckerModal', comp: SagaTimeoutCheckerModal, tab: '.stm-tab', noticeTabs: ['Pending Sagas', 'Frame Flow'],
    claims: ['all healthy', /\b0 registries reporting\b/, 'No pending settlements past deadline', 'No cross-frame refunds in last 24h'] },
  { name: 'FederationSyncModal', comp: FederationSyncModal, noticeTabs: [], noticeInBody: true,
    claims: [/\b0 stale\b/, 'all clean', /\b0 of 0\b/, 'No peers match the current filter'] },
  { name: 'AgentCardPullSyncModal', comp: AgentCardPullSyncModal, tab: '.acps-tab', noticeTabs: ['Last cycle', 'Drift fields (24h)'],
    claims: [/\b0 × 304/, /\b0 field\(s\)/, 'candidates: 0', 'No agents have been pulled yet', 'No drift detected in the last 24h'] },
  { name: 'AgentHealthModal', comp: AgentHealthModal, tab: '.ahm-tab',
    noticeTabs: ['Recent Transitions', 'Transition Matrix', 'Currently Down'],
    claims: ['every 300s', 'No state transitions on record', 'No transitions in last 24h', 'No agents currently in non-healthy state'] },
]

function claimsShown(text: string, claims: (string | RegExp)[]): string[] {
  return claims.filter((c) => (typeof c === 'string' ? text.includes(c) : c.test(text))).map(String)
}

describe('the worker modals say a failed read failed', () => {
  beforeEach(() => {
    for (const f of Object.values(api)) { f.mockReset(); f.mockRejectedValue(failure()) }
  })

  for (const c of CASES) {
    it(`${c.name}: no verdict over failed reads, and each status tab says it could not read`, async () => {
      const w = mount(c.comp, opts)
      await flushPromises()
      const seen: string[] = claimsShown(w.text(), c.claims)
      const silent: string[] = []
      if (c.noticeInBody && !w.find('[data-read-failed]').exists()) silent.push('(body)')
      if (c.tab) {
        const tabs = w.findAll(c.tab)
        expect(tabs.length, `${c.name} has tabs`).toBeGreaterThan(1)
        for (const t of tabs) {
          await t.trigger('click')
          await flushPromises()
          seen.push(...claimsShown(w.text(), c.claims))
          if (c.noticeTabs.includes(t.text().trim()) && !w.find('[data-read-failed]').exists()) silent.push(t.text().trim())
        }
      }
      if (c.name === 'AgentCardPullSyncModal') {
        seen.push(...w.findAll('.acps-stat-sub').map((e) => e.text()).filter((s) => s === 'clean'))
      }
      if (c.name === 'AgentHealthModal') {
        const down = w.findAll('.ahm-stat-value')[1]
        if (down?.text() === '0') seen.push('Currently down 0')
      }
      // one assertion, so a failure names both halves: the verdicts drawn, and the places that did not say the read failed
      expect({ drawn: [...new Set(seen)], silent }, c.name).toEqual({ drawn: [], silent: [] })
      w.unmount()
    })
  }
})

describe('an answered status keeps its verdicts (controls)', () => {
  beforeEach(() => {
    for (const f of Object.values(api)) { f.mockReset(); f.mockRejectedValue(failure()) }
  })

  it('the supply auditor: a read with no breaches says the invariant holds; no local cycle says so', async () => {
    api.getSupplyAuditorStatus.mockResolvedValue({
      summary: { cycles_24h: 1440, breaches_24h: 0, errors_24h: 0, registries_reporting: 2, live_status: 'OK',
        live_delta: '0', live_net_supply: '1', live_total_circulating: '1' },
      errors_by_reason: {}, per_registry: [], live_audit: null,
      local_last_cycle: { status: null, delta: '0', net_supply: '0', total_circulating: '0', tokens_issued: '0',
        tokens_destroyed: '0', tokens_fees: '0', last_audit_iso: null, consecutive_failures: 0 },
      snapshot_iso: '2026-10-05T12:00:00Z',
    })
    api.getSupplyAuditorEvents.mockResolvedValue({ events: [], total_returned: 0, filters_applied: { limit: 100 } })
    const w = mount(SupplyAuditorModal, opts)
    await flushPromises()
    expect(w.text()).toContain('invariant holds')
    expect(w.text()).toContain('across 2 registries')
    expect(w.text()).toContain('No SupplyInvariantBreach events on record')
    await w.findAll('.sam-tab').find((t) => t.text().trim() === 'Local Cycle')!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('No local cycle recorded yet')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })

  it('the health checker: answered with nobody down says so, in every tab', async () => {
    api.getAgentHealthStatus.mockResolvedValue({
      summary: { cycles_24h: 288, probes_24h: 10, state_changes_24h: 0, registries_reporting: 1, agents_active: 5,
        agents_unhealthy: 0, agents_unreachable: 0, agents_never_observed: 0, interval_sec: 300 },
      probes_by_outcome: {}, transitions_grid: {}, per_registry: [], db_summary: { healthy: 5 },
      flapping_or_down: [], local_last_cycle: {}, snapshot_iso: '2026-10-05T12:00:00Z',
    })
    api.getAgentHealthTransitions.mockResolvedValue({ transitions: [], total_returned: 0, filters_applied: { limit: 150 } })
    const w = mount(AgentHealthModal, opts)
    await flushPromises()
    expect(w.text()).toContain('every 300s')
    expect(w.findAll('.ahm-stat-value')[1].text()).toBe('0')
    const said: string[] = []
    for (const t of w.findAll('.ahm-tab')) {
      await t.trigger('click')
      await flushPromises()
      said.push(w.text())
      expect(w.find('[data-read-failed]').exists(), t.text()).toBe(false)
    }
    expect(said.join('\n')).toContain('No state transitions on record')
    expect(said.join('\n')).toContain('No transitions in last 24h')
    expect(said.join('\n')).toContain('No agents currently in non-healthy state')
    w.unmount()
  })
})
