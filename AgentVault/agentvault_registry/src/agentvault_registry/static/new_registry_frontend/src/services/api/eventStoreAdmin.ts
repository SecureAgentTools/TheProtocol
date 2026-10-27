/**
 * services/api/eventStoreAdmin.ts — Admin EventStore browser wrapper.
 *
 * Build #6 (2026-05-07) — frontend wrapper for the admin EventStore explorer.
 * Backend: routers/admin_health.py:get_events_search + get_events_by_aggregate
 * (added in Build #6 commit). Proxies to EventStore at internal :8200.
 *
 * Auth: admin_platform flag.
 *
 * NOTE: This is a separate wrapper from the existing services/api/eventStore.ts
 * which talks to a different (mostly stubbed/legacy) endpoint set. We're using
 * a fresh module to avoid disturbing existing callers.
 */
import { apiClient } from './client'

export interface EventStoreEvent {
  // Backend (agentvault-event-store) returns these field names — see
  // agentvault-event-store/src/routers/events.py response shape.
  id?: string                          // canonical event ID (UUID)
  event_type: string
  aggregate_id?: string | null
  aggregate_type?: string | null
  data?: Record<string, any>           // payload dict
  metadata?: Record<string, any>       // often {} when no metadata
  timestamp: string
  version?: number                     // schema version
  source_service?: string              // emitter: teg / registry / eventstore
  idempotency_key?: string | null
  seq?: number | null                  // monotonic sequence number
  [key: string]: any
}

/** §FEDEVENTS 2026-08-03: OPEN string, never a closed 'A'|'B'|'C' union (the
 *  anti-pattern config/frames.ts warns about — it capped every admin view at
 *  three frames and broke deployments with no letter, e.g. hetzner-frame).
 *  'local' (LOCAL_FRAME) = the viewer's own registry, whatever its identity;
 *  single letters remain valid for legacy sibling frames. */
export type FrameId = string
export const LOCAL_FRAME: FrameId = 'local'

/** 2026-05-07 bug fix: order for the unfiltered pagination path.
 *  'desc' (default) is newest-first (admin UI / incident response).
 *  'asc' preserves legacy chronological order for genesis-period browsing. */
export type SortOrder = 'asc' | 'desc'

/** Projection stats shape from GET /admin/eventstore-stats (cached ~60s). */
export interface EventStoreStats {
  total_events: number
  unique_agents?: number
  event_counts: Record<string, number>
  oldest_event?: string | null
  newest_event?: string | null
  [key: string]: any
}

class EventStoreAdminService {
  private base = '/admin/events'

  /**
   * GET /admin/events/search
   * Optional event_type filter, pagination, frame switch (A=mainframe, B=sovereign),
   * sort order for the unfiltered path.
   */
  async search(params?: {
    limit?: number
    offset?: number
    event_type?: string
    frame?: FrameId
    sort_order?: SortOrder
  }): Promise<{ events: EventStoreEvent[]; count: number; frame?: FrameId }> {
    try {
      const queryParams: Record<string, any> = {
        limit: params?.limit ?? 100,
        offset: params?.offset ?? 0,
        frame: params?.frame ?? LOCAL_FRAME,
        sort_order: params?.sort_order ?? 'desc',
      }
      if (params?.event_type) queryParams.event_type = params.event_type
      const resp = await apiClient.get(`${this.base}/search`, { params: queryParams })
      return resp.data ?? { events: [], count: 0 }
    } catch (err) {
      console.error('Failed to query EventStore:', err)
      throw err
    }
  }

  /**
   * GET /admin/events/aggregate/{aggregate_id}
   * Returns ALL events for a given aggregate, ordered ASC. Frame-aware.
   */
  async byAggregate(aggregateId: string, frame: FrameId = LOCAL_FRAME): Promise<{ events: EventStoreEvent[]; count: number; frame?: FrameId }> {
    try {
      const resp = await apiClient.get(
        `${this.base}/aggregate/${encodeURIComponent(aggregateId)}`,
        { params: { frame } },
      )
      return resp.data ?? { events: [], count: 0 }
    } catch (err) {
      console.error('Failed to query EventStore by aggregate:', err)
      throw err
    }
  }

  /**
   * GET /admin/eventstore-stats
   * Cached projection stats. NOTE: `event_counts` ({event_type: count}) ships
   * EMPTY in prod (the projection's per-type cache refresh is skipped), so it's
   * only an *augment* for the filter — emissionPolicyTypes() is the primary
   * source. Frame-A scoped; `frame` is forwarded for forward-compat.
   */
  async stats(frame: FrameId = LOCAL_FRAME): Promise<EventStoreStats> {
    try {
      const resp = await apiClient.get('/admin/eventstore-stats', { params: { frame } })
      return resp.data ?? { total_events: 0, event_counts: {} }
    } catch (err) {
      console.error('Failed to query EventStore stats:', err)
      return { total_events: 0, event_counts: {} }
    }
  }

  /**
   * GET /admin/event-emission-policies → distinct `event_type` names (~170).
   * The authoritative, reliable source for the event-type filter: a stable DB
   * table covering every event type the platform knows about (not just those
   * already present in the store). No backend work — endpoint already exists.
   */
  async emissionPolicyTypes(): Promise<string[]> {
    try {
      const resp = await apiClient.get('/admin/event-emission-policies')
      const policies = (resp.data?.policies ?? []) as Array<{ event_type?: string }>
      return policies.map((p) => p.event_type).filter((t): t is string => !!t)
    } catch (err) {
      console.error('Failed to load emission policies:', err)
      return []
    }
  }
}

export const eventStoreAdminService = new EventStoreAdminService()
