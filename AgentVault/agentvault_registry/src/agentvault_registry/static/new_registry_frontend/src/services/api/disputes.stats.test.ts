/**
 * §COCKPITDESK (2026-10-15) — the camera read "0 resolved · 0% resolution rate · 0h" over 22 disputes, 19 of them
 * dismissed. A dismissal is a ruling: the rate and the time count every decided dispute, and with nothing to count the
 * page shows a dash, never 0% or 0 h.
 */
import { describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() }, default: {} }))

import { disputesApi } from './disputes'

const at = (h: number) => new Date(Date.UTC(2026, 9, 1) + h * 3_600_000).toISOString()
const d = (status: string, ruledAfterH?: number) => ({ id: status + Math.random(), status, created_at: at(0),
  resolution_date: ruledAfterH === undefined ? null : at(ruledAfterH) })
const stats = (rows: any[]) => (disputesApi as any).calculateStats(rows)

describe('dispute stats', () => {
  it('counts a dismissal as a decision, for the rate and the time', () => {
    const s = stats([d('dismissed', 10), d('dismissed', 20), d('resolved', 30), d('open')])
    expect(s.decided_disputes).toBe(3)
    expect(s.resolved_disputes).toBe(1)
    expect(s.dismissed_disputes).toBe(2)
    expect(s.resolution_rate).toBe(75)
    expect(s.average_resolution_time).toBe(20)
  })

  it('says nothing (null) where there is nothing to count', () => {
    expect(stats([]).resolution_rate).toBeNull()
    const open = stats([d('open'), d('investigating')])
    expect(open.resolution_rate).toBe(0)
    expect(open.average_resolution_time, 'no ruling: no time, not 0 h').toBeNull()
  })
})
