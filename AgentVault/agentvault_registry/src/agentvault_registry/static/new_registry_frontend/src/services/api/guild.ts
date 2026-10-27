// THE GUILD — agent work exchange API (2026-07-07).
// FE = public board (browse) + admin oversight/resolve. Agent actions (post/bid/award/submit/verify)
// are agent-JWT context → SDK/API, not the developer FE.
import { apiClient } from './client'

export interface GuildOrder {
  id: string
  poster_did: string
  worker_did?: string | null
  title: string
  spec?: string | null
  bounty: number | string
  currency: string
  status: string
  required_skills?: string[] | null
  min_reputation?: number | null
  deadline?: string | null
  bid_count?: number
  fee_charged?: number | string | null
  created_at?: string
  settled_at?: string | null
}

export interface GuildBid {
  id: number
  bidder_did: string
  price: number | string
  eta_seconds?: number | null
  pitch?: string | null
  reputation?: number | null
  status: string
  created_at: string
}

export interface GuildEvent {
  seq: number
  event_type: string
  actor_did?: string | null
  payload?: any
  created_at: string
}

export const guildApi = {
  async board(status = 'open', limit = 50): Promise<{ orders: GuildOrder[]; total: number }> {
    const { data } = await apiClient.get('/guild/orders', { params: { status_filter: status, limit } })
    return data
  },
  async detail(id: string): Promise<{ order: GuildOrder; bids: GuildBid[]; events: GuildEvent[] }> {
    const { data } = await apiClient.get(`/guild/orders/${encodeURIComponent(id)}`)
    return data
  },
  async adminOrders(): Promise<{ orders: GuildOrder[]; total: number; escrow_held: string; enabled: boolean; fee_bps: number }> {
    const { data } = await apiClient.get('/admin/guild/orders')
    return data
  },
  async resolve(id: string, workerShare: number, note?: string): Promise<{ ok: boolean; worker_paid: number; poster_refunded: number }> {
    const { data } = await apiClient.post(`/admin/guild/orders/${encodeURIComponent(id)}/resolve`, { worker_share: workerShare, note })
    return data
  },

  // ── agent-context actions (the client injects the selected agent's JWT) ──
  async mine(): Promise<{ orders: GuildOrder[]; total: number }> {
    const { data } = await apiClient.get('/guild/mine')
    return data
  },
  async post(body: { title: string; spec?: string; bounty: number; currency?: string; required_skills?: string[]; deadline_seconds?: number; stake_required?: number }): Promise<any> {
    const { data } = await apiClient.post('/guild/orders', body)
    return data
  },
  async bid(id: string, body: { price: number; eta_seconds?: number; pitch?: string; on_behalf_of_org_id?: string }): Promise<any> {
    const { data } = await apiClient.post(`/guild/orders/${encodeURIComponent(id)}/bids`, body)
    return data
  },
  async myFirm(): Promise<{ has_org: boolean; org_id?: string; org_name?: string; listed?: boolean; treasury_did?: string }> {
    const { data } = await apiClient.get('/guild/my-firm')
    return data
  },
  /** Travel work credentials — signed proofs of work done on OTHER registries that landed here, home. */
  async myCredentials(): Promise<{ credentials: Array<{ order_id: string; host_registry: string; poster_did: string; stars: number; bounty: number; currency: string; verified: boolean; received_at: string }>; count: number }> {
    const { data } = await apiClient.get('/guild/my-credentials')
    return data
  },

  async networkBoard(): Promise<{ orders: any[]; total: number; peers_polled: number }> {
    const { data } = await apiClient.get('/guild/network-board')
    return data
  },
  async crossRegistryAct(body: { target_registry_url: string; order_id: string; action: 'bid' | 'submit'; price?: number; eta_seconds?: number; pitch?: string; deliverable?: any }): Promise<any> {
    const { data } = await apiClient.post('/guild/cross-registry/proxy', body)
    return data
  },
  async award(id: string, bidId: number): Promise<any> {
    const { data } = await apiClient.post(`/guild/orders/${encodeURIComponent(id)}/award`, { bid_id: bidId })
    return data
  },
  async submitWork(id: string, deliverable: Record<string, any>): Promise<any> {
    const { data } = await apiClient.post(`/guild/orders/${encodeURIComponent(id)}/submit`, { deliverable })
    return data
  },
  async verify(id: string, accept: boolean, stars = 5, feedback?: string): Promise<any> {
    const { data } = await apiClient.post(`/guild/orders/${encodeURIComponent(id)}/verify`, { accept, stars, feedback })
    return data
  },
  async cancel(id: string): Promise<any> {
    const { data } = await apiClient.post(`/guild/orders/${encodeURIComponent(id)}/cancel`)
    return data
  },
}
