/**
 * services/api/registryCardAdmin.ts — Registry Card v0.3 admin CRUD (2026-05-21).
 *
 *   GET   /api/v1/admin/registry-card                    — preview current card + derived blocks
 *   PUT   /api/v1/admin/registry-card                    — operator-editable subset
 *   POST  /api/v1/admin/registry-card/icon               — multipart icon upload
 *   POST  /api/v1/admin/registry-signing-key/rotate      — mint new EdDSA key
 *   GET   /api/v1/admin/peer-registries/{id}/card        — view federated peer card
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface RegistryCardVisual {
  icon_url?: string | null
  icon_etag?: string | null
  icon_size_bytes?: number | null
  orb_color: string
  orb_glow_color: string
  orb_pulse_speed_hz: number
  orb_size_px: number
  halo_enabled: boolean
  halo_thickness: number
  theme: 'neural' | 'sovereign' | 'custom'
  sovereign_variant?: string | null
  flare_corner_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  schema_compat: string
}

// Catalogs mirror core/registry_identity.py — keep in sync with FlareManager.vue.
// §pass67 (2026-05-23) — 18 new registry-themed encirclements + 8 new overlays.
export const FLARE_ENCIRCLEMENT_VARIANTS = [
  // Original 19 (§14-§20)
  'sauron', 'goth', 'obsidian', 'void', 'aurora', 'phoenix', 'crystal',
  'blackhole', 'halloween', 'inferno', 'glacier', 'matrix', 'galaxy', 'ink',
  'circuit', 'yule', 'sakura', 'solstice', 'harvest',
  // §pass67 wave A — Government / Civic / Official-State (4)
  'chancellery', 'statehouse', 'bastille', 'ministry',
  // §pass67 wave B — NGO / Humanitarian / Multilateral (4)
  'olive-branch', 'cross-shield', 'lighthouse', 'commons',
  // §pass67 wave C — Meme-native / Underground (4); shown as Moonshot, Diamond, Frog, Pixel Shrine
  'moonshot', 'diamond-hands', 'chad-frog', 'pixel-shrine',
  // §pass67 wave D — Regional / Future-mainframe pins (5)
  'savanna', 'andes', 'liberty', 'outback', 'alpine',
  // §pass67 wave E — Hard-money / Treasury (1)
  'bullion-vault',
] as const

export const FLARE_ENCIRCLEMENT_OVERLAYS = [
  // Original 13 (§21-§pass43)
  'glitch', 'cascade', 'panic-a', 'panic-b', 'panic-c',
  'breach', 'refract', 'stutter', 'bleed', 'crackle',
  'feedback', 'spatter', 'unravel',
  // §pass67 wave F — Registry-themed (8)
  'redaction', 'manifold', 'rugpull', 'shilling',
  'brownout', 'stampede', 'karma-debt', 'freeze',
] as const

// Corner-badge variants — mirror core/registry_identity.py:FLARE_CORNER_VARIANTS (9).
// Readable at small (16-22px) badge sizes. Validated at PUT time.
export const FLARE_CORNER_VARIANTS = [
  'sauron', 'phoenix', 'crystal', 'matrix', 'circuit',
  'chancellery', 'diamond-hands', 'liberty', 'bullion-vault',
] as const

export interface RegistryCardOperator {
  developer_id: number
  display_name: string
  bio?: string | null
  contact_email: string
  company?: string | null
  url?: string | null
  github_url?: string | null
  twitter_handle?: string | null
  timezone?: string | null
  location_label?: string | null
  latitude?: number | null
  longitude?: number | null
  operator_since?: string | null
  operator_avatar_url?: string | null
  successor_contact?: string | null
  support_contact?: {
    email?: string | null
    matrix?: string | null
    signal?: string | null
  } | null
}

export interface RegistryCardLinks {
  whitepaper?: string | null
  docs?: string | null
  github_source?: string | null
  status_page?: string | null
  blog?: string | null
  rss?: string | null
  terms_of_service?: string | null
  privacy_policy?: string | null
  code_of_conduct?: string | null
  support_url?: string | null
  discord?: string | null
  matrix?: string | null
  incident_log?: string | null
}

export interface RegistryCardCommitments {
  data_residency?: string | null
  gdpr_compliant: boolean
  incident_disclosure_sla_hours: number
  uptime_sla_pct: number
  support_response_hours: number
  deprecation_notice_days: number
  open_source_license?: string | null
  breach_disclosure_policy?: string | null
  key_rotation_max_days: number
  card_refresh_max_minutes: number
  legally_binding_disclaimer?: string | null
}

export interface RegistryCardV03 {
  registry_card_version: '0.3'
  identity: {
    spiffe_id: string
    registry_name: string
    display_name: string
    trust_domain: string
    public_url: string
    federation_base_url?: string | null
    founded_at: string
    tier: string
  }
  operator: RegistryCardOperator
  description: string
  tags: string[]
  visual: RegistryCardVisual
  capabilities: Record<string, any>
  fees: Record<string, any>
  federation: Record<string, any>
  policy: Record<string, any>
  economic: Record<string, any>
  /** Present only when this deployment has declared a jurisdiction profile.
   *  Computed + signed by the backend; never operator-editable here. */
  compliance?: {
    jurisdiction_profile?: {
      name?: string
      version?: number
      features_denied?: string[]
      declared_at?: string
      profile_hash?: string
      declared_by?: string
    }
  }
  sovereign_agents: any[]
  stats: Record<string, any>
  endpoints: Record<string, any>
  links: RegistryCardLinks
  commitments: RegistryCardCommitments
  lifecycle: {
    status: string
    quarantine_reason?: string | null
    card_updated_at: string
    card_updated_by?: number | null
    card_etag: string
    served_at: string
    next_card_refresh?: string | null
    last_card_fetch_count_24h: number
  }
  signature?: {
    alg: string
    kid: string
    jwks_url: string
    signed_canonical: string[]
    value: string
  } | null
}

