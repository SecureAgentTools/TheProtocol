/**
 * V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d): what the console makes of GET /public/announcements. The answer is read defensively
 * (a visitor's page must not break on a registry that answers something else), an announcement's call to action is only ever a
 * safe http(s) or site-relative address, and a body is text. BASE: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { readPublicAnnouncements } from './publicAnnouncements'

const row = (over: Record<string, unknown> = {}) => ({
  id: 7, title: 'Maintenance on Saturday', body: 'The registry restarts at 02:00 UTC.', broadcast_type: 'maintenance',
  created_at: '2026-11-14T10:00:00Z', cta_url: null, cta_label: null, ...over,
})

describe('readPublicAnnouncements', () => {
  it('reads the rows the registry serves, in its order', () => {
    const out = readPublicAnnouncements([row(), row({ id: 6, title: 'Older' })])
    expect(out.map((a) => a.id)).toEqual([7, 6])
    expect(out[0]).toMatchObject({ title: 'Maintenance on Saturday', type: 'maintenance', createdAt: '2026-11-14T10:00:00Z', cta: null })
  })

  it('answers an empty list for anything that is not a list, never a throw', () => {
    for (const bad of [null, undefined, {}, 'x', 3, { announcements: [] }]) expect(readPublicAnnouncements(bad)).toEqual([])
  })

  it('drops a row with no id, no title or no body, and keeps the rest', () => {
    const out = readPublicAnnouncements([row({ id: undefined }), row({ title: '' }), row({ body: null }), 'x', null, row({ id: 9 })])
    expect(out.map((a) => a.id)).toEqual([9])
  })

  it('keeps a call to action only when its address is safe and it has a label', () => {
    const ok = readPublicAnnouncements([row({ cta_url: 'https://example.org/read', cta_label: 'Read more' })])[0]
    expect(ok.cta).toEqual({ url: 'https://example.org/read', label: 'Read more' })
    const rel = readPublicAnnouncements([row({ cta_url: '/docs/38', cta_label: 'Notes' })])[0]
    expect(rel.cta).toEqual({ url: '/docs/38', label: 'Notes' })
    for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//evil.example', 'ftp://x.test/a']) {
      expect(readPublicAnnouncements([row({ cta_url: bad, cta_label: 'Go' })])[0].cta).toBeNull()
    }
    expect(readPublicAnnouncements([row({ cta_url: 'https://example.org/read', cta_label: '' })])[0].cta).toBeNull()
  })

  it('names an unknown type "info" and keeps the four known ones', () => {
    for (const t of ['info', 'warning', 'maintenance', 'critical']) expect(readPublicAnnouncements([row({ broadcast_type: t })])[0].type).toBe(t)
    expect(readPublicAnnouncements([row({ broadcast_type: 'odd' })])[0].type).toBe('info')
  })
})
