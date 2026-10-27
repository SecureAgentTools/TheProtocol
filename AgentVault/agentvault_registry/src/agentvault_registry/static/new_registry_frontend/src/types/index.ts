// Core type definitions for the Sovereign Registry

// User types
export interface User {
  id: string
  developer_id?: number  // Backend uses this for developer identity
  email: string
  name?: string
  role: 'admin' | 'developer' | 'agent' | 'user'
  is_admin?: boolean  // Backend uses this boolean flag (super-flag — passes all sub-flags)
  is_active?: boolean
  /** Whether the developer confirmed their email (GET /developers/me). Undefined = not said (an older registry). */
  is_verified?: boolean
  created_at: string
  updated_at?: string
  // Granular admin sub-flags (P3.1, 2026-05-08). Backend ships these on
  // /developers/me (DeveloperRead schema). Frontend uses them via
  // composables/usePermissions to gate per-area admin views.
  // is_admin === true overrides all of these (super-flag semantics).
  admin_treasury?: boolean
  admin_support?: boolean
  admin_enforcement?: boolean
  admin_federation?: boolean
  admin_platform?: boolean
  // Federation operator status (existing — not new but un-typed in older code)
  is_federation_operator?: boolean
  federation_operator_status?: string | null
  // PB-1 backer flare cosmetic (2026-05-09). Null until first fiat purchase.
  // 2026-05-11 §11: shadow_chancellor added (cumulative ≥ €500 hidden tier).
  flare_tier?: 'sentinel' | 'architect' | 'founder' | 'shadow_chancellor' | null
  flare_granted_at?: string | null
  // Hardening: unique flare identifier + buyer-supplied customization.
  flare_id?: string | null
  flare_display_name?: string | null
  flare_tagline?: string | null
  flare_logo_url?: string | null
  flare_link_url?: string | null
  flare_cause?: string | null
  flare_accent_color?: string | null
  // 2026-05-11 §12: dual-slot display selection. Independent of flare_tier
  // (which stays as the rolled-up "highest earned"). Selection columns drive
  // what's displayed in each slot.
  selected_corner_flare?: 'sentinel' | 'architect' | 'founder' | 'operator' | 'commander' | null
  selected_encirclement_flare?: 'shadow_chancellor' | null
  // 2026-05-12 §14: encirclement aesthetic variant. Tier=rank, variant=flavor.
  // Default 'sauron' on Shadow Chancellor grant; user can switch via FlareManager.
  flare_encirclement_variant?:
    | 'sauron' | 'goth' | 'obsidian' | 'void'
    | 'aurora' | 'phoenix' | 'crystal'
    | 'blackhole' | 'halloween'
    | 'inferno' | 'glacier' | 'matrix'
    | 'galaxy' | 'ink' | 'circuit'
    | 'yule' | 'sakura' | 'solstice' | 'harvest'
    | null
  // 2026-05-13 §28: broken-machine OVERLAY axis. Independent of variant.
  // NULL = no overlay; values from ENCIRCLEMENT_OVERLAYS set.
  flare_encirclement_overlay?:
    | 'glitch' | 'cascade'
    | 'panic-a' | 'panic-b' | 'panic-c'
    | null
  // 2026-05-13 §20: admin-only corner badge variant. NULL → render the
  // default tier icon; non-null swaps to an inline-SVG design.
  flare_corner_variant?:
    | 'rocket' | 'crown' | 'vault' | 'gavel' | 'atom' | 'network'
    | null
  // 2026-05-12 §15: celebration ack timestamp. NULL = upgrade modal still
  // pending; set after user clicks through the FlareCelebrationModal.
  flare_celebration_seen_at?: string | null
  // W2 (2026-05-09) — User-initiated GDPR Art. 17 erasure state.
  // null ≡ active (default). 'pending_deletion' during the 14-day cooling-off.
  // 'anonymized' is terminal (and unreachable through this type — the
  // password is wiped at anonymize-time, so the user can't log in to see it).
  deletion_status?: 'pending_deletion' | 'anonymized' | null
  deletion_requested_at?: string | null
  anonymized_at?: string | null
  // §LEGALKIT (Terms § 10.2): served by /developers/me; the console asks again when required
  tos_accepted_version?: string | null
  tos_current_version?: string | null
  tos_reconsent_required?: boolean
  // V0414: the documents to accept now ('terms', 'operators'); the operator document only for an account that holds operators
  reconsent_documents?: string[]
}

