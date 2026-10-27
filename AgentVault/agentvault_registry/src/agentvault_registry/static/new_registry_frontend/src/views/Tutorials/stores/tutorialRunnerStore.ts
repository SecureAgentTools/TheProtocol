// ============================================================================
// TheProtocol Tutorial System — Pinia Store
// Manages all tutorial runtime state, step execution, variable capture,
// and progress persistence.
//
// AUTH CONTEXT DISTINCTION:
//   - Production JWT (authStore.token) → authenticates user to /admin/tutorial/execute
//     This is handled AUTOMATICALLY by apiClient's axios interceptor.
//   - Sandbox tokens (capturedValues) → forwarded to registry-test via the proxy
//     These are captured step-by-step: $developerToken, $bootstrapToken, $agentToken
//     They live entirely within capturedValues and never touch authStore.
// ============================================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  TutorialTrack,
  TutorialStep,
  StepResult,
  SavedTrackProgress,
  CaptureRule,
  DynamicBodyField
} from '../types/tutorial.types'
import { tutorialApiService } from '../services/tutorialApiService'
import { allTracks } from '../data/trackDefinitions'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('tutorialRunner')

const STORAGE_KEY = 'theprotocol_tutorial_progress'

// Form-encoded endpoints (must match backend FORM_ENDPOINTS)
const FORM_ENDPOINTS = new Set(['/auth/login', '/auth/agent/token'])

/** f038: the achievement a finished track records, `tutorial_<track id>` (agent-lifecycle -> tutorial_agent_lifecycle).
 *  D6-737: derived from the id, so every track records one; a hand-kept map named the first twelve and the four newer
 *  tracks (AGORA Trading, Organizations, CI/CD, Regulatory Approval) recorded nothing. */
export function achievementTypeFor(trackId: string): string {
  return `tutorial_${trackId.replace(/-/g, '_')}`
}