export interface RegistryCardPutBody {
  display_name?: string
  description?: string
  tags?: string[]
  operator?: Partial<RegistryCardOperator>
  visual?: Partial<RegistryCardVisual>
  links?: Partial<RegistryCardLinks>
  commitments?: Partial<RegistryCardCommitments>
}

export interface RegistryIconUploadResponse {
  icon_url: string
  icon_etag: string
  icon_size_bytes: number
  format: string
}

export interface RegistryAvatarUploadResponse {
  operator_avatar_url: string
  avatar_size_bytes: number
  format: string
}

export interface RegistrySigningKeyRotation {
  registry_spiffe_id: string
  rotation_seq: number
  algorithm: string
  created_at: string
}

export const registryCardAdminApi = {
  get(): Promise<RegistryCardV03> {
    return apiClient.get('/admin/registry-card').then((r) => r.data as RegistryCardV03)
  },

  put(body: RegistryCardPutBody): Promise<RegistryCardV03> {
    return apiClient.put('/admin/registry-card', body).then((r) => r.data as RegistryCardV03)
  },

  uploadIcon(file: File): Promise<RegistryIconUploadResponse> {
    const fd = new FormData()
    fd.append('file', file)
    return apiClient
      .post('/admin/registry-card/icon', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data as RegistryIconUploadResponse)
  },

  uploadAvatar(file: File): Promise<RegistryAvatarUploadResponse> {
    const fd = new FormData()
    fd.append('file', file)
    return apiClient
      .post('/admin/registry-card/avatar', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data as RegistryAvatarUploadResponse)
  },

  rotateSigningKey(): Promise<RegistrySigningKeyRotation> {
    return apiClient
      .post('/admin/registry-signing-key/rotate')
      .then((r) => r.data as RegistrySigningKeyRotation)
  },

  peerCard(peerId: number): Promise<any> {
    return apiClient.get(`/admin/peer-registries/${peerId}/card`).then((r) => r.data)
  },
}
