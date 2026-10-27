import { describe, it, expect, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: {} }))

import { GovernanceApi } from './governance'

/**
 * §MEMBERSHIP (2026-10-02, plan § 2.4) — a vote in member mode. Every answer a member can act on comes back as a value
 * (cast, step-up, not a member, no second factor, already voted); anything else still throws, so an old registry's
 * lock-mode refusal ("Only agents with locked units can vote") is never mistaken for one of them.
 */
function refused(status: number, data: unknown) {
  return Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data } })
}
function apiWith(post: ReturnType<typeof vi.fn>) {
  return new GovernanceApi({ post } as any)
}

describe('castMemberVote', () => {
  it('an agent without gov.vote (the IRONKEY 403) is its own outcome, not "not a member"; control: another missing permission still throws', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(refused(403, { detail: 'Agent lacks required permission: gov.vote', status: 403 }))
      .mockRejectedValueOnce(refused(403, { detail: 'Agent lacks required permission: teg.transfer', status: 403 }))
    const api = apiWith(post)
    expect(await api.castMemberVote({ proposalId: '7', choice: 'for' }))
      .toEqual({ kind: 'needs_permission', permission: 'gov.vote', message: 'Agent lacks required permission: gov.vote' })
    await expect(api.castMemberVote({ proposalId: '7', choice: 'for' })).rejects.toThrow('403')
  })

  it('casts, sends only the fields it was given, and asks for no global toast on the member answers', async () => {
    const post = vi.fn().mockResolvedValue({ data: { id: 41, voting_power: 137 } })
    const out = await apiWith(post).castMemberVote({ proposalId: '7', choice: 'for' })
    expect(out).toEqual({ kind: 'cast', voteId: '41', votingPower: 137 })
    const [url, body, cfg] = post.mock.calls[0]
    expect(url).toBe('/governance/proposals/7/vote')
    expect(body).toEqual({ vote_in_favor: true, reason: null })
    expect(cfg).toEqual({ expectedStatuses: [428, 403, 409] })
  })

  it('sends the proof on the second call: a challenge id or a one-time code', async () => {
    const post = vi.fn().mockResolvedValue({ data: { id: 42 } })
    await apiWith(post).castMemberVote({ proposalId: '7', choice: 'against', challengeId: 'ch_1' })
    await apiWith(post).castMemberVote({ proposalId: '7', choice: 'against', totpCode: '123456' })
    expect(post.mock.calls[0][1]).toEqual({ vote_in_favor: false, reason: null, challenge_id: 'ch_1' })
    expect(post.mock.calls[1][1]).toEqual({ vote_in_favor: false, reason: null, totp_code: '123456' })
  })

  it('reads a 428 into the step-up challenge', async () => {
    const post = vi.fn().mockRejectedValue(refused(428, {
      error: 'step_up_required', message: 'Confirm on your phone.',
      step_up: { challenge_id: 'ch_9', challenge_hash: 'h', facts: { kind: 'governance.vote' }, methods: ['device'] },
    }))
    const out = await apiWith(post).castMemberVote({ proposalId: '7', choice: 'for' })
    expect(out.kind).toBe('step_up')
    expect(out.kind === 'step_up' && out.stepUp.challengeId).toBe('ch_9')
  })

  it('names the three member refusals', async () => {
    const notMember = await apiWith(vi.fn().mockRejectedValue(refused(403,
      { error: 'not_a_member', missing: ['bond_age'], message: 'Not a member yet.' }))).castMemberVote({ proposalId: '1', choice: 'for' })
    expect(notMember).toEqual({ kind: 'not_member', missing: ['bond_age'], message: 'Not a member yet.' })
    const noFactor = await apiWith(vi.fn().mockRejectedValue(refused(403,
      { error: 'second_factor_required', message: 'Enrol a device first.' }))).castMemberVote({ proposalId: '1', choice: 'for' })
    expect(noFactor).toEqual({ kind: 'second_factor_required', message: 'Enrol a device first.' })
    const twice = await apiWith(vi.fn().mockRejectedValue(refused(409,
      { error: 'developer_already_voted', agent_did: 'did:theprotocol:x' }))).castMemberVote({ proposalId: '1', choice: 'for' })
    expect(twice).toEqual({ kind: 'already_voted', agentDid: 'did:theprotocol:x', message: '' })
  })

  it('control: any other refusal still throws (a lock-mode 403, a 409 of another kind, a 428 without a challenge, a 500)', async () => {
    for (const e of [
      refused(403, { detail: 'Only agents with locked units can vote' }),
      refused(409, { error: 'federation_ballot_pending' }),
      refused(428, { error: 'step_up_required' }),
      refused(500, { detail: 'Failed to cast vote' }),
    ]) {
      await expect(apiWith(vi.fn().mockRejectedValue(e)).castMemberVote({ proposalId: '1', choice: 'for' })).rejects.toBe(e)
    }
  })
})
