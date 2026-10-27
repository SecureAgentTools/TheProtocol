/**
 * Settlements API wrapper — Cross-Registry Settlement Protocol.
 *
 * Backend endpoints under /api/v1/federation/disputes/*
 *  - GET    /settlements                — list (admin_enforcement)
 *  - GET    /settlements/{id}           — detail (admin_enforcement)
 *  - POST   /settlements/{id}/approve   — admin approve, optional reason
 *  - POST   /settlements/{id}/reject    — admin reject, optional reason
 *  - GET    /peer-slash-config          — list peer auto-slash configs
 *  - PUT    /peer-slash-config/{peer_id} — update peer config
 *
 * SF1 (2026-05-06): Settlement type extended with all 27 backend fields
 * including saga lifecycle (saga_state, saga_timeout_at, saga_retry_count)
 * and event chain (slash_event_id, mint_event_id, request_event_id) so
 * stuck sagas are visible in the UI.
 *
 * SF6 + SF7 (2026-05-06): extracted from inline fetch in Settlements.vue.
 */
import { apiClient } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Settlement {
  id: string
  dispute_id: number
  status: string
  complainant_did: string
  defendant_did: string
  requested_amount: number
  slashed_amount: number
  minted_amount: number
  shortfall: number
  is_partial: boolean
  ruling: string
  origin_registry_url: string
  defendant_registry_url: string
  callback_url?: string
  slash_tx_id: string
  mint_tx_id: string
  // SF1: event chain references (added 2026-05-06)
  slash_event_id?: string
  mint_event_id?: string
  request_event_id?: string
  // SF1: saga lifecycle (added 2026-05-06)
  saga_state?: string
  saga_timeout_at?: string | null
  saga_last_step_at?: string | null
  saga_retry_count?: number
  requested_at: string | null
  slashed_at: string | null
  settled_at: string | null
  error_message: string | null
}

export interface SettlementStats {
  total: number
  pending: number
  settled: number
  slashed: number
  failed: number
  expired: number
  total_requested_avt: number
  total_slashed_avt: number
  total_minted_avt: number
}

export interface SettlementListResponse {
  count: number
  stats: SettlementStats
  settlements: Settlement[]
}

export interface PeerSlashConfig {
  id: number
  name: string
  base_url: string
  status: string
  auto_slash_enabled: boolean
  auto_slash_max_avt: number
  bayesian_discount?: number
  total_interactions?: number
  disputes_lost_with?: number
  last_interaction_at?: string | null
}

export interface ApproveRejectResult {
  settlement_id: string
  status: string
  message?: string
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

// apiClient.baseURL already prepends '/api/v1' (see services/api/client.ts).
// Adding it here again would yield '/api/v1/api/v1/federation/...' → 404 cascade.
const BASE = '/federation/disputes'

export const settlementsApi = {
  async list(statusFilter?: string): Promise<SettlementListResponse> {
    const params = statusFilter && statusFilter !== 'all' ? { status_filter: statusFilter } : {}
    const { data } = await apiClient.get(`${BASE}/settlements`, { params })
    return data
  },

  async get(id: string): Promise<{ settlement: Settlement }> {
    const { data } = await apiClient.get(`${BASE}/settlements/${encodeURIComponent(id)}`)
    return data
  },

  async approve(id: string, reason?: string): Promise<ApproveRejectResult> {
    const body = reason ? { reason } : {}
    const { data } = await apiClient.post(`${BASE}/settlements/${encodeURIComponent(id)}/approve`, body)
    return data
  },

  async reject(id: string, reason?: string): Promise<ApproveRejectResult> {
    const body = reason ? { reason } : {}
    const { data } = await apiClient.post(`${BASE}/settlements/${encodeURIComponent(id)}/reject`, body)
    return data
  },

  async listPeerConfigs(): Promise<{ peers: PeerSlashConfig[] }> {
    const { data } = await apiClient.get(`${BASE}/peer-slash-config`)
    return data
  },

  async updatePeerConfig(peerId: number, payload: { auto_slash_enabled: boolean; auto_slash_max_avt: number }): Promise<unknown> {
    const { data } = await apiClient.put(`${BASE}/peer-slash-config/${peerId}`, payload)
    return data
  },
}
