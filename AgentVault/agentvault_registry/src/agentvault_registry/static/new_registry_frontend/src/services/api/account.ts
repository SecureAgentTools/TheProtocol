/**
 * account.ts — User-initiated GDPR Art. 17 erasure (W2, 2026-05-09).
 *
 * Wraps the three /api/v1/account/* endpoints used by Settings → Danger Zone
 * and the DashboardHeader pending-deletion banner.
 *
 * Endpoints:
 *   POST   /account/request-deletion    — flip status to pending_deletion
 *   POST   /account/cancel-deletion     — revert to active during cooling-off
 *   GET    /account/deletion-status     — read current state + countdown
 */
import { apiClient } from './client'

export interface DeletionStatusResponse {
  /** null ≡ active. 'pending_deletion' during 14-day cooling-off. 'anonymized' is terminal. */
  deletion_status: 'pending_deletion' | 'anonymized' | null
  /** ISO-8601 timestamp at which the user requested deletion. */
  deletion_requested_at: string | null
  /** ISO-8601 timestamp at which the daily worker will anonymize. */
  anonymizes_at: string | null
  /** Length of the cooling-off window (default 14 days). */
  cooling_off_days: number
}

export interface RequestDeletionPayload {
  password: string
  /** Must equal exactly: 'DELETE MY ACCOUNT'. */
  confirmation: string
  /** Optional free-text reason — for our analytics, not user-facing. */
  reason?: string
}

export interface SimpleAck {
  ok: boolean
  message: string
}

const ACCOUNT_BASE = '/account'

export const accountService = {
  /** Schedule the caller's account for anonymization in 14 days. */
  async requestDeletion(payload: RequestDeletionPayload): Promise<SimpleAck> {
    const r = await apiClient.post<SimpleAck>(`${ACCOUNT_BASE}/request-deletion`, payload)
    return r.data
  },

  /** Cancel a pending deletion within the cooling-off window. */
  async cancelDeletion(): Promise<SimpleAck> {
    const r = await apiClient.post<SimpleAck>(`${ACCOUNT_BASE}/cancel-deletion`)
    return r.data
  },

  /** Read the current deletion state for Settings UI countdown. */
  async getDeletionStatus(): Promise<DeletionStatusResponse> {
    const r = await apiClient.get<DeletionStatusResponse>(`${ACCOUNT_BASE}/deletion-status`)
    return r.data
  },
}

/** Phrase the user must type to confirm. Used by Settings.vue + tests. */
export const ACCOUNT_DELETE_CONFIRMATION_PHRASE = 'DELETE MY ACCOUNT'
