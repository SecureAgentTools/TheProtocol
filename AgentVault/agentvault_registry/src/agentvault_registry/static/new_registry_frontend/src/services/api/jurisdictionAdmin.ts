// REGAUTH (SPEC 2026-08-15) — the jurisdiction profile + regulatory
// authorizations rail. The profile is the operator's own declaration of what
// their law permits; `requires_authorization` entries park declared lifecycle
// acts (AGORA listing approval, IPO opening, the fiat lane) until a recorded
// authorization (the state's reference id) covers them. apiClient baseURL is
// /api/v1. ⚠ The RFC7807 handler stringifies dict details: parse string
// details that start with '{' before reading `.blockers` (E1b precedent).
import { apiClient } from './client'

const ADMIN_BASE = '/admin/jurisdiction-profile'

export interface RegulatedActionEntry {
  authority: string
  scope?: 'registry' | 'per_subject'
  mode?: 'shadow' | 'enforce'
  note?: string
}

export interface JurisdictionProfile {
  name: string
  version: number
  features?: Record<string, boolean>
  limits?: Record<string, number>
  declared_at?: string
  note?: string
  requires_authorization?: Record<string, RegulatedActionEntry>
}

export interface ProfileSummary {
  declared: boolean
  mode: string
  profile: JurisdictionProfile | null
  features_denied?: string[]
  profile_hash?: string
}

export interface RegulatoryAuthorization {
  id: string
  action: string
  subject_ref: string | null
  authority: string
  jurisdiction: string
  reference_id: string
  valid_from: string | null
  valid_until: string | null
  evidence_hash: string | null
  evidence_note?: string | null
  contract_ref: string | null
  // §VCSIGN: server-side classification of the countersign (present only when
  // contract_ref is set): resolves = agreed + zero-value, digest = the card's
  // contract_digest, problem = 'missing' | 'nonzero_value' | 'not_agreed'.
  contract_resolves?: boolean
  contract_digest?: string
  contract_problem?: string
  status: 'active' | 'revoked'
  live: boolean
  recorded_by_dev_id?: number
  presence_method?: string | null
  created_at?: string | null
  revoked_at?: string | null
  revoke_reason?: string | null
}

export interface RecordAuthorizationBody {
  action: string
  subject_ref?: string | null
  authority: string
  jurisdiction: string
  reference_id: string
  valid_from?: string | null
  valid_until?: string | null
  evidence_hash?: string | null
  evidence_note?: string | null
  contract_ref?: string | null
}

export interface PublicAuthorization {
  action: string
  subject_ref: string | null
  authority: string
  jurisdiction: string
  reference_id: string
  valid_from: string | null
  valid_until: string | null
  evidence_hash: string | null
  contract_ref: string | null
}

/** Parse an error body's `detail` back to an object when the RFC7807 handler
 *  stringified it, then return its blockers list (or []). */
export function parseBlockers(err: any): any[] {
  let detail = err?.response?.data?.detail ?? err?.detail
  if (typeof detail === 'string' && detail.trim().startsWith('{')) {
    try { detail = JSON.parse(detail) } catch { /* keep the string */ }
  }
  const blockers = detail?.blockers
  return Array.isArray(blockers) ? blockers : []
}

export const jurisdictionAdminService = {
  async getProfile(): Promise<ProfileSummary> {
    const { data } = await apiClient.get(ADMIN_BASE)
    return data
  },

  async putProfile(profile: JurisdictionProfile): Promise<ProfileSummary> {
    const { data } = await apiClient.put(ADMIN_BASE, profile)
    return data
  },

  async listAuthorizations(includeRevoked = false): Promise<{
    authorizations: RegulatoryAuthorization[]
    actions: string[]
    display_only_actions: string[]
    mode: string
  }> {
    const { data } = await apiClient.get(`${ADMIN_BASE}/authorizations`, {
      params: { include_revoked: includeRevoked },
    })
    return data
  },

  async recordAuthorization(body: RecordAuthorizationBody): Promise<{ recorded: boolean; authorization: RegulatoryAuthorization }> {
    const { data } = await apiClient.post(`${ADMIN_BASE}/authorizations`, body)
    return data
  },

  async revokeAuthorization(id: string, reason: string): Promise<{ revoked: boolean; authorization: RegulatoryAuthorization }> {
    const { data } = await apiClient.post(`${ADMIN_BASE}/authorizations/${encodeURIComponent(id)}/revoke`, { reason })
    return data
  },

  /** Public proof surface (no auth): the LIVE set the signed card publishes. */
  async publicAuthorizations(): Promise<{ authorizations: PublicAuthorization[]; count: number }> {
    const { data } = await apiClient.get('/jurisdiction/authorizations')
    return data
  },

  /** §VCSIGN-2: contracts eligible as a countersign (agreed + zero-value) for
   *  the record form's picker. Server-side C2 validation stays the enforcement. */
  async listAttestationCandidates(): Promise<AttestationCandidate[]> {
    const { data } = await apiClient.get(`${ADMIN_BASE}/attestation-candidates`)
    return (data?.candidates ?? []) as AttestationCandidate[]
  },
}

export interface AttestationCandidate {
  id: string
  title: string
  contract_type: string
  client_did: string
  provider_did: string | null
  agreed_at: string | null
  referenced: boolean
}
