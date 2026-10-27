// ============================================================================
// TheProtocol Tutorial System — API Service
// Wraps the NEW /admin/tutorial/execute endpoint (NOT admin_api_test.py)
// ============================================================================

import { apiClient } from '@/services/api/client'
import type { ApiCallDefinition } from '../types/tutorial.types'

interface ProxyResponse {
  status_code: number
  response: any
  response_time: number
  error?: string | null
}

class TutorialApiService {
  private readonly PROXY_ENDPOINT = '/admin/tutorial/execute'
  private readonly HEALTH_ENDPOINT = '/admin/tutorial/health'
  private readonly SANDBOX_DISPLAY_BASE = 'http://registry-test:8000'

  /**
   * Execute a tutorial API call through the dedicated sandbox proxy.
   *
   * IMPORTANT: The production developer JWT authenticates the user to ACCESS
   * this endpoint (handled automatically by apiClient's interceptor).
   * The auth_token parameter is the SANDBOX token forwarded to registry-test.
   * These are two completely different auth contexts.
   */
  async executeStep(
    apiCall: ApiCallDefinition,
    resolvedBody: any | null,
    resolvedPath: string,
    sandboxAuthToken: string | null,
    sandboxAuthType: string
  ): Promise<{
    statusCode: number
    body: any
    timeMs: number
    error?: string
  }> {
    const startTime = Date.now()

    try {
      const response = await apiClient.post(this.PROXY_ENDPOINT, {
        method: apiCall.method,
        path: resolvedPath,
        body: resolvedBody,
        auth_token: sandboxAuthToken,
        auth_type: sandboxAuthType
      }, {
        timeout: 30000
      })

      const data: ProxyResponse = response.data

      return {
        statusCode: data.status_code,
        body: data.response,
        timeMs: data.response_time || (Date.now() - startTime),
        error: data.error || undefined
      }
    } catch (err: any) {
      return {
        statusCode: err.response?.status || 0,
        body: err.response?.data || null,
        timeMs: Date.now() - startTime,
        error: err.message || 'Request failed'
      }
    }
  }

  /**
   * Build the display URL shown to the user (informational only).
   * Shows what the sandbox endpoint URL looks like.
   */
  buildDisplayUrl(path: string): string {
    return `${this.SANDBOX_DISPLAY_BASE}/api/v1${path}`
  }

