import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { governanceApi } from '@/services'
import type { Proposal, Vote, VotingPowerBreakdown, LockOptions } from '@/services/api/governance'
import type { MemberVoteOutcome } from '@/services/api/governance'

export const useGovernanceStore = defineStore('governance', () => {
  // State
  const proposals = ref<Proposal[]>([])
  // §FESUITE (the failing-reads census): the proposals' last read failed (the floor then says so, never "none")
  const proposalsFailed = ref(false)
  const currentProposal = ref<Proposal | null>(null)
  const myVotes = ref<Vote[]>([])
  const proposalVotes = ref<Vote[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  // Filters
  const statusFilter = ref<string>('')
  const typeFilter = ref<string>('')
  
  // P3/D2: veToken voting power state
  const myVotingPower = ref<string>('0')
  const canVote = ref(false)
  const powerPositions = ref<VotingPowerBreakdown['positions']>([])
  const decayTimeline = ref<VotingPowerBreakdown['decayTimeline']>([])
  const delegatedFrom = ref<string[]>([])
  const delegatedTo = ref<string | null>(null)
  
  // P3/D2: Lock options
  const lockOptions = ref<LockOptions | null>(null)
  
  // P3/D2: Per-proposal vote tracking
  const myVotesByProposal = ref<Record<string, { choice: string; votingPower: number; reason?: string }>>({})
  
  // Stats
  const totalProposals = ref(0)
  const activeProposals = ref(0)
  const totalVoters = ref(0)
  const totalVotingPower = ref<string>('0')
  const networkVePower = ref<string>('0')
  const participationRate = ref(0)
  
  // Pagination
  const currentPage = ref(1)
  const pageSize = ref(20)
  const totalItems = ref(0)
  
  // Computed
  const filteredProposals = computed(() => {
    let filtered = proposals.value
    
    if (statusFilter.value) {
      filtered = filtered.filter(p => p.status === statusFilter.value)
    }
    
    if (typeFilter.value) {
      filtered = filtered.filter(p => p.proposalType === typeFilter.value)
    }
    
    return filtered
  })
  
  const activeProposalsList = computed(() => 
    proposals.value.filter(p => p.status === 'voting' || p.status === 'active')
  )
  
  const hasVotingPower = computed(() => 
    parseFloat(myVotingPower.value) > 0
  )
  
  const proposalTypes = computed(() => {
    const types = new Set(proposals.value.map(p => p.proposalType))
    return Array.from(types)
  })
  
  // Actions
  async function fetchProposals(page = 1) {
    loading.value = true
    error.value = null
    
    try {
      const response = await governanceApi.getProposals({
        status: statusFilter.value,
        type: typeFilter.value,
        page,
        limit: pageSize.value,
        include_closed: true
      })
      
      proposals.value = response.proposals
      totalItems.value = response.total
      currentPage.value = page
      proposalsFailed.value = false
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch proposals'
      proposalsFailed.value = true
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchProposalById(proposalId: string) {
    loading.value = true
    error.value = null
    
    try {
      const proposal = await governanceApi.getProposal(proposalId)
      currentProposal.value = proposal
      
      // Update in list if exists
      const index = proposals.value.findIndex(p => p.id === proposalId)
      if (index !== -1) {
        proposals.value[index] = proposal
      }
      
      return proposal
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch proposal'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function createProposal(params: {
    title: string
    description: string
    type: string
    duration_seconds?: number
    policy_diff?: any
  }) {
    loading.value = true
    error.value = null
    
    try {
      const result = await governanceApi.createProposal(params)
      
      // Refresh proposals list
      await fetchProposals(1)
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to create proposal'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function vote(proposalId: string, choice: 'for' | 'against', reason?: string) {
    loading.value = true
    error.value = null
    
    try {
      const result = await governanceApi.vote({ proposalId, choice, reason })
      
      // Refresh proposal to get updated vote counts
      await fetchProposalById(proposalId)
      
      // Track that we voted on this proposal
      myVotesByProposal.value[proposalId] = {
        choice,
        votingPower: parseFloat(myVotingPower.value),
        reason
      }
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to submit vote'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * §MEMBERSHIP (2026-10-02) — a vote where the registry runs member mode (plan § 2.4). The outcome is a value the
   * screen acts on: cast, a step-up to confirm, or one of the member refusals. `extra` carries the proof on the second
   * call. A cast records the vote with the points the server counted (weight x 100); "already voted" records the
   * proposal as voted, with no choice, because another of the member's agents cast it.
   */
  async function voteAsMember(proposalId: string, choice: 'for' | 'against', reason?: string,
                              extra: { totpCode?: string; challengeId?: string } = {}): Promise<MemberVoteOutcome> {
    loading.value = true
    error.value = null
    try {
      const out = await governanceApi.castMemberVote({ proposalId, choice, reason, ...extra })
      if (out.kind === 'cast') {
        await fetchProposalById(proposalId)
        myVotesByProposal.value[proposalId] = { choice, votingPower: out.votingPower ?? 0, reason }
      } else if (out.kind === 'already_voted') {
        myVotesByProposal.value[proposalId] = { choice: '', votingPower: 0 }
      }
      return out
    } catch (err: any) {
      error.value = err.message || 'Failed to submit vote'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function tallyProposal(proposalId: string) {
    loading.value = true
    error.value = null
    
    try {
      const result = await governanceApi.tallyProposal(proposalId)
      
      // Refresh proposal to get updated status
      await fetchProposalById(proposalId)
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to tally proposal'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchProposalVotes(proposalId: string, page = 1) {
    loading.value = true
    error.value = null
    
    try {
      const response = await governanceApi.getVotes(proposalId, {
        page,
        limit: pageSize.value
      })
      
      proposalVotes.value = response.votes
      return response
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch votes'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function checkMyVote(proposalId: string) {
    try {
      const result = await governanceApi.getMyVoteOnProposal(proposalId)
      if (result.hasVoted && result.vote) {
        myVotesByProposal.value[proposalId] = {
          choice: result.vote.choice,
          votingPower: result.vote.votingPower,
          reason: result.vote.reason
        }
      }
      return result
    } catch {
      return { hasVoted: false, vote: null }
    }
  }
  
  async function fetchVotingPower() {
    loading.value = true
    error.value = null
    
    try {
      const data = await governanceApi.getVotingPower()
      
      myVotingPower.value = data.votingPower
      canVote.value = data.canVote
      powerPositions.value = data.positions
      decayTimeline.value = data.decayTimeline
      delegatedFrom.value = data.delegatedFrom
      delegatedTo.value = data.delegatedTo || null
      
      return data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch voting power'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchLockOptions() {
    try {
      lockOptions.value = await governanceApi.getLockOptions()
      return lockOptions.value
    } catch (err: any) {
      console.error('Failed to fetch lock options:', err)
      return null
    }
  }
  
  async function fetchStats() {
    loading.value = true
    error.value = null
    
    try {
      const stats = await governanceApi.getStats()
      totalProposals.value = stats.totalProposals
      activeProposals.value = stats.activeProposals
      totalVoters.value = stats.totalVoters
      totalVotingPower.value = stats.totalVotingPower
      networkVePower.value = stats.networkVePower
      participationRate.value = stats.participationRate
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch governance stats'
    } finally {
      loading.value = false
    }
  }
  
  function hasVoted(proposalId: string): boolean {
    return !!myVotesByProposal.value[proposalId]
  }
  
  function getMyVote(proposalId: string) {
    return myVotesByProposal.value[proposalId] || null
  }
  
  function setStatusFilter(status: string) {
    statusFilter.value = status
    currentPage.value = 1
  }
  
  function setTypeFilter(type: string) {
    typeFilter.value = type
    currentPage.value = 1
  }
  
  function clearError() {
    error.value = null
  }
  
  function reset() {
    proposals.value = []
    proposalsFailed.value = false
    currentProposal.value = null
    myVotes.value = []
    proposalVotes.value = []
    loading.value = false
    error.value = null
    statusFilter.value = ''
    typeFilter.value = ''
    myVotingPower.value = '0'
    canVote.value = false
    powerPositions.value = []
    decayTimeline.value = []
    delegatedFrom.value = []
    delegatedTo.value = null
    lockOptions.value = null
    myVotesByProposal.value = {}
    totalProposals.value = 0
    activeProposals.value = 0
    totalVoters.value = 0
    totalVotingPower.value = '0'
    networkVePower.value = '0'
    participationRate.value = 0
    currentPage.value = 1
    totalItems.value = 0
  }
  
  return {
    // State
    proposals,
    currentProposal,
    myVotes,
    proposalVotes,
    loading,
    error,
    statusFilter,
    typeFilter,
    myVotingPower,
    canVote,
    powerPositions,
    decayTimeline,
    delegatedFrom,
    delegatedTo,
    lockOptions,
    myVotesByProposal,
    totalProposals,
    activeProposals,
    totalVoters,
    totalVotingPower,
    networkVePower,
    participationRate,
    currentPage,
    pageSize,
    totalItems,
    
    // Computed
    filteredProposals,
    activeProposalsList,
    hasVotingPower,
    proposalTypes,
    
    // Actions
    fetchProposals,
    proposalsFailed,
    fetchProposalById,
    createProposal,
    vote,
    voteAsMember,
    tallyProposal,
    fetchProposalVotes,
    checkMyVote,
    fetchVotingPower,
    fetchLockOptions,
    fetchStats,
    hasVoted,
    getMyVote,
    setStatusFilter,
    setTypeFilter,
    clearError,
    reset
  }
})
