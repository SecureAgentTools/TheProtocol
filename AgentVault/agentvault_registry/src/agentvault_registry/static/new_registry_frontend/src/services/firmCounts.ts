/**
 * V0666 (the Firms page counts the work of a firm's own agents): the one reading of `member_work`, the settled Guild work the
 * agents of a firm did as themselves, by the organization each belonged to when the order was awarded. Every Firms surface
 * (the Firms page, the Discovery lane, the organization list) asks this and nothing else, so no surface can read another number.
 *
 * Two counts, never one number: `jobs` are the orders its agents delivered, `commissioned` the orders its agents posted. Both are
 * kept apart from the firm's own count (the work done AS the firm), and never added into it.
 *
 * Unknown is not zero: an answer that carries no `member_work` (an unlisted firm, a registry that predates it, a failed read)
 * is `null`, and the surface shows no line rather than a false zero. An answer that says 0 and 0 is an honest zero, and the
 * surface says why (`AGENTS_NONE_WHY`).
 */
export type AgentsWork = { jobs: number; commissioned: number }

const whole = (n: unknown): number => (typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.floor(n) : 0)

/** the agents' settled work as the registry states it, or null when it does not say */
export function agentsWork(memberWork: unknown): AgentsWork | null {
  if (!memberWork || typeof memberWork !== 'object') return null
  const m = memberWork as { jobs?: unknown; commissioned?: unknown }
  if (typeof m.jobs !== 'number' && typeof m.commissioned !== 'number') return null
  return { jobs: whole(m.jobs), commissioned: whole(m.commissioned) }
}

/** true when the registry answered and both counts are zero */
export function agentsWorkIsNone(w: AgentsWork | null): boolean {
  return !!w && w.jobs === 0 && w.commissioned === 0
}

/** why a zero is a zero, in the words every surface shows */
export const AGENTS_NONE_WHY =
  'A job counts here once an order its agents were awarded, or posted, settles. Work by an agent that has not joined, or that hides its organization, is not counted.'
