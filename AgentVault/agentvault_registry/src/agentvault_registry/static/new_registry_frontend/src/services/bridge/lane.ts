/**
 * §BRIDGE R8 — how bright a learned trade lane should be.
 *
 * WHY THIS IS A MODULE AND NOT FOUR LINES INSIDE THE CANVAS
 *
 * The Commander reported "traffic trails not all disappearing". Measured on the
 * live canary: stray verb lines = 0 — the verb pool releases correctly — so what
 * he was seeing is THIS layer, the #B19 learned lanes, which hold for two minutes
 * and then blink out. A thing that sits at constant strength and then vanishes
 * looks broken; a thing that visibly decays looks like weather.
 *
 * The fix is a fade. The trouble with proving a fade on a live network is that a
 * corridor in constant use is SUPPOSED to stay bright, so the live probe read
 * 1.000 for every sample and could not tell "fades correctly" from "stuck at
 * full" — a measurement with one possible answer measures nothing. Pulling the
 * arithmetic out here makes it provable without waiting on the network to go
 * quiet on exactly the corridor being watched.
 */

/** A lane is forgotten this long after its last crossing. */
export const LANE_DECAY_MS = 120_000

/**
 * Brightness in [0,1] for a lane last used `ageMs` ago that has carried `hits`
 * crossings.
 *
 * AGE dominates: full at the moment of use, easing to nothing at expiry, with a
 * slight curve so most of the visible life is spent bright and the last stretch
 * disappears gently rather than stepping off.
 *
 * TRAFFIC modulates: a corridor carrying more is brighter, logarithmically, so
 * one very busy route cannot wash the rest of the map out.
 */
export function laneBrightness(ageMs: number, hits: number): number {
  const age = Math.max(0, ageMs) / LANE_DECAY_MS
  if (age >= 1) return 0
  const fade = Math.pow(1 - age, 1.6)
  const weight = Math.min(1, 0.5 + Math.log10(1 + Math.max(0, hits)) * 0.3)
  return fade * weight
}
