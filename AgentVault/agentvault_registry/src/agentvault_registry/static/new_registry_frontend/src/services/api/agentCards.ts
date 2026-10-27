// Agent Cards API Service
import { apiClient } from './client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('agentCardsApi')

export interface AgentCard {
  id: string
  hri?: string // Human readable ID
  name: string
  description: string
  emoji?: string
  type: 'trading' | 'analysis' | 'automation' | 'security' | 'data' | 'custom'
  status: 'active' | 'inactive' | 'draft'
  capabilities: string[]
  tags: string[]
  rating?: number
  success_rate?: number
  total_earnings?: number
  transactions?: number
  uptime?: number
  verified?: boolean
  creator_did?: string
  creator_name?: string
  is_owned?: boolean
  created_at: string
  updated_at: string
}

class AgentCardsAPI {
  // Helper method to extract array from response
  private extractCardsArray(data: any): any[] {
    // Check if response is already an array
    if (Array.isArray(data)) {
      return data
    }
    // Check for various property names that might contain the array
    if (data) {
      if (Array.isArray(data.cards)) return data.cards
      if (Array.isArray(data.items)) return data.items
      if (Array.isArray(data.results)) return data.results
      if (Array.isArray(data.agent_cards)) return data.agent_cards
      if (Array.isArray(data.data)) return data.data
      
      // Check if it's an object with numeric keys
      if (typeof data === 'object') {
        const keys = Object.keys(data)
        if (keys.length > 0 && keys.every(k => !isNaN(Number(k)))) {
          return Object.values(data)
        }
      }
    }
    
    log.warn('Could not extract cards array from response:', data)
    return []
  }

  // Get all public agent cards
  async getPublicCards(): Promise<AgentCard[]> {
    try {
      const response = await apiClient.get('/agent-cards')
      import.meta.env.DEV && console.log('Agent cards API response structure:', typeof response.data, Object.keys(response.data || {}).slice(0, 5))
      
      const cards = this.extractCardsArray(response.data)
      import.meta.env.DEV && console.log('Extracted', cards.length, 'agent cards')
      
      return cards.map((card: any) => this.transformCard(card))
    } catch (error: any) {
      console.error('Failed to fetch public cards:', error)
      if (error.response?.status === 404) {
        return [] // No cards found
      }
      throw error
    }
  }

  // Get owned agent cards
  async getOwnedCards(): Promise<AgentCard[]> {
    try {
      const response = await apiClient.get('/agent-cards', {
        params: { owned_only: true }
      })
      const cards = this.extractCardsArray(response.data)
      return cards.map((card: any) => this.transformCard(card))
    } catch (error: any) {
      console.error('Failed to fetch owned cards:', error)
      if (error.response?.status === 404) {
        return []
      }
      throw error
    }
  }

  // Search agent cards
  async searchCards(query: string): Promise<AgentCard[]> {
    try {
      const response = await apiClient.get('/agent-cards', {
        params: { search: query }
      })
      const cards = this.extractCardsArray(response.data)
      return cards.map((card: any) => this.transformCard(card))
    } catch (error: any) {
      console.error('Failed to search cards:', error)
      if (error.response?.status === 404) {
        return []
      }
      throw error
    }
  }

  // Get cards by tags
  async getCardsByTags(tags: string[]): Promise<AgentCard[]> {
    try {
      const response = await apiClient.get('/agent-cards', {
        params: { tags: tags.join(',') }
      })
      const cards = this.extractCardsArray(response.data)
      return cards.map((card: any) => this.transformCard(card))
    } catch (error: any) {
      console.error('Failed to fetch cards by tags:', error)
      if (error.response?.status === 404) {
        return []
      }
      throw error
    }
  }

  // Get specific card
  async getCard(cardId: string): Promise<AgentCard> {
    try {
      const response = await apiClient.get(`/agent-cards/${cardId}`)
      return this.transformCard(response.data)
    } catch (error: any) {
      console.error('Failed to fetch card:', error)
      throw error
    }
  }

  // Get card by HRI
  async getCardByHRI(hri: string): Promise<AgentCard> {
    try {
      const response = await apiClient.get(`/agent-cards/id/${hri}`)
      return this.transformCard(response.data)
    } catch (error: any) {
      console.error('Failed to fetch card by HRI:', error)
      throw error
    }
  }

  // Create agent card
  async createCard(data: Partial<AgentCard>): Promise<AgentCard> {
    try {
      const payload = {
        name: data.name,
        description: data.description,
        emoji: data.emoji || '🤖',
        type: data.type || 'custom',
        capabilities: data.capabilities || [],
        tags: data.tags || [],
        metadata: {
          rating: data.rating,
          success_rate: data.success_rate,
          verified: data.verified
        }
      }
      
      const response = await apiClient.post('/agent-cards/', payload)
      return this.transformCard(response.data)
    } catch (error: any) {
      console.error('Failed to create card:', error)
      throw error
    }
  }

  // Update agent card
  async updateCard(cardId: string, updates: Partial<AgentCard>): Promise<AgentCard> {
    try {
      const payload = {
        name: updates.name,
        description: updates.description,
        emoji: updates.emoji,
        type: updates.type,
        capabilities: updates.capabilities,
        tags: updates.tags,
        metadata: {
          rating: updates.rating,
          success_rate: updates.success_rate,
          verified: updates.verified
        }
      }
      
      const response = await apiClient.put(`/agent-cards/${cardId}`, payload)
      return this.transformCard(response.data)
    } catch (error: any) {
      console.error('Failed to update card:', error)
      throw error
    }
  }

  // Delete/Deactivate agent card
  async deleteCard(cardId: string): Promise<void> {
    try {
      await apiClient.delete(`/agent-cards/${cardId}`)
    } catch (error: any) {
      console.error('Failed to delete card:', error)
      throw error
    }
  }

  // Transform backend card to frontend format
  private transformCard(data: any): AgentCard {
    return {
      id: data.id || data.card_id,
      hri: data.hri || data.human_readable_id,
      name: data.name || data.agent_name || 'Unnamed Agent',
      description: data.description || data.agent_description || '',
      emoji: data.emoji || data.agent_emoji || '🤖',
      type: data.type || data.agent_type || 'custom',
      status: data.status || 'active',
      capabilities: data.capabilities || data.agent_capabilities || [],
      tags: data.tags || data.agent_tags || [],
      rating: data.rating || data.metadata?.rating || 0,
      success_rate: data.success_rate || data.metadata?.success_rate || 0,
      total_earnings: data.total_earnings || data.metadata?.total_earnings || 0,
      transactions: data.transactions || data.metadata?.transactions || 0,
      uptime: data.uptime || data.metadata?.uptime || 0,
      verified: data.verified || data.metadata?.verified || false,
      creator_did: data.creator_did || data.developer_did,
      creator_name: data.creator_name || data.developer_name,
      is_owned: data.is_owned || false,
      created_at: data.created_at || new Date().toISOString(),
      updated_at: data.updated_at || new Date().toISOString()
    }
  }
}

export const agentCardsApi = new AgentCardsAPI()
