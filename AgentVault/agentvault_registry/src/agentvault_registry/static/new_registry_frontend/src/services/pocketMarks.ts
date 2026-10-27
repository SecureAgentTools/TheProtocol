/**
 * services/pocketMarks.ts — §POCKETBRIDGE2 W6.
 *
 * Earned-mark tiers for pocket LIST ROWS, resolve-what-you-see style (§R6):
 * bounded, cached per session, small concurrency, and ABSENCE RENDERS NOTHING
 * — a row without a fetched record shows no mark, never a placeholder tier.
 * Earned marks are proof-of-work reputation (§AGENTDISC #190) and must never
 * be fabricated client-side; this module only relays what the public
 * track-record endpoint attests.
 */
import { fetchTrackRecord, compactFromSummary, earnedMarks, type EarnedMarks } from '@/services/api/trackRecord'

const cache = new Map<string, EarnedMarks | null>()
let inFlight = 0
const MAX_CONCURRENT = 4

type Fetcher = (did: string) => Promise<any>
const defaultFetcher: Fetcher = (did) => fetchTrackRecord(did, 0)

async function one(did: string, fetcher: Fetcher): Promise<EarnedMarks | null> {
  if (cache.has(did)) return cache.get(did) ?? null
  while (inFlight >= MAX_CONCURRENT) await new Promise(r => setTimeout(r, 60))
  inFlight++
  try {
    const resp = await fetcher(did)
    const m = earnedMarks(compactFromSummary(resp))
    const val = m.tier ? m : null
    cache.set(did, val)
    return val
  } catch {
    // unfetchable ≠ tier-less forever: do NOT cache errors, so a later
    // viewing can succeed. Rendering-wise both are "no mark shown".
    return null
  } finally { inFlight-- }
}

/**
 * Resolve marks for the FIRST `cap` dids (the visible screenful), returning a
 * map that fills as answers land. `onEach` fires per resolution so a component
 * can paint incrementally.
 */
export function marksForMany(
  dids: string[],
  onEach: (did: string, marks: EarnedMarks) => void,
  cap = 24,
  fetcher: Fetcher = defaultFetcher,
): void {
  for (const did of dids.slice(0, cap)) {
    if (!did || !did.startsWith('did:')) continue
    void one(did, fetcher).then(m => { if (m) onEach(did, m) })
  }
}

/** test seam */
export function _resetMarkCache(): void { cache.clear() }
