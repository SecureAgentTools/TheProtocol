// CI/CD Store - Pipeline and Deployment State Management
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { cicdService } from '@/services/api/cicdService'
import type {
  Pipeline,
  PipelineStage,
  PipelineStep,
  AgentVersion,
  Deployment,
  PipelineTemplate,
  CICDStats
} from '@/services/api/cicdService'
import { useToast } from '@/composables/useToast'

export const useCICDStore = defineStore('cicd', () => {
  // State
  const pipelines = ref<Pipeline[]>([])
  const currentPipeline = ref<Pipeline | null>(null)
  const versions = ref<AgentVersion[]>([])
  const currentVersion = ref<AgentVersion | null>(null)
  const deployments = ref<Deployment[]>([])
  const currentDeployment = ref<Deployment | null>(null)
  const deploymentLogs = ref<string>('')
  const templates = ref<PipelineTemplate[]>([])
  const cicdStats = ref<CICDStats | null>(null)
  const isLoading = ref(false)
  const loadingStates = ref<Record<string, boolean>>({})
  /**
   * §FESUITE (V0577): which list reads got no answer. Each swallowed its failure into a console line, so the member
   * CI/CD page said "No pipelines configured" / "No versions yet" / "No deployments found" with counts of 0 and a red
   * "0.0%" success rate over reads that never answered; and, the store being one for every agent, the previous agent's
   * lists (and the previous deployment's logs) stayed on screen under the next one's name. A failed per-agent read now
   * clears its list and sets its flag; the templates (the same for every agent) keep what they last read.
   */
  const readFailed = ref({ pipelines: false, versions: false, deployments: false, logs: false, templates: false })

  // Draft pipeline for builder
  const draftPipeline = ref<{
    pipeline_name: string
    stages: PipelineStage[]
    trigger_type: 'push' | 'tag' | 'schedule' | 'manual'
    webhook_url: string
  }>({
    pipeline_name: '',
    stages: [],
    trigger_type: 'manual',
    webhook_url: ''
  })

  // Filters
  const filters = ref({
    environment: '',
    status: '',
    search: ''
  })

  const toast = useToast()

  /** §FESUITE — the server's sentence for a refusal (an axios error's own message is only "status code 422"). */
  function why(error: any): string {
    const d = error?.response?.data
    const detail = d?.detail ?? d?.error?.detail ?? d?.message
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail === 'object') return JSON.stringify(detail).slice(0, 300)
    return error?.message || 'Request failed'
  }

  /**
   * §FESUITE — a pipeline's webhook secret is answered ONCE, at creation. It used to travel only inside a toast that
   * nothing rendered, so no one ever saw it; the view now shows it in place until the person dismisses it.
   */
  const revealedWebhookSecret = ref<{ pipeline: string; secret: string } | null>(null)
  function dismissWebhookSecret() { revealedWebhookSecret.value = null }

  // Computed
  const activeVersion = computed(() =>
    versions.value.find(v => v.is_active)
  )

  const stableVersions = computed(() =>
    versions.value.filter(v => v.is_stable)
  )

  const recentDeployments = computed(() =>
    deployments.value.slice(0, 10)
  )

  const runningDeployments = computed(() =>
    deployments.value.filter(d => d.status === 'running')
  )

  const deploymentStats = computed(() => {
    const total = deployments.value.length
    const successful = deployments.value.filter(d => d.status === 'success').length
    const failed = deployments.value.filter(d => d.status === 'failed').length
    const successRate = total > 0 ? (successful / total) * 100 : 0
    return { total, successful, failed, successRate: successRate.toFixed(1) }
  })

  const filteredDeployments = computed(() => {
    let result = [...deployments.value]
    if (filters.value.environment) result = result.filter(d => d.environment === filters.value.environment)
    if (filters.value.status) result = result.filter(d => d.status === filters.value.status)
    if (filters.value.search) {
      const s = filters.value.search.toLowerCase()
      result = result.filter(d => d.id.toLowerCase().includes(s) || d.version_id?.toLowerCase().includes(s))
    }
    return result
  })

  // Has any pipeline with a webhook URL configured (required for pipeline-driven deployments)
  const hasWebhookPipeline = computed(() =>
    pipelines.value.some(p => p.webhook_url && p.is_active)
  )

  const webhookPipelines = computed(() =>
    pipelines.value.filter(p => p.webhook_url && p.is_active)
  )

  // ── Pipeline Actions ───────────────────────────────────────────────────────

  async function fetchPipelines(agentDid: string) {
    setLoading('pipelines', true)
    try {
      pipelines.value = await cicdService.listPipelines(agentDid)
      readFailed.value.pipelines = false
    } catch (error: any) {
      console.error('Failed to fetch pipelines:', error)
      pipelines.value = []
      readFailed.value.pipelines = true
    } finally {
      setLoading('pipelines', false)
    }
  }

  async function createPipeline(agentDid: string) {
    if (!draftPipeline.value.pipeline_name) {
      toast.error('Pipeline name is required')
      return
    }
    if (draftPipeline.value.stages.length === 0) {
      toast.error('At least one stage is required')
      return
    }

    setLoading('createPipeline', true)
    try {
      const result = await cicdService.createPipeline(agentDid, {
        pipeline_name: draftPipeline.value.pipeline_name,
        pipeline_config: { stages: draftPipeline.value.stages },
        trigger_type: draftPipeline.value.trigger_type,
        webhook_url: draftPipeline.value.webhook_url || undefined
      })

      if (result.webhook_secret) {
        revealedWebhookSecret.value = { pipeline: draftPipeline.value.pipeline_name, secret: result.webhook_secret }
        toast.success('Pipeline created', 'Copy its webhook secret from the page now: it is shown once.')
      } else {
        toast.success('Pipeline created')
      }

      // Refetch full list to get proper Pipeline objects
      await fetchPipelines(agentDid)
      clearDraftPipeline()
      return result
    } catch (error: any) {
      toast.error('Failed to create pipeline', why(error))
      throw error
    } finally {
      setLoading('createPipeline', false)
    }
  }

  async function updatePipeline(agentDid: string, pipelineId: string, data: Partial<Pipeline>) {
    setLoading('updatePipeline', true)
    try {
      const result = await cicdService.updatePipeline(agentDid, pipelineId, data)
      await fetchPipelines(agentDid)
      if (result?.webhook_secret) {
        // §FESUITE: a new webhook address gets a new secret; it is shown once, as at create
        const name = pipelines.value.find(p => p.id === pipelineId)?.pipeline_name || pipelineId
        revealedWebhookSecret.value = { pipeline: name, secret: result.webhook_secret }
        toast.success('Pipeline updated', 'Its webhook address changed, so it has a new secret: copy it from the page now, it is shown once.')
      } else {
        toast.success('Pipeline updated successfully')
      }
    } catch (error: any) {
      toast.error('Failed to update pipeline', why(error))
      throw error
    } finally {
      setLoading('updatePipeline', false)
    }
  }

  /** The view asks first (the shared confirm dialog); a store never opens the browser's own confirm(). */
  async function deletePipeline(agentDid: string, pipelineId: string) {
    setLoading('deletePipeline', true)
    try {
      await cicdService.deletePipeline(agentDid, pipelineId)
      pipelines.value = pipelines.value.filter(p => p.id !== pipelineId)
      if (currentPipeline.value?.id === pipelineId) currentPipeline.value = null
      toast.success('Pipeline deleted')
    } catch (error: any) {
      toast.error('Failed to delete pipeline', why(error))
      throw error
    } finally {
      setLoading('deletePipeline', false)
    }
  }

  async function triggerPipeline(agentDid: string, pipelineId: string) {
    setLoading('triggerPipeline', true)
    try {
      const deployment = await cicdService.triggerPipeline(agentDid, pipelineId)
      toast.success('Pipeline triggered successfully')
      await fetchDeployments(agentDid)
      return deployment
    } catch (error: any) {
      toast.error('Failed to trigger pipeline', why(error))
      throw error
    } finally {
      setLoading('triggerPipeline', false)
    }
  }

  // ── Version Actions ────────────────────────────────────────────────────────

  async function fetchVersions(agentDid: string) {
    setLoading('versions', true)
    try {
      versions.value = await cicdService.listVersions(agentDid)
      readFailed.value.versions = false
    } catch (error: any) {
      console.error('Failed to fetch versions:', error)
      versions.value = []
      readFailed.value.versions = true
    } finally {
      setLoading('versions', false)
    }
  }

  async function createVersion(agentDid: string, data: {
    version: string
    release_notes?: string
    config_snapshot?: any
    is_stable?: boolean
  }) {
    setLoading('createVersion', true)
    try {
      const result = await cicdService.createVersion(agentDid, data)
      toast.success(`Version ${data.version} created successfully`)
      // Refetch full list to get proper AgentVersion objects
      await fetchVersions(agentDid)
      return result
    } catch (error: any) {
      toast.error('Failed to create version', why(error))
      throw error
    } finally {
      setLoading('createVersion', false)
    }
  }

  async function activateVersion(agentDid: string, versionId: string) {
    setLoading('activateVersion', true)
    try {
      await cicdService.activateVersion(agentDid, versionId)
      // Refetch to get updated is_active flags (backend returns only { message })
      await fetchVersions(agentDid)
      const activated = versions.value.find(v => v.id === versionId)
      toast.success(`Version ${activated?.version ?? ''} activated`)
      return activated
    } catch (error: any) {
      toast.error('Failed to activate version', why(error))
      throw error
    } finally {
      setLoading('activateVersion', false)
    }
  }

  /** The view asks first (the shared confirm dialog). */
  async function rollbackVersion(agentDid: string, versionId: string) {
    setLoading('rollbackVersion', true)
    try {
      await cicdService.rollbackVersion(agentDid, versionId)
      await fetchVersions(agentDid)
      const version = versions.value.find(v => v.id === versionId)
      toast.success(`Rolled back to version ${version?.version ?? ''}`)
    } catch (error: any) {
      toast.error('Failed to rollback version', why(error))
      throw error
    } finally {
      setLoading('rollbackVersion', false)
    }
  }

  // ── Deployment Actions ─────────────────────────────────────────────────────

  async function fetchDeployments(agentDid: string) {
    setLoading('deployments', true)
    try {
      deployments.value = await cicdService.listDeployments(agentDid)
      readFailed.value.deployments = false
    } catch (error: any) {
      console.error('Failed to fetch deployments:', error)
      deployments.value = []
      readFailed.value.deployments = true
    } finally {
      setLoading('deployments', false)
    }
  }

  async function fetchCICDStats(agentDid: string) {
    try {
      cicdStats.value = await cicdService.getCICDStats(agentDid)
    } catch (error: any) {
      console.error('Failed to fetch CI/CD stats:', error)
    }
  }

  async function triggerDeployment(agentDid: string, data: {
    pipeline_id?: string
    version_id?: string
    environment: string
  }) {
    setLoading('triggerDeployment', true)
    try {
      const deployment = await cicdService.triggerDeployment(agentDid, data)
      toast.success(`Deployment to ${data.environment} started`)
      await fetchDeployments(agentDid)
      return deployment
    } catch (error: any) {
      toast.error('Failed to trigger deployment', why(error))
      throw error
    } finally {
      setLoading('triggerDeployment', false)
    }
  }

  async function fetchDeploymentLogs(agentDid: string, deploymentId: string) {
    setLoading('logs', true)
    try {
      deploymentLogs.value = await cicdService.getDeploymentLogs(agentDid, deploymentId)
      readFailed.value.logs = false
    } catch (error: any) {
      console.error('Failed to fetch deployment logs:', error)
      deploymentLogs.value = ''
      readFailed.value.logs = true
    } finally {
      setLoading('logs', false)
    }
  }

  async function cancelDeployment(agentDid: string, deploymentId: string) {

    setLoading('cancelDeployment', true)
    try {
      await cicdService.cancelDeployment(agentDid, deploymentId)
      const index = deployments.value.findIndex(d => d.id === deploymentId)
      if (index !== -1) deployments.value[index].status = 'cancelled'
      if (currentDeployment.value?.id === deploymentId) currentDeployment.value.status = 'cancelled'
      toast.success('Deployment cancelled')
    } catch (error: any) {
      toast.error('Failed to cancel deployment', why(error))
      throw error
    } finally {
      setLoading('cancelDeployment', false)
    }
  }

  // ── Template Actions ───────────────────────────────────────────────────────

  async function fetchTemplates(params?: { category?: string; search?: string }) {
    setLoading('templates', true)
    try {
      templates.value = await cicdService.listTemplates(params)
      readFailed.value.templates = false
    } catch (error: any) {
      console.error('Failed to fetch templates:', error)
      readFailed.value.templates = true
    } finally {
      setLoading('templates', false)
    }
  }

  async function useTemplate(template: PipelineTemplate) {
    draftPipeline.value = {
      pipeline_name: template.name,
      stages: template.template_config?.stages || [],
      trigger_type: template.template_config?.trigger_type || 'manual',
      webhook_url: template.template_config?.webhook_url || ''
    }
    toast.success('Template loaded into pipeline builder')
  }

  // ── Draft Pipeline ─────────────────────────────────────────────────────────

  function addStage() {
    draftPipeline.value.stages.push({
      id: Date.now(),
      name: `Stage ${draftPipeline.value.stages.length + 1}`,
      steps: [],
      order: draftPipeline.value.stages.length
    })
  }

  function removeStage(index: number) {
    draftPipeline.value.stages.splice(index, 1)
  }

  function addStep(stageIndex: number) {
    const stage = draftPipeline.value.stages[stageIndex]
    if (stage) {
      stage.steps.push({ id: Date.now(), name: '', command: '' })
    }
  }

  function removeStep(stageIndex: number, stepIndex: number) {
    const stage = draftPipeline.value.stages[stageIndex]
    if (stage) stage.steps.splice(stepIndex, 1)
  }

  function updateStageOrder(newStages: PipelineStage[]) {
    draftPipeline.value.stages = newStages.map((stage, index) => ({ ...stage, order: index }))
  }

  function clearDraftPipeline() {
    draftPipeline.value = { pipeline_name: '', stages: [], trigger_type: 'manual', webhook_url: '' }
    currentPipeline.value = null
  }

  /**
   * §FESUITE — Edit loads a pipeline into the builder; saving it must change THAT pipeline. The builder always called
   * createPipeline, so every edit made a second pipeline beside the first.
   */
  async function saveEditedPipeline(agentDid: string) {
    const target = currentPipeline.value
    if (!target) return createPipeline(agentDid)
    const body: Record<string, unknown> = {
      pipeline_name: draftPipeline.value.pipeline_name,
      pipeline_config: { stages: draftPipeline.value.stages },
      trigger_type: draftPipeline.value.trigger_type,
    }
    // The server issues a NEW webhook secret whenever an update carries webhook_url, and the update does not answer it:
    // send the URL only when it changed, so an unrelated edit does not silently break the CI server's signed calls.
    const url = draftPipeline.value.webhook_url || ''
    const urlChanged = url !== (target.webhook_url || '')
    if (urlChanged) body.webhook_url = url || null
    await updatePipeline(agentDid, target.id, body as any)
    if (urlChanged && url) {
      toast.warning('Webhook secret replaced', 'The webhook URL changed, so the server issued a new secret it does not show. Recreate the pipeline to see a secret.')
    }
    clearDraftPipeline()
  }

  function saveDraftToLocalStorage() {
    try {
      localStorage.setItem('cicd_draft_pipeline', JSON.stringify(draftPipeline.value))
      toast.success('Pipeline draft saved')
    } catch { /* expected */ }
  }

  function loadDraftFromLocalStorage() {
    try {
      const saved = localStorage.getItem('cicd_draft_pipeline')
      if (saved) {
        draftPipeline.value = JSON.parse(saved)
        toast.success('Pipeline draft loaded')
      }
    } catch (error) {
      console.error('Failed to load draft:', error)
    }
  }

  // ── Utility ────────────────────────────────────────────────────────────────

  function setLoading(key: string, value: boolean) {
    loadingStates.value[key] = value
    isLoading.value = Object.values(loadingStates.value).some(v => v)
  }

  function selectPipeline(pipeline: Pipeline) {
    currentPipeline.value = pipeline
  }

  function selectDeployment(deployment: Deployment) {
    currentDeployment.value = deployment
  }

  function applyFilters(newFilters: Partial<typeof filters.value>) {
    filters.value = { ...filters.value, ...newFilters }
  }

  function clearFilters() {
    filters.value = { environment: '', status: '', search: '' }
  }

  function initialize() {
    loadDraftFromLocalStorage()
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout.
  function $reset() {
    pipelines.value = []
    currentPipeline.value = null
    versions.value = []
    currentVersion.value = null
    deployments.value = []
    currentDeployment.value = null
    deploymentLogs.value = ''
    templates.value = []
    cicdStats.value = null
    isLoading.value = false
    loadingStates.value = {}
    readFailed.value = { pipelines: false, versions: false, deployments: false, logs: false, templates: false }
    filters.value = { environment: '', status: '', search: '' }
    // draftPipeline is local UX state — preserved for the new user (they
    // see a blank builder; that's the correct UX even after logout)
  }

  return {
    // State
    pipelines, currentPipeline, versions, currentVersion,
    deployments, currentDeployment, deploymentLogs,
    templates, cicdStats, isLoading, loadingStates, readFailed, draftPipeline, filters,
    $reset,

    // Computed
    activeVersion, stableVersions, recentDeployments, runningDeployments,
    deploymentStats, filteredDeployments, hasWebhookPipeline, webhookPipelines,

    // Pipeline
    fetchPipelines, createPipeline, updatePipeline, deletePipeline, triggerPipeline, selectPipeline,
    saveEditedPipeline, revealedWebhookSecret, dismissWebhookSecret,

    // Versions
    fetchVersions, createVersion, activateVersion, rollbackVersion,

    // Deployments
    fetchDeployments, fetchCICDStats, triggerDeployment, fetchDeploymentLogs, cancelDeployment, selectDeployment,

    // Templates
    fetchTemplates, useTemplate,

    // Draft
    addStage, removeStage, addStep, removeStep, updateStageOrder,
    clearDraftPipeline, saveDraftToLocalStorage, loadDraftFromLocalStorage,

    // Utility
    applyFilters, clearFilters, initialize
  }
})
