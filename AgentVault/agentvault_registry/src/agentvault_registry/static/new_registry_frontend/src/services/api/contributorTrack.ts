// V0665 (order gwo_5e0701efdef9d3989491bc37): the contributor track's client on the registry's routes (routers/contributor_track.py). Nothing here grants an
// item: the registry's evaluator writes the unlock records from governed-code events. A title is worn through the one equip route; a ring or a badge through the
// flare selection route the flare manager already uses.
import { apiClient } from './client'

export type TrackKind = 'corner' | 'encirclement' | 'title'
export interface TrackItem {
  kind: TrackKind
  key: string
  tier: number | null
  side: boolean
  condition: string
  unlocked?: boolean
  progress?: { n: number; of: number }
  /** why it cannot be earned yet (no signal, a later phase, no condition set): shown beside the item */
  later?: string | null
}
export interface MyTrack { items: TrackItem[]; equipped_title: string | null; season_wins: string[]; counts: Record<string, number> }
export interface PublicTrack { items: TrackItem[]; seasons?: string; rules?: string[] }

export async function getPublicTrack(): Promise<PublicTrack> {
  const { data } = await apiClient.get('/public/contributor-track')
  return { items: Array.isArray(data?.items) ? data.items : [], seasons: data?.seasons, rules: data?.rules }
}
export async function getMyTrack(): Promise<MyTrack> {
  const { data } = await apiClient.get('/developers/me/contributor-track')
  return { items: Array.isArray(data?.items) ? data.items : [], equipped_title: data?.equipped_title ?? null,
    season_wins: Array.isArray(data?.season_wins) ? data.season_wins : [], counts: data?.counts || {} }
}
/** Wear an unlocked title (null takes it off). A 403 is the registry's sentence of what unlocks it: the caller shows it where it asked. */
export async function equipTitle(titleKey: string | null): Promise<{ title: string | null }> {
  const { data } = await apiClient.put('/developers/me/flare/title', { title_key: titleKey }, { expectedStatuses: [400, 403] })
  return data
}
/** Wear an earned ring or badge: the flare selection route (the unlock row is its gate; a 403 carries the sentence). */
export async function wearEarned(kind: 'encirclement' | 'corner', key: string | null): Promise<Record<string, any>> {
  const body = kind === 'encirclement' ? { variant: key ?? '__clear__' } : { corner_variant: key ?? '__clear__' }
  const { data } = await apiClient.patch('/fiat/flare/selection', body, { expectedStatuses: [400, 403] })
  return data
}
/**
 * V0666 wear an earned ring or badge on one of your agents (null takes it off): the agent routes ask for the developer's unlock row (a 403 carries the sentence that
 * unlocks it), tell an agent that wears a bought ring or corner to take it off first (a 409), and keep one copy on one bearer (the registry moves it).
 */
export async function wearEarnedOnAgent(did: string, kind: 'encirclement' | 'corner', key: string | null): Promise<Record<string, any>> {
  const route = kind === 'encirclement' ? 'variant' : 'corner-variant'
  const { data } = await apiClient.patch(`/fiat/flare/agent/${encodeURIComponent(did)}/${route}`, { variant: key ?? '__clear__' }, { expectedStatuses: [400, 403, 409] })
  return data
}
