// V0663 — agent workflows API. A workflow is a parent record over Guild orders; every route is agent tier (the header's acting
// agent), like the Guild. Server rules: services/workflows.py + services/workflow_rules.py.
import { apiClient } from './client'

export interface WorkflowRuleset {
  bonded_only?: boolean
  min_reputation?: number
  min_proven_orders?: number
  max_price?: number
  org_ids?: string[]
  independent_of?: string[]
}

export interface WorkflowStepView {
  key: string
  position: number
  role: string
  spec?: string | null
  acceptance?: string | null
  budget: string
  deadline_seconds?: number | null
  ruleset: WorkflowRuleset
  input_from?: string | null
  order_id?: string | null
  order_status?: string | null
  output_hash?: string | null
  receipt?: string | null
  needs_attention: boolean
}

export interface ChainLink { step: string; output_hash: string; prev: string; receipt: string }

/** V0664: the template a workflow was made from (POST /workflow-templates/{tid}/instantiate), null when made by hand. */
export interface WorkflowTemplateRef { id: string; version: number | null; content_hash: string | null; title: string | null }

export interface WorkflowView {
  id: string
  owner_did: string
  title: string
  status: 'draft' | 'running' | 'done' | 'cancelled' | string
  ruleset: WorkflowRuleset
  ruleset_hash: string
  total_budget: string
  currency: string
  escrow_note: string
  steps: WorkflowStepView[]
  chain: ChainLink[]
  chain_ok: boolean
  chain_problem?: string | null
  posted_order_id?: string | null
  template?: WorkflowTemplateRef | null
}

export interface WorkflowListItem { id: string; title: string; status: string; total_budget: string; currency: string; created_at: string; template?: WorkflowTemplateRef | null }

export interface StepCandidates { step: string; rules: WorkflowRuleset; scope: string; passing: string[]; refused: number; considered: number }

export interface WorkflowBody {
  title: string
  total_budget: number
  currency?: string
  ruleset?: WorkflowRuleset
  steps: Array<{
    key: string
    role: string
    spec?: string
    acceptance?: string
    budget: number
    deadline_seconds?: number
    ruleset?: WorkflowRuleset
    input_from?: string
  }>
}

export const workflowsApi = {
  async create(body: WorkflowBody): Promise<WorkflowView> {
    const { data } = await apiClient.post('/workflows', body)
    return data
  },
  async mine(limit = 50): Promise<{ workflows: WorkflowListItem[] }> {
    const { data } = await apiClient.get('/workflows', { params: { limit } })
    return data
  },
  async get(id: string): Promise<WorkflowView> {
    const { data } = await apiClient.get(`/workflows/${encodeURIComponent(id)}`)
    return data
  },
  async candidates(id: string, stepKey: string): Promise<StepCandidates> {
    const { data } = await apiClient.get(`/workflows/${encodeURIComponent(id)}/steps/${encodeURIComponent(stepKey)}/candidates`)
    return data
  },
  async advance(id: string): Promise<WorkflowView> {
    const { data } = await apiClient.post(`/workflows/${encodeURIComponent(id)}/advance`)
    return data
  },
  async cancel(id: string): Promise<WorkflowView> {
    const { data } = await apiClient.post(`/workflows/${encodeURIComponent(id)}/cancel`)
    return data
  },
}
