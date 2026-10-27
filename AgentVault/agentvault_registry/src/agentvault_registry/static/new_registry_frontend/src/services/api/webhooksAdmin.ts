/**
 * services/api/webhooksAdmin.ts — Cluster-wide admin webhook health wrapper.
 *
 * Build #8 (2026-05-07) — admin oversight for webhook deliveries across
 * all developers. NOT a replacement for the per-developer self-service view
 * at /webhooks (WebhookManager.vue + Build #1 modal); this is the watchtower
 * angle: who's failing, what event types are flowing, recent failures feed.
 *
 * Backend: routers/admin_health.py:get_webhooks_aggregate +
 *          routers/admin_health.py:get_webhooks_recent_deliveries
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export type WebhookPeriod = '24h' | '7d' | '30d' | 'all'

export type DeliveryStatus = 'all' | 'success' | 'failed' | 'pending' | 'retried'

export interface WebhookCounts {
  total: number
  active: number
  inactive: number
  developers_with_webhooks: number
}

export interface DeliveryWindowStats {
  total: number
  success: number
  failed: number
  pending: number
  retried: number
  success_rate_pct: number | null
}

export interface TopEventType {
  event_type: string
  count: number
}

export interface TopFailingWebhook {
  id: string
  url: string
  is_active: boolean
  failure_count: number
  events: string[]
  last_triggered_at: string | null
  developer_id: number
  developer_email: string | null
  developer_name: string | null
}

export interface WebhooksAggregate {
  period: WebhookPeriod
  as_of: string
  webhooks: WebhookCounts
  deliveries_in_window: DeliveryWindowStats
  top_event_types: TopEventType[]
  top_failing_webhooks: TopFailingWebhook[]
}

export interface WebhookDeliveryRow {
  id: string
  webhook_id: string
  webhook_url: string | null
  developer_id: number | null
  developer_email: string | null
  event_type: string
  response_status: number | null
  response_body: string | null
  retry_count: number
  next_retry_at: string | null
  delivered_at: string | null
  error_message: string | null
}

export interface RecentDeliveriesResponse {
  count: number
  deliveries: WebhookDeliveryRow[]
  filter: { status: string | null; event_type: string | null; limit: number }
}

export interface AdminWebhookTestResult {
  success: boolean
  status_code: number | null
  delivery_id: string
  developer_id: number
}

export interface AdminWebhookToggleResult {
  id: string
  is_active: boolean
  changed: boolean
  developer_id: number
}

class WebhooksAdminService {
  private base = '/admin/webhooks'

  async aggregate(period: WebhookPeriod = '24h'): Promise<WebhooksAggregate> {
    const resp = await apiClient.get(`${this.base}/aggregate`, { params: { period } })
    return resp.data
  }

  async recentDeliveries(params?: {
    limit?: number
    status?: DeliveryStatus
    event_type?: string
  }): Promise<RecentDeliveriesResponse> {
    const query: Record<string, any> = { limit: params?.limit ?? 100 }
    if (params?.status && params.status !== 'all') query.status_filter = params.status
    if (params?.event_type) query.event_type = params.event_type
    const resp = await apiClient.get(`${this.base}/recent-deliveries`, { params: query })
    return resp.data
  }

  /**
   * Admin-tier webhook actions (#3, 2026-05-08). These bypass the per-developer
   * ownership check that routers/webhooks.py:_get_owned_webhook enforces for
   * the regular /webhooks/{id}/* surface, so cluster admins can act on ANY
   * webhook from /admin/webhooks-cluster. Owner-tier paths still work for
   * per-developer self-service at /webhooks.
   */
  async testWebhook(webhookId: string): Promise<AdminWebhookTestResult> {
    const resp = await apiClient.post(`${this.base}/${encodeURIComponent(webhookId)}/test`)
    return resp.data
  }

  async disableWebhook(webhookId: string): Promise<AdminWebhookToggleResult> {
    const resp = await apiClient.post(`${this.base}/${encodeURIComponent(webhookId)}/disable`)
    return resp.data
  }

  async enableWebhook(webhookId: string): Promise<AdminWebhookToggleResult> {
    const resp = await apiClient.post(`${this.base}/${encodeURIComponent(webhookId)}/enable`)
    return resp.data
  }
}

export const webhooksAdminService = new WebhooksAdminService()
