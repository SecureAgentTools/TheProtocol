/**
 * §FESUITE (V0578): searchPlaces says which of four answers the place search gave. The pickers turned every answer that
 * was not a list into [], so a failed (502) or switched-off (404) search looked exactly like "no place found".
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { searchPlaces } from './geocode'

const answer = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body })
afterEach(() => { vi.unstubAllGlobals() })

describe('searchPlaces', () => {
  it('a list of places is "found", in the pickers\' shape', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, [{ display_name: 'Brussels, Belgium', lat: '50.8467', lon: '4.3525' }])))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'found', places: [{ label: 'Brussels, Belgium', lat: 50.8467, lng: 4.3525 }] })
    expect((fetch as any).mock.calls[0][0]).toBe('/api/v1/public/geocode?q=Brussels')
  })
  it('an answered empty list is "none"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, [])))
    expect(await searchPlaces('Nowhereville')).toEqual({ kind: 'none' })
  })
  it('a 404 is "off" (this frame does not search places), never "none"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(404, { detail: 'geocode relay disabled on this frame' })))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'off' })
  })
  it('a 502, no answer, or an answer that is not a list is "failed", never "none"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(502, { detail: 'geocoding upstream unreachable' })))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'failed' })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'failed' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, { detail: 'not a list' })))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'failed' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => { throw new SyntaxError('no JSON') } }))
    expect(await searchPlaces('Brussels')).toEqual({ kind: 'failed' })
  })
  it('a place without usable coordinates is not offered', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(answer(200, [{ display_name: 'x', lat: 'n/a', lon: '1' }])))
    expect(await searchPlaces('x y')).toEqual({ kind: 'none' })
  })
})
