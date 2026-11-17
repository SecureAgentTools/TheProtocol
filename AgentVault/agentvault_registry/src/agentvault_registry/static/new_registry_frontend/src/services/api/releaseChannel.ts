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
  /** V0667 D6 part 3: this frame's own distribution channel (routers/distribution_releases.frame_channel). Not the public status. */
  distributions: () => apiClient.get<DistributionChannel>('/admin/release-channel/distributions').then((r) => r.data),
}

// ---- V0667 D6 part 3 (gwo_fa3b8d7611f2573a2e63ac1c): a frame's own distribution channel ----------------------------------------------
// An organization's line (a code distribution) is built by our pipeline and published on a SCOPED channel: the governing registry serves
// its signed index and its images only to the registries the index names, proven by their certificate and their frame licence.

export interface DistributionLine {
  name: string
  release?: string | null
  generated_at?: string | null
  published_at?: string | null
  images?: { prefix?: string | null; tag?: string | null; digests?: Record<string, string> | null } | null
  registries?: { name: string; trust_domain: string }[] | null
}

export interface DistributionChannel {
  governing: string | null
  here: boolean
  lines: DistributionLine[]
  reason: string | null
}

export interface DistributionRow {
  name: string
  release: string
  publishedAt: string | null
  image: string
  digest: string
}

/** One row per line, as the view prints it: the registry image's digest cut to its first twelve hex digits. */
export function distributionRows(ch: DistributionChannel | null): DistributionRow[] {
  return (ch?.lines || []).map((l) => {
    const d = l.images?.digests?.registry || ''
    return { name: l.name, release: l.release || '', publishedAt: l.published_at || null, image: l.images?.prefix || '',
             digest: d ? d.slice(0, 'sha256:'.length + 12) : '' }
  })
}

export type DistributionNote = { kind: 'none'; governing: string | null } | { kind: 'reason'; governing: string | null; reason: string }

/** Why the list is empty (null when it is not): the registry's own reason, or that no line names this frame. */
export function distributionNote(ch: DistributionChannel | null): DistributionNote | null {
  if (!ch || ch.lines.length) return null
  return ch.reason ? { kind: 'reason', governing: ch.governing, reason: ch.reason } : { kind: 'none', governing: ch.governing }
}
