/**
 * services/api/a2aPayment.ts — A2A Payment Authorization (f045) frontend wrapper.
 *
 * Build #2 (2026-05-07) — first frontend integration of the A2A payment protocol.
 * Backend reference: routers/a2a_payment.py.
 *
 * Auth tier: AGENT JWT for /my-tokens, /release-by-id, /authorize, /settle.
 *            No auth for /verify (it's a public verification endpoint by design).
 *
 * Token state machine:
 *   AUTHORIZED  → caller created hold; target can verify+settle
 *   CONSUMED    → target verified; settlement in flight
 *   SETTLING    → backend settle-via-transfer running async
 *   SETTLED     → AVT moved successfully
 *   RELEASED    → caller released the hold (no settlement)
 *   EXPIRED     → TTL elapsed without settlement
 *   FAILED      → settlement attempted but failed (network/auth)
 */
import { apiClient } from './client'

// ── Types ────────────────────────────────────────────────────────────────────

export type A2APaymentStatus =
  | 'AUTHORIZED'
  | 'CONSUMED'
  | 'SETTLING'
  | 'SETTLED'
  | 'RELEASED'
  | 'EXPIRED'
  | 'FAILED'

/**
 * Returned by GET /my-tokens. NOTE: does NOT include the plaintext token —
 * that is shown once at authorize time only. Use token_id for backend ops.
 */
export interface A2APaymentTokenItem {
  token_id: string
  target_agent_did: string
  amount: string
  status: A2APaymentStatus | string  // backend may send lowercase variants
  contract_id: number | null
  created_at: string
  expires_at: string
  settled_at: string | null
}

export interface AuthorizeRequest {
  target_agent_did: string
  amount: string
  contract_id?: number | null
  ttl_seconds?: number  // default 900 (15min), max 3600 (1hr)
}

export interface AuthorizeResponse {
  token: string                  // plaintext apt_<hex> — show ONCE
  token_id: string
  amount: string
  target_agent_did: string
  expires_at: string
  contract_id?: number | null
}

export interface VerifyRequest {
  token: string
  target_agent_did?: string
}

export interface VerifyResponse {
  valid: boolean
  token_id?: string | null
  caller_did?: string | null
  target_agent_did?: string | null
  amount?: string | null
  contract_id?: number | null
  expires_at?: string | null
  status?: string | null
  error?: string | null
}

export interface SettleRequest {
  token: string
  task_id?: string
  success?: boolean
}

export interface SettleResponse {
  token_id: string
  status: string
  settlement_tx_id?: string | null
  amount: string
  caller_did: string
  target_agent_did: string
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Status filter values supported by the backend `?status=` query param. */
export type TokenStatusFilter = A2APaymentStatus | null

/** Display tone for status pills + accent borders. */
export function statusTone(status: string): 'amber' | 'cyan' | 'green' | 'gray' | 'red' {
  const s = status?.toUpperCase()
  if (s === 'AUTHORIZED') return 'amber'
  if (s === 'CONSUMED' || s === 'SETTLING') return 'cyan'
  if (s === 'SETTLED') return 'green'
  if (s === 'RELEASED' || s === 'EXPIRED') return 'gray'
  if (s === 'FAILED') return 'red'
  return 'gray'
}

// ── API client ───────────────────────────────────────────────────────────────

class A2APaymentService {
  private base = '/a2a-payment'

  /**
   * List the calling agent's payment tokens. Requires agent JWT.
   * Backend: GET /my-tokens?status=...&limit=...
   */
  async listMyTokens(params?: { status?: string; limit?: number }): Promise<A2APaymentTokenItem[]> {
    try {
      const queryParams: Record<string, any> = {}
      if (params?.status) queryParams.status = params.status
      if (params?.limit) queryParams.limit = params.limit
      const resp = await apiClient.get<A2APaymentTokenItem[]>(`${this.base}/my-tokens`, { params: queryParams })
      return Array.isArray(resp.data) ? resp.data : []
    } catch (err) {
      console.error('Failed to fetch A2A payment tokens:', err)
      throw err
    }
  }

  /**
   * Release an AUTHORIZED token by its ID. Requires agent JWT.
   * Backend: POST /release-by-id/{token_id} (added in Build #2 for UI use).
   */
  async releaseToken(tokenId: string): Promise<{ token_id: string; status: string }> {
    try {
      const resp = await apiClient.post(`${this.base}/release-by-id/${encodeURIComponent(tokenId)}`)
      return resp.data
    } catch (err) {
      console.error('Failed to release A2A payment token:', err)
      throw err
    }
  }

  /**
   * Authorize a new payment token. Requires agent JWT.
   * Returns the plaintext token — show ONCE.
   */
  async authorize(req: AuthorizeRequest): Promise<AuthorizeResponse> {
    try {
      const resp = await apiClient.post<AuthorizeResponse>(`${this.base}/authorize`, req)
      return resp.data
    } catch (err) {
      console.error('Failed to authorize A2A payment:', err)
      throw err
    }
  }

  /**
   * Verify a token. NO AUTH — public verification by design.
   * Critical idempotency note (P25-001 in CLAUDE.md): repeated verify on a
   * CONSUMED token returns valid=true. Service agents must track local
   * consumption to avoid re-doing paid work.
   */
  async verify(req: VerifyRequest): Promise<VerifyResponse> {
    try {
      const resp = await apiClient.post<VerifyResponse>(`${this.base}/verify`, req)
      return resp.data
    } catch (err) {
      console.error('Failed to verify A2A payment:', err)
      throw err
    }
  }

  /**
   * Settle a token (move AVT to target). Requires agent JWT (target agent).
   */
  async settle(req: SettleRequest): Promise<SettleResponse> {
    try {
      const resp = await apiClient.post<SettleResponse>(`${this.base}/settle`, req)
      return resp.data
    } catch (err) {
      console.error('Failed to settle A2A payment:', err)
      throw err
    }
  }
}

export const a2aPaymentService = new A2APaymentService()
