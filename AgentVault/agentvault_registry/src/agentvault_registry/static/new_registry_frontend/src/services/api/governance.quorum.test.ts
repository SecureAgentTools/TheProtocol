import { describe, it, expect, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: {} }))

import { GovernanceApi } from './governance'

/**
 * §BATCH0911 item 2b — the proposal mapper must not invent a quorum.
 *
 * A proposal stores the quorum its tally applies (captured from the frame's policy when it was
 * proposed, by type: 10 for an ordinary proposal on EU, 20 for a policy_change). When none is
 * stored, `tally_proposal` applies NO quorum check (`if proposal.quorum_percent and ...`), yet this
 * mapper filled in 10.0 and the Senate Floor drew a line at 10% and printed "(10%)": a literal that
 * matches one frame's ordinary proposals today and describes nothing the tally does.
 */
function apiReturning(rows: unknown[]) {
  const client = { get: vi.fn().mockResolvedValue({ data: rows }) }
  return new GovernanceApi(client as any)
}

describe('the proposal mapper carries the stored quorum and never invents one', () => {
  it('a missing quorum stays missing (null), never 10', async () => {
    const { proposals } = await apiReturning([{ id: 9, title: 't', description: 'd', status: 'VOTING' }]).getProposals()
    expect(proposals[0].quorumPercent).toBeNull()
  })

  it('a null quorum stays null', async () => {
    const { proposals } = await apiReturning([{ id: 9, quorum_percent: null }]).getProposals()
    expect(proposals[0].quorumPercent).toBeNull()
  })

  it('a stored quorum is carried as stored, whatever the frame declares today', async () => {
    const { proposals } = await apiReturning([
      { id: 2, proposal_type: 'policy_change', quorum_percent: 20 },
      { id: 4, proposal_type: 'standard', quorum_percent: 15 },
    ]).getProposals()
    expect(proposals.map(p => p.quorumPercent)).toEqual([20, 15])
  })

  it('a stored zero is a real value, not a missing one', async () => {
    const { proposals } = await apiReturning([{ id: 5, quorum_percent: 0 }]).getProposals()
    expect(proposals[0].quorumPercent).toBe(0)
  })
})

describe('§MEMBERSHIP: the mapper carries the numbers a decided proposal was decided on', () => {
  it('maps the five tally fields as stored, numeric strings included', async () => {
    const { proposals } = await apiReturning([{ id: 7, status: 'FAILED', quorum_percent: 10, tally_weight_mode: 'member',
      tally_network_power: '4928', tally_quorum_required: 492.8, tally_quorum_met: false, tallied_at: '2026-10-02T18:00:00Z' }]).getProposals()
    expect(proposals[0]).toMatchObject({ tallyWeightMode: 'member', tallyNetworkPower: 4928, tallyQuorumRequired: 492.8,
      tallyQuorumMet: false, talliedAt: '2026-10-02T18:00:00Z' })
  })

  it('control: an open proposal (or one tallied before migration 0185) carries none of them, never an invented 0', async () => {
    const { proposals } = await apiReturning([{ id: 8, status: 'VOTING' }, { id: 9, tally_weight_mode: 'veto', tally_quorum_required: 'n/a' }]).getProposals()
    expect(proposals[0]).toMatchObject({ tallyWeightMode: null, tallyNetworkPower: null, tallyQuorumRequired: null, tallyQuorumMet: null, talliedAt: null })
    expect(proposals[1]).toMatchObject({ tallyWeightMode: null, tallyQuorumRequired: null })
  })
})
