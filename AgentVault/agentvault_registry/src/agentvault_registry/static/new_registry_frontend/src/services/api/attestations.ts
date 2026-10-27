import type { AxiosInstance } from 'axios'
import { apiClient } from './client'

/**
 * ZKP Attestation API client.
 *
 * Mirrors the Phase 1-5 backend models from `routers/attestations.py`:
 *   - AttestationRecord       — list / get / by-did response shape
 *   - AttestationListResponse — paginated container
 *   - AttestationReverifyResponse — re-run /verify
 *   - RevokeAttestationResponse — revoke success
 *   - ScheduleRecord / ScheduleListResponse — Phase 5 cron schedules
 *
 * Replaces the pre-Phase-1 placeholder shape (capability/certification)
 * that no longer matches the live backend.
 */

// ─── Phase 1+2+4 attestation record ───────────────────────────────────
export interface AttestationRecord {
  id: string
  agent_did: string
  circuit_id: string
  circuit_version: string
  public_inputs: Record<string, unknown>
  proof_hash: string
  policy_parameters_hash: string | null
  verified: boolean
  failure_reason: string | null
  submitted_at: string
  verified_at: string | null
  event_id: string | null
  // Phase 2 lifecycle
  expires_at: string | null
  revoked_at: string | null
  revoked_by: string | null
  revoked_reason: string | null
  expired_emitted_at: string | null
}

export interface AttestationListResponse {
  items: AttestationRecord[]
  count: number
  limit: number
  offset: number
}

export interface AttestationReverifyResponse {
  attestation_id: string
  circuit_id: string
  verified: boolean
  re_verified_at: string
  public_inputs: Record<string, unknown>
  failure_reason: string | null
  revoked: boolean
  expired: boolean
}

export interface RevokeAttestationResponse {
  attestation_id: string
  revoked_at: string
  revoked_by: string
  revoked_reason: string | null
  already_revoked: boolean
}

// ─── Phase 4 bundle + signing pubkey ───────────────────────────────────
export interface AttestationBundle {
  attestation_id: string
  agent_did: string
  circuit_id: string
  circuit_version: string
  public_inputs: Record<string, unknown>
  proof_b64: string
  proof_hash: string
  policy_parameters_hash: string | null
  verified: boolean
  verified_at: string | null
  submitted_at: string | null
  issuer_registry: string
  valid_until: string
  revoked: boolean
  revoked_at: string | null
  revoked_reason: string | null
  signature_alg: string
  signature: string
  signature_pubkey_id?: string
}

export interface SigningPubkey {
  alg: string
  pubkey_b64: string
  pubkey_id: string
  issuer_registry: string
}

export interface VerifyBundleResponse {
  verified: boolean
  reason: string
  bundle_summary: {
    attestation_id?: string
    agent_did?: string
    circuit_id?: string
    issuer_registry?: string
    valid_until?: string
    revoked?: boolean
    signature_pubkey_id?: string
  }
}

// ─── Phase 5 schedule ──────────────────────────────────────────────────
export interface AttestationSchedule {
  id: string
  agent_did: string
  circuit_id: string
  interval_hours: number
  enabled: boolean
  last_attestation_at: string | null
  next_due_at: string
  last_reminder_at: string | null
  created_at: string
  updated_at: string
}

export interface ScheduleListResponse {
  items: AttestationSchedule[]
  count: number
}

// ─── Submit ────────────────────────────────────────────────────────────
export interface SubmitAttestationRequest {
  circuit_id: string
  proof_data: { proof_bytes: string; format?: string }
  public_inputs: Record<string, unknown>
}

export interface SubmitAttestationResponse {
  status: 'verified' | 'failed'
  circuit_id: string
  message: string
  public_inputs: Record<string, unknown>
  attestation_id: string | null
  /** 1 only for the first verified attestation per agent, circuit and UTC day; null otherwise */
  reputation_delta: number | null
  /** What the proof carries: its public inputs and the commitment it outputs, as decimal strings */
  proof_public_values?: Record<string, string> | null
  /** Why the proof did not verify (null when it did) */
  reason?: string | null
}

// ─── Filters ──────────────────────────────────────────────────────────
export interface AttestationListFilters {
  agent_did?: string
  circuit_id?: string
  verified?: boolean
  since?: string  // ISO8601
  until?: string  // ISO8601
  limit?: number
  offset?: number
}

export interface AttestationByDidFilters {
  circuit_id?: string
  verified?: boolean
  limit?: number
  offset?: number
}


