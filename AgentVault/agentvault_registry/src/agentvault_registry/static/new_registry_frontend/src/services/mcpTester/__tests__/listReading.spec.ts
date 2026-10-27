import { describe, it, expect } from 'vitest'
import {
  matchesStatusBucket, isLenientPass, statusDistribution, filterRows, latencyStats, SLOW_THRESHOLD_MS, type ListFilter,
} from '../listReading'

interface R { tool: string; tier?: string; status?: number; healthy?: boolean; skipped?: boolean; elapsed?: number }
const r = (over: Partial<R>): R => ({ tool: 'theprotocol_getThing', tier: 'developer', status: 200, healthy: true, skipped: false, elapsed: 100, ...over })
const NONE: ListFilter = { text: '', tier: '', category: '', onlyFailures: false, onlySlow: false, statusBucket: '', strictPass: false }
const byPrefix = (tool: string) => (tool.replace(/^theprotocol_/, '').match(/^[a-z]+/)?.[0] ?? 'other')

describe('the HTTP-status buckets of the tool list', () => {
  it('matches a bucket by range or by exact code; no status matches nothing but "all"', () => {
    expect(matchesStatusBucket(200, '')).toBe(true)
    expect(matchesStatusBucket(undefined, '')).toBe(true)
    expect(matchesStatusBucket(204, '2xx')).toBe(true)
    expect(matchesStatusBucket(302, '2xx')).toBe(false)
    expect(matchesStatusBucket(422, '4xx')).toBe(true)
    expect(matchesStatusBucket(503, '5xx')).toBe(true)
    expect(matchesStatusBucket(403, '403')).toBe(true)
    expect(matchesStatusBucket(401, '403')).toBe(false)
    for (const b of ['2xx', '4xx', '5xx', '401', '403', '404'] as const) {
      expect(matchesStatusBucket(0, b)).toBe(false)
      expect(matchesStatusBucket(undefined, b)).toBe(false)
    }
  })

  it('counts 401, 403 and 404 in their own chips and in 4xx; a row with no status counts nowhere', () => {
    const d = statusDistribution([{ status: 200 }, { status: 201 }, { status: 401 }, { status: 403 }, { status: 404 }, { status: 422 },
      { status: 500 }, { status: 0 }, { status: undefined }])
    expect(d).toEqual({ '2xx': 2, '4xx': 4, '5xx': 1, '401': 1, '403': 1, '404': 1 })
  })
})

describe('the lenient passes the strict mode hides', () => {
  it('is a pass without a 2xx: a 4xx, a 3xx, or no status at all; never a 2xx, a skip or a failure', () => {
    expect(isLenientPass(r({ status: 200 }))).toBe(false)
    expect(isLenientPass(r({ status: 404 }))).toBe(true)
    expect(isLenientPass(r({ status: 302 }))).toBe(true)
    expect(isLenientPass(r({ status: undefined }))).toBe(true)
    expect(isLenientPass(r({ status: 404, skipped: true }))).toBe(false)
    expect(isLenientPass(r({ status: 404, healthy: false }))).toBe(false)
  })

  it('counts exactly the rows the strict filter hides (the chip said one number and the list another for a 3xx pass)', () => {
    const rows = [r({ status: 200 }), r({ status: 302 }), r({ status: 404 }), r({ status: undefined }), r({ status: 404, skipped: true }),
      r({ status: 500, healthy: false }), r({ status: 204 })]
    const hidden = filterRows(rows, NONE, byPrefix).length - filterRows(rows, { ...NONE, strictPass: true }, byPrefix).length
    expect(rows.filter(isLenientPass).length).toBe(3)
    expect(hidden).toBe(3)
  })
})

describe('the toolbar\'s filters', () => {
  const rows = [
    r({ tool: 'theprotocol_getAgentProfile', tier: 'none', status: 200 }),
    r({ tool: 'theprotocol_createAgent', tier: 'developer', status: 201, elapsed: 2400 }),
    r({ tool: 'theprotocol_adminRequest', tier: 'admin', status: 403, healthy: false }),
    r({ tool: 'theprotocol_adminPromQuery', tier: 'admin', status: undefined, skipped: true }),
    r({ tool: 'theprotocol_getMyBalance', tier: 'agent', status: 404, elapsed: SLOW_THRESHOLD_MS }),
  ]
  const names = (f: Partial<ListFilter>) => filterRows(rows, { ...NONE, ...f }, byPrefix).map((x) => x.tool.replace('theprotocol_', ''))

  it('leaves everything with no filter set', () => {
    expect(names({})).toHaveLength(5)
  })

  it('finds a name by any-case, trimmed text, and narrows by tier and by the page\'s own category', () => {
    expect(names({ text: '  AGENT ' })).toEqual(['getAgentProfile', 'createAgent'])
    expect(names({ tier: 'admin' })).toEqual(['adminRequest', 'adminPromQuery'])
    expect(names({ category: 'get' })).toEqual(['getAgentProfile', 'getMyBalance'])
  })

  it('shows failures only (neither healthy nor skipped), slow rows only (the threshold itself is slow), a status bucket', () => {
    expect(names({ onlyFailures: true })).toEqual(['adminRequest'])
    expect(names({ onlySlow: true })).toEqual(['createAgent', 'getMyBalance'])
    expect(names({ statusBucket: '4xx' })).toEqual(['adminRequest', 'getMyBalance'])
    expect(names({ statusBucket: '404' })).toEqual(['getMyBalance'])
  })

  it('combines them: every filter must hold', () => {
    expect(names({ tier: 'agent', onlySlow: true, statusBucket: '404' })).toEqual(['getMyBalance'])
    expect(names({ tier: 'agent', onlySlow: true, statusBucket: '404', strictPass: true })).toEqual([])
  })
})

describe('the sweep\'s timing statistics', () => {
  const ms = (...v: number[]) => v.map((elapsed, i) => ({ tool: `t${i}`, elapsed }))

  it('reads zeros and no slowest rows when nothing was timed', () => {
    expect(latencyStats([])).toEqual({ median: 0, p95: 0, max: 0, slowest: [] })
    expect(latencyStats([{ elapsed: 0 }, { elapsed: undefined }])).toEqual({ median: 0, p95: 0, max: 0, slowest: [] })
  })

  it('takes the middle value, or the rounded mean of the two middle ones', () => {
    expect(latencyStats(ms(30, 10, 20)).median).toBe(20)
    expect(latencyStats(ms(10, 20, 31, 40)).median).toBe(26)
  })

  it('reads the nearest-rank p95: not the maximum for twenty rows, the 95th of a hundred', () => {
    const twenty = ms(...Array.from({ length: 20 }, (_, i) => i + 1))
    expect(latencyStats(twenty).p95).toBe(19)
    expect(latencyStats(twenty).max).toBe(20)
    const hundred = ms(...Array.from({ length: 100 }, (_, i) => i + 1))
    expect(latencyStats(hundred).p95).toBe(95)
    expect(latencyStats(ms(7)).p95).toBe(7)
    expect(latencyStats(ms(1, 2, 3)).p95).toBe(3)
  })

  it('lists the slowest rows slowest first, as many as asked, leaving untimed rows out', () => {
    const stats = latencyStats([...ms(5, 50, 500, 5000), { tool: 'untimed', elapsed: 0 }], 3)
    expect(stats.slowest.map((x) => (x as { elapsed: number }).elapsed)).toEqual([5000, 500, 50])
  })
})
