import { apiClient } from './client'

// Types
export interface Webhook {
  id: string
  developer_id?: number
  url: string
  events: string[]
  secret?: string
  is_active: boolean
  created_at: string
  updated_at?: string
  last_triggered_at?: string | null
  failure_count?: number
}

export interface WebhookDelivery {
  id: string
  webhook_id?: string
  event_type: string
  payload?: any                       // backend returns the request payload (Build #1)
  response_status?: number | null
  response_body?: string | null       // backend returns response body (Build #1, truncated to 5KB)
  delivered_at: string
  retry_count?: number
  next_retry_at?: string | null
  error?: string | null
  error_message?: string | null
  success?: boolean
}

/** Build #1 (2026-05-07) — supported status filters for the /deliveries query. */
export type DeliveryStatusFilter = 'success' | 'failed' | 'pending' | 'retried' | null

export interface CreateWebhookRequest {
  url: string
  events: string[]
}

export interface UpdateWebhookRequest {
  url?: string
  events?: string[]
  is_active?: boolean
}

export interface TestWebhookResponse {
  delivery_id: string
  status: number | null
  success: boolean
  error: string | null
}

// Available webhook events
export const WEBHOOK_EVENTS = {
  // Agent Events
  AGENT_CREATED: 'agent.created',
  AGENT_UPDATED: 'agent.updated',
  AGENT_DELETED: 'agent.deleted',
  AGENT_STATUS_CHANGED: 'agent.status_changed',
  
  // Lock events
  STAKING_POSITION_CREATED: 'staking.position_created',
  STAKING_POSITION_UPDATED: 'staking.position_updated',
  STAKING_POSITION_CLOSED: 'staking.position_closed',
  STAKING_REWARDS_CLAIMED: 'staking.rewards_claimed',
  
  // Governance Events
  PROPOSAL_CREATED: 'governance.proposal_created',
  PROPOSAL_PASSED: 'governance.proposal_passed',
  PROPOSAL_FAILED: 'governance.proposal_failed',
  VOTE_CAST: 'governance.vote_cast',
  
  // Federation Events
  PEER_ADDED: 'federation.peer_added',
  PEER_REMOVED: 'federation.peer_removed',
  SYNC_COMPLETED: 'federation.sync_completed',
  
  // Contract Events
  CONTRACT_CREATED: 'contract.created',
  CONTRACT_ACCEPTED: 'contract.accepted',
  CONTRACT_COMPLETED: 'contract.completed',
  CONTRACT_DISPUTED: 'contract.disputed',
  
  // Dispute Events
  DISPUTE_CREATED: 'dispute.created',
  DISPUTE_EVIDENCE_SUBMITTED: 'dispute.evidence_submitted',
  DISPUTE_RESOLVED: 'dispute.resolved'
}

// Event categories for grouping in UI
export const EVENT_CATEGORIES = {
  'Agent Events': [
    WEBHOOK_EVENTS.AGENT_CREATED,
    WEBHOOK_EVENTS.AGENT_UPDATED,
    WEBHOOK_EVENTS.AGENT_DELETED,
    WEBHOOK_EVENTS.AGENT_STATUS_CHANGED
  ],
  'Lock Events': [
    WEBHOOK_EVENTS.STAKING_POSITION_CREATED,
    WEBHOOK_EVENTS.STAKING_POSITION_UPDATED,
    WEBHOOK_EVENTS.STAKING_POSITION_CLOSED,
    WEBHOOK_EVENTS.STAKING_REWARDS_CLAIMED
  ],
  'Governance Events': [
    WEBHOOK_EVENTS.PROPOSAL_CREATED,
    WEBHOOK_EVENTS.PROPOSAL_PASSED,
    WEBHOOK_EVENTS.PROPOSAL_FAILED,
    WEBHOOK_EVENTS.VOTE_CAST
  ],
  'Federation Events': [
    WEBHOOK_EVENTS.PEER_ADDED,
    WEBHOOK_EVENTS.PEER_REMOVED,
    WEBHOOK_EVENTS.SYNC_COMPLETED
  ],
  'Contract Events': [
    WEBHOOK_EVENTS.CONTRACT_CREATED,
    WEBHOOK_EVENTS.CONTRACT_ACCEPTED,
    WEBHOOK_EVENTS.CONTRACT_COMPLETED,
    WEBHOOK_EVENTS.CONTRACT_DISPUTED
  ],
  'Dispute Events': [
    WEBHOOK_EVENTS.DISPUTE_CREATED,
    WEBHOOK_EVENTS.DISPUTE_EVIDENCE_SUBMITTED,
    WEBHOOK_EVENTS.DISPUTE_RESOLVED
  ]
}

