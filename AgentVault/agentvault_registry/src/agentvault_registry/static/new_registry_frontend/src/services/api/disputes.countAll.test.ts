/**
 * §COCKPITDESK (2026-10-15) — the Disputes tiles read "TOTAL 100" beside dispute #205 on sbx-alpha: they counted the list's
 * first page (the route answers 100 at a time) as the whole. The counting walk pages through, each dispute once by its id,
 * and says when it stopped at its cap.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

const get = vi.hoisted(() => vi.fn())
vi.mock('./client', () => ({ apiClient: { get, post: vi.fn(), put: vi.fn() }, default: {} }))

import { disputesApi, COUNT_PAGE, COUNT_PAGES } from './disputes'

const row = (id: number, status = 'OPEN') => ({ id, status, created_at: '2026-10-01T00:00:00Z', evidence: [] })
const page = (from: number, n: number) => Array.from({ length: n }, (_, i) => row(from + i))

// a block body: a function a hook returns is its teardown, and mockReset() returns the mock itself
beforeEach(() => { get.mockReset() })

describe('counting every dispute', () => {
  it('pages through until a short page: 205 disputes are 205, not 100', async () => {
    get.mockImplementation(async (_u: string, cfg: any) => {
      const o = cfg.params.offset
      return { data: o === 0 ? page(1, 100) : o === 100 ? page(101, 100) : page(201, 5) }
    })
    const s = await disputesApi.getStats()
    expect(s.total_disputes).toBe(205)
    expect(s.capped).toBe(false)
    expect(get.mock.calls.map((c) => c[1].params)).toEqual([
      { limit: COUNT_PAGE, offset: 0 }, { limit: COUNT_PAGE, offset: 100 }, { limit: COUNT_PAGE, offset: 200 }])
  })
  it('counts a dispute two pages both answered once (a tie at a page edge)', async () => {
    get.mockImplementation(async (_u: string, cfg: any) => ({ data: cfg.params.offset === 0 ? page(1, 100) : [row(100), row(101)] }))
    expect((await disputesApi.getStats()).total_disputes).toBe(101)
  })
  it('stops at its cap and says so', async () => {
    let n = 0
    get.mockImplementation(async () => ({ data: page(++n * 1000, 100) }))
    const s = await disputesApi.getStats()
    expect(get).toHaveBeenCalledTimes(COUNT_PAGES)
    expect(s.total_disputes).toBe(COUNT_PAGE * COUNT_PAGES)
    expect(s.capped).toBe(true)
  })
  it('the list and the tiles come from the same reads: every dispute read, newest first, and the counts over them', async () => {
    get.mockImplementation(async (_u: string, cfg: any) => {
      const o = cfg.params.offset
      return { data: o === 0 ? page(1, 100) : o === 100 ? page(101, 100) : page(201, 5) }
    })
    const { rows, stats } = await disputesApi.readAll()
    expect(get).toHaveBeenCalledTimes(3)
    expect(rows).toHaveLength(205)
    expect(rows[0].id).toBe('1')
    expect(rows[204].id).toBe('205')
    expect(stats.total_disputes).toBe(205)
    expect(stats.capped).toBe(false)
  })
  it('a 404 on the first page is none; any other failure is the caller to report', async () => {
    get.mockRejectedValueOnce({ response: { status: 404 } })
    expect((await disputesApi.getStats()).total_disputes).toBe(0)
    get.mockRejectedValueOnce({ response: { status: 500 } })
    await expect(disputesApi.getStats()).rejects.toBeTruthy()
  })
})
