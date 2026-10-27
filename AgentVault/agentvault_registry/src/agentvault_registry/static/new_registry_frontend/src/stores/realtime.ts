/**
 * Realtime Store
 * Manages real-time updates and WebSocket state
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { WebSocketEvents } from '@/services/websocket'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('RealtimeStore')

export interface RealtimeActivity {
  id: string
  type: 'agent.update' | 'transaction' | 'proposal' | 'staking' | 'federation' | 'system' | 'success' | 'error'
  title: string
  message: string
  data?: any
  timestamp: string
  read: boolean
}

export interface RealtimeMetrics {
  totalAgents: number
  activeAgents: number
  totalStaked: string
  totalRewards: string
  proposalsActive: number
  proposalsPassed: number
  federationPeers: number
  dailyTransactions: number
}

export const useRealtimeStore = defineStore('realtime', () => {
  // State
  const activities = ref<RealtimeActivity[]>([])
  const metrics = ref<RealtimeMetrics>({
    totalAgents: 0,
    activeAgents: 0,
    totalStaked: '0',
    totalRewards: '0',
    proposalsActive: 0,
    proposalsPassed: 0,
    federationPeers: 0,
    dailyTransactions: 0
  })
  const unreadCount = ref(0)
  const maxActivities = 100
  const eventHandlersSetup = ref(false)
  
  // WebSocket state
  const isConnected = ref(false)
  const isReconnecting = ref(false)
  const reconnectAttempts = ref(0)
  const lastError = ref<Error | null>(null)
  
  // WebSocket instance - will be set by external initialization
  let ws: any = null

  /* §S6 — THE "STORE HANDLER TO ADD LATER" TODO BELOW WAS NEVER IMPLEMENTED,
     AND IT FAILED SILENTLY.
     `on()` used to warn and return when `ws` was not set yet. `DashboardLayout`
     sets the instance inside an async block, so any view that subscribes during
     its own setup can lose that race — and lose it INVISIBLY, because the store
     reports the miss by doing nothing rather than by throwing. A caller cannot
     tell "subscribed" from "dropped on the floor"; I wrote a retry loop against
     this API that marked itself successful on the first attempt for exactly
     that reason, which is a check that cannot fail.
     Handlers are now recorded whether or not the instance exists, and attached
     when it arrives. `attached` keeps a second `setWebSocketInstance` from
     double-registering the same handler, which would double-fire every event. */
  const pendingHandlers: Array<{ event: string; handler: any; attached: boolean }> = []
  
  // Computed
  const recentActivities = computed(() => 
    activities.value.slice(0, 20)
  )
  
  const unreadActivities = computed(() => 
    activities.value.filter(a => !a.read)
  )
  
  const hasUnread = computed(() => 
    unreadCount.value > 0
  )
  
  // Set WebSocket instance (called externally to avoid circular deps)
  function setWebSocketInstance(websocket: any) {
    ws = websocket
    setupEventHandlers()

    // Attach everything that subscribed before the instance existed.
    for (const entry of pendingHandlers) {
      if (entry.attached) continue
      try { ws.on(entry.event, entry.handler); entry.attached = true } catch { /* keep for the next instance */ }
    }
    
    // Update state when WebSocket state changes
    if (ws && ws.isConnected) {
      // Subscribe to connection state changes
      isConnected.value = ws.isConnected.value || false
    }
  }
  
  // Actions
  async function connect() {
    if (ws && ws.connect) {
      return ws.connect()
    }
    import.meta.env.DEV && console.log('[RealtimeStore] WebSocket not initialized yet')
    return Promise.resolve()
  }
  
  function disconnect() {
    if (ws && ws.disconnect) {
      ws.disconnect()
    }
    isConnected.value = false
    isReconnecting.value = false
  }
  
  function addActivity(activity: Omit<RealtimeActivity, 'id' | 'timestamp' | 'read'>) {
    const newActivity: RealtimeActivity = {
      ...activity,
      id: generateId(),
      timestamp: new Date().toISOString(),
      read: false
    }
    
    // Add to beginning of array
    activities.value.unshift(newActivity)
    
    // Keep only max activities
    if (activities.value.length > maxActivities) {
      activities.value = activities.value.slice(0, maxActivities)
    }
    
    // Update unread count
    unreadCount.value++
  }
  
  function markAsRead(activityId: string) {
    const activity = activities.value.find(a => a.id === activityId)
    if (activity && !activity.read) {
      activity.read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }
  
  function markAllAsRead() {
    activities.value.forEach(activity => {
      activity.read = true
    })
    unreadCount.value = 0
  }
  
  function clearActivities() {
    activities.value = []
    unreadCount.value = 0
  }
  
  function updateMetrics(newMetrics: Partial<RealtimeMetrics>) {
    metrics.value = {
      ...metrics.value,
      ...newMetrics
    }
  }
  
  // Set up WebSocket event handlers
  function setupEventHandlers() {
    if (!ws || eventHandlersSetup.value) return
    
    try {
      // Agent events
      ws.on('agent.update', (data: any) => {
        addActivity({
          type: 'agent.update',
          title: 'Agent Updated',
          message: `Agent ${data.agent_id} has been updated`,
          data
        })
      })
      
      ws.on('agent.status', (data: any) => {
        addActivity({
          type: 'agent.update',
          title: 'Agent Status Changed',
          message: `Agent ${data.agent_id} is now ${data.status}`,
          data
        })
      })
      
      // Transaction events
      ws.on('transaction.update', (data: any) => {
        addActivity({
          type: 'transaction',
          title: 'Transaction Update',
          message: `Transaction ${data.transaction_id} is ${data.status}`,
          data
        })
      })
      
      // Proposal events
      ws.on('proposal.update', (data: any) => {
        addActivity({
          type: 'proposal',
          title: 'Proposal Update',
          message: `Proposal ${data.proposal_id} has been updated`,
          data
        })
      })
      
      // Lock events
      ws.on('staking.reward', (data: any) => {
        addActivity({
          type: 'staking',
          title: 'Payout on locked units',
          message: `You received ${data.amount} units as a payout on locked units`,
          data
        })
      })
      
      // Federation events
      ws.on('federation.sync', (data: any) => {
        addActivity({
          type: 'federation',
          title: 'Federation Sync',
          message: `Synced ${data.agents_synced} agents from ${data.registry_id}`,
          data
        })
      })
      
      // Metrics updates
      ws.on('metrics.update', (data: any) => {
        updateMetrics({
          totalAgents: data.total_agents,
          activeAgents: data.active_agents,
          totalStaked: data.total_staked,
          totalRewards: data.total_rewards,
          proposalsActive: data.proposals_active,
          proposalsPassed: data.proposals_passed,
          federationPeers: data.federation_peers,
          dailyTransactions: data.daily_transactions
        })
      })
      
      // Connection events
      ws.on('connected', () => {
        isConnected.value = true
        isReconnecting.value = false
        reconnectAttempts.value = 0
        import.meta.env.DEV && console.log('[RealtimeStore] WebSocket connected')
      })
      
      ws.on('disconnected', () => {
        isConnected.value = false
        import.meta.env.DEV && console.log('[RealtimeStore] WebSocket disconnected')
      })
      
      ws.on('reconnecting', (attempt: number) => {
        isReconnecting.value = true
        reconnectAttempts.value = attempt
      })
      
      ws.on('error', (error: Error) => {
        lastError.value = error
        console.error('[RealtimeStore] WebSocket error:', error)
      })
      
      eventHandlersSetup.value = true
      import.meta.env.DEV && console.log('[RealtimeStore] Event handlers setup successfully')
    } catch (error) {
      console.error('[RealtimeStore] Error setting up event handlers:', error)
    }
  }
  
  // Utility function to generate ID
  function generateId(): string {
    return Math.random().toString(36).substr(2, 9)
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout. Clears activity
  // feed + metrics counters; the WS connection itself is owned by
  // websocket.ts which has its own teardown.
  function $reset() {
    activities.value = []
    unreadCount.value = 0
    eventHandlersSetup.value = false
    isConnected.value = false
    isReconnecting.value = false
    reconnectAttempts.value = 0
    lastError.value = null
    metrics.value = {
      totalAgents: 0,
      activeAgents: 0,
      totalStaked: '0',
      totalRewards: '0',
      proposalsActive: 0,
      proposalsPassed: 0,
      federationPeers: 0,
      dailyTransactions: 0,
    }
  }

  return {
    // WebSocket state
    isConnected: computed(() => isConnected.value),
    isReconnecting: computed(() => isReconnecting.value),
    reconnectAttempts: computed(() => reconnectAttempts.value),
    lastError: computed(() => lastError.value),

    // Activity state
    activities,
    recentActivities,
    unreadActivities,
    unreadCount,
    hasUnread,
    $reset,
    
    // Metrics
    metrics,
    
    // WebSocket methods
    setWebSocketInstance, // NEW: Allow external initialization
    connect,
    disconnect,
    send: (type: string, data: any) => {
      if (ws && ws.send) {
        ws.send(type, data)
      } else {
        log.warn('WebSocket not ready, cannot send message')
      }
    },
    on: <K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]) => {
      const entry = { event: event as string, handler, attached: false }
      pendingHandlers.push(entry)
      if (ws && ws.on) {
        ws.on(event, handler)
        entry.attached = true
      }
      // No warn on the miss: it is no longer a miss. The handler is held and
      // attached the moment `setWebSocketInstance` runs.
    },
    off: <K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]) => {
      const i = pendingHandlers.findIndex(e => e.event === (event as string) && e.handler === handler)
      if (i >= 0) pendingHandlers.splice(i, 1)
      if (ws && ws.off) {
        ws.off(event, handler)
      }
    },
    
    // Activity methods
    addActivity,
    markAsRead,
    markAllAsRead,
    clearActivities,
    updateMetrics
  }
})