  /**
   * Build the display headers shown to the user (informational only).
   * Shows what headers the sandbox call uses.
   */
  buildDisplayHeaders(
    authType: string,
    tokenValue?: string,
    isFormEncoded?: boolean,
    extraHeaders?: Record<string, string>
  ): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': isFormEncoded
        ? 'application/x-www-form-urlencoded'
        : 'application/json'
    }

    if (authType === 'developer' || authType === 'admin' || authType === 'agent') {
      headers['Authorization'] = `Bearer ${this.maskToken(tokenValue)}`
    } else if (authType === 'bootstrap') {
      headers['Bootstrap-Token'] = this.maskToken(tokenValue)
    }

    if (extraHeaders) {
      Object.assign(headers, extraHeaders)
    }

    return headers
  }

  private maskToken(token?: string): string {
    if (!token) return '<pending>'
    if (token.length <= 20) return token
    return `${token.substring(0, 10)}...${token.substring(token.length - 6)}`
  }

  /**
   * Execute a DIRECT API call to a specific registry (bypasses proxy).
   * Used for dual-registry scenarios (e.g., Track 4 Federation calls to registry-test-b).
   *
   * This does NOT go through apiClient (no production JWT interceptor).
   * The sandbox auth token is sent directly as a Bearer/Bootstrap-Token header.
   */
  async executeDirectCall(
    method: string,
    targetBase: string,
    resolvedPath: string,
    resolvedBody: any | null,
    sandboxAuthToken: string | null,
    sandboxAuthType: string,
    formEncoded: boolean = false
  ): Promise<{
    statusCode: number
    body: any
    timeMs: number
    error?: string
  }> {
    const startTime = Date.now()
    const url = `${targetBase}/api/v1${resolvedPath}`

    const headers: Record<string, string> = {}
    if (formEncoded) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded'
    } else {
      headers['Content-Type'] = 'application/json'
    }

    // Set auth header
    if ((sandboxAuthType === 'developer' || sandboxAuthType === 'admin' || sandboxAuthType === 'agent') && sandboxAuthToken) {
      headers['Authorization'] = `Bearer ${sandboxAuthToken}`
    } else if (sandboxAuthType === 'bootstrap' && sandboxAuthToken) {
      headers['Bootstrap-Token'] = sandboxAuthToken
    }

    try {
      const fetchOptions: RequestInit = {
        method: method.toUpperCase(),
        headers
      }

      if (method.toUpperCase() !== 'GET' && method.toUpperCase() !== 'DELETE') {
        if (formEncoded && resolvedBody) {
          fetchOptions.body = new URLSearchParams(resolvedBody as Record<string, string>).toString()
        } else if (resolvedBody !== null && resolvedBody !== undefined) {
          fetchOptions.body = JSON.stringify(resolvedBody)
        }
      }

      const response = await fetch(url, fetchOptions)
      const elapsed = Date.now() - startTime

      let responseBody: any
      try {
        responseBody = await response.json()
      } catch {
        responseBody = await response.text().catch(() => null)
      }

      return {
        statusCode: response.status,
        body: responseBody,
        timeMs: elapsed,
        error: undefined
      }
    } catch (err: any) {
      return {
        statusCode: 0,
        body: null,
        timeMs: Date.now() - startTime,
        error: err.message || 'Direct call failed'
      }
    }
  }

  /**
   * Build the display URL for a direct call (shows targetBase instead of default sandbox).
   */
  buildDirectDisplayUrl(targetBase: string, path: string): string {
    return `${targetBase}/api/v1${path}`
  }

  /**
   * Generate a real UltraHonk proof (Noir + Barretenberg) for a tutorial circuit.
   * Runs nargo execute + bb prove on the server, with a random salt and a random
   * label, and answers with the proof as base64.
   *
   * `agentDid` is the agent that will submit the proof: its reference is derived
   * from that DID and the label (public_inputs.reference_label), and
   * /attestations/submit does not verify it for any other agent.
   *
   * Available circuits (the v1.0.0 ids are answered with the v2.0.0 proof):
   * - "fairMarkupPolicy/v2.0.0"
   * - "accurateResourceUsagePolicy/v2.0.0"
   * - "fairCrossRegistryFee/v2.0.0"
   * - "contentSafetyAttestation/v2.0.0"
   *
   * Submit `circuit_id` and `public_inputs` (reference_label included) from this
   * answer as they are, with that agent's token: the registry compares every
   * stated public input with the value the proof carries.
   */
  async generateZkpProof(circuitId: string, agentDid: string): Promise<{
    circuit_id: string
    proof_bytes_base64: string
    /** the public inputs as decimal strings, and reference_label */
    public_inputs: Record<string, string>
    /** the commitment the circuit outputs, as a decimal string */
    public_outputs: Record<string, string>
    generation_time_ms: number
  }> {
    const response = await apiClient.post('/admin/tutorial/generate-proof', {
      circuit_id: circuitId,
      agent_did: agentDid
    }, { timeout: 180000 })  // 3 min: proving is slow, and the server proves two at a time
    return response.data
  }

  /**
   * Health check — verify sandbox is reachable.
   * Uses the production JWT automatically via apiClient interceptor.
   */
  /** true = the sandbox tier answers healthy; false = it answered "not healthy", or this registry serves no sandbox tier
   *  (404); null = the check itself failed (§FESUITE, 2026-10-04: a failed check said "switched off on this registry") */
  async checkSandboxHealth(): Promise<boolean | null> {
    try {
      const response = await apiClient.get(this.HEALTH_ENDPOINT, { timeout: 5000 })
      return response.data?.healthy === true
    } catch (e: any) {
      return e?.response?.status === 404 ? false : null
    }
  }
}

export const tutorialApiService = new TutorialApiService()
