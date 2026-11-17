// V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; routers/code_passport.py). On a registry that does not govern code: the developer's
// press to take part on the governing registry (never automatic), and their repository account there, read and linked through this registry. A refusal is the
// registry's {code, detail}: the press shows the sentence where it was asked, so the global toast is told these statuses are an answer.
import { apiClient } from './client'
import type { RepoAccountLinked, RepoAccountStatus } from './repoAccount'

const REFUSALS = [403, 404, 409, 422, 502, 503]

/** Exactly what the governing registry receives each time this developer acts (the registry's own preview: unsigned, nothing disclosed by reading it). */
export interface PassportCard {
  schema: string; purpose: string; developer_ref: string; display_name: string | null; home_registry: string; standing: string; agent_did: string; issued_at: string
}
export interface PassportState {
  governing: string; self_governing: boolean; available: boolean; home: string; consented: boolean; consented_at: string | null; preview: PassportCard | null; votes: string
}

export async function getPassport(): Promise<PassportState> {
  const { data } = await apiClient.get('/developers/me/code-passport', { expectedStatuses: REFUSALS })
  return data
}
/** The press (true) and taking it back (false). */
export async function setPassport(consent: boolean): Promise<PassportState> {
  const { data } = await apiClient.put('/developers/me/code-passport', { consent }, { expectedStatuses: REFUSALS })
  return data
}
/** The repository account on the code host, as the governing registry reads it. */
export async function getPassportRepo(): Promise<RepoAccountStatus> {
  const { data } = await apiClient.get('/developers/me/code-passport/repo-account', { expectedStatuses: REFUSALS })
  return data
}
/** Linking it accepts the Terms the status named; the one-time password is answered once and stored nowhere. */
export async function linkPassportRepo(username: string, termsVersion: string): Promise<RepoAccountLinked> {
  const { data } = await apiClient.post('/developers/me/code-passport/repo-account', { username, confirm: true, accept_terms: termsVersion },
    { expectedStatuses: REFUSALS })
  return data
}
