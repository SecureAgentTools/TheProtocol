/**
 * COCKPIT CARD API (L1, 2026-07-25) — liability mandates, evidence chains, presence challenges.
 *
 * Ground truth: routers/liability.py (all dev-JWT except public verify).
 * Feature-dark server-side: 404 when LIABILITY_MODE=off — callers degrade quietly.
 */

import { apiClient } from './client'
import { registryConfigWithin } from '@/composables/useRegistryConfig'

/** The route's own refusal where LIABILITY_MODE is off (routers/liability.py `_require_enabled`). */
export const LIABILITY_OFF_DETAIL = 'Liability mandates are not enabled on this registry'

/** §FESUITE (2026-10-10, the operator batch) — a registry says whether it runs liability mandates (registry-config
 *  `liability_mode`), and where it says `off` the console does not ask a route that would refuse: the call answers what
 *  the route would have (that 404, which every caller already reads as "off"), with no request sent. Measured on the
 *  sandbox operators: the Cockpit and Pocket Approvals sent 4 refused reads per visit. The challenge and device-key
 *  routes are not gated (they serve account security on every registry) and never wait here. An older registry (no
 *  field) or a config not read in time asks as before. */
export async function askIfLiabilityRuns<T>(call: () => Promise<T>): Promise<T> {
  const cfg = await registryConfigWithin()
  if (cfg.liability_mode === 'off') {
    throw Object.assign(new Error(LIABILITY_OFF_DETAIL), {
      isAxiosError: true, notAsked: true, response: { status: 404, data: { detail: LIABILITY_OFF_DETAIL } },
    })
  }
  return call()
}

export interface LiabilityResolved {
  valid: boolean
  effective_scope: string[]
  reasons: string[]
  authority_now: string[]
}

export interface LiabilityMandate {
  id: string
  developer_id: number
  agent_did: string
  tier: string
  scope: string[]
  limits: Record<string, any> | null
  status: 'signed' | 'revoked' | 'expired'
  presence_method: string
  authority_snapshot: Record<string, any>
  content_hash: string
  registry_id: string | null
  issued_at: string
  expires_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
  resolved?: LiabilityResolved
  chain_ok?: boolean
  chain_break_at?: number | null
  evidence?: LiabilityEvidence[]
}

export interface LiabilityEvidence {
  seq: number
  event_type: string
  action_ref: string | null
  payload: Record<string, any>
  authority_snapshot: Record<string, any> | null
  presence: Record<string, any> | null
  digest: string
  prev_hash: string
  chain_hash: string
  created_at: string
}

export interface LiabilityChallenge {
  id: string
  mandate_id: string
  action_type: string
  action_ref: string | null
  facts: Record<string, any>
  challenge_hash: string
  created_at: string
  expires_at: string
}

export interface DelegatableInfo {
  authority_now: string[]
  reasons: string[]
  delegatable: string[]
  base: string[]
  non_delegatable: string[]
  mode: string
  presence: { totp_enrolled: boolean }
}

export type DenyReason = 'wrong_amount' | 'wrong_counterparty' | 'not_now' | 'never'

export interface ConsentPosture {
  posture: 'swift' | 'balanced' | 'hardened'
  registry_posture: string
  source: 'registry' | 'organization'
  agent_did: string | null
  dials: {
    method_floor: 'enclave' | 'totp' | 'webauthn_uv'
    method_preferred: string
    totp_only_while_unenrolled: boolean
    read_floor_ms: number
    challenge_ttl_seconds: number
    preflight: boolean
    preview_credit_max_age_s: number
    presence_gated_raise: boolean
    device_render: string
    ceilings: boolean
    ceiling_decay_hours: number | null
    four_eyes: string
    overflow: string
    streak_badge_at: number
    streak_method_escalate_at: number | null
    streak_propose_ceiling_at: number | null
    quiet_hours: string
  }
  effective_challenge_ttl_seconds: number
  order: string[]
}

export interface Ceiling {
  scope: string; max_per_tx: string; currency: string
  granted_at: string | null; decays_at: string | null; granted_by_decision: string | null
  /** Re-derived per request, never stored. */
  live?: boolean
  state?: string
}

