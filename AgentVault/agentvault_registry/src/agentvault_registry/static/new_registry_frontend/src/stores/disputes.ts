// Dispute Management Store — OWL-17 patch
import { defineStore } from 'pinia'
import { disputesApi, type Dispute, type Evidence, type CreateDisputeData, type SubmitEvidenceData, type DisputeStats, type CompensationResult } from '@/services/api/disputes'
import { useUIStore } from './ui'
import { useAuthStore } from './auth'

interface DisputesState {
  disputes: Dispute[]
  selectedDispute: Dispute | null
  stats: DisputeStats
  /** §FESUITE (the loading sweep): the stats answered at least once; until then the tiles show a dash, not 0. */
  statsRead: boolean
  /** §FESUITE (the failing-reads census): the list's last read failed; with nothing read the page says so, never "none". */
  listFailed: boolean
  /** the list answered at least once (a 404 is the server's "none"): only then may the page say there are none */
  listRead: boolean
  loading: boolean
  statusFilter: string
  searchQuery: string
}

/** §FESUITE — the server's sentence for a refusal (an axios error's own message is only "status code 4xx"). */
function why(error: any): string {
  const d = error?.response?.data
  const detail = d?.detail ?? d?.error?.detail
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') return JSON.stringify(detail).slice(0, 300)
  return error?.message || 'Request failed'
}