/**
 * §FEPARITY-R4 (2026-08-04) — human labels for the event-name prefixes the SERVER
 * returns. Grouping is derived from the prefix, never from a hand-kept list: a new
 * backend event lands in its category automatically instead of vanishing from the UI.
 * An unlisted prefix is title-cased rather than dropped.
 */
const CATEGORY_LABELS: Record<string, string> = {
  agent: 'Agent Events',
  staking: 'Lock Events',
  governance: 'Governance Events',
  federation: 'Federation Events',
  frame_federation: 'Federation Events',
  contract: 'Contract Events',
  dispute: 'Dispute Events',
  attestation: 'Attestation Events',
  developer: 'Developer Events',
  operator: 'Operator Events',
  treasury: 'Treasury Events',
  supply: 'Supply Events',
  bridge: 'Bridge Events',
  webhook: 'Webhook Events',
  game: 'Arena Events',
}

export function categoryForEvent(event: string): string {
  const prefix = (event.split('.')[0] || '').trim()
  if (CATEGORY_LABELS[prefix]) return CATEGORY_LABELS[prefix]
  if (!prefix) return 'Other Events'
  return prefix.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + ' Events'
}

/** Group a flat event list into {category: events[]} for the picker. */
export function groupEvents(events: string[]): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const e of [...events].sort()) {
    const cat = categoryForEvent(e)
    ;(out[cat] ||= []).push(e)
  }
  return out
}

class WebhookService {
  // §FEPARITY-R4: the CANONICAL webhook router. The legacy `/developers/webhooks`
  // surface this used to call is a strict subset backed by the SAME DeveloperWebhook
  // rows (verified live: both return the same webhooks for the same developer), but it
  // has no redeliver, no supported-events (404), no status filter, and omits
  // payload/response_body/next_retry_at — so the deliveries drill-down and the filter
  // chips were both inert. Same storage, same ownership scoping, strictly more surface.
  private basePath = '/webhooks'

  /**
   * BUG-003 FIX: Map backend webhook fields to frontend Webhook interface.
   * Backend returns 'active' (bool) and 'last_triggered' (string|null),
   * but the frontend Webhook type expects 'is_active' and 'last_triggered_at'.
   */
  private transformWebhook(data: any): Webhook {
    return {
      id: data.id,
      developer_id: data.developer_id,
      url: data.url,
      events: data.events || [],
      secret: data.secret,
      // Map 'active' → 'is_active' (backend uses 'active', frontend uses 'is_active')
      // BUG-003 FIX: Use Boolean() to ensure truthy/falsy conversion is reliable
      is_active: Boolean(data.is_active ?? data.active ?? false),
      created_at: data.created_at,
      updated_at: data.updated_at,
      // Map 'last_triggered' → 'last_triggered_at'
      last_triggered_at: data.last_triggered_at || data.last_triggered || null,
      failure_count: data.failure_count || 0
    }
  }

  async listWebhooks(): Promise<Webhook[]> {
    try {
      const response = await apiClient.get(this.basePath)
      const raw = Array.isArray(response.data) ? response.data : []
      return raw.map((w: any) => this.transformWebhook(w))
    } catch (error) {
      console.error('Failed to fetch webhooks:', error)
      throw error
    }
  }

