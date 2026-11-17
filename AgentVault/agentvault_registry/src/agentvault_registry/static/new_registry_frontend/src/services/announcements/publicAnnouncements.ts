// V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d): the announcements an admin marked public, as the console reads them.
//
// GET /public/announcements answers a list of {id, title, body, broadcast_type, created_at, cta_url, cta_label}: no sign-in, only
// what an admin marked public, nothing addressed to anyone in particular (the registry's rule, services side: routers/admin_broadcast).
// This module reads the answer defensively, because a visitor's page must not break on a registry that answers something else:
// a non-list is no announcements, a row without an id, a title or a body is dropped, and a call to action survives only as a safe
// http(s) or site-relative address with a label (utils/safeUrl). A body is TEXT: the views never bind it as markup.
import apiClient from '@/services/api/client'
import { safeExternalUrl } from '@/utils/safeUrl'

export type AnnouncementType = 'info' | 'warning' | 'maintenance' | 'critical'

export interface PublicAnnouncement {
  id: number
  title: string
  body: string
  type: AnnouncementType
  createdAt: string
  cta: { url: string; label: string } | null
}

const TYPES: readonly string[] = ['info', 'warning', 'maintenance', 'critical']

const text = (v: unknown): string => (typeof v === 'string' ? v : '')

export function readPublicAnnouncements(data: unknown): PublicAnnouncement[] {
  if (!Array.isArray(data)) return []
  const out: PublicAnnouncement[] = []
  for (const r of data) {
    if (!r || typeof r !== 'object') continue
    const o = r as Record<string, unknown>
    const id = typeof o.id === 'number' && Number.isFinite(o.id) ? o.id : null
    const title = text(o.title).trim()
    const body = text(o.body).trim()
    if (id === null || !title || !body) continue
    // a protocol-relative address (//host) resolves to http on whatever page it is read: an announcement's link names its scheme
    const rawUrl = text(o.cta_url).trim()
    const url = rawUrl.startsWith('//') ? undefined : safeExternalUrl(rawUrl || null)
    const label = text(o.cta_label).trim()
    out.push({
      id, title, body,
      type: (TYPES.includes(text(o.broadcast_type)) ? text(o.broadcast_type) : 'info') as AnnouncementType,
      createdAt: text(o.created_at),
      cta: url && label ? { url, label } : null,
    })
  }
  return out
}

/** The newest public announcements (at most `limit`, the registry's cap is 50). Throws when the registry cannot be read: the view says so. */
export async function fetchPublicAnnouncements(limit = 20): Promise<PublicAnnouncement[]> {
  const { data } = await apiClient.get('/public/announcements', { params: { limit } })
  return readPublicAnnouncements(data)
}
