/**
 * §BATCH0911 item 2b — a proposal's quorum, drawn the way the tally that decides it applies it.
 *
 * Each proposal STORES its quorum when it is proposed (the frame's declared value for its type, so
 * a policy_change on EU carries 20 while an ordinary proposal carries 10). `tally_proposal` applies
 * that stored value, and applies NO quorum check when none is stored or when the network holds no
 * voting power. So the only honest fallbacks are "no line" and "no required figure": a literal would
 * describe one frame's ordinary proposals today and nothing the tally actually does.
 */

/** Horizontal position (0..100) of the quorum line on the vote bar, or null when there is no line. */
export function quorumMarkerLeft(quorumPercent: number | null | undefined): number | null {
  return quorumPercent == null ? null : Math.min(quorumPercent, 100)
}

/**
 * §MEMBERSHIP (2026-10-02, agentvault2-33's migration 0185) — a decided proposal keeps the numbers it was decided on.
 * The unit of a proposal's figures is the one its tally stored (a registry can switch between lock and member mode
 * later), else the registry's mode now (an open proposal, or one tallied before the numbers were stored).
 */
export function proposalUnit(p: { tallyWeightMode?: string | null }, memberModeNow: boolean): 'member' | 'lock' {
  if (p.tallyWeightMode === 'member' || p.tallyWeightMode === 'lock') return p.tallyWeightMode
  return memberModeNow ? 'member' : 'lock'
}

/** The quorum a decided proposal was decided on, or null where its tally stored none (then the floor shows "as of now"). */
export function storedQuorumRequired(p: { tallyWeightMode?: string | null; tallyQuorumRequired?: number | null }): number | null {
  const q = p.tallyQuorumRequired
  return (p.tallyWeightMode === 'member' || p.tallyWeightMode === 'lock') && typeof q === 'number' && Number.isFinite(q) ? q : null
}

/** Why a decided proposal failed, as its tally stored it (agentvault2-33's 0185): the quorum was not met, or the
 *  majority was against. Null for any other status, and where the tally stored no answer (tallied before 0185): no
 *  reason is claimed then. A passed proposal always met its quorum. */
export function failureReason(p: { status?: string | null; tallyQuorumMet?: boolean | null }): 'quorum_not_met' | 'majority_against' | null {
  if (String(p.status || '').toLowerCase() !== 'failed') return null
  if (p.tallyQuorumMet === false) return 'quorum_not_met'
  if (p.tallyQuorumMet === true) return 'majority_against'
  return null
}

/** Voting power a proposal needs to reach quorum, or null when it cannot be computed honestly. */
export function requiredPower(networkVePower: unknown, quorumPercent: number | null | undefined): number | null {
  if (quorumPercent == null) return null
  const np = parseFloat(String(networkVePower ?? ''))
  if (!Number.isFinite(np) || np <= 0) return null
  return Math.round(np * (quorumPercent / 100) * 100) / 100
}
