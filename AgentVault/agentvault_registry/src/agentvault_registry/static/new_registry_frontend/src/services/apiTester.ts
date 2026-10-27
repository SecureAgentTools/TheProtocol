import { apiClient } from './api/client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('apiTesterService')

export interface EndpointTest {
  method: string
  path: string
  category: string
  description?: string
  auth_type?: string
  testing?: boolean
  result?: TestResult
  showResponse?: boolean
  timeElapsed?: number
  body?: any
  headers?: Record<string, string>
}

export interface TestResult {
  healthy: boolean
  status_code: number
  response_time: number
  error?: string
  response?: any
}

export interface TestSummary {
  total: number
  healthy: number
  unhealthy: number
  percentage: number
}

class ApiTesterService {
  async getAllEndpoints(): Promise<any> {
    try {
      const response = await apiClient.get('/admin/api-test/endpoints')
      return response.data
    } catch (error) {
      console.error('Failed to fetch endpoints:', error)
      throw error
    }
  }
  
  async testEndpoint(
    endpoint: EndpointTest, 
    developerToken: string, 
    agentToken: string,
    timeout: number = 120
  ): Promise<TestResult> {
    try {
      // Create abort controller for timeout
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeout * 1000)
      
      // Prepare request body based on endpoint method
      const requestBody = endpoint.method !== 'GET' && endpoint.method !== 'DELETE' ? 
        endpoint.body || {} : null
      
      const response = await apiClient.post('/admin/api-test/test-endpoint', {
        method: endpoint.method,
        path: endpoint.path,
        category: endpoint.category,
        body: requestBody,
        developer_token: developerToken,
        agent_token: agentToken
      }, {
        signal: controller.signal
      })
      
      clearTimeout(timeoutId)
      return response.data
    } catch (error: any) {
      if (error.name === 'AbortError') {
        return {
          healthy: false,
          status_code: 0,
          response_time: timeout * 1000,
          error: 'Request timed out'
        }
      }
      
      console.error('Test failed:', error)
      return {
        healthy: false,
        status_code: error.response?.status || 0,
        response_time: 0,
        error: error.message || 'Test failed'
      }
    }
  }
  
  async runAllTests(
    developerToken: string,
    agentToken: string,
    timeout: number = 120
  ): Promise<{ results: TestResult[]; summary: TestSummary }> {
    try {
      const response = await apiClient.post('/api-test/run-all', {
        developer_token: developerToken,
        agent_token: agentToken,
        timeout
      })
      return response.data
    } catch (error) {
      console.error('Failed to run all tests:', error)
      throw error
    }
  }

  // OWL29: Sandbox endpoints
  async getSandboxCredentials(): Promise<any> {
    try {
      const response = await apiClient.get('/admin/api-test/sandbox-credentials')
      return response.data
    } catch (error) {
      log.warn('Sandbox credentials not available:', error)
      return null
    }
  }

  async resetSandbox(): Promise<any> {
    const response = await apiClient.post('/admin/api-test/reset-sandbox')
    return response.data
  }

  // 2026-04-25 — Multi-frame scenarios (BFS / EigenTrust / Governance) are now
  // served via the standard flow framework (POST /admin/api-test/test-flow with
  // flow_name=multiframe_*_complete). The earlier dedicated tab + bespoke
  // endpoints were removed; the flow runner handles them automatically.
}

export const apiTesterService = new ApiTesterService()