  async createWebhook(data: CreateWebhookRequest): Promise<Webhook> {
    try {
      const response = await apiClient.post(this.basePath, data)
      return this.transformWebhook(response.data)
    } catch (error) {
      console.error('Failed to create webhook:', error)
      throw error
    }
  }

  async updateWebhook(id: string, data: UpdateWebhookRequest): Promise<Webhook> {
    try {
      // §FEPARITY-R4: the canonical router's WebhookUpdate takes `is_active`. The old
      // `active` translation was for the legacy surface; sending it here would be
      // silently ignored by pydantic and the toggle would no-op.
      const backendData: any = { ...data }
      const response = await apiClient.put(`${this.basePath}/${id}`, backendData)
      return this.transformWebhook(response.data)
    } catch (error) {
      console.error('Failed to update webhook:', error)
      throw error
    }
  }

  async deleteWebhook(id: string): Promise<void> {
    try {
      await apiClient.delete(`${this.basePath}/${id}`)
    } catch (error) {
      console.error('Failed to delete webhook:', error)
      throw error
    }
  }

  async testWebhook(id: string): Promise<TestWebhookResponse> {
    try {
      const response = await apiClient.post(`${this.basePath}/${id}/test`)
      return response.data
    } catch (error) {
      console.error('Failed to test webhook:', error)
      throw error
    }
  }

  async getDeliveries(
    id: string,
    limit = 20,
    offset = 0,
    statusFilter: DeliveryStatusFilter = null,
  ): Promise<{ total: number; deliveries: WebhookDelivery[] }> {
    try {
      const params: Record<string, any> = { limit, offset }
      if (statusFilter) params.status = statusFilter
      const response = await apiClient.get(`${this.basePath}/${id}/deliveries`, { params })
      const data = response.data
      return {
        total: data.total ?? data.deliveries?.length ?? 0,
        deliveries: Array.isArray(data.deliveries) ? data.deliveries : []
      }
    } catch (error) {
      console.error('Failed to fetch webhook deliveries:', error)
      throw error
    }
  }

  /**
   * §FEPARITY-R4 — the LIVE event catalog.
   *
   * The picker used to render a hand-kept map that had drifted to 22 of the backend's
   * 49 events: `agent.slashed`, `agent.suspended`, `supply.invariant_breach`,
   * `contract.milestone_released` and 23 others fire on the server and could not be
   * subscribed to from the UI at all. The server has always served the real list.
   *
   * Falls back to the static map so a stale server (or an offline moment) degrades to
   * the old behaviour rather than an empty picker — never worse than before.
   */
  async getSupportedEvents(): Promise<{ events: string[]; live: boolean }> {
    try {
      const response = await apiClient.get(`${this.basePath}/events/supported`)
      const events = Array.isArray(response.data?.events) ? response.data.events : []
      if (events.length) return { events, live: true }
    } catch (error) {
      console.warn('Live webhook event catalog unavailable, using bundled list:', error)
    }
    return { events: (Object.values(EVENT_CATEGORIES) as string[][]).flat(), live: false }
  }

  /**
   * Re-send a past delivery's original payload through the live delivery path.
   * A fresh delivery row records the outcome; the original is left untouched for audit.
   */
  async redeliver(
    webhookId: string,
    deliveryId: string,
  ): Promise<{ success: boolean; status_code: number | null; delivery_id: string; redelivery_of: string }> {
    const response = await apiClient.post(
      `${this.basePath}/${webhookId}/deliveries/${deliveryId}/redeliver`,
    )
    return response.data
  }

  // Helper method to get event display name
  getEventDisplayName(event: string): string {
    const parts = event.split('.')
    if (parts.length === 2) {
      return parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
    }
    return event
  }

  // Helper method to get event category (prefix-derived — never returns null for a
  // real event, so a newly added backend event is still grouped and shown).
  getEventCategory(event: string): string | null {
    return event ? categoryForEvent(event) : null
  }
}

export const webhookService = new WebhookService()
