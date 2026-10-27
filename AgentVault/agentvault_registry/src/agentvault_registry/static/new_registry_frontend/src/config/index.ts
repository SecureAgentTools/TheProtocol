// Application configuration
export const config = {
  api: {
    baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
    timeout: 300000, // 300 seconds (5 minutes) for very slow systems
    retryAttempts: 3,
    retryDelay: 1000
  },
  
  websocket: {
    url: import.meta.env.VITE_WEBSOCKET_URL || 'ws://localhost:8000/ws',
    reconnectInterval: 5000,
    maxReconnectAttempts: 10
  },
  
  app: {
    title: import.meta.env.VITE_APP_TITLE || 'Sovereign Registry',
    version: '1.0.0',
    environment: import.meta.env.MODE,
    env: import.meta.env.MODE // Add this for compatibility
  },
  
  auth: {
    tokenKey: 'sovereign_auth_token',
    refreshTokenKey: 'sovereign_refresh_token',
    userKey: 'sovereign_user'
  },
  
  features: {
    enableWebSockets: true,
    enableFederation: true,
    enableStaking: true,
    enableGovernance: true
  }
} as const

export type Config = typeof config
