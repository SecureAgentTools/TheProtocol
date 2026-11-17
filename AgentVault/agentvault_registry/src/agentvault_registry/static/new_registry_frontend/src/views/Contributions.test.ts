/**
 * V0666 D2 (order gwo_f565ebd0575703f199dd9200): the Contributions area (#/contributions). Off on this registry, it says so in one sentence and asks nothing;
 * on, it lists the developer's organizations and their release lines, a line's queue by lane with each change's checker record, reviews and ballot, the vote
 * for a decider (confirmed: a vote is never changed) and none for anyone else, the owner's go and veto, the line form (create and change, later ballots only)
 * and the registry's refusal sentence where it was asked. Red before D2: views/Contributions.vue does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const h = vi.hoisted(() => ({
  cfg: null as any, auth: null as any, route: { query: {} as Record<string, any> }, replace: null as any,
  orgs: null as any, teams: null as any, teamMembers: null as any,
  lines: null as any, line: null as any, changes: null as any, vote: null as any, go: null as any, veto: null as any, create: null as any, update: null as any,
  report: null as any, download: null as any,
}))
vi.mock('@/services/api/distributionReports', () => ({ getReport: (...a: any[]) => h.report(...a), getRecord: vi.fn() }))
vi.mock('@/services/contentChanges/download', () => ({ downloadSigned: (...a: any[]) => h.download(...a), fileNameOf: () => 'x' }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => h.cfg }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ replace: h.replace, push: vi.fn() }) }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: {
  listOrganizations: (...a: any[]) => h.orgs(...a), listTeams: (...a: any[]) => h.teams(...a), listTeamMembers: (...a: any[]) => h.teamMembers(...a) } }))
vi.mock('@/services/api/codeDistributions', () => ({
  listOrgLines: (...a: any[]) => h.lines(...a), getLine: (...a: any[]) => h.line(...a), listLineChanges: (...a: any[]) => h.changes(...a),
  voteLineChange: (...a: any[]) => h.vote(...a), ownerGo: (...a: any[]) => h.go(...a), ownerVeto: (...a: any[]) => h.veto(...a),
  createLine: (...a: any[]) => h.create(...a), updateLine: (...a: any[]) => h.update(...a) }))

import Contributions from './Contributions.vue'

const SHA = 'a'.repeat(40)
const LINE = { slug: 'lyceum', title: 'Lyceum', organization_id: 'org-a', base_release: 'V0666', release_name: 'V0666_lyceum', branch: 'distribution/V0666_lyceum',
  open_paths: [CONSOLE_PREFIX + 'views'], decider_team_id: 'team-1', quorum_percent: 50, pass_rule: 'simple', state: 'active', deciders: 3, deciders_note: null }
const ch = (id: string, over: Record<string, any> = {}) => ({ id, title: `Change ${id}`, state: 'proposed', commit: SHA, reviews: [], sensitive: false,
  created_at: '2026-11-15T10:00:00Z', code_distribution: { slug: 'lyceum', state: 'active' }, line_ballot: { votes: 0, deciders_now: 3, ends: null, result: null }, ...over })
const QUEUE = [
  ch('cc_p'), ch('cc_c', { state: 'accepted', acceptance: { ok: true } }),
  ch('cc_r', { state: 'accepted', acceptance: { ok: true }, reviews: [{ commit: SHA, verdict: 'approve' }], review_verdict: { approvals: 1, needed: 1, blockers: [] } }),
  ch('cc_b', { state: 'balloting', acceptance: { ok: true }, line_ballot: { votes: 1, deciders_now: 3, ends: '2026-11-17T09:30:00Z', result: null } }),
  ch('cc_pa', { state: 'passed', veto_window_closes_at: '2099-01-01T00:00:00Z', line_ballot: { result: { status: 'PASSED', sentence: '2 for, 0 against, of 3 deciders: passed' } } }),
  ch('cc_m', { state: 'merged' }),
  ch('cc_f', { state: 'failed', acceptance: { ok: false, reasons: ['ci_red'] }, line_ballot: { result: { status: 'FAILED', sentence: '1 of 3 deciders voted, below the quorum of 50 percent' } } }),
]
const org = (over: Record<string, any> = {}) => ({ id: 'org-a', name: 'Lyceum Labs', owner_id: 1, my_role: 'owner', is_active: true, ...over })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const mountIt = () => mount(Contributions, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })

function setCfg(on: boolean | null, failed = false) {
  h.cfg = { codeDistributionsEnabled: ref(on === true), loaded: ref(on !== null || failed), readFailed: ref(failed), reload: vi.fn(), load: vi.fn().mockResolvedValue({}) }
}

describe('the Contributions area', () => {
  beforeEach(() => {
    setCfg(true)
    h.auth = { isAuthenticated: true, user: { id: 1 }, activeAgent: { did: 'did:theprotocol:a' } }
    h.route.query = {}
    h.replace = vi.fn()
    h.orgs = vi.fn().mockResolvedValue([org()])
    h.teams = vi.fn().mockResolvedValue([{ id: 'team-1', name: 'Core', is_active: true }])
    h.teamMembers = vi.fn().mockResolvedValue([])
    h.lines = vi.fn().mockResolvedValue([LINE])
    h.line = vi.fn().mockResolvedValue(LINE)
    h.changes = vi.fn().mockResolvedValue(QUEUE)
    h.vote = vi.fn(); h.go = vi.fn(); h.veto = vi.fn(); h.create = vi.fn(); h.update = vi.fn()
    h.report = vi.fn().mockResolvedValue({ kind: 'distribution.release.report', subject: 'V0666_lyceum' }); h.download = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ identity: { software_version: 'TheProtocolReleaseV0666' } }) }))
  })

  it('says in one sentence that code distributions are off, and asks the registry for nothing', async () => {
    setCfg(false)
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-off').text()).toBe('Code distributions are off on this registry.')
    expect(h.orgs).not.toHaveBeenCalled()
    expect(h.lines).not.toHaveBeenCalled()
    expect(tid(w, 'ctb-lines').exists()).toBe(false)
  })

  it('lists the organizations and their lines, opens a line from the link and shows its queue by lane, the ended change kept', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-org-org-a').text()).toContain('Lyceum Labs')
    expect(tid(w, 'ctb-line-lyceum').text()).toContain('V0666_lyceum')
    expect(h.changes).toHaveBeenCalledWith('lyceum')
    expect(tid(w, 'ctb-release').text()).toBe('V0666_lyceum')
    for (const [lane, id] of [['proposed', 'cc_p'], ['checked', 'cc_c'], ['review', 'cc_r'], ['balloting', 'cc_b'], ['passed', 'cc_pa'], ['merged', 'cc_m'], ['ended', 'cc_f']]) {
      expect(tid(w, `ctb-lane-${lane}`).find(`[data-testid="ctb-change-${id}"]`).exists()).toBe(true)
    }
    expect(tid(w, 'ctb-change-cc_f').find('[data-testid="ctb-checker"]').text()).toContain('ci_red')
    expect(tid(w, 'ctb-change-cc_f').find('[data-testid="ctb-ballot"]').text()).toBe('Failed: 1 of 3 deciders voted, below the quorum of 50 percent')
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-ballot"]').text()).toMatch(/1 of 3 deciders voted/)
    expect(JSON.parse(tid(w, 'ctb-propose').attributes('data-to')!)).toEqual({ name: 'code-changes-new', query: { line: 'lyceum' } })
    expect(tid(w, 'ctb-change-cc_b').find('.ctb-tag').text()).toBe('Deciders voting')                // a line's ballot is its deciders', never the members'
  })

  it('lets a decider vote, only after confirming (a vote is never changed), and shows the registry\'s answer in place', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.vote = vi.fn().mockResolvedValue({ ...QUEUE[3], line_ballot: { votes: 2, deciders_now: 3, ends: '2026-11-17T09:30:00Z', result: null } })
    const w = mountIt(); await flushPromises()
    const card = () => tid(w, 'ctb-change-cc_b')
    await card().find('[data-testid="ctb-vote-for"]').trigger('click')
    expect(h.vote).not.toHaveBeenCalled()
    expect(card().text()).toMatch(/never changed/)
    await card().find('[data-testid="ctb-vote-confirm"]').trigger('click'); await flushPromises()
    expect(h.vote).toHaveBeenCalledWith('cc_b', true)
    expect(card().find('[data-testid="ctb-ballot"]').text()).toMatch(/2 of 3 deciders voted/)
    expect(card().find('[data-testid="ctb-voted"]').text()).toMatch(/Your vote for this change is in/)          // pass 3: the vote cast is said, not offered again
    expect(card().find('[data-testid="ctb-vote-for"]').exists()).toBe(false)
  })

  it('shows a refusal where the vote was asked', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.vote = vi.fn().mockRejectedValue({ response: { data: { code: 'already_voted', detail: 'you already voted on this change' } } })
    const w = mountIt(); await flushPromises()
    await tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote-against"]').trigger('click')
    await tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote-confirm"]').trigger('click'); await flushPromises()
    expect(h.vote).toHaveBeenCalledWith('cc_b', false)
    expect(tid(w, 'ctb-refusal-cc_b').text()).toBe('you already voted on this change')
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-voted"]').exists()).toBe(false)                        // a refused vote is not said as cast
  })

  it('offers no vote to a plain member and says who votes; a team lead who is a member votes', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.orgs = vi.fn().mockResolvedValue([org({ my_role: 'member' })])
    h.auth.user = { id: 7 }
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote"]').exists()).toBe(false)
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote-why"]').text()).toMatch(/deciding team’s leads vote here/)
    expect(tid(w, 'ctb-new-line').exists()).toBe(false)                       // a member does not create lines
    expect(tid(w, 'ctb-change-cc_pa').find('[data-testid="ctb-owner"]').exists()).toBe(false)
    h.teamMembers = vi.fn().mockResolvedValue([{ developer_id: 7, role: 'lead' }])
    w = mountIt(); await flushPromises()
    expect(h.teamMembers).toHaveBeenCalledWith('org-a', 'team-1')
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote-for"]').exists()).toBe(true)
  })

  it('gives the owner a go and a veto on a passed change; the veto needs its reason', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.veto = vi.fn().mockResolvedValue({ ...QUEUE[4], state: 'vetoed' })
    const w = mountIt(); await flushPromises()
    const card = () => tid(w, 'ctb-change-cc_pa')
    expect(card().find('[data-testid="ctb-owner-go"]').text()).toMatch(/window still runs/)
    await card().find('[data-testid="ctb-owner-veto"]').trigger('click')
    expect(card().find('[data-testid="ctb-veto-confirm"]').attributes('disabled')).toBeDefined()
    await card().find('[data-testid="ctb-veto-reason"]').setValue('it breaks the order page')
    await card().find('[data-testid="ctb-veto-confirm"]').trigger('click'); await flushPromises()
    expect(h.veto).toHaveBeenCalledWith('cc_pa', 'it breaks the order page')
    expect(tid(w, 'ctb-lane-ended').find('[data-testid="ctb-change-cc_pa"]').exists()).toBe(true)
  })

  it('creates a line: refuses what the registry would refuse first, prefills the base release, sends the body and opens the new line', async () => {
    h.lines = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([LINE])
    h.create = vi.fn().mockResolvedValue(LINE)
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-no-lines').text()).toMatch(/Create one/)
    await tid(w, 'ctb-new-line').trigger('click')
    expect((tid(w, 'ctb-f-base').element as HTMLInputElement).value).toBe('V0666')
    await tid(w, 'ctb-f-save').trigger('submit')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(h.create).not.toHaveBeenCalled()
    expect(tid(w, 'ctb-form-problems').text()).toMatch(/lowercase letters/)
    await tid(w, 'ctb-f-slug').setValue('lyceum')
    await tid(w, 'ctb-f-title').setValue('Lyceum')
    await tid(w, 'ctb-f-platform-path').trigger('click')
    await tid(w, 'ctb-f-team').setValue('team-1')
    await tid(w, 'ctb-f-quorum').setValue('60')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(h.create).toHaveBeenCalledWith({ organization_id: 'org-a', slug: 'lyceum', title: 'Lyceum', base_release: 'V0666', open_paths: [CONSOLE_PREFIX],
      decider_team_id: 'team-1', quorum_percent: 60, pass_rule: 'simple' })
    expect(h.replace).toHaveBeenCalledWith({ query: { org: 'org-a', line: 'lyceum' } })
  })

  it('changes a line: says a change applies to later ballots only, sends only what changed, and shows a refusal', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.update = vi.fn().mockRejectedValueOnce({ response: { data: { code: 'quorum_percent', detail: 'the quorum is a whole percent from 50 to 100' } } }).mockResolvedValue({ ...LINE, quorum_percent: 70 })
    const w = mountIt(); await flushPromises()
    await tid(w, 'ctb-edit-line').trigger('click')
    expect(tid(w, 'ctb-form-later').text()).toMatch(/ballots opened after it/)
    expect(tid(w, 'ctb-f-slug').exists()).toBe(false)
    await tid(w, 'ctb-f-quorum').setValue('70')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(h.update).toHaveBeenCalledWith('lyceum', { quorum_percent: 70 })
    expect(tid(w, 'ctb-form-error').text()).toBe('the quorum is a whole percent from 50 to 100')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(tid(w, 'ctb-form').exists()).toBe(false)
  })

  it('says a paused line is paused and why, and offers neither a proposal nor a vote', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    const paused = { ...LINE, state: 'paused', paused_reason: 'a vote is being bought' }
    h.line = vi.fn().mockResolvedValue(paused)
    h.changes = vi.fn().mockResolvedValue([ch('cc_b', { state: 'balloting', code_distribution: { slug: 'lyceum', state: 'paused' } })])
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-paused-reason').text()).toContain('a vote is being bought')
    expect(tid(w, 'ctb-propose').exists()).toBe(false)
    expect(tid(w, 'ctb-change-cc_b').find('[data-testid="ctb-vote-why"]').text()).toMatch(/paused/)
  })

  it('asks a visitor to sign in, and a person with no organization to join one', async () => {
    h.auth = { isAuthenticated: false, user: null }
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-signin').exists()).toBe(true)
    expect(h.orgs).not.toHaveBeenCalled()
    h.auth = { isAuthenticated: true, user: { id: 9 } }
    h.orgs = vi.fn().mockResolvedValue([])
    w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-no-orgs').text()).toMatch(/join or create one/)
  })

  it('shows the vote the reader already cast, from the registry, instead of the buttons (my_vote, session-lead seq 4803)', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    h.changes = vi.fn().mockResolvedValue([
      ch('cc_for', { state: 'balloting', line_ballot: { votes: 1, deciders_now: 3, my_vote: 'FOR' } }),
      ch('cc_against', { state: 'balloting', line_ballot: { votes: 1, deciders_now: 3, my_vote: 'AGAINST' } }),
      ch('cc_none', { state: 'balloting', line_ballot: { votes: 1, deciders_now: 3, my_vote: null } }),
    ])
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ctb-change-cc_for').find('[data-testid="ctb-voted"]').text()).toMatch(/Your vote for this change is in/)
    expect(tid(w, 'ctb-change-cc_for').find('[data-testid="ctb-vote-for"]').exists()).toBe(false)
    expect(tid(w, 'ctb-change-cc_against').find('[data-testid="ctb-voted"]').text()).toMatch(/Your vote against this change is in/)
    expect(tid(w, 'ctb-change-cc_none').find('[data-testid="ctb-vote-for"]').exists()).toBe(true)
  })

  it('V0667 D7: a member downloads the line\'s signed report, a refusal is shown in place, and a visitor with no organization sees no such button', async () => {
    h.route.query = { org: 'org-a', line: 'lyceum' }
    const w = mountIt(); await flushPromises(); await flushPromises()
    await tid(w, 'ctb-report').trigger('click'); await flushPromises()
    expect(h.report).toHaveBeenCalledWith('lyceum')
    expect(h.download).toHaveBeenCalledWith({ kind: 'distribution.release.report', subject: 'V0666_lyceum' })
    h.report.mockRejectedValue({ response: { data: { code: 'guest', detail: 'the report of a release line is read by the organization\'s members, not its guests' } } })
    await tid(w, 'ctb-report').trigger('click'); await flushPromises()
    expect(tid(w, 'ctb-report-error').text()).toContain('not its guests')
  })
})
