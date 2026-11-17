/**
 * V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79): a code change's record in words. The record is
 * the registry's (GET /code-changes/{id}, services/code_changes); this words its state and its one next step and says
 * who is offered which action. The registry decides every step again (membership, independence, the window).
 */
type T = (key: string, fallback: string, params?: Record<string, unknown>) => string

export interface CodeChangeRecord {
  id: string
  state: string
  title?: string
  problem?: string
  repository?: string
  paths?: string[]
  branch?: string | null
  sensitive?: boolean
  reviews_needed?: number
  reviews?: Array<{ reviewer_developer_id?: number; verdict?: string; commit?: string; findings?: string }>
  mode?: string
  order_id?: string | null
  commit?: string | null
  proposer_did?: string | null
  proposal_id?: number | null
  acceptance?: { ok?: boolean; reasons?: string[] } | null
  review_verdict?: { approvals: number; needed: number; blockers: number[]; ok: boolean } | null
  veto_window_closes_at?: string | null
  merged?: { commit?: string; into?: string } | null
  veto?: { reason?: string } | null
  go?: unknown
  [k: string]: unknown
}

export function stateWord(state: string, t: T): string {
  switch (state) {
    case 'proposed': return t('codeChanges.state.proposed', 'Proposed')
    case 'accepted': return t('codeChanges.state.accepted', 'Checks passed')
    case 'balloting': return t('codeChanges.state.balloting', 'Members voting')
    case 'passed': return t('codeChanges.state.passed', 'Passed')
    case 'failed': return t('codeChanges.state.failed', 'Did not pass')
    case 'vetoed': return t('codeChanges.state.vetoed', 'Vetoed')
    case 'merged': return t('codeChanges.state.merged', 'Merged')
    case 'withdrawn': return t('codeChanges.state.withdrawn', 'Withdrawn')
    default: return state
  }
}

export function nextStep(r: CodeChangeRecord, t: T, now: Date = new Date()): string {
  const rv = r.review_verdict || { approvals: 0, needed: 1, blockers: [], ok: false }
  switch (r.state) {
    case 'proposed': {
      const failed = r.acceptance && r.acceptance.ok === false
      if (failed) {
        return t('codeChanges.next.checksFailed', 'The last checks did not pass: {reasons}. A new commit is checked again.',
          { reasons: (r.acceptance?.reasons || []).join('; ') })
      }
      return r.mode === 'bounty'
        ? t('codeChanges.next.delivery', 'Waiting for the worker’s delivery on the Guild order, then its signed check (its CI state, the paths it touches, a secret scan, read from the repository by the checker).')
        : t('codeChanges.next.checks', 'Waiting for the signed check of the named commit (its CI state, the paths it touches, a secret scan, read from the repository by the checker).')
    }
    case 'accepted':
      if (rv.blockers.length) {
        return t('codeChanges.next.blocked', 'A reviewer asks for changes; the ballot waits for a new commit or a new word.')
      }
      if (!rv.ok) {
        const more = Math.max(rv.needed - rv.approvals, 1)
        return more === 1 ? t('codeChanges.next.reviewsOne', 'Needs 1 more independent approval of the checked commit before its ballot.') : t('codeChanges.next.reviews', 'Needs {n} more independent approvals of the checked commit before its ballot.', { n: more })
      }
      return t('codeChanges.next.ballot', 'Reviewed. The proposer opens the members’ ballot.')
    case 'balloting':
      return t('codeChanges.next.voting', 'Members are voting on it in the Senate.')
    case 'passed': {
      const closes = r.veto_window_closes_at ? new Date(r.veto_window_closes_at) : null
      if (!r.go && closes && now < closes) {
        return t('codeChanges.next.window', 'Passed. The maintainer’s veto window is open until {at}; then a session merges the voted commit.',
          { at: closes.toISOString().replace('T', ' ').slice(0, 16) + 'Z' })
      }
      return t('codeChanges.next.merge', 'Passed. A session merges exactly the voted commit; the order then settles with verify.')
    }
    case 'merged':
      return t('codeChanges.next.merged', 'Merged into {into}. It reaches production only through a release.',
        { into: r.merged?.into || '' })
    case 'vetoed':
      return t('codeChanges.next.vetoed', 'Vetoed by the maintainer: {reason}', { reason: r.veto?.reason || '' })
    case 'failed':
      return t('codeChanges.next.failed', 'The members’ ballot did not pass it.')
    default:
      return ''
  }
}

/** Offered to a signed-in person on an accepted change; the registry refuses the proposer, the worker and a non-member. */
export function canReview(r: CodeChangeRecord, signedIn: boolean): boolean {
  return signedIn && r.state === 'accepted' && !!r.commit
}

/** Offered to the proposer's acting agent once the reviews are in. */
export function canOpenBallot(r: CodeChangeRecord, actingDid: string | null | undefined): boolean {
  return r.state === 'accepted' && !!r.review_verdict?.ok && !!actingDid && actingDid === r.proposer_did
}
