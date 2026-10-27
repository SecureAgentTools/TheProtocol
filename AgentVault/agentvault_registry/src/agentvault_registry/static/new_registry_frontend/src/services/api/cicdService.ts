// CI/CD Service - Pipeline and Deployment Management
import { apiClient } from './client'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PipelineStage {
  id: string | number
  name: string
  steps: PipelineStep[]
  order?: number
}

export interface PipelineStep {
  id: string | number
  name: string
  command: string
  requires_approval?: boolean
  timeout?: number
  retry_on_failure?: boolean
  environment_variables?: Record<string, string>
}

export interface Pipeline {
  id: string
  agent_did?: string
  pipeline_name: string
  pipeline_config: {
    stages: PipelineStage[]
  }
  trigger_type: 'push' | 'tag' | 'schedule' | 'manual'
  webhook_url: string | null
  webhook_secret?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  last_run_at?: string | null
  run_count?: number
}

export interface AgentVersion {
  id: string
  agent_did?: string
  version: string
  // Backend field is release_notes (maps from DB column "changelog")
  release_notes?: string
  // Keep changelog as alias for backward compat
  changelog?: string
  config_snapshot?: any
  artifacts?: Record<string, any>
  created_at: string
  created_by?: number
  is_active: boolean
  // Backend returns null for these until deployments happen
  deployment_count: number | null
  rollback_count: number | null
  is_stable: boolean
}

export interface Deployment {
  id: string
  agent_did?: string
  pipeline_id?: string
  version_id?: string
  version?: string
  pipeline_name?: string
  environment: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  deployment_type?: string
  deployment_metadata?: Record<string, any>
  started_at: string
  completed_at?: string | null
  duration_seconds?: number | null
  deployed_by?: number
  rollback_from?: string
  logs?: string
  error_message?: string | null
}

export interface PipelineTemplate {
  id: string
  name: string
  description: string
  category: string
  template_config?: any
  price_teg: number
  author_did?: string
  creator_id?: number
  is_public?: boolean
  is_official?: boolean
  downloads?: number
  rating?: number | null
  tags?: string[]
  usage_count?: number
  created_at: string
  updated_at?: string
}

export interface DeploymentLog {
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'debug'
  message: string
  stage?: string
  step?: string
}

export interface CICDStats {
  cicd_enabled: boolean
  last_deployment_at: string | null
  deployment_success_rate: number
  total_deployments: number
  statistics: {
    total: number
    successful: number
    failed: number
    avg_duration_seconds: number
    last_deployment: string | null
  }
}

// ─── Service ─────────────────────────────────────────────────────────────────

class CICDService {

  // Pipeline Management

  async createPipeline(agentDid: string, data: {
    pipeline_name: string
    pipeline_config: { stages: PipelineStage[] }
    trigger_type: string
    webhook_url?: string
  }): Promise<{ pipeline_id: string; webhook_secret: string | null; message: string }> {
    // Backend returns: { pipeline_id, webhook_secret, message }
    const response = await apiClient.post(
      `/agents/${agentDid}/pipelines`,
      data
    )
    return response.data
  }

  async listPipelines(agentDid: string): Promise<Pipeline[]> {
    // Backend returns: { pipelines: [...] }
    const response = await apiClient.get(
      `/agents/${agentDid}/pipelines`
    )
    return response.data.pipelines ?? []
  }

  async getPipeline(agentDid: string, pipelineId: string): Promise<Pipeline> {
    const response = await apiClient.get(
      `/agents/${agentDid}/pipelines/${pipelineId}`
    )
    return response.data
  }

  /** A changed webhook URL comes back with its new secret, once (as create returns it); an unchanged one keeps its secret. */
  async updatePipeline(agentDid: string, pipelineId: string, data: Partial<Pipeline>): Promise<{ message: string; pipeline_id: string; webhook_secret?: string | null }> {
    const response = await apiClient.put(
      `/agents/${agentDid}/pipelines/${pipelineId}`,
      data
    )
    return response.data
  }

