/**
 * §STARQUOTA (2026-08-21) — every registry you own agents on gets stars.
 *
 * The stage drew `availableAgents.slice(0, 240)`. That list is sorted
 * credentialed-first then balance-descending, so the first 240 all landed in a
 * handful of registries and the rest of the fleet simply had no stars — he saw
 * agents orbiting exactly FIVE registries (abudhabi, doha, frame-c, berlin,
 * london) out of sixteen he is signed in to, and reasonably read it as "the
 * others did not load".
 *
 * They loaded. They lost a slice().
 *
 * Same fix the backend already uses for the globe (§GLOBEPOP `_allocate_quotas`,
 * where "minimums OUTRANK budget"): give every registry a floor first, then
 * share what is left in proportion to how many agents it actually has. The cap
 * still holds — this decides WHICH stars are drawn, never how many.
 */

export interface StarCandidate {
  did: string
  /** Registry origin. Anything falsy means "this origin" (local). */
  registryUrl?: string | null
  /**
   * Explicit home bucket, and it WINS over `registryUrl`.
   *
   * §OWNEDHOMES (2026-08-21). `registryUrl` only exists on agents we hold a
   * CREDENTIAL for — it is copied off the credential, not off the registry
   * response. An agent you own as a DEVELOPER on another registry arrives from
   * the fan-out as a bare DID with no URL anywhere, so bucketing on
   * `registryUrl` alone silently filed every one of them under LOCAL and the
   * quota then had nothing to spread. The caller knows the home; let it say so.
   */
  home?: string | null
}

export const LOCAL_KEY = '__local__'

/** Group by registry origin, preserving input order inside each group. */
export function groupByRegistry(rows: StarCandidate[]): Map<string, string[]> {
  const out = new Map<string, string[]>()
  // GLOBAL dedup, first mention wins: an agent has exactly one home, and the
  // same DID landing in two buckets would take two slots and be drawn twice.
  // O(1) per row — `arr.includes` was O(n^2) and this list is now the WHOLE
  // owned fleet (4,440 on frame-c alone), not the 240 that get drawn.
  const seen = new Set<string>()
  for (const r of rows) {
    const did = r?.did && String(r.did)
    if (!did || seen.has(did)) continue
    let key = LOCAL_KEY
    const h = r.home
    if (h && typeof h === 'string' && h.trim()) {
      key = h.trim()
    } else {
      const u = r.registryUrl
      if (u && typeof u === 'string') {
        try { key = new URL(u).host } catch { key = LOCAL_KEY }
      }
    }
    seen.add(did)
    const arr = out.get(key)
    if (arr) arr.push(did); else out.set(key, [did])
  }
  return out
}

/**
 * Choose up to `cap` DIDs so every registry is represented.
 *
 * `minPer` is a FLOOR, not a target: if the floors alone exceed the cap, the
 * floor is reduced evenly rather than letting the first registries eat the
 * whole budget — the failure being fixed here is precisely "the first ones took
 * everything".
 */
export function allocateStars(
  rows: StarCandidate[], cap: number, minPer = 8,
): string[] {
  if (cap <= 0) return []
  const groups = groupByRegistry(rows)
  if (groups.size === 0) return []
  if (groups.size === 1) return [...groups.values()][0].slice(0, cap)

  // Floors first, shrunk to fit if there are more registries than budget.
  const floor = Math.max(1, Math.min(minPer, Math.floor(cap / groups.size)))
  const taken = new Map<string, number>()
  let used = 0
  for (const [k, dids] of groups) {
    const n = Math.min(floor, dids.length)
    taken.set(k, n); used += n
  }

  /*
   * Share the remainder IN PROPORTION to what each registry still has left —
   * the same rule the backend's globe uses (§GLOBEPOP `_allocate_quotas`), and
   * for the same reason.
   *
   * ⚠ THE FIRST VERSION HANDED OUT THE REMAINDER ROUND-ROBIN, one per registry
   * per pass, and measured on his account that is its own misrepresentation:
   * 16 registries × 15 stars each, so a fleet that is 4,448 local out of 5,844
   * (76%) drew as 6% local. Every registry being visible is a FLOOR, not a
   * levelling — the big one should still look big.
   */
  let remaining = cap - used
  const left = () => [...groups.entries()]
    .map(([k, d]) => ({ k, left: d.length - (taken.get(k) || 0) }))
    .filter(x => x.left > 0)
  let pool = left()
  if (remaining > 0 && pool.length) {
    const totalLeft = pool.reduce((n, x) => n + x.left, 0)
    // Largest-remainder: floor the proportional share, then hand the rounding
    // slack to whoever lost the most to rounding. Deterministic, no starvation.
    const share = pool.map(x => {
      const exact = (x.left / totalLeft) * remaining
      const base = Math.min(x.left, Math.floor(exact))
      return { k: x.k, base, frac: exact - Math.floor(exact), left: x.left }
    })
    for (const x of share) { taken.set(x.k, (taken.get(x.k) || 0) + x.base); remaining -= x.base }
    share.sort((a, b) => b.frac - a.frac)
    let guard = share.length * 2 + 1
    while (remaining > 0 && guard-- > 0) {
      let progressed = false
      for (const x of share) {
        if (remaining <= 0) break
        const cur = taken.get(x.k) || 0
        const capacity = (groups.get(x.k) || []).length
        if (cur >= capacity) continue
        taken.set(x.k, cur + 1); remaining--; progressed = true
      }
      if (!progressed) break
    }
  }
  void pool

  const out: string[] = []
  for (const [k, dids] of groups) out.push(...dids.slice(0, taken.get(k) || 0))
  return out.slice(0, cap)
}

/** How many registries are represented — for the honest caption. */
export function representedRegistries(rows: StarCandidate[], chosen: string[]): number {
  const pick = new Set(chosen)
  const groups = groupByRegistry(rows.filter(r => pick.has(String(r.did))))
  return groups.size
}
