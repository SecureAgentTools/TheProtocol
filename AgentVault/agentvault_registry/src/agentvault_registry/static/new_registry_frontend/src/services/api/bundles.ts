// §pass51 — Bundles API service. Mirrors /api/v1/bundles surface.
import { apiClient } from './client'

export interface BundleSummary {
  id: string
  kind: 'snapshot' | 'template' | 'migration'
  name: string
  slug: string | null
  description: string | null
  category: string | null
  source_dev_id: number | null
  source_did: string | null
  visibility: 'private' | 'org' | 'public'
  is_official: boolean
  is_pinned: boolean
  signature_tier: number
  size_bytes: number
  download_count: number
  install_count: number
  rating_avg: number | null
  rating_count: number
  retention_until: string | null
  expires_at: string | null
  created_at: string | null
}

export interface CreateBundlePayload {
  agent_dids: string[]
  kind?: 'snapshot' | 'template' | 'migration'
  name?: string
  description?: string
  visibility?: 'private' | 'org' | 'public'
  slug?: string | null
  category?: string | null
  include_cicd?: boolean
  is_official?: boolean
  sign?: boolean
}

export interface RestoreOptions {
  conflict_resolution?: 'skip' | 'rename' | 'overwrite'
  mode?: 'copy' | 'mirror'
  include_cicd?: boolean
}

export interface ProducedAgent {
  did: string
  name: string
  client_id: string
  client_secret: string
}

export interface RestoreResult {
  success: boolean
  produced_agents: ProducedAgent[]
  warnings: string[]
  errors: string[]
  install_id: number | null
  manifest_summary?: any
}

class BundlesApi {
  base = '/bundles'

  async list(opts: { kind?: string; visibility?: string; include_official?: boolean; limit?: number; offset?: number } = {}): Promise<{ bundles: BundleSummary[]; total: number }> {
    const { data } = await apiClient.get(this.base, { params: opts })
    return data
  }

  async getManifest(id: string): Promise<any> {
    const { data } = await apiClient.get(`${this.base}/${id}/manifest`)
    return data
  }

  async create(payload: CreateBundlePayload): Promise<any> {
    const { data } = await apiClient.post(this.base, payload)
    return data
  }

  async download(id: string): Promise<Blob> {
    const resp = await apiClient.get(`${this.base}/${id}/download`, { responseType: 'blob' })
    return resp.data
  }

  async restoreById(id: string, opts: RestoreOptions = {}): Promise<RestoreResult> {
    const { data } = await apiClient.post(`${this.base}/${id}/restore`, opts)
    return data
  }

  async restoreFromUpload(file: File, opts: RestoreOptions = {}): Promise<RestoreResult> {
    const form = new FormData()
    form.append('file', file)
    if (opts.conflict_resolution) form.append('conflict_resolution', opts.conflict_resolution)
    if (opts.mode) form.append('mode', opts.mode)
    if (opts.include_cicd !== undefined) form.append('include_cicd', String(opts.include_cicd))
    const { data } = await apiClient.post(`${this.base}/restore-from-upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return data
  }

  async fork(id: string, opts: { name?: string; royalty_bps?: number } = {}): Promise<RestoreResult> {
    // GÖDEL FORGE: the fork route restores the agents AND materializes a child bundle with
    // queryable lineage (forked_from + optional royalty carved to ancestors when it earns).
    const { data } = await apiClient.post(`${this.base}/${id}/fork`, opts)
    return data
  }

  async patch(id: string, body: { name?: string; description?: string; visibility?: string; is_pinned?: boolean; category?: string }): Promise<{ updated: boolean }> {
    const { data } = await apiClient.patch(`${this.base}/${id}`, body)
    return data
  }

  async delete(id: string): Promise<void> {
    await apiClient.delete(`${this.base}/${id}`)
  }

  async rate(id: string, rating: number, comment?: string): Promise<{ ok: boolean }> {
    const { data } = await apiClient.post(`${this.base}/${id}/rating`, { rating, comment })
    return data
  }

  async featured(limit = 12): Promise<{ featured: any[]; total: number }> {
    const { data } = await apiClient.get(`${this.base}/marketplace/featured`, { params: { limit } })
    return data
  }
}

export const bundlesApi = new BundlesApi()
