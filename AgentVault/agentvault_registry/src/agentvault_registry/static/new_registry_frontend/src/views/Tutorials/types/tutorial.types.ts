// ============================================================================
// TheProtocol Tutorial System — Type Definitions
// ============================================================================

// === TRACK DEFINITION ===

export interface TutorialTrack {
  id: string                              // URL slug: "agent-lifecycle"
  title: string                           // "Agent Lifecycle"
  subtitle: string                        // "From identity to discovery"
  description: string                     // Longer explanation for hub card
  icon: string                            // Icon name (mdi format): "mdi:user-plus"
  color: string                           // Tailwind color class base: "violet"
  gradientFrom: string                    // Tailwind: "from-violet-600"
  gradientTo: string                      // Tailwind: "to-purple-700"
  estimatedMinutes: number                // 8
  steps: TutorialStep[]
  prerequisites?: string[]                // Track IDs that must be completed first
  completionTitle?: string                // Achievement title: "First Contact", etc.
  // Access-control LOCK (optional). When set, the track renders LOCKED on the
  // TutorialHub and can't be launched by users who don't qualify. `is_admin`
  // superusers bypass both. Leave BOTH unset for open tracks (the default).
  requireAdmin?: boolean                  // Gate behind the is_admin super-flag
  requireFlag?: string                    // Gate behind an RBAC flag: "admin_enforcement"
  // Offered only where the registry's public config says this switch is on (the guided tours' rule, TutorialHub's
  // tourOffered): the staking track where staking is (his word 2026-10-25: "staking doesnt exist anymore in the way it did")
  requiresRegistryFlag?: 'staking_enabled' | 'fiat_onramp_enabled'
}

// === STEP DEFINITION ===

export interface TutorialStep {
  id: string                              // Unique within track: "authenticate"
  stepNumber: number                      // 1-indexed display number
  title: string                           // "Authenticate as Developer"
  subtitle: string                        // "Obtain your JWT access token"
  explanation: string                     // Multi-line markdown explanation
  apiCall: ApiCallDefinition
  captures?: CaptureRule[]                // What to extract from response
  validation: ValidationRule              // How to determine success
  requiresStepId?: string                // Previous step ID that must complete
  notes?: string                          // Optional post-step notes/tips
}

export interface ApiCallDefinition {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  path: string                            // "/onboard/bootstrap/request-token"
  description: string                     // One-line: "Request a single-use bootstrap token"
  pathParams?: Record<string, string>     // { "did": "$agentDid" } — resolved at runtime
  headers?: Record<string, string>        // Extra headers to display (informational)
  body?: Record<string, any> | null       // Request body (null/undefined for GET)
  bodyDynamic?: DynamicBodyField[]        // Fields that reference captured values
  authType: AuthType
  authTokenRef?: string                   // Captured value key for auth token: "$developerToken"
  targetBase?: string                     // Direct API call base URL (e.g. '/sandbox-b')
                                          // When set, bypasses proxy and calls targetBase/api/v1/... directly
  formEncoded?: boolean                   // If true, send body as application/x-www-form-urlencoded
}

export type AuthType = 'developer' | 'agent' | 'bootstrap' | 'admin' | 'none'

export interface DynamicBodyField {
  jsonPath: string                        // Dot-path in body: "target_agent_did"
  capturedKey: string                     // Key in capturedValues: "agentDid"
}

// === CAPTURE ===

export interface CaptureRule {
  key: string                             // Storage key: "agentDid"
  responsePath: string                    // Dot-path in response JSON: "agent_did"
  displayLabel: string                    // Human label: "Agent DID"
  sensitive?: boolean                     // If true, mask in display (secrets)
}

// === VALIDATION ===

export interface ValidationRule {
  successStatusCodes: number[]            // [200, 201]
  requiredResponseKeys?: string[]         // ["agent_did", "client_id"]
  failureMessage?: string                 // Custom message on failure
}

// === RUNTIME STATE ===

export interface StepResult {
  stepId: string
  status: 'pending' | 'executing' | 'success' | 'failed' | 'skipped'
  request: {
    method: string
    url: string                           // Full URL shown to user
    headers: Record<string, string>
    body: any | null
  }
  response?: {
    statusCode: number
    body: any
    timeMs: number
  }
  capturedValues?: Record<string, any>    // Values captured from this step
  error?: string
  executedAt?: string                     // ISO timestamp
}

export interface SavedTrackProgress {
  trackId: string
  completedStepIds: string[]
  capturedValues: Record<string, any>
  lastStepIndex: number
  savedAt: string                         // ISO timestamp
  firstStepAt?: string                    // ISO timestamp of first step execution
  completedAt?: string                    // ISO timestamp of track completion
}

// === EVENT STORE WEBSOCKET ===

export interface EventStoreEvent {
  id: string
  event_type: string
  aggregate_id: string
  data: Record<string, any>
  timestamp: string
  version: number
  receivedAt: string                      // Local timestamp when WS received it
}
