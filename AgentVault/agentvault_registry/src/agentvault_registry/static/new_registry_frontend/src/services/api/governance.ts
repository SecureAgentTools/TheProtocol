import type { AxiosInstance } from 'axios'
import { apiClient } from './client'
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'
import { isVotePermissionRefusal, VOTE_PERMISSION } from '@/services/membership/votePermission'

/** §MEMBERSHIP — what a vote in member mode can come back as. Every answer the member can act on is a value, not
 *  a thrown error, so the screen can say what happened and what to do next; anything else still throws. */
export type MemberVoteOutcome =
  | { kind: 'cast'; voteId: string; votingPower: number | null }
  | { kind: 'step_up'; stepUp: StepUpChallenge; message: string }
  | { kind: 'not_member'; missing: string[]; message: string }
  | { kind: 'already_voted'; agentDid: string | null; message: string }
  /** a member without a second factor where the registry requires one (`governance_presence_mode=required`) */
  | { kind: 'second_factor_required'; message: string }
  /** the agent cast the vote without the `gov.vote` permission (IRONKEY): its owner can allow it (services/membership/votePermission) */
  | { kind: 'needs_permission'; permission: string; message: string }

/** A number from the wire (the ledger can send numeric strings), or null: never NaN, never an invented 0. */
function finiteOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return Number.isFinite(n) ? n : null
}

export interface Proposal {
  id: string
  title: string
  description: string
  proposer: string
  status: 'pending' | 'active' | 'voting' | 'passed' | 'failed' | 'rejected' | 'executed'
  proposalType: 'standard' | 'policy_change'
  votingStart: string
  votingEnd: string
  votes: {
    for: string
    against: string
  }
  /** The quorum this proposal's tally applies; null when none is stored (the tally then applies none). */
  quorumPercent: number | null
  passPercent: number
  totalVoters: number
  created: string
  /** §MEMBERSHIP (agentvault2-33, migration 0185): the numbers a DECIDED proposal was decided on, all null for an open
   *  proposal and for one tallied before they were stored. The unit of the two figures is tallyWeightMode's (points
   *  in member mode, veToken power in lock mode): a registry can switch modes later, so the card keys on this. */
  tallyWeightMode?: 'lock' | 'member' | null
  tallyNetworkPower?: number | null
  tallyQuorumRequired?: number | null
  tallyQuorumMet?: boolean | null
  talliedAt?: string | null
  // Backend field aliases / extended fields
  endTime?: string
  proposer_did?: string
  votes_for?: string | number
  votes_against?: string | number
}

export interface Vote {
  id: string
  proposalId: string
  voter: string
  choice: 'for' | 'against'
  weight: string
  reason?: string
  timestamp: string
}

export interface VotingPowerBreakdown {
  votingPower: string
  canVote: boolean
  positions: Array<{
    stake_id: string
    amount: string
    lock_days: number
    remaining_days: number
    ve_power: number
  }>
  decayTimeline: Array<{
    date: string
    power: number
  }>
  delegatedFrom: string[]
  delegatedTo?: string
}

export interface LockOption {
  days: number
  label: string
  power_multiplier: number
}

export interface LockOptions {
  min_lock_days: number
  max_lock_days: number
  t_max_days: number
  flexible_multiplier: number
  tiers: LockOption[]
}

/**
 * Governance API Service
 * P3/D2: Enhanced with veToken voting power, quorum, and policy_change proposals
 */