export interface CeilingState {
  mandate_id: string
  ceiling: Ceiling | null
  posture: string
  ceilings_allowed: boolean
  decay_hours_default: number | null
  org_max_amount: string | number | null
}

export interface Receipt {
  evidence_id: number
  mandate_id: string
  event_type: string
  at: string
  action_ref: string | null
  payload: Record<string, any>
  challenge: null | {
    id: string; action_type: string; facts: Record<string, any>
    status: string; method: string | null; device_id: number | null
    created_at: string; expires_at: string; resolved_at: string | null
    delivery_acked_at: string | null
    /** The SERVER's own "is this the same thing" key — the digest the read floor
     *  matches previews on and the streak counts identical confirms with. Declared
     *  here so no surface has to re-derive sameness in TypeScript. */
    facts_digest?: string
  }
  presentations: Array<Record<string, any>>
  presentation_mismatch: boolean
  /** §COCKPITBOOK — surfaces existed in more than one (locale, render_version) group, so
   *  their renderings CANNOT be compared. Neither agreement nor disagreement was
   *  established, which is a third state and not a milder mismatch. */
  presentation_incomparable?: boolean
  presentation_groups?: { locale: string; render_version: string; surfaces: number; agree: boolean }[]
  legs_ms: { arrive: number | null; read: number | null; consent: number | null }
  ask_reason: 'required' | 'courtesy' | null
}

/** §PREFLIGHT (P8) — an agent's announcement of an action it has not taken yet.
 *
 *  `signable` is present, always false, and NOT what the UI keys on: the desk renders
 *  no approve affordance in this state AT ALL (I9 — absent, not disabled), because a
 *  disabled control is one CSS mistake away from being a live one.
 */
export interface Intent {
  id: string
  agent_did: string
  action_type: string
  action_ref: string
  facts_preview: Record<string, any>
  facts_digest: string
  created_at: string
  expires_at: string
  unverified: true
  signable: false
}

