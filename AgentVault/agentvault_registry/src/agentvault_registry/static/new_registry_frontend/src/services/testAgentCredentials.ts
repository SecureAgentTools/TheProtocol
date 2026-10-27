// Test agent credentials helper - OWL24 cleaned version
// Use console helpers to add credentials at runtime:
//   window.addAgentCredentials(did, clientId, clientSecret, name)
//   window.clearAgentCache()
//   window.viewStoredCredentials()

export const TEST_AGENT_CREDENTIALS: any[] = []
// Agents are now created dynamically via the onboarding flow.
// No hardcoded credentials.

export function storeTestCredentials() {
  // No-op: credentials should be added via UI or console helpers
  import.meta.env.DEV && console.log('[storeTestCredentials] No-op -- use window.addAgentCredentials() instead')
}

// Console helpers — development only (not exposed in production builds)
if (typeof window !== 'undefined' && import.meta.env.DEV) {
  (window as any).addAgentCredentials = (did: string, clientId: string, clientSecret: string, name?: string) => {
    const existing = window.localStorage.getItem('agentvault_agent_credentials')
    const store = existing ? JSON.parse(existing) : {}
    store[did] = {
      did,
      client_id: clientId,
      client_secret: clientSecret,
      name: name || 'Manual Agent',
      created_at: new Date().toISOString()
    }
    window.localStorage.setItem('agentvault_agent_credentials', JSON.stringify(store))
    import.meta.env.DEV && console.log(`Stored credentials for ${name || did}`)
    import.meta.env.DEV && console.log('Refresh the page to see the changes')
  }

  (window as any).clearAgentCache = () => {
    window.localStorage.removeItem('agentvault_agent_dids_cache')
    window.localStorage.removeItem('agentvault_agent_credentials')
    window.localStorage.removeItem('activeAgentId')
    import.meta.env.DEV && console.log('All agent caches cleared. Refresh to see changes.')
  }

  (window as any).viewStoredCredentials = () => {
    const creds = window.localStorage.getItem('agentvault_agent_credentials')
    if (creds) {
      const parsed = JSON.parse(creds)
      import.meta.env.DEV && console.log('Stored Agent Credentials:')
      Object.values(parsed).forEach((agent: any) => {
        import.meta.env.DEV && console.log(`  ${agent.name || 'Unnamed'} (${agent.did})`)
      })
      import.meta.env.DEV && console.log('Total:', Object.keys(parsed).length)
    } else {
      import.meta.env.DEV && console.log('No stored credentials found')
    }
  }
}