export class AttestationsApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  // ─── Phase 1: list / get / by-did / re-verify ────────────────────
  async listAttestations(filters: AttestationListFilters = {}): Promise<AttestationListResponse> {
    const { data } = await this.client.get<AttestationListResponse>(
      '/attestations',
      { params: filters },
    )
    return data
  }

  async getAttestation(attestationId: string): Promise<AttestationRecord> {
    const { data } = await this.client.get<AttestationRecord>(
      `/attestations/${attestationId}`,
    )
    return data
  }

  async reverifyAttestation(attestationId: string): Promise<AttestationReverifyResponse> {
    const { data } = await this.client.get<AttestationReverifyResponse>(
      `/attestations/${attestationId}/verify`,
    )
    return data
  }

  /**
   * Public — no auth required. Used by the agent-profile widget.
   */
  async getAttestationsByDid(
    agentDid: string,
    filters: AttestationByDidFilters = {},
  ): Promise<AttestationListResponse> {
    const did = encodeURIComponent(agentDid)
    const { data } = await this.client.get<AttestationListResponse>(
      `/agents/by-did/${did}/attestations`,
      { params: filters },
    )
    return data
  }

  // ─── Submit ──────────────────────────────────────────────────────
  async submitAttestation(req: SubmitAttestationRequest): Promise<SubmitAttestationResponse> {
    const { data } = await this.client.post<SubmitAttestationResponse>(
      '/attestations/submit',
      req,
    )
    return data
  }

  // ─── Phase 2: revoke ─────────────────────────────────────────────
  /** Agent self-revoke own attestation. */
  async revokeAttestation(
    attestationId: string,
    reason?: string,
  ): Promise<RevokeAttestationResponse> {
    const { data } = await this.client.post<RevokeAttestationResponse>(
      `/attestations/${attestationId}/revoke`,
      { reason: reason ?? null },
    )
    return data
  }

  /** Admin revoke (any agent's attestation). */
  async adminRevokeAttestation(
    attestationId: string,
    reason?: string,
  ): Promise<RevokeAttestationResponse> {
    const { data } = await this.client.post<RevokeAttestationResponse>(
      `/attestations/admin/${attestationId}/revoke`,
      { reason: reason ?? null },
    )
    return data
  }

  // ─── Phase 4: bundle + verify ────────────────────────────────────
  async getBundle(attestationId: string): Promise<AttestationBundle> {
    const { data } = await this.client.get<AttestationBundle>(
      `/attestations/${attestationId}/bundle`,
    )
    return data
  }

  async getSigningPubkey(): Promise<SigningPubkey> {
    const { data } = await this.client.get<SigningPubkey>(
      '/attestations/signing-pubkey',
    )
    return data
  }

  async verifyBundle(
    bundle: AttestationBundle,
    issuer_pubkey_b64?: string,
  ): Promise<VerifyBundleResponse> {
    const body: { bundle: AttestationBundle; issuer_pubkey_b64?: string } = { bundle }
    if (issuer_pubkey_b64) body.issuer_pubkey_b64 = issuer_pubkey_b64
    const { data } = await this.client.post<VerifyBundleResponse>(
      '/public/attestations/verify-bundle',
      body,
    )
    return data
  }

  // ─── Phase 5: schedules ──────────────────────────────────────────
  async listMySchedules(): Promise<ScheduleListResponse> {
    const { data } = await this.client.get<ScheduleListResponse>(
      '/attestations/schedules',
    )
    return data
  }

  async createSchedule(
    circuit_id: string,
    interval_hours: number,
  ): Promise<AttestationSchedule> {
    const { data } = await this.client.post<AttestationSchedule>(
      '/attestations/schedules',
      { circuit_id, interval_hours },
    )
    return data
  }

  async disableSchedule(scheduleId: string): Promise<{ status: string; schedule_id: string }> {
    const { data } = await this.client.delete<{ status: string; schedule_id: string }>(
      `/attestations/schedules/${scheduleId}`,
    )
    return data
  }

  async listSchedulesByDid(agentDid: string): Promise<ScheduleListResponse> {
    const did = encodeURIComponent(agentDid)
    const { data } = await this.client.get<ScheduleListResponse>(
      `/agents/by-did/${did}/attestation-schedules`,
    )
    return data
  }

  // ─── Circuit registry (Phase 5) ─────────────────────────────────
  /**
   * List all circuits available for attestation. Public — no auth required.
   * Used to populate dropdowns in the agent + admin views.
   */
  async listCircuits(): Promise<CircuitInfo[]> {
    const { data } = await this.client.get<{ circuits: CircuitInfo[] }>('/circuits/')
    return data.circuits ?? []
  }
}

/** A policy limit this registry enforces: the proof's limit must be at most (or at least) `limit`. */
export interface CircuitPolicyRule {
  rule: 'at_most' | 'at_least'
  limit: number
}

/**
 * One entry of GET /circuits/. v2.0.0 circuits are `active` and publish their verification key, metadata, public
 * inputs and outputs and the policy in force; v1.0.0 circuits are `retired` (their policy limits were private inputs
 * nothing bound) and name the circuit that replaces them.
 */
export interface CircuitInfo {
  circuit_id: string
  name: string
  status?: 'active' | 'retired'
  acir_url: string
  acir_available?: boolean
  source_url: string
  nargo_toml_url: string
  vk_url?: string
  metadata_url?: string
  public_inputs?: string[]
  public_outputs?: string[]
  policy?: Record<string, CircuitPolicyRule>
  superseded_by?: string
}

/**
 * Whether a circuit is retired. The circuits list says so when it was read; without it, a v1.0.0 policy circuit is
 * retired by rule (the registry refuses its proofs unless ZKP_ACCEPT_V1_CIRCUITS=true).
 */
export function isRetiredCircuit(circuitId: string, circuits: CircuitInfo[] = []): boolean {
  const listed = circuits.find((c) => c.circuit_id === circuitId)
  if (listed?.status) return listed.status === 'retired'
  return /\/v1\.0\.0$/.test(circuitId || '')
}

/** The circuit that replaces a retired one, from the list or by rule (`<name>/v2.0.0`). */
export function circuitSuccessor(circuitId: string, circuits: CircuitInfo[] = []): string | null {
  if (!isRetiredCircuit(circuitId, circuits)) return null
  const listed = circuits.find((c) => c.circuit_id === circuitId)
  return listed?.superseded_by ?? circuitId.replace(/\/v1\.0\.0$/, '/v2.0.0')
}

export const attestationsApi = new AttestationsApi()
