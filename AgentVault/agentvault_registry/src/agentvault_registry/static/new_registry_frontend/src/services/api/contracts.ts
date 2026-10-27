/**
 * Contracts API Service — OWL-16 clean rewrite
 *
 * Ground truth: routers/contracts.py
 * Backend statuses: PROPOSED → ACCEPTED → PENDING_MERGE → COMPLETED
 *
 * Auth strategy: mutation endpoints require agent JWT.
 * apiClient uses developer JWT by default for /contracts/ (not in isAgentEndpoint).
 * All mutation methods inject agent JWT via explicit Authorization header override.
 */

import { apiClient } from './client'
import axios from 'axios'

// ─── Exact mirror of backend ContractResponse ─────────────────────────────────

export interface BackendContract {
  id: number
  /** §BLOGSHOTS-FIX (2026-07-27): the spine id (ctr_…). Spine-native contracts have no legacy
   *  int id (id === -1) and are addressed by ref everywhere. Always set by current registries;
   *  optional so stale caches don't explode. */
  ref?: string | null
  client_agent_did: string
  upgrader_agent_did: string | null
  status: 'PROPOSED' | 'ACCEPTED' | 'PENDING_MERGE' | 'IN_PROGRESS' | 'COMPLETED' | 'DISPUTED' | 'FAILED'
  scope_description: string
  source_code_repo_url: string
  source_code_branch: string
  acceptance_criteria: Record<string, any>
  payment_amount: number
  access_credentials_id: string | null
  pr_url: string | null
  created_at: string
  updated_at: string
  accepted_at: string | null
  completed_at: string | null
}

// ─── Create request model ─────────────────────────────────────────────────────

export interface ContractCreateDto {
  client_agent_did: string              // Must match authenticated agent DID
  scope_description: string
  source_code_repo_url: string
  source_code_branch: string
  acceptance_criteria: Record<string, any>
  payment_amount: number
}

// ─── Malpractice response ─────────────────────────────────────────────────────

export interface MalpracticeResponse {
  message: string
  dispute_id: number
  contract_id: number
  complainant_did: string
  defendant_did: string
  status: string
}

// ─── Helper: get agent JWT from auth store ────────────────────────────────────

async function getAgentJwt(): Promise<string | null> {
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()

  if (authStore.agentToken) {
    return authStore.agentToken
  }

  // No cached token — try to re-authenticate active agent
  if (authStore.activeAgent?.client_id && authStore.activeAgent?.client_secret) {
    const ok = await authStore.authenticateAsAgent(authStore.activeAgent)
    if (ok) return authStore.agentToken
  }

  return null
}

// ─── Mutation client factory ───────────────────────────────────────────────────

async function agentRequest(
  method: 'post' | 'put' | 'patch' | 'delete',
  url: string,
  data?: any
) {
  const jwt = await getAgentJwt()
  const headers: Record<string, string> = {}
  if (jwt) {
    headers['Authorization'] = `Bearer ${jwt}`
  }
  return apiClient.request({ method, url, data, headers })
}

// ─── Ref helpers (§BLOGSHOTS-FIX) ─────────────────────────────────────────────
// One addressing rule for both surfaces: legacy rows keep their int id, spine-native
// rows (id === -1) are addressed by their ctr_… ref. The backend's _resolve accepts both.

/** The value to use in API paths and as a stable client-side key. */
export const ctrRef = (c: Pick<BackendContract, 'id' | 'ref'>): string =>
  c.ref ?? String(c.id)

/** Human label: '#1018' for legacy rows, the short ctr_… ref for spine-native ones. */
export const ctrLabel = (c: Pick<BackendContract, 'id' | 'ref'>): string =>
  c.id > 0 ? `#${c.id}` : (c.ref ? c.ref.slice(0, 12) : '#?')

// ─── API Functions ────────────────────────────────────────────────────────────

/**
 * GET /api/v1/contracts/
 * Public — no auth required.
 * Returns contracts in PROPOSED status.
 */
export async function listAvailableContracts(limit = 50): Promise<BackendContract[]> {
  // §COCKPITDESK (2026-10-15) — HIS REPORT: "/contracts (threw not found notification on opening ...)". EU and ASIA
  // retired the legacy list (D8) and answer 404, which the store reads as "retired" and the page handles; the global
  // error toast still said "Not Found" over a page working as designed. The 404 is an answer here, so the caller has it.
  const response = await apiClient.get('/contracts/', { params: { limit }, expectedStatuses: [404] })
  return Array.isArray(response.data) ? response.data : []
}

/**
 * GET /api/v1/contracts/{id}
 * Public — no auth required.
 */
export async function getContract(contractId: number | string): Promise<BackendContract> {
  const response = await apiClient.get(`/contracts/${contractId}`)
  return response.data
}

/**
 * GET /api/v1/contracts/agent/{agent_did}
 * Public — no auth required.
 * Returns all contracts involving this DID (as client or upgrader).
 * Optional role filter: 'client' | 'upgrader'
 */
export async function getAgentContracts(
  agentDid: string,
  role?: 'client' | 'upgrader'
): Promise<BackendContract[]> {
  const params: any = {}
  if (role) params.role = role
  // the agent route is gone with the list on a retired frame (its 404 is moot there); on a frame that keeps the list
  // the store fails the fetch on it and the page says so in its own words, so no global toast either way
  const response = await apiClient.get(
    `/contracts/agent/${encodeURIComponent(agentDid)}`,
    { params, expectedStatuses: [404] }
  )
  return Array.isArray(response.data) ? response.data : []
}

/**
 * POST /api/v1/contracts/
 * Requires agent JWT. client_agent_did must match authenticated agent.
 */
export async function createContract(data: ContractCreateDto): Promise<BackendContract> {
  const response = await agentRequest('post', '/contracts/', data)
  return response.data
}

/**
 * POST /api/v1/contracts/{id}/accept
 * Requires agent JWT. upgrader_agent_did should match authenticated agent.
 */
export async function acceptContract(
  contractId: number | string,
  upgraderAgentDid: string
): Promise<BackendContract> {
  const response = await agentRequest('post', `/contracts/${contractId}/accept`, {
    upgrader_agent_did: upgraderAgentDid
  })
  return response.data
}

/**
 * POST /api/v1/contracts/{id}/submit
 * Requires agent JWT. Transitions ACCEPTED → PENDING_MERGE.
 */
export async function submitContractWork(
  contractId: number | string,
  prUrl: string
): Promise<BackendContract> {
  const response = await agentRequest('post', `/contracts/${contractId}/submit`, {
    pr_url: prUrl
  })
  return response.data
}

/**
 * POST /api/v1/contracts/{id}/approve-completion
 * Requires agent JWT. Only client_agent_did may call this.
 * Triggers real treasury 2PC payment: client → treasury → upgrader.
 */
export async function approveContractCompletion(contractId: number | string): Promise<BackendContract> {
  const response = await agentRequest('post', `/contracts/${contractId}/approve-completion`)
  return response.data
}

/**
 * POST /api/v1/contracts/malpractice
 * Requires agent JWT. Caller must be a party to the contract.
 * Creates a DDR dispute via crud_disputes.create_dispute().
 */
export async function reportMalpractice(
  contractId: number | string,
  reason: string
): Promise<MalpracticeResponse> {
  const response = await agentRequest('post', '/contracts/malpractice', {
    contract_id: contractId,
    reason
  })
  return response.data
}

// ─── Re-export BackendContract as Contract for backward compat in store ───────
export type Contract = BackendContract
