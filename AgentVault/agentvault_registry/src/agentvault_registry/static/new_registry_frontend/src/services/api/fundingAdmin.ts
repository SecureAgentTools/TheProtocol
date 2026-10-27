/**
 * services/api/fundingAdmin.ts — Funding Requests admin operations.
 *
 * Build #5 (2026-05-07) — frontend wrapper for the admin-side funding flow.
 * Backend: routers/funding_requests.py (admin_router with /api/v1/admin/funding prefix).
 * Auth: admin_treasury flag (developer JWT with is_admin=true).
 */
import { apiClient } from './client'

export interface FundingRequest {
  id: number
  requester_did: string
  requester_name: string | null
  requested_amount: string
  reason: string
  status: 'pending' | 'approved' | 'rejected' | 'funded' | string
  reviewed_by: string | null
  reviewed_at: string | null
  approved_amount: string | null
  rejection_reason: string | null
  funded_at: string | null
  funding_transaction_id: string | null
  created_at: string
  updated_at: string | null
}

export type FundingStatusFilter = 'pending' | 'approved' | 'rejected' | 'funded' | null

class FundingAdminService {
  private base = '/admin/funding'

  /** GET /admin/funding/pending — oldest pending requests first */
  async listPending(): Promise<FundingRequest[]> {
    try {
      const resp = await apiClient.get<FundingRequest[]>(`${this.base}/pending`)
      return Array.isArray(resp.data) ? resp.data : []
    } catch (err) {
      console.error('Failed to load pending funding requests:', err)
      throw err
    }
  }

  /** GET /admin/funding/all?status=&limit=&offset= */
  async listAll(params?: { status?: FundingStatusFilter; limit?: number; offset?: number }): Promise<FundingRequest[]> {
    try {
      const queryParams: Record<string, any> = {}
      if (params?.status) queryParams.status = params.status
      if (params?.limit) queryParams.limit = params.limit
      if (params?.offset) queryParams.offset = params.offset
      const resp = await apiClient.get<FundingRequest[]>(`${this.base}/all`, { params: queryParams })
      return Array.isArray(resp.data) ? resp.data : []
    } catch (err) {
      console.error('Failed to load funding requests:', err)
      throw err
    }
  }

  /** POST /admin/funding/{id}/approve — body { approved_amount? } */
  async approve(requestId: number, approvedAmount?: string): Promise<FundingRequest> {
    try {
      const body: Record<string, any> = {}
      if (approvedAmount !== undefined && approvedAmount !== null && approvedAmount !== '') {
        body.approved_amount = approvedAmount
      }
      const resp = await apiClient.post<FundingRequest>(`${this.base}/${requestId}/approve`, body)
      return resp.data
    } catch (err) {
      console.error('Failed to approve funding request:', err)
      throw err
    }
  }

  /** POST /admin/funding/{id}/reject — body { reason } */
  async reject(requestId: number, reason: string): Promise<FundingRequest> {
    try {
      const resp = await apiClient.post<FundingRequest>(`${this.base}/${requestId}/reject`, { reason })
      return resp.data
    } catch (err) {
      console.error('Failed to reject funding request:', err)
      throw err
    }
  }
}

export const fundingAdminService = new FundingAdminService()