export const liabilityApi = {
  delegatable: () => askIfLiabilityRuns(() =>
    apiClient.get<DelegatableInfo>('/liability/delegatable').then(r => r.data)),

  createMandate: (body: { agent_did: string; scope: string[]; limits?: Record<string, any> | null;
                          tier?: string; expires_in_days?: number | null; totp_code: string }) =>
    askIfLiabilityRuns(() => apiClient.post<LiabilityMandate>('/liability/mandates', body).then(r => r.data)),

  myMandates: () => askIfLiabilityRuns(() =>
    apiClient.get<{ mandates: LiabilityMandate[]; count: number }>('/liability/mandates/mine').then(r => r.data)),

  getMandate: (id: string) => askIfLiabilityRuns(() =>
    apiClient.get<LiabilityMandate>(`/liability/mandates/${id}`).then(r => r.data)),

  revokeMandate: (id: string, reason?: string) => askIfLiabilityRuns(() =>
    apiClient.post(`/liability/mandates/${id}/revoke`, { reason }).then(r => r.data)),

  verifyMandate: (id: string) => askIfLiabilityRuns(() =>
    apiClient.post(`/liability/mandates/${id}/verify`).then(r => r.data)),

  createChallenge: (body: { mandate_id: string; action_type: string; action_ref?: string | null;
                            facts?: Record<string, any> }) =>
    askIfLiabilityRuns(() => apiClient.post<LiabilityChallenge>('/liability/challenges', body).then(r => r.data)),

  pendingChallenges: () =>
    apiClient.get<{ challenges: LiabilityChallenge[]; count: number }>('/liability/challenges/pending').then(r => r.data),

  approveChallenge: (id: string, body: { totp_code?: string; device_id?: number; signature?: string;
                                         credential_id?: string; authenticator_data?: string;
                                         client_data_json?: string }) =>
    apiClient.post(`/liability/challenges/${id}/approve`, body).then(r => r.data),

  /** §SHOWN — the deny taxonomy. The vocabulary is CLOSED server-side; a free-text
   *  reason would collect sentences nothing can consume. Omitted ⇒ `user_denied`. */
  denyChallenge: (id: string, reason?: DenyReason) =>
    apiClient.post(`/liability/challenges/${id}/deny`, reason ? { reason } : undefined).then(r => r.data),

  /** §SHOWN — record that a surface PRESENTED this decision, and what it showed. */
  ackChallenge: (id: string, body: { surface: 'desk' | 'device'; render_version?: string;
                                     locale?: string; presentation_hash?: string | null;
                                     first_presented_at?: string }) =>
    apiClient.post(`/liability/challenges/${id}/ack`, body).then(r => r.data),

  /** §POSTURE — the dials in force, so a surface can WEAR the posture rather than
   *  discover it by being refused. */
  posture: (agentDid?: string | null) => askIfLiabilityRuns(() =>
    apiClient.get<ConsentPosture>('/liability/posture',
      agentDid ? { params: { agent_did: agentDid } } : undefined).then(r => r.data)),

  /** §CEILING — the standing consent on a mandate, with its decay state RE-DERIVED
   *  (a decayed ceiling is ignored at read time; the pane must never render a stored
   *  "live" flag somebody forgot to flip). */
  getCeiling: (mid: string) => askIfLiabilityRuns(() =>
    apiClient.get<CeilingState>(`/liability/mandates/${mid}/ceiling`).then(r => r.data)),

  /** Granting or WIDENING standing consent is a decision: this mints a challenge that
   *  only an enrolled device can sign, in every posture. */
  raiseCeiling: (mid: string, body: { scope: string; max_per_tx: string; currency: string; hours?: number }) =>
    askIfLiabilityRuns(() => apiClient.post(`/liability/mandates/${mid}/ceiling`, body).then(r => r.data)),

  /** I7 — lowering or removing it is instant and unchallenged. Omit the body to remove. */
  tightenCeiling: (mid: string, body?: { scope: string; max_per_tx: string; currency: string }) =>
    askIfLiabilityRuns(() => apiClient.put(`/liability/mandates/${mid}/ceiling`, body).then(r => r.data)),

  /** §PREFLIGHT — what agents have ANNOUNCED they are about to do.
   *
   *  🔴 Unverified by construction and never signable. Nothing here has been checked
   *  against a mandate, a balance or a ceiling; it is an agent's own claim, rendered so
   *  a human can start reading before the real ask exists. `available:false` means the
   *  pre-flight rail itself is down — an honest gap, which is a different thing from
   *  "no agent announced anything" and renders differently.
   */
  pendingIntents: () => askIfLiabilityRuns(() =>
    apiClient.get<{ items: Intent[]; count: number; available: boolean; note?: string }>(
      '/liability/intents/pending').then(r => r.data)),

  /** §POSTURE — the receipts projection (dev-scoped across all my mandates). */
  receipts: (params?: { mandate_id?: string; since?: string; limit?: number }) => askIfLiabilityRuns(() =>
    apiClient.get<{ receipts: Receipt[]; count: number }>('/liability/receipts', { params }).then(r => r.data)),

  // WEBAUTHN — enrolment for THIS surface, through the device-agnostic self routes.
  // The per-device trio needs a push-device row to exist first; these do not, which is
  // what lets a desk browser that never subscribed to push still hold a signing key.
  webauthnSelfOptions: () =>
    apiClient.get<Record<string, any>>('/liability/webauthn/options').then(r => r.data),

  webauthnSelfRegister: (body: { attestation_object: string; client_data_json: string }) =>
    apiClient.post<{ ok: boolean; device_id: number; credential_id: string }>(
      '/liability/webauthn/register', body).then(r => r.data),

  // WEBAUTHN — the biometric-enforced signer. Enrollment goes through
  // usePocketLock.enroll() (POST /liability/webauthn/register on the SESSION,
  // not per-device); the per-device options/register/enroll-key trio that used
  // to sit here had zero callers — the dead useEnclaveKey path — and was
  // removed with it (§POCKETBRIDGE P0). Revocation is still a live rail.
  revokeDeviceKey: (deviceId: number) =>
    apiClient.post(`/liability/devices/${deviceId}/revoke-key`).then(r => r.data),
}
