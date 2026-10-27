import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * §MCPTEST30 (V0557) — the federal ballot rules the Senate floor follows (agentvault2-33's three: no choice in member
 * mode, the members' vote between an hour and thirty days and 15 minutes short of the host's end, every refusal in its
 * own word) and the names it shows (never the store's 'origin').
 */
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post } }))

import {
  castBallot, castHere, countGate, membersVoteOptions, nextStep, openMembersVote, parseRegistryId, raisedBy, refusalOf,
  registryLabel, spiffeTrustDomain, tallyFederationProposal, fetchProposalBallots,
} from './federationBallots'

const HOSTS = [
  { name: 'Sandbox Beta', trust_domain: 'sandbox-b.theprotocol.cloud' },
  { name: 'Sandbox Alpha', trust_domain: 'sandbox-a.theprotocol.cloud' },
]
const PID = '5f1c0b9e-0000-4000-8000-0000000000aa'

beforeEach(() => { h.get.mockReset(); h.post.mockReset() })

describe('names', () => {
  it('never shows the store\'s "origin": the raiser is the registry its SPIFFE id names', () => {
    const p = { proposer_operator_name: 'origin', origin_registry_id: 'spiffe://sandbox-b.theprotocol.cloud/service/sbx-beta-registry' }
    expect(raisedBy(p, HOSTS)).toBe('Sandbox Beta')
    // a trust domain the open list does not name is shown as itself, never guessed
    expect(raisedBy({ ...p, origin_registry_id: 'spiffe://elsewhere.test/service/x' }, HOSTS)).toBe('elsewhere.test')
    // the control: a real operator name is kept as the store wrote it
    expect(raisedBy({ ...p, proposer_operator_name: 'lisbon' }, HOSTS)).toBe('lisbon')
    expect(raisedBy({ proposer_operator_name: 'unknown', origin_registry_id: '' }, HOSTS)).toBe('unknown')
  })

  it('reads a registry id the way the store writes it, and names it by host where the slug matches', () => {
    expect(parseRegistryId('registry:sandbox-a.theprotocol.cloud/sandbox-alpha'))
      .toEqual({ trustDomain: 'sandbox-a.theprotocol.cloud', slug: 'sandbox-alpha' })
    expect(parseRegistryId('registry:x/With Space')).toBeNull()                 // the store refuses that shape too
    expect(registryLabel('registry:sandbox-a.theprotocol.cloud/sandbox-alpha', HOSTS)).toBe('Sandbox Alpha')
    // an operator shares its frame's trust domain: its own slug, never the frame's name
    expect(registryLabel('registry:sandbox-b.theprotocol.cloud/sbxbetaop', HOSTS)).toBe('sbxbetaop')
    expect(spiffeTrustDomain('SPIFFE://A.Test/x')).toBe('a.test')
  })
})

describe('the next step', () => {
  it('follows the members where there are members, and the operator where there are none', () => {
    expect(nextStep({ status: 'VOTING', hasMembers: true, localVote: null }).kind).toBe('open_members_vote')
    expect(nextStep({ status: 'VOTING', hasMembers: true, localVote: { local_proposal_id: 271, ends_at: 'x', open: true } }))
      .toEqual({ kind: 'members_voting', localProposalId: 271, endsAt: 'x' })
    expect(nextStep({ status: 'VOTING', hasMembers: true, localVote: { local_proposal_id: 271, ends_at: 'x', open: false } }))
      .toEqual({ kind: 'cast_members_result', localProposalId: 271 })
    expect(nextStep({ status: 'VOTING', hasMembers: false }).kind).toBe('operator_choice')
    expect(nextStep({ status: 'VOTING', hasMembers: true, cast: true, castChoice: 'for' })).toEqual({ kind: 'cast', choice: 'for' })
    expect(nextStep({ status: 'PASSED', hasMembers: true }).kind).toBe('closed')
  })

  it('offers no door while who this registry is, whether it cast or whether it has members is unread', () => {
    expect(nextStep({ status: 'VOTING', hasMembers: false, known: false }).kind).toBe('unknown')
    expect(nextStep({ status: 'VOTING', hasMembers: false, known: true, cast: null }).kind).toBe('unknown')
    expect(nextStep({ status: 'VOTING', hasMembers: null, known: true, cast: false }).kind).toBe('unknown')
    // the controls: known, read, and no members
    expect(nextStep({ status: 'VOTING', hasMembers: false, known: true, cast: false }).kind).toBe('operator_choice')
    expect(nextStep({ status: 'VOTING', hasMembers: null, known: true, cast: true, castChoice: 'for' }).kind).toBe('cast')
  })

  it('knows a cast from the full ballots at the host, else from the open list, else does not know', () => {
    const me = 'registry:sandbox-a.theprotocol.cloud/sandbox-alpha'
    expect(castHere(me, null, [{ registry_id: me }])).toBe(true)
    expect(castHere(me, { ballots_cast_by: [] }, null)).toBe(false)
    expect(castHere(me, { ballots_cast_by: [me] }, null)).toBe(true)
    expect(castHere(me, { ballots_cast_by: null }, null)).toBeNull()
  })
})

