import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §MCPTEST30 (V0557) — one federation proposal as the registries decide it. At its host the panel lists every ballot
 * whole (the rows 0f's browser pass holds to the routes: data-testid fed-ballot, data-registry, data-choice); anywhere
 * it shows this registry's next step; in member mode the cast NEVER carries a choice; a refusal shows its own word.
 */
const h = vi.hoisted(() => ({
  fetchProposalBallots: vi.fn(), openMembersVote: vi.fn(), castBallot: vi.fn(), tallyFederationProposal: vi.fn(),
  fetchBallotEligibility: vi.fn(),
  ui: { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() },
}))
vi.mock('@/services/governance/federationBallots', async (orig) => ({
  ...(await orig<typeof import('@/services/governance/federationBallots')>()),
  fetchProposalBallots: h.fetchProposalBallots, openMembersVote: h.openMembersVote, castBallot: h.castBallot,
  tallyFederationProposal: h.tallyFederationProposal, fetchBallotEligibility: h.fetchBallotEligibility,
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))

import FederationBallotPanel from './FederationBallotPanel.vue'

const PID = '5f1c0b9e-0000-4000-8000-0000000000aa'
const ALPHA = 'registry:sandbox-a.theprotocol.cloud/sandbox-alpha'
const BETA = 'registry:sandbox-b.theprotocol.cloud/sandbox-beta'
const HOSTS = [{ name: 'Sandbox Beta', trust_domain: 'sandbox-b.theprotocol.cloud' },
  { name: 'Sandbox Alpha', trust_domain: 'sandbox-a.theprotocol.cloud' }]
const FORBIDDEN = /\b(yield|apy|dividends?|shares?|returns?|investments?|rewards?|interest|stake|staking)\b/i
const LATER = new Date(Date.now() + 2 * 86_400_000).toISOString()

function ballot(registry_id: string, choice: string, basis: Record<string, unknown>) {
  return { registry_id, choice, basis, eligibility: { licence_ok: true, licence_state: 'genesis', track_ok: false,
    reasons: ['a provisional track record (observed, not enforced)'] },
    cast_at: '2026-10-03T10:40:00+00:00', verified_at_receipt: true,
    envelope: { ballot: { choice }, alg: 'EdDSA', kid: `spiffe://x/registry/${choice}#1`, signature: 'c2ln' } }
}

function mountPanel(props: Record<string, unknown>) {
  return mount(FederationBallotPanel, { props: { proposalId: PID, status: 'VOTING', endTimestamp: LATER, summary: null,
    hostKey: 'self', hostName: 'Sandbox Beta', hosted: true, open: null, hosts: HOSTS, myRegistryId: BETA,
    isAdmin: true, hasMembers: false, ...props } })
}

beforeEach(() => {
  for (const f of [h.fetchProposalBallots, h.openMembersVote, h.castBallot, h.tallyFederationProposal, h.fetchBallotEligibility]) f.mockReset()
  h.fetchBallotEligibility.mockResolvedValue({ rule: 'observe', registries: [] })
  for (const f of Object.values(h.ui)) f.mockReset()
})

describe('FederationBallotPanel', () => {
  it('lists every ballot at the host, whole, by registry name, with its basis and the key that signed it', async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballot_summary: null, ballots: [
      ballot(ALPHA, 'for', { mode: 'members', voters: 2, points_for: 108, points_against: 100, local_proposal_id: 271 }),
      ballot(BETA, 'against', { mode: 'operator' })] })
    const w = mountPanel({})
    await flushPromises()
    const rows = w.findAll('[data-testid="fed-ballot"]')
    expect(rows.map(r => [r.attributes('data-registry'), r.attributes('data-choice')])).toEqual([[ALPHA, 'for'], [BETA, 'against']])
    expect(rows[0].text()).toContain('Sandbox Alpha')
    expect(rows[0].text()).toContain('#271')
    expect(rows[0].text()).toContain('1.08')                     // points read as weights, never "108 votes"
    expect(rows[0].text()).toContain('spiffe://x/registry/for#1')
    expect(rows[1].text()).toContain("operator's choice")
    // the track record in the host's own words, never a claim about a rule the panel did not read
    expect(rows[0].text()).toContain('a provisional track record (observed, not enforced)')
    expect(w.find('[data-testid="fed-ballot-summary"]').attributes('data-cast')).toBe('2')
    // this registry has cast: no door to cast again
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('cast')
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it("a decided proposal shows the count and its three conditions, and no step of this registry's", async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'PASSED', ballots: [], ballot_summary: { status: 'PASSED', for: 2,
      against: 0, abstain: 0, cast: 2, eligible: 3, two_thirds_met: true, participation_met: true, multi_registry_met: true } })
    const w = mountPanel({ status: 'PASSED' })
    await flushPromises()
    const sum = w.find('[data-testid="fed-ballot-summary"]')
    expect(sum.attributes('data-status')).toBe('PASSED')
    expect(sum.text()).toContain('2 of 3 eligible registries cast')
    expect(w.findAll('[data-testid="fed-ballot-cond"]').map(c => c.classes().includes('fbp-cond--met'))).toEqual([true, true, true])
    expect(w.find('[data-testid="fed-ballot-mine"]').exists()).toBe(false)
    expect(w.find('[data-testid="fed-ballot-tally"]').exists()).toBe(false)
  })

  it('in member mode the cast carries NO choice, even with the select left at "against"', async () => {
    const w = mountPanel({ hosted: false, hostKey: 'Sandbox Beta', myRegistryId: ALPHA, hasMembers: true,
      open: { id: PID, ballots_cast_by: [BETA], local_vote: { local_proposal_id: 271, ends_at: '2026-10-03T10:30:00Z', open: false } } })
    await flushPromises()
    expect(h.fetchProposalBallots).not.toHaveBeenCalled()      // a peer's proposal: only its host reads it whole
    expect(w.find('[data-testid="fed-ballot-choice"]').exists()).toBe(false)
    h.castBallot.mockResolvedValue({ recorded: true, choice: 'for' })
    await w.find('[data-testid="fed-ballot-cast"]').trigger('click')
    await flushPromises()
    expect(h.castBallot).toHaveBeenCalledWith('Sandbox Beta', PID, null)
    expect(w.emitted('changed')).toBeTruthy()
    // the page remembers its own cast: a stale open list (cached per worker) must not offer the door again
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('cast')
    expect(w.find('[data-testid="fed-ballot-mine"]').text()).toContain('for')
    expect(w.find('[data-testid="fed-ballot-cast"]').exists()).toBe(false)
  })

  it("opens the members' vote for the chosen length, and sends to the open vote while it runs", async () => {
    const w = mountPanel({ hosted: false, hostKey: 'Sandbox Beta', myRegistryId: ALPHA, hasMembers: true,
      open: { id: PID, ballots_cast_by: [], local_vote: null } })
    await flushPromises()
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('open_members_vote')
    h.openMembersVote.mockResolvedValue({ local_proposal_id: 272, ends_at: 'x' })
    await w.find('[data-testid="fed-ballot-duration"]').setValue('3600')
    await w.find('[data-testid="fed-ballot-open-vote"]').trigger('click')
    await flushPromises()
    expect(h.openMembersVote).toHaveBeenCalledWith('Sandbox Beta', PID, 3600)

    const v = mountPanel({ hosted: false, hostKey: 'Sandbox Beta', myRegistryId: ALPHA, hasMembers: true,
      open: { id: PID, ballots_cast_by: [], local_vote: { local_proposal_id: 272, ends_at: '2026-10-03T10:30:00Z', open: true } } })
    await flushPromises()
    await v.find('[data-testid="fed-ballot-goto-vote"]').trigger('click')
    expect(v.emitted('open-local')?.[0]).toEqual([272])
    expect(v.find('[data-testid="fed-ballot-cast"]').exists()).toBe(false)   // nothing to cast while the members vote
  })

  it("without members the operator's choice is the ballot; a refusal shows its own word", async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballots: [], ballot_summary: null })
    const w = mountPanel({})
    await flushPromises()
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('operator_choice')
    await w.find('[data-testid="fed-ballot-choice"]').setValue('against')
    h.castBallot.mockRejectedValue({ response: { status: 403, data: { error: 'not_eligible',
      message: 'this registry may not cast a ballot here now.', reasons: ['no passing licence'] } } })
    await w.find('[data-testid="fed-ballot-cast"]').trigger('click')
    await flushPromises()
    expect(h.castBallot).toHaveBeenCalledWith('self', PID, 'against')
    const r = w.find('[data-testid="fed-ballot-refusal"]')
    expect(r.attributes('data-error')).toBe('not_eligible')
    expect(r.text()).toContain('no passing licence')
    expect(h.ui.showError).toHaveBeenCalled()
  })

  it('the count is final, so it opens only once every eligible registry has cast, and asks first', async () => {
    const ELIG = { rule: 'observe', registries: [{ id: ALPHA, eligible: true }, { id: BETA, eligible: true },
      { id: 'registry:sandbox-b.theprotocol.cloud/sbxbetaop', eligible: true }, { id: 'registry:x/refused', eligible: false }] }
    h.fetchBallotEligibility.mockResolvedValue(ELIG)
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballot_summary: null, ballots: [
      ballot(ALPHA, 'for', { mode: 'members', voters: 1, points_for: 108, points_against: 0, local_proposal_id: 271 }),
      ballot(BETA, 'for', { mode: 'operator' })] })
    const w = mountPanel({})
    await flushPromises()
    expect(w.find('[data-testid="fed-ballot-count"]').attributes('data-gate')).toBe('waiting')
    expect(w.find('[data-testid="fed-ballot-tally"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="fed-ballot-count"]').text()).toContain('2 of 3 eligible registries have cast')

    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballot_summary: null, ballots: [
      ballot(ALPHA, 'for', { mode: 'members' }), ballot(BETA, 'for', { mode: 'operator' }),
      ballot('registry:sandbox-b.theprotocol.cloud/sbxbetaop', 'abstain', { mode: 'operator' })] })
    const v = mountPanel({})
    await flushPromises()
    expect(v.find('[data-testid="fed-ballot-count"]').attributes('data-gate')).toBe('all_cast')
    await v.find('[data-testid="fed-ballot-tally"]').trigger('click')
    expect(h.tallyFederationProposal).not.toHaveBeenCalled()          // one press only asks
    expect(v.text()).toContain('Counting is final')
    h.tallyFederationProposal.mockResolvedValue({ status: 'PASSED' })
    await v.find('[data-testid="fed-ballot-tally-confirm"]').trigger('click')
    await flushPromises()
    expect(h.tallyFederationProposal).toHaveBeenCalledTimes(1)
  })

  it('a cold arrival offers no door: no registry id yet, or no membership answer yet', async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballots: [], ballot_summary: null })
    const w = mountPanel({ myRegistryId: '' })
    await flushPromises()
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('unknown')
    expect(w.find('[data-testid="fed-ballot-cast"]').exists()).toBe(false)
    const v = mountPanel({ hosted: false, hostKey: 'Sandbox Beta', myRegistryId: ALPHA, hasMembers: null,
      open: { id: PID, ballots_cast_by: [], local_vote: null } })
    await flushPromises()
    expect(v.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('unknown')
    expect(v.find('[data-testid="fed-ballot-choice"]').exists()).toBe(false)
  })

  it('one ballot is one ballot, and two are ballots (V0560: the panel said "1 ballots")', async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballot_summary: null, ballots: [
      ballot(ALPHA, 'for', { mode: 'members', voters: 1, points_for: 108, points_against: 0, local_proposal_id: 271 })] })
    const one = mountPanel({})
    await flushPromises()
    expect(one.get('[data-testid="fed-ballot-summary"]').text()).toContain('1 ballot cast so far at Sandbox Beta.')
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballot_summary: null, ballots: [
      ballot(ALPHA, 'for', { mode: 'members', voters: 1, points_for: 108, points_against: 0, local_proposal_id: 271 }),
      ballot(BETA, 'for', { mode: 'operator' })] })
    const two = mountPanel({})
    await flushPromises()
    expect(two.get('[data-testid="fed-ballot-summary"]').text()).toContain('2 ballots cast so far at Sandbox Beta.')
  })

  it('only an admin sees the doors; everyone sees the step', async () => {
    h.fetchProposalBallots.mockResolvedValue({ status: 'VOTING', ballots: [], ballot_summary: null })
    const w = mountPanel({ isAdmin: false })
    await flushPromises()
    expect(w.find('[data-testid="fed-ballot-mine"]').attributes('data-step')).toBe('operator_choice')
    expect(w.find('[data-testid="fed-ballot-cast"]').exists()).toBe(false)
    expect(w.find('[data-testid="fed-ballot-tally"]').exists()).toBe(false)
  })
})