  async deletePipeline(agentDid: string, pipelineId: string): Promise<void> {
    await apiClient.delete(`/agents/${agentDid}/pipelines/${pipelineId}`)
  }

  async triggerPipeline(agentDid: string, pipelineId: string): Promise<any> {
    // Triggers a pipeline-based deployment
    const response = await apiClient.post(
      `/agents/${agentDid}/deployments`,
      { pipeline_id: pipelineId, environment: 'production' }
    )
    return response.data
  }

  // Version Management

  async createVersion(agentDid: string, data: {
    version: string
    release_notes?: string
    config_snapshot?: any
    is_stable?: boolean
  }): Promise<{ version_id: string; message: string }> {
    // Backend returns: { version_id, message }
    const response = await apiClient.post(
      `/agents/${agentDid}/versions`,
      data
    )
    return response.data
  }

  async listVersions(agentDid: string): Promise<AgentVersion[]> {
    // Backend returns: { versions: [...] }
    const response = await apiClient.get(
      `/agents/${agentDid}/versions`
    )
    return response.data.versions ?? []
  }

  async activateVersion(agentDid: string, versionId: string): Promise<{ message: string }> {
    // Backend returns: { message }
    const response = await apiClient.post(
      `/agents/${agentDid}/versions/${versionId}/activate`
    )
    return response.data
  }

  async rollbackVersion(agentDid: string, versionId: string): Promise<{ message: string }> {
    const response = await apiClient.post(
      `/agents/${agentDid}/versions/${versionId}/rollback`
    )
    return response.data
  }

  // Deployment Management

  async triggerDeployment(agentDid: string, data: {
    pipeline_id?: string
    version_id?: string
    environment: string
  }): Promise<any> {
    // With pipeline_id: webhook-driven (requires webhook_url on pipeline)
    // Without pipeline_id: manual record, immediately success
    const response = await apiClient.post(
      `/agents/${agentDid}/deployments`,
      data
    )
    return response.data
  }

  async listDeployments(agentDid: string): Promise<Deployment[]> {
    // Backend returns: { deployments: [...] }
    const response = await apiClient.get(
      `/agents/${agentDid}/deployments`
    )
    return response.data.deployments ?? []
  }

  async getDeployment(agentDid: string, deploymentId: string): Promise<Deployment> {
    const response = await apiClient.get(
      `/agents/${agentDid}/deployments/${deploymentId}`
    )
    return response.data
  }

  async updateDeploymentStatus(agentDid: string, deploymentId: string, status: string, metadata?: any): Promise<any> {
    const response = await apiClient.post(
      `/agents/${agentDid}/deployments/${deploymentId}/status`,
      { status, metadata }
    )
    return response.data
  }

  async getDeploymentLogs(agentDid: string, deploymentId: string): Promise<string> {
    const response = await apiClient.get(
      `/agents/${agentDid}/deployments/${deploymentId}`
    )
    return response.data.logs ?? ''
  }

  async cancelDeployment(agentDid: string, deploymentId: string): Promise<void> {
    await apiClient.post(
      `/agents/${agentDid}/deployments/${deploymentId}/status`,
      { status: 'cancelled' }
    )
  }

  // Template Marketplace

  async listTemplates(params?: { category?: string; search?: string }): Promise<PipelineTemplate[]> {
    // Backend returns: { templates: [...] }
    const response = await apiClient.get('/pipeline-templates', { params })
    return response.data.templates ?? []
  }

  async getTemplate(templateId: string): Promise<PipelineTemplate> {
    const response = await apiClient.get(`/pipeline-templates/${templateId}`)
    return response.data
  }

  async createTemplate(data: {
    name: string
    description: string
    template_config: any
    category: string
    price_teg?: number
    is_public?: boolean
  }): Promise<any> {
    const response = await apiClient.post('/pipeline-templates', data)
    return response.data
  }

  // Statistics

  async getCICDStats(agentDid: string): Promise<CICDStats> {
    const response = await apiClient.get(`/agents/${agentDid}/cicd-stats`)
    return response.data
  }
}

export const cicdService = new CICDService()
