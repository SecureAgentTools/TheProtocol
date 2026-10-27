/**
 * Contracts Store — OWL-16 clean rewrite
 *
 * Uses real backend statuses: PROPOSED | ACCEPTED | PENDING_MERGE | COMPLETED
 * No mock templates. No invented fields. No fake statuses.
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { BackendContract } from '@/services/api/contracts'
import * as contractApi from '@/services/api/contracts'
import { useUIStore } from './ui'
import { isRetiredList } from '@/services/contracts/railRows'

export type ContractStatus = 'PROPOSED' | 'ACCEPTED' | 'PENDING_MERGE' | 'COMPLETED'
export type RoleFilter = 'all' | 'client' | 'upgrader'
export type StatusFilter = 'ALL' | ContractStatus

export { type BackendContract as Contract }

// ─── Stub types for UI-only components (ContractTemplates, ContractTimeline) ──

export interface ContractTemplate {
  id: string
  name: string
  category: string
  description: string
  usage_count: number
  amount: string
  duration_days: number
  repo_url: string
  acceptance_criteria: { requirements: string[] }
}

export interface ContractActivity {
  id: string
  type: string
  timestamp: string
  message: string
  actor_did: string
  actor_name?: string
  metadata?: {
    pr_url?: string
    notes?: string
    rating?: number
    feedback?: string
    reason?: string
    evidence?: string
  }
}

export const useContractStore = defineStore('contracts', () => {
  // ─── State ──────────────────────────────────────────────────────────────────
  const contracts = ref<BackendContract[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  // §TWOAGENT V0442: true when this registry answers the legacy list with a 404 (D8 retired it: EU, ASIA). The page
  // then counts and lists the contract rail instead of reading an empty legacy grid as "no contracts".
  const legacyRetired = ref(false)
  /** §FESUITE (the loading sweep): true once the list has answered (a later failed fetch keeps it, and what was shown). */
  const loaded = ref(false)
  const contractActivities = ref<ContractActivity[]>([])

  // Drawer
  const drawerOpen = ref(false)
  // §BLOGSHOTS-FIX: keyed by ctrRef (legacy int id as string, or the spine ctr_… ref) —
  // every spine-native row serialises id=-1, so a numeric key cannot address them.
  const activeContractId = ref<string | null>(null)

  // Filters
  const statusFilter = ref<StatusFilter>('ALL')
  const roleFilter = ref<RoleFilter>('all')
  const searchQuery = ref('')

  // ─── Getters ─────────────────────────────────────────────────────────────────
  const activeContract = computed(() =>
    contracts.value.find(c => contractApi.ctrRef(c) === activeContractId.value) ?? null
  )

  function getMyRole(contract: BackendContract, agentDid: string): 'client' | 'upgrader' | 'observer' {
    if (contract.client_agent_did === agentDid) return 'client'
    if (contract.upgrader_agent_did === agentDid) return 'upgrader'
    return 'observer'
  }

  const proposed  = computed(() => contracts.value.filter(c => c.status === 'PROPOSED'))
  const accepted  = computed(() => contracts.value.filter(c => c.status === 'ACCEPTED'))
  const pendingMerge = computed(() => contracts.value.filter(c => c.status === 'PENDING_MERGE'))
  const completed = computed(() => contracts.value.filter(c => c.status === 'COMPLETED'))

  const stats = computed(() => {
    const all = contracts.value
    const totalValue = all.reduce((sum, c) => sum + c.payment_amount, 0)
    const completedVal = completed.value.reduce((sum, c) => sum + c.payment_amount, 0)
    const doneCount = completed.value.length
    const total = all.length
    return {
      total,
      proposed: proposed.value.length,
      accepted: accepted.value.length,
      pendingMerge: pendingMerge.value.length,
      completed: doneCount,
      totalValue,
      completedValue: completedVal,
      successRate: total > 0 ? Math.round((doneCount / total) * 100) : 0,
      avgPayment: total > 0 ? Math.round(totalValue / total) : 0
    }
  })

  const filteredContracts = computed(() => {
    let result = [...contracts.value]

    // Status filter
    if (statusFilter.value !== 'ALL') {
      result = result.filter(c => c.status === statusFilter.value)
    }

    // Role filter — needs activeAgent DID
    if (roleFilter.value !== 'all') {
      const { useAuthStore } = require('@/stores/auth')
      const authStore = useAuthStore()
      const myDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
      if (myDid) {
        result = result.filter(c => {
          if (roleFilter.value === 'client') return c.client_agent_did === myDid
          if (roleFilter.value === 'upgrader') return c.upgrader_agent_did === myDid
          return true
        })
      }
    }

    // Search
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(c =>
        c.scope_description.toLowerCase().includes(q) ||
        c.client_agent_did.toLowerCase().includes(q) ||
        (c.upgrader_agent_did?.toLowerCase().includes(q) ?? false) ||
        c.source_code_repo_url.toLowerCase().includes(q) ||
        String(c.id).includes(q) ||
        (c.ref ?? '').toLowerCase().includes(q)
      )
    }

    // Sort: newest first
    return result.sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  })

  // ─── Actions ─────────────────────────────────────────────────────────────────

  async function fetchAllContracts() {
    loading.value = true
    error.value = null
    try {
      const data = await contractApi.listAvailableContracts(100)
      // Merge with agent contracts to get full picture
      mergeContracts(data)
    } catch (err: any) {
      console.error('fetchAllContracts failed:', err)
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchMyContracts(agentDid: string) {
    loading.value = true
    try {
      const data = await contractApi.getAgentContracts(agentDid)
      mergeContracts(data)
    } catch (err: any) {
      console.error('fetchMyContracts failed:', err)
    } finally {
      loading.value = false
    }
  }

  // §COCKPITDESK (2026-10-15): the latest fetch owns the list. The "mine" half is read for the acting agent, and a fetch
  // still in flight when the acting agent changes (the page refetches on every switch) is dropped on arrival, not shown
  // as the new agent's contracts.
  let fetchSeq = 0
  async function fetchContracts() {
    const seq = ++fetchSeq
    loading.value = true
    error.value = null
    try {
      const { useAuthStore } = await import('@/stores/auth')
      const authStore = useAuthStore()
      const myDid = authStore.activeAgent?.did || authStore.activeAgent?.agent_did

      // Fetch public PROPOSED contracts + own contracts in parallel
      const listP = contractApi.listAvailableContracts(100)
      const mineP = myDid ? contractApi.getAgentContracts(myDid) : null
      // §TWOAGENT V0442: whether the legacy surface is retired is decided by the LIST route alone. A 404 there means
      // D8 did not mount it (EU, ASIA); the agent route is gone with it, so its refusal is expected, not an error. Any
      // other failure, or a 404 from the agent route alone on a frame that has the list, fails the fetch as before.
      let listed: BackendContract[]
      try {
        listed = await listP
      } catch (e: any) {
        mineP?.catch(() => undefined)   // the list's failure is the one reported; the agent call's answer is moot now
        if (!isRetiredList(e)) throw e
        if (seq !== fetchSeq) return
        legacyRetired.value = true
        contracts.value = []
        loaded.value = true
        return
      }
      legacyRetired.value = false
      const results: BackendContract[][] = [listed]
      if (mineP) results.push(await mineP)
      if (seq !== fetchSeq) return
      const merged: BackendContract[] = []
      const seen = new Set<string>()
      for (const arr of results) {
        for (const c of arr) {
          const k = contractApi.ctrRef(c)
          if (!seen.has(k)) {
            seen.add(k)
            merged.push(c)
          }
        }
      }
      contracts.value = merged.sort((a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
      loaded.value = true
    } catch (err: any) {
      if (seq !== fetchSeq) return
      console.error('fetchContracts failed:', err)
      error.value = err.message
    } finally {
      if (seq === fetchSeq) loading.value = false
    }
  }

  function mergeContracts(incoming: BackendContract[]) {
    const map = new Map<string, BackendContract>()
    for (const c of contracts.value) map.set(contractApi.ctrRef(c), c)
    for (const c of incoming) map.set(contractApi.ctrRef(c), c)
    contracts.value = Array.from(map.values()).sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }

  function upsertContract(c: BackendContract) {
    const idx = contracts.value.findIndex(x => contractApi.ctrRef(x) === contractApi.ctrRef(c))
    if (idx >= 0) {
      contracts.value[idx] = c
    } else {
      contracts.value.unshift(c)
    }
  }

  async function createContract(data: contractApi.ContractCreateDto): Promise<BackendContract> {
    const uiStore = useUIStore()
    try {
      const created = await contractApi.createContract(data)
      upsertContract(created)
      uiStore.showSuccess('Contract Created', `Contract ${contractApi.ctrLabel(created)} proposed successfully.`)
      return created
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to create contract'
      uiStore.showError('Create Failed', msg)
      throw err
    }
  }

  async function acceptContract(
    contractId: number | string,
    upgraderDid: string
  ): Promise<BackendContract> {
    const uiStore = useUIStore()
    try {
      const updated = await contractApi.acceptContract(contractId, upgraderDid)
      upsertContract(updated)
      uiStore.showSuccess('Contract Accepted', `You are now the upgrader for Contract #${contractId}.`)
      return updated
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to accept contract'
      uiStore.showError('Accept Failed', msg)
      throw err
    }
  }

  async function submitWork(contractId: number | string, prUrl: string): Promise<BackendContract> {
    const uiStore = useUIStore()
    try {
      const updated = await contractApi.submitContractWork(contractId, prUrl)
      upsertContract(updated)
      uiStore.showSuccess('Work Submitted', `Contract #${contractId} is now pending client review.`)
      return updated
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to submit work'
      uiStore.showError('Submit Failed', msg)
      throw err
    }
  }

  async function approveCompletion(contractId: number | string): Promise<BackendContract> {
    const uiStore = useUIStore()
    try {
      const updated = await contractApi.approveContractCompletion(contractId)
      upsertContract(updated)
      uiStore.showSuccess('Contract Completed', `Payment executed. Contract #${contractId} is complete.`)
      return updated
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to approve completion'
      uiStore.showError('Approval Failed', msg)
      throw err
    }
  }

  async function reportMalpractice(
    contractId: number | string,
    reason: string
  ): Promise<contractApi.MalpracticeResponse> {
    const uiStore = useUIStore()
    try {
      const result = await contractApi.reportMalpractice(contractId, reason)
      uiStore.showSuccess('Dispute Filed', `Dispute #${result.dispute_id} created via DDR system.`)
      return result
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to file dispute'
      uiStore.showError('Malpractice Failed', msg)
      throw err
    }
  }

  // ─── Drawer ───────────────────────────────────────────────────────────────────
  function openDrawer(contractKey: number | string) {
    activeContractId.value = String(contractKey)
    drawerOpen.value = true
  }

  function closeDrawer() {
    drawerOpen.value = false
    activeContractId.value = null
  }

  // ─── Filter helpers ───────────────────────────────────────────────────────────
  function setStatusFilter(s: StatusFilter) { statusFilter.value = s }
  function setRoleFilter(r: RoleFilter) { roleFilter.value = r }
  function setSearch(q: string) { searchQuery.value = q }
  function clearFilters() {
    statusFilter.value = 'ALL'
    roleFilter.value = 'all'
    searchQuery.value = ''
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout. See globalReset.ts.
  function $reset() {
    contracts.value = []
    loading.value = false
    error.value = null
    contractActivities.value = []
    drawerOpen.value = false
    activeContractId.value = null
    statusFilter.value = 'ALL'
    roleFilter.value = 'all'
    searchQuery.value = ''
  }

  return {
    // State
    contracts, loading, loaded, error,
    drawerOpen, activeContractId,
    statusFilter, roleFilter, searchQuery,
    $reset,

    // Getters
    activeContract, proposed, accepted, pendingMerge, completed,
    stats, filteredContracts,

    // Helpers
    getMyRole,

    // Actions
    fetchContracts, fetchAllContracts, fetchMyContracts,
    legacyRetired,
    createContract, acceptContract, submitWork,
    approveCompletion, reportMalpractice,

    // Drawer
    openDrawer, closeDrawer,
    ctrRef: contractApi.ctrRef, ctrLabel: contractApi.ctrLabel,

    // Activities
    contractActivities,

    // Filters
    setStatusFilter, setRoleFilter, setSearch, clearFilters
  }
})
