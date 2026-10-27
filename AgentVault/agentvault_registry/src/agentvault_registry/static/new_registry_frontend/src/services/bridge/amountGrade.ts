/**
 * §BRIDGE R14.1 — AMOUNT GRADING WITHIN A VERB (taxonomy option B, approved).
 *
 * His instruction that started the taxonomy work: *"use some fine color grading
 * to not make it look cartoonish."* The answer he approved is B: keep the nine
 * verb hues as the ONLY identity, and let the amount vary brightness, size and
 * trail length INSIDE a hue. No tenth colour. Nothing to memorise.
 *
 * ── WHY THIS IS NOT `classifyAmount(amount) / 4` ──────────────────────────────
 * `classifyAmount` uses fixed cutoffs (10 / 1k / 100k). This network settles in
 * THREE currencies that are not at par: AVT on Frame A, JDAY on Frame B, BVT on
 * Frame C. A fixed ladder therefore does not measure "is this a big payment", it
 * measures "which currency is this" — and it would make one frame look
 * permanently busier than its neighbours for a reason that is an artefact of the
 * scale, not a fact about the traffic.
 *
 * So a payment is graded against OTHER PAYMENTS IN ITS OWN CURRENCY, from what
 * this session has actually observed. That is the same honesty rule the pulse
 * bar follows: report what was seen, and say how much was seen.
 *
 * ── WHAT IT DELIBERATELY DOES NOT DO ─────────────────────────────────────────
 * An event with NO amount (a birth, a corridor announcement, a health probe)
 * returns `null`, not 0. Those are not small payments, they are not payments,
 * and dimming them as though they were the tiniest transfer on the network would
 * be a claim the payload does not support. The caller decides what a null means
 * for each channel it drives; see the comment at the call site.
 */

import { classifyAmount } from './grammar'

/** How many observations per currency shape the distribution. */
export const SAMPLE_CAP = 240
/** Below this, the sample is too thin to be a distribution; fall back. */
export const MIN_SAMPLES = 8

export interface GradeResult {
  /** 0..1 within this currency, or null when there is nothing to grade. */
  grade: number | null
  /** 'observed' once the sample can carry it, 'fallback' before that, 'none'. */
  basis: 'observed' | 'fallback' | 'none'
  /** How many observations backed this answer — so a probe can tell them apart. */
  samples: number
}

export class AmountGrader {
  private byCurrency = new Map<string, number[]>()
  private cursor = new Map<string, number>()

  /** Currency key. Absent currency is its own bucket, never merged with a real one. */
  private key(currency: string | null | undefined): string {
    const c = (currency || '').trim().toUpperCase()
    return c || '__none__'
  }

  /** Record an observation. Only finite, non-zero magnitudes shape a distribution. */
  observe(currency: string | null | undefined, amount: number | null | undefined): void {
    if (amount === null || amount === undefined || !Number.isFinite(amount)) return
    const a = Math.abs(amount)
    if (a === 0) return
    const k = this.key(currency)
    let arr = this.byCurrency.get(k)
    if (!arr) { arr = []; this.byCurrency.set(k, arr) }
    if (arr.length < SAMPLE_CAP) {
      arr.push(a)
    } else {
      // Ring, so a long session keeps measuring the RECENT network rather than
      // being anchored forever by whatever happened in the first minute.
      const i = (this.cursor.get(k) || 0) % SAMPLE_CAP
      arr[i] = a
      this.cursor.set(k, i + 1)
    }
  }

  /** Observations held for a currency. Exposed so "observed" is provable. */
  samples(currency: string | null | undefined): number {
    return this.byCurrency.get(this.key(currency))?.length || 0
  }

  /**
   * Grade |amount| against its own currency: the fraction of observations it
   * meets or exceeds. Ties count as met, so the single most common amount on a
   * uniform network grades high rather than at zero.
   */
  grade(currency: string | null | undefined, amount: number | null | undefined): GradeResult {
    if (amount === null || amount === undefined || !Number.isFinite(amount)) {
      return { grade: null, basis: 'none', samples: 0 }
    }
    const a = Math.abs(amount)
    if (a === 0) return { grade: 0, basis: 'none', samples: 0 }

    const k = this.key(currency)
    const arr = this.byCurrency.get(k)
    const n = arr?.length || 0
    if (!arr || n < MIN_SAMPLES) {
      // Thin sample: degrade to the fixed ladder rather than to a flat zero, so
      // the first events of a session still carry some magnitude.
      return { grade: classifyAmount(a) / 4, basis: 'fallback', samples: n }
    }
    let below = 0
    for (let i = 0; i < n; i++) if (arr[i] <= a) below++
    return { grade: below / n, basis: 'observed', samples: n }
  }

  /** Every currency observed, with its sample depth. The battery needs this to
   *  tell a grader that is really grading from one that is quietly falling back
   *  to the fixed ladder forever — the two look identical on screen. */
  census(): Array<[string, number]> {
    return Array.from(this.byCurrency.entries()).map(([k, v]) => [k, v.length])
  }

  /** Test seam + a way to drop a session's memory without rebuilding the stage. */
  reset(): void { this.byCurrency.clear(); this.cursor.clear() }
}

/** The stage's grader. One per page: the distribution IS the session. */
export const amountGrader = new AmountGrader()
