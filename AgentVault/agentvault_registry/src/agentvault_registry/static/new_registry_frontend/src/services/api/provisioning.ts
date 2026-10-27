/**
 * services/api/provisioning.ts — Flare-gated cloud-op self-service (PB-1 §67).
 *
 * Backend: routers/operator_self_service.py (mainframe-only).
 * Endpoints:
 *   GET  /me/provisioning-eligibility   — eligibility state (dev JWT)
 *   POST /operators/self-provision      — gated provision (dev JWT, 402 if locked)
 *
 * The eligibility GET is the single source of truth for the OperatorPortal
 * Eligibility tab + the Provision-button gate; do NOT compute "is_unlocked"
 * client-side — the backend returns it consistent with its own NOW().
 */
import { apiClient } from './client'

export interface ProvisioningEligibility {
  is_unlocked: boolean
  unlocked_until: string | null
  months_total_purchased: number
  months_remaining: number
  last_extended_at: string | null
  eur_per_month: number
}

// §pass66 (2026-05-22) — Path C / Advanced Provisioning Form types.
// Mirror the backend `schemas.RegistryCardOperatorPut` shape — operator-
// editable v0.3 subset. Sent inside SelfProvisionRequest.card_overrides
// when the user fills the Advanced tab; the central reg applies them to
// the newly-provisioned op via cross-reg PUT to /admin/registry-card.

export interface ProvisionVisualOverride {
  orb_color?: string
  orb_glow_color?: string
  orb_pulse_speed_hz?: number
  orb_size_px?: number
  halo_enabled?: boolean
  halo_thickness?: number
  theme?: 'neural' | 'sovereign' | 'custom'
  flare_corner_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
}

export interface ProvisionPersonaOverride {
  display_name?: string
  bio?: string
  contact_email?: string
  company?: string
  url?: string
  github_url?: string
  twitter_handle?: string
  timezone?: string
  location_label?: string
  operator_avatar_url?: string
  successor_contact?: string
}

export interface ProvisionLinksOverride {
  whitepaper?: string
  docs?: string
  github_source?: string
  status_page?: string
  blog?: string
  rss?: string
  terms_of_service?: string
  privacy_policy?: string
  code_of_conduct?: string
  support_url?: string
  discord?: string
  matrix?: string
  incident_log?: string
}

export interface ProvisionCommitmentsOverride {
  data_residency?: string
  gdpr_compliant?: boolean
  incident_disclosure_sla_hours?: number
  uptime_sla_pct?: number
  support_response_hours?: number
  deprecation_notice_days?: number
  open_source_license?: string
  breach_disclosure_policy?: string
  key_rotation_max_days?: number
  card_refresh_max_minutes?: number
  legally_binding_disclaimer?: string
}

export interface RegistryCardOverrides {
  display_name?: string
  description?: string
  tags?: string[]
  operator?: ProvisionPersonaOverride
  visual?: ProvisionVisualOverride
  links?: ProvisionLinksOverride
  commitments?: ProvisionCommitmentsOverride
}

export interface SelfProvisionRequest {
  name: string
  organization?: string | null
  use_case?: string | null
  latitude?: number | null
  longitude?: number | null
  location_label?: string | null
  // §pass66 — Advanced form payload (optional)
  card_overrides?: RegistryCardOverrides | null
}

export interface SelfProvisionResponse {
  status: string
  cloud_url: string
  registry_port: number
  federation_port: number
  containers_started: string[]
  federation_peer_registered: boolean
  federation_license_key: string
  admin_email: string
  admin_password: string
  domain: string
  application_id: string
  eligibility: ProvisioningEligibility
  // §pass66 — Advanced form result fields
  card_overrides_applied?: boolean
  card_overrides_error?: string | null
  // §pass66 — Provisioning genesis funding (100k AVT cross-TEG transfer)
  genesis_funding_applied?: boolean
  genesis_funding_amount_avt?: string | null
  genesis_funding_error?: string | null
}

/** Fetch the current developer's cloud-op provisioning eligibility. */
export async function getMyProvisioningEligibility(): Promise<ProvisioningEligibility> {
  const { data } = await apiClient.get<ProvisioningEligibility>(
    '/me/provisioning-eligibility'
  )
  return data
}

/** Self-provision a cloud-op (gates on eligibility server-side). */
export async function selfProvisionCloudOperator(
  payload: SelfProvisionRequest
): Promise<SelfProvisionResponse> {
  const { data } = await apiClient.post<SelfProvisionResponse>(
    '/operators/self-provision',
    payload
  )
  return data
}
