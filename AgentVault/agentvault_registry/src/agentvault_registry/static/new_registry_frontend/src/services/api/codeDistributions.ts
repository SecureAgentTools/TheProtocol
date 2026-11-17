// V0666 D2 (order gwo_f565ebd0575703f199dd9200): the client of an organization's code distributions (its release lines, never an AGORA payout) on the
// registry's routes of D1 (routers/code_distributions.py, the line steps in routers/code_changes.py). Every route answers 404 while
// CODE_DISTRIBUTIONS_ENABLED is off; the pages ask only where registry-config says code_distributions_enabled. A refusal is the registry's
// {code, detail}: the page shows the sentence where it was asked, so the global toast is told these statuses are an answer.
import { apiClient } from './client'
import type { ChangeRecord } from './codeChanges'

const REFUSALS = [400, 402, 403, 404, 409, 422, 429]
export type LineRecord = Record<string, any>

export interface LineBody {
  organization_id: string; slug: string; title: string; base_release: string; open_paths: string[]
  decider_team_id?: string | null; quorum_percent: number; pass_rule: string
}
export type LinePatch = Partial<Pick<LineBody, 'title' | 'open_paths' | 'decider_team_id' | 'quorum_percent' | 'pass_rule'>>

const q = encodeURIComponent

/** An organization's lines (its members). */
export async function listOrgLines(orgId: string): Promise<LineRecord[]> {
  const { data } = await apiClient.get(`/organizations/${q(orgId)}/code-distributions`, { expectedStatuses: [403, 404] })
  return Array.isArray(data?.items) ? data.items : []
}
export async function getLine(slug: string): Promise<LineRecord> {
  const { data } = await apiClient.get(`/code-distributions/${q(slug)}`, { expectedStatuses: [404] })
  return data
}
export async function createLine(body: LineBody): Promise<LineRecord> {
  const { data } = await apiClient.post('/code-distributions', body, { expectedStatuses: REFUSALS })
  return data
}
export async function updateLine(slug: string, patch: LinePatch): Promise<LineRecord> {
  const { data } = await apiClient.patch(`/code-distributions/${q(slug)}`, patch, { expectedStatuses: REFUSALS })
  return data
}
/** A line's changes, newest first (public, as the main line's list is). */
export async function listLineChanges(slug: string, limit = 200): Promise<ChangeRecord[]> {
  const { data } = await apiClient.get('/code-changes', { params: { code_distribution: slug, limit }, expectedStatuses: [404] })
  return Array.isArray(data?.code_changes) ? data.code_changes : []
}
/** A decider's vote, through the selected agent (gov.vote, as the main line votes): one per developer, never changed. */
export async function voteLineChange(cid: string, vote: boolean): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${q(cid)}/code-distribution-vote`, { vote }, { expectedStatuses: REFUSALS })
  return data
}
/** The organization owner's go: recorded and shown; it never shortens the platform's veto window. */
export async function ownerGo(cid: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${q(cid)}/code-distribution-go`, {}, { expectedStatuses: REFUSALS })
  return data
}
export async function ownerVeto(cid: string, reason: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/code-changes/${q(cid)}/code-distribution-veto`, { reason }, { expectedStatuses: REFUSALS })
  return data
}

// -- the Contributions inbox (platform admins, admin_platform) --
export async function adminListLines(): Promise<LineRecord[]> {
  const { data } = await apiClient.get('/admin/code-distributions', { expectedStatuses: [403, 404] })
  return Array.isArray(data?.items) ? data.items : []
}
export async function adminPauseLine(slug: string, reason: string): Promise<LineRecord> {
  const { data } = await apiClient.post(`/admin/code-distributions/${q(slug)}/pause`, { reason }, { expectedStatuses: REFUSALS })
  return data
}
export async function adminResumeLine(slug: string): Promise<LineRecord> {
  const { data } = await apiClient.post(`/admin/code-distributions/${q(slug)}/resume`, {}, { expectedStatuses: REFUSALS })
  return data
}
/** The platform maintainer's veto and go (the main line's own routes; the registry takes them from his account only). */
export async function maintainerVeto(cid: string, reason: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/admin/code-changes/${q(cid)}/veto`, { reason }, { expectedStatuses: REFUSALS })
  return data
}
export async function maintainerGo(cid: string): Promise<ChangeRecord> {
  const { data } = await apiClient.post(`/admin/code-changes/${q(cid)}/go`, {}, { expectedStatuses: REFUSALS })
  return data
}
