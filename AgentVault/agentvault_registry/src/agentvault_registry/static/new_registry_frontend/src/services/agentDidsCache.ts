/**
 * Agent DIDs Cache Service
 * Caches agent DIDs for a developer to avoid repeated fetches
 */

export interface CachedAgentData {
  did: string
  name?: string
  created_at?: string
  last_updated: string
}

class AgentDidsCache {
  private readonly STORAGE_KEY = 'agentvault_agent_dids_cache'
  private readonly CACHE_DURATION = 30 * 1000 // 30 seconds — was 5 min, too long when onboarding agents mid-session
  
  /**
   * Get cached agent DIDs for current developer
   */
  getCachedAgents(developerId?: string): CachedAgentData[] | null {
    try {
      const stored = localStorage.getItem(this.STORAGE_KEY)
      if (!stored) return null
      
      const cache = JSON.parse(stored)
      const key = developerId || 'default'
      
      if (!cache[key]) return null
      
      // Check if cache is still valid (24 hours)
      const cacheAge = Date.now() - new Date(cache[key].timestamp).getTime()
      if (cacheAge > this.CACHE_DURATION) {
        import.meta.env.DEV && console.log('Agent DIDs cache expired, will refresh')
        return null
      }
      
      import.meta.env.DEV && console.log(`Using cached agent DIDs (${cache[key].agents.length} agents)`)
      return cache[key].agents
    } catch (error) {
      console.error('Failed to load cached agent DIDs:', error)
      return null
    }
  }
  
  /**
   * Cache agent DIDs for current developer
   */
  cacheAgents(agents: any[], developerId?: string): void {
    try {
      const stored = localStorage.getItem(this.STORAGE_KEY)
      const cache = stored ? JSON.parse(stored) : {}
      const key = developerId || 'default'
      
      cache[key] = {
        timestamp: new Date().toISOString(),
        agents: agents.map(agent => ({
          did: agent.did,
          name: agent.name,
          created_at: agent.created_at,
          last_updated: new Date().toISOString()
        }))
      }
      
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(cache))
      import.meta.env.DEV && console.log(`Cached ${agents.length} agent DIDs`)
    } catch (error) {
      console.error('Failed to cache agent DIDs:', error)
    }
  }
  
  /**
   * Clear cache for a developer or all
   */
  clearCache(developerId?: string): void {
    try {
      if (developerId) {
        const stored = localStorage.getItem(this.STORAGE_KEY)
        if (stored) {
          const cache = JSON.parse(stored)
          delete cache[developerId]
          localStorage.setItem(this.STORAGE_KEY, JSON.stringify(cache))
        }
      } else {
        localStorage.removeItem(this.STORAGE_KEY)
      }
      import.meta.env.DEV && console.log('Cleared agent DIDs cache')
    } catch (error) {
      console.error('Failed to clear cache:', error)
    }
  }
  
  /**
   * Merge cached data with fresh agent data
   */
  mergeWithCache(freshAgents: any[], cachedAgents: CachedAgentData[] | null): any[] {
    if (!cachedAgents) return freshAgents
    
    // Create a map of cached agents for quick lookup
    const cacheMap = new Map(cachedAgents.map(a => [a.did, a]))
    
    // Merge fresh data with cached data
    return freshAgents.map(agent => {
      const cached = cacheMap.get(agent.did)
      if (cached) {
        return {
          ...cached,
          ...agent, // Fresh data takes precedence
          cached: true
        }
      }
      return agent
    })
  }
}

// Export singleton instance
export const agentDidsCache = new AgentDidsCache()
