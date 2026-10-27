/**
 * §TWOAGENT (V0437) — what the provider's door onto a REPLICA can decide from the replica alone.
 *
 * A replica is the provider's registry's signed copy of a contract homed on another frame. It knows the contract's
 * status and, from homes on V0434+, which milestones the home has released (`released_milestones`); it does not know
 * the milestones themselves. So the door offers the provider's three acts (accept an offer; deliver the next unpaid
 * milestone; cancel accepted work) and leaves every finer rule to the home, whose refusal it shows verbatim.
 */

export type ReplicaDoor = 'accept' | 'work' | 'none'

/** The released milestone numbers, ascending and unique; [] when the home states none (or an older home did not say). */
export function paidMilestones(released: unknown): number[] {
  if (!Array.isArray(released)) return []
  const seqs = released.map((s) => Number(s)).filter((n) => Number.isInteger(n) && n >= 1)
  return [...new Set(seqs)].sort((a, b) => a - b)
}

/** The lowest milestone the home has not released: what a delivery most likely means. The home decides (it answers
 *  "next submittable is N" when a delivery is already awaiting review). */
export function nextDeliverable(released: unknown): number {
  const paid = new Set(paidMilestones(released))
  let n = 1
  while (paid.has(n)) n += 1
  return n
}

/** Which door a provider sees. `in_progress` is accepted work with a delivery made: more may follow, and it can still
 *  be cancelled, so it is the same door as `agreed`. */
export function doorFor(status: string | null | undefined, justAccepted = false): ReplicaDoor {
  if (justAccepted) return 'work'
  if (status === 'offered') return 'accept'
  if (status === 'agreed' || status === 'in_progress') return 'work'
  return 'none'
}