export class GovernanceApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Transform backend proposal to frontend format
   */
  private transformProposal(p: any): Proposal {
    return {
      id: String(p.id),
      title: p.title,
      description: p.description,
      proposer: p.proposer_did,
      status: p.status?.toLowerCase() || 'active',
      proposalType: p.proposal_type || 'standard',
      votingStart: p.created_at,
      votingEnd: p.end_timestamp,
      votes: {
        for: String(p.votes_for || 0),
        against: String(p.votes_against || 0)
      },
      quorumPercent: p.quorum_percent ?? null,  // §BATCH0911 — never a literal: see governanceQuorum.ts
      passPercent: p.pass_percent || 50.0,
      totalVoters: p.total_voters || 0,
      created: p.created_at,
      tallyWeightMode: p.tally_weight_mode === 'member' || p.tally_weight_mode === 'lock' ? p.tally_weight_mode : null,
      tallyNetworkPower: finiteOrNull(p.tally_network_power),
      tallyQuorumRequired: finiteOrNull(p.tally_quorum_required),
      tallyQuorumMet: typeof p.tally_quorum_met === 'boolean' ? p.tally_quorum_met : null,
      talliedAt: typeof p.tallied_at === 'string' && p.tallied_at ? p.tallied_at : null,
    }
  }

  /**
   * Get all proposals
   */
  async getProposals(params?: {
    status?: string
    type?: string
    page?: number
    limit?: number
    include_closed?: boolean
  }): Promise<{
    proposals: Proposal[]
    total: number
    page: number
    limit: number
  }> {
    const { data } = await this.client.get('/governance/proposals', {
      params: {
        include_closed: params?.include_closed || true,
        limit: params?.limit || 50,
        offset: params?.page ? ((params.page - 1) * (params.limit || 50)) : 0
      }
    })
    
    // Backend returns array directly
    const proposals = Array.isArray(data) ? data : (data.items || [])
    const transformedProposals = proposals.map((p: any) => this.transformProposal(p))
    
    return {
      proposals: transformedProposals,
      total: transformedProposals.length,
      page: params?.page || 1,
      limit: params?.limit || 20
    }
  }

  /**
   * Get a single proposal
   */
  async getProposal(proposalId: string): Promise<Proposal> {
    const { data } = await this.client.get(`/governance/proposals/${proposalId}`)
    return this.transformProposal(data)
  }

  /**
   * Create a new proposal
   */
  async createProposal(params: {
    title: string
    description: string
    type: string
    duration_seconds?: number
    policy_diff?: any
  }): Promise<{
    proposalId: string
    txHash: string
  }> {
    const proposalType = params.type === 'policy_change' ? 'policy_change' : 'standard'
    
    const { data } = await this.client.post('/governance/proposals', {
      title: params.title,
      description: params.description,
      duration_seconds: params.duration_seconds || 7 * 24 * 60 * 60,
      proposal_type: proposalType,
      policy_diff: params.policy_diff || null
    })
    
    return {
      proposalId: String(data.id),
      txHash: ''
    }
  }

  /**
   * Vote on a proposal
   */
  async vote(params: {
    proposalId: string
    choice: 'for' | 'against'
    reason?: string
  }): Promise<{
    voteId: string
    txHash: string
  }> {
    const { proposalId, choice, reason } = params
    
    const { data } = await this.client.post(`/governance/proposals/${proposalId}/vote`, {
      vote_in_favor: choice === 'for',
      reason: reason || null
    })
    
    return {
      voteId: String(data.id),
      txHash: ''
    }
  }

  /**
   * §MEMBERSHIP (plan § 2.4) — a vote where the registry runs `governance_weight_mode=member`. Same route and the
   * same agent token as `vote`; the member is the agent's developer. A binding vote may first answer 428 with a
   * step-up challenge: the caller has it approved (phone or one-time code) and calls again with `challengeId` or
   * `totpCode`. The three member-mode refusals are expected answers (no global toast); the screen names them.
   * Lock mode keeps calling `vote` and is untouched.
   */
  async castMemberVote(params: {
    proposalId: string
    choice: 'for' | 'against'
    reason?: string
    totpCode?: string
    challengeId?: string
  }): Promise<MemberVoteOutcome> {
    const { proposalId, choice, reason, totpCode, challengeId } = params
    const body: Record<string, unknown> = { vote_in_favor: choice === 'for', reason: reason || null }
    if (totpCode) body.totp_code = totpCode
    if (challengeId) body.challenge_id = challengeId
    try {
      const { data } = await this.client.post(`/governance/proposals/${proposalId}/vote`, body,
        { expectedStatuses: [428, 403, 409] })
      const power = Number(data?.voting_power)
      return { kind: 'cast', voteId: String(data?.id ?? ''), votingPower: Number.isFinite(power) ? power : null }
    } catch (e: any) {
      const status = e?.response?.status
      const d = e?.response?.data || {}
      const message = typeof d.message === 'string' ? d.message : ''
      if (status === 428) {
        const stepUp = parseStepUp(d)
        if (stepUp) return { kind: 'step_up', stepUp, message }
      }
      if (status === 403 && d.error === 'not_a_member') {
        return { kind: 'not_member', missing: Array.isArray(d.missing) ? d.missing : [], message }
      }
      if (status === 403 && d.error === 'second_factor_required') {
        return { kind: 'second_factor_required', message }
      }
      if (isVotePermissionRefusal(status, d)) {
        return { kind: 'needs_permission', permission: VOTE_PERMISSION, message: message || String(d.detail || '') }
      }
      if (status === 409 && d.error === 'developer_already_voted') {
        return { kind: 'already_voted', agentDid: typeof d.agent_did === 'string' ? d.agent_did : null, message }
      }
      throw e
    }
  }

  /**
   * Get votes for a proposal
   */
  async getVotes(proposalId: string, params?: {
    page?: number
    limit?: number
  }): Promise<{
    votes: Vote[]
    total: number
    page: number
    limit: number
  }> {
    const { data } = await this.client.get(`/governance/proposals/${proposalId}/votes`, {
      params
    })
    
    const votes: Vote[] = (Array.isArray(data) ? data : []).map((v: any) => ({
      id: String(v.id),
      proposalId: String(v.proposal_id),
      voter: v.voter_did,
      choice: v.vote ? 'for' : 'against',
      weight: String(v.voting_power),
      reason: v.reason,
      timestamp: v.created_at
    }))
    
    return {
      votes,
      total: votes.length,
      page: params?.page || 1,
      limit: params?.limit || 20
    }
  }

  /**
   * Check if current agent has voted on a proposal
   */
  async getMyVoteOnProposal(proposalId: string): Promise<{
    hasVoted: boolean
    vote: { choice: string; votingPower: number; reason?: string } | null
  }> {
    try {
      const { data } = await this.client.get(`/governance/proposals/${proposalId}/my-vote`, {
        // P3/D2: Flag to tell auth interceptor not to trigger logout on 401
        // This is a non-critical check that should fail silently
        _skipLogoutOn401: true
      } as any)
      return {
        hasVoted: data.has_voted,
        vote: data.vote ? {
          choice: data.vote.choice,
          votingPower: data.vote.voting_power,
          reason: data.vote.reason
        } : null
      }
    } catch {
      return { hasVoted: false, vote: null }
    }
  }

  /**
   * Get user's voting history (aggregated from proposal votes)
   */
  async getMyVotes(params?: {
    page?: number
    limit?: number
  }): Promise<{
    votes: Vote[]
    total: number
    page: number
    limit: number
  }> {
    // TODO: Backend doesn't have a dedicated my-votes endpoint yet
    return {
      votes: [],
      total: 0,
      page: params?.page || 1,
      limit: params?.limit || 20
    }
  }

  /**
   * Get veToken voting power with per-position breakdown
   */
  async getVotingPower(address?: string): Promise<VotingPowerBreakdown> {
    try {
      const { data } = await this.client.get('/governance/voting-power')
      
      return {
        votingPower: String(data.votingPower || '0'),
        canVote: data.canVote || false,
        positions: data.positions || [],
        decayTimeline: (data.decay_timeline || []).map((d: any) => ({
          date: d.date,
          power: d.power
        })),
        delegatedFrom: data.delegatedFrom || [],
        delegatedTo: data.delegatedTo
      }
    } catch (error) {
      console.error('Failed to fetch voting power:', error)
      return {
        votingPower: '0',
        canVote: false,
        positions: [],
        decayTimeline: [],
        delegatedFrom: [],
        delegatedTo: undefined
      }
    }
  }

  /**
   * Get lock options with power multipliers
   */
  async getLockOptions(): Promise<LockOptions> {
    try {
      const { data } = await this.client.get('/governance/lock-options')
      return data
    } catch (error) {
      console.error('Failed to fetch lock options:', error)
      return {
        min_lock_days: 0,
        max_lock_days: 365,
        t_max_days: 365,
        flexible_multiplier: 0.01,
        tiers: []
      }
    }
  }

  /**
   * Tally votes for a proposal (proposer only)
   */
  async tallyProposal(proposalId: string): Promise<{
    votes_for: number
    votes_against: number
    total_votes: number
    quorum_met: boolean
    pass_rate: number
    status: string
  }> {
    const { data } = await this.client.post(`/governance/proposals/${proposalId}/tally`)
    return data
  }

  /**
   * Delegate voting power (not yet implemented)
   */
  async delegate(delegateTo: string): Promise<{ txHash: string }> {
    throw new Error('Vote delegation is not currently supported')
  }

  /**
   * Execute a passed proposal (not yet implemented)
   */
  async executeProposal(proposalId: string): Promise<{
    txHash: string
    executed: boolean
  }> {
    throw new Error('Proposal execution is not available via API')
  }

  /**
   * Get governance statistics
   */
  async getStats(): Promise<{
    totalProposals: number
    activeProposals: number
    totalVoters: number
    totalVotingPower: string
    networkVePower: string
    participationRate: number
  }> {
    try {
      const { data } = await this.client.get('/governance/stats')
      
      return {
        totalProposals: data.totalProposals || 0,
        activeProposals: data.activeProposals || 0,
        totalVoters: data.totalVoters || 0,
        totalVotingPower: String(data.totalVotingPower || '0'),
        networkVePower: String(data.networkVePower || '0'),
        participationRate: data.participationRate || 0
      }
    } catch (error) {
      console.error('Failed to fetch governance stats:', error)
      return {
        totalProposals: 0,
        activeProposals: 0,
        totalVoters: 0,
        totalVotingPower: '0',
        networkVePower: '0',
        participationRate: 0
      }
    }
  }
}

// Export singleton instance
export const governanceApi = new GovernanceApi()