// Agent types
export interface Agent {
  did: string
  id?: string // Alternative ID
  name: string
  description?: string
  owner_id: string
  owner_name?: string
  endpoint?: string // Deprecated, use endpoints
  endpoints?: {
    webhook_url?: string
    health_check_url?: string
  }
  capabilities: string[]
  status: 'active' | 'inactive' | 'maintenance' | 'revoked'
  visibility?: 'public' | 'private'
  reputation?: number
  verified?: boolean
  metadata?: Record<string, any>
  metrics?: AgentMetrics
  config?: AgentConfig
  api_key?: string
  registry_id?: string
  registry_name?: string
  created_at: string
  updated_at: string
  card_data?: Record<string, any> // Added to match backend schema
  
  // Authentication credentials (only available when creating or from local storage)
  client_id?: string
  client_secret?: string
  
  // Balance information (populated when fetching with balances)
  liquidBalance?: number
  stakedBalance?: number
  totalBalance?: number
  hasCredentials?: boolean

  // Extended fields returned by backend / used in UI
  liquid_balance?: number | string
  staked_balance?: number | string
  total_balance?: number | string
  reputation_score?: number
  last_active_at?: string
  agent_did?: string        // legacy alias for did
  is_active?: boolean
  is_verified?: boolean
  hasInvalidCredentials?: boolean
  balance?: number           // backwards-compat alias for totalBalance
  termsOfServiceUrl?: string
  privacyPolicyUrl?: string
}

// Agent metrics
export interface AgentMetrics {
  total_requests: number
  success_rate: number
  avg_response_time: number
  uptime_percentage?: number
  last_active?: string
}

// Agent configuration
export interface AgentConfig {
  auto_start?: boolean
  max_concurrent_tasks?: number
  timeout_seconds?: number
  retry_attempts?: number
  [key: string]: any
}

// Token/TEG types
export interface TokenBalance {
  agent_did: string
  balance: string
  staked_balance: string
  available_balance: string
  last_updated: string
}

export interface TokenTransfer {
  from_did: string
  to_did: string
  amount: string
  memo?: string
}

export interface Transaction {
  id: string
  from_did: string
  to_did: string
  amount: string
  fee: string
  type: 'transfer' | 'stake' | 'unstake' | 'reward'
  status: 'pending' | 'completed' | 'failed'
  memo?: string
  created_at: string
}

// Staking types
export interface StakePosition {
  id: string
  agent_did: string
  amount: string
  rewards_earned: string
  staked_at: string
  unlocks_at?: string
}

// Governance types
export interface Proposal {
  id: string
  title: string
  description: string
  proposer_did: string
  status: 'draft' | 'active' | 'passed' | 'rejected' | 'executed'
  votes_for: number
  votes_against: number
  voting_ends_at: string
  created_at: string
}

export interface Vote {
  proposal_id: string
  voter_did: string
  vote: 'for' | 'against' | 'abstain'
  weight: string
  voted_at: string
}

// Federation types
export interface Registry {
  id: string
  name: string
  url: string
  public_key: string
  status: 'active' | 'inactive' | 'pending' | 'rejected' | 'disconnected' | 'syncing'
  trusted: boolean
  last_seen: string
  // Extended UI fields populated by federation API service
  agents?: number
  agentCount?: number
  health?: number
  latency?: number | null
  base_url?: string
  lastSync?: string
  description?: string
  version?: string
  publicKey?: string
  metadata?: Record<string, any>
  activeAgents?: number
  // Admin fields
  owner_id?: string | number
  owner_developer_id?: number
  admin_contact_email?: string
  registered_at?: string
  approved_at?: string | null
  approved_by?: string | number
  approved_by_developer_id?: number | null
  discovery_auth_info?: any
  interaction_auth_info?: any
}

// API Response types
export interface ApiResponse<T> {
  data: T
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  limit: number
  pages?: number
  totalPages?: number // Alternative naming
}

export interface ApiError {
  message: string
  code?: string
  details?: Record<string, any>
}

// DTO types for API requests
export interface CreateAgentDto {
  name: string
  description?: string
  endpoint?: string // Deprecated
  endpoints?: {
    webhook_url?: string
    health_check_url?: string
  }
  capabilities: string[]
  visibility?: 'public' | 'private'
  config?: AgentConfig
  metadata?: Record<string, any>
  bootstrap_token: string
}

export interface UpdateAgentDto {
  name?: string
  description?: string
  endpoint?: string // Deprecated
  endpoints?: {
    webhook_url?: string
    health_check_url?: string
  }
  capabilities?: string[]
  status?: 'active' | 'inactive' | 'maintenance'
  visibility?: 'public' | 'private'
  config?: AgentConfig
  metadata?: Record<string, any>
}

export interface LoginDto {
  username: string
  password: string
  role: 'admin' | 'developer' | 'agent'
}

export interface RegisterDto {
  username: string
  password: string
  email?: string
  role: 'developer' | 'agent'
}


