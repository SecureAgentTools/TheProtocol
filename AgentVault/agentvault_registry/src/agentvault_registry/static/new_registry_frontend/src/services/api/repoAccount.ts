// V0667 (order gwo_662c03447bcd627afa4a11e5): the developer's repository account on the public code host (routers/repo_accounts.py). The link is only ever the
// developer's own press: the GET says what the account shares before it; the POST makes the account and answers its one-time password, once (stored nowhere).
// A refusal is the registry's {code, detail}: the page shows the sentence where it was asked, so the global toast is told these statuses are an answer.
import { apiClient } from './client'

const REFUSALS = [403, 404, 409, 422, 503]

export interface RepoAccountPending { op: string; attempts: number; last_error: string | null; last_attempt_at: string | null; next_attempt_at: string | null; stuck: boolean }
export interface RepoAccountStatus { enabled: boolean; host: string; linked: boolean; username: string | null; state: 'active' | 'paused' | 'closed' | null; shares: string[]; pending: RepoAccountPending | null; terms_version?: string }
export interface RepoAccountLinked { username: string; host: string; password: string; sign_in: string; change_password_on_first_sign_in?: boolean; git_config: string }

export async function getRepoAccount(): Promise<RepoAccountStatus> {
  const { data } = await apiClient.get('/developers/me/repo-account')
  return data
}
/** The press accepts the Terms the status named (Terms § 10.2); the registry refuses another version and records the acceptance. */
export async function linkRepoAccount(username: string, termsVersion: string): Promise<RepoAccountLinked> {
  const { data } = await apiClient.post('/developers/me/repo-account', { username, confirm: true, accept_terms: termsVersion }, { expectedStatuses: REFUSALS })
  return data
}