export const useTutorialRunnerStore = defineStore('tutorialRunner', () => {
  // --- State ---
  const activeTrack = ref<TutorialTrack | null>(null)
  const currentStepIndex = ref(0)
  const completedStepIds = ref<Set<string>>(new Set())
  const capturedValues = ref<Record<string, any>>({})
  const stepResults = ref<Record<string, StepResult>>({})
  const isExecuting = ref(false)
  const sandboxHealthy = ref<boolean | null>(null)

  // --- Computed ---
  const currentStep = computed((): TutorialStep | null =>
    activeTrack.value?.steps[currentStepIndex.value] ?? null
  )

  const totalSteps = computed(() =>
    activeTrack.value?.steps.length ?? 0
  )

  const completedCount = computed(() => completedStepIds.value.size)

  const progressPercent = computed(() =>
    totalSteps.value > 0
      ? Math.round((completedCount.value / totalSteps.value) * 100)
      : 0
  )

  const canExecuteCurrentStep = computed(() => {
    if (!currentStep.value || isExecuting.value) return false
    const step = currentStep.value
    if (!step.requiresStepId) return true
    return completedStepIds.value.has(step.requiresStepId)
  })

  const canAdvance = computed(() =>
    currentStep.value
      ? completedStepIds.value.has(currentStep.value.id)
      : false
  )

  const isTrackComplete = computed(() =>
    activeTrack.value
      ? activeTrack.value.steps.every(s => completedStepIds.value.has(s.id))
      : false
  )

  // --- Actions ---

  function loadTrack(track: TutorialTrack) {
    activeTrack.value = track
    currentStepIndex.value = 0
    completedStepIds.value = new Set()
    capturedValues.value = {}
    stepResults.value = {}

    // Restore saved progress
    const saved = loadProgress(track.id)
    if (saved) {
      completedStepIds.value = new Set(saved.completedStepIds)
      capturedValues.value = { ...saved.capturedValues }
      currentStepIndex.value = saved.lastStepIndex
    }
  }

  function goToStep(index: number) {
    if (index >= 0 && index < totalSteps.value) {
      currentStepIndex.value = index
    }
  }

  function nextStep() {
    if (currentStepIndex.value < totalSteps.value - 1) {
      currentStepIndex.value++
    }
  }

  function previousStep() {
    if (currentStepIndex.value > 0) {
      currentStepIndex.value--
    }
  }

  /**
   * Core execution: run the current step's API call through the proxy.
   *
   * Flow:
   * 1. Resolve path variables ($agentDid → actual DID)
   * 2. Resolve body variables ($bootstrapToken → actual token)
   * 3. Determine which SANDBOX token to forward
   * 4. Call tutorialApiService.executeStep (production auth is automatic)
   * 5. Validate response
   * 6. Capture values from response
   * 7. Persist progress
   */
  async function executeCurrentStep(): Promise<StepResult> {
    const step = currentStep.value
    if (!step) throw new Error('No active step')

    isExecuting.value = true

    // Build resolved path (replace $variables)
    const resolvedPath = resolvePath(step.apiCall.path, step.apiCall.pathParams)

    // Build resolved body (inject captured values)
    const resolvedBody = resolveBody(step.apiCall.body, step.apiCall.bodyDynamic)

    // Determine sandbox auth token from captured values
    const sandboxToken = resolveSandboxAuthToken(step.apiCall.authType, step.apiCall.authTokenRef)
    const isDirectCall = !!step.apiCall.targetBase
    const isFormEncoded = step.apiCall.formEncoded || FORM_ENDPOINTS.has(resolvedPath)

    // Build display URL — direct calls show targetBase, proxy calls show default sandbox
    const displayUrl = isDirectCall
      ? tutorialApiService.buildDirectDisplayUrl(step.apiCall.targetBase!, resolvedPath)
      : tutorialApiService.buildDisplayUrl(resolvedPath)

    // Build display headers (informational — shows what hits the sandbox)
    const displayHeaders = tutorialApiService.buildDisplayHeaders(
      step.apiCall.authType,
      sandboxToken || undefined,
      isFormEncoded,
      step.apiCall.headers
    )

    // Record the request we're about to make
    const result: StepResult = {
      stepId: step.id,
      status: 'executing',
      request: {
        method: step.apiCall.method,
        url: displayUrl,
        headers: displayHeaders,
        body: resolvedBody
      },
      executedAt: new Date().toISOString()
    }
    stepResults.value[step.id] = result

    try {
      // Route: admin endpoint (direct to registry-a) OR direct call (targetBase) OR proxy
      const isAdminEndpoint = resolvedPath.startsWith('/admin/tutorial/')
      const response = isAdminEndpoint
        ? await (async () => {
            // Admin tutorial endpoints run on registry-a directly (not proxied to sandbox)
            const { apiClient } = await import('@/services/api/client')
            const startTime = Date.now()
            try {
              // generate-proof proves two at a time on the server, so a call can queue: 180 s, like tutorialApiService.
              const resp = await apiClient.post(resolvedPath, resolvedBody, { timeout: 180000 })
              return { statusCode: resp.status || 200, body: resp.data, timeMs: Date.now() - startTime }
            } catch (err: any) {
              return {
                statusCode: err.response?.status || 0,
                body: err.response?.data || null,
                timeMs: Date.now() - startTime,
                error: err.message
              }
            }
          })()
        : isDirectCall
        ? await tutorialApiService.executeDirectCall(
            step.apiCall.method,
            step.apiCall.targetBase!,
            resolvedPath,
            resolvedBody,
            sandboxToken,
            step.apiCall.authType,
            isFormEncoded
          )
        : await tutorialApiService.executeStep(
            step.apiCall,
            resolvedBody,
            resolvedPath,
            sandboxToken,
            step.apiCall.authType
          )

      result.response = {
        statusCode: response.statusCode,
        body: response.body,
        timeMs: response.timeMs
      }

      // Validate
      const isSuccess = step.validation.successStatusCodes.includes(response.statusCode)

      if (isSuccess) {
        result.status = 'success'

        // Capture values from response
        if (step.captures && response.body) {
          const captured: Record<string, any> = {}
          for (const rule of step.captures) {
            const value = getNestedValue(response.body, rule.responsePath)
            if (value !== undefined) {
              captured[rule.key] = value
              capturedValues.value[rule.key] = value
            }
          }
          result.capturedValues = captured
        }

        // Mark complete
        completedStepIds.value.add(step.id)

        // Persist
        saveProgress()

        // f038: Record achievement if track just completed
        if (activeTrack.value && activeTrack.value.steps.every(s => completedStepIds.value.has(s.id))) {
          recordAchievement(activeTrack.value)
        }
      } else {
        result.status = 'failed'
        result.error = response.error ||
          step.validation.failureMessage ||
          `Expected status ${step.validation.successStatusCodes.join('/')}, got ${response.statusCode}`
      }
    } catch (err: any) {
      result.status = 'failed'
      result.error = err.message
    } finally {
      isExecuting.value = false
      stepResults.value[step.id] = { ...result }
    }

    return result
  }

  // --- Sandbox Auth Token Resolution ---
  // All sandbox tokens come from capturedValues — NEVER from authStore

  function resolveSandboxAuthToken(authType: string, tokenRef?: string): string | null {
    // If explicit token reference provided, use it
    if (tokenRef) {
      const key = tokenRef.startsWith('$') ? tokenRef.slice(1) : tokenRef
      return capturedValues.value[key] || null
    }
    // Fallback: infer from authType using convention
    if (authType === 'developer' || authType === 'admin') {
      return capturedValues.value['developerToken'] || null
    }
    if (authType === 'agent') {
      return capturedValues.value['agentToken'] || null
    }
    if (authType === 'bootstrap') {
      return capturedValues.value['bootstrapToken'] || null
    }
    return null
  }

  // --- Variable Resolution ---

  function resolvePath(
    path: string,
    pathParams?: Record<string, string>
  ): string {
    let resolved = path
    if (pathParams) {
      for (const [param, ref] of Object.entries(pathParams)) {
        const value = ref.startsWith('$')
          ? capturedValues.value[ref.slice(1)] || ref
          : ref
        resolved = resolved.replace(`{${param}}`, encodeURIComponent(value))
      }
    }
    // Also resolve any remaining $variables in the path
    resolved = resolved.replace(/\$(\w+)/g, (_, key) =>
      capturedValues.value[key] !== undefined ? String(capturedValues.value[key]) : `$${key}`
    )
    return resolved
  }

  function resolveBody(
    body: Record<string, any> | null | undefined,
    dynamicFields?: DynamicBodyField[]
  ): any {
    if (!body) return null
    const resolved = JSON.parse(JSON.stringify(body)) // Deep clone

    // Replace $variable strings in values
    resolveObjectVariables(resolved)

    // Apply dynamic field overrides
    if (dynamicFields) {
      for (const field of dynamicFields) {
        const value = capturedValues.value[field.capturedKey]
        if (value !== undefined) {
          setNestedValue(resolved, field.jsonPath, value)
        }
      }
    }

    return resolved
  }

  function resolveObjectVariables(obj: any): void {
    if (!obj || typeof obj !== 'object') return
    for (const key of Object.keys(obj)) {
      if (typeof obj[key] === 'string' && obj[key].startsWith('$')) {
        const capturedKey = obj[key].slice(1)
        if (capturedValues.value[capturedKey] !== undefined) {
          obj[key] = capturedValues.value[capturedKey]
        }
      } else if (typeof obj[key] === 'object' && obj[key] !== null) {
        resolveObjectVariables(obj[key])
      }
    }
  }

  // --- Helpers ---

  function getNestedValue(obj: any, path: string): any {
    return path.split('.').reduce((acc, key) => {
      if (acc == null) return undefined
      // Support numeric array indices: "peers.0.id" → acc[0]
      const index = Number(key)
      return Number.isInteger(index) ? acc[index] : acc[key]
    }, obj)
  }

  function setNestedValue(obj: any, path: string, value: any): void {
    const keys = path.split('.')
    const last = keys.pop()!
    const target = keys.reduce((acc, key) => {
      if (acc[key] === undefined) acc[key] = {}
      return acc[key]
    }, obj)
    target[last] = value
  }

  // --- Persistence ---

  function saveProgress(): void {
    if (!activeTrack.value) return
    try {
      const allProgress = loadAllProgress()
      const existing = allProgress[activeTrack.value.id]
      const isNowComplete = activeTrack.value.steps.every(s => completedStepIds.value.has(s.id))
      allProgress[activeTrack.value.id] = {
        trackId: activeTrack.value.id,
        completedStepIds: Array.from(completedStepIds.value),
        capturedValues: { ...capturedValues.value },
        lastStepIndex: currentStepIndex.value,
        savedAt: new Date().toISOString(),
        firstStepAt: existing?.firstStepAt || new Date().toISOString(),
        completedAt: isNowComplete ? (existing?.completedAt || new Date().toISOString()) : existing?.completedAt
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(allProgress))
    } catch (e) {
      log.warn('Failed to save tutorial progress:', e)
    }
  }

  function loadProgress(trackId: string): SavedTrackProgress | null {
    const all = loadAllProgress()
    return all[trackId] || null
  }

  function loadAllProgress(): Record<string, SavedTrackProgress> {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    } catch {
      return {}
    }
  }

  function resetTrack(): void {
    if (!activeTrack.value) return
    completedStepIds.value = new Set()
    capturedValues.value = {}
    stepResults.value = {}
    currentStepIndex.value = 0

    try {
      const allProgress = loadAllProgress()
      delete allProgress[activeTrack.value.id]
      localStorage.setItem(STORAGE_KEY, JSON.stringify(allProgress))
    } catch (e) {
      log.warn('Failed to clear tutorial progress:', e)
    }
  }

  function resetAll(): void {
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch (e) {
      log.warn('Failed to clear all tutorial progress:', e)
    }
    completedStepIds.value = new Set()
    capturedValues.value = {}
    stepResults.value = {}
    currentStepIndex.value = 0
    activeTrack.value = null
  }

  /** the last check could not be read (null after an attempt): neither "on" nor "off" is known */
  const sandboxCheckFailed = ref(false)
  async function checkSandbox(): Promise<boolean | null> {
    sandboxHealthy.value = await tutorialApiService.checkSandboxHealth()
    sandboxCheckFailed.value = sandboxHealthy.value === null
    return sandboxHealthy.value
  }

  // f038: Record achievement on track completion (idempotent — backend deduplicates)
  async function recordAchievement(track: TutorialTrack): Promise<void> {
    const achievementType = achievementTypeFor(track.id)

    try {
      const { apiClient } = await import('@/services/api/client')
      const { useAuthStore } = await import('@/stores/auth')
      const authStore = useAuthStore()

      // Use the currently selected agent from the agent selector (top-right dropdown)
      // If no agent selected, record without payout — user can claim later via /claim-pending
      const agentDid = authStore.activeAgent?.did || undefined

      const result = await apiClient.post('/achievements/record', {
        achievement_type: achievementType,
        agent_did: agentDid,
        metadata: {
          track_id: track.id,
          track_name: track.title,
          steps_completed: track.steps.length,
          completed_at: new Date().toISOString(),
        }
      })
      const data = result.data || result
      import.meta.env.DEV && console.log(`[Achievement] ${data.status}: ${achievementType}${data.achievement?.payout_avt ? ' +' + data.achievement.payout_avt + ' units' : ''}`)

      // Check if all tutorials complete → award master achievement (every track the hub lists)
      const allProgress = loadAllProgress()
      const allTrackIds = allTracks.map(t => t.id)
      const allComplete = allTrackIds.every(id => {
        const p = allProgress[id]
        return p && p.completedAt
      })
      if (allComplete) {
        await apiClient.post('/achievements/record', {
          achievement_type: 'all_tutorials_complete',
          agent_did: agentDid,
          metadata: { completed_at: new Date().toISOString() }
        })
        log.info('ALL TUTORIALS COMPLETE — Protocol Master!')
      }
    } catch (e) {
      log.warn('[Achievement] Failed to record (non-blocking):', e)
    }
  }

  return {
    // State
    activeTrack, currentStepIndex, completedStepIds,
    capturedValues, stepResults, isExecuting, sandboxHealthy, sandboxCheckFailed,
    // Computed
    currentStep, totalSteps, completedCount, progressPercent,
    canExecuteCurrentStep, canAdvance, isTrackComplete,
    // Actions
    loadTrack, goToStep, nextStep, previousStep,
    executeCurrentStep, resetTrack, resetAll, checkSandbox,
    // Utilities (exposed for hub)
    loadAllProgress
  }
})
