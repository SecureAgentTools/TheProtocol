// V0667 (order gwo_662c03447bcd627afa4a11e5): what a repository account means for proposing a code change, as the console words it. The registry decides again
// at the press (services/repo_accounts.require_linked: 409 repo_account_required, _paused, _closed); this only greys the button and says why.
import type { RepoAccountStatus } from '@/services/api/repoAccount'

/** What stops a code change, or null: off, unknown (not read) or linked and active stops nothing; the registry decides again at the press. */
export function repoAccountBlocks(st: RepoAccountStatus | null): 'required' | 'paused' | 'closed' | null {
  if (!st || !st.enabled) return null
  if (!st.linked) return 'required'
  if (st.state === 'paused') return 'paused'
  if (st.state === 'closed') return 'closed'
  return null
}
