/**
 * §COCKPITDESK (2026-10-15) — the seven panes added that night, each over its own read, each against the answer
 * its source really gives: webhooks (failing first, never a query string), the Senate (the next to close, a vote
 * over but not tallied, no votes is not 0%), exchange rates (FX off is not a failed read), organizations (approvals
 * read only where you oversee, at most four reads, an unread one says so), the Guild board (best-paying first, the
 * bounty behind the privacy switch), settlements (what waits for a decision is not what is slashing) and the
 * release channel (an unread channel is not "up to date").
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ routes: {} as Record<string, unknown>, calls: [] as Array<{ url: string; params?: any }> }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn(async (url: string, cfg?: { params?: any }) => {
      h.calls.push({ url, params: cfg?.params })
      const v = h.routes[url]
      if (v instanceof Error) throw v
      if (v === undefined) throw Object.assign(new Error('Request failed with status code 404'), { response: { status: 404, data: { detail: 'Not Found' } } })
      return { data: v }
    }),
  },
}))
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), resolve: () => ({ name: 'x', href: '#/x' }) }) }))

import PaneWebhooks from './PaneWebhooks.vue'
import PaneSenate from './PaneSenate.vue'
import PaneForex from './PaneForex.vue'
import PaneOrgs from './PaneOrgs.vue'
import PaneGuildBoard from './PaneGuildBoard.vue'
import PaneSettlements from './PaneSettlements.vue'
import PaneRelease from './PaneRelease.vue'
import { usePrivacy } from '@/composables/usePrivacy'
import { attentionList } from '@/services/cockpit/attention'

const opts = { global: { stubs: { RecordLink: true } } }
const HOUR = 3600_000
const iso = (msFromNow: number) => new Date(Date.now() + msFromNow).toISOString()

beforeEach(() => { h.routes = {}; h.calls = []; const p = usePrivacy(); if (p.hidden.value) p.toggle() })

describe('Webhooks', () => {
  it('puts the failing endpoints first, then the paused, and prints host and path only', async () => {
    h.routes['/webhooks'] = [
      { id: 'a', url: 'https://ok.example/hook', events: ['agent.created'], is_active: true, failure_count: 0, last_triggered_at: iso(-HOUR) },
      { id: 'b', url: 'https://user:pw@paused.example/x?token=SECRET#frag', events: [], is_active: false, failure_count: 10 },
      { id: 'c', url: 'https://bad.example/in?key=SECRET2', events: ['a', 'b'], is_active: true, failure_count: 3 },
    ]
    const w = mount(PaneWebhooks, opts); await flushPromises()
    const rows = w.findAll('[data-testid="wh-row"]')
    expect(rows.map(r => r.attributes('data-state'))).toEqual(['failing', 'paused', 'ok'])
    expect(rows[0].text()).toContain('bad.example/in')
    expect(rows[0].text()).toContain('3 failed in a row')
    expect(rows[1].text()).toContain('paused after 10 failures')
    expect(w.text(), 'no query string, no userinfo').not.toMatch(/SECRET|user:pw|token=|frag/)
    expect(w.find('[data-testid="wh-head"]').text()).toBe('3 endpoints · 1 failing · 1 paused')
    expect(attentionList.value.find(a => a.id === 'webhooks'), 'the desk line hears the failing one').toMatchObject({ n: 1, tone: 'warn' })
    w.unmount()
    expect(attentionList.value.find(a => a.id === 'webhooks'), 'and forgets it when the pane leaves').toBeUndefined()
  })

  it('says how to start when there is none, and says why when the read fails', async () => {
    h.routes['/webhooks'] = []
    const w = mount(PaneWebhooks, opts); await flushPromises()
    expect(w.find('[data-testid="ckd-empty"]').text()).toContain('No webhook endpoints')
    h.routes['/webhooks'] = new Error('Network Error')
    const f = mount(PaneWebhooks, opts); await flushPromises()
    expect(f.find('[data-testid="ckd-error"]').text()).toContain('Network Error')
  })
})

describe('Senate', () => {
  it('lists the next to close first and keeps a vote that is over but untallied apart', async () => {
    h.routes['/governance/proposals'] = [
      { id: 1, title: 'Later', end_timestamp: iso(48 * HOUR), votes_for: 3, votes_against: 1, total_voters: 4 },
      { id: 2, title: 'Over', end_timestamp: iso(-HOUR), votes_for: 0, votes_against: 0, total_voters: 0 },
      { id: 3, title: 'Soon', end_timestamp: iso(2 * HOUR), votes_for: 1, votes_against: 1, total_voters: 2 },
    ]
    const w = mount(PaneSenate, opts); await flushPromises()
    const rows = w.findAll('[data-testid="sen-row"]')
    expect(rows.map(r => r.find('.sen-title').text())).toEqual(['Over', 'Soon', 'Later'])
    expect(rows[0].attributes('data-when')).toBe('over')
    expect(rows[0].text()).toContain('voting over, not tallied yet')
    expect(rows[0].text(), 'nothing cast is not 0%').toContain('no votes yet')
    expect(rows[1].text()).toContain('50% for')
    expect(rows[2].text()).toContain('75% for')
    expect(w.find('[data-testid="sen-head"]').text()).toBe('2 open · the next closes in 2h')
    expect(h.calls[0].params, 'open proposals only: the endpoint\'s default').not.toHaveProperty('include_closed')
  })

  it('says none is open when every vote is over', async () => {
    h.routes['/governance/proposals'] = [{ id: 9, title: 'Done', end_timestamp: iso(-HOUR) }]
    const w = mount(PaneSenate, opts); await flushPromises()
    expect(w.find('[data-testid="sen-head"]').text()).toBe('1 waiting for a tally, none open')
  })
})

describe('Exchange rates', () => {
  it('shows each pair both ways with its own units', async () => {
    h.routes['/teg/fx/rates'] = { available: true, rate_mode: 'pool', as_of: iso(-60_000),
      pairs: [{ a: 'SBXA', b: 'SBXB', a_per_b: '0.5', b_per_a: '2' }] }
    const w = mount(PaneForex, opts); await flushPromises()
    const row = w.find('[data-testid="fx-row"]')
    expect(row.text()).toContain('SBXA / SBXB')
    expect(row.text()).toContain('2.0000SBXB')
    expect(row.text()).toContain('0.5000SBXA')
    expect(w.find('[data-testid="fx-head"]').text()).toContain('1 pair · pool rates · as of')
  })

  it('tells "exchange is off" from "the read failed"', async () => {
    h.routes['/teg/fx/rates'] = { available: false, reason: 'FX_ENABLED is false' }
    const off = mount(PaneForex, opts); await flushPromises()
    expect(off.find('[data-testid="ckd-empty"]').text()).toContain('off on this registry: FX_ENABLED is false')
    expect(off.find('[data-testid="ckd-error"]').exists()).toBe(false)
    h.routes['/teg/fx/rates'] = new Error('timeout of 15000ms exceeded')
    const failed = mount(PaneForex, opts); await flushPromises()
    expect(failed.find('[data-testid="ckd-error"]').exists()).toBe(true)
  })
})

describe('Organizations', () => {
  it('reads approvals only where you oversee, at most four, and says when one could not be read', async () => {
    h.routes['/organizations'] = [
      { id: 'm1', name: 'Member Co', my_role: 'member', member_count: 5 },
      ...['o1', 'o2', 'o3', 'o4', 'o5'].map((id, i) => ({ id, name: `Own ${i}`, my_role: i % 2 ? 'admin' : 'owner', member_count: 2, agent_count: 1 })),
    ]
    h.routes['/organizations/o1/spend-approvals'] = { approvals: [{}, {}], count: 2 }
    h.routes['/organizations/o2/spend-approvals'] = { approvals: [], count: 0 }
    h.routes['/organizations/o3/spend-approvals'] = new Error('500')
    h.routes['/organizations/o4/spend-approvals'] = { approvals: [{}], count: 1 }
    const w = mount(PaneOrgs, opts); await flushPromises()
    const asked = h.calls.filter(c => c.url.endsWith('/spend-approvals')).map(c => c.url)
    expect(asked).toEqual(['/organizations/o1/spend-approvals', '/organizations/o2/spend-approvals',
      '/organizations/o3/spend-approvals', '/organizations/o4/spend-approvals'])
    expect(h.calls.find(c => c.url.endsWith('/spend-approvals'))!.params).toMatchObject({ status: 'pending' })
    expect(w.find('[data-testid="org-head"]').text()).toBe('6 organizations · 3 spend approvals pending')
    expect(w.findAll('[data-testid="org-row"]')[0].text(), 'the most waiting first').toContain('Own 0')
    expect(w.text()).toContain('approvals unread')
  })

  it('names a handover of ownership waiting for you', async () => {
    h.routes['/organizations'] = [{ id: 'x', name: 'Handed', my_role: 'admin', member_count: 1, pending_owner_is_me: true }]
    h.routes['/organizations/x/spend-approvals'] = { approvals: [], count: 0 }
    const w = mount(PaneOrgs, opts); await flushPromises()
    expect(w.find('[data-testid="org-owner-pending"]').exists()).toBe(true)
  })
})

describe('Guild board', () => {
  it('ranks open orders by bounty and hides the amounts with the privacy switch', async () => {
    h.routes['/guild/orders'] = { total: 3, orders: [
      { id: '1', title: 'Small', bounty: 5, currency: 'SBXA', bid_count: 1 },
      { id: '2', title: 'Big', bounty: 120, currency: 'SBXA', bid_count: 0, deadline: iso(3 * HOUR) },
      { id: '3', title: 'Late', bounty: 40, currency: 'SBXA', bid_count: 2, deadline: iso(-HOUR) },
    ] }
    const w = mount(PaneGuildBoard, opts); await flushPromises()
    expect(h.calls[0].params).toMatchObject({ status_filter: 'open' })
    const rows = w.findAll('[data-testid="gb-row"]')
    expect(rows.map(r => r.find('.gb-title').text())).toEqual(['Big', 'Late', 'Small'])
    expect(rows[0].text()).toContain('due in 3h')
    expect(rows[1].text()).toContain('past its deadline')
    expect(rows[2].text()).toContain('1 bid')
    expect(w.find('[data-testid="gb-head"]').text()).toContain('the largest pays 120')
    usePrivacy().toggle(); await flushPromises()
    expect(w.text()).not.toContain('120')
  })
})

describe('Settlements', () => {
  it('counts what waits for a decision apart from what is slashing, and lists the waiting', async () => {
    h.routes['/federation/disputes/settlements'] = { count: 4, stats: { pending: 2 }, settlements: [
      { id: 's1', status: 'PENDING_ADMIN_APPROVAL', requested_amount: 12.5, defendant_did: 'did:theprotocol:abcdef123456789',
        origin_registry_url: 'https://sbx-beta.example/api', requested_at: iso(-2 * HOUR) },
      { id: 's2', status: 'PENDING_SLASH' }, { id: 's3', status: 'SLASHING' }, { id: 's4', status: 'FAILED' },
    ] }
    const w = mount(PaneSettlements, opts); await flushPromises()
    expect(w.find('[data-testid="stl-head"]').text()).toBe('1 waiting for a decision · 2 slashing · 1 failed')
    const row = w.find('[data-testid="stl-row"]')
    expect(row.text()).toContain('12.5')
    expect(row.text()).toContain('asked by sbx-beta.example')
    expect(row.text()).toContain('abcdef12…')
  })
})

describe('Release channel', () => {
  const base = { enabled: true, channel_url: '', public_pull: false, public_namespace: '', node_kind: 'frame', rollout_command: null,
    last_check_at: iso(-HOUR), last_outcome: 'ok', last_error: null, running: { software_version: 'TheProtocolReleaseV0615' },
    latest: { version: 'V0615', kind: 'stable' }, newer: [], update_available: false, kind: 'stable', comparable: true, notified: {}, schedule: null }

  it('says up to date only when the channel was read and holds nothing newer', async () => {
    h.routes['/admin/release-channel/status'] = base
    const w = mount(PaneRelease, opts); await flushPromises()
    expect(w.find('[data-testid="ckd-release"]').attributes('data-verdict')).toBe('ok')
    expect(w.find('[data-testid="rel-running"]').text()).toContain('TheProtocolReleaseV0615')
  })

  it('never reads an unread channel as up to date, and names a newer release', async () => {
    h.routes['/admin/release-channel/status'] = { ...base, last_outcome: 'unreachable' }
    const u = mount(PaneRelease, opts); await flushPromises()
    expect(u.find('[data-testid="ckd-release"]').attributes('data-verdict')).toBe('unread')
    h.routes['/admin/release-channel/status'] = { ...base, update_available: true, latest: { version: 'V0616', kind: 'hotfix' } }
    const n = mount(PaneRelease, opts); await flushPromises()
    expect(n.find('[data-testid="rel-verdict"]').text()).toContain('V0616 (hotfix)')
  })
})
