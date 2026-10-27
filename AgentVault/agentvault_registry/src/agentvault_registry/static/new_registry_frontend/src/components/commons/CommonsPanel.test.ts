import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the commons tab: a member sees the ballot they would replace and can never give
 * points to their own work or more than 100 in all; a ballot that needs a person's confirmation is resent, after the
 * approval, with exactly the points that were shown; a closed season says what each submission got and why.
 */
const h = vi.hoisted(() => ({
  api: {
    seasons: vi.fn(), season: vi.fn(), mine: vi.fn(), ballot: vi.fn(), submit: vi.fn(),
    open: vi.fn(), close: vi.fn(), strike: vi.fn(), pay: vi.fn(), cancel: vi.fn(), writeOff: vi.fn(),
  },
  ui: { showSuccess: vi.fn(), showWarning: vi.fn(), showError: vi.fn(), showInfo: vi.fn() },
  auth: { isAuthenticated: true, userRole: 'developer', user: {} as Record<string, unknown> },
}))
vi.mock('@/services/api/commons', () => ({ commonsApi: h.api }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/services/api/liability', () => ({ liabilityApi: { pendingChallenges: vi.fn().mockResolvedValue({ challenges: [] }) } }))

import CommonsPanel from './CommonsPanel.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'

const DAY = 86_400_000
const FORBIDDEN = /\b(yield|apy|dividends?|shares?|returns?|investments?|rewards?|interest)\b/i

function sub(id: number, over: Record<string, unknown> = {}) {
  return { id, kind: 'change', title: `Work ${id}`, description: '', evidence: [{ type: 'commit', ref: `c${id}` }],
    submitter_did: `did:theprotocol:s${id}`, submitter_name: `Agent ${id}`, status: 'submitted', struck_reason: null,
    created_at: new Date(Date.now() - DAY).toISOString(), mine: false, award: null, ...over }
}
function season(over: Record<string, unknown> = {}) {
  return { id: 4, title: 'Autumn', status: 'open', currency: 'SBXA', opens_at: new Date(Date.now() - DAY).toISOString(),
    ends_at: new Date(Date.now() + 7 * DAY).toISOString(), budget: '500', seed: '0', fee_share_percent: '50',
    fee_collector_balance_at_open: '1000', recipient_cap_percent: '20', min_voters: 2, ballot_points: 100,
    closed_at: null, paid_at: null, cancelled_at: null, cancel_reason: null, rules: { max_submissions_per_developer: 5 },
    tally: null, submissions: [sub(1), sub(2), sub(3)], ballots_cast: 2, ballots: null, my_ballot: null, ...over }
}
const STEP = { kind: 'step_up', message: '', stepUp: { reason: 'commons_ballot', challengeId: 'ch_9', challengeHash: 'h',
  facts: { kind: 'commons.ballot', season_id: 4, total_points: 100 }, expiresAt: new Date(Date.now() + 120_000).toISOString(),
  ttlSeconds: 120, methods: ['device', 'totp'], how: null } }

function mountPanel() {
  return mount(CommonsPanel, { global: { stubs: { teleport: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
}
function points(w: ReturnType<typeof mountPanel>, id: number) {
  return w.find(`[data-testid="commons-points-${id}"]`)
}

beforeEach(() => {
  for (const f of Object.values(h.api)) f.mockReset()
  for (const f of Object.values(h.ui)) f.mockReset()
  h.auth.isAuthenticated = true
  h.auth.userRole = 'developer'
  h.auth.user = {}
  h.api.seasons.mockResolvedValue({ state: 'ok', seasons: [{ ...season(), paid_total: '0', submissions: 3, ballots: 2 }], currency: 'SBXA' })
  h.api.season.mockResolvedValue({ state: 'ok', season: season() })
  h.api.mine.mockResolvedValue({ seasonId: 4, status: 'open', isMember: true, mySubmissions: [sub(2, { mine: true })],
    myBallot: { allocations: { 1: 60, 99: 5 }, totalPoints: 65, updatedAt: new Date().toISOString() } })
})

describe('the commons tab', () => {
  it('a registry without the commons says so', async () => {
    h.api.seasons.mockResolvedValue({ state: 'disabled', message: '' })
    const w = mountPanel(); await flushPromises()
    expect(w.attributes('data-state')).toBe('disabled')
    expect(w.find('[data-testid="commons-disabled"]').exists()).toBe(true)
  })

  it('shows the season: its window, its budget and where the budget came from, its rules', async () => {
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-season"]').attributes('data-phase')).toBe('open')
    expect(w.find('[data-testid="commons-budget"]').text()).toContain('500')
    expect(w.find('[data-testid="commons-budget-source"]').text()).toContain("50% of the fee collector's 1,000 SBXA")
    expect(w.find('[data-testid="commons-rules"]').text()).toContain('at least 2 of the members')
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('a member\'s saved ballot is the starting point; points on submissions no longer live are dropped', async () => {
    const w = mountPanel(); await flushPromises()
    expect((points(w, 1).element as HTMLInputElement).value).toBe('60')
    expect(w.find('[data-testid="commons-points-left"]').text()).toContain('40 of 100 points left')
    expect(w.find('[data-testid="commons-saved-ballot"]').exists()).toBe(true)
    expect(w.find('[data-testid="commons-ballot-send"]').text()).toContain('Replace my ballot')
  })

  it('never a field for the member\'s own work, and never more than 100 in all', async () => {
    const w = mountPanel(); await flushPromises()
    expect(points(w, 2).exists()).toBe(false)
    expect(w.find('[data-id="2"] [data-testid="commons-sub-mine"]').exists()).toBe(true)
    await points(w, 3).setValue('80')
    await points(w, 3).trigger('change')
    expect((points(w, 3).element as HTMLInputElement).value).toBe('40')
    expect(w.find('[data-testid="commons-points-left"]').text()).toContain('0 of 100')
  })

  it('a ballot that needs a person: the dialog opens, the fields lock, and the approval resends exactly these points', async () => {
    h.api.ballot.mockResolvedValueOnce(STEP).mockResolvedValueOnce({ kind: 'saved', seasonId: 4, allocations: { 1: 60, 3: 40 }, totalPoints: 100, digest: 'd' })
    const w = mountPanel(); await flushPromises()
    await points(w, 3).setValue('40'); await points(w, 3).trigger('change')
    await w.find('[data-testid="commons-ballot-send"]').trigger('click'); await flushPromises()
    expect(h.api.ballot).toHaveBeenNthCalledWith(1, 4, { 1: 60, 3: 40 }, {})
    const dialog = w.findComponent(StepUpConfirm)
    expect(dialog.exists()).toBe(true)
    expect(points(w, 1).attributes('disabled')).toBeDefined()
    dialog.vm.$emit('approved', 'ch_9'); await flushPromises()
    expect(h.api.ballot).toHaveBeenNthCalledWith(2, 4, { 1: 60, 3: 40 }, { challengeId: 'ch_9' })
    expect(h.ui.showSuccess).toHaveBeenCalled()
    expect(w.findComponent(StepUpConfirm).exists()).toBe(false)
    expect(h.api.season).toHaveBeenCalledTimes(2)              // the season is read again after the save
  })

  it('a refused ballot on the member\'s own work drops exactly those points and says why', async () => {
    h.api.ballot.mockResolvedValue({ kind: 'refused', status: 422, error: 'own_submission', message: '', submissionIds: ['1'] })
    const w = mountPanel(); await flushPromises()
    await w.find('[data-testid="commons-ballot-send"]').trigger('click'); await flushPromises()
    expect((points(w, 1).element as HTMLInputElement).value).toBe('0')
    expect(h.ui.showWarning).toHaveBeenCalledWith(expect.any(String), expect.stringContaining('own work'))
  })

  it('control: a developer who is not a member gets no ballot, only the reason and the way to submit', async () => {
    h.api.mine.mockResolvedValue({ seasonId: 4, status: 'open', isMember: false, mySubmissions: [], myBallot: null })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-not-member"]').exists()).toBe(true)
    expect(points(w, 1).exists()).toBe(false)
    expect(w.find('[data-testid="commons-ballot"]').exists()).toBe(false)
    expect(w.find('[data-testid="commons-submit-open"]').exists()).toBe(true)
  })

  it('a closed season says what each submission got, and why one got nothing; the ballots are published', async () => {
    const closed = season({ status: 'closed', closed_at: new Date().toISOString(),
      submissions: [sub(1, { award: { median_points: '40', voters: 3, share: '0.6', amount: '100', status: 'pending', funded_amount: null, shortfall: null, paid_at: null } }), sub(3)],
      tally: { ballots_cast: 3, ballots_counted: 3, awarded: '100', unallocated: '400', tallied_at: null,
        rows: [{ submission_id: 1, voters: 3, median_points: '40', share: '1', amount: '100', capped: true, reason: null },
               { submission_id: 3, voters: 1, median_points: '0', share: '0', amount: '0', capped: false, reason: 'too_few_voters' }] },
      ballots: [{ voter_did: 'did:theprotocol:voter-one-0000000000', allocations: { 1: 40 }, total_points: 40 }] })
    h.api.seasons.mockResolvedValue({ state: 'ok', seasons: [{ ...closed, paid_total: '0', submissions: 2, ballots: 3 }], currency: 'SBXA' })
    h.api.season.mockResolvedValue({ state: 'ok', season: closed })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-season"]').attributes('data-phase')).toBe('closed')
    expect(w.find('[data-testid="commons-result"]').text()).toContain('400 SBXA of the budget is not paid out')
    expect(w.find('[data-id="1"] [data-testid="commons-award"]').text()).toContain('100 SBXA awarded')
    expect(w.find('[data-id="3"] [data-testid="commons-no-award"]').text()).toContain('Points came from 1 of the members; 2 are needed')
    expect(w.find('[data-testid="commons-ballots"]').exists()).toBe(true)
    expect(points(w, 1).exists()).toBe(false)
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('an admin strikes a submission with a public reason of at least five characters', async () => {
    h.auth.user = { admin_treasury: true }
    h.api.strike.mockResolvedValue({ kind: 'ok', data: { id: 3, status: 'struck', struck_reason: 'no such commit' } })
    const w = mountPanel(); await flushPromises()
    await w.find('[data-testid="commons-strike-open-3"]').trigger('click')
    const reason = w.find('[data-testid="commons-strike-reason-3"]')
    await reason.setValue('no')
    expect(w.find('[data-testid="commons-strike-confirm-3"]').attributes('disabled')).toBeDefined()
    await reason.setValue('no such commit')
    await w.find('form.cmn-strike__form').trigger('submit'); await flushPromises()
    expect(h.api.strike).toHaveBeenCalledWith(4, 3, 'no such commit')
    expect(w.find('[data-testid="commons-admin"]').exists()).toBe(true)
  })

  it('a failed award is written off by an admin with a reason; once payment started nothing is struck any more', async () => {
    h.auth.user = { admin_treasury: true }
    const failed = { id: 12, median_points: '40', voters: 3, share: '1', amount: '100', status: 'failed', funded_amount: null,
      shortfall: null, paid_at: null, attempted_at: new Date(Date.now() - 2 * DAY).toISOString() }
    const closed = season({ status: 'closed', closed_at: new Date().toISOString(),
      submissions: [sub(1, { award: failed }), sub(3, { award: { ...failed, id: undefined, status: 'failed' } })],
      tally: { ballots_cast: 3, ballots_counted: 3, awarded: '200', unallocated: '300', tallied_at: null, rows: [] } })
    h.api.seasons.mockResolvedValue({ state: 'ok', seasons: [{ ...closed, paid_total: '0', submissions: 2, ballots: 3 }], currency: 'SBXA' })
    h.api.season.mockResolvedValue({ state: 'ok', season: closed })
    h.api.writeOff.mockResolvedValue({ kind: 'ok', data: { id: 12, status: 'written_off', unpaid_awards: 1 } })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-strike-open-1"]').exists()).toBe(false)     // the tally is fixed
    expect(w.find('[data-testid="commons-writeoff-open-3"]').exists()).toBe(false)   // control: no award id, no write-off
    await w.find('[data-testid="commons-writeoff-open-1"]').trigger('click')
    await w.find('[data-testid="commons-writeoff-reason-1"]').setValue('no')
    expect(w.find('[data-testid="commons-writeoff-confirm-1"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="commons-writeoff-reason-1"]').setValue('paid by hand on the treasury rail')
    await w.find('[data-id="1"] form').trigger('submit'); await flushPromises()
    expect(h.api.writeOff).toHaveBeenCalledWith(4, 12, 'paid by hand on the treasury rail')
    expect(h.ui.showSuccess).toHaveBeenCalled()
  })

  it('a payment run that leaves awards past the retry window says they need a decision', async () => {
    h.auth.userRole = 'admin'
    const closed = season({ status: 'closed', closed_at: new Date().toISOString(),
      submissions: [sub(1, { award: { id: 12, median_points: '40', voters: 3, share: '1', amount: '100', status: 'pending', funded_amount: null, shortfall: null, paid_at: null, attempted_at: null } })],
      tally: { ballots_cast: 3, ballots_counted: 3, awarded: '100', unallocated: '400', tallied_at: null, rows: [] } })
    h.api.seasons.mockResolvedValue({ state: 'ok', seasons: [{ ...closed, paid_total: '0', submissions: 1, ballots: 3 }], currency: 'SBXA' })
    h.api.season.mockResolvedValue({ state: 'ok', season: closed })
    h.api.pay.mockResolvedValue({ kind: 'ok', data: { season: closed, payments: [], unpaid_awards: 1,
      needs_decision: [{ award_id: 12, recipient_did: 'did:a', amount: '100', status: 'failed', first_attempt_at: null }] } })
    const w = mountPanel(); await flushPromises()
    await w.find('[data-testid="commons-pay"]').trigger('click')
    await w.find('[data-testid="commons-admin-confirm-yes"]').trigger('click'); await flushPromises()
    expect(h.api.pay).toHaveBeenCalledWith(4)
    expect(h.ui.showWarning).toHaveBeenCalledWith(expect.any(String), expect.stringContaining('23-hour window: 1'))
  })

  it('control: without admin_treasury there is no strike and no administration', async () => {
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-strike-open-3"]').exists()).toBe(false)
    expect(w.find('[data-testid="commons-admin"]').exists()).toBe(false)
  })

  it('no season yet: the empty line for everyone, the opening form for an admin', async () => {
    h.api.seasons.mockResolvedValue({ state: 'ok', seasons: [], currency: 'SBXA' })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="commons-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="commons-admin"]').exists()).toBe(false)
    h.auth.userRole = 'admin'
    const a = mountPanel(); await flushPromises()
    expect(a.find('[data-testid="commons-admin"]').attributes('data-mode')).toBe('open')
  })
})
