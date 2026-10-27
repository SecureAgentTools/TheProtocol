import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { webhookService, type Webhook, type WebhookDelivery, type CreateWebhookRequest, type UpdateWebhookRequest, type DeliveryStatusFilter } from '@/services/api/webhookService'
import { useUIStore } from './ui'

export const useWebhookStore = defineStore('webhooks', () => {
  // State
  const webhooks = ref<Webhook[]>([])
  // §FESUITE (the failing-reads census, 2026-10-04): the list's last read failed and nothing was read (the manager then
  // says so; it said "NO WEBHOOKS FOUND")
  const listFailed = ref(false)
  const selectedWebhook = ref<Webhook | null>(null)
  const deliveries = ref<WebhookDelivery[]>([])
  const isLoading = ref(false)
  const isLoadingDeliveries = ref(false)
  const filters = ref({
    search: '',
    activeOnly: false,
    eventType: ''
  })

  // Computed
  const filteredWebhooks = computed(() => {
    let result = [...webhooks.value]

    // Apply search filter
    if (filters.value.search) {
      const search = filters.value.search.toLowerCase()
      result = result.filter(w => 
        w.url.toLowerCase().includes(search) ||
        w.events.some(e => e.toLowerCase().includes(search))
      )
    }

    // Apply active filter
    if (filters.value.activeOnly) {
      result = result.filter(w => w.is_active)
    }

    // Apply event type filter
    if (filters.value.eventType) {
      result = result.filter(w => 
        w.events.includes(filters.value.eventType)
      )
    }

    // Sort by created_at descending (newest first)
    result.sort((a, b) => 
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )

    return result
  })

  const activeWebhooks = computed(() => {
    return webhooks.value.filter(w => w.is_active)
  })

  const inactiveWebhooks = computed(() => {
    return webhooks.value.filter(w => !w.is_active)
  })

  const webhookStats = computed(() => {
    const total = webhooks.value.length
    const active = activeWebhooks.value.length
    const totalDeliveries = webhooks.value.reduce((sum, w) => {
      // We'd need a delivery count from backend for accurate stats
      return sum
    }, 0)
    const failedWebhooks = webhooks.value.filter(w => (w.failure_count || 0) > 0).length

    return {
      total,
      active,
      inactive: total - active,
      totalDeliveries,
      failedWebhooks
    }
  })

  // Actions
  async function fetchWebhooks() {
    isLoading.value = true
    try {
      webhooks.value = await webhookService.listWebhooks()
      listFailed.value = false
    } catch (error: any) {
      listFailed.value = !webhooks.value.length
      const uiStore = useUIStore()
      uiStore.showError('Failed to fetch webhooks', error.message || 'Unknown error')
      console.error('Failed to fetch webhooks:', error)
    } finally {
      isLoading.value = false
    }
  }

  async function createWebhook(data: CreateWebhookRequest) {
    const uiStore = useUIStore()
    isLoading.value = true
    
    try {
      const webhook = await webhookService.createWebhook(data)
      webhooks.value.unshift(webhook)
      // Secret is surfaced by the modal — no toast here to avoid duplicating it
      return webhook
    } catch (error: any) {
      uiStore.showError('Failed to create webhook', error.message || 'Unknown error')
      throw error
    } finally {
      isLoading.value = false
    }
  }

  async function updateWebhook(id: string, data: UpdateWebhookRequest) {
    const uiStore = useUIStore()
    isLoading.value = true
    
    try {
      const updatedWebhook = await webhookService.updateWebhook(id, data)
      
      // Update in list
      const index = webhooks.value.findIndex(w => w.id === id)
      if (index !== -1) {
        webhooks.value[index] = updatedWebhook
      }
      
      // Update selected if it's the same
      if (selectedWebhook.value?.id === id) {
        selectedWebhook.value = updatedWebhook
      }
      
      uiStore.showSuccess('Webhook Updated', 'Webhook has been updated successfully')
      return updatedWebhook
    } catch (error: any) {
      uiStore.showError('Failed to update webhook', error.message || 'Unknown error')
      throw error
    } finally {
      isLoading.value = false
    }
  }

  async function deleteWebhook(id: string) {
    const uiStore = useUIStore()
    isLoading.value = true
    
    try {
      await webhookService.deleteWebhook(id)
      
      // Remove from list
      webhooks.value = webhooks.value.filter(w => w.id !== id)
      
      // Clear selected if it was deleted
      if (selectedWebhook.value?.id === id) {
        selectedWebhook.value = null
        deliveries.value = []
      }
      
      uiStore.showSuccess('Webhook Deleted', 'Webhook has been deleted successfully')
    } catch (error: any) {
      uiStore.showError('Failed to delete webhook', error.message || 'Unknown error')
      throw error
    } finally {
      isLoading.value = false
    }
  }

  async function testWebhook(id: string) {
    const uiStore = useUIStore()
    
    try {
      const result = await webhookService.testWebhook(id)
      
      if (result.success) {
        uiStore.showSuccess('Test Successful', `Delivery sent — status ${result.status ?? 'pending'}`)
      } else {
        uiStore.showWarning('Test Failed', result.error || 'Endpoint unreachable')
      }
      
      // Refresh list to pick up updated last_triggered_at (no single-GET endpoint exists)
      await fetchWebhooks()
      
      return result
    } catch (error: any) {
      uiStore.showError('Test Failed', error.message || 'Failed to test webhook')
      throw error
    }
  }

  // Build #1 (2026-05-07): per-fetch error ref so the modal can show inline
  // retry instead of (or alongside) the toast. Persists across the modal
  // session until next fetch attempt clears it.
  const deliveriesError = ref<string | null>(null)

  // §COCKPITDESK (2026-10-15): the latest read owns the deliveries. Opening endpoint A's deliveries and then B's let A's
  // answer land after B's: A's deliveries, and A as the selected endpoint, under B's drawer.
  let deliveriesSeq = 0
  async function fetchDeliveries(
    webhookId: string,
    limit = 20,
    offset = 0,
    statusFilter: DeliveryStatusFilter = null,
  ) {
    const seq = ++deliveriesSeq
    isLoadingDeliveries.value = true
    deliveriesError.value = null

    try {
      const result = await webhookService.getDeliveries(webhookId, limit, offset, statusFilter)
      if (seq !== deliveriesSeq) return
      deliveries.value = result.deliveries

      if (!selectedWebhook.value || selectedWebhook.value.id !== webhookId) {
        selectedWebhook.value = webhooks.value.find(w => w.id === webhookId) || null
      }
    } catch (error: any) {
      if (seq !== deliveriesSeq) return
      const uiStore = useUIStore()
      const msg = error?.response?.data?.detail || error?.message || 'Unknown error'
      deliveriesError.value = msg
      uiStore.showError('Failed to fetch deliveries', msg)
      console.error('Failed to fetch deliveries:', error)
    } finally {
      if (seq === deliveriesSeq) isLoadingDeliveries.value = false
    }
  }

  function selectWebhook(webhook: Webhook | null) {
    selectedWebhook.value = webhook
    if (!webhook) {
      deliveries.value = []
    }
  }

  function clearFilters() {
    filters.value = {
      search: '',
      activeOnly: false,
      eventType: ''
    }
  }

  function toggleWebhookStatus(id: string) {
    const webhook = webhooks.value.find(w => w.id === id)
    if (webhook) {
      return updateWebhook(id, { is_active: !webhook.is_active })
    }
  }

  // Clear state on logout
  function $reset() {
    webhooks.value = []
    listFailed.value = false
    selectedWebhook.value = null
    deliveries.value = []
    isLoading.value = false
    isLoadingDeliveries.value = false
    clearFilters()
  }

  return {
    // State
    webhooks,
    listFailed,
    selectedWebhook,
    deliveries,
    deliveriesError,
    isLoading,
    isLoadingDeliveries,
    filters,
    
    // Computed
    filteredWebhooks,
    activeWebhooks,
    inactiveWebhooks,
    webhookStats,
    
    // Actions
    fetchWebhooks,
    createWebhook,
    updateWebhook,
    deleteWebhook,
    testWebhook,
    fetchDeliveries,
    selectWebhook,
    clearFilters,
    toggleWebhookStatus,
    $reset
  }
})
