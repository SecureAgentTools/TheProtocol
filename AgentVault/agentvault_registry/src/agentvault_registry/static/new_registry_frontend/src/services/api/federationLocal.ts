// §pass62 (2026-05-21) — Federation Discovery Local Registry drawer support.
// Three admin endpoints that surface real LOCAL registry data (was empty
// defaults before because the Local pseudo-peer had no peer_registries row).

import { apiClient } from './client'

export interface RegistryStats {
  agent_count: number
  agent_card_count: number
  developer_count: number
  peer_count_active: number
  peer_count_total: number
  uptime_seconds: number
  registry_name: string
  trust_domain: string
  is_central_registry: boolean
  is_genesis: boolean
}

export interface LifecycleLayer {
  status: string
  id?: string | number | null
  name?: string
  key_prefix?: string | null
  hop_distance?: number
  is_local?: boolean
  hosted?: boolean
  active?: boolean
  trust_domain?: string | null
  spiffe_id?: string
  spire_server?: string
  url?: string
  created_at?: string | null
  issued_at?: string | null
  expires_at?: string | null
  suspended_reason?: string | null
  revoked_reason?: string | null
}

export interface OperatorLifecycle {
  registry_name: string
  is_central_registry: boolean
  is_local: boolean
  application: LifecycleLayer
  license: LifecycleLayer
  peer_registry: LifecycleLayer
  cloud_stack: LifecycleLayer
  spire_bundle: LifecycleLayer
}

export interface LocalEventsResponse {
  registry: string
  aggregate_ids: string[]
  events: Array<{
    id?: string
    event_id?: string
    event_type: string
    timestamp: string
    aggregate_id?: string
    data?: Record<string, unknown>
  }>
  count: number
}

export async function fetchRegistryStats(): Promise<RegistryStats> {
  const { data } = await apiClient.get('/admin/registry-stats')
  return data
}

export async function fetchOperatorLifecycle(): Promise<OperatorLifecycle> {
  const { data } = await apiClient.get('/admin/operator-lifecycle')
  return data
}

export async function fetchLocalFederationEvents(limit = 50): Promise<LocalEventsResponse> {
  const { data } = await apiClient.get('/admin/federation/local-events', {
    params: { limit },
  })
  return data
}
