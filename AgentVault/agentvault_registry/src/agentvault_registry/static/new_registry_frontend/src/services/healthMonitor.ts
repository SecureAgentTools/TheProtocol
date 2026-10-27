import { apiClient } from './api/client'

export interface EndpointHealth {
  method: string
  path: string
  healthy: boolean
  status_code: number
  response_time: number
  error?: string
  history?: number[] // Historical health data (0-1 values)
}

export interface GroupSummary {
  total: number
  healthy: number
  unhealthy: number
  percentage: number
}

export interface HealthData {
  summary: {
    total: number
    healthy: number
    unhealthy: number
    percentage: number
  }
  groupSummaries: Record<string, GroupSummary>
  results: Record<string, EndpointHealth[]>
  timestamp: string
}

class HealthMonitorService {
  async checkHealth(tokens?: { developer_token?: string; agent_token?: string }): Promise<any> {
    try {
      // Pass tokens in request body for backend to use when testing endpoints
      // Use extra long timeout for slow systems (10 minutes)
      // Note: Backend expects flat structure, not nested in 'tokens' field
      const response = await apiClient.post('/admin/health-check', tokens || {}, {
        timeout: 600000  // 10 minutes
      })
      return response.data
    } catch (error) {
      console.error('Failed to check health:', error)
      throw error
    }
  }
  
  async checkEndpointHealth(endpoint: string): Promise<EndpointHealth> {
    try {
      const response = await apiClient.get(`/health/endpoint/${encodeURIComponent(endpoint)}`, {
        timeout: 300000  // 5 minutes for slow systems
      })
      return response.data
    } catch (error) {
      console.error('Failed to check endpoint health:', error)
      throw error
    }
  }
  
  // Add method for GET health check
  async getHealthCheck(): Promise<any> {
    try {
      const response = await apiClient.get('/admin/health-check', {
        timeout: 600000  // 10 minutes for comprehensive health check
      })
      return response.data
    } catch (error) {
      console.error('Failed to get health check:', error)
      throw error
    }
  }
  
  async getHealthHistory(timeRange: '1h' | '24h' | '7d' = '24h'): Promise<{
    timeline: string[]
    data: Record<string, number[]>
  }> {
    try {
      const response = await apiClient.get('/health/history', {
        params: { range: timeRange }
      })
      return response.data
    } catch (error) {
      console.error('Failed to fetch health history:', error)
      throw error
    }
  }
  
  async runHealthCheck(): Promise<HealthData> {
    try {
      const response = await apiClient.post('/health/run-check')
      return response.data
    } catch (error) {
      console.error('Failed to run health check:', error)
      throw error
    }
  }
}

export const healthMonitorService = new HealthMonitorService()