export const useDisputesStore = defineStore('disputes', {
  state: (): DisputesState => ({
    disputes: [],
    selectedDispute: null,
    stats: {
      total_disputes: 0,
      open_disputes: 0,
      resolved_disputes: 0,
      resolution_rate: 0,
      average_resolution_time: 0
    },
    statsRead: false,
    listFailed: false,
    listRead: false,
    loading: false,
    statusFilter: 'all',
    searchQuery: ''
  }),

  getters: {
    filteredDisputes: (state): Dispute[] => {
      let filtered = [...state.disputes]

      if (state.statusFilter !== 'all') {
        filtered = filtered.filter(d => d.status === state.statusFilter)
      }

      if (state.searchQuery) {
        const query = state.searchQuery.toLowerCase()
        filtered = filtered.filter(d =>
          d.reason.toLowerCase().includes(query) ||
          d.description.toLowerCase().includes(query) ||
          d.id.toLowerCase().includes(query) ||
          d.claimant_did.toLowerCase().includes(query) ||
          d.respondent_did.toLowerCase().includes(query)
        )
      }

      return filtered.sort((a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
    },

    myDisputes: (state): Dispute[] => {
      const authStore = useAuthStore()
      const myDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did
      if (!myDid) return []
      return state.disputes.filter(d =>
        d.claimant_did === myDid || d.respondent_did === myDid
      )
    },

    openDisputes: (state): Dispute[] => {
      return state.disputes.filter(d =>
        d.status === 'open' || d.status === 'investigating'
      )
    }
  },

  actions: {
    async fetchDisputes() {
      this.loading = true
      const uiStore = useUIStore()
      try {
        // §COCKPITDESK (2026-10-15): the list and the tiles from one set of reads (every page the counter reads)
        const { rows, stats } = await disputesApi.readAll()
        this.disputes = rows
        this.listFailed = false
        this.listRead = true
        this.stats = stats
        this.statsRead = true
      } catch (error: any) {
        console.error('Failed to fetch disputes:', error)
        // a 404 is the server's own "none"; any other failure read nothing
        this.listFailed = error.response?.status !== 404
        if (error.response?.status === 404) this.listRead = true
        if (error.response?.status !== 404) {
          uiStore.showError('Failed to load disputes', why(error))
        }
      } finally {
        this.loading = false
      }
    },

    async fetchMyDisputes() {
      const authStore = useAuthStore()
      const myDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did
      if (!myDid) return

      try {
        const disputes = await disputesApi.getAgentDisputes(myDid)
        const existingIds = new Set(this.disputes.map(d => d.id))
        const newDisputes = disputes.filter(d => !existingIds.has(d.id))
        this.disputes = [...this.disputes, ...newDisputes]
      } catch (error: any) {
        console.error('Failed to fetch my disputes:', error)
      }
    },

    async fetchDispute(disputeId: string) {
      const uiStore = useUIStore()
      try {
        const dispute = await disputesApi.getDispute(disputeId)
        const index = this.disputes.findIndex(d => d.id === disputeId)
        if (index >= 0) {
          this.disputes[index] = dispute
        } else {
          this.disputes.push(dispute)
        }
        this.selectedDispute = dispute
        return dispute
      } catch (error: any) {
        uiStore.showError('Failed to load dispute details', why(error))
        throw error
      }
    },

    // OWL-17 FIX: inject complainant_did from activeAgent
    async createDispute(data: CreateDisputeData) {
      this.loading = true
      const uiStore = useUIStore()
      const authStore = useAuthStore()

      const complainantDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
      if (!complainantDid) {
        uiStore.showError('No active agent', 'Select an agent before filing a dispute.')
        this.loading = false
        return
      }

      try {
        const dispute = await disputesApi.createDispute({ ...data, complainant_did: complainantDid })
        this.disputes.unshift(dispute)
        this.stats.total_disputes++
        this.stats.open_disputes++
        uiStore.showSuccess('Dispute Filed', 'Your dispute has been submitted for review.')
        return dispute
      } catch (error: any) {
        console.error('Failed to create dispute:', error)
        uiStore.showError('Failed to file dispute', why(error))
        throw error
      } finally {
        this.loading = false
      }
    },

    async submitEvidence(disputeId: string, data: SubmitEvidenceData) {
      const uiStore = useUIStore()
      try {
        const evidence = await disputesApi.submitEvidence(disputeId, data)
        const dispute = this.disputes.find(d => d.id === disputeId)
        if (dispute) dispute.evidence.push(evidence)
        if (this.selectedDispute?.id === disputeId) this.selectedDispute.evidence.push(evidence)
        uiStore.showSuccess('Evidence Submitted', 'Your evidence has been added to the dispute.')
        return evidence
      } catch (error: any) {
        uiStore.showError('Failed to submit evidence', why(error))
        throw error
      }
    },

    async updateRuling(disputeId: string, ruling: string, resolution: 'resolved' | 'dismissed') {
      const uiStore = useUIStore()
      try {
        const result = await disputesApi.updateRuling(disputeId, ruling, resolution)
        const dispute = result.dispute
        if (result.compensation) (dispute as any).compensation = result.compensation
        if (result.reputation_changes) (dispute as any).reputation_changes = result.reputation_changes

        const index = this.disputes.findIndex(d => d.id === disputeId)
        if (index >= 0) this.disputes[index] = dispute
        if (this.selectedDispute?.id === disputeId) this.selectedDispute = dispute

        this.stats.open_disputes = Math.max(0, this.stats.open_disputes - 1)
        if (resolution === 'resolved') this.stats.resolved_disputes++
        else this.stats.dismissed_disputes = (this.stats.dismissed_disputes ?? 0) + 1
        this.stats.decided_disputes = (this.stats.decided_disputes ?? 0) + 1

        let msg = `Dispute ${resolution}`
        if (result.compensation?.applied) {
          msg += result.compensation.partial
            ? ` — ${result.compensation.amount} of ${result.compensation.amount_requested} transferred`
            : ` — ${result.compensation.amount} compensation transferred`
        }
        uiStore.showSuccess('Ruling Applied', msg)
        return { dispute, compensation: result.compensation, reputation_changes: result.reputation_changes }
      } catch (error: any) {
        uiStore.showError('Failed to apply ruling', why(error))
        throw error
      }
    },

    async fetchStats() {
      try {
        const stats = await disputesApi.getStats()
        this.stats = stats
        this.statsRead = true
      } catch (error) {
        console.error('Failed to fetch dispute stats:', error)
      }
    },

    setStatusFilter(status: string) { this.statusFilter = status },
    setSearchQuery(query: string)   { this.searchQuery = query },
    clearFilters() { this.statusFilter = 'all'; this.searchQuery = '' },
    selectDispute(dispute: Dispute | null) { this.selectedDispute = dispute }
  }
})
