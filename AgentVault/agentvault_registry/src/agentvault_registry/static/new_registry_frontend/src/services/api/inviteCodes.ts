// Invite-code administration (§OPGUIDE-6, 2026-07-31).
//
// Before this existed the only way to mint an invite code was Swagger or curl, which
// is what the Hetzner hand-off had to document as a workaround. apiClient baseURL is
// already /api/v1, so paths here are relative.
//
// Auth: every admin call below is gated by require_admin_flag("admin_support") server
// side (legacy is_admin also passes). `validateCode` is the one PUBLIC endpoint — it is
// what the register form uses — and is included here so the panel can preflight a code
// without a second module.
import { apiClient } from './client'

/** Computed server-side; never stored. `expired` is what the UI calls "inactive". */
export type InviteCodeStatus = 'active' | 'used' | 'expired'

/**
 * §INVRBAC — the granular admin capabilities an invitation can confer.
 *
 * These five ARE the authorization system: every admin route gates on
 * require_admin_flag("admin_<area>"). The legacy `is_admin` super-flag is not in this
 * list and is never granted by an invitation, because it is a blanket bypass of those
 * gates rather than a capability you can reason about or narrow later.
 *
 * Labels and blurbs live here so the mint form, the confirm dialog and the code table
 * all name a flag the same way.
 */
export type AdminFlag =
  | 'admin_platform' | 'admin_federation' | 'admin_treasury'
  | 'admin_enforcement' | 'admin_support'

export const ADMIN_FLAGS: Array<{ key: AdminFlag; label: string; blurb: string }> = [
  { key: 'admin_platform',    label: 'Platform',    blurb: 'Registry settings, developers, agents, workers, diagnostics. The broadest of the five.' },
  { key: 'admin_federation',  label: 'Federation',  blurb: 'Peer registries, licences, cross-frame topology and operator lifecycle.' },
  { key: 'admin_treasury',    label: 'Treasury',    blurb: 'Funding, treasury movements, fees and the AGORA admin surface. Moves money.' },
  { key: 'admin_enforcement', label: 'Enforcement', blurb: 'Suspensions, slashing, disputes, quarantine and agent enforcement actions.' },
  { key: 'admin_support',     label: 'Support',     blurb: 'Support tickets, broadcasts and invitations. The narrowest useful grant.' },
]

export const flagLabel = (f: string): string =>
  ADMIN_FLAGS.find((x) => x.key === f)?.label ?? f

export interface InviteCode {
  code: string
  /** Full shareable URL with the code pre-filled. Correct on cloud-ops since §OPGUIDE-6. */
  invite_url: string
  expires_at: string | null
  note: string | null
  status: InviteCodeStatus
  use_count: number
  max_uses: number
  /** Redeeming this grants admin capability rather than creating an ordinary developer. */
  grants_admin: boolean
  /**
   * WHICH capability, resolved server-side: empty for an ordinary invitation, and all
   * five for an admin-granting code minted before flags could be chosen (mig 0143).
   */
  admin_flags: AdminFlag[]
  created_at: string
  used_at?: string | null
  created_by_email?: string | null
  used_by_email?: string | null
}

export interface GenerateInviteCodesRequest {
  count: number
  max_uses?: number
  /** null / omitted = never expires. */
  expires_days?: number | null
  note?: string | null
  grants_admin?: boolean
  /**
   * Omit (or send null) with grants_admin to mean "all five", which is what
   * grants_admin meant on its own before this field existed. The server refuses a
   * batch granting a flag the caller does not hold: you cannot invite authority you
   * do not have.
   */
  admin_flags?: AdminFlag[] | null
}

export interface InviteCodeBatch {
  codes: InviteCode[]
  count: number
}

export interface RegistrationConfig {
  beta_invite_required: boolean
  email_verification_required: boolean
}

/**
 * Public, unauthenticated. Drives whether the Invitations tab appears at all —
 * an invite-code panel on a registry with open registration would be a control
 * that governs nothing.
 */
export async function getRegistrationConfig(): Promise<RegistrationConfig> {
  const { data } = await apiClient.get<RegistrationConfig>('/auth/registration-config')
  return data
}

/**
 * List codes newest-first. `status` filtering happens SERVER-side (and, since
 * §OPGUIDE-6, before pagination) but the panel pulls the unfiltered page so it can
 * show honest per-status counts and filter without a round trip.
 */
export async function listInviteCodes(params?: {
  status_filter?: InviteCodeStatus
  limit?: number
  offset?: number
}): Promise<InviteCode[]> {
  const { data } = await apiClient.get<InviteCode[]>('/admin/invite-codes', { params })
  return data
}

export async function generateInviteCodes(
  req: GenerateInviteCodesRequest,
): Promise<InviteCodeBatch> {
  const { data } = await apiClient.post<InviteCodeBatch>('/admin/invite-codes/generate', req)
  return data
}

/**
 * Revoke = DELETE the row. There is no "revoked" state to list afterwards, and the
 * server refuses (404) on a code that has already been used — a redeemed code is
 * history, not a live grant. The panel says so rather than implying it can be undone.
 */
export async function revokeInviteCode(code: string): Promise<void> {
  await apiClient.delete(`/admin/invite-codes/${encodeURIComponent(code)}`)
}

export async function validateInviteCode(
  code: string,
): Promise<{ valid: boolean; reason: string | null }> {
  const { data } = await apiClient.get(`/admin/invite-codes/validate/${encodeURIComponent(code)}`)
  return data
}
