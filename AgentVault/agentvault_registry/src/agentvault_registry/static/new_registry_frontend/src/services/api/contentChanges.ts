// V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane's client on the registry's routes (routers/content_changes.py): an organization's own content (a migration kit,
// a proxy spec, a policy value, a console text, its branding) changed after its line's ballot and our checker. Every route answers 404 while CODE_DISTRIBUTIONS_ENABLED is off.
// A refusal is the registry's {code, detail[, reasons]}: the page shows the sentence where it was asked, so the global toast is told these statuses are an answer.
import { apiClient } from './client'

const REFUSALS = [400, 402, 403, 404, 409, 422, 429]
export type ContentRecord = Record<string, any>
export const CONTENT_KINDS = ['kit', 'proxy_spec', 'policy_value', 'console_text', 'branding', 'compliance_pack'] as const
export type ContentKind = (typeof CONTENT_KINDS)[number]

export interface ContentProposal { code_distribution: string; kind: ContentKind; target: string; title: string; problem: string; content: Record<string, unknown>; room_id?: string }
export interface ContentFilters { code_distribution?: string; state?: string; kind?: string; organization_id?: string; limit?: number }

const q = encodeURIComponent

/** The content changes of the reader's organizations (members), newest first. */
export async function listContentChanges(filters: ContentFilters = {}): Promise<ContentRecord[]> {
  const { data } = await apiClient.get('/content-changes', { params: { limit: 200, ...filters }, expectedStatuses: [404] })
  return Array.isArray(data?.content_changes) ? data.content_changes : []
}
export async function getContentChange(id: string): Promise<ContentRecord> {
  const { data } = await apiClient.get(`/content-changes/${q(id)}`, { expectedStatuses: [404] })
  return data
}
/** A member's agent proposes: our checker runs first, so a refusal here wrote nothing. */
export async function proposeContentChange(body: ContentProposal): Promise<ContentRecord> {
  const { data } = await apiClient.post('/content-changes', body, { expectedStatuses: REFUSALS })
  return data
}
/** A decider's vote, through the selected agent (gov.vote): one per developer, never changed. */
export async function voteContentChange(id: string, vote: boolean): Promise<ContentRecord> {
  const { data } = await apiClient.post(`/content-changes/${q(id)}/vote`, { vote }, { expectedStatuses: REFUSALS })
  return data
}
export async function withdrawContentChange(id: string, reason: string): Promise<ContentRecord> {
  const { data } = await apiClient.post(`/content-changes/${q(id)}/withdraw`, { reason }, { expectedStatuses: REFUSALS })
  return data
}
/** One step back, by the line's deciders or a platform admin; refused when the content changed since. */
export async function undoContentChange(id: string, reason: string): Promise<ContentRecord> {
  const { data } = await apiClient.post(`/content-changes/${q(id)}/undo`, { reason }, { expectedStatuses: REFUSALS })
  return data
}
/** The Contributions inbox's content queue (platform admins, admin_platform). */
export async function adminListContentChanges(filters: ContentFilters = {}): Promise<ContentRecord[]> {
  const { data } = await apiClient.get('/admin/content-changes', { params: { limit: 200, ...filters }, expectedStatuses: [403, 404] })
  return Array.isArray(data?.content_changes) ? data.content_changes : []
}
/** The checker's reasons of a refusal (our checker answers 422 checker_refused with them), else none. */
export function checkerReasons(e: any): string[] {
  const r = e?.response?.data?.reasons
  return Array.isArray(r) ? r.filter((x: unknown) => typeof x === 'string') : []
}