describe("the members' vote durations", () => {
  const now = Date.parse('2026-10-03T08:00:00Z')
  const eff = (o: { effective: number }[]) => o.map(x => x.effective)
  it('asks an hour to thirty days and shows what the route grants: 15 minutes short of the host end at most', () => {
    const two = membersVoteOptions('2026-10-05T08:00:00Z', now)
    expect(two).toEqual([{ request: 3600, effective: 3600 }, { request: 86400, effective: 86400 },
      { request: 3 * 86400, effective: 2 * 86400 - 900 }])                 // 3 d and 7 d are granted the same: one option
    expect(eff(membersVoteOptions(null, now))).toEqual([3600, 86400, 3 * 86400, 7 * 86400])
  })
  it('offers a capped vote shorter than an hour, and nothing when 30 minutes or less would remain', () => {
    expect(membersVoteOptions('2026-10-03T09:00:00Z', now)).toEqual([{ request: 3600, effective: 2700 }])
    expect(membersVoteOptions('2026-10-03T09:15:00Z', now)).toEqual([{ request: 3600, effective: 3600 }])
    expect(membersVoteOptions('2026-10-03T08:45:00Z', now)).toEqual([])       // too_late at the route
  })
})

describe('the count', () => {
  const now = Date.parse('2026-10-03T08:00:00Z')
  it('opens when every eligible registry has cast, or when the vote has ended, and never on a guess', () => {
    expect(countGate({ eligibleIds: ['a', 'b'], castIds: ['a'], endIso: '2026-10-05T08:00:00Z', nowMs: now }))
      .toEqual({ open: false, reason: 'waiting', cast: 1, eligible: 2 })
    expect(countGate({ eligibleIds: ['a', 'b'], castIds: ['b', 'a'], endIso: '2026-10-05T08:00:00Z', nowMs: now }).reason).toBe('all_cast')
    expect(countGate({ eligibleIds: null, castIds: ['a'], endIso: '2026-10-05T08:00:00Z', nowMs: now }).open).toBe(false)
    expect(countGate({ eligibleIds: [], castIds: [], endIso: '2026-10-05T08:00:00Z', nowMs: now }).open).toBe(false)
    expect(countGate({ eligibleIds: null, castIds: [], endIso: '2026-10-03T07:59:00Z', nowMs: now }).reason).toBe('ended')
  })
})

describe('the calls', () => {
  it('never sends a choice it was not given, and sends the operator\'s when it is', async () => {
    h.post.mockResolvedValue({ data: { recorded: true, choice: 'for' } })
    await castBallot('Sandbox Beta', PID, null)
    expect(h.post).toHaveBeenLastCalledWith('/admin/federation/ballots', { host: 'Sandbox Beta', proposal_id: PID })
    await castBallot('self', PID, 'against')
    expect(h.post).toHaveBeenLastCalledWith('/admin/federation/ballots', { host: 'self', proposal_id: PID, choice: 'against' })
    await openMembersVote('Sandbox Beta', PID, 3600)
    expect(h.post).toHaveBeenLastCalledWith('/admin/federation/ballots/local-vote', { host: 'Sandbox Beta', proposal_id: PID, duration_seconds: 3600 })
    await tallyFederationProposal(PID)
    expect(h.post).toHaveBeenLastCalledWith(`/governance/federation/proposals/${PID}/tally`, {})
    h.get.mockResolvedValue({ data: { ballots: [] } })
    await fetchProposalBallots(PID)
    expect(h.get).toHaveBeenLastCalledWith(`/governance/federation/proposals/${PID}/ballots`)
  })

  it('keeps a refusal\'s own word and its extras, and says nothing when the answer had no word', () => {
    const e = { response: { status: 409, data: { error: 'local_vote_open', message: 'still open', local_proposal_id: 271, ends_at: 'z' } } }
    expect(refusalOf(e)).toEqual({ error: 'local_vote_open', message: 'still open', status: 409,
      extra: { local_proposal_id: 271, ends_at: 'z' } })
    expect(refusalOf({ response: { status: 500, data: { detail: 'boom' } } })).toBeNull()
    expect(refusalOf(new Error('network'))).toBeNull()
  })
})
