// §RELEASECHANNEL (2026-09-21): the admin's view of the signed release channel and the rollout window they schedule.
// Backend: routers/admin_release_channel.py. The registry never updates itself; the page prints the host command.
import { ref } from 'vue'
import { apiClient } from './client'

export interface ReleaseSummary {
  version: string
  kind: 'stable' | 'hotfix' | 'security' | string
  released_at?: string | null
  registry_software_version?: string | null
  kit_url?: string | null
  kit_sha256?: string | null
  images_prefix?: string | null
  images_tag?: string | null
  image_digests?: Record<string, string>
  min_upgrade_from?: string | null
  rollback?: string | null
  notes?: string | null
  notes_url?: string | null
}

export interface ReleaseSchedule {
  version: string
  at: string
  note?: string | null
  set_by?: string | null
  set_at?: string | null
  reminded_at?: string | null
}

export interface ReleaseChannelStatus {
  enabled: boolean
  channel_url: string
  public_pull: boolean
  public_namespace: string
  node_kind: 'frame' | 'operator' | string
  rollout_command: string | null
  last_check_at: string | null
  last_outcome: 'ok' | 'unreachable' | 'invalid_signature' | 'invalid_document' | null
  last_error: string | null
  running: { kit_version?: string | null; software_version?: string | null; modified_build?: boolean } | null
  latest: ReleaseSummary | null
  newer: ReleaseSummary[]
  update_available: boolean
  kind: string | null
  comparable: boolean | null
  notified: Record<string, string>
  schedule: ReleaseSchedule | null
  /** the build the stored check saw, when this registry has changed since (the verdict was read again against the
   *  build running now) */
  checked_against?: { kit_version?: string | null; software_version?: string | null } | null
}

/** The one status every reader shows: the page, and the banner above every admin page. Each call below replaces it,
 *  so the page's own check is the banner's answer too (agentvault2-56, 2026-10-23: the banner read the status once per
 *  session and still announced a newer release after the page's check said up to date). */
export const releaseChannelState = ref<ReleaseChannelStatus | null>(null)
const keep = (s: ReleaseChannelStatus): ReleaseChannelStatus => { releaseChannelState.value = s; return s }

export const releaseChannelApi = {
  status: () => apiClient.get<ReleaseChannelStatus>('/admin/release-channel/status').then((r) => keep(r.data)),
  checkNow: () => apiClient.post<ReleaseChannelStatus>('/admin/release-channel/check').then((r) => keep(r.data)),
  schedule: (body: { version: string; at: string; note?: string }) =>
    apiClient.put<ReleaseChannelStatus>('/admin/release-channel/schedule', body).then((r) => keep(r.data)),
  unschedule: () => apiClient.delete<ReleaseChannelStatus>('/admin/release-channel/schedule').then((r) => keep(r.data)),
}
