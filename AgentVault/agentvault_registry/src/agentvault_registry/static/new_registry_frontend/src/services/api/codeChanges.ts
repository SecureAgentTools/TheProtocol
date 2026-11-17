// V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the Code changes client on the registry's routes (routers/code_changes.py). Reads are public, as the ballot is;
// propose, open the ballot and withdraw act AS the selected agent; a review is the signed-in developer's. A refusal is the registry's {code, detail}: the page
// shows the sentence where it was asked, so the global toast is told these statuses are an answer, not an error.
import { apiClient } from './client'

const REFUSALS = [400, 402, 403, 404, 409, 422, 429]
export type ChangeRecord = Record<string, any>

/** V0666 (order gwo_e086b25f868da7ec9fce9fd2): which registry governs code, and whether this one does. A registry that does not answers every write with 403 and the sentence. */
export interface CodeAuthority { governing: string | null; self: boolean; name: string; console: string | null; sentence: string | null }
export async function getAuthority(): Promise<CodeAuthority> {
  const { data } = await apiClient.get('/code-changes-authority')
  return data
}

export async function listChanges(): Promise<ChangeRecord[]> {
  const { data } = await apiClient.get('/code-changes')
  return Array.isArray(data?.code_changes) ? data.code_changes : []
}
export async function getChange(id: string): Promise<ChangeRecord> {
  const { data } = await apiClient.get(`/code-changes/${encodeURIComponent(id)}`, { expectedStatuses: [404] })
  return data
}
/** The ballot's tally: the governance proposal the change opened (public). A registry that cannot answer leaves the page without numbers, never wrong ones. */
export async function getBallot(proposalId: number): Promise<ChangeRecord | null> {
  try {
    const { data } = await apiClient.get(`/governance/proposals/${proposalId}`, { expectedStatuses: [404] })
    return data || null
  } catch { return null }
}
export interface ProposeBody { repository: string; paths: string[]; title: string; problem: string; bounty?: number; currency?: string; branch?: string; commit?: string; code_distribution?: string; room_id?: string }
export async function proposeChange(body: ProposeBody): Promise<ChangeRecord> {
  const { data } = await apiClient.post('/code-changes', body, { expectedStatuses: REFUSALS })
  return data
}
export async function reviewChange(id: string, body: { verdict: 'approve' | 'changes'; commit: string; findings: string }): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${encodeURIComponent(id)}/reviews`, body, { expectedStatuses: REFUSALS })
  return data
}
export async function openBallot(id: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${encodeURIComponent(id)}/ballot`, {}, { expectedStatuses: REFUSALS })
  return data
}
/** V0667 D4 (order gwo_b12f07e4c5adaa1f5bf4d115): propose a change merged in an organization's release line upstream, to the main code, with its history. A decider's agent
 *  (the selected agent acts); the registry answers with the new main-line change, or its sentence (who decides, the paths, once). */
export async function proposeUpstream(id: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${encodeURIComponent(id)}/upstream`, {}, { expectedStatuses: REFUSALS })
  return data
}
/** V0667 D4: the main-line changes that carry a line's change upstream, newest first, with their provenance and their state (the admin inbox). */
export async function listUpstream(): Promise<ChangeRecord[]> {
  const { data } = await apiClient.get('/code-changes', { params: { upstream: true }, expectedStatuses: [404] })
  return Array.isArray(data?.code_changes) ? data.code_changes : []
}
export async function withdrawChange(id: string, reason: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${encodeURIComponent(id)}/withdraw`, { reason }, { expectedStatuses: REFUSALS })
  return data
}
/** The registry's own sentence for a refusal, else the transport's. */
export function refusalWords(e: any, fallback: string): string {
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || (typeof d?.error?.detail === 'string' && d.error.detail) || e?.message || fallback
}
