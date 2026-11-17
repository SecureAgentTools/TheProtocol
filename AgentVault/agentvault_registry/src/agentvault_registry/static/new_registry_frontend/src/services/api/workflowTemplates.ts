// V0664 M5 (order gwo_5a4ea8476b97147f3056405e): the template library's client, on the contract's routes (sessionlogs2026/
// DESIGN_2026-11-14_MIGRATION_TEMPLATES.md §D): /api/v1/workflow-templates. Reads are public (no sign-in); purchase, fork and
// instantiate act AS the selected agent (services/api/tier.ts), as the Guild does. A paid template's files are never part of a
// page's answer: only the kit route carries them, to its owner or a buyer, and answers 402 to anyone else.
import { apiClient } from './client'
import {
  normalizeDetail, normalizeListing, listQuery, type Filters, type TemplateDetail, type TemplateListing,
} from '@/services/migrate/templates'
import { normalizeCertificates, normalizeMineList, normalizeRuns, type Certificate, type MyRun, type MyTemplate } from '@/services/migrate/mine'

export interface KitFiles { files: Record<string, string>; content_hash: string; manifest: Record<string, unknown> }

export async function listTemplates(filters: Filters): Promise<TemplateListing[]> {
  const { data } = await apiClient.get('/workflow-templates', { params: listQuery(filters) })
  const rows = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : Array.isArray(data?.templates) ? data.templates : []
  // a row without an id or a title is not a card
  return rows.map(normalizeListing).filter((x: TemplateListing) => x.id && x.title)
}

export async function getTemplate(id: string): Promise<TemplateDetail> {
  const { data } = await apiClient.get(`/workflow-templates/${encodeURIComponent(id)}`)
  return normalizeDetail(data)
}

/** The files of one version: a free template's to anyone, a paid one's to its owner or a buyer (402 to anyone else). This is the
 *  version route, which shows the files without counting a download: the kit route counts one each time and is the CLI's. */
export async function getVersion(id: string, version: number): Promise<KitFiles> {
  const { data } = await apiClient.get(`/workflow-templates/${encodeURIComponent(id)}/versions/${version}`)
  const files: Record<string, string> = {}
  for (const [path, text] of Object.entries((data?.files && typeof data.files === 'object' ? data.files : {}) as Record<string, unknown>)) {
    if (typeof text === 'string') files[path] = text
  }
  return { files, content_hash: String(data?.content_hash || ''), manifest: (data?.manifest || {}) as Record<string, unknown> }
}

export async function purchaseTemplate(id: string): Promise<{ ok: boolean }> {
  const { data } = await apiClient.post(`/workflow-templates/${encodeURIComponent(id)}/purchase`, {})
  return { ok: data?.ok !== false }
}

export async function forkTemplate(id: string): Promise<{ id: string }> {
  const { data } = await apiClient.post(`/workflow-templates/${encodeURIComponent(id)}/fork`, {})
  return { id: String(data?.template_id || '') }
}

/** A V0663 workflow draft from the template's `workflow:` steps, its provenance on it. `total_budget` is required (above zero). */
export async function instantiateTemplate(id: string, body: { total_budget: number; title?: string }): Promise<{ workflow_id: string }> {
  const { data } = await apiClient.post(`/workflow-templates/${encodeURIComponent(id)}/instantiate`, body)
  return { workflow_id: String(data?.workflow_id || '') }
}

/** A private draft from the builder: the kit's files, as text (agent tier; the agent needs contract.template.publish). Nothing is published. */
export async function createTemplate(body: { slug: string; title: string; summary?: string; files: Record<string, string>; visibility?: string; pricing_model?: string; changelog?: string }): Promise<{ template_id: string; version: number; content_hash: string; published: boolean }> {
  const { data } = await apiClient.post('/workflow-templates', { kind: 'migration', visibility: 'private', pricing_model: 'free', ...body }, { expectedStatuses: REFUSALS })
  return { template_id: String(data?.template_id || ''), version: Number(data?.version) || 1, content_hash: String(data?.content_hash || ''), published: !!data?.published }
}

/** Publishing a version: the registry's own sentence when it refuses (the bond among them), kept for the page to show. */
export async function publishVersion(id: string, version: number): Promise<{ published: boolean }> {
  const { data } = await apiClient.post(`/workflow-templates/${encodeURIComponent(id)}/versions/${version}/publish`, {}, { expectedStatuses: REFUSALS })
  return { published: !!data?.published }
}

/** The library's own refusals (a bond is needed, a rule is broken, a name is taken): the page shows the registry's sentence beside the control, so no global toast repeats it. */
const REFUSALS = [400, 402, 403, 409, 422, 429]

/** V0664 (order gwo_ef4d9981fcbba89cb8e5378b): the acting agent's own templates, drafts and unlisted ones too, with versions and buyers.
 *  A registry that does not have the route yet answers 404 or 405: the page says so instead of showing an empty list. */
export async function listMyTemplates(): Promise<MyTemplate[]> {
  const { data } = await apiClient.get('/workflow-templates/mine', { expectedStatuses: [404, 405] })
  return normalizeMineList(data)
}

/** The listing only (title, summary, visibility, price, fork share): never the content, which is a new version. */
export async function patchTemplate(id: string, body: { title?: string; summary?: string; visibility?: string; pricing_model?: string; price?: string; fork_share_bps?: number }): Promise<{ ok: boolean }> {
  await apiClient.patch(`/workflow-templates/${encodeURIComponent(id)}`, body, { expectedStatuses: REFUSALS })
  return { ok: true }
}

/** A draft version of an existing template: the kit's files, as text (the owner). */
export async function addVersion(id: string, body: { files: Record<string, string>; changelog?: string }): Promise<{ version: number; content_hash: string }> {
  const { data } = await apiClient.post(`/workflow-templates/${encodeURIComponent(id)}/versions`, body, { expectedStatuses: REFUSALS })
  return { version: Number(data?.version) || 0, content_hash: String(data?.content_hash || '') }
}

/** The acting agent's workflows, each with the template it was made from (null for one made by hand). */
export async function listMyRuns(limit = 100): Promise<MyRun[]> {
  const { data } = await apiClient.get('/workflows', { params: { limit } })
  return normalizeRuns(data)
}

/** The migration certificates the acting agent holds or issued (the TEG's own attestation list, filtered to the type). */
export async function listMyCertificates(): Promise<Certificate[]> {
  const { data } = await apiClient.get('/teg/attestations', { params: { attestation_type: 'migration.certificate', limit: 100 } })
  return normalizeCertificates(data)
}
