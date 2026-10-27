// Place search for the location pickers (§FESUITE, V0578).
//
// GET /api/v1/public/geocode?q=<place> (routers/geocode.py) answers a list of at most five places, possibly empty; 404
// when this frame's relay is switched off (GEOCODE_RELAY_ENABLED); 502 when the upstream could not be read; 422 for a
// query under two characters. The pickers read only the list: every other answer reached `.map` as an error body, threw
// inside their catch and became [], so a failed or switched-off search looked exactly like "no place found". This says
// which of the four it was. Public and unauthenticated, so it is a plain fetch, as the pickers' own calls were.

export interface Place { label: string; lat: number; lng: number }

export type PlaceSearch =
  | { kind: 'found'; places: Place[] }
  | { kind: 'none' }      // the search answered, with no place for that name
  | { kind: 'off' }       // this frame does not search places (the relay is switched off)
  | { kind: 'failed' }    // no answer, or one that is not a list of places

/** the shortest query the registry takes (routers/geocode.py min_length) */
export const PLACE_QUERY_MIN = 2

export async function searchPlaces(q: string): Promise<PlaceSearch> {
  let res: Response
  try {
    res = await fetch(`/api/v1/public/geocode?q=${encodeURIComponent(q)}`, { headers: { 'Accept-Language': 'en' } })
  } catch {
    return { kind: 'failed' }
  }
  if (res.status === 404) return { kind: 'off' }
  if (!res.ok) return { kind: 'failed' }
  let data: unknown
  try { data = await res.json() } catch { return { kind: 'failed' } }
  if (!Array.isArray(data)) return { kind: 'failed' }
  const places = data
    .map((r: any) => ({ label: String(r?.display_name ?? ''), lat: parseFloat(r?.lat), lng: parseFloat(r?.lon) }))
    .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng))
  return places.length ? { kind: 'found', places } : { kind: 'none' }
}
